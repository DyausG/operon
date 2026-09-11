"""Offline contract tests for the application-side AgentCore backend."""
from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import Mock

from botocore.exceptions import ClientError, ReadTimeoutError
import pytest

from core.agents.contracts import SpecialistContext, SupervisorBounds, SupervisorResult
from core.reliability import models as m
from core.reasoning.agentcore import AgentCoreBackend, AgentCoreSettings, MAX_RESPONSE_BYTES
from core.reasoning.errors import ReasoningBackendUnavailable
from core.reasoning.protocol import ReasoningRequest, runtime_session_id
from tests.test_promotion import ASSET, Environment, result_payload, revision, state


@pytest.fixture
def env(seeded_db):
    return Environment()


def settings(**changes):
    values = dict(
        runtime_arn="test-runtime-arn",
        qualifier="DEFAULT", region="us-east-1",
        supervisor_model_id="test-supervisor-profile",
        specialist_model_id="test-specialist-profile",
    )
    return AgentCoreSettings(**(values | changes))


class FakeClient:
    def __init__(self, response=None, error=None, *, stop_error=None):
        self.response, self.error, self.stop_error = response, error, stop_error
        self.invoke_calls, self.stop_calls = [], []

    def invoke_agent_runtime(self, **kwargs):
        self.invoke_calls.append(kwargs)
        if self.error:
            raise self.error
        response = self.response(kwargs) if callable(self.response) else self.response
        return response

    def stop_runtime_session(self, **kwargs):
        self.stop_calls.append(kwargs)
        if self.stop_error:
            raise self.stop_error
        return {"statusCode": 200, "runtimeSessionId": kwargs["runtimeSessionId"]}


class ReadableBody:
    def __init__(self, payload: bytes, *, error: Exception | None = None):
        self.payload, self.error = payload, error
        self.offset = 0
        self.closed = False

    def read(self, size: int) -> bytes:
        if self.error is not None:
            raise self.error
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


