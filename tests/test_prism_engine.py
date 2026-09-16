"""DemoEngine integration: PRISM sessions ride the engine's database, snapshot and websocket; reset and
restart behave; the Guided Demo and lifecycle remain untouched by PRISM revisions."""
from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from core.prism import RunStatus
from core.prism.slow_path import DeterministicSlowPathAdapter
from core.prism.testing import ControlledAdapter
from tests.test_engine_lifecycle import make_engine


async def wait_for(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


async def test_engine_exposes_prism_in_snapshot_and_reset_wipes_sessions(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    engine.prism.coordinator.adapter = engine.prism.adapter = ControlledAdapter()
    snapshot = engine.snapshot()
    assert snapshot["prism"]["sessions"] == [] and snapshot["prism"]["prism_version"] == 1
    session = await engine.prism.create_session()
    ack = await engine.prism.submit_message(session["session_id"], content="Investigate the compressor anomaly")
    assert await wait_for(lambda: engine.prism.repository.get_run(ack["slow_path"]["run_id"]).status == RunStatus.RUNNING)
    assert [s["session_id"] for s in engine.snapshot()["prism"]["sessions"]] == [session["session_id"]]
    await engine.reset(restart=False)
    assert engine.snapshot()["prism"]["sessions"] == [] and engine.prism.coordinator.handles == {}
    assert engine.prism.repository.list_sessions() == []


async def test_prism_session_links_to_a_real_incident_without_touching_it(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    engine.prism.coordinator.adapter = engine.prism.adapter = DeterministicSlowPathAdapter()
    await engine._advance()
    assert await wait_for(lambda: bool(engine.incidents))
    eid, incident = next(iter(engine.incidents.items()))
    before = engine.coordinator.repository.fetch_incident(incident.id)
    session = await engine.prism.create_session(incident_id=incident.id)
    await engine.prism.submit_message(session["session_id"], content="Investigate the compressor temperature anomaly.")
    assert await engine.prism.wait_idle(5)
    view = engine.prism.session_view(session["session_id"])
    assert view["incident"]["id"] == incident.id and view["canonical_revision"] == 1
    assert view["canonical"]["result"]["findings"][0].startswith(f"Incident {incident.id}")
    after = engine.coordinator.repository.fetch_incident(incident.id)
    assert after.revision == before.revision and after.phase == before.phase   # PRISM never wrote incident state
    await engine.prism.submit_message(session["session_id"], content="Correction: prioritize the vibration spike.")
    assert await engine.prism.wait_idle(5)
    assert engine.coordinator.repository.fetch_incident(incident.id).revision == before.revision


async def test_restarted_engine_recovers_prism_sessions_on_start(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    adapter = ControlledAdapter(ignore_cancellation=True)
    engine.prism.coordinator.adapter = engine.prism.adapter = adapter
    session = await engine.prism.create_session()
    sid = session["session_id"]
    one = await engine.prism.submit_message(sid, content="first instruction here")
    assert await wait_for(lambda: engine.prism.repository.get_run(one["slow_path"]["run_id"]).status == RunStatus.RUNNING)
    two = await engine.prism.submit_message(sid, content="second instruction here")
    assert await wait_for(lambda: engine.prism.repository.get_run(two["slow_path"]["run_id"]).status == RunStatus.RUNNING)
    for handle in engine.prism.coordinator.handles.values():   # process dies
        handle.task.cancel()
    await asyncio.sleep(0.02)
    restarted = make_engine(monkeypatch)
    restarted.prism.coordinator.adapter = restarted.prism.adapter = ControlledAdapter(auto_release=True)
    await restarted.start()
    await restarted.stop()
    assert restarted.prism.recovered and restarted.prism.recovered[0]["session_id"] == sid
    assert await restarted.prism.wait_idle(5)
    view = restarted.prism.session_view(sid)
    assert view["current_revision"] == 2 and view["canonical_revision"] == 2
    assert [(r["revision"], r["status"]) for r in view["runs"]] == [(1, "CANCELLED"), (2, "FAILED"), (2, "COMPLETED")]
    assert view["recovery"]["retried"]["attempt"] == 2
    ws_snapshot = restarted.snapshot()["prism"]
    assert ws_snapshot["recovered"][0]["session_id"] == sid


def test_websocket_stream_keeps_its_contract_and_carries_prism_events(seeded_db, monkeypatch):
    from server import main as server_main
    engine = make_engine(monkeypatch)
    engine.prism.coordinator.adapter = engine.prism.adapter = ControlledAdapter(auto_release=True)
    server_main.app.router.on_startup.clear()
    monkeypatch.setattr(server_main, "engine", engine)
    with TestClient(server_main.app) as client, client.websocket_connect("/ws") as ws:
        snapshot = json.loads(ws.receive_text())
        assert snapshot["type"] == "snapshot" and "fleet" in snapshot and "prism" in snapshot
        sid = client.post("/api/prism/sessions", json={}).json()["session"]["session_id"]
        first = json.loads(ws.receive_text())
        assert first["type"] == "prism" and first["prism_version"] == 1 and first["event"]["event_type"] == "session_created"
        assert first["session"]["session_id"] == sid
        client.post(f"/api/prism/sessions/{sid}/messages", json={"content": "Investigate the anomaly now"})
        seen = []
        while len(seen) < 6:
            message = json.loads(ws.receive_text())
            assert message["type"] == "prism"
            seen.append(message["event"]["event_type"])
        assert seen[:4] == ["turn_accepted", "fast_path_acknowledged", "slow_path_queued", "slow_path_started"]
        assert "canonical_state_updated" in seen
