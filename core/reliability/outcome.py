"""Deterministic outcome verification and autonomous closure authority (Step 14).

prediction != diagnosis != intervention != approval != execution != outcome

A CONFIRMED execution receipt means the consequential operation is known to have
committed. It never means the equipment recovered, and it never permits CLOSED.
Only the deterministic policy in this module, applied to durable post-intervention
evidence bound to the exact executed lineage, may establish recovery. Closure
(OBSERVING -> CLOSED) is written by ``LifecycleService`` in the same transaction as
the authoritative ``Outcome``; no other route to CLOSED exists.

Verification is application-owned and model-free: every read is local SQLite,
evidence is collected between the read snapshot and the commit transaction (never
under a lock), and the commit re-derives the decision from the persisted evidence
it binds. False non-closure is preferable to false closure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core import config, db
from . import models as m
from .evidence import EvidenceService, HealthScoreWindow, TelemetryWindow
from .execution import TRUSTED_EXECUTOR
from .freshness import revalidate
from .governance import artifact_hash
from .promotion import PromotionRefused
from .repository import DuplicateRecord, InvalidReference, StaleRevision, content_hash, manifest_authority, new_id, utcnow

POLICY_VERSION = m.OUTCOME_POLICY
VERIFIER = m.OUTCOME_VERIFIER
# Explicit, versioned, conservative policy parameters (frozen into every plan).
MIN_POST_SCORES = 3        # consecutive post-intervention scores that must agree before any terminal result
MAX_POST_SCORES = 12       # observation budget before persistently elevated risk becomes NOT_RECOVERED
SAMPLE_LIMIT = 120         # bounded window read (newest N); must exceed MAX_POST_SCORES
REGRESSION_MARGIN = 0.05   # latest risk above baseline by this much, with the whole settled tail critical, is a regression
HEALTH_QUESTION = "Persisted post-intervention health scores for deterministic outcome verification."
TELEMETRY_QUESTION = "Persisted post-intervention telemetry for outcome verification context."
HEALTH_CAPABILITY = "get_health_score_window"
TELEMETRY_CAPABILITY = "get_telemetry_window"


def policy_parameters() -> dict[str, float]:
    """The same thresholds that admit a model-risk incident decide its recovery."""
    return {"minimum_post_scores": MIN_POST_SCORES, "maximum_post_scores": MAX_POST_SCORES,
            "sample_limit": SAMPLE_LIMIT, "recovery_risk_max": config.WARN_THRESHOLD,
            "elevated_risk_min": config.TRIGGER_THRESHOLD, "regression_margin": REGRESSION_MARGIN}


def observation_start(confirmed_at: datetime) -> datetime:
    """First fully elapsed second after confirmation (mirror of ``investigation.snapshot_boundary``).

    Writers stamp scores and readings at whole-second precision, so a sample in the
    confirmation second cannot be proven post-execution and is excluded.
    """
    return confirmed_at.replace(microsecond=0) + timedelta(seconds=1)


def _errors():
    # Runtime import: lifecycle imports this module at load time.
    from .lifecycle import AuthorityRefused, LifecycleRefused
    return AuthorityRefused, LifecycleRefused


def _require(condition, reason, *, authority=True, disposition="BLOCKED"):
    if not condition:
        AuthorityRefused, LifecycleRefused = _errors()
        raise (AuthorityRefused if authority else LifecycleRefused)(reason, disposition=disposition)


class OutcomeDecision(BaseModel):
    """Pure result of the versioned policy over one frozen plan and one evidence window."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    result: m.OutcomeResult
    reason: str
    checks: dict[str, bool]
    after_metrics: dict[str, float]
    post_score_count: int


