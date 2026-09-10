"""Step 13C adversarial tests: dependency-scoped source freshness.

Every scenario runs against the real repository, evidence service, promotion boundary
and lifecycle. Only the model invocation seam is scripted. "Machine A" is the
incident asset AC-COMP-01; "Machine B" is CNC-MILL-07.
"""
from __future__ import annotations

from datetime import timedelta
import json

import pytest
from pydantic import ValidationError

from core import db
from core.agents.contracts import SupervisorResult
from core.reliability import models as m
from core.reliability.freshness import SourceReads, closure, derived_manifest, observation_manifest, revalidate
from core.reliability.investigation import DeterministicInvestigator
from core.reliability.lifecycle import LifecycleService
from core.reliability.promotion import CONFIRM_MECHANISM, PromotionRefused
from core.reliability.repository import IncidentRepository, InvalidReference, StaleRevision, content_hash, new_id, utcnow
from core.reliability.signals import signal_evidence
from tests.test_incident_state import signal
from tests.test_promotion import ASSET, Environment, result_payload, revision, state

MACHINE_B = "CNC-MILL-07"


@pytest.fixture
def env(seeded_db):
    return Environment()


def write_readings(path, asset_id, values, *, start, sensor_type="TORQUE", step=timedelta(seconds=1)):
    """Persist readings for one sensor at full-precision aware timestamps."""
    with db.get_conn(path) as conn:
        for offset, value in enumerate(values):
            conn.execute("INSERT INTO sensor_reading VALUES (?,?,?,?)",
                         (f"{asset_id}-{sensor_type}", (start + offset * step).isoformat(), value, "GOOD"))


def sql(path, statement, *params):
    with db.get_conn(path) as conn:
        conn.execute(statement, params)


def collect(env, capability, parameters=None, *, question=None, requested_by="diagnostic"):
    return env.evidence_service.request_and_collect(
        env.incident_id, requested_by=requested_by, equipment_ids=(ASSET,),
        question=question or f"Collect {capability}", capability=capability, required_for="diagnosis",
        parameters=parameters or {})


def fresh(env, evidence):
    with db.get_conn(env.repo.path) as conn:
        return not revalidate(conn, evidence.source_dependencies)


def bounded_window(env, *, values=(10.0, 12.0, 14.0, 16.0)):
    """Historical telemetry evidence for Machine A: window [start, end] frozen by the application."""
    start = utcnow() - timedelta(minutes=10)
    write_readings(env.repo.path, ASSET, values, start=start)
    end = start + timedelta(seconds=len(values))  # strictly after the last persisted sample
    collection = collect(env, "get_telemetry_window", {"sensor_type": "TORQUE", "start_at": start, "end_at": end, "sample_limit": 60})
    assert collection.evidence.quality == "GOOD" and not collection.reused
    return collection.evidence, start, end


def domains(manifest):
    return sorted(item.domain for item in manifest.dependencies)


# ------------------------------------------------------- unrelated source changes

def test_machine_a_evidence_stays_fresh_when_machine_b_receives_telemetry(env):
    evidence, start, end = bounded_window(env)
    write_readings(env.repo.path, MACHINE_B, (1.0, 2.0, 3.0), start=start)
    write_readings(env.repo.path, MACHINE_B, (4.0,), start=utcnow())
    assert fresh(env, evidence)
    again = collect(env, "get_telemetry_window", {"sensor_type": "TORQUE", "start_at": start, "end_at": end, "sample_limit": 60})
    assert again.reused and again.evidence.id == evidence.id


def test_machine_a_run_is_not_stale_when_machine_b_streams_during_reasoning(env):
    telemetry, start, _ = bounded_window(env)
    env.confirm()
    snapshot = env.start(evidence_ids=(*env.evidence_ids(), telemetry.id))
    write_readings(env.repo.path, MACHINE_B, (5.0, 6.0), start=utcnow())
    sql(env.repo.path, "INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) VALUES (?,?,?,?,?)",
        MACHINE_B, utcnow().isoformat(), 0.4, 0.6, "TWF")
    report = env.complete(snapshot)
    assert report.stale_reasons == ()
    assert env.promote_diagnosis(report).target_id == env.repo.fetch_incident(env.incident_id).current_diagnosis_id


def test_other_incident_revision_change_does_not_stale_machine_a(env):
    other = env.repo.create_incident(("HYD-PUMP-03",), admission_key="other-pump")
    env.repo.create_incident((ASSET,), admission_key="previous-compressor")
    related = collect(env, "get_related_incidents", {"limit": 20})
    assert related.evidence.quality == "GOOD" and domains(related.evidence.source_dependencies) == ["related_incidents"]
    env.confirm()
    snapshot = env.start(evidence_ids=(*env.evidence_ids(), related.evidence.id))
    env.repo.append_event(other.id, "INCIDENT_UPDATED", {"changed": True}, expected_revision=other.revision)
    env.repo.transition(other.id, m.IncidentPhase.INVESTIGATING, expected_revision=other.revision + 1, reason="unrelated")
    write_readings(env.repo.path, "HYD-PUMP-03", (1.0,), start=utcnow())
    report = env.complete(snapshot)
    assert report.stale_reasons == ()
    env.promote_diagnosis(report)
    # A same-asset incident changing is a real dependency of same-asset incident history.
    reopened = env.repo.create_incident((ASSET,), admission_key="another-compressor-incident")
    assert not fresh(env, related.evidence)
    assert reopened.id != env.incident_id


@pytest.mark.parametrize("statement", [
    "UPDATE technician SET full_name='Renamed', skills='NONE', available=0 WHERE technician_id='TECH-204'",
    "UPDATE part SET on_hand_qty=on_hand_qty+5",
    "INSERT INTO labor_booking (technician_id,window_label,status) VALUES ('TECH-201','2030-01-01T00:00:00+00:00/2030-01-01T02:00:00+00:00','BOOKED')",
    "INSERT INTO plant VALUES ('US99','Other plant','UTC')",
    "UPDATE failure_mode SET description='rewritten'",
])
def test_unrelated_resource_changes_do_not_stale_telemetry_evidence(env, statement):
    evidence, _, _ = bounded_window(env)
    sql(env.repo.path, statement)
    assert fresh(env, evidence)
    assert domains(evidence.source_dependencies) == ["sensor_inventory", "telemetry_window"]


# ------------------------------------------------------- telemetry window semantics

def test_new_sample_strictly_after_frozen_window_does_not_stale_historical_evidence(env):
    evidence, start, end = bounded_window(env)
    write_readings(env.repo.path, ASSET, (99.0,), start=end + timedelta(seconds=5))
    write_readings(env.repo.path, ASSET, (98.0,), start=utcnow())
    assert fresh(env, evidence)
    window = next(item for item in evidence.source_dependencies.dependencies if item.domain == "telemetry_window")
    assert window.scope == {"sensor_id": f"{ASSET}-TORQUE"}
    assert window.parameters["end_at"] == end.isoformat() and window.parameters["sample_limit"] == 60


