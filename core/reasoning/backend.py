"""Reasoning backends: the one seam through which advisory reasoning reaches the application.

AGENTS REASON. THE APPLICATION OWNS AUTHORITY. Every backend returns one
``SupervisorResult`` per durable run; ``PromotionService`` persists and re-audits
it and alone promotes. A backend can neither write evidence nor change a phase.
Importing this module creates no client, session or agent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
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
           "InProcessPacketBackend", "as_backend", "backend_from_environment", "runtime_identity"]

BACKEND_MODES = ("none", "local", "packet", "agentcore")


def runtime_identity(value: StrandsRuntime) -> dict:
    """Legacy snapshot shape for one Strands runtime; injected configuration is hashed."""
    model = value._model
    return {"settings": value.settings.model_dump(mode="json"),
            "implementation": f"{type(model).__module__}.{type(model).__qualname__}" if model else "strands.BedrockModel",
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


def backend_from_environment(mode: str | None = None) -> ReasoningBackend | None:
    """Select by OPERON_REASONING_BACKEND; never a silent fallback, never a client at import."""
    mode = (mode if mode is not None else config.reasoning_backend()).strip().lower()
    if mode == "none":
        return None
    if mode == "agentcore":
        raise RuntimeConfigurationError(
            "OPERON_REASONING_BACKEND=agentcore requires the AgentCore client (Step 15B), which does not exist yet")
    if mode not in {"local", "packet"}:
        raise RuntimeConfigurationError(
            f"unknown OPERON_REASONING_BACKEND {mode!r}; expected one of {', '.join(BACKEND_MODES)}")
    supervisor = StrandsRuntime(RuntimeSettings(model_id=config.BEDROCK_SUPERVISOR_MODEL_ID,
                                                aws_region=config.AWS_REGION, live_enabled=True))
    specialists = None
    if config.BEDROCK_SPECIALIST_MODEL_ID != config.BEDROCK_SUPERVISOR_MODEL_ID:
        specialists = StrandsRuntime(RuntimeSettings(model_id=config.BEDROCK_SPECIALIST_MODEL_ID,
                                                     aws_region=config.AWS_REGION, live_enabled=True))
    if mode == "local":
        return LocalStrandsBackend(supervisor, specialists)
    return InProcessPacketBackend(supervisor, specialists)