class OutcomeVerification(BaseModel):
    """One deterministic verification attempt. Authority exists only where ``outcome_id`` is set."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    incident_id: str
    phase: m.IncidentPhase
    revision: int
    disposition: Literal["CLOSED", "REINVESTIGATE", "ESCALATED", "OBSERVING", "RETRY"]
    result: m.OutcomeResult | None
    reason: str
    policy_version: str = POLICY_VERSION
    plan_id: str | None = None
    outcome_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    checks: dict[str, bool] = {}
    post_score_count: int = 0


@dataclass(frozen=True)
class ExecutedLineage:
    """Exact lineage of the execution that produced OBSERVING; nothing here is inferred from phase."""
    diagnosis: m.Diagnosis
    diagnosis_record: m.PromotionRecord
    intervention: m.Intervention
    intervention_hash: str
    record: m.PromotionRecord
    requirement: m.ApprovalRequirement
    decision_ids: tuple[str, ...]
    claim: m.ExecutionClaim
    receipt: m.ExecutionReceipt


DISPOSITIONS = {"VERIFIED_RECOVERY": ("CLOSED", m.IncidentPhase.CLOSED),
                "NOT_RECOVERED": ("REINVESTIGATE", m.IncidentPhase.INVESTIGATING),
                "REGRESSED": ("ESCALATED", m.IncidentPhase.ESCALATED)}


def evaluate(plan: m.ObservationPlan, health: HealthScoreWindow, telemetry: TelemetryWindow | None = None) -> OutcomeDecision:
    """Versioned deterministic policy ``operon-outcome-1``.

    Signals used are only those the repository persists: the classifier's failure
    probability after the intervention versus the frozen baseline signal, judged
    with the same WARN/TRIGGER thresholds that admit incidents. Telemetry is recorded
    as context (``after_metrics``) and never decides: no universal physical
    thresholds are invented. Rules, over the last ``minimum_post_scores`` scores
    (the settled tail) of the frozen window:

    * fewer than the minimum, or a baseline that was not elevated: INCONCLUSIVE;
    * every tail score below ``recovery_risk_max`` (healthy band): VERIFIED_RECOVERY;
    * every tail score critical (``elevated_risk_min`` or above) and the latest
      above baseline by ``regression_margin``: REGRESSED (a single critical tick
      never authors a regression; the critical band must persist for the tail);
    * no healthy tail after ``maximum_post_scores`` scores (the observation
      budget, whether risk stayed elevated or kept oscillating): NOT_RECOVERED;
    * anything else (risk still settling): INCONCLUSIVE, observation continues.
    """
    parameters = plan.policy_parameters
    minimum, maximum = int(parameters["minimum_post_scores"]), int(parameters["maximum_post_scores"])
    recovery_max, elevated_min = parameters["recovery_risk_max"], parameters["elevated_risk_min"]
    margin = parameters["regression_margin"]
    baseline_risk = plan.baseline_metrics["risk_score"]
    scores = list(health.scores)
    checks = {
        "window_bound_to_plan": (health.asset_id == plan.asset_id and health.requested_start == plan.observation_start
                                 and health.requested_end is not None),
        "scores_post_execution": all(point.scored_at >= plan.observation_start for point in scores),
        "baseline_elevated": baseline_risk >= recovery_max,
        "sufficient_post_scores": len(scores) >= minimum,
    }
    after: dict[str, float] = {"post_score_count": float(len(scores))}
    if scores:
        risks = [point.failure_prob for point in scores]
        after.update(risk_latest=risks[-1], risk_min=min(risks), risk_max=max(risks),
                     risk_mean=math.fsum(risks) / len(risks), health_latest=scores[-1].health_score)
    if telemetry is not None:
        for series in telemetry.series:
            if series.statistics.latest_value is not None:
                after[f"telemetry.{series.sensor_type}.latest"] = series.statistics.latest_value
            if series.statistics.mean is not None:
                after[f"telemetry.{series.sensor_type}.mean"] = series.statistics.mean

    def decision(result, reason):
        return OutcomeDecision(result=result, reason=reason, checks=checks, after_metrics=after, post_score_count=len(scores))

    if not checks["window_bound_to_plan"] or not checks["scores_post_execution"]:
        return decision("INCONCLUSIVE", "evidence window is not the frozen post-intervention observation window")
    if not checks["sufficient_post_scores"]:
        return decision("INCONCLUSIVE", f"{len(scores)} post-intervention score(s) persisted; policy requires {minimum}")
    if not checks["baseline_elevated"]:
        return decision("INCONCLUSIVE", f"baseline risk {baseline_risk:.3f} was not elevated; no recovery can be verified against it")
    tail = [point.failure_prob for point in scores[-minimum:]]
    latest = tail[-1]
    checks.update({
        "tail_healthy": all(risk < recovery_max for risk in tail),
        "tail_elevated": all(risk >= recovery_max for risk in tail),
        "tail_critical": all(risk >= elevated_min for risk in tail),
        "latest_exceeds_baseline_margin": latest >= baseline_risk + margin,
        "observation_budget_exhausted": len(scores) >= maximum,
    })
    checks["regressed"] = checks["tail_critical"] and checks["latest_exceeds_baseline_margin"]
    described = ", ".join(f"{risk:.3f}" for risk in tail)
    if checks["tail_healthy"]:
        return decision("VERIFIED_RECOVERY", f"the last {minimum} post-intervention risk scores ({described}) are below "
                        f"{recovery_max:.2f} against a baseline of {baseline_risk:.3f}")
    if checks["regressed"]:
        return decision("REGRESSED", f"the last {minimum} post-intervention risk scores ({described}) are all critical "
                        f"(at or above {elevated_min:.2f}) and the latest {latest:.3f} exceeds the baseline "
                        f"{baseline_risk:.3f} by at least {margin:.2f}")
    if checks["observation_budget_exhausted"]:
        return decision("NOT_RECOVERED", f"no {minimum} consecutive healthy risk scores (latest {described}) within "
                        f"{len(scores)} post-intervention scores; observation budget of {maximum} exhausted")
    return decision("INCONCLUSIVE", f"post-intervention risk is still settling ({described}); "
                    f"{len(scores)} of at most {maximum} scores observed")


class OutcomeVerifier:
    """Application-owned verification flow used by ``LifecycleService.verify_outcome``."""

    def __init__(self, lifecycle, evidence_service: EvidenceService | None = None):
        self.lifecycle = lifecycle
        self.repository = lifecycle.repository
        self.promotion = lifecycle.promotion
        self.evidence_service = evidence_service or EvidenceService(self.repository)
        _require(self.evidence_service.repository.path.resolve() == self.repository.path.resolve()
                 and self.evidence_service.capabilities.path.resolve() == self.repository.path.resolve(),
                 "outcome evidence store must match the incident store", authority=False)

    # ------------------------------------------------------------- lineage
    def _executed(self, conn, incident) -> ExecutedLineage:
        """Exact execution lineage: promoted intervention, its diagnosis, approval, CONFIRMED claim and receipt.

        Uses ``current=False`` lineage validation plus explicit pointer and
        supersession checks: post-intervention evidence legitimately postdates the
        diagnosis promotion, so the "no newer technical evidence" rule that guards
        approval/execution does not apply here. A FAILED or UNKNOWN execution never
        yields a lineage and therefore never enters outcome verification.
        """
        _require(incident.current_intervention_id, "incident has no current promoted intervention")
        try:
            intervention, record = self.promotion._lineage(conn, incident, incident.current_intervention_id, "intervention", current=False)
            self.promotion._current(conn, incident.id, intervention)
            diagnosis, diagnosis_record = self.promotion._lineage(conn, incident, intervention.diagnosis_id, "diagnosis", current=False)
            self.promotion._current(conn, incident.id, diagnosis)
        except (PromotionRefused, InvalidReference) as exc:
            _require(False, f"execution lineage invalid: {exc}")
        _require(incident.current_diagnosis_id == diagnosis.id and record.source_diagnosis_promotion_id == diagnosis_record.id,
                 "executed intervention does not belong to the current diagnosis lineage")
        intervention_hash = artifact_hash(intervention)
        _require(len(intervention.steps) == 1 and intervention.steps[0].capability == "create_work_package",
                 "outcome verification supports exactly one governed work-package step")
        step = intervention.steps[0]
        requirement = self.lifecycle._current_requirement(conn, incident, intervention)
        _require(requirement is not None and requirement.promotion_id == record.id,
                 "no current approval requirement binds the executed intervention")
        approval = self.lifecycle._approval_state(conn, incident, requirement)
        _require(approval.state == "APPROVED", f"exact human approval is {approval.state}")
        claims = self.lifecycle._claims_for(conn, incident.id, intervention.id)
        _require(len(claims) == 1, "executed intervention must have exactly one execution claim")
        claim = claims[0]
        _require(claim.state == "CONFIRMED", f"execution claim is {claim.state}; only CONFIRMED execution enters outcome verification")
        _require((claim.incident_id, claim.intervention_hash, claim.step_id, claim.capability, claim.request_hash) == (
            incident.id, intervention_hash, step.id, step.capability, self.lifecycle._request_hash(step)),
            "execution claim is not bound to the exact executed intervention")
        receipts = [item for item in self.lifecycle._receipts(conn, incident.id) if item.idempotency_key == claim.idempotency_key]
        confirmed = [item for item in receipts if item.status == "CONFIRMED"]
        _require(len(confirmed) == 1, "exactly one CONFIRMED receipt must settle the execution claim")
        receipt = confirmed[0]
        _require(receipt.attempt == claim.attempt and not any(
            item.attempt == receipt.attempt and item.status != "CONFIRMED" for item in receipts),
            "receipt attempt conflicts with the settled execution claim")
        _require((receipt.intervention_id, receipt.intervention_hash, receipt.step_id, receipt.capability, receipt.request_hash,
                  receipt.executor) == (intervention.id, intervention_hash, step.id, step.capability, claim.request_hash, TRUSTED_EXECUTOR),
                 "CONFIRMED receipt is not bound to the exact executed intervention")
        return ExecutedLineage(diagnosis=diagnosis, diagnosis_record=diagnosis_record, intervention=intervention,
                               intervention_hash=intervention_hash, record=record, requirement=requirement,
                               decision_ids=approval.decision_ids, claim=claim, receipt=receipt)

    # ---------------------------------------------------------------- plan
    def _plan_for(self, conn, incident, receipt_id):
        plans = [item for item in self.promotion._all(conn, incident.id, m.ObservationPlan) if item.receipt_id == receipt_id]
        return plans[0] if plans else None

    def _outcome_for(self, conn, incident, plan_id):
        outcomes = [item for item in self.promotion._all(conn, incident.id, m.Outcome) if item.plan_id == plan_id]
        return outcomes[0] if outcomes else None

    def _baseline(self, conn, incident, lineage: ExecutedLineage, confirmed_at):
        """Frozen pre-intervention baseline from the promoted diagnosis packet, or None."""
        asset_id = lineage.intervention.steps[0].equipment_ids[0]
        packet = {}
        for key in lineage.diagnosis.evidence_ids:
            try:
                packet[key] = self.promotion._get(conn, incident.id, key, m.Evidence)
            except (PromotionRefused, InvalidReference):
                continue
        signals = sorted((item for item in packet.values() if item.kind == "model_signal" and asset_id in item.equipment_ids
                          and item.observed_at is not None and item.observed_at <= confirmed_at
                          and item.content_hash == content_hash(item.payload)), key=lambda item: item.observed_at)
        if not signals:
            return None
        signal_evidence = signals[-1]
        signal = m.ModelSignal.model_validate(signal_evidence.payload)
        metrics = {"risk_score": signal.risk_score, "health_score": signal.health_score}
        ids = [signal_evidence.id]
        telemetry = sorted((item for item in packet.values() if item.kind == "telemetry" and item.quality == "GOOD"
                            and asset_id in item.equipment_ids and item.observed_at is not None
                            and item.observed_at <= confirmed_at), key=lambda item: item.observed_at)
        if telemetry:
            window = TelemetryWindow.model_validate(telemetry[-1].payload)
            for series in window.series:
                if series.statistics.mean is not None:
                    metrics[f"telemetry.{series.sensor_type}.mean"] = series.statistics.mean
                if series.statistics.latest_value is not None:
                    metrics[f"telemetry.{series.sensor_type}.latest"] = series.statistics.latest_value
            ids.append(telemetry[-1].id)
        return dict(asset_id=asset_id, signal_evidence=signal_evidence, evidence_ids=tuple(ids), metrics=metrics,
                    simulated=signal.input_provenance == "SIMULATED")

    def _build_plan(self, incident, lineage: ExecutedLineage, baseline) -> m.ObservationPlan:
        receipt = lineage.receipt
        confirmed_at = receipt.completed_at or receipt.created_at
        return m.ObservationPlan(
            id=new_id(), incident_id=incident.id, created_at=utcnow(), equipment_ids=(baseline["asset_id"],),
            asset_id=baseline["asset_id"], diagnosis_id=lineage.diagnosis.id, diagnosis_promotion_id=lineage.diagnosis_record.id,
            intervention_id=lineage.intervention.id, intervention_hash=lineage.intervention_hash, promotion_id=lineage.record.id,
            approval_requirement_id=lineage.requirement.id, approval_decision_ids=lineage.decision_ids,
            execution_claim_key=lineage.claim.idempotency_key, receipt_id=receipt.id, receipt_operation_key=receipt.operation_key,
            receipt_attempt=receipt.attempt, confirmed_at=confirmed_at, observation_start=observation_start(confirmed_at),
            baseline_signal_evidence_id=baseline["signal_evidence"].id, baseline_evidence_ids=baseline["evidence_ids"],
            baseline_metrics=baseline["metrics"], diagnosed_failure_mode_code=lineage.diagnosis.failure_mode_code,
            policy_parameters=policy_parameters())

    def _check_plan(self, plan: m.ObservationPlan, lineage: ExecutedLineage, incident):
        receipt = lineage.receipt
        _require((plan.incident_id, plan.intervention_id, plan.intervention_hash, plan.promotion_id, plan.diagnosis_id,
                  plan.diagnosis_promotion_id, plan.execution_claim_key, plan.receipt_id, plan.receipt_operation_key,
                  plan.receipt_attempt, plan.approval_requirement_id) == (
                     incident.id, lineage.intervention.id, lineage.intervention_hash, lineage.record.id, lineage.diagnosis.id,
                     lineage.diagnosis_record.id, lineage.claim.idempotency_key, receipt.id, receipt.operation_key,
                     receipt.attempt, lineage.requirement.id),
                 "observation plan does not bind the exact executed lineage")
        _require(plan.observation_start == observation_start(receipt.completed_at or receipt.created_at)
                 and plan.policy_version == POLICY_VERSION and plan.verifier_identity == VERIFIER,
                 "observation plan boundary or policy is not the application's")

    def _latest_post_score(self, conn, plan: m.ObservationPlan):
        """Newest persisted post-boundary score and the count so far (cheap pre-check, no artifacts)."""
        start = plan.observation_start.isoformat()
        row = conn.execute("SELECT COUNT(*) AS n, MAX(scored_at) AS latest FROM health_score "
                           "WHERE equipment_id=? AND scored_at>=?", (plan.asset_id, start)).fetchone()
        return int(row["n"]), row["latest"]

    # ---------------------------------------------------------- evidence
    def _window_parameters(self, plan: m.ObservationPlan, end_at: datetime) -> dict:
        return {"start_at": plan.observation_start, "end_at": end_at, "sample_limit": int(plan.policy_parameters["sample_limit"])}

    def _current_generation(self, artifacts, plan: m.ObservationPlan, capability: str):
        """The newest, not superseded outcome evidence of one capability for this plan's window start."""
        requests = {item.id: item for item in artifacts if isinstance(item, m.EvidenceRequest)}
        superseded = {getattr(item, "supersedes_id", None) for item in artifacts}
        start = plan.observation_start.isoformat()
        current = [item for item in artifacts if isinstance(item, m.Evidence) and item.id not in superseded
                   and item.source_capability == capability and item.equipment_ids == (plan.asset_id,)
                   and item.request_id in requests and requests[item.request_id].required_for == "outcome"
                   and str(requests[item.request_id].parameters.get("start_at", "")).replace("Z", "+00:00") == start]
        return current[-1].id if current else None

    def _collect(self, incident, plan: m.ObservationPlan, end_at: datetime):
        """Durable outcome evidence (required_for="outcome"), reused when its exact reads are unchanged.

        Each attempt evaluates the bounded window up to the newest persisted score. A
        later window supersedes the previous generation of the same capability, so
        the incident's current evidence never accumulates one record per attempt while
        every generation stays immutable history bound to its own frozen window.
        """
        parameters = self._window_parameters(plan, end_at)
        artifacts = self.repository.list_artifacts(incident.id)
        collections = []
        for capability, question in ((HEALTH_CAPABILITY, HEALTH_QUESTION), (TELEMETRY_CAPABILITY, TELEMETRY_QUESTION)):
            collections.append(self.evidence_service.request_and_collect(
                incident.id, requested_by="application", equipment_ids=(plan.asset_id,), question=question,
                capability=capability, required_for="outcome", parameters=parameters,
                supersedes_evidence_id=self._current_generation(artifacts, plan, capability)))
        return tuple(collections)

    def _bound_evidence(self, conn, incident, plan: m.ObservationPlan, end_at: datetime, evidence_ids):
        """Reload the evidence under the commit lock; refuse anything not exactly the plan's window."""
        loaded = {}
        for key in evidence_ids:
            try:
                evidence = self.repository._artifact(conn, incident.id, key)
            except InvalidReference as exc:
                _require(False, f"outcome evidence is not part of this incident: {exc}")
            _require(isinstance(evidence, m.Evidence) and evidence.equipment_ids == (plan.asset_id,),
                     "outcome evidence must belong to the exact observed asset")
            _require(evidence.content_hash == content_hash(evidence.payload), "outcome evidence payload hash mismatch")
            _require(manifest_authority(evidence) is None and evidence.source_dependencies is not None
                     and evidence.source_dependencies.basis == "SOURCE_QUERY", "outcome evidence must be an application source read")
            _require(evidence.request_id is not None, "outcome evidence lacks its durable request")
            request = self.repository._artifact(conn, incident.id, evidence.request_id)
            expected = self.evidence_service.capabilities.validate_parameters(
                evidence.source_capability, self._window_parameters(plan, end_at))
            _require(isinstance(request, m.EvidenceRequest) and request.required_for == "outcome"
                     and request.equipment_ids == (plan.asset_id,) and request.capability == evidence.source_capability
                     and request.parameters == expected,
                     "outcome evidence request is not bound to the frozen observation window")
            # Outcome authority is application-owned: enforced here, not only by specialist capability allowlists.
            _require(request.requested_by == "application",
                     "outcome evidence must be requested by the application, not a specialist")
            try:
                self.promotion._current(conn, incident.id, evidence)
            except PromotionRefused:
                _require(False, "outcome evidence has been superseded")
            loaded[evidence.source_capability] = evidence
        _require(HEALTH_CAPABILITY in loaded, "outcome verification requires the health-score window evidence")
        changes = []
        for evidence in loaded.values():
            changes.extend(revalidate(conn, evidence.source_dependencies))
        if changes:
            return loaded, tuple(dict.fromkeys(item.reason for item in changes))
        return loaded, ()

    # -------------------------------------------------------------- verify
    def _verification(self, incident, disposition, result, reason, **extra) -> OutcomeVerification:
        return OutcomeVerification(incident_id=incident.id, phase=incident.phase, revision=incident.revision,
                                   disposition=disposition, result=result, reason=reason, **extra)

    def _settled(self, incident, outcome: m.Outcome) -> OutcomeVerification:
        disposition = DISPOSITIONS[outcome.result][0]
        return self._verification(incident, disposition, outcome.result, outcome.reason, plan_id=outcome.plan_id,
                                  outcome_id=outcome.id, evidence_ids=outcome.verification_evidence_ids,
                                  checks=outcome.checks, post_score_count=int(outcome.after_metrics.get("post_score_count", 0)))

    def verify(self, incident_id: str) -> OutcomeVerification:
        # Phase A: read snapshot (no lock). Terminal incidents answer from their durable outcome.
        proposed = None
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase == m.IncidentPhase.CLOSED:
                outcome = self._final(conn, incident)
                return self._settled(incident, outcome)
            _require(incident.phase == m.IncidentPhase.OBSERVING,
                     f"outcome verification requires OBSERVING, found {incident.phase.value}", authority=False)
            lineage = self._executed(conn, incident)
            plan = self._plan_for(conn, incident, lineage.receipt.id)
            if plan is not None:
                self._check_plan(plan, lineage, incident)
                existing = self._outcome_for(conn, incident, plan.id)
                _require(existing is None, "an authoritative outcome exists while the incident is still OBSERVING; "
                                           "reconciliation is required and no closure is inferred")
            else:
                baseline = self._baseline(conn, incident, lineage, lineage.receipt.completed_at or lineage.receipt.created_at)
                if baseline is None:
                    return self._verification(incident, "OBSERVING", "INCONCLUSIVE",
                                              "no durable pre-intervention model signal exists in the promoted diagnosis packet; "
                                              "no comparison baseline can be frozen")
                proposed = self._build_plan(incident, lineage, baseline)
        if proposed is not None:
            # The read snapshot is closed: the plan commit is its own short transaction.
            plan = self._persist_plan(incident_id, proposed)
            if plan is None:
                return self._verification(self.repository.fetch_incident(incident_id), "RETRY", None,
                                          "observation plan changed concurrently")
        # Phase B: cheap maturity pre-check; immature windows write nothing.
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            count, latest = self._latest_post_score(conn, plan)
            incident = self.repository._fetch(conn, incident_id)
        minimum = int(plan.policy_parameters["minimum_post_scores"])
        if count < minimum or latest is None:
            return self._verification(incident, "OBSERVING", "INCONCLUSIVE",
                                      f"{count} post-intervention score(s) persisted since {plan.observation_start.isoformat()}; "
                                      f"policy requires {minimum}", plan_id=plan.id, post_score_count=count)
        end_at = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=plan.observation_start.tzinfo)
        # Phase C: durable evidence for the frozen window [observation_start, newest post score]; no lock held.
        try:
            health, telemetry = self._collect(incident, plan, end_at)
        except (StaleRevision, DuplicateRecord) as exc:
            return self._verification(incident, "RETRY", None, f"outcome evidence collection contended: {exc}", plan_id=plan.id)
        evidence_ids = (health.evidence.id, telemetry.evidence.id)
        # Phase D: deterministic evaluation of what was persisted.
        decision = evaluate(plan, health.result, telemetry.result if telemetry.evidence.quality != "MISSING" else None)
        incident = self.repository.fetch_incident(incident_id)
        if decision.result == "INCONCLUSIVE":
            return self._verification(incident, "OBSERVING", "INCONCLUSIVE", decision.reason, plan_id=plan.id,
                                      evidence_ids=evidence_ids, checks=decision.checks, post_score_count=decision.post_score_count)
        # Phase E: atomic authority: revalidate everything under the lock, re-derive, persist outcome + phase together.
        return self._commit(incident_id, plan, end_at, evidence_ids, decision)

    def _final(self, conn, incident) -> m.Outcome:
        outcomes = [item for item in self.promotion._all(conn, incident.id, m.Outcome) if item.result == "VERIFIED_RECOVERY"]
        _require(len(outcomes) == 1 and outcomes[0].verifier_identity == VERIFIER, "closed incident lacks its verified outcome")
        return outcomes[0]

    def _persist_plan(self, incident_id, plan: m.ObservationPlan):
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase != m.IncidentPhase.OBSERVING:
                return None
            lineage = self._executed(conn, incident)
            existing = self._plan_for(conn, incident, lineage.receipt.id)
            if existing is not None:
                self._check_plan(existing, lineage, incident)
                return existing
            self._check_plan(plan, lineage, incident)
            self.lifecycle._checkpoint(conn, incident, [plan], events=[("OBSERVATION_PLANNED", {
                "plan_id": plan.id, "receipt_id": plan.receipt_id, "intervention_id": plan.intervention_id,
                "intervention_hash": plan.intervention_hash, "promotion_id": plan.promotion_id,
                "observation_start": plan.observation_start.isoformat(), "policy_version": POLICY_VERSION,
                "baseline_evidence_ids": list(plan.baseline_evidence_ids)})])
            # Return the durable form so every later comparison is against stored bytes.
            return self.repository._artifact(conn, incident.id, plan.id)

    def _commit(self, incident_id, plan: m.ObservationPlan, end_at, evidence_ids, decision: OutcomeDecision) -> OutcomeVerification:
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase != m.IncidentPhase.OBSERVING:
                settled = self._outcome_for(conn, incident, plan.id)
                if settled is not None:
                    return self._settled(incident, settled)  # another worker decided first: idempotent
                return self._verification(incident, "RETRY", None, f"incident left OBSERVING ({incident.phase.value}) without an outcome")
            lineage = self._executed(conn, incident)
            stored = self._plan_for(conn, incident, lineage.receipt.id)
            _require(stored is not None and stored == plan, "observation plan is not the durable plan for the executed receipt")
            _require(self._outcome_for(conn, incident, plan.id) is None,
                     "an authoritative outcome already exists for this observation plan")
            loaded, stale = self._bound_evidence(conn, incident, plan, end_at, evidence_ids)
            if stale:
                return self._verification(incident, "RETRY", None, "outcome evidence changed before commit: " + ", ".join(stale),
                                          plan_id=plan.id, evidence_ids=tuple(evidence_ids))
            health = HealthScoreWindow.model_validate(loaded[HEALTH_CAPABILITY].payload)
            telemetry_evidence = loaded.get(TELEMETRY_CAPABILITY)
            telemetry = (TelemetryWindow.model_validate(telemetry_evidence.payload)
                         if telemetry_evidence is not None and telemetry_evidence.quality != "MISSING" else None)
            derived = evaluate(plan, health, telemetry)
            if derived != decision or derived.result == "INCONCLUSIVE":
                return self._verification(incident, "RETRY", None, "persisted evidence no longer supports the collected decision",
                                          plan_id=plan.id, evidence_ids=tuple(evidence_ids))
            disposition, phase = DISPOSITIONS[derived.result]
            simulated = any(item.provenance == "SIMULATED" for item in loaded.values())
            signal = m.ModelSignal.model_validate(self.repository._artifact(conn, incident.id, plan.baseline_signal_evidence_id).payload)
            simulated = simulated or signal.input_provenance == "SIMULATED"
            now = utcnow()
            outcome = m.Outcome(
                id=new_id(), incident_id=incident.id, created_at=now, equipment_ids=(plan.asset_id,), asset_id=plan.asset_id,
                plan_id=plan.id, diagnosis_id=plan.diagnosis_id, diagnosis_promotion_id=plan.diagnosis_promotion_id,
                intervention_id=plan.intervention_id, intervention_hash=plan.intervention_hash, promotion_id=plan.promotion_id,
                execution_claim_key=plan.execution_claim_key, execution_receipt_ids=(plan.receipt_id,), result=derived.result,
                basis="SIMULATED" if simulated else "OBSERVED", verification_evidence_ids=tuple(evidence_ids),
                observation_start=plan.observation_start, observation_end=end_at, verified_at=now,
                before_metrics=plan.baseline_metrics, after_metrics=derived.after_metrics, checks=derived.checks,
                reason=derived.reason,
                estimated_avoided_loss=lineage.intervention.estimated_avoided_loss if derived.result == "VERIFIED_RECOVERY" else None,
                measured_cost=None, diagnosis_confirmed=None,
                lesson=LESSONS[derived.result])
            changes = {"active_run_id": None}
            if derived.result != "VERIFIED_RECOVERY":
                # The executed intervention is consumed: it is never current authority again
                # and any new intervention must earn the full promotion/approval/execution chain.
                changes["current_intervention_id"] = None
            reason = REASONS[derived.result]
            updated = self.lifecycle._checkpoint(conn, incident, [outcome], phase=phase, reason=reason, events=[("OUTCOME_RECORDED", {
                "outcome_id": outcome.id, "result": outcome.result, "plan_id": plan.id, "intervention_id": plan.intervention_id,
                "intervention_hash": plan.intervention_hash, "promotion_id": plan.promotion_id, "receipt_id": plan.receipt_id,
                "execution_claim_key": plan.execution_claim_key, "evidence_ids": list(evidence_ids),
                "observation_start": plan.observation_start.isoformat(), "observation_end": end_at.isoformat(),
                "policy_version": POLICY_VERSION, "verifier_identity": VERIFIER, "reason": derived.reason,
                "checks": derived.checks})], **changes)
            return self._verification(updated, disposition, derived.result, derived.reason, plan_id=plan.id, outcome_id=outcome.id,
                                      evidence_ids=tuple(evidence_ids), checks=derived.checks, post_score_count=derived.post_score_count)


LESSONS = {
    "VERIFIED_RECOVERY": "Post-intervention persisted risk scores returned to the healthy band; the modelled risk that admitted "
                         "the incident is no longer present. Physical repair quality was not independently measured.",
    "NOT_RECOVERED": "Persisted risk stayed elevated for the whole observation budget after a confirmed work package; the "
                     "diagnosis and intervention require re-investigation through the full authority chain.",
    "REGRESSED": "Persisted risk stayed in the critical band for the settled tail and rose above the pre-intervention "
                 "baseline after execution; human "
                 "escalation is required and no further consequential action is taken automatically.",
}
REASONS = {
    "VERIFIED_RECOVERY": "deterministic outcome policy verified recovery from durable post-intervention evidence",
    "NOT_RECOVERED": "deterministic outcome policy found no recovery; re-investigation required",
    "REGRESSED": "deterministic outcome policy detected post-intervention regression; escalated",
}
