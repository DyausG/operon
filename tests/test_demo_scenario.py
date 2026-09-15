"""Guided Demo Scenario: deterministic inputs, the real lifecycle, the configured reasoning backend.

Every test drives ``DemoEngine.start_guided_demo`` exactly as ``POST /api/demo/scenario``
does. Reasoning reaches the incident only through the ``ReasoningBackend`` seam; with no
provider the engine uses the labelled deterministic advisory, with a configured runtime
the scenario's runs genuinely invoke it and its output lands in durable artifacts.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from core import config, db, engine as engine_module
from core.agents.contracts import AdvisoryInput, SpecialistContext
from core.agents.runtime import RuntimeSettings, StrandsRuntime
from core.demo_scenario import SCENARIO_ID
from core.reasoning.backend import LocalStrandsBackend, ReasoningBackend
from core.providers.errors import ProviderError
from core.reliability import models as m
from core.reliability.models import IncidentPhase
from tests.test_promotion import MECHANISM, result_payload
from tests.test_strands_agents import ScriptedModel, settings
from tests.test_supervisor import decision, delegation

ASSET = "AC-COMP-01"
INTENT_KEYS = ("requirement_id", "intervention_id", "intervention_hash", "context_revision")


@pytest.fixture(autouse=True)
def fast_ticks(monkeypatch):
    monkeypatch.setattr(config, "TICK_SECONDS", 0.01)


def make_engine(runtime=None) -> engine_module.DemoEngine:
    engine = engine_module.DemoEngine(runtime=runtime)
    engine.demo_step_delay = 0.01
    return engine


async def wait_status(engine, status: str, timeout: float = 40) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        projection = engine._demo_projection()
        if projection.get("status") == status:
            return projection
        if projection.get("status") == "failed" and status != "failed":
            raise AssertionError(f"guided demo failed: {projection.get('error')}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"demo did not reach {status}: {engine._demo_projection()}")


def approval_intent(engine) -> dict:
    lifecycle = engine.snapshot()["alerts"][0]["lifecycle"]
    return {key: lifecycle[key] for key in INTENT_KEYS}


async def finish(engine):
    await engine.reset(restart=False)
    await engine.stop()


def artifacts_of(engine, cls):
    incident = engine.incidents[ASSET]
    return [item for item in engine.coordinator.repository.list_artifacts(incident.id) if isinstance(item, cls)]


class EngineSpecialists(ScriptedModel):
    """Only the provider boundary is scripted; every specialist SDK loop executes for real."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.packets = []

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        from core.reliability.orchestration import ROLE_CONTRACTS
        context = SpecialistContext.model_validate_json(messages[0]["content"][0]["text"])
        role = next(role for role, cls in ROLE_CONTRACTS.items() if cls.__name__ in {item["name"] for item in tool_specs})
        self.packets.append(context)
        repo = self.engine.coordinator.repository
        artifacts = repo.list_artifacts(context.incident_id)
        snapshot = next(a for a in artifacts if isinstance(a, m.SupervisorRunSnapshot) and a.run_id == context.run_id)
        history = [a.id for a in artifacts if isinstance(a, m.Evidence) and a.kind == "maintenance_history"
                   and a.id in snapshot.evidence_manifest][-1]
        draft = repo.get_artifact(context.incident_id, context.review_target_id) if context.review_target_id else None
        example = result_payload(SimpleNamespace(incident_id=context.incident_id, history_id=history), snapshot, draft=draft)
        value = next(item["assessment"] for item in example["assessments"]
                     if isinstance(AdvisoryInput.model_validate(item).assessment, ROLE_CONTRACTS[role]))
        mapping = {"plan" if source_role == "planner" else source_role: item.key
                   for item in context.advisory_inputs for source_role, cls in ROLE_CONTRACTS.items()
                   if isinstance(item.assessment, cls)}
        value["input_assessment_keys"] = [mapping[key] for key in value.get("input_assessment_keys", [])]
        if role == "critic" and not draft:
            value["subject_id"] = mapping["diagnostic"]
        self.turns = iter([[(ROLE_CONTRACTS[role].__name__, value)]])
        async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


