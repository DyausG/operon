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

from pydantic import BaseModel, ConfigDict, Field

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
    # Non-secret tunables the Settings page may show and (per UPDATABLE_FIELDS) change.
    settings: dict[str, Any] = Field(default_factory=dict)
    timeouts: dict[str, float] = Field(default_factory=dict)


class TimeoutPolicy(BaseModel):
    """Provider-owned time bounds. Every value is seconds; the provider sets the defaults.

    ``connect``      TCP/TLS connect.
    ``first_token``  the transport read timeout. On a streamed chat this is the longest
                     silence tolerated before the first token (prompt evaluation) and
                     between chunks; on a non-streamed completion it bounds the whole reply.
    ``invocation``   one agent invocation: every model turn plus its tool calls.
    ``run``          one complete supervisor run including nested specialists.
    ``auxiliary``    one bounded JSON completion for the governance/monitoring peers.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    connect_seconds: float = Field(gt=0, le=120)
    first_token_seconds: float = Field(gt=0, le=3600)
    invocation_seconds: float = Field(gt=0, le=7200)
    run_seconds: float = Field(gt=0, le=14400)
    auxiliary_seconds: float = Field(gt=0, le=600)

    def merged(self, options: "ModelOptions | None") -> "TimeoutPolicy":
        """This policy with the explicitly supplied per-runtime overrides applied."""
        if options is None:
            return self
        changes = {
            "connect_seconds": options.connect_timeout_seconds,
            "first_token_seconds": options.read_timeout_seconds,
            "invocation_seconds": options.invocation_timeout_seconds,
            "run_seconds": options.run_timeout_seconds,
        }
        return self.model_copy(update={k: v for k, v in changes.items() if v is not None})


CLOUD_TIMEOUTS = TimeoutPolicy(connect_seconds=3, first_token_seconds=30, invocation_seconds=90,
                               run_seconds=240, auxiliary_seconds=20)


class ModelOptions(BaseModel):
    """Per-invocation knobs a runtime may pass when it asks for a Strands model.

    ``None`` means "the provider's own policy"; only an explicitly supplied value
    overrides it.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    temperature: float | None = None
    max_tokens: int | None = None
    connect_timeout_seconds: float | None = None
    read_timeout_seconds: float | None = None
    invocation_timeout_seconds: float | None = None
    run_timeout_seconds: float | None = None
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

    def timeout_policy(self) -> TimeoutPolicy:
        """The time bounds this provider considers appropriate; cloud defaults unless overridden."""
        return CLOUD_TIMEOUTS

    def preflight(self, *, tool_calling: bool = True) -> None:
        """Verify the selected model can serve the agent workflow; raise ``ProviderError`` otherwise.

        Cloud providers know their capabilities statically, so the default is a no-op.
        Local providers override this to check the pulled model before a run starts.
        """
        self.require_configured()

    def public_settings(self) -> dict[str, Any]:
        """Non-secret tunables for status and the Settings page. Never a credential."""
        return {}

    # Shared helpers -----------------------------------------------------
    def _status(self, **overrides) -> ProviderStatus:
        base = dict(provider=self.kind, display_name=self.display_name, configured=self.configured(),
                    model=self.model_id, credential=self.credential_status(), capabilities=self.capabilities(),
                    settings=self.public_settings(), timeouts=self.timeout_policy().model_dump())
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