@pytest.mark.parametrize("mutation", ["insert_inside", "modify_inside", "delete_inside", "insert_before_start_inside_limit"])
def test_mutations_inside_the_queried_window_stale_telemetry_evidence(env, mutation):
    evidence, start, end = bounded_window(env)
    sensor = f"{ASSET}-TORQUE"
    if mutation == "insert_inside":
        write_readings(env.repo.path, ASSET, (50.0,), start=start + timedelta(seconds=1, milliseconds=500))
    elif mutation == "modify_inside":
        sql(env.repo.path, "UPDATE sensor_reading SET value_eu=value_eu+1 WHERE sensor_id=? AND ts>=? AND ts<=?", sensor, start.isoformat(), end.isoformat())
    elif mutation == "delete_inside":
        sql(env.repo.path, "DELETE FROM sensor_reading WHERE sensor_id=? AND ts=?", sensor, (start + timedelta(seconds=2)).isoformat())
    else:
        write_readings(env.repo.path, ASSET, (0.5,), start=start)  # duplicate timestamp at window start
    assert not fresh(env, evidence)
    with db.get_conn(env.repo.path) as conn:
        changes = revalidate(conn, evidence.source_dependencies)
    assert [item.dependency.domain for item in changes] == ["telemetry_window"]


def test_sensor_configuration_change_stales_telemetry_evidence(env):
    evidence, _, _ = bounded_window(env)
    sql(env.repo.path, "UPDATE sensor SET unit_eu='kNm' WHERE sensor_id=?", f"{ASSET}-TORQUE")
    with db.get_conn(env.repo.path) as conn:
        changes = revalidate(conn, evidence.source_dependencies)
    assert [item.dependency.domain for item in changes] == ["sensor_inventory"]
    # Another asset's sensor configuration is outside the queried scope.
    sql(env.repo.path, "UPDATE sensor SET unit_eu='kNm' WHERE sensor_id=?", f"{MACHINE_B}-TORQUE")
    with db.get_conn(env.repo.path) as conn:
        assert len(revalidate(conn, evidence.source_dependencies)) == 1


def test_open_ended_latest_reads_are_modelled_honestly_and_pinned_by_the_application(env):
    """Without a boundary, "latest N" and "latest reading" legitimately change with new
    same-asset samples; the deterministic baseline pins the application clock instead."""
    write_readings(env.repo.path, ASSET, (1.0, 2.0), start=utcnow() - timedelta(minutes=1))
    open_ended = collect(env, "get_telemetry_window", {"sensor_type": "TORQUE", "sample_limit": 60}).evidence
    context = collect(env, "get_asset_context").evidence
    window = next(item for item in open_ended.source_dependencies.dependencies if item.domain == "telemetry_window")
    assert window.parameters["end_at"] is None
    assert {item.domain for item in context.source_dependencies.dependencies} == {
        "asset_registry", "health_score_latest", "sensor_inventory", "telemetry_latest"}
    write_readings(env.repo.path, ASSET, (3.0,), start=utcnow())
    assert not fresh(env, open_ended) and not fresh(env, context)
    # Deterministic baseline reads carry an application-pinned boundary and stay reproducible.
    fresh_incident = env.repo.create_incident((MACHINE_B,), admission_key="baseline-b")
    write_readings(env.repo.path, MACHINE_B, (1.0, 2.0), start=utcnow() - timedelta(minutes=1))
    result = DeterministicInvestigator(env.repo, env.evidence_service).investigate(fresh_incident.id)
    baseline = [env.repo.get_artifact(fresh_incident.id, key) for key in result.evidence_ids]
    pinned = {item.source_capability: item for item in baseline if isinstance(item, m.Evidence)}
    assert pinned["get_telemetry_window"].payload["requested_end"] is not None
    assert pinned["get_asset_context"].payload["as_of"] is not None
    write_readings(env.repo.path, MACHINE_B, (3.0,), start=utcnow())
    sql(env.repo.path, "INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) VALUES (?,?,?,?,?)",
        MACHINE_B, utcnow().isoformat(), 0.4, 0.6, "TWF")
    for capability in ("get_telemetry_window", "get_asset_context", "get_operating_context"):
        assert fresh(env, pinned[capability]), capability


# ------------------------------------------------------- capability isolation

def test_new_telemetry_does_not_stale_maintenance_history(env):
    history = env.repo.get_artifact(env.incident_id, env.history_id)
    assert domains(history.source_dependencies) == ["maintenance_history"]
    write_readings(env.repo.path, ASSET, (1.0, 2.0, 3.0), start=utcnow())
    sql(env.repo.path, "INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) VALUES (?,?,?,?,?)",
        ASSET, utcnow().isoformat(), 0.4, 0.6, "OSF")
    assert fresh(env, history)


@pytest.mark.parametrize("statement", [
    "UPDATE maintenance_event SET note=note || ' amended' WHERE equipment_id='AC-COMP-01'",
    "INSERT INTO work_order (wo_number,equipment_id,status,priority,created_at,detail) VALUES ('WO-NEW','AC-COMP-01','OPEN','HIGH','2026-09-01T00:00:00+00:00','new')",
    "UPDATE work_order SET status='CANCELLED' WHERE equipment_id='AC-COMP-01'",
    "UPDATE technician SET full_name='Renamed' WHERE technician_id=(SELECT technician_id FROM work_order WHERE equipment_id='AC-COMP-01')",
    "INSERT INTO part_reservation (wo_id,part_id,qty,status) SELECT wo_id,'PRT-BRG',1,'RESERVED' FROM work_order WHERE equipment_id='AC-COMP-01'",
])
def test_maintenance_changes_for_the_asset_stale_maintenance_history(env, statement):
    history = env.repo.get_artifact(env.incident_id, env.history_id)
    sql(env.repo.path, statement)
    assert not fresh(env, history)


@pytest.mark.parametrize("statement", [
    "INSERT INTO work_order (wo_number,equipment_id,status,priority,created_at,detail) VALUES ('WO-B','CNC-MILL-07','OPEN','HIGH','2026-09-01T00:00:00+00:00','other asset')",
    "UPDATE technician SET full_name='Renamed' WHERE technician_id NOT IN (SELECT technician_id FROM work_order WHERE equipment_id='AC-COMP-01')",
    "INSERT INTO part_reservation (wo_id,part_id,qty,status) VALUES (NULL,'PRT-BRG',1,'RESERVED')",
    "UPDATE equipment SET criticality='LOW' WHERE equipment_id='AC-COMP-01'",
])
def test_changes_outside_the_queried_scope_do_not_stale_maintenance_history(env, statement):
    history = env.repo.get_artifact(env.incident_id, env.history_id)
    sql(env.repo.path, statement)
    assert fresh(env, history)


