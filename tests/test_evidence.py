"""Bounded evidence retrieval and request/persistence behavior."""
from datetime import timedelta
import subprocess
import sys

import pytest

from core import db
from core.reliability import models as m
from core.reliability.evidence import (
    Availability, DataOrigin, EvidenceCapabilities, EvidenceService,
    TrendDirection, UnsupportedEvidenceCapability,
)
from core.reliability.repository import IncidentRepository, InvalidReference, new_id, utcnow
from core.seed_data import SENSOR_FEATURES
from core.simulator import PlantSimulator


@pytest.fixture
def repo(seeded_db):
    return IncidentRepository()


def _signal(asset_id="AC-COMP-01"):
    now = utcnow()
    return m.ModelSignal(
        id=new_id(), created_at=now, equipment_id=asset_id, observed_at=now,
        risk_score=0.9, health_score=0.1, candidate_failure_mode="PWF",
        mode_distribution={"PWF": 1.0}, features={"torque": 16.0},
        model_source="test.HealthModel", model_version="sha256:test",
        input_source="core.simulator.PlantSimulator", input_provenance="SIMULATED",
    )


def _readings(asset_id="AC-COMP-01", sensor_type="TORQUE", values=(10.0, 12.0, 14.0, 16.0)):
    start = utcnow() - timedelta(minutes=len(values))
    with db.get_conn() as conn:
        for offset, value in enumerate(values):
            conn.execute("INSERT INTO sensor_reading VALUES (?,?,?,?)", (
                f"{asset_id}-{sensor_type}", (start + timedelta(minutes=offset)).isoformat(), value, "GOOD",
            ))
    return start


def test_asset_context_returns_grounded_sensor_inventory_and_explicit_unknowns(repo):
    _readings(values=(41.0,))
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) "
            "VALUES (?,?,?,?,?)", ("AC-COMP-01", utcnow().isoformat(), 0.1, 0.9, "PWF"),
        )
    context = EvidenceCapabilities(repo.path).get_asset_context("AC-COMP-01")
    assert context.availability == Availability.AVAILABLE
    assert context.asset_type == "COMPRESSOR" and context.line_id == "LINE-A"
    assert context.current_risk == 0.9 and context.risk_state == "CRITICAL"
    torque = next(sensor for sensor in context.sensors if sensor.sensor_type == "TORQUE")
    assert torque.unit == "Nm" and torque.latest_reading.value == 41.0
    assert context.operating_state is None
    assert {"operating_state", "oem_specifications", "operating_limits"} <= set(context.missing_fields)
    assert DataOrigin.SEEDED_DEMO in context.provenance.data_origins

    missing = EvidenceCapabilities(repo.path).get_asset_context("UNKNOWN-ASSET")
    assert missing.availability == Availability.UNAVAILABLE
    assert missing.asset_name is None and missing.missing_reason


def test_telemetry_window_statistics_trend_bounds_units_and_provenance(repo):
    start = _readings()
    result = EvidenceCapabilities(repo.path).get_telemetry_window(
        "AC-COMP-01", sensor_type="torque", start_at=start, sample_limit=3,
    )
    assert result.availability == Availability.AVAILABLE
    assert result.requested_sample_limit == 3 and result.sensor_type == "TORQUE"
    series = result.series[0]
    assert [point.value for point in series.readings] == [12.0, 14.0, 16.0]
    assert all(point.unit == "Nm" and point.asset_id == "AC-COMP-01" for point in series.readings)
    stats = series.statistics
    assert (stats.first_value, stats.latest_value, stats.minimum, stats.maximum) == (12.0, 16.0, 12.0, 16.0)
    assert stats.mean == 14.0 and stats.absolute_delta == 4.0
    assert stats.percentage_delta == pytest.approx(33.3333333)
    assert stats.trend == TrendDirection.RISING
    assert result.provenance.capability == "get_telemetry_window"
    assert result.provenance.source_tables == ("sensor", "sensor_reading")
    assert result.provenance.data_origins == (DataOrigin.SIMULATED,)
    assert result.provenance.observation_start == series.readings[0].timestamp
    assert "limit=3" in result.provenance.locator


