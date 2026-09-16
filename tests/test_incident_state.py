"""Durable state invariants, exercised against isolated on-disk SQLite databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import sqlite3
import subprocess
import sys

import pytest
from pydantic import ValidationError

from core import db
from core.reliability import models as m
from core.reliability.coordinator import IncidentCoordinator
from core.reliability.repository import (
    DuplicateRecord, IncidentRepository, InvalidReference, StaleRevision,
    content_hash, new_id, utcnow,
)
from core.reliability.signals import signal_evidence
from core.reliability.state import InvalidTransition, validate_transition
from core.seed_data import seed


@pytest.fixture
def repo(seeded_db):
    return IncidentRepository()


def signal(equipment_id="AC-COMP-01"):
    now = utcnow()
    return m.ModelSignal(
        id=new_id(), created_at=now, observed_at=now, equipment_id=equipment_id,
        risk_score=0.91, health_score=0.09, candidate_failure_mode="OSF",
        mode_distribution={"OSF": 0.7, "PWF": 0.3},
        attribution=(m.Attribution(feature="torque", label="Torque", value=62, contribution=0.3),),
        features={"torque": 62}, model_source="core.model.HealthModel",
        model_version="sha256:test-model", input_source="core.simulator.PlantSimulator",
        input_provenance="SIMULATED",
    )


def create(repo):
    return repo.create_incident(("AC-COMP-01",), admission_key="test-alert")


def test_create_fetch_and_restart_in_new_process(repo):
    incident, _ = repo.admit_signal(signal())
    assert repo.fetch_incident(incident.id) == incident
    assert IncidentRepository(repo.path).list_active_incidents() == [incident]
    # A separate interpreter proves this does not depend on module or object state.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from pathlib import Path; "
         "from core.reliability.repository import IncidentRepository; "
         "print(IncidentRepository(Path(sys.argv[1])).fetch_incident(sys.argv[2]).model_dump_json())",
         str(repo.path), incident.id], capture_output=True, text=True, check=True,
    )
    assert m.Incident.model_validate_json(result.stdout) == incident


def test_immutable_artifacts_and_defensive_payloads(repo):
    incident = create(repo)
    evidence = signal_evidence(signal(), incident.id)
    updated = repo.add_artifact(evidence, expected_revision=incident.revision)
    assert updated.revision == incident.revision + 1
    with pytest.raises(ValidationError):
        evidence.summary = "overwrite"
    evidence.payload["risk_score"] = 0.2
    stored = repo.get_artifact(incident.id, evidence.id)
    assert stored.payload["risk_score"] == 0.91
    with pytest.raises(DuplicateRecord):
        repo.add_artifact(stored, expected_revision=updated.revision)
    with db.get_conn(repo.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE incident_artifact SET body_json='{}'")
    assert repo.fetch_incident(incident.id) == updated


def test_lifecycle_revisions_ordered_events_and_terminal_admission(repo):
    incident = create(repo)
    phases = ["INVESTIGATING", "AWAITING_EVIDENCE", "INVESTIGATING", "DIAGNOSIS_VALIDATED",
              "PLANNING", "INTERVENTION_VALIDATED", "AWAITING_APPROVAL", "READY",
              "EXECUTING", "OBSERVING"]
    coordinator = IncidentCoordinator(repo)
    for phase in phases:
        previous = incident
        incident = coordinator.transition(incident.id, m.IncidentPhase(phase),
                                          expected_revision=incident.revision, reason="application test command")
        assert incident.revision == previous.revision + 1
    # Step 14: CLOSED is verified-outcome authority, never a graph-only application command.
    with pytest.raises(InvalidReference, match="verified outcome authority"):
        coordinator.transition(incident.id, m.IncidentPhase.CLOSED, expected_revision=incident.revision, reason="graph only")
    assert repo.fetch_incident(incident.id) == incident and repo.list_active_incidents() == [incident]
    incident = coordinator.transition(incident.id, m.IncidentPhase.CANCELLED,
                                      expected_revision=incident.revision, reason="application test command")
    assert repo.list_active_incidents() == []
    events = repo.list_events(incident.id)
    assert events[0].event_type == "INCIDENT_OPENED"
    assert events[-1].event_type == "PHASE_CHANGED" and events[-1].payload["to"] == "CANCELLED"
    assert not any(e.event_type == "INCIDENT_CLOSED" for e in events)
    assert [e.id for e in events] == sorted({e.id for e in events})
    assert repo.list_events(incident.id, after_id=events[-2].id) == events[-1:]
    assert create(repo).id != incident.id


@pytest.mark.parametrize("current,target", [
    ("OPEN", "EXECUTING"), ("OPEN", "CLOSED"), ("OPEN", "OPEN"),
    ("INVESTIGATING", "READY"), ("CLOSED", "OPEN"), ("CANCELLED", "INVESTIGATING"),
    ("EXECUTION_FAILED", "EXECUTING"),
])
def test_invalid_transitions_are_independently_rejected(current, target):
    with pytest.raises(InvalidTransition):
        validate_transition(m.IncidentPhase(current), m.IncidentPhase(target))


def test_invalid_and_stale_writes_leave_no_partial_state(repo):
    original = create(repo)
    with pytest.raises(InvalidTransition):
        repo.transition(original.id, m.IncidentPhase.READY, expected_revision=1, reason="invalid")
    incident = repo.transition(original.id, m.IncidentPhase.INVESTIGATING, expected_revision=1, reason="start")
    with pytest.raises(StaleRevision):
        repo.transition(incident.id, m.IncidentPhase.AWAITING_EVIDENCE, expected_revision=1, reason="late")
    with pytest.raises(StaleRevision):
        repo.add_artifact(signal_evidence(signal(), incident.id), expected_revision=1)
    assert repo.fetch_incident(incident.id) == incident
    assert len(repo.list_events(incident.id)) == 2
    assert repo.list_artifacts(incident.id) == []


def test_reference_scope_type_and_hash_checks_roll_back(repo):
    one = create(repo)
    two = repo.create_incident(("HYD-PUMP-03",), admission_key="second")
    evidence = signal_evidence(signal(), one.id)
    one = repo.add_artifact(evidence, expected_revision=one.revision)
    bad = signal_evidence(signal("HYD-PUMP-03"), two.id).model_copy(update={"derived_from_ids": (evidence.id,)})
    with pytest.raises(InvalidReference):
        repo.add_artifact(bad, expected_revision=two.revision)
    with pytest.raises(InvalidReference, match="scope"):
        repo.add_artifact(signal_evidence(signal(), two.id), expected_revision=two.revision)
    with pytest.raises(InvalidReference, match="hash"):
        repo.add_artifact(evidence.model_copy(update={"id": new_id(), "content_hash": "wrong"}),
                          expected_revision=one.revision)
    diagnosis = m.Diagnosis(id=new_id(), created_at=utcnow(), incident_id=one.id,
                            equipment_ids=one.equipment_ids, hypothesis_ids=(evidence.id,),
                            conclusion="bad reference type", evidence_ids=(evidence.id,), confidence=0.5)
    with pytest.raises(InvalidReference, match="Hypothesis"):
        repo.add_artifact(diagnosis, expected_revision=one.revision)
    assert repo.fetch_incident(two.id) == two
    assert repo.list_artifacts(two.id) == []


def test_migrations_twice_preserve_existing_database_and_incidents(repo):
    incident = create(repo)
    with db.get_conn(repo.path) as conn:
        conn.execute("INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob) "
                     "VALUES ('AC-COMP-01','preserved',0.8,0.2)")
    db.init_schema(repo.path)
    db.init_schema(repo.path)
    seed()
    assert repo.fetch_incident(incident.id) == incident
    with db.get_conn(repo.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM health_score WHERE scored_at='preserved'").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migrate_pre_operon_schema_without_replacing_it(tmp_path):
    path = tmp_path / "old.db"
    with db.get_conn(path) as conn:
        conn.executescript(db.SCHEMA)
        conn.execute("INSERT INTO plant VALUES ('existing','Existing plant','UTC')")
    db.init_schema(path)
    db.init_schema(path)
    with db.get_conn(path) as conn:
        assert conn.execute("SELECT plant_name FROM plant").fetchone()[0] == "Existing plant"
        assert [row[0] for row in conn.execute("SELECT version FROM schema_migration ORDER BY version")] == [
            "001_operon", "002_governed_execution", "003_execution_claim_adapter", "004_authoritative_promotion",
            "005_reliability_lifecycle", "006_dependency_scoped_freshness", "007_outcome_verification",
            "008_prism_runtime"]


def test_concurrent_duplicate_admission_and_distinct_machines(repo):
    sample = signal()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: IncidentRepository(repo.path).admit_signal(sample), range(8)))
    assert sum(created for _, created in results) == 1
    assert len({incident.id for incident, _ in results}) == 1
    first = results[0][0]
    assert len(repo.list_artifacts(first.id)) == 1
    assert len(repo.list_events(first.id)) == 3
    second, created = repo.admit_signal(signal("HYD-PUMP-03"))
    assert created and second.id != first.id
    assert len(repo.list_active_incidents()) == 2
    coordinator = IncidentCoordinator(IncidentRepository(repo.path))
    assert len(coordinator.recover()) == 2


def test_signal_provenance_and_candidate_mode_preserved(repo):
    original = signal()
    incident, _ = repo.admit_signal(original)
    evidence = repo.get_artifact(incident.id, incident.signal_evidence_ids[0])
    assert m.ModelSignal.model_validate(evidence.payload) == original
    assert evidence.source_version == original.model_version
    assert evidence.source_uri == original.model_source
    assert evidence.provenance == "DERIVED"
    assert evidence.payload["input_provenance"] == "SIMULATED"
    assert evidence.content_hash == content_hash(evidence.payload)
    assert incident.phase == m.IncidentPhase.OPEN


def test_escalation_blocks_duplicate_admission_until_cancelled(repo):
    incident, _ = repo.admit_signal(signal())
    incident = repo.transition(incident.id, m.IncidentPhase.ESCALATED,
                               expected_revision=incident.revision, reason="missing evidence")
    assert repo.list_events(incident.id)[-1].event_type == "INCIDENT_ESCALATED"
    assert repo.admit_signal(signal())[0].id == incident.id
    repo.transition(incident.id, m.IncidentPhase.CANCELLED, expected_revision=incident.revision, reason="cancel")
    assert repo.admit_signal(signal())[0].id != incident.id


def test_events_are_append_only_revision_checked_and_validated(repo):
    incident = create(repo)
    event = repo.append_event(incident.id, "INCIDENT_UPDATED", {"note": "application activity"}, expected_revision=1)
    assert event.revision == 2
    with pytest.raises(StaleRevision):
        repo.append_event(incident.id, "INCIDENT_UPDATED", {}, expected_revision=1)
    with pytest.raises(ValueError):
        repo.append_event(incident.id, "INCIDENT_CLOSED", {}, expected_revision=2)
    with db.get_conn(repo.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE incident_event SET event_type='INCIDENT_CLOSED'")


def test_timestamps_schema_and_scores_are_validated():
    payload = signal().model_dump()
    for update in ({"observed_at": datetime(2026, 1, 1)}, {"risk_score": 1.1},
                   {"schema_version": 2}, {"unexpected": True}, {"id": ""}):
        with pytest.raises(ValidationError):
            m.ModelSignal.model_validate({**payload, **update})


@pytest.mark.parametrize("reset", [db.reset_transactional, lambda: seed(reset=True)])
def test_explicit_demo_reset_clears_incidents_but_preserves_migration(repo, reset):
    create(repo)
    reset()
    assert repo.list_active_incidents() == []
    with db.get_conn(repo.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 8


def test_validation_approval_and_execution_records_remain_distinct(repo):
    incident, _ = repo.admit_signal(signal())
    evidence_id = incident.signal_evidence_ids[0]

    def persist(artifact):
        nonlocal incident
        incident = repo.add_artifact(artifact, expected_revision=incident.revision)
        return artifact

    def identity():
        return dict(id=new_id(), incident_id=incident.id, created_at=utcnow())

    hypothesis = persist(m.Hypothesis(**identity(), equipment_ids=incident.equipment_ids,
                                      mechanism="excess load", supporting_evidence_ids=(evidence_id,),
                                      confidence=0.6, confidence_basis="test evidence", falsification_tests=("inspect load",)))
    diagnosis = persist(m.Diagnosis(**identity(), equipment_ids=incident.equipment_ids,
                                    hypothesis_ids=(hypothesis.id,), evidence_ids=(evidence_id,),
                                    conclusion="candidate overload", confidence=0.6))
    verdict = m.ValidationVerdict(**identity(), target_kind="diagnosis", target_id=diagnosis.id,
                                  target_hash="incorrect", input_revision=incident.revision,
                                  decision="NEEDS_EVIDENCE", validator_run_id="critic-test")
    with pytest.raises(InvalidReference, match="hash"):
        persist(verdict)
    persist(verdict.model_copy(update={"target_hash": content_hash(diagnosis.model_dump(mode="json"))}))
    intervention = persist(m.Intervention(**identity(), diagnosis_id=diagnosis.id, revision=1,
        steps=(m.InterventionStep(id=new_id(), created_at=utcnow(), capability="inspect",
                                  equipment_ids=incident.equipment_ids, parameters={}),),
        risk="LOW", estimated_cost=10, estimated_downtime_minutes=5,
        estimated_avoided_loss=0, business_assumption_version="test-1"))
    intervention_hash = content_hash(intervention.model_dump(mode="json"))
    requirement = persist(m.ApprovalRequirement(**identity(), intervention_id=intervention.id,
        intervention_hash=intervention_hash, policy_version="test-1", mode="HUMAN",
        required_roles=("operator",), minimum_distinct_approvers=1))
    decision = m.ApprovalDecision(**identity(), requirement_id=requirement.id,
        intervention_id=intervention.id, intervention_hash=intervention_hash,
        actor_id="test-operator", actor_role="operator", decision="APPROVE", rationale="test ledger only",
        context_revision=incident.revision)
    incident = repo.add_approval_decision(decision, expected_revision=incident.revision)
    assert repo.get_approval_decision(incident.id, decision.id) == decision
    receipt = m.ExecutionReceipt(**identity(), intervention_id=intervention.id,
        operation_key="unique-operation", adapter="test", request_hash="test-request", status="UNKNOWN")
    incident = repo.add_execution_receipt(receipt, expected_revision=incident.revision)
    assert repo.get_execution_receipt(incident.id, receipt.id) == receipt
    with pytest.raises(DuplicateRecord):
        repo.add_execution_receipt(receipt.model_copy(update={"id": new_id()}), expected_revision=incident.revision)
    assert repo.fetch_incident(incident.id) == incident
    # Persisting a report/decision/receipt never advances the authoritative phase.
    assert incident.phase == m.IncidentPhase.OPEN


def test_migration_failure_rolls_back_schema_and_version(tmp_path, monkeypatch):
    from core import migrations
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "001_bad.sql").write_text(
        "CREATE TABLE must_rollback (id TEXT);\nINSERT INTO table_that_does_not_exist VALUES (1);\n")
    monkeypatch.setattr(migrations, "__file__", str(directory / "__init__.py"))
    with db.get_conn(tmp_path / "failed.db") as conn:
        with pytest.raises(sqlite3.OperationalError):
            migrations.apply_migrations(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_racing_revisions_allow_only_one_writer(repo):
    incident = create(repo)

    def transition(_):
        try:
            return IncidentRepository(repo.path).transition(
                incident.id, m.IncidentPhase.INVESTIGATING, expected_revision=incident.revision, reason="race")
        except StaleRevision:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(transition, range(2)))
    assert sum(result is not None for result in results) == 1
    assert repo.fetch_incident(incident.id).revision == 2
    assert len(repo.list_events(incident.id)) == 2


def test_signal_evidence_failure_rolls_back_entire_admission(repo, monkeypatch):
    from core.reliability import signals
    original = signals.signal_evidence
    monkeypatch.setattr(signals, "signal_evidence", lambda signal, incident_id:
                        original(signal, incident_id).model_copy(update={"content_hash": "bad"}))
    with pytest.raises(InvalidReference):
        repo.admit_signal(signal())
    assert repo.list_active_incidents() == []
    with db.get_conn(repo.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM incident_event").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM incident_artifact").fetchone()[0] == 0
