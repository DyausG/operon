"""Step 15A: the pure reasoning handler over the packet, with real Strands loops."""
import json
import sqlite3

import pytest
from botocore.exceptions import ClientError

from core.agents.contracts import SpecialistContext, SupervisorBounds, SupervisorResult
from core.agents.runtime import StrandsRuntime
from core.agents.supervisor import supervise_reliability
from core.reliability import models as m
from core.reasoning.handler import handler_identity, reason
from core.reasoning.packet import build_request
from core.reasoning.protocol import PROTOCOL_VERSION, ReasoningResponse
from tests.test_promotion import ASSET, Environment
from tests.test_strands_agents import ScriptedModel, protected_state, settings
from core.agents.tools import SPECIALIST_TOOL_NAMES
from tests.test_supervisor import SpecialistsModel, decision, delegation, evidence_followup, supported_need, workflow


def packet_reads(role, packet, messages, response):
    """Every role first performs all of its allowed read tools, then reports."""
    if len(messages) == 1:
        return [(name, {}) for name in sorted(SPECIALIST_TOOL_NAMES[role] - {"request_evidence"})]
    return response


class Guard:
    """Block SQLite only for the reasoning call, never for the test fixtures."""
    def __enter__(self):
        self.context = pytest.MonkeyPatch.context()
        block_sqlite(self.context.__enter__())
        return self

    def __exit__(self, *exc):
        self.context.__exit__(*exc)


@pytest.fixture
def env(seeded_db):
    return Environment()


def prepared(env):
    snapshot = env.start()
    context = SpecialistContext.model_validate(snapshot.context_payload)
    incident = env.repo.fetch_incident(env.incident_id)
    return snapshot, context, incident


def request_for(env, snapshot, context, incident, runtime, specialists=None, **overrides):
    expected = handler_identity(runtime, specialists)
    if overrides:
        expected = expected.model_copy(update=overrides)
    return build_request(env.evidence_service, incident, context, SupervisorBounds.model_validate(snapshot.bounds),
                         snapshot_id=snapshot.id, expected_identity=expected)


def runtimes(turns, specialists=None):
    return StrandsRuntime(settings(), model=ScriptedModel(turns)), StrandsRuntime(settings(), model=specialists or SpecialistsModel())


def normalized(result: SupervisorResult) -> str:
    """Delegation keys are fresh application ids per run; compare modulo them."""
    text = result.model_dump_json()
    for index, record in enumerate(result.delegations):
        text = text.replace(record.key, f"assessment:{index}")
    return text