# ------------------------------------------------------- evidence reuse

def test_exact_unchanged_request_reuses_valid_evidence(env):
    first = collect(env, "get_asset_context")
    before = state(env)
    second = collect(env, "get_asset_context")
    assert second.reused and second.evidence.id == first.evidence.id and second.request.id == first.request.id
    assert state(env) == before
    # A different question is a different durable request even with identical parameters.
    third = collect(env, "get_asset_context", question="A different question")
    assert not third.reused and third.evidence.id != first.evidence.id


def test_stale_dependency_creates_superseding_generation_and_preserves_history(env):
    original = env.repo.get_artifact(env.incident_id, env.history_id)
    requests_before = [a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.EvidenceRequest)]
    with db.get_conn(env.repo.path) as conn:
        stored_before = conn.execute("SELECT artifact_id,content_hash,body_json FROM incident_artifact WHERE incident_id=? ORDER BY rowid",
                                     (env.incident_id,)).fetchall()
    sql(env.repo.path, "UPDATE maintenance_event SET note=note || ' amended' WHERE equipment_id='AC-COMP-01'")
    fresh_collection = collect(env, "get_maintenance_history", question="Read recorded service history")
    assert not fresh_collection.reused
    assert fresh_collection.evidence.supersedes_id == original.id
    assert fresh_collection.request.supersedes_id is not None
    assert fresh_collection.evidence.source_dependencies != original.source_dependencies
    assert fresh(env, fresh_collection.evidence) and not fresh(env, original)
    with db.get_conn(env.repo.path) as conn:
        stored_after = conn.execute("SELECT artifact_id,content_hash,body_json FROM incident_artifact WHERE incident_id=? ORDER BY rowid",
                                    (env.incident_id,)).fetchall()
    assert [tuple(row) for row in stored_after[:len(stored_before)]] == [tuple(row) for row in stored_before]
    assert env.repo.get_artifact(env.incident_id, original.id) == original
    superseded_requests = [a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.EvidenceRequest) and a.id in {r.id for r in requests_before}]
    assert superseded_requests == requests_before


def test_reuse_requires_current_unsuperseded_artifact_and_validated_manifest(env):
    original = env.repo.get_artifact(env.incident_id, env.history_id)
    env.repo.add_artifact(original.model_copy(update={"id": new_id(), "supersedes_id": original.id}), expected_revision=revision(env))
    again = collect(env, "get_maintenance_history", question="Read recorded service history")
    assert not again.reused and again.evidence.supersedes_id == original.id


# ------------------------------------------------------- run snapshots

def test_snapshot_freezes_exact_dependency_closure_of_the_packet(env):
    telemetry, _, _ = bounded_window(env)
    env.confirm()
    snapshot = env.start(evidence_ids=(*env.evidence_ids(), telemetry.id))
    manifest = snapshot.source_dependency_manifest
    assert manifest is not None and manifest.basis == "CLOSURE" and snapshot.source_state_hash is None
    history = env.repo.get_artifact(env.incident_id, env.history_id)
    expected = closure([history.source_dependencies, telemetry.source_dependencies])
    assert manifest == expected
    assert {item.identity for item in manifest.dependencies} == {
        item.identity for item in (*history.source_dependencies.dependencies, *telemetry.source_dependencies.dependencies)}
    # Observations contribute no mutable dependencies; the confirmation's support is in the closure via provenance.
    assert env.confirmation.source_dependencies == observation_manifest()
    assert env.repo.get_artifact(env.incident_id, env.signal_id).source_dependencies == observation_manifest()
    # Every frozen dependency is inspectable and recomputable from local data.
    with db.get_conn(env.repo.path) as conn:
        reads = SourceReads(conn)
        for dependency in manifest.dependencies:
            getattr(reads, dependency.domain)(**dependency.scope, **dependency.parameters)
    assert {item.identity: item.fingerprint for item in reads.dependencies} == {item.identity: item.fingerprint for item in manifest.dependencies}


def test_actual_dependency_change_during_reasoning_marks_report_stale_with_precise_reason(env):
    telemetry, start, end = bounded_window(env)
    env.confirm()
    snapshot = env.start(evidence_ids=(*env.evidence_ids(), telemetry.id))
    write_readings(env.repo.path, ASSET, (77.0,), start=start + timedelta(milliseconds=500))
    report = env.complete(snapshot)
    assert report.stale_reasons == (f"SOURCE_DEPENDENCY_CHANGED:telemetry_window[end_at={end.isoformat()},sample_limit=60,"
                                    f"sensor_id={ASSET}-TORQUE,start_at={start.isoformat()}]",)
    with pytest.raises(PromotionRefused, match="stale report"):
        env.promote_diagnosis(report)


def test_unrelated_streaming_telemetry_during_reasoning_does_not_stale_report(env):
    telemetry, start, end = bounded_window(env)
    env.confirm()
    snapshot = env.start(evidence_ids=(*env.evidence_ids(), telemetry.id))
    write_readings(env.repo.path, ASSET, (20.0, 21.0, 22.0), start=end + timedelta(seconds=1))
    write_readings(env.repo.path, MACHINE_B, (1.0, 2.0), start=start)
    sql(env.repo.path, "INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) VALUES (?,?,?,?,?)",
        ASSET, utcnow().isoformat(), 0.3, 0.7, "OSF")
    report = env.complete(snapshot)
    assert report.stale_reasons == ()


def test_new_evidence_during_reasoning_never_enters_the_frozen_packet(env):
    env.confirm()
    snapshot = env.start()
    during = collect(env, "get_asset_context")
    payload = result_payload(env, snapshot)
    payload["evidence_used"] = [*payload["evidence_used"], during.evidence.id]
    payload["decision"]["evidence_used"] = payload["evidence_used"]
    report = env.complete(snapshot, payload)
    assert "REVISION_CHANGED_DURING_RUN" in report.stale_reasons
    assert during.evidence.id not in snapshot.evidence_manifest and during.evidence.id in report.evidence_manifest
    assert snapshot.source_dependency_manifest == env.repo.get_artifact(env.incident_id, snapshot.id).source_dependency_manifest
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(report)


# ------------------------------------------------------- promotion

