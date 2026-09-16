"""Slow Path: the runtime contract for longer reasoning work.

Every execution knows its identity (session/turn/revision/run/attempt), its
cancellation token, its deadline, its runtime/provider role identity and its
commit fence. Adapters return a ``SlowPathResult``; they never mutate canonical
state themselves. External effects go through ``SlowPathExecution.effect`` so the
fence can refuse them once the revision is superseded.

Two built-in adapters: a deterministic one (labelled DETERMINISTIC; delay and
cooperativeness configurable so the interruption scenario is reproducible without
any model) and a provider-backed one that asks the Stage 0 registry for the
``slow`` role and runs the bounded JSON completion off the event loop. No vendor
SDK is imported here.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import os
import time
from typing import Any, Protocol

from core.reliability.repository import content_hash

from .cancellation import CancellationToken, uninterruptible
from .fencing import RunFence, StaleRevisionError
from .models import CommitDecision, PrismEffect, PrismEvent, PrismTurn, ROLE_SLOW, RunIdentity, SlowPathResult

ROLE_PROVIDER_SLOW = ROLE_SLOW


class SlowPathUnavailable(RuntimeError):
    def __init__(self, message: str, *, code: str = "slow_path_unavailable"):
        super().__init__(message)
        self.code = code


@dataclass
class EffectOutcome:
    effect: PrismEffect
    performed: bool          # this call performed the external action
    duplicate: bool          # an earlier call already recorded it


@dataclass
class SlowPathExecution:
    identity: RunIdentity
    turn: PrismTurn
    context: dict[str, Any]
    cancellation: CancellationToken
    fence: RunFence
    runtime: dict[str, Any]
    deadline_monotonic: float | None = None
    role: str = ROLE_SLOW
    progress: Callable[[dict], Awaitable[None]] | None = None
    commit: Callable[..., Awaitable[Any]] | None = None
    publish: Callable[[list[PrismEvent]], Awaitable[None]] | None = None
    effects: list[EffectOutcome] = field(default_factory=list)
    decision: CommitDecision | None = None   # set once ``complete`` has passed the fence (any outcome)

    @property
    def session_id(self) -> str:
        return self.identity.session_id

    @property
    def revision(self) -> int:
        return self.identity.revision

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    def check_cancelled(self) -> None:
        self.cancellation.raise_if_cancelled()

    def remaining_seconds(self) -> float | None:
        if self.deadline_monotonic is None:
            return None
        return max(0.0, self.deadline_monotonic - time.monotonic())

    async def report(self, **payload) -> None:
        if self.progress is not None:
            await self.progress(dict(payload))

    async def complete(self, result: SlowPathResult, *, apply: Callable[[Any], dict | None] | None = None):
        """Early/explicit completion through the runtime's fence (events published). Duplicates are no-ops.

        ``apply(conn)`` (Stage 2) is executed inside the commit transaction only if the fence
        admits the result: it is the one place a Slow Path result may write canonical
        application state, and it is atomic with the PRISM commit itself.
        """
        if self.commit is None:
            decision, events = self.fence.commit(result, runtime=self.runtime, apply=apply)
            if self.publish is not None:
                await self.publish(events)
        else:
            decision = await self.commit(result, apply=apply)
        self.decision = decision
        return decision

    async def transact(self, *, kind: str, key: str, payload: dict, perform: Callable[[Any], dict | None]) -> EffectOutcome:
        """Atomic fenced write, exactly once per (session, revision, key) (Stage 2).

        Unlike ``effect`` (which performs an *external* action between two transactions),
        ``perform(conn)`` runs inside the fence transaction over the shared database, so the
        eligibility check and the write cannot be separated by a newer revision. Refused with
        ``StaleRevisionError`` once the revision is superseded; a duplicate key returns the
        recorded outcome without performing anything.
        """
        request_hash = content_hash({"kind": kind, "payload": payload})
        effect, performed, events = self.fence.transact(kind=kind, idempotency_key=key, request_hash=request_hash,
                                                        perform=perform)
        if events and self.publish is not None:
            await self.publish(events)
        outcome = EffectOutcome(effect=effect, performed=performed, duplicate=not performed)
        self.effects.append(outcome)
        return outcome

    async def effect(self, *, tool_call_id: str, kind: str, payload: dict, perform: Callable[[], Awaitable[dict]],
                     idempotency_key: str | None = None) -> EffectOutcome:
        """Perform an external effect exactly once per (session, revision, key); fenced on the revision.

        Refused with ``StaleRevisionError`` when the run's revision is no longer canonical, so a
        superseded revision can never trigger a tool. A duplicate call returns the recorded
        outcome without performing anything. If the process dies after ``perform`` but before
        completion is recorded, recovery marks the effect UNKNOWN; it is never re-run blindly.
        """
        key = idempotency_key or tool_call_id
        request_hash = content_hash({"kind": kind, "payload": payload})
        effect, created = self.fence.begin_effect(tool_call_id=tool_call_id, idempotency_key=key, kind=kind,
                                                  request_hash=request_hash)
        if not created:
            outcome = EffectOutcome(effect=effect, performed=False, duplicate=True)
            self.effects.append(outcome)
            return outcome
        try:
            result = await perform()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            effect, _ = self.fence.complete_effect(effect.effect_id, status="FAILED",
                                                   result={"error": f"{type(exc).__name__}: {exc}"[:500]})
            outcome = EffectOutcome(effect=effect, performed=True, duplicate=False)
            self.effects.append(outcome)
            raise
        effect, applied = self.fence.complete_effect(effect.effect_id, status="COMPLETED", result=result)
        outcome = EffectOutcome(effect=effect, performed=True, duplicate=not applied)
        self.effects.append(outcome)
        return outcome


class SlowPathAdapter(Protocol):
    name: str
    cancellable: bool

    def identity(self) -> dict: ...

    async def run(self, execution: SlowPathExecution) -> SlowPathResult: ...


def incident_context(incident_repository, incident_id: str | None) -> dict[str, Any]:
    """Read-only Operon incident context handed to the Slow Path (never a write handle)."""
    if incident_repository is None or incident_id is None:
        return {"incident": None}
    try:
        incident = incident_repository.fetch_incident(incident_id)
    except LookupError:
        return {"incident": None, "incident_id": incident_id, "missing": True}
    from core.reliability import models as m
    artifacts = incident_repository.list_artifacts(incident_id)
    diagnosis = next((a for a in reversed(artifacts) if isinstance(a, m.Diagnosis)), None)
    intervention = next((a for a in reversed(artifacts) if isinstance(a, m.Intervention)), None)
    evidence = [a for a in artifacts if isinstance(a, m.Evidence)]
    return {
        "incident": {
            "id": incident.id, "phase": incident.phase.value, "revision": incident.revision,
            "equipment_ids": list(incident.equipment_ids), "severity": incident.severity,
            "diagnosis": diagnosis.conclusion if diagnosis else None,
            "intervention": intervention.summary if intervention else None,
            "evidence_count": len(evidence), "evidence_kinds": sorted({e.kind for e in evidence}),
        }
    }


def _summarize(execution: SlowPathExecution) -> tuple[str, list[str]]:
    incident = (execution.context or {}).get("incident")
    findings = []
    if incident:
        findings.append(f"Incident {incident['id']} is in phase {incident['phase']} (revision {incident['revision']}).")
        findings.append(f"{incident['evidence_count']} evidence records frozen: {', '.join(incident['evidence_kinds']) or 'none'}.")
        if incident.get("diagnosis"):
            findings.append(f"Current diagnosis: {incident['diagnosis'][:160]}")
    else:
        findings.append("No Operon incident is linked to this session.")
    content = execution.turn.content.strip()
    summary = f"Revision {execution.revision}: analysed operator instruction \"{content[:120]}\"."
    return summary, findings


class DeterministicSlowPathAdapter:
    """Deterministic Slow Path over the frozen incident context. Labelled DETERMINISTIC; never a model.

    ``delay_seconds`` models long reasoning; ``cooperative=False`` models a worker that ignores
    cancellation (its result must then be fenced, which the interruption scenario demonstrates).
    """
    name = "deterministic"

    def __init__(self, *, delay_seconds: float = 0.0, cooperative: bool = True):
        self.delay_seconds, self.cooperative = float(delay_seconds), bool(cooperative)

    @property
    def cancellable(self) -> bool:
        return self.cooperative

    def identity(self) -> dict:
        return {"adapter": self.name, "role": ROLE_SLOW, "provider": "none", "model": None, "live_model": False,
                "provenance": "DETERMINISTIC", "implementation": "operon.prism.slow-path.deterministic-v1",
                "cancellable": self.cooperative, "delay_seconds": self.delay_seconds}

    async def run(self, execution: SlowPathExecution) -> SlowPathResult:
        await execution.report(stage="analysing", delay_seconds=self.delay_seconds)
        if self.delay_seconds > 0:
            if self.cooperative:
                await execution.cancellation.sleep(self.delay_seconds)
            else:
                await uninterruptible(asyncio.sleep(self.delay_seconds))
        summary, findings = _summarize(execution)
        return SlowPathResult(summary=summary, findings=findings, provenance="DETERMINISTIC",
                              runtime=self.identity(),
                              proposed_actions=[{"kind": "review", "description": "Review the frozen evidence packet "
                                                 "against the operator instruction; no external action proposed."}])


class ProviderSlowPathAdapter:
    """Model-backed Slow Path through the Stage 0 registry (``role="slow"``). Bounded, off-loop, fenced."""
    name = "provider"
    cancellable = True   # the awaiting task is cancelled; the provider thread is abandoned and fenced

    def __init__(self, registry=None, *, role: str = ROLE_PROVIDER_SLOW):
        self._registry, self.role = registry, role

    def _provider(self):
        from core.providers import get_registry
        registry = self._registry or get_registry()
        provider = registry.build(role=self.role)
        if provider.kind == "none" or not provider.configured():
            raise SlowPathUnavailable(provider.not_configured_reason(), code="provider_not_configured")
        return provider

    def identity(self) -> dict:
        try:
            provider = self._provider()
        except SlowPathUnavailable as exc:
            return {"adapter": self.name, "role": self.role, "provider": "none", "model": None, "live_model": False,
                    "provenance": None, "unavailable_reason": str(exc)}
        return {"adapter": self.name, "role": self.role, "provider": provider.kind, "model": provider.model_id,
                "live_model": True, "provenance": "LIVE", "locality": provider.capabilities().locality}

    async def run(self, execution: SlowPathExecution) -> SlowPathResult:
        provider = self._provider()
        incident = (execution.context or {}).get("incident") or {}
        system = ("You are the Slow Path of Operon's PRISM interruptible runtime. Answer with one JSON object: "
                  '{"summary": str, "findings": [str], "proposed_actions": [{"kind": str, "description": str}]}. '
                  "You advise only; the application decides. Never claim an action was taken.")
        user = (f"Operator instruction (revision {execution.revision}): {execution.turn.content[:2000]}\n"
                f"Incident context: {incident}")
        timeout = provider.timeout_policy().auxiliary_seconds
        remaining = execution.remaining_seconds()
        if remaining is not None:
            timeout = min(timeout, max(1.0, remaining))
        await execution.report(stage="model_call", provider=provider.kind, timeout_seconds=timeout)
        payload = await asyncio.wait_for(asyncio.to_thread(provider.generate_json, system, user, timeout=timeout),
                                         timeout=timeout + 5)
        findings = [str(f)[:400] for f in (payload.get("findings") or [])[:32]]
        actions = [a for a in (payload.get("proposed_actions") or [])[:16] if isinstance(a, dict)]
        return SlowPathResult(summary=str(payload.get("summary") or "model returned no summary")[:4000],
                              findings=findings, proposed_actions=actions, provenance="LIVE", runtime=self.identity())


def adapter_from_environment(registry=None, env=None, *, services: dict | None = None) -> SlowPathAdapter:
    """OPERON_PRISM_SLOW_PATH: auto | operon | deterministic | provider.

    ``auto`` and ``operon`` (Stage 2) select the production adapter around Operon's real
    supervisor/specialist reasoning (``core.prism.operon``); it reasons through the provider bound
    to role ``slow`` and labels a no-provider run SIMULATED, never LIVE. ``deterministic`` is the
    Stage 1 no-model adapter, ``provider`` the Stage 1 bounded JSON completion. Both older modes are
    explicit development selections; production never masquerades a fake as live reasoning.

    OPERON_PRISM_SLOW_DELAY_SECONDS and OPERON_PRISM_SLOW_COOPERATIVE tune the deterministic adapter
    (the manual interruption scenario uses a delay and a non-cooperative worker on purpose);
    OPERON_PRISM_SLOW_COOPERATIVE, OPERON_PRISM_SLOW_HOLD_SECONDS and OPERON_PRISM_SLOW_MAX_PASSES
    tune the production adapter (development knobs, documented in docs/PRISM_RUNTIME.md).
    """
    env = os.environ if env is None else env
    mode = (env.get("OPERON_PRISM_SLOW_PATH") or "auto").strip().lower()
    if mode in ("auto", "operon"):
        from .operon import OperonSlowPathAdapter, default_backend_factory, options_from_environment
        options = options_from_environment(env)
        if services is None:
            from core.reliability.repository import IncidentRepository
            services = {"incident_repository": IncidentRepository(), "backend_factory": default_backend_factory(registry)}
        return OperonSlowPathAdapter(**{**options, **services})
    try:
        delay = float(env.get("OPERON_PRISM_SLOW_DELAY_SECONDS") or 0.0)
    except ValueError:
        delay = 0.0
    cooperative = (env.get("OPERON_PRISM_SLOW_COOPERATIVE") or "1").strip().lower() not in ("0", "false", "no", "off")
    deterministic = DeterministicSlowPathAdapter(delay_seconds=max(0.0, delay), cooperative=cooperative)
    if mode == "deterministic":
        return deterministic
    provider = ProviderSlowPathAdapter(registry)
    if mode == "provider":
        return provider
    try:
        provider._provider()
    except SlowPathUnavailable:
        return deterministic
    return provider


__all__ = ["DeterministicSlowPathAdapter", "EffectOutcome", "ProviderSlowPathAdapter", "SlowPathAdapter",
           "SlowPathExecution", "SlowPathUnavailable", "StaleRevisionError", "adapter_from_environment",
           "incident_context"]
