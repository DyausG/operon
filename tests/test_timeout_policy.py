"""Provider-owned timeout policy, Ollama context handling, off-loop peers and compact rendering."""
from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx
import pytest

from core.agents.contracts import DiagnosticContext, SupervisorBounds
from core.agents.rendering import BOOKKEEPING_KEYS, INHERITANCE_NOTE, compact, model_message, model_view
from core.agents.runtime import RuntimeConfigurationError, RuntimeSettings, StrandsRuntime
from core.providers import ProviderConfig, ProviderError, config_from_environment, reset
from core.providers.base import CLOUD_TIMEOUTS, ModelOptions, TimeoutPolicy
from core.providers.bedrock import BedrockProvider, BedrockSettings
from core.providers.gemini import GeminiProvider, GeminiSettings
from core.providers.ollama import OllamaProvider, OllamaSettings, estimate_tokens
from core.reliability.models import Evidence
from core.services.adapters import gemini_peers
from tests.test_providers import FakeBoto, FakeGenaiClient, gemini, ollama_transport


# ------------------------------------------------------------- policies ----
def test_cloud_providers_keep_cloud_bounds_and_expose_them():
    g = GeminiProvider(GeminiSettings(timeout_seconds=12))
    assert g.timeout_policy() == CLOUD_TIMEOUTS.model_copy(update={"first_token_seconds": 12, "auxiliary_seconds": 12})
    b = BedrockProvider(BedrockSettings(connect_timeout_seconds=5, read_timeout_seconds=40))
    policy = b.timeout_policy()
    assert (policy.connect_seconds, policy.first_token_seconds, policy.invocation_seconds, policy.run_seconds) == (5, 40, 90, 240)
    assert b.describe().timeouts == policy.model_dump() and "api_key" not in json.dumps(g.describe().model_dump())


def test_ollama_policy_is_local_scale_and_configurable_from_environment():
    provider = OllamaProvider(OllamaSettings(model="qwen2.5:7b"))
    policy = provider.timeout_policy()
    assert policy == TimeoutPolicy(connect_seconds=3, first_token_seconds=300, invocation_seconds=900,
                                   run_seconds=1800, auxiliary_seconds=60)
    cfg = config_from_environment({
        "OPERON_OLLAMA_MODEL": "qwen2.5:7b", "OPERON_OLLAMA_TIMEOUT_SECONDS": "420",
        "OPERON_OLLAMA_CONNECT_TIMEOUT_SECONDS": "2", "OPERON_OLLAMA_INVOCATION_TIMEOUT_SECONDS": "1000",
        "OPERON_OLLAMA_RUN_TIMEOUT_SECONDS": "2400", "OPERON_OLLAMA_PEER_TIMEOUT_SECONDS": "45",
        "OPERON_OLLAMA_NUM_CTX": "32768"})
    assert cfg.ollama.num_ctx == 32768
    assert OllamaProvider(cfg.ollama).timeout_policy() == TimeoutPolicy(
        connect_seconds=2, first_token_seconds=420, invocation_seconds=1000, run_seconds=2400, auxiliary_seconds=45)
    assert OllamaProvider(cfg.ollama).describe().settings["num_ctx"] == 32768


def test_runtime_defaults_to_provider_policy_and_explicit_overrides_win(monkeypatch):
    reset(ProviderConfig())
    ollama = RuntimeSettings(provider="ollama", model_id="qwen2.5:7b", live_enabled=True)
    assert ollama.read_timeout_seconds is None and ollama.invocation_timeout_seconds is None
    runtime = StrandsRuntime(ollama, provider=OllamaProvider(OllamaSettings(model="qwen2.5:7b")))
    assert runtime.invocation_timeout() == 900 and runtime.run_timeout() == 1800
    assert runtime.timeouts().first_token_seconds == 300
    # The old accidental 30 s override is gone: nothing in the runtime shortens the provider bound.
    assert "30" not in json.dumps(ollama.model_options().model_dump())
    explicit = StrandsRuntime(ollama.model_copy(update={"read_timeout_seconds": 44, "invocation_timeout_seconds": 120,
                                                         "run_timeout_seconds": 500}),
                              provider=OllamaProvider(OllamaSettings(model="qwen2.5:7b")))
    assert explicit.timeouts().first_token_seconds == 44
    assert explicit.invocation_timeout() == 120 and explicit.run_timeout() == 500
    bedrock = StrandsRuntime(RuntimeSettings(model_id="m", aws_region="us-east-1"),
                             provider=BedrockProvider(BedrockSettings()))
    assert bedrock.invocation_timeout() == 90 and bedrock.run_timeout() == 240


