"""F1.2 plant execution boundary (M3): PlantActuator, durable simulated-plant state, restart.

The lifecycle changes the (simulated) plant only through the PlantActuator port and only
in response to an eligible work report; dispatch never does. The simulated plant keeps
its own durable memory, so a restart resumes it exactly and can never manufacture a
recovery. Production has no actuator: every effect is NOT_SUPPORTED.
"""
from __future__ import annotations

from datetime import timedelta
import inspect
import re

import numpy as np
import pytest

from core import db, engine as engine_module, plant
from core.agents.runtime import StrandsRuntime
from core.plant import (NullActuator, PlantActuationError, PlantEffect, SimulatorActuator, SimulatorStateStore,
                        actuator_for)
from core.reliability import models as m
from core.reliability import outcome as outcome_module
from core.reliability.lifecycle import LifecycleRefused
from core.reliability.repository import DuplicateRecord, utcnow
from core.simulator import FLEET, PlantSimulator, estimate_progress
from tests.test_engine_lifecycle import ASSET, make_engine
from tests.test_f1_2_invariants import TECHNICIAN, report_via_engine, to_approval
from tests.test_strands_agents import ScriptedModel, settings


def restart(monkeypatch):
    return make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))


async def dispatched(monkeypatch, *, response="RECOVERS"):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock, response=response)
    assert (await engine.approve(ASSET, intent))["ok"]
    return engine, bridge


def actuations(engine, incident_id):
    return [a for a in engine.coordinator.repository.list_artifacts(incident_id) if isinstance(a, m.PlantActuation)]


# ------------------------------------------------------------------- actuators
@pytest.mark.parametrize("result, intervention, partial, mode, profile", [
    ("COMPLETED", "RECOVERS", "PERSISTS", "recovering", "RECOVERS"),
    ("COMPLETED", "PERSISTS", "PERSISTS", "unresponsive", "PERSISTS"),
    ("PARTIAL", "RECOVERS", "PERSISTS", "unresponsive", "PERSISTS"),
    ("PARTIAL", "PERSISTS", "RECOVERS", "recovering", "RECOVERS"),
])
def test_simulated_plant_responds_to_eligible_work_by_profile(result, intervention, partial, mode, profile):
    sim = PlantSimulator()
    state = sim.assets[ASSET]
    state.mode, state.prog = "arrested", 0.9
    state.profile.intervention_response, state.profile.partial_response = intervention, partial
    outcome = SimulatorActuator(lambda: sim).apply(PlantEffect("WORK_PERFORMED", ASSET, work_result=result, report_id="r"))
    assert (outcome.status, outcome.mode_before, outcome.mode_after, outcome.response_profile) == (
        "APPLIED", "arrested", mode, profile)
    assert outcome.actuator == "core.plant.SimulatorActuator" and outcome.applied


def test_only_eligible_work_can_be_a_work_effect():
    for result in ("NOT_PERFORMED", None):
        with pytest.raises(ValueError, match="eligible COMPLETED/PARTIAL"):
            PlantEffect("WORK_PERFORMED", ASSET, work_result=result, report_id="r")
    with pytest.raises(ValueError, match="eligible COMPLETED/PARTIAL"):
        PlantEffect("WORK_PERFORMED", ASSET, work_result="COMPLETED")
    with pytest.raises(PlantActuationError):
        SimulatorActuator(PlantSimulator).apply(PlantEffect("ANALYSIS_HOLD", "NO-SUCH-ASSET"))


def test_holds_releases_and_run_to_failure_are_named_effects():
    sim = PlantSimulator()
    actuator = SimulatorActuator(lambda: sim)
    assert actuator.apply(PlantEffect("ANALYSIS_HOLD", ASSET)).mode_after == "arrested"
    assert actuator.apply(PlantEffect("HOLD_RELEASED", ASSET)).mode_after == "degrading"
    assert actuator.apply(PlantEffect("RUN_TO_FAILURE", ASSET)).mode_after == "failing"
    assert actuator.apply(PlantEffect("HOLD_REAPPLIED", ASSET)).mode_after == "arrested"
    healthy = next(p.equipment_id for p in FLEET if p.scenario == "healthy")
    actuator.apply(PlantEffect("ANALYSIS_HOLD", healthy))
    assert actuator.apply(PlantEffect("HOLD_RELEASED", healthy)).mode_after == "healthy"


