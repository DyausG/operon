"""Step 15A: the application trust boundary for results produced elsewhere.

A crafted 'perfect' response never changes state by itself; only the unchanged
_complete_run -> _settle -> promote_* path does, over the validated result.
"""
import json

import pytest

from core.agents.contracts import SpecialistContext, SupervisorResult
from core.agents.runtime import StrandsRuntime
from core.reliability import models as m
from core.reliability.promotion import PromotionRefused
from core.reasoning.errors import ReasoningBackendUnavailable
from core.reasoning.handler import handler_identity
from core.reasoning.protocol import PROTOCOL_VERSION, ReasoningResponse
from core.reasoning.trust import validate_response
from tests.test_promotion import ASSET, Environment, result_payload, state
from tests.test_incident_state import signal
from tests.test_strands_agents import ScriptedModel, protected_state, settings


@pytest.fixture
def env(seeded_db):
    return Environment()


def runtime():
    return StrandsRuntime(settings(), model=ScriptedModel())


def envelope(env, snapshot, result=None, identity=None, **changes):
    identity = identity or handler_identity(runtime())
    payload = dict(protocol_version=PROTOCOL_VERSION, incident_id=env.incident_id, run_id=snapshot.run_id,
                   snapshot_id=snapshot.id, input_revision=snapshot.input_revision, status="COMPLETED",
                   runtime_identity=identity.model_dump(mode="json"),
                   result=result if result is not None else result_payload(env, snapshot),
                   telemetry={"duration_ms": 5, "trace_id": "trace-1"})
    return json.loads(json.dumps(payload | changes))


def validate(env, snapshot, response, identity=None):
    context = SpecialistContext.model_validate(snapshot.context_payload)
    return validate_response(snapshot=snapshot, context=context, response=response, repository=env.repo,
                             expected_identity=identity or handler_identity(runtime()))


def test_valid_response_is_revalidated_and_changes_nothing_until_the_application_promotes(env):
    env.confirm()
    env.resources()
    snapshot = env.start()
    before = protected_state(env.repo, env.incident_id)
    durable = state(env)
    validated = validate(env, snapshot, envelope(env, snapshot))
    assert isinstance(validated, SupervisorResult)
    assert validated.disposition == "ADVISORY_CONCLUSION" and validated.termination_reason == "MODEL_COMPLETED"
    assert validated.evidence_used == tuple(sorted(snapshot.evidence_manifest))
    assert validated.candidate_diagnosis_key == "diagnostic" and validated.critic_keys == ("critic",)
    # Validation alone is inert: no report, no phase change, no protected rows touched.
    assert protected_state(env.repo, env.incident_id) == before and state(env) == durable
    # The unchanged application path then persists, audits and promotes the validated result.
    report = env.service._complete_run(snapshot, validated)
    assert report.completion == "MODEL_COMPLETED" and not report.stale_reasons
    assert env.repo.fetch_incident(env.incident_id).phase == m.IncidentPhase.INVESTIGATING
    promotion = env.promote_diagnosis(report)
    incident = env.repo.fetch_incident(env.incident_id)
    assert incident.phase == m.IncidentPhase.DIAGNOSIS_VALIDATED and incident.current_diagnosis_id == promotion.target_id


@pytest.mark.parametrize("change,code", [
    ({"incident_id": "wrong"}, "CORRELATION"), ({"run_id": "wrong"}, "CORRELATION"),
    ({"snapshot_id": "wrong"}, "CORRELATION"), ({"input_revision": 1}, "CORRELATION"),
    ({"protocol_version": "operon-reasoning-2"}, "PROTOCOL_MISMATCH"), ({"database": "/tmp/x"}, "PROTOCOL"),
    ({"result": {"authority": True}}, "PROTOCOL"), ({"runtime_identity": None}, "PROTOCOL"),
])
def test_envelope_faults_are_rejected(env, change, code):
    snapshot = env.start()
    before = state(env)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        validate(env, snapshot, envelope(env, snapshot, **change))
    assert failure.value.code == code and failure.value.retryable is False
    assert state(env) == before


@pytest.mark.parametrize("field", ["prompts", "result_schema", "context_schema", "strands_version",
                                   "supervisor_model_id", "specialist_model_id", "region", "policy"])
