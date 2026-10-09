"""D10: the deprecated legacy demo (OPERON_LEGACY_DEMO) is isolated from the F1.2 verified workflow.

The legacy path keeps its historical behaviour (approval sets the simulated asset to
"recovering"), unchanged by F1.2. These tests demonstrate that it can neither enter nor
corrupt V2's work and verification lifecycle: a legacy case has no work assignment, no
plant actuation record, no observation plan and can never be verified or closed; and an
engine running in legacy mode never touches a V2 case.
"""
from __future__ import annotations

import pytest

from core.agents.runtime import StrandsRuntime
from core.reliability import models as m
from core.reliability.lifecycle import AuthorityRefused, LifecycleRefused
from core.reliability.repository import utcnow
from tests.test_engine import StubModel
from tests.test_engine_lifecycle import ASSET, make_engine
from tests.test_f1_2_invariants import TECHNICIAN, report_via_engine, to_approval
from tests.test_strands_agents import ScriptedModel, settings

V2_RECORDS = (m.WorkAssignment, m.WorkReport, m.PlantActuation, m.ObservationPlan, m.Outcome)


def records(engine, incident_id, kinds=V2_RECORDS):
    return [a for a in engine.coordinator.repository.list_artifacts(incident_id) if isinstance(a, kinds)]


async def test_a_legacy_case_can_never_enter_work_or_verification(seeded_db, monkeypatch):
    legacy = make_engine(monkeypatch, legacy=True)
    monkeypatch.setattr(StubModel, "attribute", lambda self, _features: [
        {"feature": "torque", "label": "Torque", "value": 62.0, "contribution": 0.34}])
    await legacy._advance()
    legacy.sim.assets[ASSET].prog = 0.9
    assert (await legacy.approve(ASSET))["ok"]
    incident = legacy.incidents[ASSET]
    assert legacy.sim.assets[ASSET].mode == "recovering"  # documented legacy behaviour, unchanged by F1.2
    assert records(legacy, incident.id) == []
    with pytest.raises(AuthorityRefused):
        legacy.lifecycle.verify_outcome(incident.id)
    view = legacy.lifecycle.projection(incident.id)
    assert view["verification"]["state"] == "BLOCKED" and view["work"] == []
    with pytest.raises(LifecycleRefused):
        legacy.lifecycle.acknowledge_work(incident.id, assignment_id="any", expected_revision=incident.revision,
                                          actor=TECHNICIAN)
    # A V2 engine restarted over the same database never verifies or closes the legacy case.
    v2 = make_engine(monkeypatch, failure_prob=0.05)
    for _ in range(4):
        await v2._advance()
    assert records(v2, incident.id) == []
    assert v2.coordinator.repository.fetch_incident(incident.id).phase != m.IncidentPhase.CLOSED


async def test_a_legacy_mode_engine_never_touches_a_v2_case(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock)
    assert (await engine.approve(ASSET, intent))["ok"]
    before = engine.coordinator.repository.fetch_incident(bridge.incident_id)
    legacy = make_engine(monkeypatch, legacy=True)
    for _ in range(4):
        await legacy._advance()
    after = legacy.coordinator.repository.fetch_incident(bridge.incident_id)
    assert after == before and not records(legacy, bridge.incident_id, (m.LegacyAlert,))
    # Back on the authoritative path the V2 case continues exactly where it was.
    resumed = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    assert resumed.alerts[ASSET]["lifecycle"]["verification"]["state"] == "AWAITING_WORK"
    await report_via_engine(resumed, bridge)
    assert resumed.alerts[ASSET]["lifecycle"]["verification"]["state"] in ("COLLECTING", "EVALUATING")
    assert len(records(resumed, bridge.incident_id, (m.PlantActuation,))) == 1
