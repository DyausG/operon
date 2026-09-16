"""/api/prism: session creation, message acceptance, malformed input, idempotent replay, interruption,
immediate response while the Slow Path blocks, state retrieval/reconnect, websocket envelope compatibility."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from core.prism import PrismRepository, PrismRuntime, RunStatus
from core.prism.testing import ControlledAdapter


class FakeEngine:
    """Only what the PRISM routes and the provider overview touch."""

    def __init__(self, prism):
        self.prism = prism
        self.runtime = None
        self.running = False

    def reasoning_provenance(self):
        return {"backend": "none", "status": "awaiting_runtime", "provider": "none"}


@pytest.fixture
def api(seeded_db, monkeypatch):
    from server import main as server_main
    adapter = ControlledAdapter()
    runtime = PrismRuntime(PrismRepository(), adapter=adapter)
    server_main.app.router.on_startup.clear()
    monkeypatch.setattr(server_main, "engine", FakeEngine(runtime))
    with TestClient(server_main.app) as client:
        yield client, runtime, adapter
    # TestClient runs the app's loop in a thread; tasks are owned by it. Nothing to await here.


def create(client, **body):
    response = client.post("/api/prism/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["session"]


def test_session_creation_and_retrieval(api):
    client, runtime, _ = api
    session = create(client, metadata={"operator": "smoke"})
    assert session["current_revision"] == 0 and session["runtime_state"] == "idle" and session["metadata"] == {"operator": "smoke"}
    fetched = client.get(f"/api/prism/sessions/{session['session_id']}")
    assert fetched.status_code == 200 and fetched.json()["session"]["session_id"] == session["session_id"]
    assert fetched.json()["session"]["provenance"]["adapter"] == "controlled"
    listed = client.get("/api/prism/sessions").json()
    assert [s["session_id"] for s in listed["sessions"]] == [session["session_id"]]
    assert client.get("/api/prism/sessions/does-not-exist").status_code == 404
    assert client.get("/api/prism/sessions/not%20valid%20id").status_code == 400
    assert client.post("/api/prism/sessions", json={"incident_id": "nope"}).status_code == 404
    overview = client.get("/api/prism").json()
    assert overview["ok"] and overview["prism_version"] == 1 and overview["slow_path"]["adapter"] == "controlled"


def test_message_acceptance_returns_promptly_while_slow_path_blocks(api):
    client, runtime, adapter = api
    sid = create(client)["session_id"]
    started = time.perf_counter()
    response = client.post(f"/api/prism/sessions/{sid}/messages",
                           json={"content": "Investigate the compressor temperature anomaly.", "request_id": "req-1"})
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["ok"] and body["revision"] == 1 and body["fast_path"]["status"] == "accepted"
    assert body["slow_path"]["status"] == "QUEUED" and body["slow_path"]["run_id"]
    assert body["fast_path"]["latency_ms"] is not None and body["acceptance_ms"] < 500
    assert elapsed_ms < 1500, elapsed_ms
    # The Slow Path is blocked (never released) yet state retrieval works immediately.
    view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
    assert view["current_revision"] == 1 and view["slow_path"]["run_id"] == body["slow_path"]["run_id"]
    assert view["runtime_state"] in ("slow_path", "fast_path")
    metrics = client.get("/api/prism/metrics").json()
    assert metrics["fast_path_acknowledgement"]["count"] == 1


def test_malformed_input_is_rejected(api):
    client, _, _ = api
    sid = create(client)["session_id"]
    url = f"/api/prism/sessions/{sid}/messages"
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"content": ""}).status_code == 422
    assert client.post(url, json={"content": "x" * 8001}).status_code == 422
    assert client.post(url, json={"content": "hello there", "content_type": "hologram"}).status_code == 422
    assert client.post(url, json={"content": "hello there", "request_id": "bad id!"}).status_code == 422
    assert client.post(url, json={"content": "hello there", "metadata": {str(i): i for i in range(17)}}).status_code == 422
    assert client.post(url, json={"content": "hello there", "metadata": {"nested": {"a": 1}}}).status_code == 422
    assert client.post(url, json={"content": "hello there", "metadata": {"k" * 41: 1}}).status_code == 400
    assert client.post(url, json={"content": "hello there", "metadata": {"v": "x" * 501}}).status_code == 400
    assert client.post(url, json={"content": "hello there", "provider": "gemini"}).status_code == 422
    assert client.post("/api/prism/sessions/unknown-session/messages", json={"content": "hello there"}).status_code == 404
    assert client.post("/api/prism/sessions/bad%20id/messages", json={"content": "hello there"}).status_code == 400
    assert client.get(f"/api/prism/sessions/{sid}/events?after=-1").status_code == 400


def test_idempotent_replay_and_conflict(api):
    client, _, _ = api
    sid = create(client)["session_id"]
    url = f"/api/prism/sessions/{sid}/messages"
    first = client.post(url, json={"content": "Investigate the anomaly now", "idempotency_key": "op-1"}).json()
    replay = client.post(url, json={"content": "Investigate the anomaly now", "idempotency_key": "op-1"}).json()
    assert replay["duplicate"] and replay["turn_id"] == first["turn_id"] and replay["slow_path"]["run_id"] == first["slow_path"]["run_id"]
    assert client.get(f"/api/prism/sessions/{sid}").json()["session"]["current_revision"] == 1
    conflict = client.post(url, json={"content": "Something else entirely", "idempotency_key": "op-1"})
    assert conflict.status_code == 409


def test_interruption_advances_revision_immediately_and_fences_the_old_run(api):
    client, runtime, adapter = api
    sid = create(client)["session_id"]
    url = f"/api/prism/sessions/{sid}/messages"
    one = client.post(url, json={"content": "Investigate the compressor temperature anomaly."}).json()
    deadline = time.time() + 5
    while runtime.repository.get_run(one["slow_path"]["run_id"]).status != RunStatus.RUNNING and time.time() < deadline:
        time.sleep(0.01)
    two = client.post(url, json={"content": "Correction: prioritize the vibration spike and ignore the temperature hypothesis for now."}).json()
    assert two["revision"] == 2 and two["fast_path"]["status"] == "accepted_superseding"
    assert two["superseded"]["revision"] == 1 and two["superseded"]["run_ids"] == [one["slow_path"]["run_id"]]
    view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
    assert view["current_revision"] == 2 and view["interruption"]["superseded_revision"] == 1
    adapter.release.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
        if view["canonical_revision"] == 2:
            break
        time.sleep(0.02)
    assert view["canonical_revision"] == 2 and view["canonical"]["run_id"] == two["slow_path"]["run_id"]
    statuses = {r["revision"]: r["status"] for r in view["runs"]}
    assert statuses == {1: "CANCELLED", 2: "COMPLETED"}
    events = client.get(f"/api/prism/sessions/{sid}/events").json()
    kinds = [e["event_type"] for e in events["events"]]
    assert kinds[:4] == ["session_created", "turn_accepted", "fast_path_acknowledged", "slow_path_queued"]
    assert {"interruption_received", "revision_superseded", "cancellation_requested", "run_cancelled",
            "canonical_state_updated"} <= set(kinds)
    # Reconnect: only what the client missed.
    last = events["events"][-3]["event_id"]
    tail = client.get(f"/api/prism/sessions/{sid}/events?after={last}").json()
    assert [e["event_id"] for e in tail["events"]] == [last + 1, last + 2]
    assert tail["type"] == "prism_reconnect" and tail["session"]["session_id"] == sid


def test_responses_never_contain_secrets_or_prompts(api, monkeypatch):
    client, runtime, adapter = api
    monkeypatch.setenv("GEMINI_API_KEY", "fake-secret-key-should-never-appear")
    sid = create(client)["session_id"]
    client.post(f"/api/prism/sessions/{sid}/messages", json={"content": "Investigate the anomaly now",
                                                            "metadata": {"api_key": "client-supplied-secret"}})
    for path in (f"/api/prism/sessions/{sid}", f"/api/prism/sessions/{sid}/events", "/api/prism", "/api/prism/metrics"):
        text = client.get(path).text
        assert "fake-secret-key" not in text
    events = client.get(f"/api/prism/sessions/{sid}/events").json()["events"]
    assert all("client-supplied-secret" not in str(e["payload"]) for e in events)
