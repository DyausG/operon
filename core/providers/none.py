"""Truthful no-provider mode: deterministic Operon with model-backed reasoning disabled."""
from __future__ import annotations

from .base import Capabilities, CredentialStatus, DISPLAY_NAMES, ModelOptions, ModelProvider, ProviderStatus
from .errors import ProviderError

REASON = ("No model provider is configured. Deterministic telemetry, health scoring, incident "
          "admission, baseline evidence and the Guided Demo remain available; model-backed "
          "reasoning is disabled, live incidents wait in INVESTIGATING and the Guided Demo uses "
          "the labelled deterministic advisory (no model).")


class NoProvider(ModelProvider):
    kind = "none"
    display_name = DISPLAY_NAMES["none"]

    @property
    def model_id(self) -> None:
        return None

    def configured(self) -> bool:
        return False

    def credential_status(self) -> CredentialStatus:
        return CredentialStatus(configured=False, source="not_required", detail="no credential needed")

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def describe(self) -> ProviderStatus:
        return self._status(reachable=None, detail=REASON)

    def test_connection(self, *, timeout: float | None = None) -> ProviderStatus:
        return self._status(reachable=None, probe="connection", detail=REASON)

    def strands_model(self, options: ModelOptions | None = None):
        raise ProviderError("provider_not_configured", REASON, provider=self.kind)

    def generate_json(self, system: str, user: str, *, timeout: float | None = None) -> dict:
        raise ProviderError("provider_not_configured", REASON, provider=self.kind)

    def identity_locator(self) -> str:
        return "none"

    def not_configured_reason(self) -> str:
        return REASON
