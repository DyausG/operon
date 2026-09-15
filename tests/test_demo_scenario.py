"""Focused guarantees for the isolated Guided Demo read-model mode."""
from __future__ import annotations

import asyncio
import json

import pytest

from core import db
from core.demo import DemoScenarioRunner
from core.demo.runner import POST_APPROVAL_SECONDS, PRE_APPROVAL_SECONDS, PROVENANCE, RUNTIME
from core.engine import DemoEngine


FLEET = [
    {"equipment_id": "AC-COMP-01", "name": "Air Compressor 01",
     "equipment_class": "COMPRESSOR", "criticality": "HIGH"},
    {"equipment_id": "PUMP-01", "name": "Coolant Pump 01",
     "equipment_class": "PUMP", "criticality": "MEDIUM"},
]


async def wait_status(runner: DemoScenarioRunner, status: str, timeout: float = 2) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        state = runner.snapshot()
        if state and state["demo_scenario"]["status"] == status:
            return state
        await asyncio.sleep(.002)
    raise AssertionError(f"demo did not reach {status}: {runner.snapshot()}")


def approval_intent(state: dict) -> dict:
    lifecycle = state["alerts"][0]["lifecycle"]
    return {key: lifecycle[key] for key in
            ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}


async def capture(runner: DemoScenarioRunner, snapshots: list[dict]) -> None:
    snapshots.append(runner.snapshot())


def subsequence(expected: list[str], actual: list[str]) -> bool:
    values = iter(actual)
    return all(any(item == wanted for item in values) for wanted in expected)


@pytest.mark.asyncio
async def test_scripted_demo_pauses_and_never_auto_approves():
    snapshots = []
    runner = DemoScenarioRunner(FLEET, publish=lambda: capture(runner, snapshots), time_scale=.003)
    assert (await runner.start("AC-COMP-01"))["ok"]
    awaiting = await wait_status(runner, "awaiting_human_approval")

    assert awaiting["alerts"][0]["lifecycle"]["phase"] == "AWAITING_APPROVAL"
    assert awaiting["alerts"][0]["lifecycle"]["read_model"]["approval_decisions"] == []
    assert awaiting["demo_scenario"]["approval_state"] == "PENDING"
    assert awaiting["demo_scenario"]["elapsed_seconds"] == PRE_APPROVAL_SECONDS == 42
    assert runner.task.done()
    await asyncio.sleep(.08)
    assert runner.snapshot()["alerts"][0]["lifecycle"]["phase"] == "AWAITING_APPROVAL"

    phases = [state["demo_scenario"]["phase"] for state in snapshots]
    for phase in ("FACTORY_HEALTHY", "FACTORY_DEGRADING", "PREDICTIVE_RISK_RISING", "OPEN",
                  "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED", "PLANNING",
                  "INTERVENTION_VALIDATED", "AWAITING_APPROVAL"):
        assert phase in phases
    assert all(state["demo_scenario"]["provenance"] == PROVENANCE for state in snapshots)
    assert all(state["demo_scenario"]["runtime"] == RUNTIME for state in snapshots)
    assert all(state["demo_scenario"]["live_model"] is False for state in snapshots)
    elapsed = {state["demo_scenario"]["status"]: state["demo_scenario"]["elapsed_seconds"] for state in snapshots}
    assert elapsed == {
        "factory_healthy": 0, "degrading": 3, "risk_rising_1": 6, "risk_rising_2": 9,
        "risk_rising_3": 12, "incident_open": 14, "investigating": 17, "evidence_review": 20,
        "specialist_evidence_review": 23, "awaiting_evidence": 25, "inspection_received": 28,
        "diagnosis_validated": 31, "diagnosis_phase_validated": 34, "specialist_review": 36,
        "intervention_validated": 40, "awaiting_human_approval": PRE_APPROVAL_SECONDS,
    }


