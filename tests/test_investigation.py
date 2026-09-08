"""Deterministic investigation gathers evidence without asserting a diagnosis."""
from datetime import timedelta

from core import db
from core.reliability import models as m
from core.reliability.investigation import DeterministicInvestigator
from core.reliability.repository import IncidentRepository, new_id, utcnow


def _signal(asset_id="HYD-PUMP-03"):
    now = utcnow()
    return m.ModelSignal(
        id=new_id(), created_at=now, equipment_id=asset_id, observed_at=now,
        risk_score=0.88, health_score=0.12, candidate_failure_mode="HDF",
        mode_distribution={"HDF": 0.7, "PWF": 0.3}, features={"torque": 39.0},
        model_source="test.HealthModel", model_version="sha256:test",
        input_source="core.simulator.PlantSimulator", input_provenance="SIMULATED",
    )


def _persist_demo_telemetry(asset_id="HYD-PUMP-03"):
    start = utcnow() - timedelta(minutes=3)
    # Persisted values use the real seeded sensor identity/unit and a bounded,
    # deterministic trend representative of simulator output.
    with db.get_conn() as conn:
        for offset, value in enumerate((43.0, 41.0, 39.0)):
            conn.execute("INSERT INTO sensor_reading VALUES (?,?,?,?)", (
                f"{asset_id}-TORQUE", (start + timedelta(minutes=offset)).isoformat(), value, "GOOD",
            ))


def test_investigation_transitions_collects_packet_and_has_no_consequential_effects(seeded_db):
    repo = IncidentRepository()
    _persist_demo_telemetry()
    incident, _ = repo.admit_signal(_signal())
    with db.get_conn() as conn:
        protected = ("work_order", "maintenance_event", "work_package", "part_reservation",
                     "labor_booking", "notification", "alert", "part", "technician")
        before = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in protected}

    result = DeterministicInvestigator(repo).investigate(incident.id, telemetry_sample_limit=20)
    assert result.incident.phase == m.IncidentPhase.INVESTIGATING
    assert "get_maintenance_history" in result.unavailable_capabilities
    assert "get_related_incidents" in result.unavailable_capabilities

    artifacts = repo.list_artifacts(incident.id)
    evidence = [item for item in artifacts if isinstance(item, m.Evidence)]
    assert {item.kind for item in evidence} >= {
        "model_signal", "telemetry", "maintenance_history", "asset_relation", "operational_context",
    }
    missing = [item for item in evidence if item.quality == "MISSING"]
    assert {item.source_capability for item in missing} >= {
        "get_maintenance_history", "get_related_incidents",
    }
    telemetry = next(item for item in evidence if item.kind == "telemetry")
    torque = next(item for item in telemetry.payload["series"] if item["sensor_type"] == "TORQUE")
    assert torque["statistics"]["trend"] == "FALLING"
    assert torque["statistics"]["first_value"] == 43.0
    assert torque["statistics"]["latest_value"] == 39.0

    assert not any(isinstance(item, (m.Hypothesis, m.Diagnosis, m.ValidationVerdict, m.Intervention))
                   for item in artifacts)
    action = repo.get_artifact(incident.id, result.action_id)
    assert isinstance(action, m.AgentAction)
    assert action.mode == "DETERMINISTIC" and action.model_id is None
    assert action.tool_name == "collect_baseline_evidence"

    with db.get_conn() as conn:
        after = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in protected}
    assert after == before


def test_investigation_packet_reconstructs_with_incident_scope(seeded_db):
    repo = IncidentRepository()
    _persist_demo_telemetry("AC-COMP-01")
    incident, _ = repo.admit_signal(_signal("AC-COMP-01"))
    result = DeterministicInvestigator(repo).investigate(incident.id)

    rebuilt = IncidentRepository(repo.path)
    recovered = rebuilt.fetch_incident(incident.id)
    recovered_evidence = [rebuilt.get_artifact(incident.id, evidence_id)
                          for evidence_id in result.evidence_ids]
    assert recovered.phase == m.IncidentPhase.INVESTIGATING
    assert all(isinstance(item, m.Evidence) for item in recovered_evidence)
    assert all(item.incident_id == incident.id for item in recovered_evidence)
    assert all(set(item.equipment_ids) <= set(incident.equipment_ids) for item in recovered_evidence)
    assert not any(isinstance(item, m.Diagnosis) for item in rebuilt.list_artifacts(incident.id))
