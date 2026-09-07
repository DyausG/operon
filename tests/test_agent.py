"""Agent: provider selection, rate limiter, tool conversion, governance + fallback."""
from __future__ import annotations
import time

import pytest

from core import agent, config


# --------------------------------------------------------------- provider ----
@pytest.mark.parametrize("provider,gem,bed,expected", [
    ("auto", True, True, "gemini"),        # auto prefers gemini
    ("auto", False, True, "bedrock"),
    ("auto", False, False, "deterministic"),
    ("gemini", False, True, "deterministic"),   # explicit gemini but unavailable
    ("bedrock", True, False, "deterministic"),
    ("deterministic", True, True, "deterministic"),
])
def test_agent_mode_selection(monkeypatch, provider, gem, bed, expected):
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", False)
    monkeypatch.setattr(config, "LLM_PROVIDER", provider)
    monkeypatch.setattr(config, "gemini_available", lambda: gem)
    monkeypatch.setattr(config, "bedrock_available", lambda: bed)
    assert config.agent_mode() == expected


def test_force_deterministic_overrides_everything(monkeypatch):
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", True)
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(config, "gemini_available", lambda: True)
    assert config.agent_mode() == "deterministic"


# ------------------------------------------------------------- rate limit ----
def test_rate_limiter_capacity_bounds():
    assert agent._RateLimiter(3).capacity == 3
    assert agent._RateLimiter(100).capacity == 6   # burst capped at 6
    assert agent._RateLimiter(0).capacity == 1


def test_rate_limiter_bursts_then_refills():
    rl = agent._RateLimiter(60)                # capacity 6, refill 1 token/sec
    for _ in range(rl.capacity):               # drain the bucket fast
        rl.acquire()
    # simulate 3s elapsed instead of sleeping -> 3 tokens available, no wait
    rl.last -= 3.0
    t0 = time.monotonic()
    rl.acquire()
    assert time.monotonic() - t0 < 0.1


# --------------------------------------------------------- tool conversion ---
def test_gemini_tool_conversion_matches_spec():
    decls = agent._gemini_tools()[0].function_declarations
    names = {d.name for d in decls}
    spec_names = {t["toolSpec"]["name"] for t in agent._TOOLS_SPEC}
    assert names == spec_names
    assert all(d.parameters_json_schema is not None for d in decls)


# ----------------------------------------------------------------- decide ----
def _ctx():
    return {
        "equipment_id": "AC-COMP-01", "equipment_name": "Instrument Air Compressor 01",
        "equipment_class": "COMPRESSOR", "criticality": "HIGH",
        "failure_mode": {"failure_mode_id": "FM-OSF", "mode_code": "OSF",
                         "failure_mode_name": "Overstrain Failure",
                         "description": "x.", "recommended_action": "Service.",
                         "est_planned_minutes": 45},
        "mode_prediction": {"mode": "OSF", "mode_label": "Overstrain Failure"},
        "prediction": {"failure_prob": 0.91, "health_score": 0.05},
        "drivers": [{"label": "Torque", "value": 62.0, "contribution": 0.34}],
    }


def test_decide_deterministic_includes_governance_step(seeded_db, monkeypatch):
    monkeypatch.setattr(config, "agent_mode", lambda: "deterministic")
    p = agent.decide(_ctx())
    assert p["mode"] == "deterministic"
    assert p["governance"]["decision"] in ("APPROVE", "CONDITIONS", "VETO")
    titles = [s["title"] for s in p["trace"]]
    assert any(t.startswith("Governance ruling") for t in titles)
    # governance sits just before the final Recommendation step
    assert titles[-1] == "Recommendation"
    assert titles[-2].startswith("Governance ruling")


def test_decide_falls_back_when_provider_errors(seeded_db, monkeypatch):
    monkeypatch.setattr(config, "agent_mode", lambda: "gemini")

    def boom(baseline, ctx):
        raise RuntimeError("simulated provider outage")

    monkeypatch.setitem(agent._ENHANCERS, "gemini", boom)
    p = agent.decide(_ctx())
    assert p["mode"] == "deterministic"          # graceful fallback
    assert "llm_error" in p and "simulated provider outage" in p["llm_error"]
    assert p["governance"]["decision"]           # governance still applied