def test_production_has_no_actuator_and_never_reports_execution():
    sim = PlantSimulator()
    before = sim.snapshot()
    actuator = actuator_for("production", lambda: sim)
    assert isinstance(actuator, NullActuator) and actuator.kind == "none"
    for effect in (PlantEffect("ANALYSIS_HOLD", ASSET), PlantEffect("WORK_PERFORMED", ASSET, work_result="COMPLETED",
                                                                     report_id="r")):
        result = actuator.apply(effect)
        assert result.status == "NOT_SUPPORTED" and not result.applied and result.mode_after is None
        assert "nothing was applied" in result.reason
    assert sim.snapshot() == before
    assert isinstance(actuator_for("sandbox", lambda: sim), SimulatorActuator)
    assert isinstance(actuator_for("unspecified", lambda: sim), SimulatorActuator)


def test_actuation_records_cannot_misrepresent_what_was_applied():
    common = dict(id="a", incident_id="i", created_at=utcnow(), equipment_ids=(ASSET,), report_id="r", assignment_id="w",
                  actuator="x", work_result="COMPLETED", reason="r")
    m.PlantActuation(**common, status="APPLIED", actuator_kind="simulator", provenance="SIMULATED", mode_after="recovering")
    m.PlantActuation(**common, status="NOT_SUPPORTED", actuator_kind="none")
    for bad in (dict(status="APPLIED", actuator_kind="none", provenance="SIMULATED"),
                dict(status="APPLIED", actuator_kind="simulator"),
                dict(status="NOT_SUPPORTED", actuator_kind="none", provenance="SIMULATED"),
                dict(status="NOT_SUPPORTED", actuator_kind="none", mode_after="recovering")):
        with pytest.raises(ValueError):
            m.PlantActuation(**common, **bad)


# ------------------------------------------------------- durable plant state
def test_simulator_state_round_trips_exactly(seeded_db):
    sim = PlantSimulator()
    for _ in range(5):
        sim.tick()
    sim.assets[ASSET].mode, sim.assets[ASSET].prog = "unresponsive", 1.02
    sim.assets[ASSET].profile.intervention_response, sim.assets[ASSET].profile.field_response = "PERSISTS", "DECLINES"
    store = SimulatorStateStore()
    store.save(sim)
    store.save(sim)  # upsert, not duplicate rows
    restored = PlantSimulator()
    assert restored.restore(store.load()) == set(sim.assets)
    assert restored.snapshot() == sim.snapshot()
    db.reset_transactional()
    assert store.load() == {}


def test_progress_estimate_is_deterministic_and_close_to_the_true_condition():
    for profile in FLEET:
        sim = PlantSimulator()
        state = sim.assets[profile.equipment_id]
        for true_prog in (0.0, 0.4, 0.9, 1.1):
            state.prog = true_prog
            samples = [sim._features_for(state) for _ in range(3)]
            readings = {key: float(np.mean([sample[key] for sample in samples])) for key in samples[0]}
            estimate = estimate_progress(state.profile, readings)
            assert estimate == estimate_progress(state.profile, readings)
            if profile.scenario == "healthy":
                assert estimate == 0.0
            else:
                assert abs(estimate - true_prog) < 0.08, (profile.equipment_id, true_prog, estimate)