def test_statistics_are_derived_from_persisted_demo_simulator_telemetry(repo):
    simulator = PlantSimulator(seed=7)
    observed = utcnow() - timedelta(seconds=4)
    persisted_torque = []
    with db.get_conn() as conn:
        for tick in range(4):
            features = simulator.tick()["AC-COMP-01"]
            persisted_torque.append(features["torque"])
            timestamp = (observed + timedelta(seconds=tick)).isoformat()
            for feature, sensor_type, _unit in SENSOR_FEATURES:
                conn.execute("INSERT INTO sensor_reading VALUES (?,?,?,?)", (
                    f"AC-COMP-01-{sensor_type}", timestamp, features[feature], "GOOD",
                ))
    result = EvidenceCapabilities(repo.path).get_telemetry_window(
        "AC-COMP-01", sensor_type="TORQUE", sample_limit=4,
    )
    stats = result.series[0].statistics
    assert [point.value for point in result.series[0].readings] == persisted_torque
    assert stats.first_value == persisted_torque[0]
    assert stats.latest_value == persisted_torque[-1]
    assert stats.minimum == min(persisted_torque)
    assert stats.maximum == max(persisted_torque)
    assert stats.mean == pytest.approx(sum(persisted_torque) / len(persisted_torque))
    assert stats.trend in {TrendDirection.RISING, TrendDirection.FALLING, TrendDirection.STABLE}


def test_insufficient_and_missing_telemetry_are_explicit(repo):
    _readings(values=(0.0,))
    one = EvidenceCapabilities(repo.path).get_telemetry_window(
        "AC-COMP-01", sensor_type="TORQUE", sample_limit=10,
    )
    assert one.availability == Availability.PARTIAL
    assert one.series[0].statistics.trend == TrendDirection.INSUFFICIENT_DATA
    assert one.series[0].statistics.absolute_delta is None
    assert one.series[0].missing_reason

    missing = EvidenceCapabilities(repo.path).get_telemetry_window(
        "AC-COMP-01", sensor_type="VIBRATION", sample_limit=10,
    )
    assert missing.availability == Availability.UNAVAILABLE
    assert missing.series == () and "not registered" in missing.missing_reason


def test_maintenance_history_returns_only_persisted_records(repo):
    capabilities = EvidenceCapabilities(repo.path)
    history = capabilities.get_maintenance_history("AC-COMP-01")
    assert history.availability == Availability.AVAILABLE
    assert len(history.records) == 1
    record = history.records[0]
    assert record.work_order_number == "DEMO-HIST-WO-0001"
    assert record.status == "COMPLETE" and record.technician_id == "TECH-201"
    assert record.data_origin == DataOrigin.SEEDED_DEMO
    assert record.outcome is None  # current schema does not store one
    assert history.provenance.source_tables[0] == "work_order"

    empty = capabilities.get_maintenance_history("HYD-PUMP-03")
    assert empty.availability == Availability.UNAVAILABLE
    assert empty.records == () and empty.missing_reason


def test_related_incidents_are_same_asset_only_and_do_not_invent_diagnosis(repo):
    current, _ = repo.admit_signal(_signal())
    previous = repo.create_incident(("AC-COMP-01",), admission_key="older-ac")
    other = repo.create_incident(("HYD-PUMP-03",), admission_key="other-pump")
    result = EvidenceCapabilities(repo.path).get_related_incidents(
        "AC-COMP-01", exclude_incident_id=current.id,
    )
    assert [item.incident_id for item in result.incidents] == [previous.id]
    assert result.incidents[0].validated_diagnosis is None
    assert other.id not in {item.incident_id for item in result.incidents}


