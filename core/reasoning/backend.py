"""Reasoning backends: the one seam through which advisory reasoning reaches the application.

AGENTS REASON. THE APPLICATION OWNS AUTHORITY. Every backend returns one
``SupervisorResult`` per durable run; ``PromotionService`` persists and re-audits
it and alone promotes. A backend can neither write evidence nor change a phase.
Importing this module creates no client, session or agent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import json

from core import config
from core.agents.contracts import SpecialistContext, SupervisorBounds, SupervisorResult
from core.agents.runtime import RuntimeConfigurationError, RuntimeSettings, StrandsRuntime
from core.reliability.repository import content_hash
from .errors import ReasoningBackendUnavailable
from .handler import handler_identity, reason
from .packet import build_request
from .protocol import SESSION_PREFIX
from .trust import validate_response

__all__ = ["BACKEND_MODES", "ReasoningBackend", "ReasoningBackendUnavailable", "LocalStrandsBackend",
           "InProcessPacketBackend", "as_backend", "backend_from_environment", "runtime_identity",
           "runtime_settings_for", "runtimes_from_registry"]

BACKEND_MODES = ("none", "local", "packet", "agentcore")


def runtime_identity(value: StrandsRuntime) -> dict:
    """Legacy snapshot shape for one Strands runtime; injected configuration is hashed."""
    model = value._model
    return {"settings": value.settings.model_dump(mode="json"),
            "timeouts": value.timeouts().model_dump(mode="json"),
            "implementation": value.model_implementation(),
            "injected_configuration_hash": content_hash(model.get_config()) if model else None}


class ReasoningBackend(ABC):
    """One reasoning path per durable run. Results are advisory input to application gates."""
    name: str

    @abstractmethod
    def identity(self) -> dict:
        """Frozen into ``SupervisorRunSnapshot.runtime_identity`` before any model call."""

    @abstractmethod
    async def supervise(self, service, context: SpecialistContext, *, bounds: SupervisorBounds,
                        snapshot=None, cancellation_result_handler=None) -> SupervisorResult:
        """Produce the advisory result for the frozen ``context`` of ``snapshot``."""

    async def preflight(self) -> None:
        """Fail before a durable run starts when the configured model cannot serve it.

        Raises ``RuntimeConfigurationError``. Remote backends validate on their own side.
        """
        return None

    def run_timeout(self) -> float:
        """The run bound this backend's provider policy prescribes (frozen into the snapshot)."""
        from core.providers.base import CLOUD_TIMEOUTS
        return CLOUD_TIMEOUTS.run_seconds


async def _preflight_runtimes(runtime: StrandsRuntime, specialist_runtime: StrandsRuntime | None) -> None:
    """Provider capability checks off the event loop (a local provider talks to its server)."""
    for candidate in (runtime, specialist_runtime):
        if candidate is not None:
            await asyncio.to_thread(candidate.preflight)


def _runtimes(runtime, specialist_runtime):
    if not isinstance(runtime, StrandsRuntime):
        raise TypeError("backend requires a StrandsRuntime")
    if specialist_runtime is not None and not isinstance(specialist_runtime, StrandsRuntime):
        raise TypeError("specialist runtime must be a StrandsRuntime")
    return runtime, specialist_runtime


class LocalStrandsBackend(ReasoningBackend):
    """Today's in-process path, unchanged: the supervisor holds the application EvidenceService."""
    name = "local"

    def __init__(self, runtime: StrandsRuntime, specialist_runtime: StrandsRuntime | None = None):
        self.runtime, self.specialist_runtime = _runtimes(runtime, specialist_runtime)

    def identity(self) -> dict:
        return {"backend": self.name, "supervisor": runtime_identity(self.runtime),
                "specialists": runtime_identity(self.specialist_runtime or self.runtime)}

    async def preflight(self) -> None:
        await _preflight_runtimes(self.runtime, self.specialist_runtime)

    def run_timeout(self) -> float:
        return self.runtime.run_timeout()

    async def supervise(self, service, context, *, bounds, snapshot=None, cancellation_result_handler=None):
        # Call-time import: the application test seam patches this module attribute.
        from core.agents.supervisor import supervise_reliability
        return await supervise_reliability(self.runtime, service, context, bounds=bounds,
                                           specialist_runtime=self.specialist_runtime,
                                           cancellation_result_handler=cancellation_result_handler)


