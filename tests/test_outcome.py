"""Step 14 adversarial tests: outcome verification and autonomous closure.

Every scenario runs the real promotion lineage, approval, execution claim/receipt
and the real deterministic verifier against an isolated SQLite store. Nothing mocks
authority. Timestamps are written explicitly (no wall-clock sleeps): post-intervention
scores are stamped after the durable observation boundary derived from the receipt.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

import pytest

from core import db
from core.reliability import models as m
from core.reliability import outcome as oc
from core.reliability.execution import GovernedExecutor
from core.reliability.freshness import revalidate
from core.reliability.governance import ApprovalLedger, artifact_hash
from core.reliability.legacy import prepare_legacy_intervention
from core.reliability.lifecycle import (
    AuthorityRefused, ExecutionRefused, LifecycleRefused, LifecycleService,
)
from core.reliability.repository import IncidentRepository, InvalidReference, new_id, utcnow
from tests.conftest import sample_proposal
from tests.test_freshness import write_readings
from tests.test_promotion import ASSET, revision, state
from tests.test_reliability_lifecycle import Flow, RecordingCmms, counts, use_cmms

MACHINE_B = "CNC-MILL-07"
HEALTHY = (0.12, 0.10, 0.08)
BASELINE_RISK = 0.91  # tests.test_incident_state.signal()


@pytest.fixture
def flow(seeded_db):
    return Flow()


def write_scores(path, asset_id, probs, *, start, step=timedelta(seconds=1), mode="OSF"):
    """Persist classifier scores exactly as the engine does (equipment, scored_at, health, risk, mode)."""
    with db.get_conn(path) as conn:
        for offset, prob in enumerate(probs):
            conn.execute("INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) "
                         "VALUES (?,?,?,?,?)", (asset_id, (start + offset * step).isoformat(), 1 - prob, prob, mode))


def observing(flow, monkeypatch=None, adapter=None):
    """READY -> execute -> OBSERVING with a CONFIRMED receipt. Returns (intervention, receipt)."""
    if adapter is not None:
        use_cmms(monkeypatch, adapter)
    intervention, *_ = flow.ready()
    report = flow.lifecycle.execute(flow.incident_id, intervention.id, intervention_hash=artifact_hash(intervention))
    assert report.phase == m.IncidentPhase.OBSERVING
    receipt = flow.repo.get_execution_receipt(flow.incident_id, report.receipt_ids[-1])
    assert receipt.status == "CONFIRMED"
    return intervention, receipt


def boundary(receipt):
    return oc.observation_start(receipt.completed_at)


def post(flow, receipt, probs, *, offset=1):
    """Scores stamped strictly inside the post-intervention window."""
    write_scores(flow.repo.path, ASSET, probs, start=boundary(receipt) + timedelta(seconds=offset))


def verify(flow):
    return flow.lifecycle.verify_outcome(flow.incident_id)


def outcomes(flow):
    return flow.kinds(m.Outcome)


def plans(flow):
    return flow.kinds(m.ObservationPlan)


def events(flow, kind):
    return [e for e in flow.repo.list_events(flow.incident_id) if e.event_type == kind]


# ------------------------------------------------------------ execution != outcome

def test_confirmed_execution_enters_observing_and_never_closes_by_itself(flow):
    intervention, receipt = observing(flow)
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.OBSERVING and not outcomes(flow) and not plans(flow)
    first = verify(flow)
    assert first.disposition == "OBSERVING" and first.result == "INCONCLUSIVE" and first.outcome_id is None
    assert first.post_score_count == 0 and "requires 3" in first.reason
    # The plan is the only durable write: it freezes boundary, baseline and exact lineage before any authority.
    plan, = plans(flow)
    assert first.plan_id == plan.id and plan.receipt_id == receipt.id and plan.confirmed_at == receipt.completed_at
    assert plan.observation_start == boundary(receipt) > receipt.completed_at
    assert (plan.intervention_id, plan.intervention_hash, plan.execution_claim_key) == (
        intervention.id, artifact_hash(intervention), receipt.idempotency_key)
    assert plan.baseline_metrics["risk_score"] == BASELINE_RISK and plan.baseline_signal_evidence_id == flow.signal_id
    assert plan.policy_version == oc.POLICY_VERSION and plan.verifier_identity == oc.VERIFIER
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)
    assert events(flow, "OBSERVATION_PLANNED") and not events(flow, "INCIDENT_CLOSED")


def test_execution_receipt_alone_never_creates_an_outcome_and_immature_attempts_write_nothing(flow):
    _, receipt = observing(flow)
    verify(flow)
    before = state(flow), counts(flow.repo)
    for _ in range(3):
        result = verify(flow)
        assert result.result == "INCONCLUSIVE" and result.outcome_id is None
    assert (state(flow), counts(flow.repo)) == before  # no evidence, no events, no revision churn
    assert not [a for a in flow.repo.list_artifacts(flow.incident_id)
                if isinstance(a, m.EvidenceRequest) and a.required_for == "outcome"]
    # Recovery reconstructs OBSERVING with its exact lineage; it never verifies or closes.
    status = LifecycleService(IncidentRepository(flow.repo.path)).recover()
    status = next(item for item in status if item.incident_id == flow.incident_id)
    assert status.phase == m.IncidentPhase.OBSERVING and status.execution_lineage_valid and status.plan_id
    assert status.outcome_id is None and status.receipt_ids == (receipt.id,) and not status.reconciliation_required


def test_pre_execution_samples_cannot_prove_recovery_and_later_samples_can(flow):
    _, receipt = observing(flow)
    # Healthy scores and telemetry stamped before (and in the same second as) confirmation.
    write_scores(flow.repo.path, ASSET, (0.05, 0.05, 0.05, 0.05), start=receipt.completed_at - timedelta(seconds=3))
    write_scores(flow.repo.path, ASSET, (0.05,), start=receipt.completed_at.replace(microsecond=0))
    write_readings(flow.repo.path, ASSET, (1.0, 1.0, 1.0), start=receipt.completed_at - timedelta(seconds=3))
    result = verify(flow)
    assert result.result == "INCONCLUSIVE" and result.post_score_count == 0 and not outcomes(flow)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING
    # Two post-boundary scores are still insufficient; the third settles the tail.
    post(flow, receipt, HEALTHY[:2])
    result = verify(flow)
    assert result.result == "INCONCLUSIVE" and result.post_score_count == 2 and not outcomes(flow)
    post(flow, receipt, HEALTHY[2:], offset=3)
    result = verify(flow)
    assert result.disposition == "CLOSED" and result.result == "VERIFIED_RECOVERY" and result.outcome_id
    assert result.post_score_count == 3 and flow.incident().phase == m.IncidentPhase.CLOSED


def test_verified_recovery_closes_atomically_with_full_lineage(flow):
    intervention, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    before_revision = revision(flow)
    result = verify(flow)
    incident = flow.incident()
    outcome, = outcomes(flow)
    plan, = plans(flow)
    assert incident.phase == m.IncidentPhase.CLOSED and result.outcome_id == outcome.id
    assert incident.current_intervention_id == intervention.id and incident.active_run_id is None
    # Evidence collection advanced the revision through the public path; the outcome,
    # the phase change and the closure events then commit together in one final revision.
    assert incident.revision > before_revision
    closed = events(flow, "INCIDENT_CLOSED")
    recorded = events(flow, "OUTCOME_RECORDED")
    assert len(closed) == len(recorded) == 1 and closed[0].revision == recorded[0].revision == incident.revision
    final = {e.event_type for e in flow.repo.list_events(flow.incident_id) if e.revision == incident.revision}
    assert final == {"ARTIFACT_ADDED", "PHASE_CHANGED", "OUTCOME_RECORDED", "INCIDENT_CLOSED"}
    assert closed[0].payload["outcome_id"] == outcome.id and recorded[0].payload["policy_version"] == oc.POLICY_VERSION
    promotion = flow.service.promotion_lineage(flow.incident_id, intervention.id, "intervention", require_current=False)
    assert (outcome.intervention_id, outcome.intervention_hash, outcome.promotion_id) == (
        intervention.id, artifact_hash(intervention), promotion.id)
    assert (outcome.diagnosis_id, outcome.diagnosis_promotion_id) == (intervention.diagnosis_id, promotion.source_diagnosis_promotion_id)
    assert outcome.execution_claim_key == receipt.idempotency_key and outcome.execution_receipt_ids == (receipt.id,)
    assert outcome.plan_id == plan.id and outcome.observation_start == plan.observation_start
    assert outcome.result == "VERIFIED_RECOVERY" and outcome.verifier_identity == oc.VERIFIER
    assert outcome.before_metrics["risk_score"] == BASELINE_RISK and outcome.after_metrics["risk_latest"] == HEALTHY[-1]
    assert outcome.basis == "SIMULATED" and outcome.diagnosis_confirmed is None and outcome.measured_cost is None
    assert outcome.estimated_avoided_loss == intervention.estimated_avoided_loss
    # Verification evidence is durable, application-requested for the outcome, and bound to the window.
    evidence = {a.id: a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.Evidence)}
    used = [evidence[key] for key in outcome.verification_evidence_ids]
    assert {e.kind for e in used} == {"health_score", "telemetry"} and all(e.equipment_ids == (ASSET,) for e in used)
    requests = {a.id: a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.EvidenceRequest)}
    for item in used:
        request = requests[item.request_id]
        assert request.required_for == "outcome" and request.requested_by == "application"
        assert request.parameters["start_at"].replace("Z", "+00:00") == plan.observation_start.isoformat()
    # Receipts were bound, but they are not evidence.
    assert receipt.id not in outcome.verification_evidence_ids
    assert flow.lifecycle.status(flow.incident_id).outcome_result == "VERIFIED_RECOVERY"


def test_health_score_window_capability_is_bounded_and_replayable(flow):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    start = boundary(receipt)
    window = flow.evidence_service.capabilities.get_health_score_window(ASSET, start_at=start, end_at=start + timedelta(seconds=10))
    assert [p.failure_prob for p in window.scores] == list(HEALTHY) and window.availability.value == "AVAILABLE"
    collection = flow.evidence_service.request_and_collect(
        flow.incident_id, requested_by="application", equipment_ids=(ASSET,), question="q",
        capability="get_health_score_window", required_for="outcome",
        parameters={"start_at": start, "end_at": start + timedelta(seconds=10), "sample_limit": 50})
    evidence = collection.evidence
    assert evidence.kind == "health_score" and evidence.provenance == "SIMULATED" and evidence.quality == "GOOD"
    assert [d.domain for d in evidence.source_dependencies.dependencies] == ["health_score_window"]
    # Later scores do not stale the bounded window; a mutation inside it does.
    write_scores(flow.repo.path, ASSET, (0.9,), start=start + timedelta(seconds=30))
    with db.get_conn(flow.repo.path) as conn:
        assert revalidate(conn, evidence.source_dependencies) == ()
        conn.execute("UPDATE health_score SET failure_prob=0.5 WHERE equipment_id=? AND failure_prob=?", (ASSET, HEALTHY[1]))
    with db.get_conn(flow.repo.path) as conn:
        assert [c.dependency.domain for c in revalidate(conn, evidence.source_dependencies)] == ["health_score_window"]


# -------------------------------------------------------------- not recovered

def test_persistently_elevated_risk_is_not_recovered_and_preserves_history(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms())
    intervention, receipt = observing(flow)
    post(flow, receipt, (0.85,) * 5)
    settling = verify(flow)
    assert settling.result == "INCONCLUSIVE" and "still settling" in settling.reason and not outcomes(flow)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING
    post(flow, receipt, (0.85,) * 7, offset=6)
    before = counts(flow.repo)
    result = verify(flow)
    incident = flow.incident()
    assert result.disposition == "REINVESTIGATE" and result.result == "NOT_RECOVERED"
    assert incident.phase == m.IncidentPhase.INVESTIGATING and incident.current_intervention_id is None
    assert incident.current_diagnosis_id == intervention.diagnosis_id
    outcome, = outcomes(flow)
    assert outcome.result == "NOT_RECOVERED" and outcome.execution_receipt_ids == (receipt.id,)
    assert outcome.estimated_avoided_loss is None and "budget" in outcome.reason
    assert not events(flow, "INCIDENT_CLOSED") and len(events(flow, "OUTCOME_RECORDED")) == 1
    # History is intact: diagnosis, intervention, approval, claim, receipt, and the failed outcome evidence.
    assert flow.repo.get_artifact(flow.incident_id, intervention.id).status == "VALIDATED"
    assert flow.repo.get_execution_claim(receipt.idempotency_key).state == "CONFIRMED"
    assert [r.id for r in flow.repo.list_execution_receipts(flow.incident_id)] == [receipt.id]
    assert len(flow.repo.list_approval_decisions(flow.incident_id)) == 1
    assert counts(flow.repo) == before and adapter.calls == 1
    # The previous intervention never executes again silently: every command refuses.
    with pytest.raises(ExecutionRefused):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    with pytest.raises(LifecycleRefused):
        flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    with pytest.raises(ExecutionRefused):
        flow.lifecycle.retry_execution(flow.incident_id, expected_revision=revision(flow))
    current = flow.incident()
    for target in ("DIAGNOSIS_VALIDATED", "PLANNING", "INTERVENTION_VALIDATED", "AWAITING_APPROVAL", "READY"):
        current = flow.repo.transition(current.id, m.IncidentPhase(target), expected_revision=current.revision, reason="graph only")
    with pytest.raises(AuthorityRefused, match="no current promoted intervention"):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert adapter.calls == 1 and counts(flow.repo)["work_package"] == 1
    # A healthy stream afterwards cannot overwrite the recorded failure with a verified recovery.
    post(flow, receipt, HEALTHY, offset=30)
    with pytest.raises(LifecycleRefused, match="requires OBSERVING"):
        verify(flow)
    assert [o.result for o in outcomes(flow)] == ["NOT_RECOVERED"]


async def test_new_intervention_after_failed_outcome_requires_the_full_authority_chain(flow, monkeypatch):
    from core.agents.contracts import SupervisorResult
    from tests.test_promotion import result_payload
    intervention, receipt = observing(flow)
    post(flow, receipt, (0.85,) * 12)
    assert verify(flow).result == "NOT_RECOVERED"
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING
    # The executed work order changed the asset's maintenance history, so the old
    # trusted confirmation's support is stale and a new run cannot promote without
    # fresh trusted evidence; nothing is inherited from the consumed intervention.

    async def invoke(runtime, service, context, **kwargs):
        snapshot = next(a for a in flow.repo.list_artifacts(flow.incident_id)
                        if isinstance(a, m.SupervisorRunSnapshot) and a.run_id == context.run_id)
        flow.history_id = next(key for key in snapshot.evidence_manifest
                               if flow.repo.get_artifact(flow.incident_id, key).kind == "maintenance_history")
        return SupervisorResult.model_validate(result_payload(flow, snapshot))
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime,
                                            evidence_service=flow.evidence_service)
    assert outcome.disposition == "NEEDS_EVIDENCE" and flow.incident().phase == m.IncidentPhase.AWAITING_EVIDENCE
    assert flow.incident().current_intervention_id is None
    assert counts(flow.repo)["execution_claim"] == 1 and counts(flow.repo)["work_package"] == 1
    # Baseline refresh for the re-investigation sees the post-intervention evidence as memory.
    current = set(flow.lifecycle.current_evidence_ids(flow.incident_id, ASSET))
    outcome_evidence = {a.id for a in flow.repo.list_artifacts(flow.incident_id)
                        if isinstance(a, m.Evidence) and a.kind == "health_score"}
    assert outcome_evidence & current


# ------------------------------------------------------------------ regression

def test_regression_escalates_without_closure_or_new_action(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms())
    intervention, receipt = observing(flow)
    post(flow, receipt, (0.97, 0.98, 0.99))
    before = counts(flow.repo)
    result = verify(flow)
    incident = flow.incident()
    assert result.disposition == "ESCALATED" and result.result == "REGRESSED"
    assert incident.phase == m.IncidentPhase.ESCALATED and incident.current_intervention_id is None
    outcome, = outcomes(flow)
    assert outcome.result == "REGRESSED" and outcome.checks["regressed"] and outcome.after_metrics["risk_latest"] == 0.99
    assert outcome.checks["tail_critical"] and outcome.checks["latest_exceeds_baseline_margin"]
    assert "all critical" in outcome.reason and "exceeds the baseline" in outcome.reason
    assert events(flow, "INCIDENT_ESCALATED") and not events(flow, "INCIDENT_CLOSED")
    assert counts(flow.repo) == before and adapter.calls == 1
    with pytest.raises(ExecutionRefused):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    # Evidence explaining the regression is durable and attributable.
    evidence = [flow.repo.get_artifact(flow.incident_id, key) for key in outcome.verification_evidence_ids]
    assert all(e.equipment_ids == (ASSET,) and e.incident_id == flow.incident_id for e in evidence)


def test_policy_is_deterministic_explicit_and_conservative():
    parameters = oc.policy_parameters()
    assert parameters["recovery_risk_max"] == 0.45 and parameters["elevated_risk_min"] == 0.80
    now = utcnow()
    plan_fields = dict(id="plan", incident_id="i", created_at=now, equipment_ids=(ASSET,), asset_id=ASSET, diagnosis_id="d",
                       diagnosis_promotion_id="dp", intervention_id="iv", intervention_hash="h", promotion_id="p",
                       approval_requirement_id="r", approval_decision_ids=("a",), execution_claim_key="k", receipt_id="rc",
                       receipt_operation_key="ok", receipt_attempt=1, confirmed_at=now, observation_start=oc.observation_start(now),
                       baseline_signal_evidence_id="s", baseline_evidence_ids=("s",), baseline_metrics={"risk_score": 0.91, "health_score": 0.09},
                       policy_parameters=parameters)
    plan = m.ObservationPlan(**plan_fields)
    from core.reliability.evidence import EvidenceCapabilities

    def window(probs):
        start = plan.observation_start
        return EvidenceCapabilities().parse_result("get_health_score_window", {
            "asset_id": ASSET, "requested_start": start.isoformat(), "requested_end": (start + timedelta(seconds=len(probs))).isoformat(),
            "requested_sample_limit": 120, "availability": "AVAILABLE" if len(probs) > 1 else "PARTIAL",
            "scores": [{"asset_id": ASSET, "score_id": n, "scored_at": (start + timedelta(seconds=n)).isoformat(),
                        "health_score": 1 - p, "failure_prob": p, "predicted_mode": None} for n, p in enumerate(probs)],
            "risk_statistics": {"sample_count": len(probs), "trend": "STABLE"}, "health_statistics": {"sample_count": len(probs), "trend": "STABLE"},
            "provenance": {"capability": "get_health_score_window", "source_system": "operon.sqlite", "source_tables": ["health_score"],
                           "data_origins": ["MODEL_PRODUCED"], "collected_at": now.isoformat(), "parameters": {}, "locator": "x"}})
    cases = {
        (): "INCONCLUSIVE", (0.1, 0.1): "INCONCLUSIVE", (0.1, 0.1, 0.1): "VERIFIED_RECOVERY",
        (0.9, 0.5, 0.1): "INCONCLUSIVE", (0.9, 0.1, 0.1, 0.1): "VERIFIED_RECOVERY", (0.1, 0.1, 0.449): "VERIFIED_RECOVERY",
        (0.1, 0.1, 0.45): "INCONCLUSIVE", (0.85,) * 11: "INCONCLUSIVE", (0.85,) * 12: "NOT_RECOVERED",
        (0.5,) * 12: "NOT_RECOVERED", (0.1,) * 11 + (0.5,): "NOT_RECOVERED", (0.9, 0.1) * 6: "NOT_RECOVERED", (0.9, 0.9, 0.95): "INCONCLUSIVE",
        (0.9, 0.9, 0.97): "REGRESSED", (0.99, 0.1, 0.1): "INCONCLUSIVE",
        # Regression needs the whole settled tail critical AND the latest above baseline + margin (0.96).
        (0.1, 0.1, 0.99): "INCONCLUSIVE",                    # single anomalous tick after healthy samples
        (0.5, 0.5, 0.99): "INCONCLUSIVE",                    # single spike after settling samples
        (0.1, 0.1, 0.5, 0.99): "INCONCLUSIVE",               # spike after a healthy-then-settling run
        (0.5, 0.97, 0.99): "INCONCLUSIVE",                   # two critical of the three required
        (0.85, 0.85, 0.80, 0.97): "REGRESSED",               # exactly the minimum critical tail, latest >= 0.96
        (0.1, 0.8, 0.85, 0.97): "REGRESSED",                 # earlier healthy history does not shield a persistent tail
        (0.99, 0.99, 0.95): "INCONCLUSIVE",                  # full critical tail but latest below baseline + margin
        (0.97, 0.97, 0.959): "INCONCLUSIVE",                 # margin is judged on the latest score only
        (0.5,) * 11 + (0.99,): "NOT_RECOVERED",              # single spike at the budget is still just no recovery
        (0.85,) * 11 + (0.99,): "REGRESSED",                 # persistent critical tail at the budget escalates instead
        (0.97,) * 12: "REGRESSED",
    }
    for probs, expected in cases.items():
        decision = oc.evaluate(plan, window(probs))
        assert decision.result == expected, (probs, decision.reason)
        assert decision == oc.evaluate(plan, window(probs))  # deterministic
        assert decision.checks and decision.reason
        if len(probs) >= 3:
            tail = probs[-3:]
            assert decision.checks["tail_critical"] is all(risk >= 0.80 for risk in tail)
            assert decision.checks["latest_exceeds_baseline_margin"] is (probs[-1] >= 0.91 + 0.05)
            assert decision.checks["regressed"] is (decision.checks["tail_critical"] and decision.checks["latest_exceeds_baseline_margin"])
            assert (decision.result == "REGRESSED") is decision.checks["regressed"]
    spike = oc.evaluate(plan, window((0.1, 0.1, 0.99)))
    assert spike.checks["latest_exceeds_baseline_margin"] and not spike.checks["tail_critical"] and not spike.checks["regressed"]
    assert "still settling" in spike.reason
    # A baseline that was never elevated cannot be "recovered from".
    flat = m.ObservationPlan(**(plan_fields | {"baseline_metrics": {"risk_score": 0.2, "health_score": 0.8}}))
    assert oc.evaluate(flat, window((0.1, 0.1, 0.1))).result == "INCONCLUSIVE"
    # A window that is not the plan's frozen boundary never decides anything.
    other = m.ObservationPlan(**(plan_fields | {"observation_start": plan.observation_start + timedelta(seconds=1),
                                                "confirmed_at": now + timedelta(seconds=1)}))
    assert oc.evaluate(other, window((0.1, 0.1, 0.1))).result == "INCONCLUSIVE"


# ----------------------------------------------------------- exact lineage

def test_outcome_verification_requires_observing(flow):
    flow.ready()
    with pytest.raises(LifecycleRefused, match="requires OBSERVING"):
        verify(flow)
    assert not plans(flow) and not outcomes(flow)


@pytest.mark.parametrize("outcome_kind", ["fail", "unknown"])
def test_failed_or_unknown_execution_never_verifies_recovery(flow, monkeypatch, outcome_kind):
    use_cmms(monkeypatch, RecordingCmms(outcome_kind))
    intervention, *_ = flow.ready()
    with pytest.raises(Exception):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    receipt, = flow.repo.list_execution_receipts(flow.incident_id)
    assert receipt.status == ("FAILED" if outcome_kind == "fail" else "UNKNOWN")
    # Graph-only transitions reach OBSERVING; the verifier binds the claim, not the phase.
    incident = flow.incident()
    for target in ("READY", "EXECUTING", "OBSERVING"):
        incident = flow.repo.transition(incident.id, m.IncidentPhase(target), expected_revision=incident.revision, reason="graph only")
    write_scores(flow.repo.path, ASSET, HEALTHY, start=receipt.created_at + timedelta(seconds=2))
    with pytest.raises(AuthorityRefused, match="only CONFIRMED execution"):
        verify(flow)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow) and not plans(flow)
    assert not flow.lifecycle.status(flow.incident_id).execution_lineage_valid


def test_retry_after_definitive_failure_binds_the_confirmed_attempt(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms("fail"))
    intervention, *_ = flow.ready()
    with pytest.raises(Exception):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    flow.lifecycle.retry_execution(flow.incident_id, expected_revision=revision(flow))
    adapter.outcome = "confirm"
    report = flow.lifecycle.execute(flow.incident_id, intervention.id)
    failed, confirmed = flow.repo.list_execution_receipts(flow.incident_id)
    assert (failed.status, failed.attempt, confirmed.status, confirmed.attempt) == ("FAILED", 1, "CONFIRMED", 2)
    post(flow, confirmed, HEALTHY)
    result = verify(flow)
    plan, = plans(flow)
    assert result.result == "VERIFIED_RECOVERY" and plan.receipt_id == confirmed.id and plan.receipt_attempt == 2
    assert outcomes(flow)[0].execution_receipt_ids == (confirmed.id,)


def test_tampered_claim_state_is_refused(flow):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    with db.get_conn(flow.repo.path) as conn:
        conn.execute("UPDATE execution_claim SET state='FAILED' WHERE idempotency_key=?", (receipt.idempotency_key,))
    with pytest.raises(AuthorityRefused, match="execution claim is FAILED"):
        verify(flow)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)


def test_superseded_or_swapped_intervention_pointer_is_refused(flow):
    intervention, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    draft = next(a for a in flow.kinds(m.Intervention) if a.status == "DRAFT")
    # Pointer swapped to an artifact without promotion lineage (the reviewed draft).
    with flow.repo._write() as conn:
        incident = flow.repo._fetch(conn, flow.incident_id)
        flow.lifecycle._checkpoint(conn, incident, current_intervention_id=draft.id)
    with pytest.raises(AuthorityRefused, match="lineage"):
        verify(flow)
    assert not outcomes(flow) and not plans(flow)
    # Pointer restored, but the executed intervention has been superseded by a newer artifact.
    newer = intervention.model_copy(update={"id": new_id(), "created_at": utcnow(), "supersedes_id": intervention.id,
                                            "revision": intervention.revision + 1})
    with flow.repo._write() as conn:
        incident = flow.repo._fetch(conn, flow.incident_id)
        flow.lifecycle._checkpoint(conn, incident, [newer], current_intervention_id=intervention.id)
    with pytest.raises(AuthorityRefused, match="superseded"):
        verify(flow)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)


def test_legacy_observing_incident_without_promotion_lineage_cannot_verify(flow):
    flow.resources()
    with pytest.warns(DeprecationWarning):
        legacy = prepare_legacy_intervention(flow.repo, flow.incident_id, sample_proposal())
    ApprovalLedger(flow.repo).decide(flow.incident_id, legacy.requirement.id, actor_id="op", actor_role="maintenance_approver",
                                     decision="APPROVE", rationale="legacy demo")
    report = GovernedExecutor(flow.repo).execute(flow.incident_id, legacy.intervention.id)
    assert report.phase == m.IncidentPhase.OBSERVING
    receipt = flow.repo.get_execution_receipt(flow.incident_id, report.receipt_ids[0])
    write_scores(flow.repo.path, ASSET, HEALTHY, start=receipt.created_at + timedelta(seconds=2))
    with pytest.raises(AuthorityRefused, match="no current promoted intervention"):
        verify(flow)
    # The legacy executor's idempotent OBSERVING report still never closes.
    assert GovernedExecutor(flow.repo).execute(flow.incident_id, legacy.intervention.id).phase == m.IncidentPhase.OBSERVING
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)


# ------------------------------------------------------------- evidence scope

def other_incident_evidence(flow, plan, end_at):
    other = flow.repo.create_incident((MACHINE_B,), admission_key="other-machine")
    write_scores(flow.repo.path, MACHINE_B, HEALTHY, start=plan.observation_start + timedelta(seconds=1))
    parameters = {"start_at": plan.observation_start, "end_at": end_at, "sample_limit": int(plan.policy_parameters["sample_limit"])}
    return other, flow.evidence_service.request_and_collect(
        other.id, requested_by="application", equipment_ids=(MACHINE_B,), question=oc.HEALTH_QUESTION,
        capability=oc.HEALTH_CAPABILITY, required_for="outcome", parameters=parameters)


def test_commit_refuses_evidence_from_another_incident(flow, monkeypatch):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    verifier = oc.OutcomeVerifier(flow.lifecycle)
    original = verifier._collect

    def foreign(incident, plan, end_at):
        health, telemetry = original(incident, plan, end_at)
        _, stolen = other_incident_evidence(flow, plan, end_at)
        return type(health)(request=stolen.request, evidence=stolen.evidence, result=health.result), telemetry
    monkeypatch.setattr(verifier, "_collect", foreign)
    with pytest.raises(AuthorityRefused, match="not part of this incident"):
        verifier.verify(flow.incident_id)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)


def test_commit_refuses_evidence_for_another_asset_or_window(flow, monkeypatch):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    verifier = oc.OutcomeVerifier(flow.lifecycle)
    original = verifier._collect

    def relabelled(incident, plan, end_at):
        health, telemetry = original(incident, plan, end_at)
        forged = health.evidence.model_copy(update={"id": new_id(), "equipment_ids": (MACHINE_B,)})
        with db.get_conn(flow.repo.path) as conn:  # bypasses add_artifact scope checks deliberately
            conn.execute("INSERT INTO incident_artifact VALUES (?,?,?,?,?,?,?)",
                         (forged.id, incident.id, "Evidence", 1, forged.created_at.isoformat(), "x", forged.model_dump_json()))
        return type(health)(request=health.request, evidence=forged, result=health.result), telemetry
    monkeypatch.setattr(verifier, "_collect", relabelled)
    with pytest.raises(AuthorityRefused, match="exact observed asset"):
        verifier.verify(flow.incident_id)
    assert not outcomes(flow)

    def other_window(incident, plan, end_at):
        health, telemetry = original(incident, plan, end_at)
        shifted = flow.evidence_service.request_and_collect(
            incident.id, requested_by="application", equipment_ids=(ASSET,), question=oc.HEALTH_QUESTION,
            capability=oc.HEALTH_CAPABILITY, required_for="outcome",
            parameters={"start_at": plan.observation_start - timedelta(seconds=30), "end_at": end_at, "sample_limit": 120})
        return type(health)(request=shifted.request, evidence=shifted.evidence, result=health.result), telemetry
    monkeypatch.setattr(verifier, "_collect", other_window)
    with pytest.raises(AuthorityRefused, match="frozen observation window"):
        verifier.verify(flow.incident_id)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)
    # The untouched verifier still closes from legitimate evidence.
    assert verify(flow).disposition == "CLOSED"


def test_commit_refuses_outcome_evidence_requested_by_a_specialist(flow, monkeypatch):
    """Same asset, capability, window and required_for="outcome", but not requested by the application."""
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    verifier = oc.OutcomeVerifier(flow.lifecycle)
    original = verifier._collect

    def specialist_requested(incident, plan, end_at):
        health, telemetry = original(incident, plan, end_at)
        borrowed = flow.evidence_service.request_and_collect(
            incident.id, requested_by="supervisor", equipment_ids=(ASSET,), question=oc.HEALTH_QUESTION,
            capability=oc.HEALTH_CAPABILITY, required_for="outcome", parameters=verifier._window_parameters(plan, end_at))
        assert borrowed.request.requested_by == "supervisor" and borrowed.request.parameters == health.request.parameters
        return type(health)(request=borrowed.request, evidence=borrowed.evidence, result=health.result), telemetry
    monkeypatch.setattr(verifier, "_collect", specialist_requested)
    with pytest.raises(AuthorityRefused, match="requested by the application"):
        verifier.verify(flow.incident_id)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)
    # The untouched verifier still closes from its own application-requested evidence.
    assert verify(flow).disposition == "CLOSED"


def test_missing_baseline_stays_inconclusive_without_a_plan(flow, monkeypatch):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    monkeypatch.setattr(oc.OutcomeVerifier, "_baseline", lambda self, conn, incident, lineage, confirmed_at: None)
    result = verify(flow)
    assert result.result == "INCONCLUSIVE" and "baseline" in result.reason and result.plan_id is None
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not plans(flow) and not outcomes(flow)


# ---------------------------------------------------------- Step 13C freshness

def test_unrelated_assets_incidents_and_later_samples_do_not_disturb_verification(flow):
    other = flow.repo.create_incident(("HYD-PUMP-03",), admission_key="unrelated-pump")
    _, receipt = observing(flow)
    post(flow, receipt, (0.9, 0.5, 0.1))  # mixed tail: mature but still settling
    result = verify(flow)
    assert result.result == "INCONCLUSIVE" and "still settling" in result.reason and result.evidence_ids
    collected = set(result.evidence_ids)
    artifacts_before = len(flow.repo.list_artifacts(flow.incident_id))
    # Machine B streams, another incident advances, and this asset gets samples after the frozen window.
    write_scores(flow.repo.path, MACHINE_B, (0.99, 0.99, 0.99), start=boundary(receipt) + timedelta(seconds=1))
    write_readings(flow.repo.path, MACHINE_B, (5.0, 6.0), start=boundary(receipt) + timedelta(seconds=1))
    flow.repo.append_event(other.id, "INCIDENT_UPDATED", {"changed": True}, expected_revision=other.revision)
    flow.repo.transition(other.id, m.IncidentPhase.INVESTIGATING, expected_revision=other.revision + 1, reason="unrelated")
    for key in collected:
        with db.get_conn(flow.repo.path) as conn:
            assert revalidate(conn, flow.repo.get_artifact(flow.incident_id, key).source_dependencies) == ()
    again = verify(flow)
    assert again.result == "INCONCLUSIVE" and set(again.evidence_ids) == collected
    assert len(flow.repo.list_artifacts(flow.incident_id)) == artifacts_before  # reused, nothing appended
    # New same-asset scores are a later window generation that supersedes the earlier one; the
    # earlier bounded window itself stays fresh as immutable history.
    post(flow, receipt, HEALTHY, offset=10)
    closed = verify(flow)
    assert closed.disposition == "CLOSED" and not (set(closed.evidence_ids) & collected)
    superseded = {getattr(a, "supersedes_id", None) for a in flow.repo.list_artifacts(flow.incident_id)}
    assert collected <= superseded
    current = set(flow.lifecycle.current_evidence_ids(flow.incident_id, ASSET))
    assert not (collected & current) and set(closed.evidence_ids) & current
    with db.get_conn(flow.repo.path) as conn:
        for key in collected | set(closed.evidence_ids):
            assert revalidate(conn, flow.repo.get_artifact(flow.incident_id, key).source_dependencies) == ()


def test_mutation_inside_the_frozen_window_is_reevaluated_or_refused(flow, monkeypatch):
    _, receipt = observing(flow)
    post(flow, receipt, (0.9, 0.5, 0.1))
    first = verify(flow)
    assert first.result == "INCONCLUSIVE"
    # A row inside the window changes: the earlier evidence is stale and a new generation decides.
    with db.get_conn(flow.repo.path) as conn:
        conn.execute("UPDATE health_score SET failure_prob=0.1, health_score=0.9 WHERE equipment_id=? AND failure_prob IN (0.9, 0.5)", (ASSET,))
    with db.get_conn(flow.repo.path) as conn:
        stale = [key for key in first.evidence_ids
                 if revalidate(conn, flow.repo.get_artifact(flow.incident_id, key).source_dependencies)]
    assert stale
    second = verify(flow)
    assert second.disposition == "CLOSED" and set(second.evidence_ids) != set(first.evidence_ids)
    assert not (set(second.evidence_ids) & set(stale))  # the stale health window was replaced, not reused
    for key in stale:
        assert any(getattr(a, "supersedes_id", None) == key for a in flow.repo.list_artifacts(flow.incident_id))


def test_mutation_between_collection_and_commit_refuses_the_commit(flow, monkeypatch):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    verifier = oc.OutcomeVerifier(flow.lifecycle)
    original = verifier._collect

    def collect_then_mutate(incident, plan, end_at):
        collected = original(incident, plan, end_at)
        with db.get_conn(flow.repo.path) as conn:
            conn.execute("UPDATE health_score SET failure_prob=0.95 WHERE equipment_id=? AND failure_prob=?", (ASSET, HEALTHY[-1]))
        return collected
    monkeypatch.setattr(verifier, "_collect", collect_then_mutate)
    result = verifier.verify(flow.incident_id)
    assert result.disposition == "RETRY" and "changed before commit" in result.reason and result.outcome_id is None
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not outcomes(flow)
    # The clean path re-collects the mutated window and decides from what is actually persisted.
    clean = verify(flow)
    assert clean.result == "INCONCLUSIVE" and not outcomes(flow)


def test_post_closure_source_change_never_reopens_or_rewrites(flow):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    closed = verify(flow)
    assert closed.disposition == "CLOSED"
    before = state(flow)
    with db.get_conn(flow.repo.path) as conn:
        conn.execute("UPDATE health_score SET failure_prob=0.99 WHERE equipment_id=?", (ASSET,))
    write_scores(flow.repo.path, ASSET, (0.99,) * 3, start=boundary(receipt) + timedelta(minutes=5))
    again = verify(flow)
    assert again.disposition == "CLOSED" and again.outcome_id == closed.outcome_id and state(flow) == before
    assert flow.incident().phase == m.IncidentPhase.CLOSED and len(outcomes(flow)) == 1
    # Forensic: the outcome's frozen evidence manifest now reports exactly the changed read.
    with db.get_conn(flow.repo.path) as conn:
        changed = [c.dependency.domain for key in outcomes(flow)[0].verification_evidence_ids
                   for c in revalidate(conn, flow.repo.get_artifact(flow.incident_id, key).source_dependencies)]
    assert "health_score_window" in changed


# ---------------------------------------------------- idempotency / concurrency

def test_duplicate_verification_is_idempotent(flow):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    first = verify(flow)
    before = state(flow), counts(flow.repo)
    for _ in range(3):
        again = verify(flow)
        assert again.disposition == "CLOSED" and again.outcome_id == first.outcome_id
    assert (state(flow), counts(flow.repo)) == before
    assert len(events(flow, "INCIDENT_CLOSED")) == len(events(flow, "OUTCOME_RECORDED")) == len(outcomes(flow)) == 1
    # Restart: a fresh service sees the final state and never re-verifies.
    fresh = LifecycleService(IncidentRepository(flow.repo.path))
    assert flow.incident_id not in {s.incident_id for s in fresh.recover()}
    status = fresh.status(flow.incident_id)
    assert status.phase == m.IncidentPhase.CLOSED and status.outcome_id == first.outcome_id
    assert fresh.verify_outcome(flow.incident_id).outcome_id == first.outcome_id and (state(flow), counts(flow.repo)) == before


def test_concurrent_verification_creates_exactly_one_authoritative_outcome(flow):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    gate = threading.Barrier(2)

    def run(_):
        gate.wait(5)
        try:
            return LifecycleService(IncidentRepository(flow.repo.path)).verify_outcome(flow.incident_id)
        except (AuthorityRefused, LifecycleRefused) as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    outcome, = outcomes(flow)
    decided = [r for r in results if isinstance(r, oc.OutcomeVerification) and r.outcome_id]
    assert decided and all(r.outcome_id == outcome.id for r in decided)
    assert all(isinstance(r, oc.OutcomeVerification) and r.disposition in ("CLOSED", "RETRY") for r in results)
    assert flow.incident().phase == m.IncidentPhase.CLOSED
    assert len(events(flow, "INCIDENT_CLOSED")) == 1 and len(events(flow, "OUTCOME_RECORDED")) == 1
    with db.get_conn(flow.repo.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM incident_artifact WHERE kind='ObservationPlan'").fetchone()[0] == 1


def test_concurrent_conflicting_decisions_cannot_both_commit(flow, monkeypatch):
    """Worker A collected a healthy window; worker B a regressed one. Only the first commit wins."""
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    verifier_a = oc.OutcomeVerifier(flow.lifecycle)
    original = verifier_a._collect
    entered, release = threading.Event(), threading.Event()

    def slow_collect(incident, plan, end_at):
        collected = original(incident, plan, end_at)
        entered.set()
        assert release.wait(5)
        return collected
    monkeypatch.setattr(verifier_a, "_collect", slow_collect)
    results = {}
    thread = threading.Thread(target=lambda: results.update(a=verifier_a.verify(flow.incident_id)))
    thread.start()
    assert entered.wait(5)
    post(flow, receipt, (0.97, 0.98, 0.99), offset=10)  # regression lands while A is between collection and commit
    results["b"] = LifecycleService(IncidentRepository(flow.repo.path)).verify_outcome(flow.incident_id)
    release.set()
    thread.join(5)
    assert results["b"].disposition == "ESCALATED" and results["b"].result == "REGRESSED"
    assert results["a"].disposition in ("ESCALATED", "RETRY") and results["a"].result in ("REGRESSED", None)
    assert [o.result for o in outcomes(flow)] == ["REGRESSED"] and flow.incident().phase == m.IncidentPhase.ESCALATED


# ------------------------------------------------------------------ ownership

def test_callers_cannot_forge_outcome_authority(flow):
    _, receipt = observing(flow)
    verify(flow)
    plan, = plans(flow)
    now = utcnow()
    forged = m.Outcome(
        id=new_id(), incident_id=flow.incident_id, created_at=now, equipment_ids=(ASSET,), asset_id=ASSET, plan_id=plan.id,
        diagnosis_id=plan.diagnosis_id, diagnosis_promotion_id=plan.diagnosis_promotion_id, intervention_id=plan.intervention_id,
        intervention_hash=plan.intervention_hash, promotion_id=plan.promotion_id, execution_claim_key=plan.execution_claim_key,
        execution_receipt_ids=(receipt.id,), result="VERIFIED_RECOVERY", basis="SIMULATED",
        verification_evidence_ids=(flow.signal_id,), observation_start=plan.observation_start,
        observation_end=plan.observation_start, verified_at=now, checks={"forged": True}, reason="forged", lesson="forged")
    before = state(flow)
    with pytest.raises(InvalidReference, match="outcome records require"):
        flow.repo.add_artifact(forged, expected_revision=revision(flow))
    with pytest.raises(InvalidReference, match="outcome records require"):
        flow.repo.add_artifact(plan.model_copy(update={"id": new_id(), "receipt_id": "other"}), expected_revision=revision(flow))
    with pytest.raises(InvalidReference, match="verified outcome authority"):
        flow.repo.transition(flow.incident_id, m.IncidentPhase.CLOSED, expected_revision=revision(flow), reason="forged")
    with pytest.raises(ValueError):
        flow.repo.append_event(flow.incident_id, "INCIDENT_CLOSED", {}, expected_revision=revision(flow))
    with pytest.raises(LifecycleRefused, match="requires the authoritative verified outcome"):
        with flow.repo._write() as conn:
            flow.lifecycle._checkpoint(conn, flow.repo._fetch(conn, flow.incident_id), phase=m.IncidentPhase.CLOSED)
    with pytest.raises(ValueError, match="never an authoritative outcome"):
        m.Outcome.model_validate(forged.model_dump() | {"result": "INCONCLUSIVE"})
    assert state(flow) == before and flow.incident().phase == m.IncidentPhase.OBSERVING
    # A row smuggled around the repository is never closure: the verifier refuses and flags reconciliation.
    with db.get_conn(flow.repo.path) as conn:
        conn.execute("INSERT INTO incident_artifact VALUES (?,?,?,?,?,?,?)",
                     (forged.id, flow.incident_id, "Outcome", 1, now.isoformat(), "x", forged.model_dump_json()))
    post(flow, receipt, HEALTHY)
    with pytest.raises(AuthorityRefused, match="reconciliation is required and no closure is inferred"):
        verify(flow)
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.OBSERVING and not events(flow, "INCIDENT_CLOSED")
    status = flow.lifecycle.status(flow.incident_id)
    assert status.reconciliation_required and status.outcome_id == forged.id
    recovered = next(s for s in LifecycleService(IncidentRepository(flow.repo.path)).recover() if s.incident_id == flow.incident_id)
    assert recovered.phase == m.IncidentPhase.OBSERVING and recovered.reconciliation_required


def test_verification_is_model_free_and_holds_no_lock_during_collection(flow, monkeypatch):
    async def never(*args, **kwargs):
        raise AssertionError("outcome verification must never invoke a model")
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", never)
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)
    verifier = oc.OutcomeVerifier(flow.lifecycle)
    original = verifier._collect
    observed = []

    def collect(incident, plan, end_at):
        with db.get_conn(flow.repo.path) as conn:
            conn.execute("BEGIN IMMEDIATE")  # would block if the verifier held a writer
            observed.append(True)
        return original(incident, plan, end_at)
    monkeypatch.setattr(verifier, "_collect", collect)
    assert verifier.verify(flow.incident_id).disposition == "CLOSED" and observed


def test_migration_007_is_idempotent_and_indexes_exist(seeded_db):
    db.init_schema()
    db.init_schema()
    with db.get_conn() as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"ix_observation_plan_receipt", "ix_outcome_plan", "ix_outcome_incident"} <= names
        assert conn.execute("SELECT COUNT(*) FROM schema_migration WHERE version='007_outcome_verification'").fetchone()[0] == 1


def test_simulated_plant_response_is_profile_driven():
    from core.simulator import PlantSimulator
    sim = PlantSimulator()
    sim.assets[ASSET].prog = 0.9
    assert sim.respond_to_intervention(ASSET) == "recovering"
    sim.tick()
    assert sim.assets[ASSET].prog < 0.9
    sim.assets[MACHINE_B].prog = 0.9
    sim.assets[MACHINE_B].profile.intervention_response = "PERSISTS"
    assert sim.respond_to_intervention(MACHINE_B) == "unresponsive"
    sim.tick()
    assert sim.assets[MACHINE_B].prog == 0.9
    sim.assets[MACHINE_B].profile.intervention_response = "MAGIC"
    with pytest.raises(ValueError):
        sim.respond_to_intervention(MACHINE_B)