def test_evidence_request_persists_provenance_events_and_is_idempotent(repo):
    incident, _ = repo.admit_signal(_signal())
    service = EvidenceService(repo, EvidenceCapabilities(repo.path))
    kwargs = dict(
        requested_by="diagnostic", equipment_ids=("AC-COMP-01",),
        question="What equipment and sensors are persisted?",
        capability="get_asset_context", required_for="diagnosis", parameters={},
    )
    first = service.request_and_collect(incident.id, **kwargs)
    artifacts_after_first = repo.list_artifacts(incident.id)
    events_after_first = repo.list_events(incident.id)
    second = EvidenceService(IncidentRepository(repo.path)).request_and_collect(incident.id, **kwargs)
    assert second.reused and second.evidence.id == first.evidence.id
    assert second.request.id == first.request.id
    assert repo.list_artifacts(incident.id) == artifacts_after_first
    assert repo.list_events(incident.id) == events_after_first
    assert first.request.status == "SATISFIED"
    assert first.evidence.request_id and first.evidence.collection_key
    assert first.evidence.content_hash
    assert first.evidence.source_capability == "get_asset_context"
    assert first.evidence.source_system == "operon.sqlite"
    assert first.evidence.schema_version == 1
    assert {event.event_type for event in events_after_first} >= {
        "EVIDENCE_REQUESTED", "EVIDENCE_COLLECTED", "EVIDENCE_REQUEST_RESOLVED",
    }


def test_unsupported_request_fails_without_fabricating_artifacts(repo):
    incident = repo.create_incident(("AC-COMP-01",), admission_key="unsupported")
    service = EvidenceService(repo)
    with pytest.raises(UnsupportedEvidenceCapability, match="unsupported evidence capability"):
        service.request_and_collect(
            incident.id, requested_by="critic", equipment_ids=("AC-COMP-01",),
            question="Invent a vibration spectrum", capability="query_anything",
            required_for="diagnosis", parameters={"fft": True},
        )
    assert repo.list_artifacts(incident.id) == []


def test_evidence_survives_repository_and_process_reconstruction(repo):
    incident, _ = repo.admit_signal(_signal())
    collection = EvidenceService(repo).request_and_collect(
        incident.id, requested_by="diagnostic", equipment_ids=("AC-COMP-01",),
        question="Get operating context", capability="get_operating_context",
        required_for="diagnosis", parameters={},
    )
    rebuilt = IncidentRepository(repo.path).get_artifact(incident.id, collection.evidence.id)
    assert rebuilt == collection.evidence
    code = (
        "from pathlib import Path; import sys; "
        "from core.reliability.repository import IncidentRepository; "
        "print(IncidentRepository(Path(sys.argv[1])).get_artifact(sys.argv[2],sys.argv[3]).id)"
    )
    process = subprocess.run(
        [sys.executable, "-c", code, str(repo.path), incident.id, collection.evidence.id],
        text=True, capture_output=True, check=True,
    )
    assert process.stdout.strip() == collection.evidence.id


def test_separate_incidents_cannot_mix_evidence(repo):
    first, _ = repo.admit_signal(_signal("AC-COMP-01"))
    second, _ = repo.admit_signal(_signal("HYD-PUMP-03"))
    one = EvidenceService(repo).request_and_collect(
        first.id, requested_by="diagnostic", equipment_ids=("AC-COMP-01",),
        question="Asset one", capability="get_asset_context", required_for="diagnosis",
    )
    two = EvidenceService(repo).request_and_collect(
        second.id, requested_by="diagnostic", equipment_ids=("HYD-PUMP-03",),
        question="Asset two", capability="get_asset_context", required_for="diagnosis",
    )
    assert one.evidence.incident_id != two.evidence.incident_id
    assert one.evidence.equipment_ids == ("AC-COMP-01",)
    assert two.evidence.equipment_ids == ("HYD-PUMP-03",)
    with pytest.raises(InvalidReference):
        repo.get_artifact(first.id, two.evidence.id)
