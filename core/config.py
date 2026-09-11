"""
Central configuration for Operon reliability operations.

Every business assumption and tunable threshold lives here and is surfaced in the
UI, so the demo's value claims are transparent and defensible. All figures are
illustrative. This project is a generic, vendor-neutral portfolio POC — it is not
affiliated with, endorsed by, or built for any specific company.
"""
from __future__ import annotations
import os
from pathlib import Path

# Load a local .env if present (python-dotenv ships with uvicorn[standard]).
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Branding (generic / vendor-neutral)
# ---------------------------------------------------------------------------
APP_NAME = "Operon"
APP_TAGLINE = "Autonomous Reliability Operations for Industrial Systems"
PLANT_NAME = os.getenv("POC_PLANT_NAME", "Demo Manufacturing Plant 01")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CORE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CORE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
FRONTEND_BUILD = PROJECT_DIR / "frontend" / "dist"          # built React bundle (if present)
FRONTEND_LEGACY = PROJECT_DIR / "frontend" / "index.html"   # fallback static page

DATASET_CSV = Path(os.getenv("POC_DATASET", str(DATA_DIR / "ai4i2020.csv")))
DB_PATH = Path(os.getenv("POC_DB_PATH", str(DATA_DIR / "poc.db")))
MODEL_PATH = Path(os.getenv("POC_MODEL_PATH", str(DATA_DIR / "health_model.joblib")))

# ---------------------------------------------------------------------------
# Demo timing (compressed "time")
# ---------------------------------------------------------------------------
TICK_SECONDS = float(os.getenv("POC_TICK_SECONDS", "1.0"))   # wall-clock seconds between ticks
MINUTES_PER_TICK = 15        # each tick represents 15 min of plant time
TRIGGER_THRESHOLD = 0.80     # failure_prob at/above which the agent engages
WARN_THRESHOLD = 0.45        # amber band on the floor

# ---------------------------------------------------------------------------
# Business-value assumptions (all editable; surfaced in the UI)
#   Illustrative manufacturing-line economics for the value model.
# ---------------------------------------------------------------------------
DOWNTIME_COST_PER_HOUR = 11400.0     # $/hr of unplanned line downtime
UNPLANNED_OUTAGE_HOURS = 8.0         # a seized asset takes a line down ~8h
PLANNED_SWAP_HOURS = 0.75            # a scheduled swap during a micro-stop
SCRAP_PER_UNPLANNED_EVENT = 18500.0  # secondary scrap/rework on in-process failure
FLEET_LINES = 7                      # lines in the pilot factory

# Criticality weighting used by the agent's triage ranking.
CRITICALITY_WEIGHT = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.35}

def recovered_value() -> float:
    hours_avoided = UNPLANNED_OUTAGE_HOURS - PLANNED_SWAP_HOURS
    return hours_avoided * DOWNTIME_COST_PER_HOUR + SCRAP_PER_UNPLANNED_EVENT

def unplanned_loss() -> float:
    return UNPLANNED_OUTAGE_HOURS * DOWNTIME_COST_PER_HOUR + SCRAP_PER_UNPLANNED_EVENT

# ---------------------------------------------------------------------------
# OEE (illustrative line-level values for the value bar)
# ---------------------------------------------------------------------------
OEE_BASELINE = 0.712
OEE_TARGET = 0.855

# ---------------------------------------------------------------------------
# Step 13B lifecycle boundaries.
#
# The durable authoritative lifecycle (admission -> investigation -> promotion ->
# approval -> governed execution) is the default engine path. The pre-13B demo
# shortcut (prepare_legacy_intervention) is deprecated compatibility code and runs
# only when explicitly enabled. Trusted confirmation/binding HTTP endpoints are
# disabled unless the deployment explicitly declares its host boundary trusted.
# ---------------------------------------------------------------------------
def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


def legacy_demo_enabled() -> bool:
    return _flag("OPERON_LEGACY_DEMO")


def trusted_submissions_enabled() -> bool:
    return _flag("OPERON_TRUSTED_SUBMISSIONS")


# ---------------------------------------------------------------------------
# Agentic AI — pluggable LLM provider with a graceful deterministic fallback.
#
# For this POC-demo phase the default is **Google Gemini** (generous free tier —
# just drop a GEMINI_API_KEY in .env). **AWS Bedrock** is kept for the later
# scale / real-data phase. If no provider is configured/reachable, the agent
# silently uses a deterministic planner, so the repo always runs for anyone who
# clones it. No keys are ever committed.
#
# Provider selection (SENTINEL_LLM_PROVIDER): "auto" (default) tries Gemini, then
# Bedrock, then deterministic. Force one with "gemini" | "bedrock" | "deterministic".
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("SENTINEL_LLM_PROVIDER", "auto").strip().lower()
# Explicit off-switch for the hosted/public demo (forces deterministic mode).
FORCE_DETERMINISTIC = os.getenv("POC_FORCE_DETERMINISTIC", "").strip().lower() in ("1", "true", "yes")

