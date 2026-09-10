"""Engine and API integration of the Step 13B authoritative lifecycle (offline)."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core import db, engine as engine_module
from core.agents.contracts import SupervisorResult
from core.agents.runtime import StrandsRuntime
from core.reliability import models as m
from core.reliability.promotion import PromotionService
from core.reliability.repository import utcnow
from tests.test_engine import StubModel
from tests.test_promotion import result_payload
from tests.test_strands_agents import ScriptedModel, settings

ASSET = "AC-COMP-01"
MECHANISM = "Confirmed compressor mechanical overload"


def make_engine(monkeypatch, failure_prob=0.91, *, runtime=None, legacy=None):
    monkeypatch.setattr(engine_module, "load_or_train", lambda: StubModel(failure_prob))
    monkeypatch.setattr(StubModel, "attribute", lambda self, _features: [
        {"feature": "torque", "label": "Torque", "value": 62.0, "contribution": 0.34}])
    return engine_module.DemoEngine(runtime=runtime, legacy_demo=legacy)


class Bridge:
    """Adapts an engine incident to the promotion test payload helpers."""

    def __init__(self, engine, eid):
        self.engine, self.eid = engine, eid
        self.repo = engine.coordinator.repository
        self.incident_id = engine.incidents[eid].id
        incident = self.repo.fetch_incident(self.incident_id)
        self.signal_id = incident.signal_evidence_ids[0]
        artifacts = self.repo.list_artifacts(self.incident_id)
        self.history_id = next(a.id for a in artifacts if isinstance(a, m.Evidence) and a.kind == "maintenance_history")
        self.confirmation = None
        self.resource = None

    def revision(self):
        return self.repo.fetch_incident(self.incident_id).revision

    def current_history_id(self, manifest=None):
        artifacts = self.repo.list_artifacts(self.incident_id)
        superseded = {a.supersedes_id for a in artifacts if getattr(a, "supersedes_id", None)}
        history = [a.id for a in artifacts if isinstance(a, m.Evidence) and a.kind == "maintenance_history"
                   and a.id not in superseded and (manifest is None or a.id in manifest)]
        return history[-1]

    def confirm(self):
        # Trusted support must be source-fresh; refresh baseline reads like the lifecycle does.
        self.engine.lifecycle.refresh_baseline_evidence(self.incident_id, ASSET, self.engine.evidence_service)
        self.history_id = self.current_history_id()
        fields = dict(incident_id=self.incident_id, asset_id=ASSET, confirmed_mechanism=MECHANISM, failure_mode_code="OSF",
                      supporting_evidence_ids=(self.history_id,),
                      performed_checks=(m.PerformedCheck(check="Shaft inspection", result="Overload confirmed", passed=True),),
                      observed_at=utcnow(), source="offline-inspection", actor_id="trusted-inspector", provenance="SIMULATED")
        response = self.engine.submit_technical_confirmation(m.TrustedTechnicalConfirmation(**fields),
                                                             expected_revision=self.revision())
        self.confirmation = self.repo.get_artifact(self.incident_id, response["evidence_id"])
        return response

    def resources(self):
        with db.get_conn(self.repo.path) as conn:
            tech = conn.execute("SELECT technician_id FROM technician WHERE skills LIKE '%COMPRESSOR%' AND available=1 "
                                "ORDER BY technician_id").fetchone()[0]
            parts = tuple(m.WorkPackagePart(part_id=row[0], quantity=row[1]) for row in conn.execute(
                "SELECT part_id,qty_per_service FROM equipment_part WHERE equipment_id=? ORDER BY part_id", (ASSET,)))
        start = utcnow() + timedelta(days=1)
        fields = dict(incident_id=self.incident_id, asset_id=ASSET, technician_id=tech, qualification="COMPRESSOR",
                      qualification_valid_until=start + timedelta(days=30), available_start=start - timedelta(hours=1),
                      available_end=start + timedelta(hours=4), window_start=start, window_end=start + timedelta(hours=2),
                      window_confirmed=True, parts=parts, observed_at=utcnow(), source="offline-dispatch",
                      actor_id="trusted-dispatcher", provenance="SIMULATED")
        response = self.engine.submit_resource_confirmation(m.ResourceConfirmation(**fields), expected_revision=self.revision())
        self.resource = self.repo.get_artifact(self.incident_id, response["evidence_id"])
        return response

    def binding_fields(self):
        incident = self.repo.fetch_incident(self.incident_id)
        promotion = PromotionService(self.repo).promotion_lineage(self.incident_id, incident.current_diagnosis_id, "diagnosis")
        resource = m.ResourceConfirmation.model_validate(self.resource.payload)
        report = self.repo.get_artifact(self.incident_id, promotion.source_report_id)
        return dict(diagnosis_id=promotion.target_id, source_report_id=report.id, source_plan_key="plan", asset_id=ASSET,
                    failure_mode_id="FM-OSF", technician_id=resource.technician_id, parts=resource.parts,
                    resource_confirmation_id=self.resource.id, signal_evidence_id=self.signal_id,
                    window_start=resource.window_start, window_end=resource.window_end, duration_minutes=45,
                    work_instructions=("Isolate compressor and verify zero energy.", "Perform reviewed mechanical overhaul."),
                    technical_preconditions=("Isolation verified by qualified technician",),
                    verification_criteria=("Record physical inspection and service checks",),
                    evidence_ids=tuple(sorted(set(report.evidence_manifest) | {self.resource.id})),
                    estimated_cost=550.0, estimated_downtime_minutes=60, estimated_avoided_loss=12000.0,
                    business_assumption_version="test-business-2026-1", safety_review="Reviewed isolation and mechanical hazards",
                    safety_relevant=True, reversible=False, external_commitment=True)


def scripted_supervisor(monkeypatch, bridge_ref, transform=None):
    """Scripted advisory results per incident; every run cites only its frozen packet."""
    async def invoke(runtime, service, context, **kwargs):
        repo = service.repository
        # Invocation runs outside any write transaction: an independent writer succeeds.
        with db.get_conn(repo.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
        artifacts = repo.list_artifacts(context.incident_id)
        snapshot = next(a for a in artifacts if isinstance(a, m.SupervisorRunSnapshot) and a.run_id == context.run_id)
        draft = repo.get_artifact(context.incident_id, context.review_target_id) if context.review_target_id else None
        history = [a.id for a in artifacts if isinstance(a, m.Evidence) and a.kind == "maintenance_history"
                   and a.id in snapshot.evidence_manifest]
        env = SimpleNamespace(incident_id=context.incident_id,
                              history_id=history[-1] if history else next(iter(snapshot.evidence_manifest)))
        bridge = bridge_ref.get("bridge")
        if bridge is not None and bridge.incident_id == context.incident_id:
            bridge.history_id = env.history_id
        payload = result_payload(env, snapshot, draft=draft)
        if transform:
            payload = transform(payload)
        return SupervisorResult.model_validate(payload)
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)


async def test_default_engine_path_admits_and_investigates_without_manufacturing_authority(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    assert not engine.legacy_demo and engine.runtime is None
    await engine._advance()
    assert engine.alerts and all(a["status"] == "ANALYZING" for a in engine.alerts.values())
    for eid, incident in engine.incidents.items():
        incident = engine.coordinator.repository.fetch_incident(incident.id)
        assert incident.phase == m.IncidentPhase.INVESTIGATING
        assert incident.current_diagnosis_id is None and incident.current_intervention_id is None
        artifacts = engine.coordinator.repository.list_artifacts(incident.id)
        assert not any(isinstance(a, (m.Diagnosis, m.Intervention, m.ValidationVerdict, m.ApprovalRequirement, m.LegacyAlert))
                       for a in artifacts)
        assert any(isinstance(a, m.Evidence) and a.kind == "telemetry" for a in artifacts)
        assert engine.alerts[eid]["lifecycle"]["phase"] == "INVESTIGATING"
        assert engine.alerts[eid]["lifecycle"]["supervisor_available"] is False
    # Equipment-only approval intent is rejected; nothing executes.
    assert (await engine.approve("AC-COMP-01"))["ok"] is False
    assert (await engine.reject("AC-COMP-01", {"requirement_id": "x"}))["ok"] is False
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM approval_decision").fetchone()[0] == 0
    # Repeated ticks re-admit nothing and fabricate nothing.
    ids = {eid: incident.id for eid, incident in engine.incidents.items()}
    await engine._advance()
    assert {eid: incident.id for eid, incident in engine.incidents.items()} == ids
    assert engine.snapshot()["authority_path"] == "lifecycle"


async def test_engine_drives_the_full_authoritative_lifecycle_to_observing(seeded_db, monkeypatch):
    holder = {}
    scripted_supervisor(monkeypatch, holder)
    engine = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    engine.sim.assets[ASSET].prog = 0.9
    await engine._advance()
    bridge = holder["bridge"] = Bridge(engine, ASSET)
    await engine.drain()
    assert engine.incidents[ASSET].phase == m.IncidentPhase.AWAITING_EVIDENCE
    assert engine.alerts[ASSET]["lifecycle"]["phase"] == "AWAITING_EVIDENCE" and engine.alerts[ASSET]["proposal"] is None

    # Ticks must not spin supervisor attempts while evidence is missing.
    await engine._advance()
    await engine.drain()
    assert engine.incidents[ASSET].phase == m.IncidentPhase.AWAITING_EVIDENCE

    # Trusted confirmation resumes investigation; a fresh run then promotes the diagnosis.
    bridge.confirm()
    assert engine.incidents[ASSET].phase == m.IncidentPhase.INVESTIGATING
    await engine.stop()  # pause telemetry persistence so 13A raw-source freshness can hold
    engine._progress_lifecycle()
    await engine.drain()
    incident = engine.coordinator.repository.fetch_incident(bridge.incident_id)
    assert incident.phase == m.IncidentPhase.DIAGNOSIS_VALIDATED and incident.current_diagnosis_id

    bridge.resources()
    response = await engine.plan(bridge.incident_id, expected_revision=bridge.revision(), **bridge.binding_fields())
    assert response["ok"], response
    alert = engine.alerts[ASSET]
    assert alert["status"] == "PENDING_APPROVAL" and alert["proposal"]["governance"]["decision"] == "CONDITIONS"
    intent = {key: alert["lifecycle"][key] for key in ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}
    assert all(intent.values())

    stale = await engine.approve(ASSET, intent | {"context_revision": intent["context_revision"] - 1})
    assert stale["ok"] is False and "stale" in stale["error"]
    wrong = await engine.approve(ASSET, intent | {"intervention_hash": "tampered"})
    assert wrong["ok"] is False
    assert engine.incidents[ASSET].phase == m.IncidentPhase.AWAITING_APPROVAL

    result = await engine.approve(ASSET, intent)
    assert result["ok"], result
    assert result["phase"] == "OBSERVING" and result["result"]["outcome"] == "DISPATCHED"
    assert result["result"]["recovered_value"] == 12000.0
    incident = engine.coordinator.repository.fetch_incident(bridge.incident_id)
    assert incident.phase == m.IncidentPhase.OBSERVING
    assert engine.alerts[ASSET]["status"] == "APPROVED" and engine.sim.assets[ASSET].mode == "recovering"
    receipts = engine.coordinator.repository.list_execution_receipts(bridge.incident_id)
    assert [r.status for r in receipts] == ["CONFIRMED"]
    assert receipts[0].intervention_hash == intent["intervention_hash"]
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM incident_artifact WHERE kind='Outcome'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM incident_artifact WHERE kind='LegacyAlert'").fetchone()[0] == 0
    # Idempotent re-approval reproduces the same decision but never dispatches twice.
    again = await engine.approve(ASSET, intent | {"context_revision": intent["context_revision"]})
    assert again["ok"] is False and "requires READY" in again["error"]
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 1

    # Restart reconstructs OBSERVING from durable pointers without any dispatch.
    restarted = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    assert restarted.incidents[ASSET].phase == m.IncidentPhase.OBSERVING
    assert restarted.alerts[ASSET]["status"] == "APPROVED" and restarted.sim.assets[ASSET].mode == "recovering"
    assert restarted.alerts[ASSET]["execution_receipt_ids"] == [receipts[0].id]
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 1


async def test_restart_reconstructs_ready_and_requires_explicit_execution(seeded_db, monkeypatch):
    holder = {}
    scripted_supervisor(monkeypatch, holder)
    engine = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    await engine._advance()
    await engine.stop()
    bridge = holder["bridge"] = Bridge(engine, ASSET)
    await engine.drain()
    bridge.confirm()
    engine._progress_lifecycle()
    await engine.drain()
    bridge.resources()
    assert (await engine.plan(bridge.incident_id, expected_revision=bridge.revision(), **bridge.binding_fields()))["ok"]
    alert = engine.alerts[ASSET]
    intent = {key: alert["lifecycle"][key] for key in ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}
    decision = engine.lifecycle.decide_approval(bridge.incident_id, decision="APPROVE", actor_id="approver", actor_role="maintenance_approver",
                                                rationale="approved out of band", **intent)  # crash before dispatch
    assert engine.coordinator.repository.fetch_incident(bridge.incident_id).phase == m.IncidentPhase.READY

    restarted = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    assert restarted.incidents[ASSET].phase == m.IncidentPhase.READY
    assert restarted.alerts[ASSET]["status"] == "APPROVED" and restarted.sim.assets[ASSET].mode == "arrested"
    await restarted._advance()
    await restarted.drain()
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 0
    rejected = await restarted.reject(ASSET, intent)
    assert rejected["ok"] is False
    result = await restarted.execute(bridge.incident_id, decision.intervention_id, intervention_hash=decision.intervention_hash)
    assert result["ok"] and result["phase"] == "OBSERVING"
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 1


async def test_engine_rejection_escalates_without_execution(seeded_db, monkeypatch):
    holder = {}
    scripted_supervisor(monkeypatch, holder)
    engine = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    await engine._advance()
    await engine.stop()
    bridge = holder["bridge"] = Bridge(engine, ASSET)
    await engine.drain()
    bridge.confirm()
    engine._progress_lifecycle()
    await engine.drain()
    bridge.resources()
    assert (await engine.plan(bridge.incident_id, expected_revision=bridge.revision(), **bridge.binding_fields()))["ok"]
    alert = engine.alerts[ASSET]
    intent = {key: alert["lifecycle"][key] for key in ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}
    assert (await engine.reject(ASSET, intent))["ok"]
    assert engine.incidents[ASSET].phase == m.IncidentPhase.ESCALATED and engine.alerts[ASSET]["status"] == "REJECTED"
    assert engine.sim.assets[ASSET].mode == "failing"
    assert (await engine.approve(ASSET, intent))["ok"] is False
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_package").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM approval_decision").fetchone()[0] == 1


async def test_supervisor_failures_escalate_and_never_promote(seeded_db, monkeypatch):
    holder = {}
    scripted_supervisor(monkeypatch, holder, lambda payload: payload | {"termination_reason": "MODEL_FAILED", "disposition": "ESCALATED",
                                                                       "decision": None, "blockers": ["Invocation failed"]})
    engine = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    await engine._advance()
    holder["bridge"] = Bridge(engine, ASSET)
    await engine.drain()
    incident = engine.coordinator.repository.fetch_incident(engine.incidents[ASSET].id)
    assert incident.phase == m.IncidentPhase.ESCALATED and incident.current_diagnosis_id is None
    assert engine.alerts[ASSET]["status"] == "ESCALATED"


def test_api_contract_rejects_equipment_only_and_stale_approval_intent(seeded_db, monkeypatch):
    from server import main as server_main
    engine = make_engine(monkeypatch)
    monkeypatch.setattr(server_main, "engine", engine)
    client = TestClient(server_main.app)
    assert client.post("/api/approve/AC-COMP-01").status_code == 400
    assert client.post("/api/reject/AC-COMP-01").status_code == 400
    response = client.post("/api/approve/AC-COMP-01", json={"requirement_id": "r", "intervention_id": "i",
                                                            "intervention_hash": "h", "context_revision": 1})
    assert response.status_code == 409 and response.json()["ok"] is False
    assert client.post("/api/approve/AC-COMP-01", json={"requirement_id": "r"}).status_code == 422
    assert client.get("/api/incidents/missing").status_code == 404
    assert client.post("/api/incidents/missing/execute", json={"intervention_id": "i", "intervention_hash": "h"}).status_code == 409
    # Trusted submissions are disabled unless the host boundary is explicitly declared trusted.
    body = {"expected_revision": 1, "confirmation": {}}
    assert client.post("/api/incidents/x/confirmations/technical", json=body).status_code in (403, 422)
    monkeypatch.delenv("OPERON_TRUSTED_SUBMISSIONS", raising=False)
    assert client.post("/api/incidents/x/drafts", json={"expected_revision": 1, "binding": {}}).status_code == 403
    # No endpoint accepts authority artifacts.
    paths = {route.path for route in server_main.app.routes}
    assert not any(token in path for path in paths for token in ("promotion", "verdict", "report"))


async def test_legacy_demo_path_requires_explicit_opt_in(seeded_db, monkeypatch):
    monkeypatch.setenv("OPERON_LEGACY_DEMO", "1")
    engine = make_engine(monkeypatch)
    assert engine.legacy_demo and engine.snapshot()["authority_path"] == "legacy-demo"
    monkeypatch.delenv("OPERON_LEGACY_DEMO")
    assert not make_engine(monkeypatch).legacy_demo