def block_sqlite(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the reasoning handler must never open SQLite")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr("core.db.get_conn", forbidden)


async def test_handler_parity_with_local_supervisor_over_the_same_packet(env):
    snapshot, context, incident = prepared(env)
    local_runtime, local_specialists = runtimes(workflow(context), SpecialistsModel(transform=packet_reads))
    local = await supervise_reliability(local_runtime, env.evidence_service, context,
                                        bounds=SupervisorBounds.model_validate(snapshot.bounds),
                                        specialist_runtime=local_specialists)
    runtime, specialists = runtimes(workflow(context), SpecialistsModel(transform=packet_reads))
    request = request_for(env, snapshot, context, incident, runtime, specialists)
    before = protected_state(env.repo, env.incident_id)
    artifacts = env.repo.list_artifacts(env.incident_id)
    with Guard():
        response = await reason(json.loads(request.model_dump_json()), runtime, specialists)
    assert response.status == "COMPLETED" and response.protocol_version == PROTOCOL_VERSION
    assert (response.incident_id, response.run_id, response.snapshot_id, response.input_revision) == (
        env.incident_id, snapshot.run_id, snapshot.id, snapshot.input_revision)
    assert response.runtime_identity == request.expected_identity
    remote = SupervisorResult.model_validate(response.result)
    assert normalized(remote) == normalized(local)
    assert remote.disposition == "NEEDS_EVIDENCE" and len(remote.delegations) == 6
    assert all(item.status == "SUCCEEDED" for item in remote.delegations)
    # Every packet-served read succeeded remotely, with the same observation payloads
    # the local tools read from the store (only the collection clock differs).
    def observations(model):
        seen = []
        for call in model.calls[1::2]:
            for block in call["messages"][-1]["content"]:
                assert block["toolResult"]["status"] == "success"
                payload = block["toolResult"]["content"][0]["json"]
                payload["provenance"].pop("collected_at")
                seen.append(payload)
        return seen
    remote_reads, local_reads = observations(specialists._model), observations(local_specialists._model)
    assert len(remote_reads) == len(local_reads) > 0 and remote_reads == local_reads
    assert protected_state(env.repo, env.incident_id) == before
    assert env.repo.list_artifacts(env.incident_id) == artifacts


@pytest.mark.parametrize("path", ["supervisor", "nested"])
async def test_evidence_needs_are_deferred_not_collected(env, path):
    snapshot, context, incident = prepared(env)
    if path == "supervisor":
        turns = [delegation("diagnostic"), evidence_followup("diagnostic", 0, {"sample_limit": 120}), decision(context)]
        transform = supported_need
    else:
        def transform(role, packet, messages, response):
            if role == "diagnostic" and len(messages) == 1:
                return [("request_evidence", {"query": {"capability": "get_telemetry_window",
                                                       "question": "Collect vibration readings",
                                                       "parameters": {"sample_limit": 120}}})]
            if role == "diagnostic":
                block = messages[-1]["content"][0]["toolResult"]
                assert block["status"] == "error" and "deferred" in json.dumps(block)
            return supported_need(role, packet, messages, response)
        turns = [delegation("diagnostic"), decision(context)]
    runtime, specialists = runtimes(turns, SpecialistsModel(transform=transform))
    request = request_for(env, snapshot, context, incident, runtime, specialists)
    before = protected_state(env.repo, env.incident_id)
    artifacts = env.repo.list_artifacts(env.incident_id)
    with Guard():
        response = await reason(json.loads(request.model_dump_json()), runtime, specialists)
    assert response.status == "COMPLETED"
    result = SupervisorResult.model_validate(response.result)
    record = result.evidence_requests[0]
    assert record.status == "DEFERRED" and record.evidence_id is None and record.request_id is None
    assert record.parameters == {"sensor_type": None, "start_at": None, "end_at": None, "sample_limit": 120}
    assert record.required_for == "diagnosis" and record.capability == "get_telemetry_window"
    assert record.requested_by == ("supervisor" if path == "supervisor" else "diagnostic")
    assert result.disposition == "NEEDS_EVIDENCE" and result.termination_reason == "MODEL_COMPLETED"
    assert any(need.capability == "get_telemetry_window" for need in result.unresolved_evidence_needs)
    assert not any("acquisition failed" in item for item in result.blockers)
    assert result.delegations[0].status == "SUCCEEDED"
    assert protected_state(env.repo, env.incident_id) == before
    assert env.repo.list_artifacts(env.incident_id) == artifacts


@pytest.mark.parametrize("fault,code", [
    ("protocol", "PROTOCOL_MISMATCH"), ("identity", "VERSION_MISMATCH"), ("unknown_field", "PACKET_INVALID"),
    ("foreign_evidence", "PACKET_INVALID"), ("revision", "PACKET_INVALID"), ("not_json_object", "PROTOCOL_MISMATCH"),
])
async def test_protocol_identity_and_packet_faults_fail_before_any_model_call(env, fault, code):
    snapshot, context, incident = prepared(env)
    runtime, specialists = runtimes(workflow(context))
    overrides = {"prompts": "sha256:drifted"} if fault == "identity" else {}
    request = request_for(env, snapshot, context, incident, runtime, specialists, **overrides)
    payload = json.loads(request.model_dump_json())
    if fault == "protocol":
        payload["protocol_version"] = "operon-reasoning-2"
    elif fault == "unknown_field":
        payload["database_path"] = "/tmp/poc.db"
    elif fault == "foreign_evidence":
        other = env.repo.create_incident(("HYD-PUMP-03",), admission_key="other")
        foreign = env.evidence_service.request_and_collect(
            other.id, requested_by="diagnostic", equipment_ids=("HYD-PUMP-03",), question="Read",
            capability="get_asset_context", required_for="diagnosis").evidence
        payload["context"]["evidence"].append(foreign.model_dump(mode="json"))
    elif fault == "revision":
        payload["incident"]["revision"] += 1
    elif fault == "not_json_object":
        payload = ["not", "an", "object"]
    with Guard():
        response = await reason(payload, runtime, specialists)
    assert response.status == "FAILED" and response.failure.code == code and response.failure.retryable is False
    assert response.result is None
    assert not runtime._model.calls and not specialists._model.calls
    if fault != "not_json_object":
        assert (response.incident_id, response.run_id) == (env.incident_id, snapshot.run_id)
    assert ReasoningResponse.model_validate_json(response.model_dump_json()) == response


async def test_model_failure_before_reasoning_is_unavailable_but_after_is_reported(env):
    snapshot, context, incident = prepared(env)
    error = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "ConverseStream")
    runtime, specialists = runtimes([error])
    request = request_for(env, snapshot, context, incident, runtime, specialists)
    with Guard():
        response = await reason(json.loads(request.model_dump_json()), runtime, specialists)
    assert response.status == "FAILED" and response.failure.code == "MODEL_UNAVAILABLE" and response.failure.retryable
    runtime, specialists = runtimes([delegation("diagnostic"), error])
    request = request_for(env, snapshot, context, incident, runtime, specialists)
    with Guard():
        response = await reason(json.loads(request.model_dump_json()), runtime, specialists)
    assert response.status == "COMPLETED"
    result = SupervisorResult.model_validate(response.result)
    assert result.termination_reason == "MODEL_FAILED" and result.disposition == "ESCALATED"
    assert len(result.delegations) == 1 and result.delegations[0].status == "SUCCEEDED"


