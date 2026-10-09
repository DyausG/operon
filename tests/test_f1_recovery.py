"""F1.1 focused tests: contracts, lifecycle semantics and functional recovery.

Real repository transactions and real promotion gates throughout. Model output is
scripted (tests.test_promotion.result_payload) because F1.1 proves the application
semantics around a model, not a provider.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core import db
from core.agents.contracts import AdvisoryInput, CriticAssessment, DiagnosticAssessment
from core.reliability import lifecycle as lc
from core.reliability import models as m
from core.reliability.actors import ActorRefused, authorize, refuse_simulated_in_production, request_actor_kind
from core.reliability.assessments import prepare_specialist_context, validate_specialist_assessment
from core.reliability.lifecycle import (
    ApprovalRefused, GovernanceBlocked, LifecycleRefused, LifecycleService, ReconciliationRequired,
)
from core.reliability.orchestration import effective_uncertainties
from core.reliability.promotion import PromotionRefused
from core.reliability.repository import InactiveIncident, InvalidReference, StaleRevision, utcnow
from tests.test_incident_state import signal
from tests.test_promotion import ASSET, MECHANISM, result_payload, revision
from tests.test_reliability_lifecycle import APPROVER, Flow, RecordingCmms, scripted_supervisor, use_cmms

ENGINEER = m.ActorRef(kind="DECLARED", id="engineer-1", role="reliability_engineer")
TECHNICIAN = m.ActorRef(kind="DECLARED", id="tech-7", role="technician")


@pytest.fixture
def flow(seeded_db):
    return Flow()


def diagnostic(payload):
    return payload["assessments"][0]["assessment"]


def events(flow, kind=None):
    return [e for e in flow.repo.list_events(flow.incident_id) if kind is None or e.event_type == kind]


def to_approval(flow, *, uncertainties=(), critic_reviews=(), window_days=1):
    """Diagnosis -> draft -> exact review -> promoted intervention -> approval requirement.

    Returns (diagnosis promotion, diagnosis report, requirement, intervention).
    """
    flow.confirm()
    start = utcnow() + timedelta(days=window_days)
    flow.resources(window_start=start, window_end=start + timedelta(hours=2),
                   available_start=start - timedelta(hours=1), available_end=start + timedelta(hours=4))
    snapshot = flow.start()
    payload = result_payload(flow, snapshot)
    diagnostic(payload)["uncertainties"] = list(uncertainties)
    critic = payload["assessments"][1]["assessment"]
    critic["uncertainty_reviews"] = list(critic_reviews)
    report = flow.complete(snapshot, payload)
    promotion = flow.promote_diagnosis(report)
    draft = flow.service.create_draft(flow.incident_id, expected_revision=revision(flow),
                                      **flow.binding_fields(promotion, report))
    review = flow.complete(flow.start(draft), draft=draft)
    flow.promote_intervention(review, draft)
    requirement = flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    intervention = flow.repo.get_artifact(flow.incident_id, requirement.intervention_id)
    return promotion, report, requirement, intervention


# ------------------------------------------------------------- hypothesis identity
def test_durable_reference_survives_runs_and_paraphrase_still_promotes(flow):
    mapping = flow.register()
    registered = flow.service.current_hypotheses(flow.incident_id)
    assert mapping == {"overload": "HYP-001", "sensor": "HYP-002"}
    assert {ref: item.status for ref, item in registered.items()} == {"HYP-001": "OPEN", "HYP-002": "OPEN"}
    flow.confirm()
    snapshot = flow.start()
    # The second run sees the durable hypotheses and words the same mechanism differently.
    assert {item["reference"] for item in snapshot.context_payload["artifacts"]} == {"HYP-001", "HYP-002"}
    payload = result_payload(flow, snapshot)
    reworded = "Progressive shaft wear under sustained mechanical overload"
    diagnostic(payload)["competing_hypotheses"][0]["mechanism"] = reworded
    promotion = flow.promote_diagnosis(flow.complete(snapshot, payload))
    diagnosis = flow.repo.get_artifact(flow.incident_id, promotion.target_id)
    supported = flow.repo.get_artifact(flow.incident_id, diagnosis.hypothesis_ids[0])
    assert diagnosis.conclusion == reworded != MECHANISM  # the confirmation's prose was never compared
    assert supported.reference == "HYP-001" and supported.status == "SUPPORTED" and supported.link_basis == "MODEL"
    assert supported.supersedes_id == registered["HYP-001"].id
    assert flow.service.current_hypotheses(flow.incident_id)["HYP-002"].status == "UNRESOLVED"


def test_missing_reference_is_a_contract_failure_not_a_text_match(flow):
    flow.confirm()
    snapshot = flow.start()
    payload = result_payload(flow, snapshot)
    diagnostic(payload)["competing_hypotheses"][0]["hypothesis_ref"] = None  # identical mechanism text
    report = flow.complete(snapshot, payload)
    before = flow.incident().revision
    with pytest.raises(PromotionRefused) as exc:
        flow.promote_diagnosis(report)
    assert exc.value.disposition == "CONTRACT" and exc.value.code == "HYPOTHESIS_REF_MISSING"
    assert flow.incident().revision == before and not flow.kinds(m.Diagnosis)


def test_confirmation_must_name_a_current_durable_hypothesis(flow):
    flow.register()
    with pytest.raises(PromotionRefused, match="current durable hypothesis"):
        flow.confirm(hypothesis_ref="HYP-999")
    with pytest.raises(PromotionRefused, match="hypothesis_ref"):
        flow.confirm(hypothesis_ref=None)


def drop_refs(*keys):
    def transform(payload):
        for item in diagnostic(payload)["competing_hypotheses"]:
            if item["key"] in keys:
                item["hypothesis_ref"] = None
        return payload
    return transform


async def diagnose(flow):
    return await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime,
                                         evidence_service=flow.evidence_service)


async def test_structural_fallback_links_only_after_the_contract_retry_budget(flow, monkeypatch):
    flow.confirm()
    scripted_supervisor(monkeypatch, flow, drop_refs("overload"))
    first, second = await diagnose(flow), await diagnose(flow)
    assert [first.disposition, second.disposition] == ["RETRY", "RETRY"]
    assert first.category == "TECHNICAL" and first.code == second.code == "HYPOTHESIS_REF_MISSING"
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING and not flow.kinds(m.Diagnosis)
    third = await diagnose(flow)
    assert third.disposition == "PROMOTED"
    diagnosis = flow.repo.get_artifact(flow.incident_id, flow.incident().current_diagnosis_id)
    supported = flow.repo.get_artifact(flow.incident_id, diagnosis.hypothesis_ids[0])
    verdict = next(v for v in flow.kinds(m.ValidationVerdict) if v.target_id == diagnosis.id)
    assert supported.reference == flow.hypothesis_ref and supported.link_basis == "APPLICATION_FALLBACK"
    assert verdict.check_results.get("hypothesis_link_application_fallback") is True


async def test_ambiguous_fallback_never_promotes(flow, monkeypatch):
    flow.confirm()
    flow.confirm(hypothesis_ref="HYP-002")  # two inspections confirm two different hypotheses
    scripted_supervisor(monkeypatch, flow, drop_refs("overload", "sensor"))
    outcomes = [await diagnose(flow) for _ in range(3)]
    assert [item.disposition for item in outcomes] == ["RETRY", "RETRY", "SUSPENDED"]
    assert outcomes[-1].code == "HYPOTHESIS_LINK_AMBIGUOUS"
    assert not flow.kinds(m.Diagnosis) and flow.incident().analysis.suspended


# ----------------------------------------------------------------- uncertainty
def test_minor_and_material_uncertainty_promote_and_material_reaches_the_approver(flow):
    promotion, _, requirement, _ = to_approval(flow, uncertainties=[
        {"statement": "Bearing temperature trend has a two-hour gap", "severity": "MATERIAL"},
        {"statement": "Ambient temperature sensor is uncalibrated", "severity": "MINOR"}])
    verdict = flow.repo.get_artifact(flow.incident_id, promotion.verdict_id)
    assert {(item.statement, item.severity, item.source_role) for item in verdict.uncertainties} == {
        ("Bearing temperature trend has a two-hour gap", "MATERIAL", "diagnostic"),
        ("Ambient temperature sensor is uncalibrated", "MINOR", "diagnostic")}
    assert [item.statement for item in requirement.material_uncertainties] == ["Bearing temperature trend has a two-hour gap"]
    assert any("MATERIAL uncertainty (diagnostic)" in item for item in requirement.conditions)
    shown = flow.lifecycle.projection(flow.incident_id)["requirement"]["material_uncertainties"]
    assert [item["statement"] for item in shown] == ["Bearing temperature trend has a two-hour gap"]


def test_blocking_uncertainty_prevents_promotion(flow):
    flow.confirm()
    snapshot = flow.start()
    payload = result_payload(flow, snapshot)
    diagnostic(payload)["uncertainties"] = [{"statement": "Shaft not yet inspected", "severity": "BLOCKING"}]
    report = flow.complete(snapshot, payload)
    with pytest.raises(PromotionRefused, match="blocking uncertainty") as exc:
        flow.promote_diagnosis(report)
    assert exc.value.disposition == "NEEDS_EVIDENCE"


def test_critic_raise_blocks_and_preserves_the_original_severity(flow):
    flow.confirm()
    snapshot = flow.start()
    payload = result_payload(flow, snapshot)
    diagnostic(payload)["uncertainties"] = [{"statement": "Load history incomplete", "severity": "MATERIAL"}]
    payload["assessments"][1]["assessment"]["uncertainty_reviews"] = [{
        "assessment_key": "diagnostic", "uncertainty_index": 0, "severity": "BLOCKING",
        "rationale": "Without load history overload cannot be separated from wear"}]
    report = flow.complete(snapshot, payload)
    with pytest.raises(PromotionRefused, match="blocking uncertainty"):
        flow.promote_diagnosis(report)
    advice = {item["key"]: AdvisoryInput.model_validate(item) for item in report.result_payload["assessments"]}
    recorded = next(item for item in effective_uncertainties(advice, run_id=report.run_id) if item.source_key == "diagnostic")
    assert (recorded.severity, recorded.original_severity, recorded.raised_by_key) == ("BLOCKING", "MATERIAL", "critic")


def test_critic_raise_to_material_is_carried_to_the_approver(flow):
    _, _, requirement, _ = to_approval(flow, uncertainties=[{"statement": "Vibration not trended", "severity": "MINOR"}],
                                       critic_reviews=[{"assessment_key": "diagnostic", "uncertainty_index": 0,
                                                        "severity": "MATERIAL", "rationale": "Affects the plan"}])
    [material] = requirement.material_uncertainties
    assert (material.severity, material.original_severity, material.raised_by_key) == ("MATERIAL", "MINOR", "critic")


def test_critic_may_never_lower_severity(flow):
    diagnostic_assessment = DiagnosticAssessment(
        incident_id=flow.incident_id, evidence_reviewed=(flow.history_id,), reasoning_summary="Assessment",
        competing_hypotheses=(), recommended_hypothesis=None, confidence=0.4,
        uncertainties=({"statement": "Load history incomplete", "severity": "MATERIAL"},))
    scope = prepare_specialist_context(flow.repo, flow.incident_id, asset_id=ASSET, run_id="review-run",
                                       evidence_ids=(flow.history_id,),
                                       advisory_inputs=(AdvisoryInput(key="diagnostic", assessment=diagnostic_assessment),))
    critic = CriticAssessment(
        incident_id=flow.incident_id, evidence_reviewed=(flow.history_id,), reasoning_summary="Review",
        input_assessment_keys=("diagnostic",), subject_id="diagnostic", subject_kind="assessment", evidence_gaps=(),
        contradictions=(), unsupported_claims=(), recommendation="ACCEPT", requested_additional_evidence=(),
        uncertainty_reviews=({"assessment_key": "diagnostic", "uncertainty_index": 0, "severity": "MINOR",
                              "rationale": "Not important"},))
    with pytest.raises(InvalidReference, match="never lower"):
        validate_specialist_assessment(flow.repo, critic, scope, set())


def test_pre_f1_string_uncertainty_reads_as_blocking():
    assessment = DiagnosticAssessment(incident_id="i", evidence_reviewed=("e",), reasoning_summary="s",
                                      competing_hypotheses=(), recommended_hypothesis=None, confidence=0.1,
                                      uncertainties=["legacy free text"])
    assert assessment.uncertainties[0].severity == "BLOCKING"


# ---------------------------------------------------- failure classification
async def test_technical_failures_retry_then_suspend_durably_and_resume_restores(flow, monkeypatch):
    scripted_supervisor(monkeypatch, flow, lambda payload: payload | {"termination_reason": "TIMEOUT"})
    outcomes = [await diagnose(flow) for _ in range(3)]
    assert [item.disposition for item in outcomes] == ["RETRY", "RETRY", "SUSPENDED"]
    assert {item.category for item in outcomes} == {"TECHNICAL"} and outcomes[0].code == "TIMEOUT"
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING  # never escalated
    assert [e.event_type for e in events(flow) if e.event_type.startswith("ANALYSIS_")] == [
        "ANALYSIS_RETRY_SCHEDULED", "ANALYSIS_RETRY_SCHEDULED", "ANALYSIS_SUSPENDED"]
    reports = len(flow.kinds(m.SupervisorReport))
    # Durable across a restart: a fresh service reads the same suspension and runs nothing.
    restarted = LifecycleService(flow.repo)
    blocked = await restarted.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime,
                                       evidence_service=flow.evidence_service)
    assert blocked.disposition == "SUSPENDED" and len(flow.kinds(m.SupervisorReport)) == reports
    restarted.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="provider restored")
    assert flow.incident().analysis is None and events(flow)[-1].event_type in {"ANALYSIS_RESUMED", "LIFECYCLE_COMMAND"}
    assert (await diagnose(flow)).disposition == "RETRY"  # a fresh budget after an audited resume


async def test_retry_budget_is_configurable(flow, monkeypatch):
    monkeypatch.setenv("OPERON_TECHNICAL_RETRY_ATTEMPTS", "1")
    scripted_supervisor(monkeypatch, flow, lambda payload: payload | {"termination_reason": "MODEL_FAILED"})
    assert (await diagnose(flow)).disposition == "SUSPENDED"


async def test_failed_specialist_is_technical_and_insufficient_evidence_parks(flow, monkeypatch):
    def failed(payload):
        payload["delegations"][0]["status"] = "FAILED"
        payload["delegations"][0]["error_code"] = "RateLimited"
        return payload | {"disposition": "BLOCKED"}
    scripted_supervisor(monkeypatch, flow, failed)
    outcome = await diagnose(flow)
    assert (outcome.disposition, outcome.category, outcome.code) == ("RETRY", "TECHNICAL", "SPECIALIST_FAILURE")
    scripted_supervisor(monkeypatch, flow)
    parked = await diagnose(flow)  # no trusted confirmation exists yet
    assert (parked.disposition, parked.category) == ("NEEDS_EVIDENCE", "EVIDENCE")
    assert parked.phase == m.IncidentPhase.AWAITING_EVIDENCE
    assert events(flow, "HYPOTHESES_REGISTERED")[-1].payload["recommended"] == "HYP-001"


async def test_governance_block_after_promotion_returns_to_planning(flow, monkeypatch):
    scripted_supervisor(monkeypatch, flow)
    promotion, report = flow.diagnosis()
    original = flow.lifecycle.promotion.promote_intervention

    def then_lose_the_technician(*args, **kwargs):
        record = original(*args, **kwargs)
        with db.get_conn(flow.repo.path) as conn:  # resources change before approval is requested
            conn.execute("UPDATE technician SET available=0")
        return record
    monkeypatch.setattr(flow.lifecycle.promotion, "promote_intervention", then_lose_the_technician)
    outcome = await flow.lifecycle.plan(flow.incident_id, runtime=flow.runtime, evidence_service=flow.evidence_service,
                                        expected_revision=revision(flow), **flow.binding_fields(promotion, report))
    assert (outcome.disposition, outcome.category) == ("GOVERNANCE_BLOCKED", "GOVERNANCE")
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.PLANNING and incident.current_intervention_id is None
    command = events(flow, "LIFECYCLE_COMMAND")[-1].payload
    assert command["command"] == "governance_blocked" and command["actor"]["kind"] == "SYSTEM"


# ------------------------------------------------------------ recovery commands
def test_escalate_and_resume_are_audited_and_validated(flow):
    with pytest.raises(LifecycleRefused, match="nothing to resume"):
        flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="why")
    with pytest.raises(LifecycleRefused, match="rationale"):
        flow.lifecycle.escalate(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale=" ")
    with pytest.raises(StaleRevision):
        flow.lifecycle.escalate(flow.incident_id, expected_revision=revision(flow) - 1, actor=ENGINEER, rationale="x")
    flow.lifecycle.escalate(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="needs authority")
    assert flow.incident().phase == m.IncidentPhase.ESCALATED
    flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="reviewed")
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING
    commands = [e.payload for e in events(flow, "LIFECYCLE_COMMAND")]
    assert [(c["command"], c["from"], c["to"]) for c in commands] == [
        ("escalate", "INVESTIGATING", "ESCALATED"), ("resume", "ESCALATED", "INVESTIGATING")]
    assert commands[1]["actor"]["id"] == "engineer-1" and commands[1]["actor"]["authenticated"] is False


def test_resume_refuses_a_valid_pending_approval(flow):
    to_approval(flow)
    with pytest.raises(LifecycleRefused, match="still valid"):
        flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="x")


def test_cancel_reaches_cancelled_and_releases_admission(flow):
    to_approval(flow)
    flow.lifecycle.cancel(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="duplicate case")
    assert flow.incident().phase == m.IncidentPhase.CANCELLED
    assert events(flow, "INCIDENT_CANCELLED")[-1].payload["rationale"] == "duplicate case"
    with pytest.raises(InactiveIncident):
        flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="x")
    incident, created = flow.repo.admit_signal(signal())
    assert created and incident.id != flow.incident_id  # the asset can open a new case


def test_cancel_is_refused_while_dispatch_is_in_flight(flow, monkeypatch):
    intervention, _, _, _ = flow.ready()
    refusals = []

    def cancel_during_dispatch():
        try:
            flow.lifecycle.cancel(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="stop")
        except LifecycleRefused as exc:
            refusals.append(str(exc))
    use_cmms(monkeypatch, RecordingCmms(hook=cancel_during_dispatch))
    flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert refusals and "in flight" in refusals[0] and flow.incident().phase == m.IncidentPhase.OBSERVING


def test_reject_returns_to_planning_and_the_case_can_be_replanned(flow):
    promotion, report, requirement, intervention = to_approval(flow)
    flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(requirement, intervention)
                                                        | {"decision": "REJECT", "rationale": "window clashes with a shutdown"}))
    assert flow.incident().phase == m.IncidentPhase.PLANNING
    recorded = events(flow, "APPROVAL_RECORDED")[-1].payload
    assert (recorded["actor_id"], recorded["actor_kind"], recorded["return_to"]) == (APPROVER["actor_id"], "DECLARED", "PLANNING")
    draft = flow.service.create_draft(flow.incident_id, expected_revision=revision(flow), **flow.binding_fields(promotion, report))
    flow.promote_intervention(flow.complete(flow.start(draft), draft=draft), draft)
    flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    assert flow.incident().phase == m.IncidentPhase.AWAITING_APPROVAL  # not a dead end


def test_expired_approval_is_renewed_for_the_same_exact_intervention(flow, monkeypatch):
    _, _, requirement, intervention = to_approval(flow, window_days=3)
    with pytest.raises(ApprovalRefused, match="expired"):
        flow.lifecycle.renew_approval(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="x")
    monkeypatch.setattr(lc, "utcnow", lambda: utcnow() + timedelta(hours=25))
    renewed = flow.lifecycle.renew_approval(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER,
                                            rationale="approver was unavailable")
    assert renewed.supersedes_id == requirement.id and renewed.intervention_hash == requirement.intervention_hash
    assert events(flow, "LIFECYCLE_COMMAND")[-1].payload["command"] == "renew_approval"
    flow.lifecycle.decide_approval(flow.incident_id, **flow.command(renewed, intervention))
    assert flow.incident().phase == m.IncidentPhase.READY


def test_expiry_after_the_window_requires_planning_again(flow, monkeypatch):
    _, _, _, _ = to_approval(flow)
    monkeypatch.setattr(lc, "utcnow", lambda: utcnow() + timedelta(hours=25))
    with pytest.raises(GovernanceBlocked, match="window"):
        flow.lifecycle.renew_approval(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="x")
    flow.lifecycle.return_to_planning(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER,
                                      rationale="window has passed")
    assert flow.incident().phase == m.IncidentPhase.PLANNING and flow.incident().current_intervention_id is None


def test_dispatch_retry_and_abandonment_are_audited(flow, monkeypatch):
    intervention, _, _, _ = flow.ready()
    use_cmms(monkeypatch, RecordingCmms("fail"))
    with pytest.raises(Exception):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert flow.incident().phase == m.IncidentPhase.EXECUTION_FAILED and not flow.kinds(m.WorkAssignment)
    flow.lifecycle.retry_execution(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="CMMS back")
    assert flow.incident().phase == m.IncidentPhase.READY
    assert events(flow, "LIFECYCLE_COMMAND")[-1].payload["command"] == "retry_execution"
    with pytest.raises(Exception):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="replan the work")
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING and flow.incident().current_intervention_id is None


def test_ambiguous_dispatch_cannot_be_abandoned_by_resume(flow, monkeypatch):
    intervention, _, _, _ = flow.ready()
    use_cmms(monkeypatch, RecordingCmms("unknown"))
    with pytest.raises(Exception):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    with pytest.raises(ReconciliationRequired):
        flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER, rationale="x")


# ------------------------------------------------------------------------ work
def test_work_requested_acknowledged_and_reported_are_separate_facts_not_recovery(flow):
    intervention, _, _, _ = flow.ready()
    flow.lifecycle.execute(flow.incident_id, intervention.id)
    [assignment] = flow.kinds(m.WorkAssignment)
    assert assignment.assignee.kind == "WORKER" and assignment.assignee.reference_system == "operon.local.technician_roster"
    assert assignment.intervention_hash == flow.lifecycle.status(flow.incident_id).intervention_hash
    assert events(flow, "WORK_ASSIGNED")[-1].payload["assignment_id"] == assignment.id
    assert flow.lifecycle.work_status(flow.incident_id)[0]["state"] == "ASSIGNED"

    def report(**kw):
        # F1.2 (intentional change): a COMPLETED report must attest whether physical work was done.
        return flow.lifecycle.report_work(flow.incident_id, assignment_id=assignment.id, expected_revision=revision(flow),
                                          actor=TECHNICIAN, result="COMPLETED", summary="Bearing replaced",
                                          performed_at=utcnow(), asset_intervened=True, **kw)
    with pytest.raises(LifecycleRefused, match="acknowledged before"):
        report()
    flow.lifecycle.acknowledge_work(flow.incident_id, assignment_id=assignment.id, expected_revision=revision(flow),
                                    actor=TECHNICIAN)
    with pytest.raises(LifecycleRefused, match="already ACKNOWLEDGED"):
        flow.lifecycle.acknowledge_work(flow.incident_id, assignment_id=assignment.id, expected_revision=revision(flow),
                                        actor=TECHNICIAN)
    work_report = report()
    assert work_report.actor == TECHNICIAN and work_report.result == "COMPLETED"
    with pytest.raises(LifecycleRefused, match="already REPORTED"):
        report()
    # Reported work is not recovery: no outcome, no closure, the phase is unchanged.
    assert flow.incident().phase == m.IncidentPhase.OBSERVING and not flow.kinds(m.Outcome)
    state = LifecycleService(flow.repo).work_status(flow.incident_id)[0]  # durable across a restart
    assert (state["state"], state["result"], state["acknowledged_by"]["id"]) == ("REPORTED", "COMPLETED", "tech-7")


def test_work_records_are_only_written_by_lifecycle_commands(flow):
    intervention, _, _, _ = flow.ready()
    flow.lifecycle.execute(flow.incident_id, intervention.id)
    [assignment] = flow.kinds(m.WorkAssignment)
    forged = assignment.model_copy(update={"id": "forged"})
    with pytest.raises(InvalidReference, match="work records"):
        flow.repo.add_artifact(forged, expected_revision=revision(flow))
    with pytest.raises(ValidationError):
        m.WorkReport(id="r", incident_id=flow.incident_id, created_at=utcnow(), equipment_ids=(ASSET,),
                     assignment_id=assignment.id, result="COMPLETED", summary="done", actor=TECHNICIAN,
                     provenance="OBSERVED")  # performed work needs a time


# ------------------------------------------------------------------- sandbox
def production_incident():
    return m.Incident(id="p", created_at=utcnow(), updated_at=utcnow(), equipment_ids=(ASSET,), admission_key="k",
                      environment="PRODUCTION")


def test_sandbox_identity_is_accepted_only_on_sandbox_incidents(seeded_db, monkeypatch):
    monkeypatch.setenv("OPERON_ENVIRONMENT", "sandbox")
    flow = Flow()
    incident = flow.incident()
    assert incident.environment == "SANDBOX"
    assert authorize("SANDBOX", incident) == "SANDBOX" and authorize("SCENARIO", incident) == "SCENARIO"
    with pytest.raises(ActorRefused):
        authorize("DECLARED", incident)
    sandbox = m.ActorRef(kind="SANDBOX", id="sandbox-approver", role="maintenance_approver")
    flow.lifecycle.escalate(flow.incident_id, expected_revision=revision(flow), actor=sandbox, rationale="test")
    actor = events(flow, "LIFECYCLE_COMMAND")[-1].payload["actor"]
    assert actor["kind"] == "SANDBOX" and actor["authenticated"] is False and "unauthenticated" in actor["label"]
    monkeypatch.setenv("OPERON_ENVIRONMENT", "")  # the same identity outside a sandbox process
    with pytest.raises(ActorRefused):
        authorize("SANDBOX", incident)


def test_sandbox_identity_is_refused_on_unspecified_incidents(flow):
    with pytest.raises(ActorRefused):
        flow.lifecycle.escalate(flow.incident_id, expected_revision=revision(flow),
                                actor=m.ActorRef(kind="SANDBOX", id="s"), rationale="x")


def test_production_refuses_every_unauthenticated_human_action(monkeypatch):
    incident = production_incident()
    for kind in ("SANDBOX", "DECLARED", "SCENARIO"):
        with pytest.raises(ActorRefused):
            authorize(kind, incident)
    assert authorize("SYSTEM", incident) == "SYSTEM"
    with pytest.raises(ActorRefused):
        refuse_simulated_in_production(incident, "SIMULATED")
    monkeypatch.setenv("OPERON_ENVIRONMENT", "production")
    with pytest.raises(ActorRefused):
        request_actor_kind()
    with pytest.raises(ValidationError):
        m.ActorRef(kind="SANDBOX", id="x", authenticated=True)
    monkeypatch.setenv("OPERON_ENVIRONMENT", "staging")
    with pytest.raises(ValueError):
        request_actor_kind()


def confirmation_body(incident_id="i-1"):
    return {"expected_revision": 1, "confirmation": {
        "incident_id": incident_id, "asset_id": ASSET, "confirmed_mechanism": MECHANISM, "hypothesis_ref": "HYP-001",
        "supporting_evidence_ids": ["e-1"], "performed_checks": [{"check": "c", "result": "r", "passed": True}],
        "observed_at": utcnow().isoformat(), "source": "field", "actor_id": "tech-7", "provenance": "SIMULATED",
        "actor_kind": "DECLARED"}}


def test_http_gate_and_server_assigned_actor_kind(monkeypatch):
    from server import main as server_main
    captured = {}
    stub = SimpleNamespace(
        submit_technical_confirmation=lambda confirmation, expected_revision: captured.update(c=confirmation) or {"ok": True},
        lifecycle_command=None, legacy_demo=False)
    monkeypatch.setattr(server_main, "engine", stub)
    client = TestClient(server_main.app)
    work = {"expected_revision": 1, "actor_id": "tech-7"}
    # Unspecified environment: the sandbox field-response and input routes are closed.
    assert client.post("/api/incidents/i-1/work/a-1/acknowledge", json=work).status_code == 403
    assert client.post("/api/incidents/i-1/confirmations/technical", json=confirmation_body()).status_code == 403
    # Sandbox: open, and the caller cannot choose its own actor kind.
    monkeypatch.setenv("OPERON_ENVIRONMENT", "sandbox")
    assert client.post("/api/incidents/i-1/confirmations/technical", json=confirmation_body()).status_code == 200
    assert captured["c"].actor_kind == "SANDBOX"
    # Production: no human command is accepted before authenticated identity exists.
    monkeypatch.setenv("OPERON_ENVIRONMENT", "production")
    monkeypatch.setenv("OPERON_TRUSTED_SUBMISSIONS", "1")  # the legacy bypass never applies in production
    assert client.post("/api/incidents/i-1/confirmations/technical", json=confirmation_body()).status_code == 403
    command = {"expected_revision": 1, "actor_id": "e", "rationale": "r"}
    assert client.post("/api/incidents/i-1/commands/cancel", json=command).status_code == 403
    intent = {"requirement_id": "r", "intervention_id": "i", "intervention_hash": "h", "context_revision": 1}
    assert client.post("/api/approve/AC-COMP-01", json=intent).status_code == 403


async def test_guided_demo_is_refused_in_production(seeded_db, monkeypatch):
    from tests.test_engine_lifecycle import make_engine
    monkeypatch.setenv("OPERON_ENVIRONMENT", "production")
    engine = make_engine(monkeypatch)
    result = await engine.start_guided_demo(ASSET)
    assert result["ok"] is False and "production" in result["error"]


async def test_engine_cancel_releases_the_asset_for_a_new_case(seeded_db, monkeypatch):
    from tests.test_engine_lifecycle import make_engine
    engine = make_engine(monkeypatch)
    await engine._advance()
    await engine.stop()
    first = engine.incidents[ASSET]
    assert engine.sim.assets[ASSET].mode == "arrested"
    result = await engine.lifecycle_command(first.id, "cancel", expected_revision=first.revision,
                                            actor=ENGINEER, rationale="false positive")
    assert result["ok"] and result["incident"]["phase"] == "CANCELLED"
    assert engine.sim.assets[ASSET].mode == "degrading"
    await engine._advance()
    assert engine.incidents[ASSET].id != first.id  # the persisting condition is a new case
