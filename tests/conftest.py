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

# --- isolate BEFORE importing core (config resolves paths/creds at import) ----
_TMP_DB = pathlib.Path(tempfile.gettempdir()) / "sentinel_pytest_poc.db"
os.environ["POC_DB_PATH"] = str(_TMP_DB)

# Neutralize provider creds. Empty (not absent) so python-dotenv's load_dotenv
# (override=False) won't repopulate GEMINI_API_KEY from a local .env.
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
for _k in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "SENTINEL_LLM_PROVIDER",
           "POC_FORCE_DETERMINISTIC"):
    os.environ.pop(_k, None)
for _k in [k for k in os.environ if k.startswith("SENTINEL_") and k.endswith("_ADAPTER")]:
    os.environ.pop(_k, None)

import pytest  # noqa: E402
from core.db import init_schema  # noqa: E402
from core.seed_data import seed  # noqa: E402
from core.db import reset_transactional  # noqa: E402


@pytest.fixture()
def seeded_db():
    """Fresh schema + master data + wiped transactional tables."""
    init_schema()
    seed()
    reset_transactional()
    yield


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