def test_runtime_identity_drift_is_refused(env, field):
    snapshot = env.start()
    drifted = handler_identity(runtime()).model_copy(update={field: "drifted-value"})
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        validate(env, snapshot, envelope(env, snapshot, identity=drifted))
    assert failure.value.code == "VERSION_MISMATCH" and field in str(failure.value)
    # build_id is informational and never refuses advice.
    validate(env, snapshot, envelope(env, snapshot, identity=handler_identity(runtime()).model_copy(update={"build_id": "sha-1"})))


def test_failed_status_passes_its_code_and_retryability_through(env):
    snapshot = env.start()
    response = envelope(env, snapshot, status="FAILED", runtime_identity=None,
                        failure={"code": "MODEL_UNAVAILABLE", "message": "throttled", "retryable": True})
    response["result"] = None
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        validate(env, snapshot, response)
    assert failure.value.code == "MODEL_UNAVAILABLE" and failure.value.retryable is True


def foreign_evidence(env):
    other = env.repo.create_incident(("HYD-PUMP-03",), admission_key="other")
    return env.evidence_service.request_and_collect(
        other.id, requested_by="diagnostic", equipment_ids=("HYD-PUMP-03",), question="Read",
        capability="get_asset_context", required_for="diagnosis").evidence.id


def same_incident_unpacked_evidence(env):
    return env.evidence_service.request_and_collect(
        env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,), question="Later read",
        capability="get_asset_context", required_for="diagnosis").evidence.id


def mutate(env, payload, kind):
    if kind == "bounds":
        payload["bounds"] = payload["bounds"] | {"max_delegations": 3}
    elif kind == "result_scope":
        payload["run_id"] = "wrong"
    elif kind == "unknown_evidence":
        payload["evidence_used"] = list(payload["evidence_used"]) + ["invented"]
    elif kind == "foreign_evidence":
        payload["assessments"][0]["assessment"]["evidence_reviewed"].append(foreign_evidence(env))
    elif kind == "unpacked_same_incident_evidence":
        payload["delegations"][0]["evidence_ids"].append(same_incident_unpacked_evidence(env))
    elif kind == "collected_request":
        payload["evidence_requests"] = [dict(requested_by="supervisor", capability="get_telemetry_window",
                                             question="q", status="COLLECTED", evidence_id=None, request_id=None)]
    elif kind == "request_with_identity":
        payload["evidence_requests"] = [dict(requested_by="supervisor", capability="get_telemetry_window",
                                             question="q", status="FAILED", evidence_id=payload["evidence_used"][0])]
    elif kind == "delegation_revision":
        payload["delegations"][0]["input_revision"] = payload["input_revision"] + 1
    elif kind == "role_mismatch":
        payload["delegations"][0]["role"] = "engineering"
    elif kind == "unsupplied_decision_key":
        payload["decision"]["maintenance_plan_key"] = "invented"
        payload["maintenance_plan_key"] = "invented"
    elif kind == "assessment_without_delegation":
        payload["delegations"] = payload["delegations"][:-1]
    elif kind == "selection_not_canonical":
        payload["candidate_diagnosis_key"] = None
    elif kind == "foreign_assessment_incident":
        payload["assessments"][0]["assessment"]["incident_id"] = "other"
    elif kind == "inputs_not_closure":
        payload["delegations"][2]["input_assessment_keys"] = ["critic"]
    elif kind == "too_many_delegations":
        record = payload["delegations"][0]
        payload["delegations"] = [dict(record, key=f"d{index}") for index in range(11)]
        payload["assessments"] = [dict(payload["assessments"][0], key=f"d{index}") for index in range(11)]
    return payload


@pytest.mark.parametrize("kind", [
    "bounds", "result_scope", "unknown_evidence", "foreign_evidence", "unpacked_same_incident_evidence",
    "collected_request", "request_with_identity", "delegation_revision", "role_mismatch",
    "unsupplied_decision_key", "assessment_without_delegation", "selection_not_canonical",
    "foreign_assessment_incident", "inputs_not_closure", "too_many_delegations",
])
def test_result_faults_are_rejected_with_nothing_persisted(env, kind):
    snapshot = env.start()
    payload = mutate(env, result_payload(env, snapshot), kind)
    before = state(env)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        validate(env, snapshot, envelope(env, snapshot, result=payload))
    assert failure.value.code in {"RESULT_INVALID", "PROTOCOL"} and failure.value.retryable is False
    assert state(env) == before


