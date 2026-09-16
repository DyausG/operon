"""Ollama / local open-source model provider.

Talks to a running Ollama server over its HTTP API (httpx) for status, model
validation and bounded JSON completions, and hands Strands its ``OllamaModel``
for the supervisor/specialist agents. Nothing here installs Ollama or pulls a
model: an absent server or model is reported truthfully as a normalized error.

Local inference is slow in a different way from cloud inference: the transport
read timeout on a streamed chat is really "how long may prompt evaluation take
before the first token", so this provider owns a ``TimeoutPolicy`` with much
larger, separately configurable bounds, sends an explicit context window
(``num_ctx``) with every request, and refuses a prompt the server would silently
truncate (Ollama drops the *head* of an oversized prompt, i.e. the system prompt
and the tool definitions).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .base import (
    Capabilities, CredentialStatus, DISPLAY_NAMES, ModelOptions, ModelProvider, ProviderStatus, TimeoutPolicy, now_iso,
)
from .errors import ProviderError, normalize_exception

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_NUM_CTX = 16384
# Conservative token estimate for refusing a prompt before it is sent. Operon's
# JSON-heavy packets tokenize at roughly 2.9 characters per token on Qwen/Llama
# vocabularies; 3.0 refuses slightly early rather than letting the server truncate.
CHARS_PER_TOKEN_ESTIMATE = 3.0
PREFLIGHT_CACHE_SECONDS = 60.0
WRITE_TIMEOUT_SECONDS = 30.0


class OllamaSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str = Field(default=DEFAULT_OLLAMA_BASE_URL, min_length=1, max_length=300, pattern=r"^https?://\S+$")
    model: str = Field(default="", max_length=200)
    # Transport bounds. ``timeout_seconds`` is the read / first-token bound (see TimeoutPolicy).
    timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    # Agent-operation bounds: one agent invocation, one complete supervisor run, one peer completion.
    invocation_timeout_seconds: float = Field(default=900.0, gt=0, le=7200)
    run_timeout_seconds: float = Field(default=1800.0, gt=0, le=14400)
    peer_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    # Context window sent with every request. Ollama's server default (4096) truncates Operon's packets.
    num_ctx: int = Field(default=DEFAULT_OLLAMA_NUM_CTX, ge=2048, le=262144)
    max_tokens: int = Field(default=2048, ge=1, le=65536)
    temperature: float = Field(default=0.2, ge=0, le=2)
    keep_alive: str | None = None

    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")


def _same_model(configured: str, installed: str) -> bool:
    if configured == installed:
        return True
    return f"{configured}:latest" == installed or configured == f"{installed}:latest"


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN_ESTIMATE) + 1


def truncation_error(prompt_tokens: int, num_ctx: int, *, provider: str = "ollama") -> ProviderError:
    return ProviderError(
        "provider_error",
        f"Ollama truncated the prompt: {prompt_tokens} prompt tokens filled the {num_ctx}-token context window, "
        "so the system prompt and tool definitions were discarded before generation. Raise "
        "OPERON_OLLAMA_NUM_CTX (Settings -> AI provider -> Context window) or reduce the evidence packet; "
        "the reply was not accepted.", provider=provider, retryable=False)


def oversized_prompt_error(estimated_tokens: int, num_ctx: int, *, provider: str = "ollama") -> ProviderError:
    return ProviderError(
        "provider_error",
        f"prompt estimated at ~{estimated_tokens} tokens exceeds the configured Ollama context window "
        f"(num_ctx={num_ctx}); the server would silently truncate it. Raise OPERON_OLLAMA_NUM_CTX "
        "(Settings -> AI provider -> Context window) or reduce the evidence packet.",
        provider=provider, retryable=False)


def _context_length(show: dict) -> int | None:
    """The model's trained context length from ``/api/show`` (``<arch>.context_length``)."""
    info = show.get("model_info") or {}
    for key, value in info.items():
        if str(key).endswith(".context_length") and isinstance(value, int):
            return value
    return None


