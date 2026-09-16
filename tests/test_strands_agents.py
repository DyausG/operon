"""Exercise the real Strands loop; only the model/provider boundary is scripted."""
import asyncio
from copy import deepcopy
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, ProfileNotFound
from pydantic import ValidationError
from strands import Agent
from strands.models import Model

from core import db
from core.agents.contracts import (
    CriticAssessment, DiagnosticAssessment, DiagnosticContext, EngineeringAssessment,
    MaintenancePlanAssessment, OperationsAssessment,
)
from core.agents.diagnostic import DIAGNOSTIC_PROMPT, DiagnosticInvocationError, assess_diagnosis
from core.agents.runtime import RuntimeConfigurationError, RuntimeSettings, StrandsRuntime
from core.agents.tools import DIAGNOSTIC_TOOL_NAMES, MAX_EVIDENCE_TOOL_CALLS, diagnostic_tools
from core.reliability import models as m
from core.reliability.assessments import prepare_diagnostic_context, validate_diagnostic_assessment
from core.reliability.evidence import EvidenceService
from core.reliability.repository import ARTIFACT_TYPES, IncidentRepository, InvalidReference


class ScriptedModel(Model):
    """Native Model implementation yielding recorded tool-use stream events."""
    def __init__(self, turns=()):
        self.turns = iter(turns)
        self.calls = []
        self.config = {"model_id": "offline-script", "context_window_limit": 100000}

    def get_config(self):
        return self.config

    def update_config(self, **kwargs):
        self.config.update(kwargs)

    async def structured_output(self, *args, **kwargs):
        raise AssertionError("deprecated structured_output path must not be used")
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls.append(deepcopy(dict(messages=messages, tools=tool_specs)))
        turn = next(self.turns, None)
        assert turn is not None, "unexpected extra model call"
        if isinstance(turn, Exception):
            raise turn
        if callable(turn):
            turn = turn(messages)
        yield {"messageStart": {"role": "assistant"}}
        for index, (name, payload) in enumerate(turn):
            yield {"contentBlockStart": {"contentBlockIndex": index, "start": {
                "toolUse": {"toolUseId": f"call-{len(self.calls)}-{index}", "name": name}}}}
            yield {"contentBlockDelta": {"contentBlockIndex": index, "delta": {
                "toolUse": {"input": json.dumps(payload)}}}}
            yield {"contentBlockStop": {"contentBlockIndex": index}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
                            "metrics": {"latencyMs": 1}}}


def settings(**kwargs):
    return RuntimeSettings(model_id="explicit-account-model", aws_region="us-east-1", **kwargs)


def report(incident_id, evidence_ids=()):
    return dict(incident_id=incident_id, evidence_reviewed=list(evidence_ids),
                competing_hypotheses=[dict(key="inspection-needed", mechanism="Cause remains unresolved",
                    supporting_evidence_ids=list(evidence_ids), confidence=0.2,
                    falsification_tests=["Collect discriminating inspection evidence"])],
                recommended_hypothesis=None, confidence=0.2,
                missing_evidence_requests=[dict(capability="inspection", question="Inspect the suspected component")],
                reasoning_summary="Available observations do not confirm a cause.")


@pytest.fixture
def scoped(seeded_db):
    repo = IncidentRepository()
    incident = repo.create_incident(("AC-COMP-01",), admission_key="strands-smoke")
    service = EvidenceService(repo)
    collection = service.request_and_collect(
        incident.id, requested_by="diagnostic", equipment_ids=incident.equipment_ids,
        question="Read asset context", capability="get_asset_context", required_for="diagnosis",
    )
    context = prepare_diagnostic_context(repo, incident.id, asset_id="AC-COMP-01", run_id="test-run",
                                         evidence_ids=(collection.evidence.id,))
    return repo, service, context


def protected_state(repo, incident_id):
    with db.get_conn() as conn:
        tables = ("work_order", "maintenance_event", "work_package", "part_reservation", "labor_booking",
                  "notification", "alert", "part", "technician")
        rows = {name: [tuple(row) for row in conn.execute(f"SELECT * FROM {name}")] for name in tables}
    return (rows, repo.fetch_incident(incident_id).phase,
            [item for item in repo.list_artifacts(incident_id)
             if not isinstance(item, (m.Evidence, m.EvidenceRequest))],
            repo.list_approval_decisions(incident_id), repo.list_execution_receipts(incident_id))


