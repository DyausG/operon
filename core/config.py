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
# Agentic AI — provider-agnostic model layer (see core/providers and docs/PROVIDERS.md).
#
# Provider choice is independent from Operon's reliability domain logic. The
# registry in core.providers selects Gemini, Ollama (local), Bedrock or none from
# OPERON_AI_PROVIDER (legacy alias SENTINEL_LLM_PROVIDER): "auto" (default) picks
# the first *configured* cloud provider, else none. With no provider Operon runs
# deterministically and reports model-backed reasoning as unavailable; it never
# fabricates reasoning. POC_FORCE_DETERMINISTIC=1 forces the no-provider mode.
# The constants below are kept for compatibility; the registry is authoritative.
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("OPERON_AI_PROVIDER", os.getenv("SENTINEL_LLM_PROVIDER", "auto")).strip().lower()
FORCE_DETERMINISTIC = os.getenv("POC_FORCE_DETERMINISTIC", "").strip().lower() in ("1", "true", "yes")

# --- Google Gemini -------------------------------------------------------------
# The API key is never held in this module; it lives only inside the provider registry.
GEMINI_MODEL_ID = os.getenv("OPERON_GEMINI_MODEL", os.getenv("GEMINI_MODEL_ID", "gemini-flash-latest"))
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "1024"))
# Free-tier friendliness: cap requests/min (client-side token bucket) and retry
# transient 429/5xx with exponential backoff.
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "12"))
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "5"))

# --- Ollama / local models ---------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OPERON_OLLAMA_BASE_URL", os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"))
OLLAMA_MODEL = os.getenv("OPERON_OLLAMA_MODEL", "")

# --- AWS Bedrock (optional; no AWS credentials are required to start) --------
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
# Cross-region inference profile id works in most accounts; override per your access.
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_MAX_TOKENS = int(os.getenv("BEDROCK_MAX_TOKENS", "1024"))

# --- Step 15 reasoning backend (supervisor + specialists) -------------------
# OPERON_REASONING_BACKEND: none | local | packet | agentcore. Unset resolves to
# "local" whenever a model provider is configured, else "none". local/packet build
# their Strands runtimes from the active provider; agentcore is Bedrock-only.
# Model ids are frozen into every run's expected runtime identity so a drifted
# deployment is refused.
BEDROCK_SUPERVISOR_MODEL_ID = os.getenv("OPERON_BEDROCK_SUPERVISOR_MODEL_ID", "").strip() or BEDROCK_MODEL_ID
BEDROCK_SPECIALIST_MODEL_ID = os.getenv("OPERON_BEDROCK_SPECIALIST_MODEL_ID", "").strip() or BEDROCK_SUPERVISOR_MODEL_ID


def reasoning_backend() -> str:
    """Resolve the configured reasoning backend mode; read at call time, never cached."""
    value = os.getenv("OPERON_REASONING_BACKEND", "").strip().lower()
    if value:
        return value
    return "local" if agent_mode() != "deterministic" else "none"


def provider_registry():
    """The process provider registry (lazy; constructing it performs no I/O)."""
    from core.providers import get_registry
    return get_registry()


def gemini_available() -> bool:
    """True only if the google-genai SDK is importable AND an API key is configured."""
    if FORCE_DETERMINISTIC or not provider_registry().build("gemini").configured():
        return False
    try:
        import google.genai  # noqa: F401
    except Exception:
        return False
    return True


def bedrock_available() -> bool:
    """True only if boto3 is importable AND AWS credentials are configured (env/profile/role/file)."""
    if FORCE_DETERMINISTIC or not provider_registry().build("bedrock").configured():
        return False
    try:
        import boto3  # noqa: F401
        import botocore  # noqa: F401
    except Exception:
        return False
    return True


def ollama_available() -> bool:
    """True only if an Ollama model is configured (reachability is verified by Test Connection)."""
    return not FORCE_DETERMINISTIC and provider_registry().build("ollama").configured()


def agent_mode() -> str:
    """Resolve the active provider: 'gemini' | 'ollama' | 'bedrock' | 'deterministic'.

    Legacy name kept for the API/UI; the provider registry decides. No network.
    """
    if FORCE_DETERMINISTIC:
        return "deterministic"
    kind = provider_registry().resolve_kind()
    return "deterministic" if kind == "none" else kind


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
