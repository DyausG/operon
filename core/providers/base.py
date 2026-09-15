"""The ModelProvider boundary: everything Operon needs from a model vendor, nothing more.

Operon's reliability domain (incident lifecycle, evidence, promotion, governance,
execution, outcome verification) never imports a vendor SDK. It asks a
``ModelProvider`` for a Strands ``Model`` (supervisor and specialist agents) or a
bounded JSON completion (the governance/monitoring peers), and reads status and
capability metadata that the API and the Settings page can show without secrets.

Importing this module creates no client, session or socket. Provider creation is
centralized in ``core.providers.registry``; later PRISM work may build one provider
per role (fast/slow path) through the same factory.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from .errors import ProviderError

ProviderKind = Literal["none", "gemini", "ollama", "bedrock"]
PROVIDER_KINDS: tuple[str, ...] = ("none", "gemini", "ollama", "bedrock")
DISPLAY_NAMES = {"none": "No model provider", "gemini": "Google Gemini", "ollama": "Ollama (local)",
                 "bedrock": "Amazon Bedrock"}
Locality = Literal["none", "local", "cloud"]


class Capabilities(BaseModel):
    """What the selected provider/model is known to support. ``None`` means unverified."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    text_generation: bool | None = False
    structured_output: bool | None = False
    tool_calling: bool | None = False
    streaming: bool | None = False
    image_input: bool | None = False
    locality: Locality = "none"


class CredentialStatus(BaseModel):
    """Configured/masked credential status. Never carries a secret value."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    configured: bool = False
    source: Literal["none", "environment", "session", "aws_chain", "not_required"] = "none"
    detail: str = ""


class ProviderStatus(BaseModel):
    """Non-secret provider state for the API, the Settings page and the launcher."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    display_name: str
    configured: bool
    reachable: bool | None = None
    model: str | None = None
    models: tuple[str, ...] = ()
    endpoint: str | None = None
    region: str | None = None
    credential: CredentialStatus = CredentialStatus()
    capabilities: Capabilities = Capabilities()
    probe: Literal["none", "connection"] = "none"
    error: dict[str, Any] | None = None
    checked_at: str | None = None
    detail: str = ""


class ModelOptions(BaseModel):
    """Per-invocation knobs a runtime may pass when it asks for a Strands model."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    temperature: float | None = None
    max_tokens: int | None = None
    connect_timeout_seconds: float | None = None
    read_timeout_seconds: float | None = None
    request_attempts: int | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ModelProvider(ABC):
    """One configured provider + model. Construction performs no I/O."""

    kind: ClassVar[str]
    display_name: ClassVar[str]

    @property
    @abstractmethod
    def model_id(self) -> str | None:
        """The configured model identifier (``None`` when nothing is configured)."""

    @abstractmethod
    def configured(self) -> bool:
        """True when every required non-network prerequisite is present."""

    @abstractmethod
    def credential_status(self) -> CredentialStatus:
        """Configured/masked credential status; never a secret."""

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Capabilities known without a network call."""

    @abstractmethod
    def describe(self) -> ProviderStatus:
        """Static status without touching the network."""

    @abstractmethod
    def test_connection(self, *, timeout: float | None = None) -> ProviderStatus:
        """Validate credentials/reachability/model. Never raises; failures land in ``error``."""

    @abstractmethod
    def strands_model(self, options: ModelOptions | None = None):
        """A Strands ``Model`` bound to this provider; raises ``ProviderError`` when unusable."""

    @abstractmethod
    def generate_json(self, system: str, user: str, *, timeout: float | None = None) -> dict:
        """One bounded JSON-object completion; raises ``ProviderError`` on any failure."""

    @abstractmethod
    def identity_locator(self) -> str:
        """Non-secret endpoint/region string frozen into run identity (e.g. an AWS region)."""

    # Shared helpers -----------------------------------------------------
    def _status(self, **overrides) -> ProviderStatus:
        base = dict(provider=self.kind, display_name=self.display_name, configured=self.configured(),
                    model=self.model_id, credential=self.credential_status(), capabilities=self.capabilities())
        base.update(overrides)
        return ProviderStatus(**base)

    def _failed(self, error: ProviderError, **overrides) -> ProviderStatus:
        values = dict(reachable=False, probe="connection", error=error.to_dict(), checked_at=now_iso())
        values.update(overrides)
        return self._status(**values)

    def require_configured(self) -> None:
        if not self.configured():
            raise ProviderError("provider_not_configured", self.not_configured_reason(), provider=self.kind)

    def not_configured_reason(self) -> str:
        return f"{self.display_name} is not configured"
