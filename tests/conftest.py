"""
Shared test fixtures + environment isolation.

Runs BEFORE any `core` import so config picks up a throwaway SQLite file and a
clean, credential-free environment — tests must never touch the real data/poc.db
or make live LLM calls, regardless of the developer's shell or local .env.
"""
from __future__ import annotations
import os
import pathlib
import tempfile
import socket

# --- isolate BEFORE importing core (config resolves paths/creds at import) ----
_TMP_ROOT = tempfile.TemporaryDirectory(prefix="operon-pytest-")
_TMP_DB = pathlib.Path(_TMP_ROOT.name) / "poc.db"
os.environ["POC_DB_PATH"] = str(_TMP_DB)
os.environ["POC_MODEL_PATH"] = str(pathlib.Path(_TMP_ROOT.name) / "model.joblib")
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

# Neutralize provider creds. Empty (not absent) so python-dotenv's load_dotenv
# (override=False) won't repopulate GEMINI_API_KEY from a local .env.
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
for _k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE", "AWS_BEARER_TOKEN_BEDROCK",
           "SENTINEL_LLM_PROVIDER", "OPERON_AI_PROVIDER", "OPERON_OLLAMA_MODEL", "OPERON_OLLAMA_BASE_URL",
           "OPERON_GEMINI_MODEL", "OPERON_SPECIALIST_MODEL_ID", "OPERON_TRUSTED_SUBMISSIONS",
           "POC_FORCE_DETERMINISTIC", "OPERON_REASONING_BACKEND"):
    os.environ.pop(_k, None)
# A developer's ~/.aws/credentials must not make Bedrock look configured in tests.
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = str(pathlib.Path(_TMP_ROOT.name) / "no-aws-credentials")
for _k in [k for k in os.environ if k.startswith("SENTINEL_") and k.endswith("_ADAPTER")]:
    os.environ.pop(_k, None)
os.environ["POC_FORCE_DETERMINISTIC"] = "1"

import pytest  # noqa: E402
from core.db import init_schema  # noqa: E402
from core.seed_data import seed  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_database_and_network(tmp_path, monkeypatch):
    from core import config, db
    path = tmp_path / "operon.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setenv("POC_DB_PATH", str(path))

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"network access is blocked in tests: {address}")
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"network access is blocked in tests: {address}")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)

    def blocked_dns(*args, **kwargs):
        raise AssertionError("DNS/network access is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked_dns)


@pytest.fixture()
def seeded_db(_isolate_database_and_network):
    """Fresh schema + master data + wiped transactional tables."""
    init_schema()
    seed(reset=True)
    yield


@pytest.fixture(autouse=True)
def _clean_provider_registry():
    """The provider registry is process state; rebuild it from the clean environment per test."""
    from core.providers import reset
    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def _clean_service_cache():
    """Adapter selection is cached as singletons — reset around every test so a
    test that changes SENTINEL_*_ADAPTER can't leak into the next."""
    from core.services import reset_cache
    reset_cache()
    yield
    reset_cache()


def sample_proposal(seeded=True) -> dict:
    """A proposal shaped like agent.build_proposal produces, for governance/CMMS."""
    from core import tools
    tech = tools.assign_technician("COMPRESSOR")
    return {
        "equipment_id": "AC-COMP-01",
        "failure_mode": {"failure_mode_id": "FM-OSF"},
        "prediction": {"failure_prob": 0.91},
        "business": {"unplanned_loss": 109150.0, "recovered_value": 101150.0},
        "actions": {
            "work_order": {"priority": "HIGH", "detail": "test WO"},
            "technician": tech["technician"],
            "parts": tools.check_parts("AC-COMP-01"),
            "schedule": tools.block_schedule("AC-COMP-01", 45),
        },
    }


def prompt_context(messages, repository=None):
    """The trusted SpecialistContext behind an agent's first user message.

    Agents receive a compact rendering (core.agents.rendering) that every evidence
    record still validates from; fakes rebuild the context from the prompt alone,
    as a remote packet handler would. ``repository`` is accepted for call-site
    symmetry and unused: packet mode forbids store access.
    """
    from core.agents.contracts import SpecialistContext
    from core.agents.rendering import context_from_message
    return SpecialistContext.model_validate(context_from_message(messages[0]["content"][0]["text"]))
