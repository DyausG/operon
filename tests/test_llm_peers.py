"""LLM-backed peers: default selection, deterministic fallback without a key,
the model path (monkeypatched), the no-technician safety guard, and caching."""
from __future__ import annotations

import pytest

from core import services, config
from core.providers import ProviderError
from core.services.adapters import gemini_peers
from core.services.adapters.local import LocalGovernanceAdapter, LocalMonitoringAdapter
from core.services.adapters.gemini_peers import LLMGovernanceAdapter, LLMMonitoringAdapter


@pytest.fixture
def model(monkeypatch):
    """Route the peers' JSON completions to a fake provider response."""
    def install(fn):
        monkeypatch.setattr(gemini_peers, "model_json", fn)
    return install


def _proposal(tech=True):
    return {
        "equipment_id": "AC-COMP-01", "criticality": "HIGH",
        "failure_mode": {"mode_code": "OSF"},
        "prediction": {"failure_prob": 0.91},
        "business": {"unplanned_loss": 50_000},
        "actions": {"technician": {"technician_id": "T1", "full_name": "X"} if tech else None,
                    "parts": {"critical_available": True}},
    }


def _alerts(*specs):
    return {"alerts": [{"equipment_id": e, "equipment_class": c, "predicted_mode": m,
                        "failure_prob": 0.9, "criticality": "HIGH"} for e, c, m in specs]}


# --------------------------------------------------------------- defaults ----
def test_peers_default_to_llm_adapter():
    assert isinstance(services.governance(), LLMGovernanceAdapter)
    assert isinstance(services.monitoring(), LLMMonitoringAdapter)


def test_explicit_local_pins_deterministic(monkeypatch):
    monkeypatch.setenv("SENTINEL_GOVERNANCE_ADAPTER", "local")
    services.reset_cache()
    assert isinstance(services.governance(), LocalGovernanceAdapter)


# ------------------------------------------------------- no-key fallback -----
def test_model_json_is_none_without_a_configured_provider(monkeypatch):
    assert gemini_peers.model_json("s", "u") is None
    from core.providers import config_from_environment, reset
    reset(config_from_environment({"OPERON_AI_PROVIDER": "ollama", "OPERON_OLLAMA_MODEL": "gemma3"}))
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", False)
    calls = []
    monkeypatch.setattr(type(config.provider_registry().active()), "generate_json",
                        lambda self, system, user, timeout=None: calls.append(system) or {"escalate": False})
    assert gemini_peers.model_json("s", "u") == {"escalate": False} and calls == ["s"]
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", True)
    assert gemini_peers.model_json("s", "u") is None


def test_llm_governance_falls_back_without_key():
    # conftest clears every provider -> no provider -> deterministic policy
    v = LLMGovernanceAdapter().review_plan(_proposal(tech=False))
    assert v["decision"] == "VETO"
    assert v["policy_version"] == "gov-policy-1"          # the deterministic engine


def test_llm_monitoring_falls_back_without_key():
    a = LLMMonitoringAdapter().assess(_alerts(("HYD-PUMP-03", "PUMP", "HDF"),
                                              ("COOL-PMP-09", "PUMP", "PWF")))
    assert a["escalate"] is True
    assert any(c["pattern"] == "same-equipment-class" for c in a["correlations"])


# ----------------------------------------------------------- model path ------
def test_llm_governance_uses_model_when_available(model):
    model(lambda system, user: {"decision": "conditions", "reasons": ["r"], "conditions": ["c"]})
    v = LLMGovernanceAdapter().review_plan(_proposal(tech=True))
    assert v["decision"] == "CONDITIONS"                  # normalized upper
    assert v["policy_version"] == "gov-llm-1"             # the LLM engine


def test_llm_governance_safety_guard_forces_veto_without_tech(model):
    # model wrongly says APPROVE, but there's no technician -> forced VETO
    model(lambda system, user: {"decision": "APPROVE", "reasons": [], "conditions": []})
    v = LLMGovernanceAdapter().review_plan(_proposal(tech=False))
    assert v["decision"] == "VETO"


def test_llm_governance_bad_output_falls_back(model):
    def boom(system, user):
        raise ProviderError("rate_limited", "quota exhausted", provider="gemini")

    model(boom)
    v = LLMGovernanceAdapter().review_plan(_proposal(tech=True))
    assert v["policy_version"] == "gov-policy-1"          # degraded to deterministic


def test_llm_monitoring_caches_same_alert_set(model):
    calls = {"n": 0}

    def fake(system, user):
        calls["n"] += 1
        return {"escalate": True, "correlations": [], "rationale": "systemic"}

    model(fake)
    adapter = LLMMonitoringAdapter()
    snap = _alerts(("A", "PUMP", "HDF"), ("B", "PUMP", "HDF"))
    first = adapter.assess(snap)
    second = adapter.assess(snap)          # same set -> served from cache
    assert first == second
    assert calls["n"] == 1                 # the model was consulted only once
