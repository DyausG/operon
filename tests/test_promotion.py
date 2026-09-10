"""Offline adversarial tests of the application promotion boundary.

Private completion fixtures replace only the invocation seam. Authority tests
always load durable reports and exercise the real transaction and gates.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import sqlite3

import pytest
from pydantic import ValidationError

from core import db
from core.agents.contracts import AdvisoryInput, SpecialistContext, SupervisorResult
from core.agents.runtime import StrandsRuntime
from core.reliability import models as m
from core.reliability.evidence import EvidenceService
from core.reliability.governance import WorkPackageParameters
from core.reliability.legacy import prepare_legacy_intervention
from core.reliability.promotion import (
    CONFIRM_MECHANISM, POLICY_VERSION, VALIDATOR, PromotionConflict, PromotionRefused,
    PromotionService, executable_content_hash,
)
from core.reliability.repository import IncidentRepository, InvalidReference, StaleRevision, content_hash, new_id, utcnow
from tests.conftest import sample_proposal
from tests.test_incident_state import signal
from tests.test_strands_agents import ScriptedModel, settings

ASSET = "AC-COMP-01"
MECHANISM = "Confirmed compressor mechanical overload"


def digest(value):
    return content_hash(value.model_dump(mode="json"))


def revision(env):
    return env.repo.fetch_incident(env.incident_id).revision


class Environment:
    def __init__(self):
        self.repo = IncidentRepository()
        self.service = PromotionService(self.repo)
        self.evidence_service = EvidenceService(self.repo)
        self.runtime = StrandsRuntime(settings(), model=ScriptedModel())
        incident, _ = self.repo.admit_signal(signal())
        self.incident_id = incident.id
        self.signal_id = incident.signal_evidence_ids[0]
        self.repo.transition(incident.id, m.IncidentPhase.INVESTIGATING,
                             expected_revision=incident.revision, reason="test application investigation")
        history = self.evidence_service.request_and_collect(
            incident.id, requested_by="diagnostic", equipment_ids=(ASSET,), question="Read recorded service history",
            capability="get_maintenance_history", required_for="diagnosis")
        self.history_id = history.evidence.id
        self.confirmation = None
        self.resource = None

    def confirm(self, **changes):
        fields = dict(incident_id=self.incident_id, asset_id=ASSET, confirmed_mechanism=MECHANISM,
                      failure_mode_code="OSF", supporting_evidence_ids=(self.history_id,),
                      performed_checks=(m.PerformedCheck(check="Independent load and shaft inspection", result="Mechanical overload confirmed", passed=True),),
                      observed_at=utcnow(), source="offline-inspection-fixture", actor_id="trusted-test-inspector", provenance="SIMULATED")
        self.confirmation = self.service.submit_technical_confirmation(
            m.TrustedTechnicalConfirmation(**(fields | changes)), expected_revision=revision(self))
        return self.confirmation

    def resources(self, **changes):
        with db.get_conn(self.repo.path) as conn:
            tech = conn.execute("SELECT technician_id FROM technician WHERE skills LIKE '%COMPRESSOR%' AND available=1 ORDER BY technician_id").fetchone()[0]
            parts = tuple(m.WorkPackagePart(part_id=row[0], quantity=row[1]) for row in conn.execute(
                "SELECT part_id,qty_per_service FROM equipment_part WHERE equipment_id=? ORDER BY part_id", (ASSET,)))
        start = utcnow() + timedelta(days=1)
        fields = dict(incident_id=self.incident_id, asset_id=ASSET, technician_id=tech, qualification="COMPRESSOR",
                      qualification_valid_until=start + timedelta(days=30), available_start=start - timedelta(hours=1),
                      available_end=start + timedelta(hours=4), window_start=start, window_end=start + timedelta(hours=2),
                      window_confirmed=True, parts=parts, observed_at=utcnow(), source="offline-dated-dispatch-fixture",
                      actor_id="trusted-test-dispatcher", provenance="SIMULATED")
        self.resource = self.service.submit_resource_confirmation(m.ResourceConfirmation(**(fields | changes)), expected_revision=revision(self))
        return self.resource

    def evidence_ids(self):
        return (self.signal_id, self.history_id, *((self.confirmation.id,) if self.confirmation else ()),
                *((self.resource.id,) if self.resource else ()))

    def start(self, draft=None, evidence_ids=None):
        return self.service.start_run(
            self.incident_id, asset_id=ASSET, stage="INTERVENTION_REVIEW" if draft else "DIAGNOSIS",
            expected_revision=revision(self), evidence_ids=evidence_ids or (draft.evidence_ids if draft else self.evidence_ids()),
            runtime=self.runtime, draft_id=draft.id if draft else None)

    def complete(self, snapshot, payload=None, draft=None):
        return self.service._complete_run(snapshot, SupervisorResult.model_validate(payload or result_payload(self, snapshot, draft=draft)))

    def promote_diagnosis(self, report, confirmation_id=None, expected_revision=None):
        return self.service.promote_diagnosis(self.incident_id, report_id=report.id,
            confirmation_id=confirmation_id or (self.confirmation.id if self.confirmation else self.history_id),
            expected_revision=revision(self) if expected_revision is None else expected_revision)

    def diagnosis(self):
        self.confirm()
        self.resources()
        snapshot = self.start()
        report = self.complete(snapshot)
        promotion = self.promote_diagnosis(report)
        return promotion, report

    def binding_fields(self, promotion, report):
        resource = m.ResourceConfirmation.model_validate(self.resource.payload)
        return dict(diagnosis_id=promotion.target_id, source_report_id=report.id, source_plan_key="plan",
                    asset_id=ASSET, failure_mode_id="FM-OSF", technician_id=resource.technician_id,
                    parts=resource.parts, resource_confirmation_id=self.resource.id, signal_evidence_id=self.signal_id,
                    window_start=resource.window_start, window_end=resource.window_end, duration_minutes=45,
                    work_instructions=("Isolate compressor and verify zero energy.", "Perform reviewed mechanical overhaul."),
                    technical_preconditions=("Isolation verified by qualified technician",),
                    verification_criteria=("Record physical inspection and service checks",),
                    evidence_ids=self.evidence_ids(), estimated_cost=550.0, estimated_downtime_minutes=60,
                    estimated_avoided_loss=12000.0, business_assumption_version="test-business-2026-1",
                    safety_review="Reviewed isolation and mechanical hazards", safety_relevant=True,
                    reversible=False, external_commitment=True)

    def draft(self):
        promotion, report = self.diagnosis()
        return self.service.create_draft(self.incident_id, expected_revision=revision(self), **self.binding_fields(promotion, report))

    def promote_intervention(self, report, draft, expected_revision=None):
        return self.service.promote_intervention(self.incident_id, report_id=report.id, draft_id=draft.id,
            expected_revision=revision(self) if expected_revision is None else expected_revision)


@pytest.fixture
def env(seeded_db):
    return Environment()


def result_payload(env, snapshot, draft=None):
    evidence = list(snapshot.evidence_manifest)
    common = dict(incident_id=env.incident_id, evidence_reviewed=evidence, reasoning_summary="Independent advisory review of supplied evidence.")
    if draft is None:
        diagnostic = common | dict(competing_hypotheses=[
            dict(key="overload", mechanism=MECHANISM, supporting_evidence_ids=[env.history_id], confidence=0.7,
                 falsification_tests=["Suggested independent repeat load test"]),
            dict(key="sensor", mechanism="Sensor bias alternative", supporting_evidence_ids=[], confidence=0.2,
                 falsification_tests=["Suggested sensor calibration check"])], recommended_hypothesis="overload", confidence=0.7)
        critic = common | dict(subject_kind="assessment", subject_id="diagnostic", input_assessment_keys=["diagnostic"],
                               evidence_gaps=[], contradictions=[], unsupported_claims=[], recommendation="ACCEPT", requested_additional_evidence=[])
        plan = common | dict(input_assessment_keys=["diagnostic", "critic"], validated_input_ids=[], proposed_steps=[
            dict(description="Reviewed physical maintenance proposal", equipment_ids=[ASSET], evidence_ids=[env.history_id],
                 preconditions=["Independent application binding"], verification_criteria=["Review actual work package"])],
            estimated_exposure=999.0, exposure_currency="USD", exposure_assumptions=["Advisory exposure only"],
            reversible=False, safety_relevant=True, external_commitment=True, approval_considerations=["Application policy later"])
        assessments = [("diagnostic", "diagnostic", diagnostic), ("critic", "critic", critic), ("planner", "plan", plan)]
    else:
        exact = dict(reviewed_intervention_id=draft.id, reviewed_intervention_hash=digest(draft))
        engineering = common | exact | dict(diagnosis_id=draft.diagnosis_id, constraints_considered=["Reviewed isolation constraints"],
            intervention_feasibility="FEASIBLE", blockers=[], safety_concerns=[], recommended_intervention_elements=["Exact supplied draft"])
        operations = common | exact | dict(intervention_id=draft.id, input_assessment_keys=["engineering"], resource_feasibility="FEASIBLE",
            inventory_observations=["Durable BOM stock checked"], workforce_observations=["Dated qualification confirmed"],
            scheduling_observations=["Confirmed dated window reviewed"], blockers=[], operational_recommendations=["Recheck at execution"])
        critic = common | exact | dict(subject_kind="intervention", subject_id=draft.id,
            input_assessment_keys=["engineering", "operations"], evidence_gaps=[], contradictions=[], unsupported_claims=[],
            recommendation="ACCEPT", requested_additional_evidence=[])
        assessments = [("engineering", "engineering", engineering), ("operations", "operations", operations), ("critic", "critic", critic)]
    selections = dict(candidate_diagnosis_key=None if draft else "diagnostic", engineering_key="engineering" if draft else None,
                      operations_key="operations" if draft else None, maintenance_plan_key=None if draft else "plan", critic_keys=["critic"])
    return dict(incident_id=env.incident_id, run_id=snapshot.run_id, input_revision=snapshot.input_revision,
        disposition="ADVISORY_CONCLUSION", decision=dict(incident_id=env.incident_id, run_id=snapshot.run_id,
            disposition="ADVISORY_CONCLUSION", reasoning_summary="Advisory only; application must validate.", evidence_used=evidence, **selections),
        assessments=[dict(key=key, assessment=value) for _, key, value in assessments],
        delegations=[dict(key=key, role=role, question="Review supplied inputs", input_revision=snapshot.input_revision,
                          input_assessment_keys=value.get("input_assessment_keys", []), evidence_ids=evidence, status="SUCCEEDED")
                     for role, key, value in assessments], evidence_requests=[], evidence_used=evidence, **selections,
        unresolved_evidence_needs=[], blockers=[], termination_reason="MODEL_COMPLETED", exhausted_limits=[], tool_calls=4, bounds=snapshot.bounds)


def state(env):
    return env.repo.fetch_incident(env.incident_id), env.repo.list_artifacts(env.incident_id), env.repo.list_events(env.incident_id)


async def test_snapshot_is_durable_before_invocation_and_terminal_report_after(env, monkeypatch):
    env.confirm()
    observed = []
    async def invoke(runtime, service, context, **kwargs):
        snapshots = [a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.SupervisorRunSnapshot)]
        assert len(snapshots) == 1
        snapshot = snapshots[0]
        assert context.run_id == snapshot.run_id == env.repo.fetch_incident(env.incident_id).active_run_id
        assert context.input_revision == revision(env)
        # An independent writer succeeds: invocation is outside the write transaction.
        with db.get_conn(env.repo.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
        observed.append(snapshot)
        return SupervisorResult.model_validate(result_payload(env, snapshot))
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)
    report = await env.service.run_supervisor(env.incident_id, service=env.evidence_service, runtime=env.runtime,
        asset_id=ASSET, stage="DIAGNOSIS", expected_revision=revision(env), evidence_ids=env.evidence_ids())
    assert report.completion == "MODEL_COMPLETED" and not report.stale_reasons
    assert report.input_revision == report.completion_revision == observed[0].input_revision
    assert report.checkpoint_revision == revision(env)
    assert env.repo.get_artifact(env.incident_id, report.id) == report
    assert isinstance(SupervisorResult.model_validate(report.result_payload), SupervisorResult)
    assert observed[0].runtime_identity and observed[0].version_identity and observed[0].evidence_manifest


@pytest.mark.parametrize("exception,completion", [(asyncio.CancelledError, "CANCELLED"), (RuntimeError, "MODEL_FAILED")])
async def test_failed_and_cancelled_invocations_persist_terminal_report(env, monkeypatch, exception, completion):
    async def invoke(*args, **kwargs):
        raise exception()
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)
    with pytest.raises(exception):
        await env.service.run_supervisor(env.incident_id, service=env.evidence_service, runtime=env.runtime,
            asset_id=ASSET, stage="DIAGNOSIS", expected_revision=revision(env), evidence_ids=env.evidence_ids())
    reports = [a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.SupervisorReport)]
    assert len(reports) == 1 and reports[0].completion == completion
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(reports[0])


def test_terminal_report_duplicate_is_idempotent_and_changed_payload_conflicts(env):
    snapshot = env.start()
    result = SupervisorResult.model_validate(result_payload(env, snapshot))
    report = env.service._complete_run(snapshot, result)
    before = state(env)
    assert env.service._complete_run(snapshot, result) == report
    assert state(env) == before
    with pytest.raises(PromotionConflict):
        env.service._complete_run(snapshot, result.model_copy(update={"blockers": ("changed",)}))


@pytest.mark.parametrize("change", [{"run_id": "wrong"}, {"incident_id": "wrong"}, {"input_revision": 1}])
def test_report_scope_rejected(env, change):
    snapshot = env.start()
    before = state(env)
    with pytest.raises(PromotionRefused):
        env.complete(snapshot, result_payload(env, snapshot) | change)
    assert state(env) == before


def test_report_load_explicitly_validates_supervisor_json(env):
    report = env.complete(env.start())
    payload = report.model_dump(mode="json")
    payload["result_payload"]["unexpected_authority"] = True
    payload["result_hash"] = content_hash(payload["result_payload"])
    with db.get_conn(env.repo.path) as conn:
        conn.execute("DROP TRIGGER immutable_incident_artifact")
        conn.execute("UPDATE incident_artifact SET body_json=? WHERE artifact_id=?", (json.dumps(payload), report.id))
    with pytest.raises(ValidationError):
        env.repo.get_artifact(env.incident_id, report.id)


@pytest.mark.parametrize("when", ["during", "after", "evidence_during", "evidence_after", "new_run_during", "new_run_after", "raw_during", "raw_after"])
def test_freshness_is_conservative(env, when):
    env.confirm()
    snapshot = env.start()
    report = env.complete(snapshot) if when.endswith("after") else None
    if when.startswith("evidence"):
        env.evidence_service.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
            question="Collect committed asset evidence", capability="get_asset_context", required_for="diagnosis")
    elif when.startswith("new_run"):
        env.start()
    elif when.startswith("raw"):
        with db.get_conn(env.repo.path) as conn:
            conn.execute("UPDATE part SET on_hand_qty=on_hand_qty+1")
    else:
        env.repo.append_event(env.incident_id, "INCIDENT_UPDATED", {"changed": True}, expected_revision=revision(env))
    report = report or env.complete(snapshot)
    assert report.input_revision == snapshot.input_revision
    if not when.endswith("after"):
        assert report.stale_reasons
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(report)


def test_start_run_rejects_stale_raw_evidence_before_reasoning(env):
    with db.get_conn(env.repo.path) as conn:
        conn.execute("UPDATE maintenance_event SET note='changed source'")
    with pytest.raises(PromotionRefused, match="raw evidence"):
        env.start()


@pytest.mark.parametrize("failure", ["missing_confirmation", "mechanism", "no_support", "classifier_only", "model_only", "critic_only", "contradiction"])
def test_diagnosis_needs_independent_grounding(env, failure):
    if failure != "missing_confirmation":
        env.confirm(confirmed_mechanism="Different mechanism" if failure == "mechanism" else MECHANISM)
    if failure == "model_only":
        history = env.repo.get_artifact(env.incident_id, env.history_id)
        payload = {"model_reasoning": MECHANISM}
        model_evidence = history.model_copy(update={"id": new_id(), "kind": "document", "source_capability": "model_reasoning",
            "payload": payload, "content_hash": content_hash(payload), "derived_from_ids": (env.signal_id,),
            "request_id": None, "provenance": "DERIVED"})
        env.repo.add_artifact(model_evidence, expected_revision=revision(env))
    snapshot = env.start(evidence_ids=(*env.evidence_ids(), model_evidence.id) if failure == "model_only" else None)
    payload = result_payload(env, snapshot)
    selected = payload["assessments"][0]["assessment"]["competing_hypotheses"][0]
    if failure == "no_support":
        selected["supporting_evidence_ids"] = []
    if failure == "classifier_only":
        selected["supporting_evidence_ids"] = [env.signal_id]
    if failure == "model_only":
        selected["supporting_evidence_ids"] = [model_evidence.id]
    if failure == "critic_only":
        payload["assessments"][0]["assessment"]["recommended_hypothesis"] = None
    if failure == "contradiction":
        selected["contradicting_evidence_ids"] = [env.history_id]
    report = env.complete(snapshot, payload)
    before = state(env)
    with pytest.raises(PromotionRefused) as exc:
        env.promote_diagnosis(report)
    assert exc.value.disposition == "NEEDS_EVIDENCE"
    assert state(env) == before


def test_valid_confirmation_creates_durable_competing_hypotheses_and_application_verdict(env):
    env.confirm()
    report = env.complete(env.start())
    promotion = env.promote_diagnosis(report)
    diagnosis = env.repo.get_artifact(env.incident_id, promotion.target_id)
    verdict = env.repo.get_artifact(env.incident_id, promotion.verdict_id)
    hypotheses = [env.repo.get_artifact(env.incident_id, key) for key in diagnosis.hypothesis_ids]
    assert len(hypotheses) == 2 and all(item.id not in {"overload", "sensor", "diagnostic"} for item in hypotheses)
    assert promotion.advisory_artifact_mapping["diagnostic/overload"] == diagnosis.hypothesis_ids[0]
    assert promotion.advisory_artifact_mapping["diagnostic/sensor"] == diagnosis.alternative_hypothesis_ids[0]
    assert diagnosis.confidence is None and all(item.confidence is None for item in hypotheses)
    assert diagnosis.status == "ACCEPTED" and diagnosis.conclusion == MECHANISM
    assert set(diagnosis.evidence_ids) == set(report.evidence_manifest)
    assert verdict.validator_identity == VALIDATOR and verdict.validation_policy_version == POLICY_VERSION
    assert verdict.decision == "ACCEPT" and verdict.target_hash == digest(diagnosis)
    assert verdict.input_revision == report.input_revision
    assert verdict.falsification_attempts == ()
    assert hypotheses[0].falsification_tests == ("Suggested independent repeat load test",)
    assert verdict.check_results["trusted_mechanism_match"] and verdict.challenges
    incident = env.repo.fetch_incident(env.incident_id)
    assert incident.current_diagnosis_id == diagnosis.id and incident.phase == m.IncidentPhase.DIAGNOSIS_VALIDATED
    assert promotion.output_revision == incident.revision and incident.active_run_id is None
    assert env.service.promotion_lineage(env.incident_id, diagnosis.id, "diagnosis") == promotion
    assert not env.repo.list_approval_decisions(env.incident_id)


@pytest.mark.parametrize("field,value", [("termination_reason", "TIMEOUT"), ("termination_reason", "CANCELLED"),
    ("termination_reason", "INVALID_OUTPUT"), ("termination_reason", "LIMIT_EXHAUSTED"), ("termination_reason", "MODEL_FAILED"),
    ("exhausted_limits", ["turns"]), ("invalid_output", True), ("disposition", "BLOCKED"), ("disposition", "ESCALATED"),
    ("disposition", "UNRESOLVED"), ("blockers", ["unresolved invocation"]),
    ("unresolved_evidence_needs", [{"capability": "inspection", "question": "Additional check"}])])
def test_unsuccessful_advisory_run_never_promotes(env, field, value):
    env.confirm()
    snapshot = env.start()
    report = env.complete(snapshot, result_payload(env, snapshot) | {field: value})
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(report)


@pytest.mark.parametrize("failure", ["cycle", "wrong_incident", "wrong_run", "stale_review", "failed_call", "cancelled_call",
    "noncanonical", "unsupplied_evidence", "old_critic", "critic_reject", "diagnosis_need", "missing_delegation"])
def test_advisory_provenance_and_critic_gates(env, failure):
    env.confirm()
    snapshot = env.start()
    value = result_payload(env, snapshot)
    if failure == "cycle":
        value["assessments"][0]["assessment"]["input_assessment_keys"] = ["critic"]
    elif failure == "wrong_incident":
        value["assessments"][0]["assessment"]["incident_id"] = "foreign"
    elif failure == "wrong_run":
        value["decision"]["run_id"] = "foreign"
    elif failure == "stale_review":
        value["delegations"][1]["input_revision"] -= 1
    elif failure in {"failed_call", "cancelled_call"}:
        value["delegations"][1]["status"] = "FAILED" if failure == "failed_call" else "CANCELLED"
    elif failure == "noncanonical":
        value["candidate_diagnosis_key"] = "critic"
    elif failure == "unsupplied_evidence":
        value["delegations"][0]["evidence_ids"] = []
    elif failure == "old_critic":
        value["assessments"][1]["assessment"]["subject_id"] = "old-diagnostic"
    elif failure == "critic_reject":
        value["assessments"][1]["assessment"].update(recommendation="REJECT", contradictions=["Contradictory physical finding"])
    elif failure == "diagnosis_need":
        value["assessments"][0]["assessment"]["missing_evidence_requests"] = [{"capability": "inspection", "question": "Unresolved"}]
    else:
        value["delegations"] = value["delegations"][1:]
    report = env.complete(snapshot, value)
    with pytest.raises((PromotionRefused, InvalidReference)):
        env.promote_diagnosis(report)


def test_trusted_confirmation_cannot_be_fabricated_through_generic_repository(env):
    confirmation = env.confirm()
    with pytest.raises(InvalidReference, match="trusted PromotionService"):
        env.repo.add_artifact(confirmation.model_copy(update={"id": new_id()}), expected_revision=revision(env))
    with pytest.raises(PromotionRefused, match="independent technical"):
        env.confirm(supporting_evidence_ids=(env.signal_id,))


@pytest.mark.parametrize("field,value", [("asset_id", "foreign"), ("incident_id", "foreign")])
def test_foreign_confirmation_submission_rejected(env, field, value):
    with pytest.raises((PromotionRefused, LookupError)):
        env.confirm(**{field: value})


def test_foreign_confirmation_not_promotable(env):
    env.confirm()
    report = env.complete(env.start())
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(report, confirmation_id="foreign-confirmation")


def test_planner_prose_cannot_directly_promote(env):
    promotion, report = env.diagnosis()
    with pytest.raises((InvalidReference, PromotionRefused)):
        env.service.promote_intervention(env.incident_id, report_id=report.id, draft_id="plan", expected_revision=revision(env))
    with pytest.raises((ValidationError, TypeError)):
        env.service.create_draft(env.incident_id, expected_revision=revision(env), **report.result_payload["assessments"][-1]["assessment"])


@pytest.mark.parametrize("field", ["estimated_cost", "estimated_avoided_loss", "business_assumption_version", "duration_minutes",
    "technician_id", "window_start", "window_end", "safety_relevant", "external_commitment", "reversible"])
def test_unknown_required_binding_fields_block(env, field):
    promotion, report = env.diagnosis()
    fields = env.binding_fields(promotion, report)
    fields.pop(field)
    before = state(env)
    with pytest.raises(ValidationError):
        env.service.create_draft(env.incident_id, expected_revision=revision(env), **fields)
    assert state(env) == before


@pytest.mark.parametrize("failure", ["unknown_technician", "qualification", "undated", "unconfirmed_window", "insufficient_parts"])
def test_resource_confirmation_requires_real_resources_and_dated_attestation(env, failure):
    if failure == "insufficient_parts":
        with db.get_conn(env.repo.path) as conn:
            conn.execute("UPDATE part SET on_hand_qty=0")
    changes = {"unknown_technician": {"technician_id": "invented"}, "qualification": {"qualification": "unqualified"},
               "undated": {"available_start": None}, "unconfirmed_window": {"window_confirmed": False}}.get(failure, {})
    with pytest.raises((PromotionRefused, ValidationError)):
        env.resources(**changes)


@pytest.mark.parametrize("failure", ["engineering_conditional", "engineering_unsafe", "engineering_blocked", "engineering_constraint",
    "engineering_safety", "operations_unknown", "operations_blocked", "operations_no_resources", "missing_exact_review",
    "wrong_draft_hash", "critic_wrong_draft", "critic_stale_inputs", "critic_rejection", "evidence_need", "wrong_diagnosis"])
def test_intervention_promotion_gates(env, failure):
    draft = env.draft()
    snapshot = env.start(draft)
    value = result_payload(env, snapshot, draft=draft)
    eng, ops, critic = [item["assessment"] for item in value["assessments"]]
    if failure == "engineering_conditional":
        eng["intervention_feasibility"] = "CONDITIONAL"
    elif failure == "engineering_unsafe":
        eng["intervention_feasibility"] = "UNSAFE"
    elif failure == "engineering_blocked":
        eng.update(intervention_feasibility="INFEASIBLE", blockers=["Technical blocker"])
    elif failure == "engineering_constraint":
        eng.update(intervention_feasibility="CONDITIONAL", missing_constraints=["Unknown pressure limit"])
    elif failure == "engineering_safety":
        eng["safety_concerns"] = ["Unresolved isolation"]
    elif failure == "operations_unknown":
        ops["resource_feasibility"] = "UNKNOWN"
    elif failure == "operations_blocked":
        ops["blockers"] = ["Availability not confirmed"]
    elif failure == "operations_no_resources":
        ops["evidence_reviewed"] = [env.history_id]
    elif failure == "missing_exact_review":
        eng.pop("reviewed_intervention_id")
        eng.pop("reviewed_intervention_hash")
    elif failure == "wrong_draft_hash":
        eng["reviewed_intervention_hash"] = "wrong"
    elif failure == "critic_wrong_draft":
        critic["subject_id"] = "wrong"
    elif failure == "critic_stale_inputs":
        critic["input_assessment_keys"] = []
    elif failure == "critic_rejection":
        critic.update(recommendation="REJECT", unsupported_claims=["Not technically justified"])
    elif failure == "evidence_need":
        value["unresolved_evidence_needs"] = [{"capability": "inspection", "question": "Unresolved"}]
    else:
        eng["diagnosis_id"] = "wrong"
    report = env.complete(snapshot, value)
    before = state(env)
    with pytest.raises(PromotionRefused):
        env.promote_intervention(report, draft)
    assert state(env) == before


def test_exact_reviewed_binding_promotes_unchanged_content_without_approval(env):
    draft = env.draft()
    report = env.complete(env.start(draft), draft=draft)
    promotion = env.promote_intervention(report, draft)
    target = env.repo.get_artifact(env.incident_id, promotion.target_id)
    verdict = env.repo.get_artifact(env.incident_id, promotion.verdict_id)
    assert target.status == "VALIDATED" and target.revision > draft.revision
    assert target.steps == draft.steps and target.evidence_ids == draft.evidence_ids
    assert executable_content_hash(target) == executable_content_hash(draft) == promotion.reviewed_content_hash
    assert target.estimated_cost == 550 and target.estimated_avoided_loss == 12000
    assert target.estimated_cost != 999  # planner exposure is never a cost estimate
    assert target.risk == "HIGH" and target.window_start
    assert WorkPackageParameters.model_validate(target.steps[0].parameters).equipment_id == ASSET
    assert verdict.validator_identity == VALIDATOR and verdict.decision == "ACCEPT"
    assert env.service.promotion_lineage(env.incident_id, target.id, "intervention") == promotion
    incident = env.repo.fetch_incident(env.incident_id)
    assert incident.current_intervention_id == target.id and incident.current_diagnosis_id == target.diagnosis_id
    assert incident.phase == m.IncidentPhase.INTERVENTION_VALIDATED
    assert not any(isinstance(a, m.ApprovalRequirement) for a in env.repo.list_artifacts(env.incident_id))
    assert not env.repo.list_execution_receipts(env.incident_id)


@pytest.mark.parametrize("failure", ["capability", "parameters", "asset", "cost", "instructions", "risk"])
def test_substantive_draft_tampering_requires_new_application_binding(env, failure):
    original = env.draft()
    changes = {"id": new_id(), "supersedes_id": original.id, "revision": original.revision + 1}
    if failure == "capability":
        changes["steps"] = (original.steps[0].model_copy(update={"capability": "inspect"}),)
    elif failure == "parameters":
        changes["steps"] = (original.steps[0].model_copy(update={"parameters": original.steps[0].parameters | {"technician_id": "invented"}}),)
    elif failure == "asset":
        changes["steps"] = (original.steps[0].model_copy(update={"parameters": original.steps[0].parameters | {"equipment_id": "foreign"}}),)
    elif failure == "cost":
        changes["estimated_cost"] = 1
    elif failure == "instructions":
        changes["steps"] = (original.steps[0].model_copy(update={"preconditions": ()}),)
    else:
        changes["risk_metadata"] = {}
    draft = m.Intervention.model_validate(original.model_dump() | changes)
    env.repo.add_artifact(draft, expected_revision=revision(env))
    report = env.complete(env.start(draft), draft=draft)
    with pytest.raises(PromotionRefused):
        env.promote_intervention(report, draft)


@pytest.mark.parametrize("stage,write_index", [("diagnosis", n) for n in range(1, 13)] + [("intervention", n) for n in range(1, 9)])
def test_every_promotion_write_rolls_back_atomically(env, monkeypatch, stage, write_index):
    if stage == "diagnosis":
        env.confirm()
        report = env.complete(env.start())
        promote = lambda: env.promote_diagnosis(report)
    else:
        draft = env.draft()
        report = env.complete(env.start(draft), draft=draft)
        promote = lambda: env.promote_intervention(report, draft)
    before = state(env)
    count = 0
    def failing(method):
        def wrapped(*args, **kwargs):
            nonlocal count
            result = method(*args, **kwargs)
            count += 1
            if count == write_index:
                raise RuntimeError("injected after durable internal write")
            return result
        return wrapped
    for name in ("_store_artifact", "_update", "_event"):
        monkeypatch.setattr(env.repo, name, failing(getattr(env.repo, name)))
    with pytest.raises(RuntimeError, match="injected"):
        promote()
    assert count == write_index and state(env) == before


@pytest.mark.parametrize("stage", ["diagnosis", "intervention"])
def test_identical_concurrent_promotions_and_stale_retry_return_original(env, stage):
    if stage == "diagnosis":
        env.confirm()
        report = env.complete(env.start())
        expected = revision(env)
        promote = lambda: env.promote_diagnosis(report, expected_revision=expected)
    else:
        draft = env.draft()
        report = env.complete(env.start(draft), draft=draft)
        expected = revision(env)
        promote = lambda: env.promote_intervention(report, draft, expected_revision=expected)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: promote(), range(2)))
    assert first == second
    before = state(env)
    assert promote() == first and state(env) == before
    assert len([a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.PromotionRecord) and a.stage == stage]) == 1


def test_changed_payload_under_same_promotion_identity_conflicts(env):
    env.confirm()
    report = env.complete(env.start())
    env.promote_diagnosis(report)
    with pytest.raises(PromotionConflict):
        env.promote_diagnosis(report, confirmation_id=env.history_id, expected_revision=report.input_revision)


def test_retry_never_reactivates_superseded_authority(env):
    env.confirm()
    first_report = env.complete(env.start())
    first = env.promote_diagnosis(first_report)
    env.repo.transition(env.incident_id, m.IncidentPhase.INVESTIGATING, expected_revision=revision(env), reason="New investigation")
    second = env.promote_diagnosis(env.complete(env.start()))
    before = state(env)
    assert env.promote_diagnosis(first_report, expected_revision=first_report.input_revision) == first
    assert state(env) == before and env.repo.fetch_incident(env.incident_id).current_diagnosis_id == second.target_id
    with pytest.raises(PromotionRefused):
        env.service.promotion_lineage(env.incident_id, first.target_id, "diagnosis")


def test_legacy_and_unpromoted_artifacts_have_no_new_lineage(env):
    env.resources()
    legacy = prepare_legacy_intervention(env.repo, env.incident_id, sample_proposal())
    for stage, target in (("intervention", legacy.intervention.id), ("diagnosis", legacy.intervention.diagnosis_id)):
        with pytest.raises(PromotionRefused, match="promotion lineage"):
            env.service.promotion_lineage(env.incident_id, target, stage)
    assert env.repo.fetch_incident(env.incident_id).current_diagnosis_id is None
    assert env.repo.fetch_incident(env.incident_id).current_intervention_id is None
    fields = env.binding_fields(
        type("Record", (), {"target_id": legacy.intervention.diagnosis_id})(), type("Report", (), {"id": "legacy"})())
    with pytest.raises(PromotionRefused):
        env.service.create_draft(env.incident_id, expected_revision=revision(env), **fields)


@pytest.mark.parametrize("kind", ["SupervisorRunSnapshot", "SupervisorReport", "PromotionRecord"])
def test_migration_uniqueness_and_repeat_safety(env, kind):
    env.confirm()
    snapshot = env.start()
    report = env.complete(snapshot)
    promotion = env.promote_diagnosis(report)
    artifact = {"SupervisorRunSnapshot": snapshot, "SupervisorReport": report, "PromotionRecord": promotion}[kind]
    before = state(env)
    db.init_schema(env.repo.path)
    db.init_schema(env.repo.path)
    assert state(env) == before
    duplicate = artifact.model_copy(update={"id": new_id()})
    with db.get_conn(env.repo.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO incident_artifact VALUES (?,?,?,?,?,?,?)", (
                duplicate.id, env.incident_id, kind, 1, duplicate.created_at.isoformat(), digest(duplicate), duplicate.model_dump_json()))
    with pytest.raises(InvalidReference, match="trusted PromotionService"):
        env.repo.add_artifact(duplicate, expected_revision=revision(env))


class NativePromotionSpecialists(ScriptedModel):
    """Only the provider boundary is scripted; all SDK delegations execute."""
    def __init__(self, env, draft=None):
        super().__init__()
        self.env, self.draft = env, draft
        self.packets = []

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        from core.reliability.orchestration import ROLE_CONTRACTS
        context = SpecialistContext.model_validate_json(messages[0]["content"][0]["text"])
        role = next(role for role, cls in ROLE_CONTRACTS.items() if cls.__name__ in {item["name"] for item in tool_specs})
        self.packets.append(context)
        snapshot = next(a for a in self.env.repo.list_artifacts(context.incident_id)
                        if isinstance(a, m.SupervisorRunSnapshot) and a.run_id == context.run_id)
        example = result_payload(self.env, snapshot, draft=self.draft)
        value = next(item["assessment"] for item in example["assessments"]
                     if isinstance(AdvisoryInput.model_validate(item).assessment, ROLE_CONTRACTS[role]))
        mapping = {"plan" if source_role == "planner" else source_role: item.key
                   for item in context.advisory_inputs for source_role, cls in ROLE_CONTRACTS.items()
                   if isinstance(item.assessment, cls)}
        value["input_assessment_keys"] = [mapping[key] for key in value.get("input_assessment_keys", [])]
        if role == "critic" and not self.draft:
            value["subject_id"] = mapping["diagnostic"]
        self.turns = iter([[(ROLE_CONTRACTS[role].__name__, value)]])
        async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


@pytest.mark.parametrize("stage", ["diagnosis", "intervention"])
async def test_native_strands_runs_can_cross_only_the_application_boundary(env, stage):
    from tests.test_supervisor import delegation, decision
    if stage == "diagnosis":
        env.confirm()
        draft = None
        turns = [delegation("diagnostic"), delegation("critic", ("diagnostic",)),
                 delegation("planner", ("diagnostic", "critic"))]
    else:
        draft = env.draft()
        turns = [delegation("engineering"), delegation("operations", ("engineering",)),
                 delegation("critic", ("engineering", "operations"))]
    def finish(messages):
        context = SpecialistContext.model_validate(json.loads(messages[0]["content"][0]["text"])["context"])
        return decision(context, "ADVISORY_CONCLUSION")(messages)
    model = ScriptedModel([*turns, finish])
    specialists = NativePromotionSpecialists(env, draft)
    report = await env.service.run_supervisor(env.incident_id, service=env.evidence_service,
        runtime=StrandsRuntime(settings(), model=model), specialist_runtime=StrandsRuntime(settings(), model=specialists),
        asset_id=ASSET, stage="INTERVENTION_REVIEW" if draft else "DIAGNOSIS", expected_revision=revision(env),
        evidence_ids=draft.evidence_ids if draft else env.evidence_ids(), draft_id=draft.id if draft else None)
    assert report.completion == "MODEL_COMPLETED", report.result_payload
    assert report.result_payload["disposition"] == "ADVISORY_CONCLUSION", report.result_payload
    if draft:
        assert all(packet.review_target_id == draft.id and packet.review_target_hash == digest(draft) for packet in specialists.packets)
        promotion = env.promote_intervention(report, draft)
    else:
        assert env.repo.fetch_incident(env.incident_id).current_diagnosis_id is None
        promotion = env.promote_diagnosis(report)
    assert env.service.promotion_lineage(env.incident_id, promotion.target_id, stage) == promotion


@pytest.mark.parametrize("failure", ["unresolved_request", "superseded_evidence", "wrong_asset_run", "wrong_incident_report"])
def test_durable_scope_and_evidence_prerequisites(env, failure):
    env.confirm()
    if failure == "unresolved_request":
        request = m.EvidenceRequest(id=new_id(), created_at=utcnow(), incident_id=env.incident_id,
            requested_by="diagnostic", equipment_ids=(ASSET,), question="Check unresolved need", capability="inspection", required_for="diagnosis")
        env.repo.add_artifact(request, expected_revision=revision(env))
        report = env.complete(env.start())
        with pytest.raises(PromotionRefused, match="unresolved durable"):
            env.promote_diagnosis(report)
    elif failure == "superseded_evidence":
        history = env.repo.get_artifact(env.incident_id, env.history_id)
        env.repo.add_artifact(history.model_copy(update={"id": new_id(), "supersedes_id": history.id}), expected_revision=revision(env))
        with pytest.raises(PromotionRefused, match="superseded"):
            env.start()
    elif failure == "wrong_asset_run":
        with pytest.raises(PromotionRefused, match="asset"):
            env.service.start_run(env.incident_id, asset_id="wrong", stage="DIAGNOSIS", expected_revision=revision(env),
                                  evidence_ids=env.evidence_ids(), runtime=env.runtime)
    else:
        report = env.complete(env.start())
        other = env.repo.create_incident((ASSET,), admission_key="foreign incident")
        with pytest.raises(InvalidReference):
            env.service.promote_diagnosis(other.id, report_id=report.id, confirmation_id=env.confirmation.id, expected_revision=other.revision)


def test_read_only_unknown_workforce_snapshot_is_insufficient(env):
    from core.reliability.resources import ResourceCapabilities
    promotion, report = env.diagnosis()
    snapshot = ResourceCapabilities(env.evidence_service.capabilities).inspect_available_technicians(ASSET)
    assert snapshot.availability == "UNKNOWN"
    unknown = env.resource.model_copy(update={"id": new_id(), "payload": snapshot.model_dump(mode="json"),
        "source_capability": "inspect_available_technicians", "source_system": "operon.resources",
        "content_hash": content_hash(snapshot.model_dump(mode="json"))})
    env.repo.add_artifact(unknown, expected_revision=revision(env))
    with pytest.raises(PromotionRefused, match="dated resource"):
        env.service.create_draft(env.incident_id, expected_revision=revision(env),
            **(env.binding_fields(promotion, report) | {"resource_confirmation_id": unknown.id}))


@pytest.mark.parametrize("table,sql", [
    ("inventory", "UPDATE part SET on_hand_qty=0"),
    ("technician", "UPDATE technician SET available=0"),
    ("qualification", "UPDATE technician SET skills='UNQUALIFIED'"),
    ("equipment", "UPDATE equipment SET equipment_class='CHANGED' WHERE equipment_id='AC-COMP-01'"),
    ("booking", "INSERT INTO labor_booking (technician_id,status) SELECT technician_id,'BOOKED' FROM technician LIMIT 1"),
    ("telemetry", "INSERT INTO sensor_reading (sensor_id,ts,value_eu) SELECT sensor_id,'2026-09-10T00:00:00Z',123 FROM sensor LIMIT 1"),
])
def test_raw_operational_changes_after_exact_review_cannot_promote(env, table, sql):
    draft = env.draft()
    report = env.complete(env.start(draft), draft=draft)
    checkpoint = revision(env)
    with db.get_conn(env.repo.path) as conn:
        conn.execute(sql)
    assert revision(env) == checkpoint
    with pytest.raises(PromotionRefused, match="raw operational"):
        env.promote_intervention(report, draft)


def test_new_technical_evidence_invalidates_current_diagnosis_for_binding(env):
    promotion, report = env.diagnosis()
    env.confirm()
    with pytest.raises(PromotionRefused, match="new technical evidence"):
        env.service.create_draft(env.incident_id, expected_revision=revision(env), **env.binding_fields(promotion, report))


def test_changed_draft_under_same_promotion_identity_conflicts(env):
    draft = env.draft()
    report = env.complete(env.start(draft), draft=draft)
    env.promote_intervention(report, draft)
    different = draft.model_copy(update={"id": new_id()})
    env.repo.add_artifact(different, expected_revision=revision(env))
    with pytest.raises(PromotionConflict):
        env.promote_intervention(report, different, expected_revision=report.input_revision)


@pytest.mark.parametrize("command", ["start", "complete"])
def test_run_claim_and_report_writes_are_atomic(env, monkeypatch, command):
    snapshot = env.start() if command == "complete" else None
    before = state(env)
    original = env.repo._update
    def failure(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("checkpoint failure")
    monkeypatch.setattr(env.repo, "_update", failure)
    with pytest.raises(RuntimeError, match="checkpoint failure"):
        env.complete(snapshot) if snapshot else env.start()
    assert state(env) == before


def test_pre_004_artifact_hashes_survive_additive_metadata(env):
    hypothesis = m.Hypothesis(id=new_id(), created_at=utcnow(), incident_id=env.incident_id,
        equipment_ids=(ASSET,), mechanism="Legacy hypothesis", confidence=0.3, confidence_basis="Legacy advisory", falsification_tests=())
    env.repo.add_artifact(hypothesis, expected_revision=revision(env))
    diagnosis = m.Diagnosis(id=new_id(), created_at=utcnow(), incident_id=env.incident_id,
        equipment_ids=(ASSET,), hypothesis_ids=(hypothesis.id,), conclusion="Legacy candidate", evidence_ids=(), confidence=0.3)
    env.repo.add_artifact(diagnosis, expected_revision=revision(env))
    old_intervention = dict(id=new_id(), created_at=utcnow().isoformat().replace("+00:00", "Z"), incident_id=env.incident_id, schema_version=1,
        diagnosis_id=diagnosis.id, revision=1, steps=[dict(schema_version=1, id=new_id(), created_at=utcnow().isoformat().replace("+00:00", "Z"),
            capability="inspect", equipment_ids=[ASSET], parameters={}, depends_on=[], preconditions=[], verification_criteria=[])],
        evidence_ids=[], risk="HIGH", window_start=None, window_end=None, estimated_cost=1.0, estimated_downtime_minutes=1,
        estimated_avoided_loss=1.0, business_assumption_version="legacy", status="DRAFT", supersedes_id=None)
    artifact = m.Intervention.model_validate(old_intervention)
    assert digest(artifact) == content_hash(old_intervention)
    env.repo.add_artifact(artifact, expected_revision=revision(env))
    with pytest.raises(PromotionRefused, match="lacks application promotion lineage"):
        env.service.promotion_lineage(env.incident_id, artifact.id, "intervention")
    db.init_schema(env.repo.path)
    assert digest(env.repo.get_artifact(env.incident_id, artifact.id)) == content_hash(old_intervention)


def test_source_change_then_restoration_still_invalidates_run(env):
    env.confirm()
    snapshot = env.start()
    with db.get_conn(env.repo.path) as conn:
        conn.execute("UPDATE part SET on_hand_qty=on_hand_qty+1")
        conn.execute("UPDATE part SET on_hand_qty=on_hand_qty-1")
    report = env.complete(snapshot)
    assert "RAW_SOURCE_CHANGED" in report.stale_reasons
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(report)


def test_later_application_rejection_invalidates_diagnosis_lineage(env):
    promotion, report = env.diagnosis()
    diagnosis = env.repo.get_artifact(env.incident_id, promotion.target_id)
    rejection = m.ValidationVerdict(id=new_id(), created_at=utcnow(), incident_id=env.incident_id,
        target_kind="diagnosis", target_id=diagnosis.id, target_hash=digest(diagnosis), input_revision=revision(env),
        decision="REJECT", blocking_issues=("Trusted later review contradicts mechanism",), validator_run_id="application-review")
    env.repo.add_artifact(rejection, expected_revision=revision(env))
    with pytest.raises(PromotionRefused, match="outstanding application rejection"):
        env.service.create_draft(env.incident_id, expected_revision=revision(env), **env.binding_fields(promotion, report))


async def test_native_cancellation_retains_completed_delegation_audit(env):
    from tests.test_supervisor import delegation
    env.confirm()
    waiting = asyncio.Event()
    class PausingSupervisor(ScriptedModel):
        async def stream(self, *args, **kwargs):
            if self.calls:
                waiting.set()
                await asyncio.Event().wait()
            async for event in super().stream(*args, **kwargs):
                yield event
    supervisor = PausingSupervisor([delegation("diagnostic")])
    task = asyncio.create_task(env.service.run_supervisor(env.incident_id, service=env.evidence_service,
        runtime=StrandsRuntime(settings(), model=supervisor),
        specialist_runtime=StrandsRuntime(settings(), model=NativePromotionSpecialists(env)),
        asset_id=ASSET, stage="DIAGNOSIS", expected_revision=revision(env), evidence_ids=env.evidence_ids()))
    await asyncio.wait_for(waiting.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    report = next(a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.SupervisorReport))
    result = SupervisorResult.model_validate(report.result_payload)
    assert result.termination_reason == "CANCELLED"
    assert len(result.delegations) == len(result.assessments) == 1
    assert result.delegations[0].status == "SUCCEEDED"


async def test_native_corrected_invalid_specialist_output_is_not_promotable(env):
    from tests.test_supervisor import delegation, decision
    env.confirm()
    class CorrectedSpecialist(NativePromotionSpecialists):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            if not self.calls:
                self.turns = iter([[('DiagnosticAssessment', {'invalid': True})]])
                async for event in ScriptedModel.stream(self, messages, tool_specs, system_prompt, **kwargs):
                    yield event
            else:
                async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
                    yield event
    def finish(messages):
        context = SpecialistContext.model_validate(json.loads(messages[0]['content'][0]['text'])['context'])
        return decision(context, 'UNRESOLVED')(messages)
    report = await env.service.run_supervisor(env.incident_id, service=env.evidence_service,
        runtime=StrandsRuntime(settings(), model=ScriptedModel([delegation('diagnostic'), finish])),
        specialist_runtime=StrandsRuntime(settings(), model=CorrectedSpecialist(env)),
        asset_id=ASSET, stage='DIAGNOSIS', expected_revision=revision(env), evidence_ids=env.evidence_ids())
    result = SupervisorResult.model_validate(report.result_payload)
    assert result.delegations[0].status == 'FAILED'
    assert not result.assessments
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(report)


def test_stale_cached_evidence_is_recollected_for_a_fresh_run(env):
    original = env.repo.get_artifact(env.incident_id, env.history_id)
    with db.get_conn(env.repo.path) as conn:
        conn.execute("UPDATE maintenance_event SET note=note || ' revised observation'")
    fresh = env.evidence_service.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
        question="Read recorded service history", capability="get_maintenance_history", required_for="diagnosis")
    assert not fresh.reused and fresh.evidence.id != original.id and fresh.evidence.supersedes_id == original.id
    env.history_id = fresh.evidence.id
    env.confirm()
    promotion = env.promote_diagnosis(env.complete(env.start()))
    assert original.id not in promotion.evidence_manifest and fresh.evidence.id in promotion.evidence_manifest


def test_resource_evidence_preserves_application_checked_inventory_quantities(env):
    evidence = env.resources()
    confirmation = m.ResourceConfirmation.model_validate(evidence.payload)
    assert confirmation.inventory_snapshot
    for part in confirmation.inventory_snapshot:
        assert part.on_hand_quantity - part.reserved_quantity >= part.required_quantity > 0
    assert confirmation.provenance == evidence.provenance == "SIMULATED"


def test_concurrent_run_claims_require_the_current_revision(env):
    checkpoint = revision(env)
    def start(_):
        try:
            return env.service.start_run(env.incident_id, asset_id=ASSET, stage="DIAGNOSIS", expected_revision=checkpoint,
                evidence_ids=env.evidence_ids(), runtime=env.runtime)
        except StaleRevision:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, range(2)))
    snapshots = [value for value in results if value is not None]
    assert len(snapshots) == 1 and env.repo.fetch_incident(env.incident_id).active_run_id == snapshots[0].run_id
    assert len([a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.SupervisorRunSnapshot)]) == 1
