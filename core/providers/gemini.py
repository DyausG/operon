"""Google Gemini provider (google-genai SDK; Strands ``GeminiModel`` for agents).

The API key is server-side only: it is read from the environment or set for the
process through the registry, held as a ``SecretStr`` and never serialized.
Constructing the provider performs no I/O; clients are created per call.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .base import Capabilities, CredentialStatus, DISPLAY_NAMES, ModelOptions, ModelProvider, ProviderStatus, now_iso
from .errors import ProviderError, normalize_exception

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
GEMINI_ENDPOINT = "generativelanguage.googleapis.com"


class GeminiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    api_key: SecretStr | None = None
    key_source: str = "none"          # none | environment | session
    model: str = Field(default=DEFAULT_GEMINI_MODEL, min_length=1, max_length=200, pattern=r"\S")
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_output_tokens: int = Field(default=1024, ge=1, le=65536)
    temperature: float = Field(default=0.2, ge=0, le=2)

    def key(self) -> str | None:
        value = self.api_key.get_secret_value().strip() if self.api_key is not None else ""
        return value or None


def _default_client_factory(api_key: str, timeout_seconds: float):
    from google import genai
    from google.genai import types
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)))


class GeminiProvider(ModelProvider):
    kind = "gemini"
    display_name = DISPLAY_NAMES["gemini"]

    def __init__(self, settings: GeminiSettings, *, client_factory: Callable[[str, float], Any] | None = None):
        self.settings = GeminiSettings.model_validate(settings)
        self._client_factory = client_factory or _default_client_factory

    # ---- metadata ---------------------------------------------------------
    @property
    def model_id(self) -> str:
        return self.settings.model

    def configured(self) -> bool:
        return self.settings.key() is not None

    def credential_status(self) -> CredentialStatus:
        if not self.configured():
            return CredentialStatus(configured=False, source="none", detail="GEMINI_API_KEY is not set")
        source = "session" if self.settings.key_source == "session" else "environment"
        return CredentialStatus(configured=True, source=source, detail="API key present (server-side)")

    def capabilities(self) -> Capabilities:
        return Capabilities(text_generation=True, structured_output=True, tool_calling=True, streaming=True,
                            image_input=True, locality="cloud")

    def identity_locator(self) -> str:
        return GEMINI_ENDPOINT

    def not_configured_reason(self) -> str:
        return "Gemini needs GEMINI_API_KEY (server-side) before it can be used"

    def describe(self) -> ProviderStatus:
        return self._status(endpoint=GEMINI_ENDPOINT,
                            detail="configured" if self.configured() else self.not_configured_reason())

    # ---- clients ----------------------------------------------------------
    def _secrets(self):
        return (self.settings.key(),)

    def client(self, timeout: float | None = None):
        self.require_configured()
        try:
            return self._client_factory(self.settings.key(), timeout or self.settings.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - SDK construction failures are provider errors
            raise self._normalize(exc) from exc

    def _normalize(self, exc: BaseException) -> ProviderError:
        return normalize_exception(exc, provider=self.kind, secrets=self._secrets()) or ProviderError(
            "provider_error", f"{type(exc).__name__}: {exc}", provider=self.kind, secrets=self._secrets())

    # ---- operations -------------------------------------------------------
    def test_connection(self, *, timeout: float | None = None) -> ProviderStatus:
        if not self.configured():
            return self._failed(ProviderError("provider_not_configured", self.not_configured_reason(), provider=self.kind),
                                endpoint=GEMINI_ENDPOINT)
        try:
            client = self.client(timeout)
            info = client.models.get(model=self.settings.model)
        except ProviderError as err:
            return self._failed(err, endpoint=GEMINI_ENDPOINT)
        except Exception as exc:  # noqa: BLE001
            return self._failed(self._normalize(exc), endpoint=GEMINI_ENDPOINT)
        resolved = getattr(info, "name", None) or self.settings.model
        return self._status(reachable=True, probe="connection", endpoint=GEMINI_ENDPOINT, checked_at=now_iso(),
                            detail=f"credential accepted; model {resolved} available")

    def generate_json(self, system: str, user: str, *, timeout: float | None = None) -> dict:
        client = self.client(timeout)
        try:
            from google.genai import types
            from core import gemini as transport
            response = transport.generate(
                client, model=self.settings.model,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=user)])],
                config=types.GenerateContentConfig(
                    system_instruction=system, temperature=self.settings.temperature,
                    max_output_tokens=self.settings.max_output_tokens, response_mime_type="application/json"))
            text = (getattr(response, "text", None) or "").strip()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._normalize(exc) from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("provider_error", "Gemini returned a non-JSON response", provider=self.kind) from exc
        if not isinstance(data, dict):
            raise ProviderError("provider_error", "Gemini returned a non-object JSON response", provider=self.kind)
        return data

    def strands_model(self, options: ModelOptions | None = None):
        self.require_configured()
        options = options or ModelOptions()
        try:
            from strands.models.gemini import GeminiModel
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("provider_error", f"Strands Gemini model unavailable: {type(exc).__name__}",
                                provider=self.kind) from exc
        timeout = options.read_timeout_seconds or self.settings.timeout_seconds
        params = {"temperature": options.temperature if options.temperature is not None else self.settings.temperature,
                  "max_output_tokens": options.max_tokens or self.settings.max_output_tokens}
        return GeminiModel(client_args={"api_key": self.settings.key(),
                                        "http_options": {"timeout": int(timeout * 1000)}},
                           model_id=self.settings.model, params=params)