def test_dependency_and_lazy_import():
    assert version("strands-agents") == "1.54.0"
    # Fresh interpreter blocks even import-time calls, before any Operon import.
    code = '''
import socket
def blocked(*args, **kwargs):
    raise AssertionError("external/model activity forbidden during import")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.getaddrinfo = blocked
import boto3
boto3.Session.__init__ = blocked
boto3.client = blocked
import strands
strands.Agent.__init__ = blocked
strands.models.BedrockModel.__init__ = blocked
import core.agents
import core.agents.runtime
import core.agents.contracts
import core.agents.tools
import core.agents.diagnostic
import core.agents.engineering
import core.agents.operations
import core.agents.critic
import core.agents.planner
import core.agents.invocation
import core.agents.supervisor
import core.reliability.assessments
import core.reliability.orchestration
import core.reasoning
import core.reasoning.protocol
import core.reasoning.identity
import core.reasoning.packet
import core.reasoning.handler
import core.reasoning.trust
import core.reasoning.backend
import core.reasoning.agentcore
import agentcore_app.main
import core.agent
import server.main
'''
    result = subprocess.run([sys.executable, "-c", code], timeout=30, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_runtime_injection_and_disabled_live(scoped, monkeypatch):
    _, service, context = scoped
    forbidden = Mock(side_effect=AssertionError("no AWS session allowed"))
    monkeypatch.setattr("boto3.Session", forbidden)
    model = ScriptedModel()
    runtime = StrandsRuntime(settings(), model=model)
    kwargs = dict(name="test", system_prompt=DIAGNOSTIC_PROMPT, output_model=DiagnosticAssessment,
                  tools=diagnostic_tools(service, context, set()))
    first, second = runtime.create_agent(**kwargs), runtime.create_agent(**kwargs)
    assert isinstance(first, Agent) and first.model is model
    assert first is not second and first.messages is not second.messages
    assert set(first.tool_names) == DIAGNOSTIC_TOOL_NAMES
    assert not model.calls
    with pytest.raises(RuntimeConfigurationError, match="disabled"):
        StrandsRuntime(settings()).create_agent(**kwargs)
    forbidden.assert_not_called()


def test_explicit_bedrock_configuration(monkeypatch):
    session = Mock()
    factory = Mock(return_value=session)
    bedrock = Mock()
    monkeypatch.setattr("core.providers.bedrock._default_session_factory", factory)
    monkeypatch.setattr("strands.models.BedrockModel", bedrock)
    runtime = StrandsRuntime(settings(live_enabled=True))
    assert runtime.settings.provider == "bedrock" and runtime.provider.kind == "bedrock"
    runtime._live_model()
    factory.assert_called_once_with(region_name="us-east-1", profile_name=None)
    kwargs = bedrock.call_args.kwargs
    assert kwargs["boto_session"] is session and "region_name" not in kwargs
    assert kwargs["model_id"] == "explicit-account-model" and kwargs["max_tokens"] == 2500
    assert kwargs["boto_client_config"].retries == {"mode": "standard", "total_max_attempts": 2}
    session.get_credentials.return_value = None
    with pytest.raises(RuntimeConfigurationError, match="credentials unavailable") as info:
        runtime._live_model()
    assert info.value.code == "provider_not_configured"
    factory.side_effect = ProfileNotFound(profile="missing")
    with pytest.raises(RuntimeConfigurationError, match="Cannot configure bedrock"):
        runtime._live_model()


def test_runtime_settings_cover_every_provider():
    from core.agents.runtime import provider_for_settings
    with pytest.raises(ValidationError, match="aws_region"):
        RuntimeSettings(model_id="m")
    gemini = RuntimeSettings(provider="gemini", model_id="gemini-2.5-flash")
    assert gemini.identity_locator() == "generativelanguage.googleapis.com" and gemini.aws_region is None
    ollama = RuntimeSettings(provider="ollama", model_id="gemma3", endpoint="http://box:11434/")
    assert ollama.identity_locator() == "http://box:11434"
    assert provider_for_settings(gemini).kind == "gemini" and provider_for_settings(ollama).model_id == "gemma3"
    assert StrandsRuntime(gemini).model_implementation() == "strands.models.gemini"
    with pytest.raises(RuntimeConfigurationError, match="disabled"):
        StrandsRuntime(ollama)._live_model()
    with pytest.raises(TypeError):
        StrandsRuntime(ollama, provider=object())


@pytest.mark.parametrize("change", [
    {"confidence": 1.1}, {"confidence": float("nan")}, {"incident_id": " "},
    {"recommended_hypothesis": "invented"}, {"execute": "dispatch"},
    {"reasoning_summary": ""}, {"competing_hypotheses": [{}]},
])
def test_malformed_diagnostic_contract_rejected(change):
    with pytest.raises(ValidationError):
        DiagnosticAssessment.model_validate(report("incident") | change)


def test_contracts_are_advisory_and_reference_ids():
    result = DiagnosticAssessment.model_validate(report("incident", ("evidence",)))
    assert not isinstance(result, m.Artifact)
    assert "DiagnosticAssessment" not in ARTIFACT_TYPES
    for contract in (EngineeringAssessment, OperationsAssessment, CriticAssessment, MaintenancePlanAssessment):
        assert not issubclass(contract, m.Artifact)
        assert contract.model_config["extra"] == "forbid"
        assert "incident_id" in contract.model_json_schema()["properties"]
        with pytest.raises(ValidationError):
            contract.model_validate({"incident_id": "incident"})
    payload = report("incident", ("evidence",))
    payload["competing_hypotheses"][0]["supporting_evidence_ids"] = ["not-reviewed"]
    with pytest.raises(ValidationError, match="citations"):
        DiagnosticAssessment.model_validate(payload)


async def test_real_loop_structured_advice_has_no_authoritative_effect(scoped):
    repo, service, context = scoped
    before = protected_state(repo, context.incident_id)
    incident_before = repo.fetch_incident(context.incident_id)
    model = ScriptedModel([[('DiagnosticAssessment', report(context.incident_id, (context.evidence[0].id,)))]])
    result = await assess_diagnosis(StrandsRuntime(settings(), model=model), service, context)
    assert isinstance(result, DiagnosticAssessment)
    assert protected_state(repo, context.incident_id) == before
    assert repo.fetch_incident(context.incident_id) == incident_before
    with pytest.raises(ValueError, match="unsupported artifact type"):
        repo.add_artifact(result, expected_revision=incident_before.revision)
    assert repo.fetch_incident(context.incident_id) == incident_before
    names = {spec["name"] for spec in model.calls[0]["tools"]}
    assert names == DIAGNOSTIC_TOOL_NAMES | {"DiagnosticAssessment"}
    assert json.loads(model.calls[0]["messages"][0]["content"][0]["text"])["run_id"] == "test-run"


async def test_all_read_tools_delegate_preserve_provenance_and_do_not_write(scoped, monkeypatch):
    repo, service, context = scoped
    reads = sorted(DIAGNOSTIC_TOOL_NAMES - {"request_evidence"})
    observed = []
    original = service.capabilities.collect
    def collect(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(result.model_dump(mode="json"))
        return result
    monkeypatch.setattr(service.capabilities, "collect", collect)
    incident_before = repo.fetch_incident(context.incident_id)
    def final(messages):
        results = [block["toolResult"] for msg in messages for block in msg["content"] if "toolResult" in block]
        assert len(results) == 5
        for item, expected in zip(results, observed):
            assert item["status"] == "success"
            assert item["content"][0]["json"] == expected
        return [("DiagnosticAssessment", report(context.incident_id))]
    model = ScriptedModel([[(name, {}) for name in reads], final])
    await assess_diagnosis(StrandsRuntime(settings(), model=model), service, context)
    assert len(observed) == 5
    assert repo.fetch_incident(context.incident_id) == incident_before


async def test_evidence_request_uses_application_service_and_only_appends_evidence(scoped, monkeypatch):
    repo, service, context = scoped
    before = protected_state(repo, context.incident_id)
    original = service.request_and_collect
    spy = Mock(wraps=original)
    monkeypatch.setattr(service, "request_and_collect", spy)
    def final(messages):
        block = messages[-1]["content"][0]["toolResult"]
        assert block["status"] == "success", block
        collection = block["content"][0]["json"]
        persisted = repo.get_artifact(context.incident_id, collection["evidence"]["id"])
        assert collection["evidence"] == persisted.model_dump(mode="json")
        assert collection["result"]["provenance"] == persisted.payload["provenance"]
        return [("DiagnosticAssessment", report(context.incident_id, (persisted.id,)))]
    model = ScriptedModel([[('request_evidence', {"query": {
        "capability": "get_maintenance_history", "question": "Review persisted maintenance", "parameters": {"limit": 1},
    }})], final])
    result = await assess_diagnosis(StrandsRuntime(settings(), model=model), service, context)
    assert result.evidence_reviewed
    spy.assert_called_once()
    assert spy.call_args.kwargs["requested_by"] == "diagnostic"
    assert spy.call_args.kwargs["equipment_ids"] == (context.asset_id,)
    assert protected_state(repo, context.incident_id) == before
    assert not any(isinstance(item, m.Diagnosis) for item in repo.list_artifacts(context.incident_id))


@pytest.mark.parametrize("name,args,error", [
    ("request_evidence", {"query": {"capability": "arbitrary_sql", "question": "query"}}, "unsupported evidence capability"),
    ("get_telemetry_window", {"sample_limit": 501}, "500"),
    ("get_maintenance_history", {"limit": 0}, "1"),
    ("request_evidence", {"query": {"capability": "get_asset_context", "question": "read", "incident_id": "foreign"}}, "Extra inputs"),
    ("commit_actions", {"incident_id": "foreign"}, "Unknown tool"),
])
async def test_bad_or_dangerous_tool_calls_fail_explicitly(scoped, name, args, error):
    repo, service, context = scoped
    before = protected_state(repo, context.incident_id)
    incident_before = repo.fetch_incident(context.incident_id)
    def final(messages):
        block = messages[-1]["content"][0]["toolResult"]
        assert block["status"] == "error"
        assert error.lower() in json.dumps(block).lower()
        return [("DiagnosticAssessment", report(context.incident_id))]
    await assess_diagnosis(StrandsRuntime(settings(), model=ScriptedModel([[(name, args)], final])), service, context)
    assert protected_state(repo, context.incident_id) == before
    assert repo.fetch_incident(context.incident_id) == incident_before


async def test_bad_structured_output_fails_at_native_turn_limit(scoped):
    repo, service, context = scoped
    before = protected_state(repo, context.incident_id)
    model = ScriptedModel([[('DiagnosticAssessment', {"incident_id": context.incident_id})]])
    with pytest.raises(DiagnosticInvocationError, match="limit_turns"):
        await assess_diagnosis(StrandsRuntime(settings(max_turns=1), model=model), service, context)
    assert len(model.calls) == 1
    assert protected_state(repo, context.incident_id) == before


@pytest.mark.parametrize("payload", [report("foreign"), report("incident", ("invented",))])
def test_application_validator_rejects_foreign_or_unknown_references(payload):
    with pytest.raises(InvalidReference):
        validate_diagnostic_assessment(DiagnosticAssessment.model_validate(payload),
                                       incident_id="incident", available_evidence_ids=set())


async def test_bedrock_failure_is_explicit_without_fallback(scoped):
    _, service, context = scoped
    error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "not enabled"}}, "ConverseStream")
    with pytest.raises(DiagnosticInvocationError, match="No fallback"):
        await assess_diagnosis(StrandsRuntime(settings(), model=ScriptedModel([error])), service, context)


