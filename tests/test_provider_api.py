"""/api/providers: status without secrets, selection, non-secret updates, session secrets, connection tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core import config
from core.providers import ProviderError
from core.providers.base import Capabilities

FAKE_KEY = "fake-gemini-key-for-tests-1234567890"


class FakeEngine:
    def __init__(self):
        self.runtime = None
        self.running = False
        self.reconfigured = 0

    async def reconfigure_runtime(self):
        self.reconfigured += 1
        return {"ok": True}

    def reasoning_provenance(self):
        return {"backend": "none", "status": "awaiting_runtime", "provider": "none"}


@pytest.fixture
def api(monkeypatch):
    from server import main as server_main
    engine = FakeEngine()
    server_main.app.router.on_startup.clear()
    monkeypatch.setattr(server_main, "engine", engine)
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", False)
    from core.providers import ProviderConfig, reset
    reset(ProviderConfig())
    with TestClient(server_main.app) as client:
        yield client, engine


def test_overview_reports_every_provider_without_secrets(api):
    client, _ = api
    r = client.get("/api/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["active"] == "none" and body["selection"] == "auto"
    assert set(body["providers"]) == {"none", "gemini", "ollama", "bedrock"}
    assert body["providers"]["gemini"]["credential"] == {"configured": False, "source": "none",
                                                         "detail": "GEMINI_API_KEY is not set"}
    assert body["providers"]["ollama"]["capabilities"]["locality"] == "local"
    assert body["reasoning_backend"] == "none" and body["supervisor_available"] is False
    health = client.get("/api/health").json()
    assert health["provider"] == "none" and health["agent_mode"] == "deterministic"


def test_select_and_update_non_secret_fields(api):
    client, engine = api
    r = client.post("/api/providers/select", json={"provider": "ollama", "model": "gemma3"})
    assert r.status_code == 200 and r.json()["active"] == "ollama"
    assert r.json()["providers"]["ollama"]["model"] == "gemma3" and engine.reconfigured == 1
    r = client.put("/api/providers/ollama", json={"base_url": "http://gpu-box:11434"})
    assert r.status_code == 200 and r.json()["status"]["endpoint"] == "http://gpu-box:11434"
    assert client.get("/api/health").json()["provider"] == "ollama"
    r = client.put("/api/providers/ollama", json={"base_url": "nope"})
    assert r.status_code == 400 and "invalid ollama configuration" in r.json()["error"]
    r = client.put("/api/providers/ollama", json={"region": "eu-west-1"})
    assert r.status_code == 400 and "does not accept" in r.json()["error"]
    r = client.put("/api/providers/none", json={"model": "x"})
    assert r.status_code == 404
    r = client.post("/api/providers/select", json={"provider": "openai"})
    assert r.status_code == 400 and "unknown provider selection" in r.json()["error"]
    r = client.put("/api/providers/bedrock", json={"region": "eu-central-1", "model_id": "eu.anthropic.test"})
    assert r.status_code == 200 and r.json()["status"]["region"] == "eu-central-1"
    r = client.put("/api/providers/bedrock", json={"unknown": 1})
    assert r.status_code == 422


def test_ollama_context_and_timeouts_are_updatable_and_reported(api):
    client, engine = api
    r = client.put("/api/providers/ollama", json={"model": "qwen2.5:7b", "num_ctx": 32768, "timeout_seconds": 420,
                                                  "run_timeout_seconds": 2400})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    status = r.json()["status"]
    assert status["settings"]["num_ctx"] == 32768 and status["settings"]["timeout_seconds"] == 420
    assert status["timeouts"]["first_token_seconds"] == 420 and status["timeouts"]["run_seconds"] == 2400
    assert status["timeouts"]["invocation_seconds"] == 900  # untouched fields keep the local defaults
    overview = client.get("/api/providers").json()
    assert overview["providers"]["ollama"]["settings"]["num_ctx"] == 32768
    r = client.put("/api/providers/ollama", json={"num_ctx": 512})
    assert r.status_code == 400 and "num_ctx" in r.json()["error"]
    r = client.put("/api/providers/gemini", json={"num_ctx": 8192})
    assert r.status_code == 400 and "does not accept" in r.json()["error"]


def test_session_secret_is_accepted_from_loopback_and_never_returned(api):
    client, engine = api
    r = client.put("/api/providers/gemini", json={"api_key": FAKE_KEY, "model": "gemini-2.5-flash"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"]["credential"] == {"configured": True, "source": "session", "detail": "API key present (server-side)"}
    assert FAKE_KEY not in r.text
    assert FAKE_KEY not in client.get("/api/providers").text
    assert config.provider_registry().config.gemini.key() == FAKE_KEY       # held in memory only
    assert FAKE_KEY not in config.provider_registry().config.model_dump_json()
    r = client.post("/api/providers/select", json={"provider": "gemini"})
    assert r.json()["active"] == "gemini" and r.json()["reasoning_backend"] == "local"
    r = client.put("/api/providers/gemini", json={"api_key": ""})
    assert r.json()["status"]["credential"]["configured"] is False


def test_session_secret_is_refused_from_a_non_loopback_client(api, monkeypatch):
    client, _ = api
    from server import providers_api
    monkeypatch.setattr(providers_api, "LOOPBACK_HOSTS", frozenset())
    r = client.put("/api/providers/gemini", json={"api_key": FAKE_KEY})
    assert r.status_code == 403 and "loopback" in r.json()["error"]
    assert config.provider_registry().config.gemini.key() is None
    monkeypatch.setenv("OPERON_TRUSTED_SUBMISSIONS", "1")
    r = client.put("/api/providers/gemini", json={"api_key": FAKE_KEY})
    assert r.status_code == 200 and FAKE_KEY not in r.text


def test_connection_test_uses_the_provider_and_normalized_errors(api, monkeypatch):
    client, _ = api
    registry = config.provider_registry()

    def fake_test(kind, *, timeout=None):
        provider = registry.build(kind)
        if kind == "ollama":
            return provider._failed(ProviderError("provider_unreachable", "Ollama is not running", provider="ollama"))
        return provider._status(reachable=True, probe="connection", detail="ok",
                                capabilities=Capabilities(text_generation=True, locality="cloud"))
    monkeypatch.setattr(registry, "test", fake_test)
    r = client.post("/api/providers/ollama/test")
    assert r.status_code == 200 and r.json()["ok"] is False
    assert r.json()["status"]["error"]["code"] == "provider_unreachable"
    r = client.post("/api/providers/gemini/test")
    assert r.json()["ok"] is True and r.json()["status"]["reachable"] is True
    assert r.json()["status"]["capabilities"]["text_generation"] is True
    assert client.post("/api/providers/openai/test").status_code == 404


def test_no_provider_test_connection_is_truthful(api):
    client, _ = api
    r = client.post("/api/providers/none/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["status"]["reachable"] is None and "deterministic" in r.json()["status"]["detail"].lower()