class InProcessPacketBackend(ReasoningBackend):
    """The remote contract, executed in-process: packet -> handler -> trust validation.

    The handler only ever sees JSON, exactly as a remote runtime would, and its
    result only enters the application through ``trust.validate_response``.
    Cancellation propagates; no partial remote result is ever accepted.
    """
    name = "packet"

    def __init__(self, runtime: StrandsRuntime, specialist_runtime: StrandsRuntime | None = None, *,
                 build_id: str | None = None):
        self.runtime, self.specialist_runtime = _runtimes(runtime, specialist_runtime)
        self.build_id = build_id

    def expected_identity(self):
        return handler_identity(self.runtime, self.specialist_runtime, build_id=self.build_id)

    def identity(self) -> dict:
        return {"backend": self.name, "supervisor": runtime_identity(self.runtime),
                "specialists": runtime_identity(self.specialist_runtime or self.runtime),
                "expected_identity": self.expected_identity().model_dump(mode="json"),
                "session_id_scheme": SESSION_PREFIX + "{run_id}"}

    async def preflight(self) -> None:
        await _preflight_runtimes(self.runtime, self.specialist_runtime)

    def run_timeout(self) -> float:
        return self.runtime.run_timeout()

    async def supervise(self, service, context, *, bounds, snapshot=None, cancellation_result_handler=None):
        if snapshot is None:
            raise ValueError("packet reasoning requires the durable run snapshot")
        expected = self.expected_identity()
        incident = service.repository.fetch_incident(context.incident_id)
        try:
            request = build_request(service, incident, context, bounds, snapshot_id=snapshot.id,
                                    expected_identity=expected)
        except ValueError as exc:
            raise ReasoningBackendUnavailable(str(exc), code="PACKET_INVALID", retryable=False) from exc
        payload = json.loads(request.model_dump_json())
        response = await reason(payload, self.runtime, self.specialist_runtime, build_id=self.build_id)
        return validate_response(snapshot=snapshot, context=context, response=json.loads(response.model_dump_json()),
                                 repository=service.repository, expected_identity=expected)


def as_backend(runtime, specialist_runtime=None) -> ReasoningBackend:
    """Accept a bare ``StrandsRuntime`` (legacy callers) or a backend."""
    if isinstance(runtime, ReasoningBackend):
        if specialist_runtime is not None:
            raise TypeError("a reasoning backend already owns its specialist runtime")
        return runtime
    if isinstance(runtime, StrandsRuntime):
        return LocalStrandsBackend(runtime, specialist_runtime)
    raise TypeError("runtime must be a StrandsRuntime or a ReasoningBackend")


def runtime_settings_for(provider, *, model_id: str | None = None, **overrides) -> RuntimeSettings:
    """Explicit live settings for one provider; construction only, no credential or client."""
    kind = provider.kind
    if kind == "none":
        raise RuntimeConfigurationError(provider.not_configured_reason(), code="provider_not_configured")
    values = {"provider": kind, "model_id": model_id or provider.model_id, "live_enabled": True}
    if kind == "bedrock":
        values["aws_region"] = provider.settings.region
    elif kind == "ollama":
        values["endpoint"] = provider.settings.normalized_base_url()
    values.update(overrides)
    try:
        return RuntimeSettings(**values)
    except ValueError as exc:
        raise RuntimeConfigurationError(f"{kind} runtime settings invalid: {exc}", code="provider_not_configured") from exc


def runtimes_from_registry(registry=None) -> tuple[StrandsRuntime, StrandsRuntime | None]:
    """Supervisor and (optional, when a distinct model is configured) specialist runtimes."""
    from core.providers import get_registry
    registry = registry or get_registry()
    provider = registry.active()
    if provider.kind == "none" or not provider.configured():
        raise RuntimeConfigurationError(provider.not_configured_reason(), code="provider_not_configured")
    supervisor = StrandsRuntime(runtime_settings_for(provider), provider=provider)
    specialists = None
    specialist_model = registry.config.specialist_model
    if specialist_model and specialist_model != provider.model_id:
        specialist_provider = type(provider)(provider.settings.model_copy(
            update={"model_id" if provider.kind == "bedrock" else "model": specialist_model}))
        specialists = StrandsRuntime(runtime_settings_for(specialist_provider, model_id=specialist_model),
                                     provider=specialist_provider)
    return supervisor, specialists


def backend_from_environment(mode: str | None = None, *, registry=None) -> ReasoningBackend | None:
    """Select by OPERON_REASONING_BACKEND; never a silent fallback, never a client at import.

    ``local``/``packet`` build their Strands runtimes from the active model provider
    (Gemini, Ollama or Bedrock). With no configured provider they raise instead of
    silently degrading; the engine then reports the supervisor as awaiting a runtime.
    """
    mode = (mode if mode is not None else config.reasoning_backend()).strip().lower()
    if mode == "none":
        return None
    if mode == "agentcore":
        # Call-time import keeps boto3 client construction out of all import and
        # non-AgentCore paths. Settings validation performs no credential lookup.
        from .agentcore import AgentCoreBackend, AgentCoreSettings
        try:
            return AgentCoreBackend(AgentCoreSettings.from_environment())
        except ValueError as exc:
            raise RuntimeConfigurationError(str(exc)) from exc
    if mode not in {"local", "packet"}:
        raise RuntimeConfigurationError(
            f"unknown OPERON_REASONING_BACKEND {mode!r}; expected one of {', '.join(BACKEND_MODES)}")
    supervisor, specialists = runtimes_from_registry(registry)
    if mode == "local":
        return LocalStrandsBackend(supervisor, specialists)
    return InProcessPacketBackend(supervisor, specialists)