async def test_disabled_live_runtime_is_reported_as_unavailable_without_fallback(env, monkeypatch):
    snapshot, context, incident = prepared(env)
    runtime = StrandsRuntime(settings())  # no injected model, live disabled
    request = request_for(env, snapshot, context, incident, runtime)
    from unittest.mock import Mock
    forbidden = Mock(side_effect=AssertionError("no AWS session allowed"))
    monkeypatch.setattr("boto3.Session", forbidden)
    with Guard():
        response = await reason(json.loads(request.model_dump_json()), runtime)
    assert response.status == "FAILED" and response.failure.code == "MODEL_UNAVAILABLE"
    assert response.failure.retryable is False
    forbidden.assert_not_called()


async def test_handler_result_cannot_become_authority_by_itself(env, monkeypatch):
    snapshot, context, incident = prepared(env)
    runtime, specialists = runtimes(workflow(context, disposition="ADVISORY_CONCLUSION"), SpecialistsModel(supported=True))
    request = request_for(env, snapshot, context, incident, runtime, specialists)
    before = protected_state(env.repo, env.incident_id)
    incident_before = env.repo.fetch_incident(env.incident_id)
    response = await reason(json.loads(request.model_dump_json()), runtime, specialists)
    assert response.status == "COMPLETED"
    assert SupervisorResult.model_validate(response.result).disposition == "ADVISORY_CONCLUSION"
    assert protected_state(env.repo, env.incident_id) == before
    assert env.repo.fetch_incident(env.incident_id) == incident_before
    assert not any(isinstance(item, (m.Diagnosis, m.SupervisorReport, m.PromotionRecord))
                   for item in env.repo.list_artifacts(env.incident_id))
