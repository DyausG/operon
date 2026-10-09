"""F1.2 HTTP contracts: work routes, gates, idempotent replay and the projection fields (M4).

The routes keep the F1.1 response shape ({ok, command, result_id, incident}) and add
``replayed``. Field-response routes stay behind the sandbox gate; production refuses
every unauthenticated human command; the server, not the caller, decides actor kind and
report provenance.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from server import main as server_main
from tests.test_engine_lifecycle import ASSET
from tests.test_f1_2_invariants import to_approval
from core.reliability.repository import utcnow


def test_new_routes_exist_and_respect_the_route_name_contract():
    paths = {route.path for route in server_main.app.routes}
    assert "/api/incidents/{incident_id}/work/{assignment_id}/decline" in paths
    assert "/api/incidents/{incident_id}/commands/reassign_work" in paths
    assert not any(token in path for path in paths for token in ("promotion", "verdict", "report"))


def test_field_response_routes_are_gated_and_production_refuses_humans(monkeypatch):
    calls = []

    async def command(incident_id, name, **arguments):
        calls.append((name, arguments))
        return {"ok": True}
    monkeypatch.setattr(server_main, "engine", SimpleNamespace(lifecycle_command=command, legacy_demo=False))
    client = TestClient(server_main.app)
    decline = {"expected_revision": 1, "actor_id": "tech-7", "reason": "no access"}
    reassign = {"expected_revision": 1, "actor_id": "dispatcher", "rationale": "second crew", "assignment_id": "a-1"}
    assert client.post("/api/incidents/i-1/work/a-1/decline", json=decline).status_code == 403  # unspecified env
    assert client.post("/api/incidents/i-1/commands/reassign_work", json=reassign).status_code == 200
    assert calls[-1][1]["actor"].kind == "DECLARED"
    monkeypatch.setenv("OPERON_ENVIRONMENT", "sandbox")
    assert client.post("/api/incidents/i-1/work/a-1/decline", json=decline).status_code == 200
    assert calls[-1][0] == "decline_work" and calls[-1][1]["actor"].kind == "SANDBOX"
    report = {"expected_revision": 1, "actor_id": "tech-7", "result": "COMPLETED", "summary": "done",
              "performed_at": utcnow().isoformat(), "asset_intervened": True, "provenance": "OBSERVED"}
    assert client.post("/api/incidents/i-1/work/a-1/response", json=report).status_code == 422  # caller cannot choose
    report.pop("provenance")
    assert client.post("/api/incidents/i-1/work/a-1/response", json=report).status_code == 200
    assert calls[-1][1]["provenance"] == "SIMULATED"  # work about the simulated plant is simulated
    monkeypatch.setenv("OPERON_ENVIRONMENT", "production")
    for path, body in (("/api/incidents/i-1/work/a-1/decline", decline),
                       ("/api/incidents/i-1/commands/reassign_work", reassign)):
        assert client.post(path, json=body).status_code == 403


async def test_work_over_http_end_to_end_with_replay_and_projection(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock)
    assert (await engine.approve(ASSET, intent))["ok"]
    monkeypatch.setattr(server_main, "engine", engine)
    monkeypatch.setenv("OPERON_TRUSTED_SUBMISSIONS", "1")  # opens the human-input routes in the local mode
    client = TestClient(server_main.app)
    view = client.get(f"/api/incidents/{bridge.incident_id}").json()
    assert view["verification"]["state"] == "AWAITING_WORK" and view["plant"]["actuator"] == "simulator"
    assert {"work_assignments", "work_reports", "plant_actuations"} <= set(view["read_model"])
    assignment_id = view["work"][0]["assignment_id"]
    base = f"/api/incidents/{bridge.incident_id}/work/{assignment_id}"
    ack = {"expected_revision": view["revision"], "actor_id": "tech-7", "actor_role": "technician", "request_key": "ack-1"}
    first = client.post(f"{base}/acknowledge", json=ack)
    assert first.status_code == 200 and first.json()["replayed"] is False
    again = client.post(f"{base}/acknowledge", json=ack)  # retry with the old revision
    assert again.status_code == 200 and again.json()["replayed"] is True
    revision = again.json()["incident"]["revision"]
    bad = client.post(f"{base}/response", json={"expected_revision": revision, "actor_id": "tech-7", "result": "COMPLETED",
                                                 "summary": "done", "performed_at": utcnow().isoformat()})
    assert bad.status_code == 409 and "asset_intervened" in bad.json()["error"]
    report = {"expected_revision": revision, "actor_id": "tech-7", "result": "COMPLETED", "summary": "Overhaul performed",
              "performed_at": utcnow().isoformat(), "asset_intervened": True, "request_key": "report-1"}
    done = client.post(f"{base}/response", json=report)
    assert done.status_code == 200, done.json()
    body = done.json()["incident"]
    assert body["work"][0]["state"] == "REPORTED" and body["work"][0]["eligible"] is True
    assert body["work"][0]["provenance"] == "SIMULATED"
    assert body["verification"]["state"] == "COLLECTING" and body["verification"]["work_report_id"]
    assert body["plant"]["actuations"][0]["status"] == "APPLIED"
    assert client.post(f"{base}/response", json=report).json()["replayed"] is True
    stale = client.post(f"{base}/decline", json={"expected_revision": 1, "actor_id": "tech-7", "reason": "x"})
    assert stale.status_code == 409 and stale.json()["ok"] is False  # stale revision; nothing written