# --- Google Gemini (default for the POC demo) ------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", "")).strip()
# 'gemini-flash-latest' is an alias that always maps to the current free-tier
# flash model, so the default keeps working as Google rotates model versions.
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-flash-latest")
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "1024"))
# Free-tier friendliness: cap requests/min (client-side token bucket) and retry
# transient 429/5xx with exponential backoff.
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "12"))
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "5"))

# --- AWS Bedrock (kept for the scale / real-data phase) --------------------
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
# Cross-region inference profile id works in most accounts; override per your access.
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_MAX_TOKENS = int(os.getenv("BEDROCK_MAX_TOKENS", "1024"))

# --- Step 15 reasoning backend (supervisor + specialists) -------------------
# OPERON_REASONING_BACKEND: none | local | packet | agentcore. Unset preserves the
# legacy behaviour: "local" when the legacy selector resolves to Bedrock, else none.
# Supervisor/specialist model ids default to BEDROCK_MODEL_ID; they are frozen into
# every run's expected runtime identity so a drifted deployment is refused.
BEDROCK_SUPERVISOR_MODEL_ID = os.getenv("OPERON_BEDROCK_SUPERVISOR_MODEL_ID", "").strip() or BEDROCK_MODEL_ID
BEDROCK_SPECIALIST_MODEL_ID = os.getenv("OPERON_BEDROCK_SPECIALIST_MODEL_ID", "").strip() or BEDROCK_SUPERVISOR_MODEL_ID


def reasoning_backend() -> str:
    """Resolve the configured reasoning backend mode; read at call time, never cached."""
    value = os.getenv("OPERON_REASONING_BACKEND", "").strip().lower()
    if value:
        return value
    return "local" if agent_mode() == "bedrock" else "none"


def gemini_available() -> bool:
    """True only if the google-genai SDK is importable AND an API key is set."""
    if FORCE_DETERMINISTIC or not GEMINI_API_KEY:
        return False
    try:
        import google.genai  # noqa: F401
    except Exception:
        return False
    return True


def bedrock_available() -> bool:
    """True only if boto3 is importable AND some AWS credential is resolvable."""
    if FORCE_DETERMINISTIC:
        return False
    try:
        import boto3  # noqa: F401
        import botocore  # noqa: F401
    except Exception:
        return False
    # Explicit env creds or a resolvable profile/role.
    if os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"):
        return True
    try:
        import botocore.session
        return botocore.session.get_session().get_credentials() is not None
    except Exception:
        return False


def agent_mode() -> str:
    """Resolve the active agent provider: 'gemini' | 'bedrock' | 'deterministic'."""
    if FORCE_DETERMINISTIC:
        return "deterministic"
    if LLM_PROVIDER == "gemini":
        return "gemini" if gemini_available() else "deterministic"
    if LLM_PROVIDER == "bedrock":
        return "bedrock" if bedrock_available() else "deterministic"
    if LLM_PROVIDER == "deterministic":
        return "deterministic"
    # auto: prefer Gemini's free tier for the POC, then Bedrock, then fallback.
    if gemini_available():
        return "gemini"
    if bedrock_available():
        return "bedrock"
    return "deterministic"


# ---------------------------------------------------------------------------
# Peer agents (Governance + Monitoring) — reached via the services layer.
#
# By default these run in-process as deterministic policy/correlation engines
# (offline, bullet-proof). Set SENTINEL_GOVERNANCE_ADAPTER=a2a /
# SENTINEL_MONITORING_ADAPTER=a2a to reach them over the A2A protocol instead
# (start the peer server: `uv run python -m a2a_app.server`). A2A is for agents;
# MCP is for tools.
# ---------------------------------------------------------------------------
# Governance policy: financial exposure above this needs manager co-sign (CONDITIONS).
GOVERNANCE_AUTO_APPROVE_LIMIT = float(os.getenv("SENTINEL_GOV_APPROVE_LIMIT", "120000"))
# A2A peer server location (used by the 'a2a' adapters and the peer server).
A2A_HOST = os.getenv("SENTINEL_A2A_HOST", "127.0.0.1")
A2A_PORT = int(os.getenv("SENTINEL_A2A_PORT", "8200"))
A2A_BASE_URL = os.getenv("SENTINEL_A2A_BASE", f"http://{A2A_HOST}:{A2A_PORT}")