@pytest.mark.asyncio
async def test_manual_approval_runs_execution_observation_recovery_and_close():
    snapshots = []
    runner = DemoScenarioRunner(FLEET, publish=lambda: capture(runner, snapshots), time_scale=.003)
    await runner.start("AC-COMP-01")
    awaiting = await wait_status(runner, "awaiting_human_approval")

    refused = await runner.approve("AC-COMP-01", approval_intent(awaiting) | {"intervention_hash": "wrong"})
    assert refused["ok"] is False
    result = await runner.approve("AC-COMP-01", approval_intent(awaiting))
    assert result == {"ok": True, "phase": "READY", "demo": True, "provenance": "SIMULATED"}
    closed = await wait_status(runner, "complete")

    phases = [state["alerts"][0]["lifecycle"]["phase"] for state in snapshots if state["alerts"]]
    assert subsequence(["READY", "EXECUTING", "OBSERVING", "CLOSED"], phases)
    statuses = [state["demo_scenario"]["status"] for state in snapshots]
    assert subsequence(["ready", "executing", "execution_receipt", "observing", "observation_baseline",
                        "telemetry_recovering_1", "telemetry_recovering_2", "telemetry_recovering_3",
                        "telemetry_stable_healthy", "verified_recovery", "complete"], statuses)
    receipt_frame = next(state for state in snapshots if state["demo_scenario"]["status"] == "execution_receipt")
    assert receipt_frame["alerts"][0]["lifecycle"]["phase"] == "EXECUTING"
    assert closed["demo_scenario"]["elapsed_seconds"] == PRE_APPROVAL_SECONDS + POST_APPROVAL_SECONDS == 75
    elapsed = {state["demo_scenario"]["status"]: state["demo_scenario"]["elapsed_seconds"] for state in snapshots}
    assert {key: elapsed[key] for key in (
        "ready", "executing", "execution_receipt", "observing", "observation_baseline",
        "telemetry_recovering_1", "telemetry_recovering_2", "telemetry_recovering_3",
        "telemetry_stable_healthy", "verified_recovery", "complete",
    )} == {"ready": 42, "executing": 44, "execution_receipt": 49, "observing": 53,
           "observation_baseline": 56, "telemetry_recovering_1": 60, "telemetry_recovering_2": 64,
           "telemetry_recovering_3": 68, "telemetry_stable_healthy": 70,
           "verified_recovery": 72, "complete": 75}
    view = closed["alerts"][0]["lifecycle"]["read_model"]
    receipt = view["execution_receipts"][0]
    assert receipt["external_ids"]["work_order"] == "DEMO-WO-1042"
    assert receipt["technician_id"] == "TECH-DEMO-03"
    assert receipt["resources_consumed"] == [{"part_id": "DEMO-PART-BRG-04", "quantity": 1}]
    assert receipt["provenance"] == PROVENANCE
    observations = view["observation_plans"][0]["observations"]
    assert [item["failure_risk"] for item in observations] == [.64, .39, .18, .09]
    assert all(item["provenance"] == PROVENANCE and item["runtime"] == RUNTIME
               and item["live_model"] is False for item in observations)
    assert view["outcomes"][0]["result"] == "VERIFIED_RECOVERY"
    assert view["outcomes"][0]["provenance"] == PROVENANCE


@pytest.mark.asyncio
async def test_rich_demo_read_model_is_concise_consistent_and_simulated():
    runner = DemoScenarioRunner(FLEET, time_scale=.001)
    await runner.start("AC-COMP-01")
    state = await wait_status(runner, "awaiting_human_approval")
    view = state["alerts"][0]["lifecycle"]["read_model"]

    risks = [point["prob"] for point in state["histories"]["AC-COMP-01"]]
    assert risks == [.07, .14, .29, .48, .68, .86]
    assert len(view["evidence"]) == 5
    assert {item["kind"] for item in view["evidence"]} == {
        "model_signal", "telemetry", "operational_context", "maintenance_history", "inspection"}
    assert all(item["provenance"] == PROVENANCE and item["runtime"] == RUNTIME
               and item["live_model"] is False for item in view["evidence"])

    roles = {item["role"] for run in view["agent_runs"] for item in run["delegations"]}
    assert roles == {"diagnostic", "engineering", "operations", "critic", "planner"}
    assert all(item["summary"] for run in view["agent_runs"] for item in run["delegations"])
    diagnosis = view["diagnosis"]
    assert diagnosis["affected_component"] == "Drive-end bearing assembly"
    assert diagnosis["confidence"] == .94 and len(diagnosis["key_observations"]) == 3
    intervention, binding = view["intervention"], view["binding"]
    assert intervention["priority"] == "HIGH" and intervention["part_id"] == "DEMO-PART-BRG-04"
    assert intervention["estimated_downtime_minutes"] == 45 and intervention["safety_note"]
    assert binding["technician_id"] == "TECH-DEMO-03" and binding["inventory_status"] == "IN_STOCK"
    for item in [*view["agent_runs"], diagnosis, intervention, *view["verdicts"], *view["requirements"]]:
        assert item["provenance"] == PROVENANCE and item["runtime"] == RUNTIME and item["live_model"] is False
    await runner.reset()