# ------------------------------------------------------------- engine wiring
async def test_eligible_report_actuates_once_and_is_recorded_as_simulated(seeded_db, monkeypatch):
    engine, bridge = await dispatched(monkeypatch)
    assert engine.sim.assets[ASSET].mode == "arrested" and not actuations(engine, bridge.incident_id)
    await report_via_engine(engine, bridge)
    [actuation] = actuations(engine, bridge.incident_id)
    assert (actuation.status, actuation.provenance, actuation.mode_before, actuation.mode_after) == (
        "APPLIED", "SIMULATED", "arrested", "recovering")
    assert engine.sim.assets[ASSET].mode == "recovering"
    stored = SimulatorStateStore().load()[ASSET]
    assert stored["mode"] == "recovering"  # durable before the record exists
    plant_view = engine.alerts[ASSET]["lifecycle"]["plant"]
    assert plant_view["actuator"] == "simulator" and plant_view["pending_report_ids"] == []
    assert plant_view["actuations"][0]["report_id"] == actuation.report_id
    events = [e for e in engine.coordinator.repository.list_events(bridge.incident_id)
              if e.event_type == "PLANT_ACTUATION_RECORDED"]
    assert len(events) == 1 and events[0].payload["actor"]["kind"] == "SYSTEM"
    # Idempotent: recording the same report again returns the same record; the index refuses a second row.
    from core.plant import ActuationResult
    again = engine.lifecycle.record_actuation(bridge.incident_id, report_id=actuation.report_id, result=ActuationResult(
        status="APPLIED", actuator="x", actuator_kind="simulator", cause="WORK_PERFORMED", equipment_id=ASSET, reason="x"))
    assert again == actuation
    with pytest.raises(DuplicateRecord):
        with engine.coordinator.repository._write() as conn:
            engine.coordinator.repository._store_artifact(
                conn, engine.coordinator.repository._fetch(conn, bridge.incident_id),
                actuation.model_copy(update={"id": "second"}), historical_input=True)


async def test_ineligible_or_declined_work_never_actuates(seeded_db, monkeypatch):
    engine, bridge = await dispatched(monkeypatch)
    [work] = engine.lifecycle.work_status(bridge.incident_id)
    await engine.lifecycle_command(bridge.incident_id, "acknowledge_work", assignment_id=work["assignment_id"],
                                   expected_revision=bridge.revision(), actor=TECHNICIAN)
    response = await engine.lifecycle_command(
        bridge.incident_id, "report_work", assignment_id=work["assignment_id"], expected_revision=bridge.revision(),
        actor=TECHNICIAN, result="COMPLETED", summary="Paperwork closed only", performed_at=utcnow(),
        asset_intervened=False)
    assert response["ok"] and response["incident"]["verification"]["state"] == "WORK_NOT_PERFORMED"
    assert engine.sim.assets[ASSET].mode == "arrested" and not actuations(engine, bridge.incident_id)
    report_id = engine.lifecycle.work_status(bridge.incident_id)[0]["report_id"]
    with pytest.raises(LifecycleRefused, match="only an eligible work report"):
        engine.lifecycle.record_actuation(bridge.incident_id, report_id=report_id, result=None)


async def test_dispatch_and_ticks_without_work_leave_the_plant_held(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock)
    held = engine.sim.assets[ASSET].prog
    assert (await engine.approve(ASSET, intent))["ok"]
    for _ in range(4):
        clock["now"] += timedelta(seconds=1)
        await engine._advance()
    assert (engine.sim.assets[ASSET].mode, engine.sim.assets[ASSET].prog) == ("arrested", held)
    assert engine.alerts[ASSET]["lifecycle"]["verification"]["state"] == "AWAITING_WORK"


async def test_a_crash_between_report_and_actuation_is_replayed_once(seeded_db, monkeypatch):
    engine, bridge = await dispatched(monkeypatch)
    [work] = engine.lifecycle.work_status(bridge.incident_id)
    # The report commits but the engine "crashes" before its plant effect is applied.
    engine.lifecycle.acknowledge_work(bridge.incident_id, assignment_id=work["assignment_id"],
                                      expected_revision=bridge.revision(), actor=TECHNICIAN)
    report = engine.lifecycle.report_work(bridge.incident_id, assignment_id=work["assignment_id"],
                                          expected_revision=bridge.revision(), actor=TECHNICIAN, result="COMPLETED",
                                          summary="done", performed_at=utcnow(), asset_intervened=True)
    assert engine.sim.assets[ASSET].mode == "arrested"
    assert [r.id for r in engine.lifecycle.pending_actuations(bridge.incident_id)] == [report.id]
    restarted = restart(monkeypatch)
    assert restarted.sim.assets[ASSET].mode == "recovering"
    assert len(actuations(restarted, bridge.incident_id)) == 1 and not restarted.lifecycle.pending_actuations(bridge.incident_id)
    again = restart(monkeypatch)
    assert len(actuations(again, bridge.incident_id)) == 1 and again.sim.assets[ASSET].mode == "recovering"


