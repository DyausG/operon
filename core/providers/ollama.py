"""Ollama / local open-source model provider.

Talks to a running Ollama server over its HTTP API (httpx) for status, model
validation and bounded JSON completions, and hands Strands its ``OllamaModel``
for the supervisor/specialist agents. Nothing here installs Ollama or pulls a
model: an absent server or model is reported truthfully as a normalized error.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .base import Capabilities, CredentialStatus, DISPLAY_NAMES, ModelOptions, ModelProvider, ProviderStatus, now_iso
from .errors import ProviderError, normalize_exception

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


class OllamaSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str = Field(default=DEFAULT_OLLAMA_BASE_URL, min_length=1, max_length=300, pattern=r"^https?://\S+$")
    model: str = Field(default="", max_length=200)
    timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    max_tokens: int = Field(default=2048, ge=1, le=65536)
    temperature: float = Field(default=0.2, ge=0, le=2)
    keep_alive: str | None = None

    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")


def _same_model(configured: str, installed: str) -> bool:
    if configured == installed:
        return True
    return f"{configured}:latest" == installed or configured == f"{installed}:latest"


class OllamaProvider(ModelProvider):
    kind = "ollama"
    display_name = DISPLAY_NAMES["ollama"]

    def __init__(self, settings: OllamaSettings, *, transport: httpx.BaseTransport | None = None):
        self.settings = OllamaSettings.model_validate(settings)
        self._transport = transport

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

    def describe(self) -> ProviderStatus:
        return self._status(endpoint=self.settings.normalized_base_url(),
                            detail="configured (reachability unverified)" if self.configured() else self.not_configured_reason())

    # ---- transport --------------------------------------------------------
    def _http(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(base_url=self.settings.normalized_base_url(),
                            timeout=httpx.Timeout(timeout or self.settings.timeout_seconds,
                                                  connect=self.settings.connect_timeout_seconds),
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
        return self._status(reachable=True, probe="connection", endpoint=endpoint, models=models,
                            capabilities=capabilities, checked_at=now_iso(),
                            detail=f"Ollama {version} reachable; model {match} available")

    def generate_json(self, system: str, user: str, *, timeout: float | None = None) -> dict:
        self.require_configured()
        body: dict[str, Any] = {
            "model": self.model_id, "stream": False, "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": self.settings.temperature, "num_predict": self.settings.max_tokens},
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
        config: dict[str, Any] = {
            "model_id": self.model_id,
            "temperature": options.temperature if options.temperature is not None else self.settings.temperature,
            "max_tokens": options.max_tokens or self.settings.max_tokens,
        }
        if self.settings.keep_alive:
            config["keep_alive"] = self.settings.keep_alive
        timeout = options.read_timeout_seconds or self.settings.timeout_seconds
        return OllamaModel(self.settings.normalized_base_url(), ollama_client_args={"timeout": timeout}, **config)