def response_for(env, snapshot, backend, *, mutate=None):
    def response(kwargs):
        request = ReasoningRequest.model_validate_json(kwargs["payload"])
        body = dict(
            protocol_version="operon-reasoning-1", incident_id=request.incident_id,
            run_id=request.run_id, snapshot_id=request.snapshot_id,
            input_revision=request.input_revision, status="COMPLETED", failure=None,
            runtime_identity=backend.expected_identity().model_dump(mode="json"),
            result=result_payload(env, snapshot), telemetry={"duration_ms": 7},
        )
        if mutate:
            mutate(body)
        raw = json.dumps(body, separators=(",", ":")).encode()
        split = max(1, len(raw) // 2)
        return {"statusCode": 200, "contentType": "application/json",
                "runtimeSessionId": request.runtime_session_id,
                "response": [raw[:split], raw[split:]]}
    return response


def start(env, backend):
    snapshot = env.service.start_run(
        env.incident_id, asset_id=ASSET, stage="DIAGNOSIS",
        expected_revision=revision(env), evidence_ids=env.evidence_ids(), runtime=backend)
    return snapshot, SpecialistContext.model_validate(snapshot.context_payload)


async def test_agentcore_backend_serializes_frozen_request_invokes_fake_and_trusts_response(env):
    fake = FakeClient()
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    fake.response = response_for(env, snapshot, backend)
    before = state(env)

    result = await backend.supervise(
        env.evidence_service, context,
        bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)

    assert isinstance(result, SupervisorResult) and result.disposition == "ADVISORY_CONCLUSION"
    assert state(env) == before  # validation is advisory and writes nothing
    assert len(fake.invoke_calls) == len(fake.stop_calls) == 1
    invocation = fake.invoke_calls[0]
    request = ReasoningRequest.model_validate_json(invocation["payload"])
    assert request.context.model_dump(mode="json") == snapshot.context_payload
    assert request.bounds.model_dump(mode="json") == snapshot.bounds
    assert request.expected_identity == backend.expected_identity()
    assert request.runtime_session_id == runtime_session_id(snapshot.run_id)
    assert set(invocation) == {
        "agentRuntimeArn", "runtimeSessionId", "qualifier", "payload", "baggage", "contentType", "accept"}
    assert invocation["agentRuntimeArn"] == backend.settings.runtime_arn
    assert invocation["runtimeSessionId"] == request.runtime_session_id
    assert invocation["qualifier"] == "DEFAULT"
    assert invocation["contentType"] == invocation["accept"] == "application/json"
    assert f"operon.incident_id={env.incident_id}" in invocation["baggage"]
    assert f"operon.run_id={snapshot.run_id}" in invocation["baggage"]
    assert fake.stop_calls[0] == {
        "agentRuntimeArn": backend.settings.runtime_arn,
        "runtimeSessionId": request.runtime_session_id,
        "qualifier": "DEFAULT",
    }


async def test_successful_readable_response_is_closed_after_validation(env):
    fake = FakeClient()
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    response = response_for(env, snapshot, backend)
    bodies = []

    def readable_response(kwargs):
        result = response(kwargs)
        body = ReadableBody(b"".join(result["response"]))
        bodies.append(body)
        return result | {"response": body}

    fake.response = readable_response
    result = await backend.supervise(
        env.evidence_service, context,
        bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert result.disposition == "ADVISORY_CONCLUSION"
    assert len(bodies) == 1 and bodies[0].closed is True


async def test_client_factory_is_lazy_and_configures_one_attempt_and_bounded_timeout(env):
    created = []
    fake = FakeClient()

    def factory(**kwargs):
        created.append(kwargs)
        return fake

    backend = AgentCoreBackend(settings(), client_factory=factory)
    snapshot, context = start(env, backend)
    assert created == []
    assert backend._client(SupervisorBounds.model_validate(snapshot.bounds)) is fake
    assert len(created) == 1 and created[0]["region_name"] == "us-east-1"
    client_config = created[0]["config"]
    assert client_config.connect_timeout == 5
    assert client_config.read_timeout == snapshot.bounds["timeout_seconds"] + 60
    assert client_config.retries == {"mode": "standard", "total_max_attempts": 1}


@pytest.mark.parametrize(("mutation", "code"), [
    (lambda body: body.update(run_id="wrong-run"), "CORRELATION"),
    (lambda body: body.update(incident_id="foreign-incident"), "CORRELATION"),
    (lambda body: body["runtime_identity"].update(prompts="drifted"), "VERSION_MISMATCH"),
])
async def test_untrusted_correlation_identity_and_cross_incident_responses_are_rejected(env, mutation, code):
    fake = FakeClient()
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    fake.response = response_for(env, snapshot, backend, mutate=mutation)
    before = state(env)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(env.evidence_service, context,
                                bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert failure.value.code == code and failure.value.retryable is False
    assert state(env) == before


async def test_agentcore_service_session_echo_mismatch_is_rejected_before_envelope_trust(env):
    fake = FakeClient()
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    response = response_for(env, snapshot, backend)
    fake.response = lambda kwargs: response(kwargs) | {"runtimeSessionId": "wrong-session"}
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(env.evidence_service, context,
                                bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert failure.value.code == "CORRELATION" and failure.value.retryable is False


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"protocol_version":"operon-reasoning-1"}'])
async def test_malformed_remote_responses_fail_closed(env, body):
    fake = FakeClient({"statusCode": 200, "contentType": "application/json", "response": [body]})
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(env.evidence_service, context,
                                bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert failure.value.code == "PROTOCOL" and failure.value.retryable is False
    assert not [item for item in env.repo.list_artifacts(env.incident_id)
                if isinstance(item, m.SupervisorReport)]


@pytest.mark.parametrize("content_type", [None, 7, "text/plain"])
async def test_missing_non_string_and_incorrect_content_types_fail_closed(env, content_type):
    body = ReadableBody(b"{}")
    response = {"statusCode": 200, "response": body}
    if content_type is not None:
        response["contentType"] = content_type
    backend = AgentCoreBackend(settings(), client=FakeClient(response))
    snapshot, context = start(env, backend)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(env.evidence_service, context,
                                bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert failure.value.code == "PROTOCOL" and body.closed is True


@pytest.mark.parametrize("stream_kind", ["readable", "iterable"])
@pytest.mark.parametrize("size", [MAX_RESPONSE_BYTES, MAX_RESPONSE_BYTES + 1])
async def test_response_size_boundary_is_incremental_closed_and_fail_closed(env, stream_kind, size):
    payload = b" " * size
    body = ReadableBody(payload) if stream_kind == "readable" else iter(
        (payload[offset:offset + 64_000] for offset in range(0, len(payload), 64_000)))
    fake = FakeClient({"statusCode": 200, "contentType": "application/json", "response": body})
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(env.evidence_service, context,
                                bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert failure.value.code == "PROTOCOL"
    if size == MAX_RESPONSE_BYTES:
        assert "malformed JSON" in str(failure.value)
    else:
        assert "exceeds" in str(failure.value)
    if stream_kind == "readable":
        assert body.closed is True


async def test_read_failure_closes_body_and_stops_session(env):
    body = ReadableBody(
        b"", error=ReadTimeoutError(endpoint_url="https://agentcore.invalid", error="timeout"))
    fake = FakeClient({"statusCode": 200, "contentType": "application/json", "response": body})
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(env.evidence_service, context,
                                bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert failure.value.code == "TIMEOUT"
    assert body.closed is True and len(fake.stop_calls) == 1


async def test_factory_client_cancellation_rejects_late_result_and_eventually_stops_session(
        env, monkeypatch):
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    trusted = Mock(side_effect=AssertionError("a late cancelled response must never reach trust"))
    monkeypatch.setattr("core.reasoning.agentcore.validate_response", trusted)

    class BlockingClient(FakeClient):
        def invoke_agent_runtime(self, **kwargs):
            self.invoke_calls.append(kwargs)
            entered.set()
            release.wait(timeout=2)
            return response_for(env, snapshot, backend)(kwargs)

        def stop_runtime_session(self, **kwargs):
            result = super().stop_runtime_session(**kwargs)
            stopped.set()
            return result

    fake = BlockingClient()
    backend = AgentCoreBackend(settings(), client_factory=lambda **_: fake)
    snapshot, context = start(env, backend)
    task = asyncio.create_task(backend.supervise(
        env.evidence_service, context,
        bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot))
    while not entered.is_set():
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    for _ in range(1_000):
        if stopped.is_set():
            break
        await asyncio.sleep(0.001)
    assert stopped.is_set() and len(fake.stop_calls) == 1
    trusted.assert_not_called()


@pytest.mark.parametrize(("error", "code", "retryable"), [
    (ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "InvokeAgentRuntime"),
     "AccessDeniedException", False),
    (ClientError({"Error": {"Code": "RuntimeClientError", "Message": "runtime failed"}}, "InvokeAgentRuntime"),
     "RuntimeClientError", True),
    (ReadTimeoutError(endpoint_url="https://agentcore.invalid", error="timeout"), "TIMEOUT", True),
])
async def test_client_failures_are_mapped_without_fallback(env, error, code, retryable):
    backend = AgentCoreBackend(settings(), client=FakeClient(error=error))
    snapshot, context = start(env, backend)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(env.evidence_service, context,
                                bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert failure.value.code == code and failure.value.retryable is retryable


async def test_backend_failure_persists_only_conservative_audit_report(env):
    error = ClientError({"Error": {"Code": "RuntimeClientError", "Message": "runtime failed"}},
                        "InvokeAgentRuntime")
    backend = AgentCoreBackend(settings(), client=FakeClient(error=error))
    with pytest.raises(ReasoningBackendUnavailable, match="RuntimeClientError"):
        await env.service.run_supervisor(
            env.incident_id, service=env.evidence_service, runtime=backend, asset_id=ASSET,
            stage="DIAGNOSIS", expected_revision=revision(env), evidence_ids=env.evidence_ids())
    reports = [item for item in env.repo.list_artifacts(env.incident_id)
               if isinstance(item, m.SupervisorReport)]
    assert len(reports) == 1 and reports[0].completion == "MODEL_FAILED"
    assert reports[0].result_payload["disposition"] == "ESCALATED"
    assert "RuntimeClientError" in reports[0].result_payload["blockers"][0]
    incident = env.repo.fetch_incident(env.incident_id)
    assert incident.phase == m.IncidentPhase.INVESTIGATING and incident.current_diagnosis_id is None


async def test_stop_session_failure_never_discards_an_already_validated_response(env):
    fake = FakeClient(stop_error=RuntimeError("cleanup failed"))
    backend = AgentCoreBackend(settings(), client=fake)
    snapshot, context = start(env, backend)
    fake.response = response_for(env, snapshot, backend)
    result = await backend.supervise(env.evidence_service, context,
                                     bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
    assert result.disposition == "ADVISORY_CONCLUSION" and len(fake.stop_calls) == 1


def test_agentcore_environment_requires_runtime_and_both_verified_model_ids(monkeypatch):
    for name in ("OPERON_AGENTCORE_RUNTIME_ARN", "OPERON_BEDROCK_SUPERVISOR_MODEL_ID",
                 "OPERON_BEDROCK_SPECIALIST_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="OPERON_AGENTCORE_RUNTIME_ARN"):
        AgentCoreSettings.from_environment()
    monkeypatch.setenv("OPERON_AGENTCORE_RUNTIME_ARN", "test-runtime-arn")
    monkeypatch.setenv("OPERON_BEDROCK_SUPERVISOR_MODEL_ID", "supervisor")
    monkeypatch.setenv("OPERON_BEDROCK_SPECIALIST_MODEL_ID", "specialists")
    resolved = AgentCoreSettings.from_environment()
    assert resolved.supervisor_model_id == "supervisor" and resolved.specialist_model_id == "specialists"