async def test_deadline_cancels_model_call(scoped):
    _, service, context = scoped
    class WaitingModel(ScriptedModel):
        cancelled = False
        async def stream(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True
            yield  # pragma: no cover
    model = WaitingModel()
    with pytest.raises(asyncio.TimeoutError):
        await assess_diagnosis(StrandsRuntime(settings(invocation_timeout_seconds=0.01), model=model), service, context)
    assert model.cancelled


def test_context_bounds_scope_and_application_reads(scoped):
    repo, _, context = scoped
    with pytest.raises(InvalidReference, match="outside incident"):
        prepare_diagnostic_context(repo, context.incident_id, asset_id="HYD-PUMP-03", run_id="r", evidence_ids=())
    with pytest.raises(ValidationError, match="selected asset"):
        DiagnosticContext.model_validate(context.model_dump() | {"asset_id": "HYD-PUMP-03"})
    payload = context.model_dump()
    payload["evidence"][0]["payload"] = {"oversized": "x" * 64_000}
    with pytest.raises(ValidationError, match="64000"):
        DiagnosticContext.model_validate(payload)


def test_no_repository_or_executor_imports_in_agent_layer():
    # An architectural regression guard, complementing real invocation state checks.
    root = Path(__file__).resolve().parents[1] / "core" / "agents"
    for path in root.glob("*.py"):
        source = path.read_text()
        assert "import sqlite3" not in source
        assert "from core.reliability.repository" not in source
        assert "GovernedExecutor" not in source
        assert "from core import services" not in source


async def test_oversized_tool_result_fails_without_truncating_provenance(scoped, monkeypatch):
    repo, service, context = scoped
    oversized = service.capabilities.get_asset_context(context.asset_id).model_copy(
        update={"asset_name": "x" * 48_000})
    monkeypatch.setattr(service.capabilities, "collect", Mock(return_value=oversized))
    def final(messages):
        result = messages[-1]["content"][0]["toolResult"]
        assert result["status"] == "error"
        assert "48000 bytes" in json.dumps(result)
        assert "x" * 100 not in json.dumps(result)
        return [("DiagnosticAssessment", report(context.incident_id))]
    model = ScriptedModel([[('get_asset_context', {})], final])
    before = repo.fetch_incident(context.incident_id)
    await assess_diagnosis(StrandsRuntime(settings(), model=model), service, context)
    assert repo.fetch_incident(context.incident_id) == before


async def test_tool_budget_bounds_multiple_calls_in_one_turn(scoped, monkeypatch):
    _, service, context = scoped
    spy = Mock(wraps=service.capabilities.collect)
    monkeypatch.setattr(service.capabilities, "collect", spy)
    def final(messages):
        results = [block["toolResult"] for block in messages[-1]["content"]]
        assert all(item["status"] == "success" for item in results[:-1])
        assert results[-1]["status"] == "error"
        assert "budget exhausted" in json.dumps(results[-1])
        return [("DiagnosticAssessment", report(context.incident_id))]
    model = ScriptedModel([[('get_asset_context', {})] * (MAX_EVIDENCE_TOOL_CALLS + 1), final])
    await assess_diagnosis(StrandsRuntime(settings(), model=model), service, context)
    assert spy.call_count == MAX_EVIDENCE_TOOL_CALLS


async def test_mismatched_invocation_scope_cannot_use_tools(scoped):
    _, service, context = scoped
    def final(messages):
        result = messages[-1]["content"][0]["toolResult"]
        assert result["status"] == "error" and "trusted incident/run" in json.dumps(result)
        return [("DiagnosticAssessment", report(context.incident_id))]
    model = ScriptedModel([[('get_asset_context', {})], final])
    runtime = StrandsRuntime(settings(), model=model)
    agent = runtime.create_agent(name="scope-test", system_prompt=DIAGNOSTIC_PROMPT,
                                 output_model=DiagnosticAssessment,
                                 tools=diagnostic_tools(service, context, set()))
    await agent.invoke_async("test", invocation_state={"incident_id": "foreign"},
                             limits=runtime.settings.invocation_limits())


@pytest.mark.parametrize("limits,stop", [
    ({"max_total_tokens": 1}, "limit_total_tokens"),
    ({"max_output_tokens": 1}, "limit_output_tokens"),
])
async def test_native_token_limits_reject_incomplete_reports(scoped, limits, stop):
    _, service, context = scoped
    model = ScriptedModel([[('get_asset_context', {})]])
    with pytest.raises(DiagnosticInvocationError, match=stop):
        await assess_diagnosis(StrandsRuntime(settings(**limits), model=model), service, context)
    assert len(model.calls) == 1


def test_future_specialist_contracts_accept_advice_only():
    common = dict(incident_id="incident", evidence_reviewed=["evidence"], reasoning_summary="Uncertainty remains")
    EngineeringAssessment(**common, diagnosis_id="diagnosis", constraints_considered=[],
                          intervention_feasibility="UNKNOWN", blockers=[], safety_concerns=[],
                          recommended_intervention_elements=[])
    OperationsAssessment(**common, intervention_id="intervention", resource_feasibility="UNKNOWN",
                         inventory_observations=[], workforce_observations=[], scheduling_observations=[],
                         blockers=[], operational_recommendations=[])
    CriticAssessment(**common, subject_id="diagnosis", subject_kind="diagnosis", evidence_gaps=[],
                     contradictions=[], unsupported_claims=[], recommendation="NEEDS_EVIDENCE",
                     requested_additional_evidence=[])
    plan = MaintenancePlanAssessment(**common, validated_input_ids=["diagnosis", "verdict"],
        proposed_steps=[dict(description="Propose inspection", equipment_ids=["asset"], evidence_ids=["evidence"],
                             preconditions=["Application approval"], verification_criteria=["Record inspection findings"])],
        estimated_exposure=None, exposure_currency=None, exposure_assumptions=[], reversible=None,
        safety_relevant=None, external_commitment=None, approval_considerations=["Requires policy review"])
    with pytest.raises(ValidationError):
        MaintenancePlanAssessment.model_validate(plan.model_dump() | {"estimated_exposure": -1})