def scripted_supervisor_turns():
    def conclude(messages):
        context = SpecialistContext.model_validate(json.loads(messages[0]["content"][0]["text"])["context"])
        return decision(context, "ADVISORY_CONCLUSION")(messages)
    diagnosis = [delegation("diagnostic"), delegation("critic", ("diagnostic",)),
                 delegation("planner", ("diagnostic", "critic")), conclude]
    review = [delegation("engineering"), delegation("operations", ("engineering",)),
              delegation("critic", ("engineering", "operations")), conclude]
    return [*diagnosis, *diagnosis, *review]


# ---------------------------------------------------------------------------------
async def test_no_provider_runs_real_lifecycle_with_labelled_deterministic_advisory(seeded_db, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a model agent was created although no provider is configured")
    monkeypatch.setattr(StrandsRuntime, "create_agent", forbidden)
    engine = make_engine(runtime=None)
    assert engine.runtime is None
    try:
        started = await engine.start_guided_demo(ASSET)
        assert started["ok"]
        demo = started["demo_scenario"]
        assert demo["scenario"]["id"] == SCENARIO_ID and demo["scenario"]["deterministic"] is True
        assert demo["scenario"]["provenance"] == "SIMULATED" and demo["scenario"]["seed"] == 7
        assert demo["reasoning"]["backend"] == "deterministic" and demo["reasoning"]["live_model"] is False
        assert demo["reasoning"]["provider"] == "none" and demo["reasoning"]["provenance"] == "SIMULATED"
        assert demo["status"] == "factory_healthy" and demo["phase"] == "FACTORY_HEALTHY"
        assert engine.snapshot()["authority_path"] == "lifecycle"

        awaiting = await wait_status(engine, "awaiting_human_approval")
        repo = engine.coordinator.repository
        incident = repo.fetch_incident(engine.incidents[ASSET].id)
        assert incident.phase == IncidentPhase.AWAITING_APPROVAL
        assert awaiting["incident_id"] == incident.id and awaiting["approval_state"] == "PENDING"
        with db.get_conn(repo.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM incident").fetchone()[0] == 1
        snapshots = artifacts_of(engine, m.SupervisorRunSnapshot)
        assert {item.stage for item in snapshots} == {"DIAGNOSIS", "INTERVENTION_REVIEW"}
        for item in snapshots:
            assert item.runtime_identity["backend"] == "deterministic"
            assert item.runtime_identity["live_model"] is False and item.runtime_identity["provider"] == "none"
        view = engine.snapshot()["alerts"][0]["lifecycle"]["read_model"]
        assert view["agent_runs"] and all(
            run["reasoning"] == {**run["reasoning"], "backend": "deterministic", "provider": "none",
                                 "live_model": False, "provenance": "SIMULATED"} for run in view["agent_runs"])
        assert all("no model provider" in (run["summary"] or "") for run in view["agent_runs"])
        assert view["diagnosis"] is not None and view["intervention"] is not None
        assert engine.snapshot()["reasoning_provenance"]["status"] == "awaiting_runtime"

        result = await engine.approve(ASSET, approval_intent(engine))
        assert result["ok"], result
        closed = await wait_status(engine, "complete", timeout=60)
        assert closed["approval_state"] == "APPROVED"
        assert repo.fetch_incident(incident.id).phase == IncidentPhase.CLOSED
        assert artifacts_of(engine, m.Outcome)[0].result == "VERIFIED_RECOVERY"
        assert engine._guided_owner is None
    finally:
        await finish(engine)


async def test_configured_runtime_is_invoked_and_its_output_reaches_durable_artifacts(seeded_db):
    supervisor = ScriptedModel(scripted_supervisor_turns())
    engine = make_engine(runtime=None)
    specialists = EngineSpecialists(engine)
    backend = LocalStrandsBackend(StrandsRuntime(settings(), model=supervisor),
                                  StrandsRuntime(settings(), model=specialists))
    engine.runtime = engine._base_runtime = backend
    try:
        started = await engine.start_guided_demo(ASSET)
        assert started["demo_scenario"]["reasoning"]["backend"] == "local"
        assert started["demo_scenario"]["reasoning"]["provenance"] == "INJECTED"
        assert started["demo_scenario"]["reasoning"]["model"] == "explicit-account-model"
        await wait_status(engine, "awaiting_human_approval")

        assert len(supervisor.calls) == 12, "the scenario's runs must invoke the configured runtime"
        assert len(specialists.packets) == 9
        repo = engine.coordinator.repository
        incident = repo.fetch_incident(engine.incidents[ASSET].id)
        diagnosis = repo.get_artifact(incident.id, incident.current_diagnosis_id)
        hypotheses = [repo.get_artifact(incident.id, key) for key in diagnosis.hypothesis_ids]
        assert MECHANISM in {item.mechanism for item in hypotheses}, "model output must reach the diagnosis"
        snapshots = artifacts_of(engine, m.SupervisorRunSnapshot)
        assert all(item.runtime_identity["backend"] == "local" for item in snapshots)
        assert all(item.runtime_identity["supervisor"]["implementation"].endswith("ScriptedModel") for item in snapshots)
        runs = engine.snapshot()["alerts"][0]["lifecycle"]["read_model"]["agent_runs"]
        assert {run["reasoning"]["provenance"] for run in runs} == {"INJECTED"}
        assert {run["reasoning"]["provider"] for run in runs} == {"bedrock"}
        assert all(run["status"] == "MODEL_COMPLETED" for run in runs)
        assert engine.snapshot()["demo_scenario"]["scenario"]["id"] == SCENARIO_ID
        assert engine.snapshot()["demo_scenario"]["reasoning"]["backend"] == "local"
    finally:
        await finish(engine)


async def test_provider_failure_is_reported_truthfully_without_fabricated_reasoning(seeded_db):
    class BrokenBackend(ReasoningBackend):
        name = "local"
        runtime = StrandsRuntime(RuntimeSettings(provider="ollama", endpoint="http://127.0.0.1:1",
                                                 model_id="gemma3:latest", live_enabled=True))

        def identity(self):
            from core.reasoning.backend import runtime_identity
            return {"backend": self.name, "supervisor": runtime_identity(self.runtime),
                    "specialists": runtime_identity(self.runtime)}

        async def supervise(self, *_args, **_kwargs):
            raise ProviderError("provider_unreachable", "Ollama is not running or not reachable at http://127.0.0.1:1",
                                provider="ollama")

    engine = make_engine(runtime=BrokenBackend())
    try:
        started = await engine.start_guided_demo(ASSET)
        assert started["demo_scenario"]["reasoning"] == {**started["demo_scenario"]["reasoning"], "backend": "local",
                                                          "provider": "ollama", "model": "gemma3:latest",
                                                          "live_model": True, "provenance": "LIVE"}
        failed = await wait_status(engine, "failed")
        assert "provider_unreachable" in failed["error"] or "not reachable" in failed["error"], failed
        assert artifacts_of(engine, m.Diagnosis) == [] and artifacts_of(engine, m.Hypothesis) == []
        reports = artifacts_of(engine, m.SupervisorReport)
        assert reports and reports[-1].completion == "MODEL_FAILED"
        assert not any("hypothes" in blocker.lower() for blocker in reports[-1].result_payload["blockers"])
        assert engine.running, "the simulator resumes after a failed scenario"
    finally:
        await finish(engine)


async def test_settings_provider_switch_applies_to_the_next_guided_demo(seeded_db, monkeypatch):
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", False)  # the process-start lock is off, as in a normal run
    engine = make_engine(runtime=None)
    try:
        assert engine.runtime is None
        config.provider_registry().select("ollama", model="gemma3:latest")
        reconfigured = await engine.reconfigure_runtime()
        assert reconfigured["supervisor_available"] is True
        assert engine.reasoning_provenance() == {**engine.reasoning_provenance(), "backend": "local",
                                                 "provider": "ollama", "model": "gemma3:latest", "live_model": True}
        started = await engine.start_guided_demo(ASSET)
        assert started["demo_scenario"]["reasoning"]["provider"] == "ollama"
        assert started["demo_scenario"]["reasoning"]["model"] == "gemma3:latest"
        assert engine._guided_backend is engine.runtime
        failed = await wait_status(engine, "failed")  # tests block the network: the real request is refused
        assert "Model invocation failed" in failed["error"] or "ollama" in failed["error"].lower(), failed
        snapshot = artifacts_of(engine, m.SupervisorRunSnapshot)[-1]
        assert snapshot.runtime_identity["supervisor"]["settings"]["provider"] == "ollama"
        assert snapshot.runtime_identity["supervisor"]["settings"]["model_id"] == "gemma3:latest"
        assert snapshot.runtime_identity["supervisor"]["implementation"] == "strands.models.ollama"

        config.provider_registry().select("none")
        await engine.reconfigure_runtime()
        assert engine.runtime is None
        restarted = await engine.start_guided_demo(ASSET)
        assert restarted["demo_scenario"]["reasoning"]["backend"] == "deterministic"
        await wait_status(engine, "awaiting_human_approval")
    finally:
        await finish(engine)


async def test_scenario_telemetry_is_reproducible_across_runs(seeded_db):
    traces, descriptors = [], []
    for _ in range(2):
        engine = make_engine(runtime=None)
        try:
            started = await engine.start_guided_demo(ASSET)
            descriptors.append(started["demo_scenario"]["scenario"])
            await wait_status(engine, "awaiting_human_approval")
            alert = engine.snapshot()["alerts"][0]
            traces.append(([point["prob"] for point in engine.histories[ASSET]], alert["created_tick"]))
        finally:
            await finish(engine)
    assert descriptors[0] == descriptors[1]
    (first, tick_a), (second, tick_b) = traces
    assert tick_a == tick_b
    common = min(len(first), len(second))
    assert first[:common] == second[:common]
    assert first[0] < config.WARN_THRESHOLD and max(first) >= config.TRIGGER_THRESHOLD


async def test_reset_restart_and_http_entry(seeded_db):
    from server import main as server_main
    engine = make_engine(runtime=None)
    previous = server_main.engine
    server_main.engine = engine
    try:
        started = await server_main.guided_demo(server_main.DemoScenarioCommand(equipment_id=ASSET))
        assert started.status_code == 200 and json.loads(started.body)["ok"] is True
        first_task = engine._guided_task
        await wait_status(engine, "awaiting_human_approval")
        restarted = await engine.start_guided_demo(ASSET)
        assert restarted["ok"] and first_task.done()
        assert engine._demo_projection()["status"] == "factory_healthy"
        await wait_status(engine, "awaiting_human_approval")
        response = await server_main.approve(ASSET, server_main.ApprovalIntent(**approval_intent(engine)))
        assert response.status_code == 200 and json.loads(response.body)["ok"] is True
        artifact = engine.demo_artifact(engine.incidents[ASSET].current_diagnosis_id)
        assert artifact["artifact_type"] == "diagnosis" and artifact["runtime"] == "Operon application"
        run = engine.snapshot()["alerts"][0]["lifecycle"]["read_model"]["agent_runs"][0]
        inspected = engine.demo_artifact(run["artifact_id"])
        assert inspected["artifact_type"] == "specialist_activity" and inspected["live_model"] is False
        assert inspected["reasoning"]["backend"] == "deterministic"
        await engine.reset()
        assert engine._demo_projection() == {"active": False} and engine._guided_task is None
        with pytest.raises(LookupError):
            engine.demo_artifact(artifact["id"])
    finally:
        server_main.engine = previous
        await finish(engine)


async def test_rejection_cancels_the_scenario_on_the_real_lifecycle(seeded_db):
    engine = make_engine(runtime=None)
    try:
        await engine.start_guided_demo(ASSET)
        await wait_status(engine, "awaiting_human_approval")
        result = await engine.reject(ASSET, approval_intent(engine))
        assert result["ok"] and result["phase"] == "ESCALATED"
        cancelled = await wait_status(engine, "cancelled")
        assert cancelled["approval_state"] == "REJECTED" and cancelled["phase"] == "ESCALATED"
        assert engine._guided_owner is None
    finally:
        await finish(engine)