@pytest.mark.parametrize("stage", ["diagnosis", "intervention"])
def test_promotion_succeeds_after_unrelated_source_changes(env, stage):
    if stage == "diagnosis":
        telemetry, _, _ = bounded_window(env)
        env.confirm()
        report = env.complete(env.start(evidence_ids=(*env.evidence_ids(), telemetry.id)))
        promote = lambda: env.promote_diagnosis(report)
    else:
        draft = env.draft()
        report = env.complete(env.start(draft), draft=draft)
        promote = lambda: env.promote_intervention(report, draft)
    write_readings(env.repo.path, ASSET, (30.0, 31.0), start=utcnow())
    write_readings(env.repo.path, MACHINE_B, (1.0,), start=utcnow())
    sql(env.repo.path, "UPDATE technician SET full_name='Renamed' WHERE technician_id='TECH-204'")
    sql(env.repo.path, "INSERT INTO labor_booking (technician_id,window_label,status) VALUES ('TECH-204','shift','BOOKED')")
    other = env.repo.create_incident(("HYD-PUMP-03",), admission_key="other-pump")
    env.repo.append_event(other.id, "INCIDENT_UPDATED", {"changed": True}, expected_revision=other.revision)
    promotion = promote()
    assert env.repo.get_artifact(env.incident_id, promotion.target_id)


def test_promotion_refuses_when_a_frozen_dependency_changed_after_completion(env):
    telemetry, start, _ = bounded_window(env)
    env.confirm()
    report = env.complete(env.start(evidence_ids=(*env.evidence_ids(), telemetry.id)))
    write_readings(env.repo.path, ASSET, (77.0,), start=start + timedelta(milliseconds=500))
    before = state(env)
    with pytest.raises(PromotionRefused, match="frozen source dependency changed: telemetry_window") as refused:
        env.promote_diagnosis(report)
    assert refused.value.disposition == "NEEDS_EVIDENCE" and state(env) == before
    assert LifecycleService(env.repo)._refusal_is_stale(env.incident_id, report)


@pytest.mark.parametrize("stage", ["diagnosis", "intervention"])
def test_evidence_and_input_artifact_manifests_are_validated_independently(env, stage):
    """Dependency revalidation passes here; the exact evidence/input artifact manifests still gate."""
    if stage == "diagnosis":
        env.confirm()
        snapshot = env.start()
        report = env.complete(snapshot)
        field, key, message = "evidence_manifest", env.history_id, "evidence manifest differs"
    else:
        draft = env.draft()
        snapshot = env.start(draft)
        report = env.complete(snapshot, draft=draft)
        field, key, message = "input_artifact_manifest", draft.id, "artifact manifest mismatch"
    body = json.loads(snapshot.model_dump_json())
    body[field][key] = "sha256:tampered"
    with db.get_conn(env.repo.path) as conn:
        conn.execute("DROP TRIGGER immutable_incident_artifact")
        conn.execute("UPDATE incident_artifact SET body_json=? WHERE artifact_id=?", (json.dumps(body), snapshot.id))
    with db.get_conn(env.repo.path) as conn:
        assert revalidate(conn, env.repo.get_artifact(env.incident_id, snapshot.id).source_dependency_manifest) == ()
    with pytest.raises(PromotionRefused, match=message):
        env.promote_diagnosis(report) if stage == "diagnosis" else env.promote_intervention(report, draft)


def test_input_artifact_manifest_detects_superseded_draft(seeded_db):
    env = Environment()
    draft = env.draft()
    report = env.complete(env.start(draft), draft=draft)
    env.repo.add_artifact(draft.model_copy(update={"id": new_id(), "supersedes_id": draft.id, "revision": draft.revision + 1}),
                          expected_revision=revision(env))
    with pytest.raises(PromotionRefused):
        env.promote_intervention(report, draft)


# ------------------------------------------------------- derived evidence

def test_stale_parent_dependency_invalidates_derived_closure(env):
    env.confirm()
    document_payload = {"derived_summary": "model reasoning over history"}
    derived = env.repo.get_artifact(env.incident_id, env.history_id).model_copy(update={
        "id": new_id(), "kind": "document", "source_capability": "model_reasoning", "payload": document_payload,
        "content_hash": content_hash(document_payload), "derived_from_ids": (env.history_id,), "request_id": None,
        "provenance": "DERIVED", "source_dependencies": derived_manifest()})
    env.repo.add_artifact(derived, expected_revision=revision(env))
    lifecycle = LifecycleService(env.repo)
    assert {env.confirmation.id, derived.id} <= set(lifecycle.current_evidence_ids(env.incident_id, ASSET))
    sql(env.repo.path, "UPDATE maintenance_event SET note=note || ' amended' WHERE equipment_id='AC-COMP-01'")
    with pytest.raises(PromotionRefused, match="maintenance_history") as refused:
        env.start(evidence_ids=(env.signal_id, derived.id))
    assert refused.value.disposition == "NEEDS_EVIDENCE"
    with pytest.raises(PromotionRefused, match="maintenance_history"):
        env.start(evidence_ids=(env.signal_id, env.confirmation.id))
    current = lifecycle.current_evidence_ids(env.incident_id, ASSET)
    assert env.signal_id in current and not {env.history_id, env.confirmation.id, derived.id} & set(current)


# ------------------------------------------------------- trusted confirmations

def test_trusted_confirmation_is_an_immutable_observation_as_telemetry_advances(env):
    telemetry, _, end = bounded_window(env)
    confirmation = env.confirm(supporting_evidence_ids=(env.history_id, telemetry.id))
    assert confirmation.source_dependencies == observation_manifest() and confirmation.source_state_hash is None
    write_readings(env.repo.path, ASSET, (40.0, 41.0), start=end + timedelta(seconds=2))
    write_readings(env.repo.path, ASSET, (42.0,), start=utcnow())
    assert fresh(env, confirmation) and env.repo.get_artifact(env.incident_id, confirmation.id) == confirmation
    report = env.complete(env.start(evidence_ids=(*env.evidence_ids(), telemetry.id)))
    assert report.stale_reasons == ()
    env.promote_diagnosis(report)


def test_confirmation_support_must_still_satisfy_freshness_at_promotion(env):
    telemetry, start, _ = bounded_window(env)
    env.confirm(supporting_evidence_ids=(env.history_id, telemetry.id))
    report = env.complete(env.start(evidence_ids=(*env.evidence_ids(), telemetry.id)))
    write_readings(env.repo.path, ASSET, (77.0,), start=start + timedelta(milliseconds=500))
    with pytest.raises(PromotionRefused, match="telemetry_window") as refused:
        env.promote_diagnosis(report)
    assert refused.value.disposition == "NEEDS_EVIDENCE"
    resource = env.resources()
    assert resource.source_dependencies == observation_manifest()