def test_supervisor_bounds_default_to_runtime_policy_but_keep_explicit_values():
    assert SupervisorBounds().timeout_seconds is None
    assert SupervisorBounds(timeout_seconds=0.1).timeout_seconds == 0.1


def test_cloud_strands_models_still_receive_their_short_read_timeouts():
    provider, _ = gemini(FakeGenaiClient(), timeout_seconds=12)
    assert provider.strands_model().client_args["http_options"]["timeout"] == 12000
    assert provider.strands_model(ModelOptions(read_timeout_seconds=7)).client_args["http_options"]["timeout"] == 7000
    captured = {}
    import strands.models as strands_models
    original = strands_models.BedrockModel

    class Capture:
        def __init__(self, **kwargs):
            captured.update(kwargs)
    strands_models.BedrockModel = Capture
    try:
        BedrockProvider(BedrockSettings(), session_factory=FakeBoto()).strands_model()
        assert captured["boto_client_config"].read_timeout == 30 and captured["boto_client_config"].connect_timeout == 3
        BedrockProvider(BedrockSettings(), session_factory=FakeBoto()).strands_model(ModelOptions(read_timeout_seconds=44))
        assert captured["boto_client_config"].read_timeout == 44
    finally:
        strands_models.BedrockModel = original


# --------------------------------------------------------- ollama transport ----
def test_ollama_http_timeout_separates_connect_from_read():
    provider = OllamaProvider(OllamaSettings(model="qwen2.5:7b", timeout_seconds=300, connect_timeout_seconds=2))
    timeout = provider.http_timeout()
    assert isinstance(timeout, httpx.Timeout)
    assert (timeout.connect, timeout.read, timeout.pool) == (2, 300, 2) and timeout.write == 30
    model = provider.strands_model(ModelOptions(read_timeout_seconds=44))
    client_timeout = model.client_args["timeout"]
    assert isinstance(client_timeout, httpx.Timeout) and (client_timeout.connect, client_timeout.read) == (2, 44)
    assert model.get_config()["options"] == {"num_ctx": 16384}
    from strands.models.ollama import OllamaModel
    assert isinstance(model, OllamaModel) and type(model).__module__ == OllamaModel.__module__


def test_ollama_generate_json_sends_num_ctx_and_rejects_truncated_replies():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "{\"ok\": true}"},
                                         "prompt_eval_count": seen.get("__count", 100)})
    provider = OllamaProvider(OllamaSettings(model="qwen2.5:7b", num_ctx=4096), transport=httpx.MockTransport(handler))
    assert provider.generate_json("s", "u") == {"ok": True}
    assert seen["options"]["num_ctx"] == 4096 and seen["stream"] is False

    def truncated(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "{\"ok\": true}"},
                                         "prompt_eval_count": 4096})
    provider = OllamaProvider(OllamaSettings(model="qwen2.5:7b", num_ctx=4096), transport=httpx.MockTransport(truncated))
    with pytest.raises(ProviderError) as info:
        provider.generate_json("s", "u")
    assert "truncated" in str(info.value) and info.value.retryable is False and "NUM_CTX" in str(info.value)


def test_ollama_refuses_a_prompt_that_cannot_fit_before_sending_it():
    calls = []
    provider = OllamaProvider(OllamaSettings(model="qwen2.5:7b", num_ctx=2048),
                              transport=ollama_transport(log=calls))
    with pytest.raises(ProviderError) as info:
        provider.generate_json("s", "x" * 9000)
    assert "exceeds the configured Ollama context window" in str(info.value) and calls == []
    assert estimate_tokens("x" * 3000) == 1001


async def test_guarded_strands_model_rejects_truncation_and_oversized_prompts():
    import strands.models.ollama as strands_ollama
    provider = OllamaProvider(OllamaSettings(model="qwen2.5:7b", num_ctx=2048))
    model = provider.strands_model()
    messages = [{"role": "user", "content": [{"text": "hello"}]}]

    async def fake_stream(self, messages, tool_specs=None, system_prompt=None, *, tool_choice=None, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"metadata": {"usage": {"inputTokens": 2048, "outputTokens": 5, "totalTokens": 2053},
                            "metrics": {"latencyMs": 1}}}
    original = strands_ollama.OllamaModel.stream
    strands_ollama.OllamaModel.stream = fake_stream
    try:
        with pytest.raises(ProviderError, match="truncated"):
            async for _ in model.stream(messages):
                pass
    finally:
        strands_ollama.OllamaModel.stream = original
    with pytest.raises(ProviderError, match="exceeds the configured Ollama context window"):
        async for _ in model.stream([{"role": "user", "content": [{"text": "x" * 7000}]}]):
            pass