def test_conservative_merge_never_trusts_the_remote_disposition(env):
    snapshot = env.start()
    optimistic = result_payload(env, snapshot) | {"blockers": ["Remote noted a blocker"]}
    validated = validate(env, snapshot, envelope(env, snapshot, result=optimistic))
    assert validated.disposition == "UNRESOLVED" and "Remote noted a blocker" in validated.blockers
    cautious = result_payload(env, snapshot) | {"disposition": "NEEDS_EVIDENCE"}
    validated = validate(env, snapshot, envelope(env, snapshot, result=cautious))
    assert validated.disposition == "NEEDS_EVIDENCE"
    needy = result_payload(env, snapshot) | {"unresolved_evidence_needs": [{"capability": "inspection", "question": "Look"}]}
    validated = validate(env, snapshot, envelope(env, snapshot, result=needy))
    assert validated.disposition == "NEEDS_EVIDENCE" and validated.unresolved_evidence_needs[0].capability == "inspection"
    deferred = result_payload(env, snapshot) | {"evidence_requests": [dict(
        requested_by="supervisor", capability="get_telemetry_window", question="Longer window", status="DEFERRED",
        parameters={"sample_limit": 120}, required_for="diagnosis")]}
    validated = validate(env, snapshot, envelope(env, snapshot, result=deferred))
    assert validated.disposition == "NEEDS_EVIDENCE" and validated.evidence_requests[0].status == "DEFERRED"
    report = env.service._complete_run(snapshot, validated)
    with pytest.raises(PromotionRefused, match="not a supported advisory conclusion"):
        env.promote_diagnosis(report)
    failed = result_payload(env, snapshot) | {"delegations": [
        dict(record, status="FAILED", error_code="SpecialistInvocationError") if record["key"] == "plan" else record
        for record in result_payload(env, snapshot)["delegations"]]}
    failed["assessments"] = [item for item in failed["assessments"] if item["key"] != "plan"]
    failed["maintenance_plan_key"] = None
    failed["decision"]["maintenance_plan_key"] = None
    validated = validate(env, snapshot, envelope(env, snapshot, result=failed))
    assert validated.disposition == "BLOCKED"
    aborted = result_payload(env, snapshot) | {"termination_reason": "MODEL_FAILED"}
    assert validate(env, snapshot, envelope(env, snapshot, result=aborted)).disposition == "ESCALATED"
    exhausted = result_payload(env, snapshot) | {"exhausted_limits": ["supervisor_tool_calls"]}
    validated = validate(env, snapshot, envelope(env, snapshot, result=exhausted))
    assert validated.disposition == "ESCALATED" and validated.termination_reason == "LIMIT_EXHAUSTED"


def test_validated_result_cannot_be_reused_by_another_incident_or_run(env):
    snapshot = env.start()
    validated = validate(env, snapshot, envelope(env, snapshot))
    other, _ = env.repo.admit_signal(signal("HYD-PUMP-03"))
    other_signal_id = other.signal_evidence_ids[0]
    env.repo.transition(other.id, m.IncidentPhase.INVESTIGATING, expected_revision=other.revision, reason="test")
    evidence = env.evidence_service.request_and_collect(
        other.id, requested_by="diagnostic", equipment_ids=("HYD-PUMP-03",), question="Read",
        capability="get_asset_context", required_for="diagnosis").evidence
    other_snapshot = env.service.start_run(
        other.id, asset_id="HYD-PUMP-03", stage="DIAGNOSIS", expected_revision=env.repo.fetch_incident(other.id).revision,
        evidence_ids=(other_signal_id, evidence.id), runtime=runtime())
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        validate_response(snapshot=other_snapshot, context=SpecialistContext.model_validate(other_snapshot.context_payload),
                          response=envelope(env, snapshot), repository=env.repo, expected_identity=handler_identity(runtime()))
    assert failure.value.code == "CORRELATION"
    with pytest.raises(PromotionRefused):
        env.service._complete_run(other_snapshot, validated)
    later = env.start()  # supersedes the first run
    with pytest.raises(PromotionRefused):
        env.service._complete_run(later, validated)
    assert env.repo.fetch_incident(env.incident_id).phase == m.IncidentPhase.INVESTIGATING


def test_response_model_rejects_inconsistent_envelopes():
    with pytest.raises(ValueError):
        ReasoningResponse(status="COMPLETED", result={})
    with pytest.raises(ValueError):
        ReasoningResponse(status="FAILED", result={}, failure={"code": "INTERNAL", "message": "x", "retryable": True})
    with pytest.raises(ValueError):
        ReasoningResponse(status="FAILED")