def test_resource_confirmation_stays_an_observation_while_binding_rechecks_actual_stock(seeded_db):
    env = Environment()
    promotion, report = env.diagnosis()
    sql(env.repo.path, "UPDATE part SET on_hand_qty=0 WHERE part_id='PRT-BRG'")
    assert fresh(env, env.resource)  # the dated attestation is not rewritten by stock changes
    with pytest.raises(PromotionRefused, match="insufficient parts"):
        env.service.create_draft(env.incident_id, expected_revision=revision(env), **env.binding_fields(promotion, report))


# ------------------------------------------------------- compatibility

def legacy_evidence_body(env, evidence, *, source_state_hash="sha256:legacy"):
    body = json.loads(evidence.model_dump_json())
    body.pop("source_dependencies", None)
    body["id"], body["source_state_hash"] = new_id(), source_state_hash
    return body


def insert_legacy(env, kind, body):
    with db.get_conn(env.repo.path) as conn:
        conn.execute("INSERT INTO incident_artifact VALUES (?,?,?,?,?,?,?)",
                     (body["id"], env.incident_id, kind, 1, body["created_at"], content_hash(body), json.dumps(body)))
    incident = env.repo.fetch_incident(env.incident_id)
    with env.repo._write() as conn:
        env.repo._update(conn, incident, artifact_ids=(*incident.artifact_ids, body["id"]))
    return body["id"]


def test_legacy_artifacts_remain_loadable_with_unchanged_hashes(env):
    history = env.repo.get_artifact(env.incident_id, env.history_id)
    body = legacy_evidence_body(env, history)
    legacy_id = insert_legacy(env, "Evidence", body)
    loaded = env.repo.get_artifact(env.incident_id, legacy_id)
    assert loaded.source_dependencies is None and loaded.source_state_hash == "sha256:legacy"
    assert content_hash(loaded.model_dump(mode="json")) == content_hash(body)
    snapshot = env.start()
    snapshot_body = json.loads(snapshot.model_dump_json())
    snapshot_body.pop("source_dependency_manifest")
    snapshot_body.update(id=new_id(), run_id=new_id(), source_state_hash="sha256:legacy")
    legacy_snapshot_id = insert_legacy(env, "SupervisorRunSnapshot", snapshot_body)
    loaded_snapshot = env.repo.get_artifact(env.incident_id, legacy_snapshot_id)
    assert loaded_snapshot.source_dependency_manifest is None and loaded_snapshot.source_state_hash == "sha256:legacy"
    assert content_hash(loaded_snapshot.model_dump(mode="json")) == content_hash(snapshot_body)


def test_legacy_global_checkpoint_records_cannot_bypass_scoped_freshness(env):
    env.confirm()
    history = env.repo.get_artifact(env.incident_id, env.history_id)
    legacy_id = insert_legacy(env, "Evidence", legacy_evidence_body(env, history))
    lifecycle = LifecycleService(env.repo)
    assert legacy_id not in lifecycle.current_evidence_ids(env.incident_id, ASSET)
    with pytest.raises(PromotionRefused, match="predates dependency-scoped freshness") as refused:
        env.start(evidence_ids=(env.signal_id, legacy_id))
    assert refused.value.disposition == "NEEDS_EVIDENCE"
    # A legacy snapshot (whole-store hash only) completes with an explicit unverifiable
    # stale reason and can never be promoted; a new run is required.
    snapshot = env.start()
    body = json.loads(snapshot.model_dump_json())
    body.pop("source_dependency_manifest")
    body.update(id=new_id(), run_id=new_id(), source_state_hash="sha256:legacy")
    body["context_payload"]["run_id"] = body["run_id"]
    legacy_snapshot_id = insert_legacy(env, "SupervisorRunSnapshot", body)
    legacy_snapshot = env.repo.get_artifact(env.incident_id, legacy_snapshot_id)
    incident = env.repo.fetch_incident(env.incident_id)
    with env.repo._write() as conn:
        env.repo._update(conn, incident, active_run_id=legacy_snapshot.run_id)
    payload = result_payload(env, legacy_snapshot)
    report = env.service._complete_run(legacy_snapshot, SupervisorResult.model_validate(payload))
    assert "LEGACY_SOURCE_CHECKPOINT_UNVERIFIABLE" in report.stale_reasons
    with pytest.raises(PromotionRefused):
        env.promote_diagnosis(report)


# ------------------------------------------------------- continuous stream

async def test_continuous_telemetry_outside_the_frozen_window_keeps_the_run_promotable(env, monkeypatch):
    telemetry, start, end = bounded_window(env)
    env.confirm(supporting_evidence_ids=(env.history_id, telemetry.id))
    written = []

    async def invoke(runtime, service, context, **kwargs):
        snapshot = next(a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.SupervisorRunSnapshot) and a.run_id == context.run_id)
        for tick in range(5):  # the plant keeps streaming for every asset while the model reasons
            now = utcnow()
            for asset in (ASSET, MACHINE_B, "HYD-PUMP-03"):
                for sensor_type in ("TORQUE", "SPEED"):
                    write_readings(env.repo.path, asset, (float(tick),), start=now, sensor_type=sensor_type)
                sql(env.repo.path, "INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) VALUES (?,?,?,?,?)",
                    asset, now.isoformat(), 0.5, 0.5, "OSF")
            written.append(now)
        return SupervisorResult.model_validate(result_payload(env, snapshot))
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)
    report = await env.service.run_supervisor(env.incident_id, service=env.evidence_service, runtime=env.runtime,
        asset_id=ASSET, stage="DIAGNOSIS", expected_revision=revision(env), evidence_ids=(*env.evidence_ids(), telemetry.id))
    assert written and all(moment > end for moment in written)
    assert report.stale_reasons == () and report.completion == "MODEL_COMPLETED"
    write_readings(env.repo.path, ASSET, (9.0,), start=utcnow())
    promotion = env.promote_diagnosis(report)
    assert env.repo.fetch_incident(env.incident_id).current_diagnosis_id == promotion.target_id