@pytest.mark.asyncio
async def test_reset_cancels_previous_demo_task_without_stale_updates():
    runner = DemoScenarioRunner(FLEET, time_scale=.02)
    await runner.start("AC-COMP-01")
    old_task = runner.task
    await asyncio.sleep(.01)
    await runner.start("PUMP-01")
    assert old_task.done()
    assert runner.snapshot()["demo_scenario"]["equipment_id"] == "PUMP-01"
    assert runner.snapshot()["demo_scenario"]["phase"] == "FACTORY_HEALTHY"
    live = [task for task in asyncio.all_tasks() if not task.done() and task.get_name().startswith("operon-demo:")]
    assert live == [runner.task]
    await runner.reset()
    assert runner.snapshot() is None and runner.task is None
    assert not [task for task in asyncio.all_tasks() if not task.done() and task.get_name().startswith("operon-demo:")]


@pytest.mark.asyncio
async def test_engine_demo_isolated_from_production_storage_model_and_reasoning(seeded_db, monkeypatch):
    class ForbiddenRuntime:
        name = "forbidden"
        async def supervise(self, *_args, **_kwargs):
            raise AssertionError("production reasoning participated in Guided Demo")

    engine = DemoEngine(runtime=ForbiddenRuntime())
    engine.demo_runner.time_scale = .003
    with db.get_conn(engine.coordinator.repository.path) as conn:
        before = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("incident", "incident_artifact", "incident_event", "sensor_reading", "health_score")}
    monkeypatch.setattr(engine.model, "predict", lambda *_: (_ for _ in ()).throw(
        AssertionError("production model participated in Guided Demo")))

    assert (await engine.start_guided_demo("AC-COMP-01"))["ok"]
    awaiting = await wait_status(engine.demo_runner, "awaiting_human_approval")
    with db.get_conn(engine.coordinator.repository.path) as conn:
        after = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in before}
    assert after == before
    assert engine.snapshot()["authority_path"] == "demo-read-model-only"
    assert engine.snapshot()["reasoning_provenance"] == {
        "backend": "guided-demo", "runtime": RUNTIME,
        "framework": "Deterministic simulated specialist activity", "model_provider": None,
        "status": "simulated", "provenance": PROVENANCE, "live_model": False,
    }

    assert (await engine.approve("AC-COMP-01", approval_intent(awaiting)))["phase"] == "READY"
    await wait_status(engine.demo_runner, "complete")
    with db.get_conn(engine.coordinator.repository.path) as conn:
        assert {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before} == before
    old_task = engine.demo_runner.task
    await engine.reset()
    assert old_task.done()
    assert engine._demo_projection()["phase"] == "FACTORY_HEALTHY"
    assert engine.demo_runner.task is not old_task
    await engine.demo_runner.reset(publish=False)
    await engine.stop()


@pytest.mark.asyncio
async def test_http_demo_entry_and_existing_approval_action(seeded_db):
    from server import main as server_main

    previous = server_main.engine
    engine = DemoEngine(runtime=None)
    engine.demo_runner.time_scale = .003
    server_main.engine = engine
    try:
        started = await server_main.guided_demo(server_main.DemoScenarioCommand(equipment_id="AC-COMP-01"))
        assert started.status_code == 200 and json.loads(started.body)["ok"] is True
        state = await wait_status(engine.demo_runner, "awaiting_human_approval")
        response = await server_main.approve(
            "AC-COMP-01", server_main.ApprovalIntent(**approval_intent(state)))
        assert response.status_code == 200
        assert json.loads(response.body)["phase"] == "READY"
        await engine.reset()
        assert engine.snapshot()["demo_scenario"]["phase"] == "FACTORY_HEALTHY"
        await engine.demo_runner.reset(publish=False)
        await engine.stop()
    finally:
        server_main.engine = previous