async def test_an_actuator_failure_is_recorded_and_replayed_at_restart(seeded_db, monkeypatch):
    engine, bridge = await dispatched(monkeypatch)

    def broken(effect):
        raise RuntimeError("simulator unavailable")
    monkeypatch.setattr(engine.actuator, "apply", broken)
    await report_via_engine(engine, bridge)
    assert not actuations(engine, bridge.incident_id) and engine.sim.assets[ASSET].mode == "arrested"
    plant_view = engine.lifecycle.projection(bridge.incident_id)["plant"]
    assert plant_view["failures"][0]["error"].startswith("RuntimeError") and plant_view["pending_report_ids"]
    restarted = restart(monkeypatch)  # a fresh engine has a working actuator
    assert len(actuations(restarted, bridge.incident_id)) == 1 and restarted.sim.assets[ASSET].mode == "recovering"
    assert restarted.lifecycle.projection(bridge.incident_id)["plant"]["failures"] == []


async def test_without_an_actuator_reported_work_changes_nothing_and_says_so(seeded_db, monkeypatch):
    engine, bridge = await dispatched(monkeypatch)
    engine.actuator = NullActuator()
    await report_via_engine(engine, bridge)
    [actuation] = actuations(engine, bridge.incident_id)
    assert (actuation.status, actuation.actuator_kind, actuation.provenance, actuation.mode_after) == (
        "NOT_SUPPORTED", "none", None, None)
    assert engine.sim.assets[ASSET].mode == "arrested"
    # Verification is independent of the actuator: the report still opened observation.
    assert engine.alerts[ASSET]["lifecycle"]["verification"]["state"] in ("COLLECTING", "EVALUATING")


async def test_production_engine_has_no_plant_actuator(seeded_db, monkeypatch):
    monkeypatch.setenv("OPERON_ENVIRONMENT", "production")
    engine = make_engine(monkeypatch)
    assert engine.actuator.kind == "none"


async def test_pre_009_database_restores_held_condition_from_telemetry(seeded_db, monkeypatch):
    engine, bridge = await dispatched(monkeypatch)
    for _ in range(3):
        await engine._advance()
    held = engine.sim.assets[ASSET].prog
    other = next(p.equipment_id for p in FLEET if p.scenario == "healthy")
    with db.get_conn() as conn:  # a database written before migration 009 has no plant memory
        conn.execute("DELETE FROM simulator_asset_state")
    restarted = restart(monkeypatch)
    state = restarted.sim.assets[ASSET]
    assert state.mode == "arrested" and abs(state.prog - held) < 0.1  # held, never reset to healthy
    assert restarted.sim.assets[other].prog == 0.0  # ordinary assets follow their profile


# --------------------------------------------------------------- static guards
def test_verification_never_reads_plant_actuation_or_the_simulator():
    source = inspect.getsource(outcome_module)
    assert "PlantActuation" not in source and "simulator" not in source.lower().replace("simulated", "")


def test_engine_lifecycle_paths_change_the_simulator_only_through_the_actuator():
    source = inspect.getsource(engine_module.DemoEngine)
    allowed = {"_recover_incidents", "start_guided_demo", "_plan_legacy_alert", "_approve_legacy", "_reject_legacy",
               "_restore_held_asset"}
    offenders = []
    for name, method in inspect.getmembers(engine_module.DemoEngine, inspect.isfunction):
        if name in allowed:
            continue
        body = inspect.getsource(method)
        if re.search(r"sim\.set_mode|respond_to_(intervention|work)|\.mode\s*=(?!=)|\.prog\s*=(?!=)", body):
            offenders.append(name)
    assert offenders == [] and "respond_to_intervention" not in source
    assert inspect.getsource(plant).count("respond_to_work") == 1