async def test_lifecycle_diagnosis_promotes_while_the_plant_streams(seeded_db, monkeypatch):
    """LifecycleService.diagnose end to end: baseline reads are pinned by the application,
    so same-asset and other-asset ticks during reasoning change nothing the run relied on."""
    from tests.test_reliability_lifecycle import Flow
    flow = Flow()
    for sensor_type in ("AIRTEMP", "PROCTEMP", "SPEED", "TORQUE", "TOOLWEAR"):
        write_readings(flow.repo.path, ASSET, (1.0, 2.0, 3.0), start=utcnow() - timedelta(minutes=2), sensor_type=sensor_type)
    flow.confirm()

    async def invoke(runtime, service, context, **kwargs):
        snapshot = next(a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.SupervisorRunSnapshot) and a.run_id == context.run_id)
        assert {"telemetry_window", "telemetry_latest", "health_score_latest"} <= {d.domain for d in snapshot.source_dependency_manifest.dependencies}
        for asset in (ASSET, MACHINE_B):
            now = utcnow()
            write_readings(flow.repo.path, asset, (5.0,), start=now)
            sql(flow.repo.path, "INSERT INTO health_score (equipment_id,scored_at,health_score,failure_prob,predicted_mode) VALUES (?,?,?,?,?)",
                asset, now.isoformat(), 0.4, 0.6, "OSF")
        return SupervisorResult.model_validate(result_payload(flow, snapshot))
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime, evidence_service=flow.evidence_service)
    assert outcome.disposition == "PROMOTED", outcome.reason
    # Unrelated streaming triggers no refresh; a real history change does.
    flow.repo.transition(flow.incident_id, m.IncidentPhase.INVESTIGATING, expected_revision=revision(flow), reason="reopen")
    before = len(flow.repo.list_artifacts(flow.incident_id))
    write_readings(flow.repo.path, ASSET, (6.0,), start=utcnow())
    flow.lifecycle.refresh_baseline_evidence(flow.incident_id, ASSET, flow.evidence_service)
    assert len(flow.repo.list_artifacts(flow.incident_id)) == before
    sql(flow.repo.path, "UPDATE maintenance_event SET note=note || ' amended' WHERE equipment_id='AC-COMP-01'")
    flow.lifecycle.refresh_baseline_evidence(flow.incident_id, ASSET, flow.evidence_service)
    assert len(flow.repo.list_artifacts(flow.incident_id)) > before


# ------------------------------------------------------- authority invariants

def test_agents_cannot_supply_fingerprints_or_manifests_through_requests(env):
    for parameters in ({"fingerprint": "x"}, {"source_dependencies": {"basis": "IMMUTABLE_OBSERVATION"}}, {"as_of": "not-a-time"}):
        with pytest.raises((ValueError, ValidationError)):
            collect(env, "get_asset_context", parameters)
    with pytest.raises(ValidationError):
        m.SourceDependencyManifest(basis="SOURCE_QUERY", dependencies=())
    with pytest.raises(ValidationError):
        m.SourceDependencyManifest(basis="IMMUTABLE_OBSERVATION", dependencies=(m.SourceDependency(
            domain="asset_registry", scope={"asset_id": ASSET}, fingerprint="x"),))


@pytest.mark.parametrize("forgery", ["fingerprint", "narrowed", "broadened", "other_asset_scope", "observation_basis",
                                     "closure_basis", "unsupported_capability", "derived_without_parents", "no_request", "foreign_request"])
def test_caller_supplied_evidence_cannot_mint_trusted_manifests(env, forgery):
    telemetry, _, _ = bounded_window(env)
    manifest = telemetry.source_dependencies
    changes = {"id": new_id()}
    expected = InvalidReference
    if forgery == "fingerprint":
        changes["source_dependencies"] = manifest.model_copy(update={"dependencies": (
            manifest.dependencies[0].model_copy(update={"fingerprint": "sha256:forged"}), *manifest.dependencies[1:])})
        expected = StaleRevision
    elif forgery == "narrowed":
        changes["source_dependencies"] = manifest.model_copy(update={"dependencies": manifest.dependencies[:1]})
    elif forgery == "broadened":
        extra = m.SourceDependency(domain="asset_registry", scope={"asset_id": ASSET}, fingerprint=manifest.dependencies[0].fingerprint)
        changes["source_dependencies"] = manifest.model_copy(update={"dependencies": (*manifest.dependencies, extra)})
    elif forgery == "other_asset_scope":
        moved = tuple(item.model_copy(update={"scope": {key: value.replace(ASSET, MACHINE_B) for key, value in item.scope.items()}})
                      for item in manifest.dependencies)
        changes["source_dependencies"] = manifest.model_copy(update={"dependencies": moved})
    elif forgery == "observation_basis":
        changes["source_dependencies"] = observation_manifest()
    elif forgery == "closure_basis":
        changes.update(source_capability="custom.import", source_dependencies=closure([manifest]))
    elif forgery == "unsupported_capability":
        changes["source_capability"] = "custom.import"
    elif forgery == "derived_without_parents":
        changes.update(source_capability="custom.import", source_dependencies=derived_manifest())
    elif forgery == "no_request":
        changes["request_id"] = None
    else:
        changes["request_id"] = env.repo.get_artifact(env.incident_id, env.history_id).request_id
    before = state(env)
    with pytest.raises(expected):
        env.repo.add_artifact(telemetry.model_copy(update=changes), expected_revision=revision(env))
    assert state(env) == before


def test_content_hash_and_closure_consistency_still_detect_mutation(env):
    telemetry, _, _ = bounded_window(env)
    mutated = telemetry.model_copy(update={"id": new_id(), "payload": telemetry.payload | {"asset_id": MACHINE_B}})
    with pytest.raises(InvalidReference, match="content hash"):
        env.repo.add_artifact(mutated, expected_revision=revision(env))
    # Two artifacts freezing the same read with different fingerprints cannot share a closure.
    conflicting = telemetry.source_dependencies.model_copy(update={"dependencies": (
        telemetry.source_dependencies.dependencies[0].model_copy(update={"fingerprint": "sha256:other"}),)})
    with pytest.raises(ValueError, match="conflicting"):
        closure([telemetry.source_dependencies, conflicting])


def test_snapshot_manifest_is_promotion_owned_and_model_output_cannot_alter_it(env):
    env.confirm()
    snapshot = env.start()
    forged = snapshot.model_copy(update={"id": new_id(), "source_dependency_manifest": closure([])})
    with pytest.raises(InvalidReference, match="trusted PromotionService"):
        env.repo.add_artifact(forged, expected_revision=revision(env))
    with pytest.raises(PromotionRefused, match="snapshot differs"):
        env.service._complete_run(snapshot.model_copy(update={"source_dependency_manifest": closure([])}),
                                  SupervisorResult.model_validate(result_payload(env, snapshot)))
    report = env.complete(snapshot)
    assert env.repo.get_artifact(env.incident_id, snapshot.id).source_dependency_manifest == snapshot.source_dependency_manifest
    assert report.stale_reasons == ()


def test_signal_admission_and_other_incident_scope_are_unchanged(seeded_db):
    repo = IncidentRepository()
    incident, created = repo.admit_signal(signal())
    evidence = repo.get_artifact(incident.id, incident.signal_evidence_ids[0])
    assert created and evidence.source_dependencies == observation_manifest()
    other, _ = repo.admit_signal(signal().model_copy(update={"equipment_id": MACHINE_B}))
    foreign = repo.get_artifact(other.id, other.signal_evidence_ids[0])
    with pytest.raises(InvalidReference):
        repo.add_artifact(foreign.model_copy(update={"id": new_id(), "incident_id": incident.id}), expected_revision=repo.fetch_incident(incident.id).revision)


