"""Production PRISM Slow Path over Operon's real supervisor/specialist reasoning (Stage 2).

The adapter connects a PRISM revision to the existing reasoning lifecycle without
duplicating it and without letting reasoning mutate canonical state on its own::

    operator instruction (revision N)
      -> bounded reasoning question (current instruction + prior canonical context only)
      -> CLAIM     PromotionService.start_run            fenced transaction (prism_effect claim:{run})
      -> COMPUTE   ReasoningBackend.supervise            real supervisor/specialists, evidence-only writes
      -> CANDIDATE SupervisorResult -> SlowPathResult    no canonical write yet
      -> FENCE     PrismRepository.commit_result         BEGIN IMMEDIATE, fencing.decide inside
      -> APPLY     PromotionService._complete_run + settle   inside that same transaction, once
         or STALE  result kept on the PRISM run as history; the incident is untouched

The claim, the report and the settlement all execute through connection-injected
promotion/repository seams, so a revision that was superseded between the fence
decision and the write cannot exist: both happen under one SQLite ``BEGIN IMMEDIATE``
over the database the incident tables share. Cancellation is propagated as far as
the supervisor allows (task cancel, token checkpoints, tool-boundary checkpoint);
it is never relied on for correctness.

No vendor SDK is imported here. The reasoning backend comes from a factory that
resolves the Stage 0 registry with the semantic role ``slow``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import os
import time
from typing import Any

from core import db
from core.reliability import models as m
from core.reliability.repository import content_hash

from .cancellation import CancelledByRuntime
from .fencing import StaleRevisionError
from .models import ROLE_SLOW, SlowPathResult
from .slow_path import SlowPathExecution, SlowPathUnavailable

logger = logging.getLogger(__name__)

IMPLEMENTATION = "operon.prism.slow-path.operon-v1"
MAX_INSTRUCTION_CHARS = 1400
MAX_PRIOR_CONTEXT_CHARS = 400
MAX_QUESTION_CHARS = 2000
DEFAULT_MAX_PASSES = 2
STAGE_QUESTION = ("Assess competing mechanisms against the operator instruction above and explicitly review "
                  "the selected diagnostic assessment.")
PROVENANCE_MAP = {"LIVE": "LIVE", "INJECTED": "INJECTED", "SIMULATED": "SIMULATED"}


def compose_question(instruction: str, revision: int, prior: dict | None) -> tuple[str, dict]:
    """The bounded reasoning question: the current instruction is authoritative; only the last
    canonical result (an earlier revision's committed summary) is carried as context.
    Superseded instructions are never included, so they cannot remain authoritative."""
    text = " ".join(instruction.split())[:MAX_INSTRUCTION_CHARS]
    parts = [f"Operator instruction (PRISM revision {revision}, authoritative): {text}"]
    prior_revision = None
    if prior and prior.get("canonical_summary") and prior.get("canonical_revision"):
        prior_revision = int(prior["canonical_revision"])
        summary = " ".join(str(prior["canonical_summary"]).split())[:MAX_PRIOR_CONTEXT_CHARS]
        parts.append(f"Prior canonical context (revision {prior_revision}; the instruction above overrides it "
                     f"wherever they conflict): {summary}")
    parts.append(STAGE_QUESTION)
    question = "\n".join(parts)[:MAX_QUESTION_CHARS]
    metadata = {"revision": revision, "instruction_chars": len(text), "instruction_hash": content_hash(text),
                "prior_canonical_revision": prior_revision, "question_chars": len(question),
                "context_policy": "current_instruction+last_canonical_summary"}
    return question, metadata


def _hypotheses(result, key) -> list[dict]:
    if not key:
        return []
    assessment = next((item.assessment for item in result.assessments if item.key == key), None)
    if assessment is None or not hasattr(assessment, "competing_hypotheses"):
        return []
    return [{"key": h.key, "mechanism": h.mechanism[:300], "confidence": h.confidence,
             "recommended": h.key == assessment.recommended_hypothesis,
             "supporting_evidence_ids": list(h.supporting_evidence_ids),
             "contradicting_evidence_ids": list(h.contradicting_evidence_ids)}
            for h in assessment.competing_hypotheses]


def _plan(result) -> list[dict]:
    key = result.maintenance_plan_key
    if not key:
        return []
    plan = next((item.assessment for item in result.assessments if item.key == key), None)
    if plan is None or not hasattr(plan, "proposed_steps"):
        return []
    return [{"description": step.description[:300], "equipment_ids": list(step.equipment_ids),
             "preconditions": list(step.preconditions)[:5]} for step in plan.proposed_steps[:10]]


def next_step(result) -> str:
    needs = [f"{n.capability}: {n.question}" for n in result.unresolved_evidence_needs[:3]]
    if result.termination_reason != "MODEL_COMPLETED":
        return f"Reasoning ended with {result.termination_reason}; human review of the run is required."
    if result.disposition == "ADVISORY_CONCLUSION":
        return ("Advisory conclusion reached; Operon's application gates decide promotion "
                "(trusted technical confirmation required before a diagnosis becomes authoritative).")
    if result.disposition == "NEEDS_EVIDENCE" or needs:
        return "Evidence needed before a conclusion: " + ("; ".join(needs) if needs else "see unresolved needs.")
    if result.disposition in {"BLOCKED", "ESCALATED"}:
        return "Blocked: " + "; ".join(result.blockers[:2]) if result.blockers else "Blocked; human review required."
    return "Unresolved: " + ("; ".join(result.blockers[:2]) if result.blockers else "human review required.")


class OperonSlowPathAdapter:
    """PRISM Slow Path adapter around the real Operon reasoning stack (compute before commit)."""
    name = "operon"

    def __init__(self, *, incident_repository, backend_factory: Callable[[], Any], lifecycle=None, promotion=None,
                 evidence_service=None, busy: Callable[[str], str | None] | None = None, cooperative: bool = True,
                 hold_seconds: float = 0.0, max_passes: int = DEFAULT_MAX_PASSES, bounds=None, role: str = ROLE_SLOW):
        from core.reliability.evidence import EvidenceService
        from core.reliability.lifecycle import LifecycleService
        from core.reliability.promotion import PromotionService
        self.repository = incident_repository
        self.backend_factory = backend_factory
        self.lifecycle = lifecycle or LifecycleService(incident_repository)
        self.promotion = promotion or PromotionService(incident_repository)
        self.evidence_service = evidence_service or EvidenceService(incident_repository)
        self.busy = busy
        self.cooperative = bool(cooperative)
        self.hold_seconds = max(0.0, float(hold_seconds))
        self.max_passes = max(1, int(max_passes))
        self.bounds = bounds
        self.role = role

    # ---- identity ---------------------------------------------------------------------
    @property
    def cancellable(self) -> bool:
        return self.cooperative

    def _backend(self):
        try:
            backend = self.backend_factory()
        except SlowPathUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - reported as a structured unavailability
            raise SlowPathUnavailable(f"{type(exc).__name__}: {exc}"[:300], code="provider_not_configured") from exc
        if backend is None:
            raise SlowPathUnavailable("no reasoning backend is configured for the PRISM slow role",
                                      code="provider_not_configured")
        return backend

    @staticmethod
    def describe(backend) -> dict:
        from core.reasoning.provenance import describe_backend
        description = describe_backend(backend)
        if description.get("provenance") is None:
            identity = backend.identity() if hasattr(backend, "identity") else {}
            for key in ("provider", "model", "provenance", "live_model", "implementation"):
                if identity.get(key) is not None:
                    description[key] = identity[key]
            name = getattr(backend, "name", description.get("backend"))
            description["backend"] = name
            description["runtime"] = f"{name} reasoning backend (injected)"
        return description

    def identity(self) -> dict:
        base = {"adapter": self.name, "role": self.role, "implementation": IMPLEMENTATION,
                "cancellable": self.cancellable, "hold_seconds": self.hold_seconds, "max_passes": self.max_passes}
        try:
            backend = self._backend()
        except SlowPathUnavailable as exc:
            return {**base, "backend": None, "provider": "none", "model": None, "live_model": False,
                    "provenance": None, "unavailable_reason": str(exc)}
        description = self.describe(backend)
        return {**base, "backend": description.get("backend"), "runtime": description.get("runtime"),
                "framework": description.get("framework"), "provider": description.get("provider") or "none",
                "model": description.get("model"), "live_model": bool(description.get("live_model")),
                "provenance": description.get("provenance"), "locality": description.get("locality")}

    # ---- helpers -------------------------------------------------------------------------
    def _checkpoint(self, execution: SlowPathExecution) -> None:
        """Cooperative cancellation checkpoint; a deliberately non-cooperative worker skips it."""
        if self.cooperative:
            execution.check_cancelled()

    async def _wait_while_busy(self, execution: SlowPathExecution, incident_id: str) -> None:
        if self.busy is None:
            return
        reported = None
        while True:
            reason = self.busy(incident_id)
            if not reason:
                return
            remaining = execution.remaining_seconds()
            if remaining is not None and remaining <= 0:
                raise SlowPathUnavailable(f"incident busy until the deadline: {reason}", code="incident_busy")
            if reason != reported:
                await execution.report(stage="waiting_for_incident", reason=reason)
                reported = reason
            if self.cooperative:
                await execution.cancellation.sleep(0.25)
            else:
                await asyncio.sleep(0.25)

    def _stale_reasons(self, snapshot) -> list[str]:
        """Read-only preview of ``_complete_run``'s staleness verdict (authoritative check is in the apply)."""
        from core.reliability.freshness import revalidate
        reasons = []
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            incident = self.repository._fetch(conn, snapshot.incident_id)
            if incident.active_run_id != snapshot.run_id:
                reasons.append("ACTIVE_RUN_CHANGED")
            if incident.revision != snapshot.input_revision:
                reasons.append("REVISION_CHANGED_DURING_RUN")
            if snapshot.source_dependency_manifest is not None:
                reasons.extend(change.reason for change in revalidate(conn, snapshot.source_dependency_manifest))
        return reasons

    def _settle(self, conn, incident_id: str, report, revision: int) -> dict:
        """Apply the lifecycle's deterministic settlement for a *current* report, inside the apply transaction.

        PROMOTE runs the unchanged diagnosis gates (trusted confirmation required); NEEDS_EVIDENCE parks
        the incident in AWAITING_EVIDENCE exactly as ``LifecycleService.diagnose`` does. Unlike the
        autonomous lifecycle, an operator-driven PRISM run never escalates an incident: a blocked or
        failed candidate is recorded and left to the operator.
        """
        from core.reliability.promotion import CONFIRM_MECHANISM, PromotionRefused
        disposition, reason = self.lifecycle._settle(incident_id, report, "DIAGNOSIS")
        outcome = {"disposition": disposition, "reason": reason, "promotion_id": None}
        if disposition == "PROMOTE":
            confirmation_id = None
            for key in report.evidence_manifest:
                artifact = self.repository._artifact(conn, incident_id, key)
                if getattr(artifact, "source_capability", None) == CONFIRM_MECHANISM:
                    confirmation_id = key
            if confirmation_id is None:
                disposition, reason = "NEEDS_EVIDENCE", "trusted technical confirmation has not been supplied"
            else:
                try:
                    promotion = self.promotion.promote_diagnosis(
                        incident_id, report_id=report.id, confirmation_id=confirmation_id,
                        expected_revision=report.checkpoint_revision, conn=conn)
                    outcome.update(disposition="PROMOTED", reason="application promoted the diagnosis",
                                   promotion_id=promotion.id)
                    disposition = "PROMOTED"
                except PromotionRefused as exc:
                    disposition = "NEEDS_EVIDENCE" if exc.disposition == "NEEDS_EVIDENCE" else "UNRESOLVED"
                    reason = str(exc)
        if disposition == "NEEDS_EVIDENCE":
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase == m.IncidentPhase.INVESTIGATING:
                self.repository.transition_in(conn, incident_id, m.IncidentPhase.AWAITING_EVIDENCE,
                                              expected_revision=incident.revision,
                                              reason=f"{reason} (PRISM revision {revision})")
        outcome.update(disposition=disposition, reason=reason)
        incident = self.repository._fetch(conn, incident_id)
        outcome.update(incident_phase=incident.phase.value, incident_revision=incident.revision)
        return outcome

    def _candidate(self, result, snapshot, description: dict, *, pass_no: int, request: dict,
                   timing: dict) -> SlowPathResult:
        hypotheses = _hypotheses(result, result.candidate_diagnosis_key)
        recommended = next((h for h in hypotheses if h["recommended"]), None)
        summary = (result.decision.reasoning_summary if result.decision else None) or (
            f"Supervisor run ended {result.termination_reason} with disposition {result.disposition}"
            + (f": {result.blockers[0]}" if result.blockers else "."))
        findings = []
        if recommended:
            findings.append(f"Recommended hypothesis: {recommended['mechanism']} (confidence {recommended['confidence']}).")
        for h in hypotheses:
            if not h["recommended"]:
                findings.append(f"Alternative hypothesis: {h['mechanism']} (confidence {h['confidence']}).")
        findings.extend(f"Evidence needed: {n.capability}: {n.question}" for n in result.unresolved_evidence_needs[:5])
        findings.extend(f"Blocker: {b}" for b in result.blockers[:5])
        actions = [{"kind": "next_step", "description": next_step(result)}]
        actions.extend({"kind": "plan_candidate", "description": step["description"], "approval": "required",
                        "equipment_ids": step["equipment_ids"]} for step in _plan(result)[:8])
        provenance = PROVENANCE_MAP.get(str(description.get("provenance")), "INJECTED")
        candidate = {
            "operon_run_id": snapshot.run_id, "snapshot_id": snapshot.id, "input_revision": snapshot.input_revision,
            "stage": snapshot.stage, "disposition": result.disposition,
            "termination_reason": result.termination_reason, "exhausted_limits": list(result.exhausted_limits),
            "tool_calls": result.tool_calls,
            "specialists": [{"role": d.role, "key": d.key, "status": d.status, "error_code": d.error_code}
                            for d in result.delegations],
            "evidence_used": list(result.evidence_used),
            "evidence_requests": [{"capability": r.capability, "status": r.status, "evidence_id": r.evidence_id}
                                  for r in result.evidence_requests],
            "hypotheses": hypotheses, "recommended_hypothesis": recommended,
            "confidence": recommended["confidence"] if recommended else None,
            "unresolved_evidence_needs": [{"capability": n.capability, "question": n.question}
                                          for n in result.unresolved_evidence_needs[:10]],
            "blockers": list(result.blockers[:10]), "plan_candidate": _plan(result),
            "next_step": next_step(result), "human_review_required": True,
            "failure": next((b for b in result.blockers if b.startswith("Model invocation failed")), None),
        }
        return SlowPathResult(
            summary=summary[:4000], findings=[f[:400] for f in findings[:32]], proposed_actions=actions[:16],
            provenance=provenance, runtime={**self.identity(), "pass": pass_no},
            details={"candidate": candidate, "reasoning_request": request, "timing": timing,
                     "reasoning": {"backend": description.get("backend"), "provider": description.get("provider"),
                                   "model": description.get("model"), "live_model": bool(description.get("live_model")),
                                   "provenance": description.get("provenance"), "runtime": description.get("runtime")}})

    # ---- the run ----------------------------------------------------------------------------
    async def run(self, execution: SlowPathExecution) -> SlowPathResult:
        started = time.monotonic()
        incident = (execution.context or {}).get("incident") or {}
        incident_id = incident.get("id")
        if not incident_id:
            raise SlowPathUnavailable("PRISM session is not linked to an Operon incident; production reasoning "
                                      "needs authoritative incident context", code="incident_required")
        self._checkpoint(execution)
        backend = self._backend()
        description = self.describe(backend)
        question, request = compose_question(execution.turn.content, execution.revision,
                                             (execution.context or {}).get("session"))
        request.update(incident_id=incident_id, role=self.role, provider=description.get("provider"),
                       model=description.get("model"), backend=description.get("backend"))
        await execution.report(stage="reasoning_context_prepared", **request)
        from core.agents.runtime import RuntimeConfigurationError
        try:
            await backend.preflight()
        except RuntimeConfigurationError as exc:
            raise SlowPathUnavailable(f"reasoning runtime unavailable: {exc}", code=exc.code or "provider_not_configured")
        await self._wait_while_busy(execution, incident_id)
        loop = asyncio.get_running_loop()
        pending: set[asyncio.Task] = set()

        def observe(payload: dict) -> None:
            safe = {k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool)) or v is None}
            safe.setdefault("stage", "supervisor_progress")

            def _spawn():
                task = loop.create_task(execution.report(**safe))
                pending.add(task)
                task.add_done_callback(pending.discard)
            loop.call_soon_threadsafe(_spawn)

        compute_kwargs = {}
        if getattr(backend, "supports_progress", False):
            compute_kwargs = {"progress": observe,
                              "cancelled": lambda: self.cooperative and execution.cancellation.cancelled}
        from core.agents.contracts import SpecialistContext, SupervisorBounds
        from core.reliability.promotion import PromotionRefused
        candidate = None
        for pass_no in range(1, self.max_passes + 1):
            self._checkpoint(execution)
            eligibility = execution.fence.check()
            if eligibility.reason in ("already_terminal", "run_missing", "session_missing", "session_closed"):
                # A replayed/duplicate execution of a finished run never reasons again (fail closed).
                raise StaleRevisionError(eligibility)
            current = self.repository.fetch_incident(incident_id)
            if current.phase not in (m.IncidentPhase.INVESTIGATING, m.IncidentPhase.AWAITING_EVIDENCE):
                raise SlowPathUnavailable(
                    f"incident {incident_id} is in phase {current.phase.value}; PRISM production reasoning "
                    "currently serves the diagnosis stage (INVESTIGATING / AWAITING_EVIDENCE)", code="stage_unavailable")
            asset_id = current.equipment_ids[0]
            if execution.fence.check().committed:
                # Baseline reads are refreshed like the lifecycle does; evidence-only, additive, audited.
                await asyncio.to_thread(self.lifecycle.refresh_baseline_evidence, incident_id, asset_id,
                                        self.evidence_service)
            evidence_ids = await asyncio.to_thread(self.lifecycle.current_evidence_ids, incident_id, asset_id)
            bounds = SupervisorBounds.model_validate(self.bounds or SupervisorBounds())
            remaining = execution.remaining_seconds()
            timeout = backend.run_timeout() if bounds.timeout_seconds is None else bounds.timeout_seconds
            if remaining is not None:
                timeout = max(1.0, min(timeout, remaining))
            bounds = bounds.model_copy(update={"timeout_seconds": float(timeout)})
            holder: dict[str, Any] = {}

            def claim(conn):
                live = self.repository._fetch(conn, incident_id)
                if live.phase == m.IncidentPhase.AWAITING_EVIDENCE:
                    live = self.repository.transition_in(conn, incident_id, m.IncidentPhase.INVESTIGATING,
                                                         expected_revision=live.revision,
                                                         reason=f"operator instruction (PRISM revision {execution.revision})")
                snapshot = self.promotion.start_run(
                    incident_id, asset_id=asset_id, stage="DIAGNOSIS", expected_revision=live.revision,
                    evidence_ids=evidence_ids, runtime=backend, bounds=bounds, question=question, conn=conn)
                holder["snapshot"] = snapshot
                return {"operon_run_id": snapshot.run_id, "snapshot_id": snapshot.id,
                        "input_revision": snapshot.input_revision, "evidence_count": len(snapshot.evidence_manifest)}
            try:
                outcome = await execution.transact(kind="operon_run_claim", key=f"claim:{execution.run_id}:p{pass_no}",
                                                   payload={"incident_id": incident_id, "pass": pass_no,
                                                            "instruction_hash": request["instruction_hash"]},
                                                   perform=claim)
            except PromotionRefused as exc:
                raise SlowPathUnavailable(f"reasoning run could not be claimed: {exc}", code="claim_refused") from exc
            snapshot = holder.get("snapshot")
            if snapshot is None:  # duplicate claim (same key): reload the frozen snapshot
                snapshot = self.repository.get_artifact(incident_id, outcome.effect.result["snapshot_id"])
            await execution.report(stage="run_claimed", pass_no=pass_no, **outcome.effect.result)
            context = SpecialistContext.model_validate(snapshot.context_payload)
            run_bounds = SupervisorBounds.model_validate(snapshot.bounds)
            cancelled_result = None

            def preserve(result):
                nonlocal cancelled_result
                cancelled_result = result
            compute_started = time.monotonic()
            try:
                result = await backend.supervise(self.evidence_service, context, bounds=run_bounds, snapshot=snapshot,
                                                 cancellation_result_handler=preserve, **compute_kwargs)
            except (asyncio.CancelledError, CancelledByRuntime):
                await self._record_terminated(execution, snapshot, cancelled_result, run_bounds, "CANCELLED", None)
                raise
            except Exception as exc:  # noqa: BLE001 - audited on the incident (fenced), then recorded as the PRISM failure
                await self._record_terminated(execution, snapshot, None, run_bounds, "MODEL_FAILED", exc)
                raise
            await self._drain(pending)   # supervisor/specialist progress lands before the candidate does
            timing = {"compute_ms": round((time.monotonic() - compute_started) * 1000, 1),
                      "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "pass": pass_no}
            candidate = self._candidate(result, snapshot, description, pass_no=pass_no, request=request, timing=timing)
            info = candidate.details["candidate"]
            await execution.report(stage="candidate_ready", pass_no=pass_no, disposition=info["disposition"],
                                   termination_reason=info["termination_reason"], tool_calls=info["tool_calls"],
                                   specialists=len(info["specialists"]), compute_ms=timing["compute_ms"])
            await self._before_fence(execution, candidate)
            stale = self._stale_reasons(snapshot)
            if stale and pass_no < self.max_passes and result.termination_reason == "MODEL_COMPLETED" \
                    and not execution.cancellation.cancelled and execution.fence.check().committed:
                # The frozen inputs changed while reasoning (e.g. evidence was collected): record the
                # report as history through the fence and reason again over the refreshed packet.
                try:
                    await execution.transact(kind="operon_run_report", key=f"report:{execution.run_id}:p{pass_no}",
                                             payload={"operon_run_id": snapshot.run_id, "stale": stale},
                                             perform=lambda conn: {"report_id": self.promotion._complete_run(
                                                 snapshot, result, conn=conn).id, "stale_reasons": stale})
                    await execution.report(stage="candidate_fenced", pass_no=pass_no, disposition="retry",
                                           stale_reasons=",".join(stale))
                    continue
                except StaleRevisionError:
                    pass   # superseded meanwhile: the fence below records this candidate as stale history

            def apply(conn):
                report = self.promotion._complete_run(snapshot, result, conn=conn)
                applied = {"report_id": report.id, "operon_run_id": report.run_id,
                           "stale_reasons": list(report.stale_reasons), "completion": report.completion,
                           "checkpoint_revision": report.checkpoint_revision, "settlement": None}
                if not report.stale_reasons:
                    applied["settlement"] = self._settle(conn, incident_id, report, execution.revision)
                else:
                    live = self.repository._fetch(conn, incident_id)
                    applied["settlement"] = {"disposition": "RETRY", "reason": "run inputs changed during reasoning: "
                                             + ", ".join(report.stale_reasons), "incident_phase": live.phase.value,
                                             "incident_revision": live.revision, "promotion_id": None}
                return applied
            decision = await execution.complete(candidate, apply=apply)
            await execution.report(stage="candidate_fenced", pass_no=pass_no,
                                   disposition="committed" if decision.committed else "stale", reason=decision.reason,
                                   current_revision=decision.current_revision)
            if decision.committed:
                await execution.report(stage="candidate_applied", pass_no=pass_no,
                                       operon_run_id=snapshot.run_id, total_ms=round((time.monotonic() - started) * 1000, 1))
            break
        await self._drain(pending)
        return candidate

    async def _before_fence(self, execution: SlowPathExecution, candidate: SlowPathResult) -> None:
        """The boundary between a computed candidate and the fence. Development-only gate: with
        ``OPERON_PRISM_SLOW_HOLD_SECONDS`` the real candidate is held here so an interruption can be
        reproduced against genuine model output; tests use the same seam as a race barrier."""
        if self.hold_seconds > 0:
            await execution.report(stage="development_hold", seconds=self.hold_seconds)
            await asyncio.sleep(self.hold_seconds)

    @staticmethod
    async def _drain(pending: set) -> None:
        await asyncio.sleep(0)   # let call_soon_threadsafe-scheduled spawns run
        for task in list(pending):
            if not task.done():
                try:
                    await task
                except Exception:  # noqa: BLE001 - progress is audit only
                    pass

    async def _record_terminated(self, execution, snapshot, partial, bounds, reason: str, exc) -> None:
        """Best effort audit, exactly what ``run_supervisor`` records for a cancelled/failed invocation:
        a still-current revision leaves a CANCELLED/MODEL_FAILED report on the incident; a superseded
        revision is refused by the fence and stays PRISM-only history. Never blocks propagation."""
        from core.agents.contracts import SupervisorResult
        blocker = "Application invocation did not complete."
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            blocker += f" Reasoning backend failure: {code}."
        elif exc is not None:
            blocker += f" {type(exc).__name__}."
        result = partial or SupervisorResult(
            incident_id=snapshot.incident_id, run_id=snapshot.run_id, input_revision=snapshot.input_revision,
            disposition="ESCALATED", decision=None, assessments=(), delegations=(), evidence_requests=(),
            evidence_used=(), candidate_diagnosis_key=None, engineering_key=None, operations_key=None, critic_keys=(),
            maintenance_plan_key=None, unresolved_evidence_needs=(), blockers=(blocker,),
            termination_reason=reason, exhausted_limits=(), tool_calls=0, bounds=bounds)
        try:
            await execution.transact(kind="operon_run_report", key=f"{reason.lower()}:{execution.run_id}:{snapshot.run_id}",
                                     payload={"operon_run_id": snapshot.run_id, "termination": reason},
                                     perform=lambda conn: {"report_id": self.promotion._complete_run(snapshot, result, conn=conn).id})
        except StaleRevisionError:
            await execution.report(stage="cancellation_observed" if reason == "CANCELLED" else "stale_failure_fenced",
                                   boundary="supervisor", fenced=True, operon_run_id=snapshot.run_id)
        except Exception:  # noqa: BLE001 - audit only; the original outcome must propagate promptly
            logger.debug("terminated report not recorded", exc_info=True)


def options_from_environment(env=None) -> dict:
    """Development knobs for the production adapter (all optional, all documented as such)."""
    env = os.environ if env is None else env
    try:
        hold = float(env.get("OPERON_PRISM_SLOW_HOLD_SECONDS") or 0.0)
    except ValueError:
        hold = 0.0
    try:
        passes = int(env.get("OPERON_PRISM_SLOW_MAX_PASSES") or DEFAULT_MAX_PASSES)
    except ValueError:
        passes = DEFAULT_MAX_PASSES
    cooperative = (env.get("OPERON_PRISM_SLOW_COOPERATIVE") or "1").strip().lower() not in ("0", "false", "no", "off")
    return {"hold_seconds": max(0.0, hold), "max_passes": max(1, passes), "cooperative": cooperative}


def default_backend_factory(registry=None):
    """Resolve the ``slow`` role through the Stage 0 registry; the labelled deterministic advisory
    (provider ``none``, provenance SIMULATED) only when *no* provider is configured. A configured but
    unusable provider is reported, never silently replaced."""
    from core import config
    from core.reasoning.backend import backend_from_environment

    def factory():
        from core.providers import get_registry
        reg = registry or get_registry()
        provider = reg.build(role=ROLE_SLOW)
        if config.reasoning_backend() == "none" or provider.kind == "none" or not provider.configured():
            from core.demo_scenario import DeterministicAdvisoryBackend
            return DeterministicAdvisoryBackend()
        backend = backend_from_environment(registry=reg, role=ROLE_SLOW)
        if backend is None:
            from core.demo_scenario import DeterministicAdvisoryBackend
            return DeterministicAdvisoryBackend()
        return backend
    return factory


__all__ = ["OperonSlowPathAdapter", "compose_question", "default_backend_factory", "next_step",
           "options_from_environment"]