# ------------------------------------------------- concurrency and restart matrix
async def test_concurrent_actuation_records_converge_on_one(seeded_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from core.plant import ActuationResult
    from core.reliability.lifecycle import LifecycleService
    engine, bridge = await dispatched(monkeypatch)
    [work] = engine.lifecycle.work_status(bridge.incident_id)
    engine.lifecycle.acknowledge_work(bridge.incident_id, assignment_id=work["assignment_id"],
                                      expected_revision=bridge.revision(), actor=TECHNICIAN)
    report = engine.lifecycle.report_work(bridge.incident_id, assignment_id=work["assignment_id"],
                                          expected_revision=bridge.revision(), actor=TECHNICIAN, result="COMPLETED",
                                          summary="done", performed_at=utcnow(), asset_intervened=True)
    result = ActuationResult(status="APPLIED", actuator="core.plant.SimulatorActuator", actuator_kind="simulator",
                             cause="WORK_PERFORMED", equipment_id=ASSET, reason="replay", mode_before="arrested",
                             mode_after="recovering", response_profile="RECOVERS")
    barrier = threading.Barrier(3)

    def record(_):
        barrier.wait()
        return LifecycleService(engine.coordinator.repository).record_actuation(bridge.incident_id, report_id=report.id,
                                                                                result=result)
    with ThreadPoolExecutor(max_workers=3) as pool:
        recorded = list(pool.map(record, range(3)))
    assert len({item.id for item in recorded}) == 1 and len(actuations(engine, bridge.incident_id)) == 1


async def test_projection_is_identical_across_a_restart_mid_observation(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock)
    assert (await engine.approve(ASSET, intent))["ok"]
    await report_via_engine(engine, bridge)
    clock["now"] = utcnow() + timedelta(seconds=2)
    for _ in range(4):
        clock["now"] += timedelta(seconds=1)
        await engine._advance()
    now = clock["now"]
    before = engine.lifecycle.projection(bridge.incident_id, now=now, actuator_kind="simulator")
    assert before["verification"]["state"] == "EVALUATING" and before["phase"] == "OBSERVING"
    restarted = restart(monkeypatch)
    after = restarted.lifecycle.projection(bridge.incident_id, now=now, actuator_kind=restarted.actuator.kind)
    assert after == before
    assert {key: restarted.sim.assets[ASSET].__dict__[key] for key in ("mode", "prog", "tick")} == {
        key: engine.sim.assets[ASSET].__dict__[key] for key in ("mode", "prog", "tick")}


def test_simulator_is_deterministic_from_the_same_restored_state():
    first, second = PlantSimulator(), PlantSimulator()
    for _ in range(4):
        first.tick()
    second.restore({row["equipment_id"]: row for row in first.snapshot()})
    replay = PlantSimulator()
    replay.restore({row["equipment_id"]: row for row in first.snapshot()})
    assert [second.tick() for _ in range(3)] == [replay.tick() for _ in range(3)]


async def test_a_hold_applied_inside_a_tick_survives_a_crash_before_the_next_save(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)  # StubModel 0.91: every degrading asset is admitted in this tick
    engine.sim.assets[ASSET].prog = 0.9
    await engine.stop()
    await engine._advance()  # tick save happens before admission; the admission hold is not yet durable
    await engine.drain()
    assert engine.sim.assets[ASSET].mode == "arrested"
    assert SimulatorStateStore().load()[ASSET]["mode"] == "degrading"
    held = engine.sim.assets[ASSET].prog
    restarted = restart(monkeypatch)  # crash: no further tick
    assert (restarted.sim.assets[ASSET].mode, restarted.sim.assets[ASSET].prog) == ("arrested", held)