def relabel(env, source_id, **changes):
    """A caller-shaped copy of a durable record: new id, no request, generic provenance."""
    payload = changes.pop("payload", {"imported": "caller supplied"})
    base = {"id": new_id(), "request_id": None, "collection_key": None, "payload": payload,
            "content_hash": content_hash(payload), "source_capability": "custom.import"}
    return env.repo.get_artifact(env.incident_id, source_id).model_copy(update=base | changes)


@pytest.mark.parametrize("forgery", ["document_observation", "inspection_observation", "resource_snapshot_observation",
                                     "trusted_capability_from_public_path", "derived_telemetry", "derived_history",
                                     "derived_operating_context", "capability_kind_relabelled", "derived_from_non_evidence"])
def test_generic_caller_cannot_mint_observation_or_derived_freshness(env, forgery):
    """IMMUTABLE_OBSERVATION and DERIVED are not caller-controlled freshness bypasses."""
    telemetry, _, _ = bounded_window(env)
    expected = "immutable observations"
    if forgery == "document_observation":
        forged = relabel(env, env.history_id, kind="document", source_dependencies=observation_manifest())
    elif forgery == "inspection_observation":
        forged = relabel(env, env.history_id, kind="inspection", source_capability="field.inspection",
                         source_dependencies=observation_manifest())
    elif forgery == "resource_snapshot_observation":
        forged = relabel(env, env.history_id, kind="resource_availability", source_capability="inspect_available_technicians",
                         source_dependencies=observation_manifest())
    elif forgery == "trusted_capability_from_public_path":
        forged = relabel(env, env.history_id, kind="inspection", source_capability=CONFIRM_MECHANISM,
                         source_dependencies=observation_manifest())
        expected = "trusted PromotionService"
    elif forgery == "derived_telemetry":
        forged = relabel(env, telemetry.id, payload=telemetry.payload, source_dependencies=derived_manifest(),
                         derived_from_ids=(env.signal_id,))
        expected = "produced only by application source capabilities"
    elif forgery == "derived_history":
        forged = relabel(env, env.history_id, source_dependencies=derived_manifest(), derived_from_ids=(env.history_id,))
        expected = "produced only by application source capabilities"
    elif forgery == "derived_operating_context":
        forged = relabel(env, env.history_id, kind="operational_context", source_dependencies=derived_manifest(),
                         derived_from_ids=(env.signal_id, env.history_id))
        expected = "produced only by application source capabilities"
    elif forgery == "capability_kind_relabelled":
        # A valid, replayable source-query manifest cannot be attached to a different kind.
        forged = telemetry.model_copy(update={"id": new_id(), "kind": "inspection"})
        expected = "kind does not match"
    else:
        request_id = env.repo.get_artifact(env.incident_id, env.history_id).request_id
        forged = relabel(env, env.history_id, kind="document", source_dependencies=derived_manifest(),
                         derived_from_ids=(request_id,))
        expected = "requires Evidence"
    before = state(env)
    with pytest.raises(InvalidReference, match=expected):
        env.repo.add_artifact(forged, expected_revision=revision(env))
    assert state(env) == before
    assert forged.id not in LifecycleService(env.repo).current_evidence_ids(env.incident_id, ASSET)


@pytest.mark.parametrize("forgery", ["observation", "derived_telemetry"])
def test_forged_rows_that_bypass_insertion_never_enter_a_promotable_packet(env, forgery):
    """The same authority is re-checked wherever freshness is decided, not only on insert."""
    telemetry, _, _ = bounded_window(env)
    if forgery == "observation":
        forged = relabel(env, env.history_id, kind="document", source_dependencies=observation_manifest())
    else:
        forged = relabel(env, telemetry.id, payload=telemetry.payload, source_dependencies=derived_manifest(),
                         derived_from_ids=(env.signal_id,))
    forged_id = insert_legacy(env, "Evidence", json.loads(forged.model_dump_json()))
    loaded = env.repo.get_artifact(env.incident_id, forged_id)
    assert loaded.source_dependencies == forged.source_dependencies  # historical rows still load unchanged
    assert fresh(env, loaded)  # its own manifest recomputes nothing...
    lifecycle = LifecycleService(env.repo)
    assert forged_id not in lifecycle.current_evidence_ids(env.incident_id, ASSET)  # ...and grants nothing
    with pytest.raises(PromotionRefused) as refused:
        env.start(evidence_ids=(env.signal_id, forged_id))
    assert refused.value.disposition == "NEEDS_EVIDENCE"
    assert env.repo.fetch_incident(env.incident_id).active_run_id is None


def test_legitimate_signals_confirmations_and_derivations_keep_their_semantics(env):
    """Model signals, trusted confirmations and parent-bound derivations are unchanged."""
    lifecycle = LifecycleService(env.repo)
    # A second model signal reaches the incident through the public path with its observation manifest.
    second = signal_evidence(signal(), env.incident_id)
    env.repo.add_artifact(second, expected_revision=revision(env))
    assert env.repo.get_artifact(env.incident_id, second.id).source_dependencies == observation_manifest()
    # Trusted confirmations still mint observations through the promotion boundary only.
    confirmation, resource = env.confirm(), env.resources()
    assert confirmation.source_dependencies == resource.source_dependencies == observation_manifest()
    # A derivation of a generic kind is accepted and is exactly as fresh as its parents.
    derived = relabel(env, env.history_id, kind="document", source_capability="model_reasoning",
                      source_dependencies=derived_manifest(), derived_from_ids=(env.history_id, second.id))
    env.repo.add_artifact(derived, expected_revision=revision(env))
    current = set(lifecycle.current_evidence_ids(env.incident_id, ASSET))
    assert {env.signal_id, second.id, confirmation.id, resource.id, derived.id, env.history_id} <= current
    snapshot = env.start(evidence_ids=(*env.evidence_ids(), second.id, derived.id))
    assert env.history_id in snapshot.evidence_manifest and domains(snapshot.source_dependency_manifest) == ["maintenance_history"]
    write_readings(env.repo.path, ASSET, (3.0,), start=utcnow())
    assert env.complete(snapshot).stale_reasons == ()
    sql(env.repo.path, "UPDATE maintenance_event SET note=note || ' amended' WHERE equipment_id='AC-COMP-01'")
    current = set(lifecycle.current_evidence_ids(env.incident_id, ASSET))
    assert {env.signal_id, second.id, resource.id} <= current and not {derived.id, env.history_id, confirmation.id} & current


