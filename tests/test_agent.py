"""Agent: provider selection, rate limiter, tool conversion, governance + fallback."""
from __future__ import annotations
import time

import pytest

from core import agent, config


# --------------------------------------------------------------- provider ----
def _registry(monkeypatch, env):
    from core.providers import config_from_environment, reset
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", False)
    return reset(config_from_environment(env))


GEMINI = {"GEMINI_API_KEY": "fake-key-for-tests-000000"}
BEDROCK = {"AWS_PROFILE": "operon-test"}


@pytest.mark.parametrize("provider,gem,bed,expected", [
    ("auto", True, True, "gemini"),        # auto prefers gemini
    ("auto", False, True, "bedrock"),
    ("auto", False, False, "deterministic"),
    ("gemini", False, True, "gemini"),          # explicit selection is honoured and reported unconfigured
    ("bedrock", True, False, "bedrock"),
    ("deterministic", True, True, "deterministic"),
    ("none", True, True, "deterministic"),
])
def test_agent_mode_selection(monkeypatch, provider, gem, bed, expected):
    env = {"OPERON_AI_PROVIDER": provider}
    if gem:
        env |= GEMINI
    if bed:
        env |= BEDROCK
        monkeypatch.setenv("AWS_PROFILE", "operon-test")
    registry = _registry(monkeypatch, env)
    assert config.agent_mode() == expected
    if expected != "deterministic":
        assert registry.status().configured is ({"gemini": gem, "bedrock": bed}[expected])


def test_force_deterministic_overrides_everything(monkeypatch):
    _registry(monkeypatch, {"OPERON_AI_PROVIDER": "gemini", **GEMINI})
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", True)
    assert config.agent_mode() == "deterministic"
    _registry(monkeypatch, {"OPERON_AI_PROVIDER": "gemini", "POC_FORCE_DETERMINISTIC": "1", **GEMINI})
    assert config.agent_mode() == "deterministic"


def test_legacy_selector_alias_still_works(monkeypatch):
    assert _registry(monkeypatch, {"SENTINEL_LLM_PROVIDER": "gemini", **GEMINI}).resolve_kind() == "gemini"
    assert config.agent_mode() == "gemini"


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


def test_decide_keeps_baseline_for_ollama_without_a_legacy_loop(seeded_db, monkeypatch):
    monkeypatch.setattr(config, "agent_mode", lambda: "ollama")
    p = agent.decide(_ctx())
    assert p["mode"] == "deterministic" and "no legacy tool-calling loop" in p["llm_note"]


def test_decide_falls_back_when_provider_errors(seeded_db, monkeypatch):
    monkeypatch.setattr(config, "agent_mode", lambda: "gemini")

    def boom(baseline, ctx):
        raise RuntimeError("simulated provider outage")

    monkeypatch.setitem(agent._ENHANCERS, "gemini", boom)
    p = agent.decide(_ctx())
    assert p["mode"] == "deterministic"          # graceful fallback
    assert "llm_error" in p and "simulated provider outage" in p["llm_error"]
    assert p["governance"]["decision"]           # governance still applied
