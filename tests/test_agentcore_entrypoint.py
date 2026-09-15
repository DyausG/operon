"""Offline contract tests for the advisory-only AgentCore runtime entrypoint."""
from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from unittest.mock import Mock

from bedrock_agentcore import BedrockAgentCoreApp
import pytest

import agentcore_app.main as entrypoint
from core.agents.contracts import SpecialistContext, SupervisorBounds, SupervisorResult
from core.agents.runtime import StrandsRuntime
from core.reasoning.handler import handler_identity
from core.reasoning.packet import build_request
from core.reasoning.protocol import ReasoningResponse
from tests.test_promotion import Environment
from tests.test_strands_agents import ScriptedModel, protected_state, settings
from tests.test_supervisor import SpecialistsModel, workflow


@pytest.fixture
def env(seeded_db):
    return Environment()


def prepared(env):
    snapshot = env.start()
    context = SpecialistContext.model_validate(snapshot.context_payload)
    incident = env.repo.fetch_incident(env.incident_id)
    runtime = StrandsRuntime(settings(), model=ScriptedModel(workflow(context)))
    specialists = StrandsRuntime(settings(), model=SpecialistsModel())
    request = build_request(
        env.evidence_service, incident, context, SupervisorBounds.model_validate(snapshot.bounds),
        snapshot_id=snapshot.id, expected_identity=handler_identity(runtime, specialists))
    return snapshot, runtime, specialists, request


def test_entrypoint_is_registered_with_context_parameter_and_no_authority_objects():
    assert isinstance(entrypoint.app, BedrockAgentCoreApp)
    assert entrypoint.app.handlers["main"] is entrypoint.invoke
    assert tuple(inspect.signature(entrypoint.invoke).parameters) == ("payload", "context")
    source = inspect.getsource(entrypoint)
    for forbidden in ("IncidentRepository", "EvidenceService", "sqlite3", "PromotionService",
                      "LifecycleService", "GovernedExecutor"):
        assert forbidden not in source


async def test_entrypoint_returns_protocol_envelope_using_only_packet_reasoning(env, monkeypatch):
    snapshot, runtime, specialists, request = prepared(env)
    monkeypatch.setattr(entrypoint, "_runtime_factory", lambda: (runtime, specialists, None))
    forbidden = Mock(side_effect=AssertionError("runtime must never open the Operon store"))
    before = protected_state(env.repo, env.incident_id)
    with monkeypatch.context() as guard:
        guard.setattr("core.db.get_conn", forbidden)
        guard.setattr("sqlite3.connect", forbidden)
        payload = await entrypoint.invoke(
            json.loads(request.model_dump_json()), SimpleNamespace(session_id=request.runtime_session_id))

    response = ReasoningResponse.model_validate(payload)
    assert response.status == "COMPLETED" and response.runtime_identity == request.expected_identity
    result = SupervisorResult.model_validate(response.result)
    assert result.incident_id == env.incident_id and result.run_id == snapshot.run_id
    assert result.human_review_required is True
    assert protected_state(env.repo, env.incident_id) == before
    forbidden.assert_not_called()


async def test_entrypoint_rejects_runtime_session_mismatch_before_model_calls(env, monkeypatch):
    _, runtime, specialists, request = prepared(env)
    monkeypatch.setattr(entrypoint, "_runtime_factory", lambda: (runtime, specialists, None))
    payload = await entrypoint.invoke(
        json.loads(request.model_dump_json()), SimpleNamespace(session_id="wrong-session"))
    response = ReasoningResponse.model_validate(payload)
    assert response.status == "FAILED" and response.failure.code == "PACKET_INVALID"
    assert not runtime._model.calls and not specialists._model.calls

    payload = await entrypoint.invoke(json.loads(request.model_dump_json()), SimpleNamespace(session_id=None))
    response = ReasoningResponse.model_validate(payload)
    assert response.status == "FAILED" and response.failure.code == "PACKET_INVALID"
    assert not runtime._model.calls and not specialists._model.calls


def test_runtime_model_configuration_is_explicit_and_lazy(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("runtime construction must not create an AWS session"))
    monkeypatch.setattr("boto3.Session", forbidden)
    monkeypatch.setenv("OPERON_AWS_REGION", "us-west-2")
    monkeypatch.setenv("OPERON_BEDROCK_SUPERVISOR_MODEL_ID", "supervisor-profile")
    monkeypatch.setenv("OPERON_BEDROCK_SPECIALIST_MODEL_ID", "specialist-profile")
    runtime, specialists, build_id = entrypoint._build_runtimes()
    assert runtime.settings.live_enabled and specialists.settings.live_enabled
    assert runtime.settings.model_id == "supervisor-profile"
    assert specialists.settings.model_id == "specialist-profile"
    assert runtime.settings.aws_region == specialists.settings.aws_region == "us-west-2"
    assert build_id is None
    forbidden.assert_not_called()


async def test_malformed_packet_uses_shared_handler_and_never_constructs_an_agent(monkeypatch):
    runtime = StrandsRuntime(settings(), model=ScriptedModel())
    specialists = StrandsRuntime(settings(), model=ScriptedModel())
    monkeypatch.setattr(entrypoint, "_runtime_factory", lambda: (runtime, specialists, None))
    response = ReasoningResponse.model_validate(await entrypoint.invoke(
        {"protocol_version": "operon-reasoning-1", "database_path": "/tmp/forbidden.db"},
        SimpleNamespace(session_id=None)))
    assert response.status == "FAILED" and response.failure.code == "PACKET_INVALID"
    assert not runtime._model.calls and not specialists._model.calls