def test_related_incidents_dependency_follows_same_asset_incident_revisions_only(env):
    """Every mutation of a returned incident's state or artifacts advances its revision."""
    related_b = env.repo.create_incident((ASSET,), admission_key="compressor-b")
    unrelated_c = env.repo.create_incident(("HYD-PUMP-03",), admission_key="pump-c")
    related = collect(env, "get_related_incidents", {"limit": 20})
    returned = {item["incident_id"] for item in related.result.model_dump(mode="json")["incidents"]}
    assert related.evidence.quality == "GOOD" and related_b.id in returned and env.incident_id not in returned
    dependency = related.evidence.source_dependencies.dependencies[0]
    assert dependency.domain == "related_incidents" and dependency.scope["exclude_incident_id"] == env.incident_id

    # Unrelated incident, unrelated asset telemetry and the requesting incident itself change nothing.
    env.repo.append_event(unrelated_c.id, "INCIDENT_UPDATED", {"changed": True}, expected_revision=unrelated_c.revision)
    env.repo.transition(unrelated_c.id, m.IncidentPhase.INVESTIGATING, expected_revision=unrelated_c.revision + 1, reason="unrelated")
    env.evidence_service.request_and_collect(unrelated_c.id, requested_by="diagnostic", equipment_ids=("HYD-PUMP-03",),
        question="history", capability="get_maintenance_history", required_for="diagnosis")
    write_readings(env.repo.path, ASSET, (1.0, 2.0), start=utcnow())
    write_readings(env.repo.path, "HYD-PUMP-03", (1.0,), start=utcnow())
    env.repo.append_event(env.incident_id, "INCIDENT_UPDATED", {"self": True}, expected_revision=revision(env))
    assert fresh(env, related.evidence)

    # A returned artifact set changes through the legitimate application path: revision advances, A goes stale.
    before = env.repo.fetch_incident(related_b.id).revision
    collection = env.evidence_service.request_and_collect(related_b.id, requested_by="diagnostic", equipment_ids=(ASSET,),
        question="history", capability="get_maintenance_history", required_for="diagnosis")
    after = env.repo.fetch_incident(related_b.id).revision
    assert after > before and collection.evidence.id in env.repo.fetch_incident(related_b.id).artifact_ids
    with db.get_conn(env.repo.path) as conn:
        changes = revalidate(conn, related.evidence.source_dependencies)
    assert [item.dependency.domain for item in changes] == ["related_incidents"]
    assert changes[0].reason.startswith("SOURCE_DEPENDENCY_CHANGED:related_incidents[")

    # Returned state changes through the legitimate path as well; a fresh collection is a new generation.
    again = collect(env, "get_related_incidents", {"limit": 20})
    assert not again.reused and again.evidence.supersedes_id == related.evidence.id and fresh(env, again.evidence)
    env.repo.transition(related_b.id, m.IncidentPhase.INVESTIGATING, expected_revision=after, reason="state change")
    assert env.repo.fetch_incident(related_b.id).revision == after + 1 and not fresh(env, again.evidence)


async def test_approval_and_execution_paths_are_unchanged_under_streaming(seeded_db, monkeypatch):
    from tests.test_reliability_lifecycle import Flow
    from core.reliability.governance import artifact_hash
    flow = Flow()
    intervention, promotion, requirement, decision = flow.ready()
    write_readings(flow.repo.path, ASSET, (1.0, 2.0), start=utcnow())
    write_readings(flow.repo.path, MACHINE_B, (1.0,), start=utcnow())
    report = flow.lifecycle.execute(flow.incident_id, intervention.id, intervention_hash=artifact_hash(intervention))
    assert report.phase == m.IncidentPhase.OBSERVING
    assert flow.lifecycle.status(flow.incident_id).claim_state == "CONFIRMED"


def test_baseline_boundary_is_the_previous_whole_second_and_sparse_windows_are_repinned(seeded_db):
    """Second-precision writers cannot land inside a frozen baseline window after it was
    collected; a baseline window with too few samples is re-pinned, not re-asked."""
    from datetime import datetime, timezone
    from core.reliability.investigation import baseline_parameters, snapshot_boundary
    moment = datetime(2026, 9, 10, 17, 0, 5, 400000, tzinfo=timezone.utc)
    assert snapshot_boundary(moment) == datetime(2026, 9, 10, 17, 0, 4, tzinfo=timezone.utc)
    assert baseline_parameters("get_telemetry_window", {"sample_limit": 60}, collected_at=moment)["end_at"] == snapshot_boundary(moment)
    assert baseline_parameters("get_maintenance_history", {"limit": 20}, collected_at=moment) == {"limit": 20}
    explicit = baseline_parameters("get_asset_context", {"as_of": moment}, collected_at=utcnow())
    assert explicit["as_of"] == moment
    # Engine-style same-second write after collection sorts strictly after the boundary.
    assert moment.replace(microsecond=0).isoformat() > snapshot_boundary(moment).isoformat()

    env = Environment()
    lifecycle = LifecycleService(env.repo)
    first = lifecycle.refresh_baseline_evidence(env.incident_id, ASSET, env.evidence_service)
    windows = lambda: [a for a in env.repo.list_artifacts(env.incident_id) if isinstance(a, m.Evidence) and a.kind == "telemetry"]
    assert len(windows()) == 1 and windows()[0].quality == "MISSING"
    # Samples now exist before the next boundary: the refresh pins a new window and it is usable.
    for sensor_type in ("AIRTEMP", "PROCTEMP", "SPEED", "TORQUE", "TOOLWEAR"):
        write_readings(env.repo.path, ASSET, (1.0, 2.0, 3.0), start=utcnow() - timedelta(minutes=1), sensor_type=sensor_type)
    second = lifecycle.refresh_baseline_evidence(env.incident_id, ASSET, env.evidence_service)
    assert set(second) != set(first) and len(windows()) == 2 and windows()[-1].quality == "GOOD"
    # Same second: the sparse window is superseded under its key; later: a newer boundary is pinned.
    assert windows()[-1].payload["requested_end"] >= windows()[0].payload["requested_end"]
    # A usable window is reused as-is; unrelated streaming does not re-pin or refresh anything.
    write_readings(env.repo.path, ASSET, (4.0,), start=utcnow())
    before = len(env.repo.list_artifacts(env.incident_id))
    third = lifecycle.refresh_baseline_evidence(env.incident_id, ASSET, env.evidence_service)
    assert set(third) == set(second) and len(env.repo.list_artifacts(env.incident_id)) == before
    assert windows()[-1].id in lifecycle.current_evidence_ids(env.incident_id, ASSET)
    assert windows()[0].id not in lifecycle.current_evidence_ids(env.incident_id, ASSET)
