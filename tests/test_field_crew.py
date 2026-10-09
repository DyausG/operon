"""F1.2 simulated field crew (D6): deterministic scenario technicians through the ordinary work commands.

The crew is a SCENARIO actor. Every acknowledgement, decline and report goes through the
validated, audited LifecycleService commands with SIMULATED provenance. It is off unless
explicitly enabled (or for the Guided Demo asset), never runs in production, and a case
without a crew truthfully waits for work.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from core.agents.runtime import StrandsRuntime
from core.field_crew import ACTOR, RESPONSES, SimulatedFieldCrew
from core.reliability import models as m
from core.reliability.repository import utcnow
from tests.test_engine import StubModel
from tests.test_engine_lifecycle import ASSET, make_engine
from tests.test_f1_2_invariants import to_approval
from tests.test_strands_agents import ScriptedModel, settings

CREW = SimulatedFieldCrew(ack_after=timedelta(seconds=2), report_after=timedelta(seconds=3))


def work(state="ASSIGNED", **fields):
    now = utcnow()
    return {"assignment_id": "a-1", "current": True, "state": state, "assigned_at": now.isoformat(),
            "acknowledged_at": now.isoformat() if state != "ASSIGNED" else None,
            "instructions": ["Isolate", "Overhaul", "Verify"], **fields}


# ------------------------------------------------------------------ decisions
def test_the_crew_waits_for_its_delays_and_never_acts_on_superseded_work():
    assigned = work()
    now = utcnow()
    assert CREW.next_action(assigned, "COMPLETES", now) is None
    assert CREW.next_action(assigned, "COMPLETES", now + timedelta(seconds=3)).command == "acknowledge_work"
    assert CREW.next_action(work(current=False), "COMPLETES", now + timedelta(hours=1)) is None
    assert CREW.next_action(work("ACKNOWLEDGED"), "COMPLETES", now) is None
    assert CREW.next_action(work("REPORTED"), "COMPLETES", now + timedelta(hours=1)) is None
    with pytest.raises(ValueError):
        CREW.next_action(assigned, "MAGIC", now)


@pytest.mark.parametrize("response, command, result", [
    ("COMPLETES", "report_work", "COMPLETED"), ("PARTIAL", "report_work", "PARTIAL"),
    ("NOT_PERFORMED", "report_work", "NOT_PERFORMED"), ("DECLINES", "decline_work", None), ("NO_SHOW", None, None),
])
def test_each_scenario_response_maps_to_one_ordinary_command(response, command, result):
    later = utcnow() + timedelta(minutes=5)
    first = CREW.next_action(work(), response, later)
    action = first if response == "DECLINES" or first is None else CREW.next_action(work("ACKNOWLEDGED"), response, later)
    if command is None:
        assert first is None
        return
    assert action.command == command and action.arguments["request_key"].startswith("sim-crew:a-1:")
    if result is not None:
        assert action.arguments["result"] == result and action.arguments["provenance"] == "SIMULATED"
        assert "[SIMULATED field crew]" in action.arguments["summary"]
        assert action.arguments.get("asset_intervened") is (None if result == "NOT_PERFORMED" else True)
    if result == "PARTIAL":
        assert action.arguments["completed_instructions"] == (0,) and action.arguments["findings"]
    assert set(RESPONSES) >= {response}


# --------------------------------------------------------------------- engine
async def dispatched(monkeypatch, *, field_response="COMPLETES", enabled=True, response="RECOVERS"):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock, response=response)
    engine.sim.assets[ASSET].profile.field_response = field_response
    engine.field_crew_enabled = enabled
    assert (await engine.approve(ASSET, intent))["ok"]
    clock["now"] = utcnow()
    return engine, bridge, clock


async def ticks(engine, clock, count, *, step=timedelta(seconds=1)):
    for _ in range(count):
        clock["now"] += step
        await engine._advance()


def events(engine, bridge, kind):
    return [e for e in engine.coordinator.repository.list_events(bridge.incident_id) if e.event_type == kind]


async def test_without_a_crew_the_case_truthfully_waits_for_work(seeded_db, monkeypatch):
    engine, bridge, clock = await dispatched(monkeypatch, enabled=False)
    await ticks(engine, clock, 8)
    assert engine.alerts[ASSET]["lifecycle"]["verification"]["state"] == "AWAITING_WORK"
    assert not events(engine, bridge, "WORK_ACKNOWLEDGED") and engine.sim.assets[ASSET].mode == "arrested"


async def test_a_completing_crew_acts_through_audited_commands_and_verification_decides(seeded_db, monkeypatch):
    engine, bridge, clock = await dispatched(monkeypatch)
    await ticks(engine, clock, 3)
    [ack] = events(engine, bridge, "WORK_ACKNOWLEDGED")
    assert ack.payload["actor"]["kind"] == "SCENARIO" and ack.payload["actor"]["label"] == "Scenario driver (simulated)"
    await ticks(engine, clock, 4)
    [reported] = events(engine, bridge, "WORK_REPORTED")
    assert reported.payload["eligible"] is True and reported.payload["provenance"] == "SIMULATED"
    [report] = [a for a in engine.coordinator.repository.list_artifacts(bridge.incident_id) if isinstance(a, m.WorkReport)]
    assert report.actor == ACTOR and "[SIMULATED field crew]" in report.summary
    assert engine.sim.assets[ASSET].mode == "recovering"
    assert engine.alerts[ASSET]["lifecycle"]["verification"]["state"] in ("COLLECTING", "EVALUATING")
    # The report alone is not recovery: closure needs post-report scores in the healthy band.
    assert engine.coordinator.repository.fetch_incident(bridge.incident_id).phase == m.IncidentPhase.OBSERVING
    engine.model = StubModel(0.05)
    await ticks(engine, clock, 4)
    incident = engine.coordinator.repository.fetch_incident(bridge.incident_id)
    assert incident.phase == m.IncidentPhase.CLOSED
    outcome = next(a for a in engine.coordinator.repository.list_artifacts(bridge.incident_id) if isinstance(a, m.Outcome))
    assert outcome.work_report_id == report.id and outcome.observation_start > report.created_at
    assert engine._business_summary()["events_prevented"] == 1


@pytest.mark.parametrize("field_response, expected", [("DECLINES", "DECLINED"), ("NOT_PERFORMED", "REPORTED")])
async def test_a_crew_that_does_not_perform_the_work_never_starts_observation(seeded_db, monkeypatch, field_response,
                                                                             expected):
    engine, bridge, clock = await dispatched(monkeypatch, field_response=field_response)
    await ticks(engine, clock, 8)
    lifecycle = engine.alerts[ASSET]["lifecycle"]
    assert lifecycle["work"][0]["state"] == expected and lifecycle["verification"]["state"] == "WORK_NOT_PERFORMED"
    assert engine.sim.assets[ASSET].mode == "arrested"
    assert not [a for a in engine.coordinator.repository.list_artifacts(bridge.incident_id)
                if isinstance(a, (m.PlantActuation, m.ObservationPlan))]


async def test_partial_work_is_eligible_and_the_profile_decides_the_simulated_response(seeded_db, monkeypatch):
    engine, bridge, clock = await dispatched(monkeypatch, field_response="PARTIAL")
    await ticks(engine, clock, 8)
    work = engine.alerts[ASSET]["lifecycle"]["work"][0]
    assert (work["result"], work["eligible"]) == ("PARTIAL", True)
    assert engine.sim.assets[ASSET].mode == "unresponsive"  # partial_response defaults to PERSISTS


async def test_a_no_show_crew_leaves_the_acknowledgement_overdue(seeded_db, monkeypatch):
    engine, bridge, clock = await dispatched(monkeypatch, field_response="NO_SHOW")
    await ticks(engine, clock, 3)
    view = engine.lifecycle.projection(bridge.incident_id, now=utcnow() + timedelta(hours=1))
    assert view["work"][0]["ack_overdue"] is True and view["verification"]["state"] == "AWAITING_WORK"
    assert engine.coordinator.repository.fetch_incident(bridge.incident_id).phase == m.IncidentPhase.OBSERVING


async def test_the_crew_resumes_from_durable_work_state_after_restart(seeded_db, monkeypatch):
    engine, bridge, clock = await dispatched(monkeypatch)
    await ticks(engine, clock, 3)
    assert events(engine, bridge, "WORK_ACKNOWLEDGED") and not events(engine, bridge, "WORK_REPORTED")
    restarted = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    restarted.field_crew_enabled = True
    restarted._clock = lambda: clock["now"]
    await ticks(restarted, clock, 5)
    assert len(events(restarted, bridge, "WORK_ACKNOWLEDGED")) == 1 and len(events(restarted, bridge, "WORK_REPORTED")) == 1
    assert len(events(restarted, bridge, "PLANT_ACTUATION_RECORDED")) == 1
    assert restarted.sim.assets[ASSET].mode in ("recovering", "healthy")  # the simulated recovery progresses per tick


async def test_the_crew_never_exists_in_production(seeded_db, monkeypatch):
    monkeypatch.setenv("OPERON_ENVIRONMENT", "production")
    monkeypatch.setenv("OPERON_SIMULATED_FIELD_CREW", "1")
    engine = make_engine(monkeypatch)
    assert engine.field_crew is None and engine.field_crew_enabled is False


async def test_verification_sub_state_changes_are_broadcast_but_not_every_score(seeded_db, monkeypatch):
    from tests.test_engine_lifecycle import recorded_broadcasts
    engine, bridge, clock = await dispatched(monkeypatch)
    messages = recorded_broadcasts(engine)
    await ticks(engine, clock, 12)
    states = [msg["alert"]["lifecycle"]["verification"]["state"] for msg in messages
              if msg["type"] == "alert" and msg.get("phase") == "verification"]
    assert states and states == list(dict.fromkeys(states))  # one message per sub-state change
    assert "EVALUATING" in states
    snapshot_view = engine.alerts[ASSET]["lifecycle"]["verification"]
    assert snapshot_view["post_score_count"] == engine.lifecycle.verification(bridge.incident_id)["post_score_count"]