def test_ollama_preflight_refuses_missing_or_tool_less_models_and_caches_success():
    calls = []
    provider = OllamaProvider(OllamaSettings(model="qwen2.5:7b"), transport=ollama_transport(log=calls))
    provider.preflight()
    provider.preflight()
    assert [p for _, p in calls].count("/api/show") == 1  # second call served from the short cache
    no_tools = OllamaProvider(OllamaSettings(model="qwen2.5:7b"), transport=ollama_transport(show_caps=("completion",)))
    with pytest.raises(ProviderError) as info:
        no_tools.preflight()
    assert info.value.code == "unsupported_capability" and "tool calling" in str(info.value)
    missing = OllamaProvider(OllamaSettings(model="nope:1b"), transport=ollama_transport())
    with pytest.raises(ProviderError) as info:
        missing.preflight()
    assert info.value.code == "model_not_found"
    down = OllamaProvider(OllamaSettings(model="qwen2.5:7b"), transport=ollama_transport(down=True))
    with pytest.raises(ProviderError) as info:
        down.preflight()
    assert info.value.code == "provider_unreachable"
    runtime = StrandsRuntime(RuntimeSettings(provider="ollama", model_id="qwen2.5:7b", live_enabled=True), provider=no_tools)
    with pytest.raises(RuntimeConfigurationError, match="cannot serve this run"):
        runtime.preflight()


async def test_backend_preflight_refuses_the_run_before_any_durable_record(monkeypatch):
    from core.reasoning.backend import LocalStrandsBackend
    no_tools = OllamaProvider(OllamaSettings(model="qwen2.5:7b"), transport=ollama_transport(show_caps=("completion",)))
    runtime = StrandsRuntime(RuntimeSettings(provider="ollama", model_id="qwen2.5:7b", live_enabled=True), provider=no_tools)
    with pytest.raises(RuntimeConfigurationError, match="tool calling"):
        await LocalStrandsBackend(runtime).preflight()
    ok = OllamaProvider(OllamaSettings(model="qwen2.5:7b"), transport=ollama_transport())
    await LocalStrandsBackend(StrandsRuntime(RuntimeSettings(provider="ollama", model_id="qwen2.5:7b", live_enabled=True),
                                             provider=ok)).preflight()


# ----------------------------------------------------------------- peers ----
def test_peer_completions_are_bounded_by_the_auxiliary_timeout(monkeypatch):
    reset(config_from_environment({"OPERON_AI_PROVIDER": "ollama", "OPERON_OLLAMA_MODEL": "qwen2.5:7b"}))
    from core import config
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", False)
    seen = {}

    def fake(self, system, user, timeout=None):
        seen["timeout"] = timeout
        return {"escalate": False}
    monkeypatch.setattr(OllamaProvider, "generate_json", fake)
    assert gemini_peers.model_json("s", "u") == {"escalate": False}
    assert seen["timeout"] == 60
    reset(ProviderConfig())


async def test_monitoring_peer_never_blocks_the_event_loop(seeded_db, monkeypatch):
    from tests.test_engine import make_engine
    from core import services
    engine = make_engine(monkeypatch)
    started = threading.Event()

    class SlowPeer:
        def assess(self, snapshot):
            started.set()
            time.sleep(0.4)
            return {"escalate": True, "correlations": ["slow"], "rationale": "model answer"}
    monkeypatch.setattr(services, "monitoring", lambda: SlowPeer())
    snap = {"alerts": [{"equipment_id": "A", "equipment_class": "PUMP", "predicted_mode": "x",
                        "failure_prob": 0.9, "criticality": "HIGH"},
                       {"equipment_id": "B", "equipment_class": "PUMP", "predicted_mode": "x",
                        "failure_prob": 0.9, "criticality": "HIGH"}]}
    t0 = time.perf_counter()
    first = engine._peer_monitoring(snap)
    assert time.perf_counter() - t0 < 0.1 and first["pending"] is True and "rationale" in first
    ticks = 0
    for _ in range(6):
        await asyncio.sleep(0.1)
        ticks += 1  # the loop keeps turning while the peer sleeps in its thread
    assert started.is_set() and ticks == 6
    await asyncio.gather(*engine._monitoring_tasks.values())
    settled = engine._peer_monitoring(snap)
    assert settled == {"escalate": True, "correlations": ["slow"], "rationale": "model answer"}


