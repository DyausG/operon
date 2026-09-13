"""Focused proof that the guided recording flow uses every authority boundary."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from core import db
from core.engine import DemoEngine
from core.reliability import models as m
from core.reliability.repository import utcnow


class ResponsiveModel:
    def predict(self, features):
        risk = 0.92 if features["torque"] > 51 else 0.08
        return {"failure_prob": risk, "health_score": 1 - risk}

    def predict_mode(self, _features):
        return {"mode": "OSF", "mode_label": "Overstrain Failure"}

    def attribute(self, features):
        return [{"feature": "torque", "label": "Torque", "value": features["torque"], "contribution": 0.34}]


async def wait_for(engine, phase, timeout=8):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        incident = engine.incidents.get("AC-COMP-01")
        if incident and engine.coordinator.repository.fetch_incident(incident.id).phase == phase:
            return engine.coordinator.repository.fetch_incident(incident.id)
        await asyncio.sleep(0.02)
    raise AssertionError(f"guided demo did not reach {phase.value}: {engine._demo_projection()}")


async def test_guided_demo_pauses_for_human_then_closes_through_verifier(seeded_db, monkeypatch):
    now = {"value": utcnow()}
    def clock():
        now["value"] += timedelta(seconds=1)
        return now["value"]
    monkeypatch.setattr("core.config.TICK_SECONDS", 0.02)
    engine = DemoEngine(clock=clock)
    engine.model = ResponsiveModel()
    engine.demo_step_delay = 0.02
    try:
        before = engine.snapshot()
        assert await engine.start_guided_demo("NOT-AN-ASSET") == {"ok": False, "error": "unknown demo equipment"}
        assert engine.tick_i == before["tick"] and engine._demo_projection() == {"active": False}
        result = await engine.start_guided_demo("AC-COMP-01")
        assert result["ok"] and result["demo_scenario"]["physical_provenance"] == "SIMULATED"
        incident = await wait_for(engine, m.IncidentPhase.AWAITING_APPROVAL)

        # The controller cannot approve or execute: it intentionally stops here.
        assert engine._demo_projection()["status"] == "awaiting_human_approval"
        assert engine.coordinator.repository.list_approval_decisions(incident.id) == []
        assert engine.coordinator.repository.list_execution_receipts(incident.id) == []
        artifacts = engine.coordinator.repository.list_artifacts(incident.id)
        snapshots = [item for item in artifacts if isinstance(item, m.SupervisorRunSnapshot)]
        confirmations = [item for item in artifacts if isinstance(item, m.Evidence)
                         and item.source_capability in {"operon.confirm_mechanism", "operon.confirm_resources"}]
        assert snapshots and all(item.runtime_identity["backend"] == "demo" for item in snapshots)
        assert confirmations and all(item.provenance == "SIMULATED" for item in confirmations)

        alert = engine.alerts["AC-COMP-01"]
        intent = {key: alert["lifecycle"][key] for key in
                  ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}
        approved = await engine.approve("AC-COMP-01", intent)
        assert approved["ok"] and approved["phase"] == "OBSERVING"
        await wait_for(engine, m.IncidentPhase.CLOSED)

        receipts = engine.coordinator.repository.list_execution_receipts(incident.id)
        outcomes = [item for item in engine.coordinator.repository.list_artifacts(incident.id)
                    if isinstance(item, m.Outcome)]
        assert [item.status for item in receipts] == ["CONFIRMED"]
        assert len(outcomes) == 1 and outcomes[0].result == "VERIFIED_RECOVERY"
        assert engine._demo_projection()["status"] == "complete"
        with db.get_conn(engine.coordinator.repository.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 1
    finally:
        await engine.stop()