class OllamaProvider(ModelProvider):
    kind = "ollama"
    display_name = DISPLAY_NAMES["ollama"]

    def __init__(self, settings: OllamaSettings, *, transport: httpx.BaseTransport | None = None):
        self.settings = OllamaSettings.model_validate(settings)
        self._transport = transport
        self._preflight_ok_at: float | None = None

    # ---- metadata ---------------------------------------------------------
    @property
    def model_id(self) -> str | None:
        return self.settings.model.strip() or None

    def configured(self) -> bool:
        return self.model_id is not None

    def credential_status(self) -> CredentialStatus:
        return CredentialStatus(configured=True, source="not_required", detail="local server; no credential")

    def capabilities(self) -> Capabilities:
        # Tool calling and vision depend on the pulled model; they are verified by Test Connection.
        return Capabilities(text_generation=True, structured_output=True, tool_calling=None, streaming=True,
                            image_input=None, locality="local")

    def identity_locator(self) -> str:
        return self.settings.normalized_base_url()

    def not_configured_reason(self) -> str:
        return "Ollama needs a model name (OPERON_OLLAMA_MODEL), for example one shown by `ollama list`"

    def timeout_policy(self) -> TimeoutPolicy:
        s = self.settings
        return TimeoutPolicy(connect_seconds=s.connect_timeout_seconds, first_token_seconds=s.timeout_seconds,
                             invocation_seconds=s.invocation_timeout_seconds, run_seconds=s.run_timeout_seconds,
                             auxiliary_seconds=s.peer_timeout_seconds)

    def public_settings(self) -> dict[str, Any]:
        s = self.settings
        return {"base_url": s.normalized_base_url(), "model": s.model, "num_ctx": s.num_ctx,
                "timeout_seconds": s.timeout_seconds, "connect_timeout_seconds": s.connect_timeout_seconds,
                "invocation_timeout_seconds": s.invocation_timeout_seconds,
                "run_timeout_seconds": s.run_timeout_seconds, "peer_timeout_seconds": s.peer_timeout_seconds,
                "max_tokens": s.max_tokens}

    def describe(self) -> ProviderStatus:
        return self._status(endpoint=self.settings.normalized_base_url(),
                            detail="configured (reachability unverified)" if self.configured() else self.not_configured_reason())

    # ---- transport --------------------------------------------------------
    def http_timeout(self, read: float | None = None, *, connect: float | None = None) -> httpx.Timeout:
        """Structured timeout: connect is short, read (first token / between chunks) may be long."""
        return httpx.Timeout(connect=connect or self.settings.connect_timeout_seconds,
                             read=read or self.settings.timeout_seconds,
                             write=WRITE_TIMEOUT_SECONDS, pool=connect or self.settings.connect_timeout_seconds)

    def _http(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(base_url=self.settings.normalized_base_url(), timeout=self.http_timeout(timeout),
                            transport=self._transport)

    def _normalize(self, exc: BaseException) -> ProviderError:
        err = normalize_exception(exc, provider=self.kind)
        if err is None:
            return ProviderError("provider_error", f"{type(exc).__name__}: {exc}", provider=self.kind)
        if err.code == "provider_unreachable":
            return ProviderError("provider_unreachable",
                                 f"Ollama is not running or not reachable at {self.settings.normalized_base_url()}",
                                 provider=self.kind)
        return err

    def _json(self, response: httpx.Response) -> dict:
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ProviderError("provider_error", "Ollama returned an unexpected payload", provider=self.kind)
        return data

    # ---- operations -------------------------------------------------------
    def installed_models(self, client: httpx.Client) -> tuple[str, ...]:
        tags = self._json(client.get("/api/tags"))
        names = []
        for item in tags.get("models") or []:
            name = item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
        return tuple(names)

    def test_connection(self, *, timeout: float | None = None) -> ProviderStatus:
        endpoint = self.settings.normalized_base_url()
        try:
            with self._http(timeout or 15.0) as client:
                version = self._json(client.get("/api/version")).get("version")
                models = self.installed_models(client)
                if not self.configured():
                    return self._failed(ProviderError("provider_not_configured", self.not_configured_reason(),
                                                      provider=self.kind),
                                        reachable=True, endpoint=endpoint, models=models,
                                        detail=f"Ollama {version} reachable; choose one of the installed models")
                match = next((name for name in models if _same_model(self.model_id, name)), None)
                if match is None:
                    hint = (f"model {self.model_id!r} is not installed; run `ollama pull {self.model_id}` "
                            f"or pick an installed model")
                    return self._failed(ProviderError("model_not_found", hint, provider=self.kind),
                                        reachable=True, endpoint=endpoint, models=models,
                                        detail=f"Ollama {version} reachable")
                show = self._json(client.post("/api/show", json={"model": match}))
        except ProviderError as err:
            return self._failed(err, endpoint=endpoint)
        except Exception as exc:  # noqa: BLE001
            return self._failed(self._normalize(exc), endpoint=endpoint)
        caps = {str(c) for c in (show.get("capabilities") or [])}
        capabilities = Capabilities(text_generation=True, structured_output=True, streaming=True, locality="local",
                                    tool_calling=("tools" in caps) if caps else None,
                                    image_input=("vision" in caps) if caps else None)
        detail = f"Ollama {version} reachable; model {match} available"
        context_length = _context_length(show)
        if context_length is not None:
            detail += f"; trained context {context_length} tokens, requests use num_ctx={self.settings.num_ctx}"
            if self.settings.num_ctx > context_length:
                detail += " (above the trained context; lower OPERON_OLLAMA_NUM_CTX or expect degraded output)"
        return self._status(reachable=True, probe="connection", endpoint=endpoint, models=models,
                            capabilities=capabilities, checked_at=now_iso(), detail=detail)

    def preflight(self, *, tool_calling: bool = True) -> None:
        """Refuse to start an agent run the pulled model cannot serve.

        Checks reachability, that the configured model is installed and, when the
        workflow needs tools, that the model advertises the ``tools`` capability.
        The positive answer is cached briefly; a failure is never cached.
        """
        self.require_configured()
        now = time.monotonic()
        if self._preflight_ok_at is not None and now - self._preflight_ok_at < PREFLIGHT_CACHE_SECONDS:
            return
        status = self.test_connection()
        if status.error is not None:
            raise ProviderError(status.error["code"], status.error["message"], provider=self.kind,
                                retryable=status.error.get("retryable"))
        if tool_calling and status.capabilities.tool_calling is False:
            raise ProviderError(
                "unsupported_capability",
                f"Ollama model {self.model_id!r} does not advertise tool calling, which the supervisor and "
                "specialist agents require; choose a tool-capable model (for example qwen2.5, llama3.1 or "
                "mistral-nemo) in Settings -> AI provider", provider=self.kind, retryable=False)
        self._preflight_ok_at = now

    def _options(self) -> dict[str, Any]:
        return {"temperature": self.settings.temperature, "num_predict": self.settings.max_tokens,
                "num_ctx": self.settings.num_ctx}

    def check_truncation(self, prompt_tokens: int | None) -> None:
        """Raise when the server reports a prompt that filled the whole context window.

        Ollama truncates an oversized prompt to exactly ``num_ctx`` tokens (keeping
        the first four and the tail), so a reported prompt size at or above the
        window means the head of the prompt was discarded.
        """
        if isinstance(prompt_tokens, int) and prompt_tokens >= self.settings.num_ctx:
            raise truncation_error(prompt_tokens, self.settings.num_ctx, provider=self.kind)

    def check_prompt_size(self, text: str) -> None:
        estimated = estimate_tokens(text)
        if estimated > self.settings.num_ctx:
            raise oversized_prompt_error(estimated, self.settings.num_ctx, provider=self.kind)

    def generate_json(self, system: str, user: str, *, timeout: float | None = None) -> dict:
        self.require_configured()
        self.check_prompt_size(system + user)
        body: dict[str, Any] = {
            "model": self.model_id, "stream": False, "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": self._options(),
        }
        if self.settings.keep_alive:
            body["keep_alive"] = self.settings.keep_alive
        try:
            with self._http(timeout) as client:
                data = self._json(client.post("/api/chat", json=body))
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._normalize(exc) from exc
        self.check_truncation(data.get("prompt_eval_count"))
        content = ((data.get("message") or {}).get("content") or "").strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("provider_error", "Ollama returned a non-JSON response", provider=self.kind) from exc
        if not isinstance(parsed, dict):
            raise ProviderError("provider_error", "Ollama returned a non-object JSON response", provider=self.kind)
        return parsed

    def strands_model(self, options: ModelOptions | None = None):
        self.require_configured()
        options = options or ModelOptions()
        try:
            from strands.models.ollama import OllamaModel
        except Exception as exc:  # noqa: BLE001 - the optional ``ollama`` client package is missing
            raise ProviderError("provider_error", "Strands Ollama model unavailable: install the `ollama` package",
                                provider=self.kind) from exc
        policy = self.timeout_policy().merged(options)
        config: dict[str, Any] = {
            "model_id": self.model_id,
            "temperature": options.temperature if options.temperature is not None else self.settings.temperature,
            "max_tokens": options.max_tokens or self.settings.max_tokens,
            "options": {"num_ctx": self.settings.num_ctx},
        }
        if self.settings.keep_alive:
            config["keep_alive"] = self.settings.keep_alive
        timeout = self.http_timeout(policy.first_token_seconds, connect=policy.connect_seconds)
        return _guarded_model_class(OllamaModel)(
            self.settings.normalized_base_url(), ollama_client_args={"timeout": timeout}, provider=self, **config)


def _guarded_model_class(base):
    """``OllamaModel`` that refuses oversized prompts and rejects truncated ones."""

    class GuardedOllamaModel(base):
        def __init__(self, host, *, provider: OllamaProvider, **kwargs):
            super().__init__(host, **kwargs)
            self._provider = provider

        async def stream(self, messages, tool_specs=None, system_prompt=None, *, tool_choice=None, **kwargs):
            request = self.format_request(messages, tool_specs, system_prompt)
            self._provider.check_prompt_size(json.dumps(request))
            async for event in super().stream(messages, tool_specs, system_prompt, tool_choice=tool_choice, **kwargs):
                metadata = event.get("metadata") if isinstance(event, dict) else None
                if metadata:
                    self._provider.check_truncation((metadata.get("usage") or {}).get("inputTokens"))
                yield event

    GuardedOllamaModel.__name__ = base.__name__
    GuardedOllamaModel.__qualname__ = base.__qualname__
    GuardedOllamaModel.__module__ = base.__module__
    return GuardedOllamaModel
