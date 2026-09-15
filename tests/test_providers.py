"""Stage 0 provider layer: selection, no-provider mode, mocked adapters, normalized errors, capabilities."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr

from core import config
from core.providers import (Capabilities, DISPLAY_NAMES, ERROR_CODES, PROVIDER_KINDS, ProviderConfig, ProviderError,
                            ProviderRegistry, ProviderStatus, config_from_environment, normalize_exception,
                            normalize_selection)
from core.providers.bedrock import BedrockProvider, BedrockSettings
from core.providers.gemini import GeminiProvider, GeminiSettings
from core.providers.none import NoProvider
from core.providers.ollama import OllamaProvider, OllamaSettings
from core.providers.status import render

FAKE_KEY = "test-gemini-key-not-real-0000000000"


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """Every test starts from the credential-free environment conftest guarantees."""
    from core.providers import reset
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", False)
    reset(ProviderConfig())
    yield
    reset()


# ------------------------------------------------------------ selection ----
def test_environment_defaults_to_auto_and_no_provider():
    cfg = config_from_environment({})
    assert cfg.selection == "auto" and cfg.force_none is False
    registry = ProviderRegistry(cfg)
    assert registry.resolve_kind() == "none"
    assert isinstance(registry.active(), NoProvider)
    assert registry.overview()["active_display_name"] == DISPLAY_NAMES["none"]


@pytest.mark.parametrize("raw,expected", [
    ("auto", "auto"), ("GEMINI", "gemini"), ("ollama", "ollama"), ("bedrock", "bedrock"),
    ("deterministic", "none"), ("none", "none"), ("local", "ollama"),
])
def test_selection_vocabulary_and_legacy_aliases(raw, expected):
    assert normalize_selection(raw) == expected


def test_unknown_selection_is_rejected_by_api_but_tolerated_from_environment():
    with pytest.raises(ValueError, match="unknown provider selection"):
        normalize_selection("cloud")
    assert config_from_environment({"OPERON_AI_PROVIDER": "cloud"}).selection == "auto"


def test_auto_prefers_configured_gemini_then_bedrock(monkeypatch):
    assert ProviderRegistry(config_from_environment({})).resolve_kind() == "none"
    monkeypatch.setenv("AWS_PROFILE", "operon-test")      # Bedrock credential evidence (environment only)
    assert ProviderRegistry(config_from_environment({})).resolve_kind() == "bedrock"
    assert ProviderRegistry(config_from_environment({"GEMINI_API_KEY": FAKE_KEY})).resolve_kind() == "gemini"


def test_force_deterministic_wins_over_configured_provider():
    cfg = config_from_environment({"GEMINI_API_KEY": FAKE_KEY, "POC_FORCE_DETERMINISTIC": "1"})
    assert ProviderRegistry(cfg).resolve_kind() == "none"
    cfg = config_from_environment({"GEMINI_API_KEY": FAKE_KEY, "SENTINEL_LLM_PROVIDER": "deterministic"})
    assert ProviderRegistry(cfg).resolve_kind() == "none"


def test_explicit_selection_of_an_unconfigured_provider_stays_truthful():
    registry = ProviderRegistry(config_from_environment({"OPERON_AI_PROVIDER": "gemini"}))
    assert registry.resolve_kind() == "gemini"
    status = registry.status()
    assert status.configured is False and status.credential.configured is False
    with pytest.raises(ProviderError) as info:
        registry.active().strands_model()
    assert info.value.code == "provider_not_configured"


def test_config_agent_mode_and_reasoning_backend_follow_the_registry(monkeypatch):
    from core.providers import reset
    monkeypatch.delenv("OPERON_REASONING_BACKEND", raising=False)
    assert config.agent_mode() == "deterministic" and config.reasoning_backend() == "none"
    reset(config_from_environment({"OPERON_AI_PROVIDER": "ollama", "OPERON_OLLAMA_MODEL": "m"}))
    assert config.agent_mode() == "ollama" and config.reasoning_backend() == "local"
    assert config.ollama_available() and not config.gemini_available() and not config.bedrock_available()
    monkeypatch.setattr(config, "FORCE_DETERMINISTIC", True)
    assert config.agent_mode() == "deterministic"


def test_registry_select_and_update_never_expose_secrets():
    registry = ProviderRegistry(ProviderConfig())
    registry.update("gemini", api_key=FAKE_KEY, model="gemini-2.5-flash")
    status = registry.select("gemini")
    assert status.configured and status.credential.source == "session" and status.model == "gemini-2.5-flash"
    dumped = json.dumps(registry.overview()) + json.dumps(status.model_dump(mode="json"))
    assert FAKE_KEY not in dumped
    assert FAKE_KEY not in repr(registry.config) and FAKE_KEY not in registry.config.model_dump_json()
    registry.update("gemini", api_key="")            # clearing falls back to the (absent) environment key
    assert registry.status("gemini").configured is False
    with pytest.raises(ValueError, match="does not accept"):
        registry.update("ollama", api_key="x")
    with pytest.raises(ValueError, match="invalid ollama configuration"):
        registry.update("ollama", base_url="not a url")
    with pytest.raises(ValueError, match="no configurable"):
        registry.update("none", model="x")
    registry.select("bedrock", model="my-profile")
    assert registry.status("bedrock").model == "my-profile"


def test_build_is_reusable_and_role_hook_is_reserved():
    registry = ProviderRegistry(ProviderConfig())
    assert registry.build("gemini") is registry.build("gemini")
    assert registry.build(role="fast").kind == "none"
    from core.providers.registry import RoleOverride
    registry.config.roles["fast"] = RoleOverride(provider="ollama")
    assert registry.build(role="fast").kind == "ollama" and registry.overview()["roles"]["fast"]["provider"] == "ollama"
    with pytest.raises(ValueError):
        registry.build("openai")


# ---------------------------------------------------------- no provider ----
def test_no_provider_reports_unavailable_everywhere():
    provider = NoProvider()
    status = provider.describe()
    assert status.configured is False and status.reachable is None and status.model is None
    assert status.capabilities == Capabilities()
    assert "deterministic" in provider.test_connection().detail.lower() or "Deterministic" in provider.test_connection().detail
    for call in (lambda: provider.strands_model(), lambda: provider.generate_json("s", "u")):
        with pytest.raises(ProviderError) as info:
            call()
        assert info.value.code == "provider_not_configured" and info.value.retryable is False


def test_status_render_is_secret_free_and_explains_deterministic_mode():
    registry = ProviderRegistry(ProviderConfig())
    lines = render(registry.overview())
    assert lines[0] == "AI provider" and "deterministic" in " ".join(lines)
    registry.update("gemini", api_key=FAKE_KEY)
    registry.select("gemini")
    text = "\n".join(render(registry.overview()))
    assert "Google Gemini selected" in text and FAKE_KEY not in text


# ------------------------------------------------------------- errors ----
def test_error_codes_are_closed_and_messages_redacted():
    assert set(ERROR_CODES) == {"provider_not_configured", "authentication_failed", "provider_unreachable",
                                "model_not_found", "rate_limited", "timeout", "unsupported_capability", "provider_error"}
    err = ProviderError("authentication_failed", f"key {FAKE_KEY} rejected", provider="gemini", secrets=(FAKE_KEY,))
    assert FAKE_KEY not in str(err) and "[redacted]" in str(err)
    assert err.to_dict() == {"code": "authentication_failed", "message": str(err), "provider": "gemini", "retryable": False}
    assert ProviderError("rate_limited", "x", provider="p").retryable is True
    with pytest.raises(ValueError):
        ProviderError("weird", "x", provider="p")


class _GenaiError(Exception):
    __module__ = "google.genai.errors"

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class _OllamaResponseError(Exception):
    __module__ = "ollama._types"

    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize("exc,code", [
    (httpx.ConnectError("refused"), "provider_unreachable"),
    (httpx.ReadTimeout("slow"), "timeout"),
    (ConnectionRefusedError(), "provider_unreachable"),
    (TimeoutError(), "timeout"),
    (_GenaiError(400, "API key not valid. Please pass a valid API key."), "authentication_failed"),
    (_GenaiError(403, "permission denied"), "authentication_failed"),
    (_GenaiError(404, "model not found"), "model_not_found"),
    (_GenaiError(429, "RESOURCE_EXHAUSTED"), "rate_limited"),
    (_GenaiError(503, "overloaded"), "provider_error"),
    (_OllamaResponseError(404, "model 'x' not found"), "model_not_found"),
])
def test_normalize_exception_maps_transport_and_sdk_failures(exc, code):
    err = normalize_exception(exc, provider="test")
    assert err is not None and err.code == code and err.provider == "test"


def test_normalize_exception_maps_aws_and_strands_failures():
    from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError
    from strands.types.exceptions import ModelThrottledException
    def client_error(code):
        return ClientError({"Error": {"Code": code, "Message": "m"}}, "op")
    assert normalize_exception(client_error("ExpiredTokenException"), provider="bedrock").code == "authentication_failed"
    assert normalize_exception(client_error("AccessDeniedException"), provider="bedrock").code == "authentication_failed"
    assert normalize_exception(client_error("ResourceNotFoundException"), provider="bedrock").code == "model_not_found"
    assert normalize_exception(client_error("ThrottlingException"), provider="bedrock").code == "rate_limited"
    assert normalize_exception(client_error("InternalServerException"), provider="bedrock").retryable is True
    assert normalize_exception(NoCredentialsError(), provider="bedrock").code == "provider_not_configured"
    assert normalize_exception(ReadTimeoutError(endpoint_url="x"), provider="bedrock").code == "timeout"
    assert normalize_exception(EndpointConnectionError(endpoint_url="x"), provider="bedrock").code == "provider_unreachable"
    assert normalize_exception(ModelThrottledException("slow down"), provider="gemini").code == "rate_limited"
    assert normalize_exception(ValueError("application error"), provider="gemini") is None


# ------------------------------------------------------------- gemini ----
class FakeGenaiClient:
    def __init__(self, *, get=None, text='{"decision": "APPROVE", "reasons": [], "conditions": []}'):
        self.get_error, self.text, self.calls = get, text, []
        self.models = self

    def get(self, *, model):
        self.calls.append(("get", model))
        if self.get_error:
            raise self.get_error
        return SimpleNamespace(name=f"models/{model}")

    def generate_content(self, **kwargs):
        self.calls.append(("generate", kwargs["model"]))
        if isinstance(self.text, Exception):
            raise self.text
        return SimpleNamespace(text=self.text)


def gemini(client, **settings):
    factory = Mock(return_value=client)
    provider = GeminiProvider(GeminiSettings(api_key=SecretStr(FAKE_KEY), key_source="environment", **settings),
                              client_factory=factory)
    return provider, factory


def test_gemini_describe_and_capabilities_without_network():
    provider = GeminiProvider(GeminiSettings())
    status = provider.describe()
    assert status.configured is False and status.credential.detail == "GEMINI_API_KEY is not set"
    assert status.endpoint == "generativelanguage.googleapis.com" and status.reachable is None
    provider, factory = gemini(FakeGenaiClient(), model="gemini-2.5-pro")
    assert provider.describe().model == "gemini-2.5-pro" and provider.credential_status().source == "environment"
    caps = provider.capabilities()
    assert caps.locality == "cloud" and caps.tool_calling and caps.structured_output and caps.image_input
    factory.assert_not_called()


def test_gemini_test_connection_uses_model_metadata_not_generation():
    client = FakeGenaiClient()
    provider, factory = gemini(client, timeout_seconds=7)
    status = provider.test_connection()
    assert status.reachable is True and status.probe == "connection" and status.error is None
    assert client.calls == [("get", "gemini-flash-latest")]
    assert factory.call_args.args == (FAKE_KEY, 7)
    assert FAKE_KEY not in status.model_dump_json()


@pytest.mark.parametrize("exc,code", [
    (_GenaiError(400, "API key not valid"), "authentication_failed"),
    (_GenaiError(404, "not found"), "model_not_found"),
    (_GenaiError(429, "quota"), "rate_limited"),
    (httpx.ConnectError("dns"), "provider_unreachable"),
])
def test_gemini_test_connection_normalizes_failures(exc, code):
    provider, _ = gemini(FakeGenaiClient(get=exc))
    status = provider.test_connection()
    assert status.reachable is False and status.error["code"] == code and FAKE_KEY not in json.dumps(status.error)


def test_gemini_unconfigured_test_connection_and_generate():
    provider = GeminiProvider(GeminiSettings(), client_factory=Mock(side_effect=AssertionError("no client")))
    status = provider.test_connection()
    assert status.error["code"] == "provider_not_configured"
    with pytest.raises(ProviderError) as info:
        provider.generate_json("s", "u")
    assert info.value.code == "provider_not_configured"


def test_gemini_generate_json_parses_and_rejects_non_json(monkeypatch):
    from core import gemini as transport
    monkeypatch.setattr(transport.LIMITER, "acquire", lambda: None)
    provider, _ = gemini(FakeGenaiClient())
    assert provider.generate_json("system", "user")["decision"] == "APPROVE"
    provider, _ = gemini(FakeGenaiClient(text="not json"))
    with pytest.raises(ProviderError, match="non-JSON"):
        provider.generate_json("system", "user")
    provider, _ = gemini(FakeGenaiClient(text=_GenaiError(429, "quota")))
    monkeypatch.setattr(transport, "is_transient", lambda e: False)
    with pytest.raises(ProviderError) as info:
        provider.generate_json("system", "user")
    assert info.value.code == "rate_limited"


def test_gemini_strands_model_is_bound_to_the_key_and_model(monkeypatch):
    provider, _ = gemini(FakeGenaiClient(), model="gemini-2.5-flash", timeout_seconds=12)
    from core.providers.base import ModelOptions
    model = provider.strands_model(ModelOptions(temperature=0.3, max_tokens=999))
    from strands.models.gemini import GeminiModel
    assert isinstance(model, GeminiModel)
    assert model.client_args["api_key"] == FAKE_KEY and model.client_args["http_options"]["timeout"] == 12000
    assert model.get_config()["model_id"] == "gemini-2.5-flash"
    assert model.get_config()["params"] == {"temperature": 0.3, "max_output_tokens": 999}


# -------------------------------------------------------------- ollama ----
def ollama_transport(*, version="0.15.2", models=("gemma3:latest", "qwen2.5:7b"), show_caps=("completion", "tools"),
                     chat='{"escalate": true, "correlations": [], "rationale": "same class"}', down=False, log=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append((request.method, request.url.path))
        if down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": version})
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m, "model": m} for m in models]})
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": list(show_caps)})
        if path == "/api/chat":
            body = json.loads(request.content)
            assert body["format"] == "json" and body["stream"] is False
            return httpx.Response(200, json={"message": {"role": "assistant", "content": chat}})
        return httpx.Response(404, json={"error": "not found"})
    return httpx.MockTransport(handler)


def ollama(model="gemma3", **kwargs):
    log = []
    provider = OllamaProvider(OllamaSettings(model=model, base_url="http://ollama.test:11434"),
                              transport=ollama_transport(log=log, **kwargs))
    return provider, log


def test_ollama_describe_is_local_and_honest_about_unverified_capabilities():
    provider, log = ollama()
    status = provider.describe()
    assert status.configured and status.endpoint == "http://ollama.test:11434" and status.reachable is None
    assert status.capabilities.locality == "local" and status.capabilities.tool_calling is None
    assert status.credential.source == "not_required"
    assert provider.identity_locator() == "http://ollama.test:11434"
    assert log == []
    assert OllamaProvider(OllamaSettings()).describe().configured is False


def test_ollama_test_connection_validates_model_and_reports_capabilities():
    provider, log = ollama()
    status = provider.test_connection()
    assert status.reachable is True and status.error is None
    assert status.models == ("gemma3:latest", "qwen2.5:7b") and "gemma3:latest" in status.detail
    assert status.capabilities.tool_calling is True and status.capabilities.image_input is False
    assert [p for _, p in log] == ["/api/version", "/api/tags", "/api/show"]


def test_ollama_not_running_and_model_unavailable_states():
    provider, _ = ollama(down=True)
    status = provider.test_connection()
    assert status.reachable is False and status.error["code"] == "provider_unreachable"
    assert "not running" in status.error["message"]
    provider, _ = ollama(model="llama3.3:70b")
    status = provider.test_connection()
    assert status.reachable is True and status.error["code"] == "model_not_found"
    assert "ollama pull llama3.3:70b" in status.error["message"] and status.models
    provider = OllamaProvider(OllamaSettings(model=""), transport=ollama_transport())
    status = provider.test_connection()
    assert status.reachable is True and status.error["code"] == "provider_not_configured" and status.models


def test_ollama_generate_json_and_strands_model():
    provider, _ = ollama()
    assert provider.generate_json("s", "u")["escalate"] is True
    provider, _ = ollama(chat="nope")
    with pytest.raises(ProviderError, match="non-JSON"):
        provider.generate_json("s", "u")
    provider, _ = ollama(down=True)
    with pytest.raises(ProviderError) as info:
        provider.generate_json("s", "u")
    assert info.value.code == "provider_unreachable"
    from strands.models.ollama import OllamaModel
    model = ollama()[0].strands_model()
    assert isinstance(model, OllamaModel) and model.host == "http://ollama.test:11434"
    assert model.get_config()["model_id"] == "gemma3"


# ------------------------------------------------------------- bedrock ----
class FakeBoto:
    def __init__(self, *, credentials=True, sts_error=None, model_error=None, profile_error=None, converse_text=None):
        self.credentials, self.sts_error, self.model_error = credentials, sts_error, model_error
        self.profile_error, self.converse_text, self.calls = profile_error, converse_text, []

    # session ---------------------------------------------------------
    def __call__(self, *, region_name, profile_name):
        self.calls.append(("session", region_name, profile_name))
        if self.profile_error:
            raise self.profile_error
        return self

    def get_credentials(self):
        if not self.credentials:
            return None
        return SimpleNamespace(get_frozen_credentials=lambda: SimpleNamespace(access_key="AKIAFAKE", secret_key="fake"))

    def client(self, name, config=None):
        self.calls.append(("client", name))
        return self

    # clients ---------------------------------------------------------
    def get_caller_identity(self):
        if self.sts_error:
            raise self.sts_error
        return {"Account": "000000000000"}

    def get_foundation_model(self, modelIdentifier):
        if self.model_error:
            raise self.model_error
        return {"modelDetails": {"modelId": modelIdentifier}}

    def get_inference_profile(self, inferenceProfileIdentifier):
        return {"inferenceProfileId": inferenceProfileIdentifier}

    def converse(self, **kwargs):
        self.calls.append(("converse", kwargs["modelId"]))
        return {"output": {"message": {"content": [{"text": self.converse_text}]}}}


def bedrock(fake, **settings):
    return BedrockProvider(BedrockSettings(region="eu-west-1", model_id="test-model", **settings), session_factory=fake)


def test_bedrock_describe_inspects_environment_only(monkeypatch):
    fake = FakeBoto()
    provider = bedrock(fake)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE", "AWS_BEARER_TOKEN_BEDROCK"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent/credentials")
    status = provider.describe()
    assert status.configured is False and status.region == "eu-west-1" and status.credential.source == "none"
    monkeypatch.setenv("AWS_PROFILE", "operon-demo")
    assert provider.credential_status().source == "environment" and "operon-demo" in provider.credential_status().detail
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")
    assert provider.credential_status().detail == "AWS access key present (server-side)"
    assert "fake-secret" not in provider.describe().model_dump_json()
    assert fake.calls == []


def test_bedrock_test_connection_paths():
    from botocore.exceptions import ClientError
    fake = FakeBoto()
    status = bedrock(fake).test_connection()
    assert status.reachable is True and "test-model" in status.detail
    assert [c for c in fake.calls if c[0] == "client"] == [("client", "sts"), ("client", "bedrock")]
    status = bedrock(FakeBoto(credentials=False)).test_connection()
    assert status.error["code"] == "provider_not_configured"
    expired = ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "GetCallerIdentity")
    assert bedrock(FakeBoto(sts_error=expired)).test_connection().error["code"] == "authentication_failed"
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "GetFoundationModel")
    assert bedrock(FakeBoto(model_error=denied)).test_connection().error["code"] == "authentication_failed"
    validation = ClientError({"Error": {"Code": "ValidationException", "Message": "not a foundation model"}},
                             "GetFoundationModel")
    status = bedrock(FakeBoto(model_error=validation)).test_connection()
    assert status.reachable is True and "inference profile" in status.detail
    from botocore.exceptions import ProfileNotFound
    status = bedrock(FakeBoto(profile_error=ProfileNotFound(profile="missing"))).test_connection()
    assert status.error["code"] == "provider_not_configured"


def test_bedrock_generate_json_and_strands_model(monkeypatch):
    fake = FakeBoto(converse_text='```json\n{"decision": "VETO", "reasons": ["r"], "conditions": []}\n```')
    assert bedrock(fake).generate_json("s", "u")["decision"] == "VETO"
    assert ("converse", "test-model") in fake.calls
    captured = {}
    class FakeBedrockModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)
    monkeypatch.setattr("strands.models.BedrockModel", FakeBedrockModel)
    from core.providers.base import ModelOptions
    bedrock(FakeBoto(), max_tokens=1234).strands_model(ModelOptions(read_timeout_seconds=44, request_attempts=3))
    assert captured["model_id"] == "test-model" and captured["max_tokens"] == 1234
    assert captured["boto_client_config"].read_timeout == 44
    assert captured["boto_client_config"].retries == {"mode": "standard", "total_max_attempts": 3}
    with pytest.raises(ProviderError, match="credentials unavailable"):
        bedrock(FakeBoto(credentials=False)).strands_model()


# ------------------------------------------------------ status contract ----
def test_provider_status_contract_has_no_secret_fields():
    fields = set(ProviderStatus.model_fields)
    assert fields == {"provider", "display_name", "configured", "reachable", "model", "models", "endpoint", "region",
                      "credential", "capabilities", "probe", "error", "checked_at", "detail"}
    for kind in PROVIDER_KINDS:
        status = ProviderRegistry(ProviderConfig()).status(kind)
        assert status.provider == kind and status.display_name == DISPLAY_NAMES[kind]