# -------------------------------------------------------------- rendering ----
def sample_evidence(incident_id="inc-1"):
    return Evidence(
        id="ev-1", created_at="2026-09-15T20:07:27Z", incident_id=incident_id, equipment_ids=("AC-COMP-01",),
        kind="telemetry", source_uri="operon://evidence/x", source_locator="equipment:AC-COMP-01",
        source_version="v1", content_hash="abc", observed_at="2026-09-15T20:07:26Z",
        retrieved_at="2026-09-15T20:07:27Z", quality="GOOD", provenance="SIMULATED", summary="window",
        payload={"schema_version": 1, "asset_id": "AC-COMP-01", "operating_state": None,
                 "series": [{"schema_version": 1, "sensor_id": "S1", "unit": "K", "quality": "GOOD",
                             "readings": [{"schema_version": 1, "asset_id": "AC-COMP-01", "sensor_id": "S1",
                                           "unit": "K", "timestamp": "t1", "value": 1.5, "quality": "GOOD"},
                                          {"schema_version": 1, "asset_id": "AC-COMP-01", "sensor_id": "S1",
                                           "unit": "K", "timestamp": "t2", "value": 2.5, "quality": "SUSPECT"}]}]},
        source_capability="get_telemetry_window", source_system="operon.sqlite")


def test_compact_view_keeps_grounding_fields_and_drops_bookkeeping_and_repeats():
    context = DiagnosticContext(incident_id="inc-1", asset_id="AC-COMP-01", run_id="run-1", input_revision=3,
                                evidence=(sample_evidence(),))
    view = model_view(context)
    evidence = view["evidence"][0]
    assert evidence["id"] == "ev-1" and evidence["kind"] == "telemetry" and evidence["quality"] == "GOOD"
    assert evidence["summary"] == "window" and evidence["observed_at"] and evidence["source_capability"]
    assert not BOOKKEEPING_KEYS & set(evidence) and "content_hash" in evidence  # still a valid Evidence record
    from core.agents.contracts import DiagnosticContext as Ctx
    from core.agents.rendering import context_from_message
    assert Ctx.model_validate(context_from_message(model_message(context))).evidence[0].id == "ev-1"
    readings = evidence["payload"]["series"][0]["readings"]
    assert readings[0] == {"timestamp": "t1", "value": 1.5}                     # asset/sensor/unit/quality inherited
    assert readings[1] == {"timestamp": "t2", "value": 2.5, "quality": "SUSPECT"}  # a differing value is kept
    assert evidence["payload"]["operating_state"] is None                       # null stays: it means unknown
    assert evidence["payload"]["asset_id"] == "AC-COMP-01"                      # payload top level is intact
    message = model_message(context)
    assert json.loads(message)["_note"] == INHERITANCE_NOTE
    assert len(message) < len(context.model_dump_json()) * 0.9  # small sample; the real packet halves


def test_compact_is_lossless_under_inheritance():
    original = json.loads(sample_evidence().model_dump_json())

    def expand(node, inherited, top=False):
        if isinstance(node, dict):
            scope = {**inherited, **{k: v for k, v in node.items() if not isinstance(v, (dict, list))}}
            out = {k: expand(v, scope) for k, v in node.items()}
            if not top:
                for key, value in inherited.items():
                    out.setdefault(key, value)
            return out
        if isinstance(node, list):
            return [expand(item, inherited) for item in node]
        return node

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items()
                    if k not in BOOKKEEPING_KEYS and not (k in {"derived_from_ids", "supersedes_id"} and not v)}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    from core.agents.rendering import evidence_view
    view = evidence_view(original)
    expanded = {**view, "payload": expand(view["payload"], {}, top=True)}
    stripped = strip(original)

    def contains(superset, subset):
        if isinstance(subset, dict):
            return all(key in superset and contains(superset[key], value) for key, value in subset.items())
        if isinstance(subset, list):
            return len(superset) == len(subset) and all(contains(a, b) for a, b in zip(superset, subset))
        return superset == subset
    assert contains(expanded, stripped)
