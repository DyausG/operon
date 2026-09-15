"""The FastAPI host serves the SPA for client-side routes and keeps API 404s as JSON."""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from server import main as server_main

    # Startup would launch the engine loop; the routing under test does not need it.
    server_main.app.router.on_startup.clear()
    with TestClient(server_main.app) as c:
        yield c


def test_client_routes_resolve_to_the_document(client):
    from core import config
    html_expected = (config.FRONTEND_BUILD / "index.html").exists()
    for path in ("/login", "/app/dashboard", "/app/incidents/DEMO-INCIDENT-01", "/app/settings"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html"), path
        if html_expected:
            assert 'id="root"' in r.text, path


def test_unknown_api_paths_stay_json_404(client):
    for path in ("/api/nope", "/api/incidents", "/assets/missing.js"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json"), path
