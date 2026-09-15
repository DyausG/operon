"""Pure remote reasoning function: packet in, advisory response out.

``reason`` is what a reasoning runtime executes. It depends only on the request
and model output: it constructs no repository, opens no store, writes nothing and
mints no durable identity. The unchanged Strands supervisor runs over a
``PacketEvidenceAccess``; evidence needs surface as DEFERRED records.
"""
from __future__ import annotations

import asyncio
import time

from pydantic import ValidationError

from core.agents.runtime import RuntimeConfigurationError, StrandsRuntime
from core.reliability.repository import InvalidReference
from .finalization import AsyncGeneratorScope
from .identity import runtime_identity
from .packet import PacketEvidenceAccess
from .protocol import (
    PROTOCOL_VERSION, ReasoningFailure, ReasoningRequest, ReasoningResponse, ReasoningTelemetry,
    RuntimeIdentity,
)

CORRELATION_FIELDS = ("incident_id", "run_id", "snapshot_id", "input_revision")


def handler_identity(runtime: StrandsRuntime, specialist_runtime: StrandsRuntime | None = None, *,
                     build_id: str | None = None) -> RuntimeIdentity:
    """Identity of this code plus the configured models; computed, never asserted."""
    specialists = specialist_runtime or runtime
    return runtime_identity(supervisor_model_id=runtime.settings.model_id,
                            specialist_model_id=specialists.settings.model_id,
                            region=runtime.settings.identity_locator(), build_id=build_id)


def _correlation(payload) -> dict:
    fields = {}
    if isinstance(payload, dict):
        for key in CORRELATION_FIELDS:
            value = payload.get(key)
            if key == "input_revision":
                fields[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None
            else:
                fields[key] = value if isinstance(value, str) and value.strip() else None
    return fields


def _failed(correlation: dict, code: str, message: str, *, retryable: bool, started: float,
            identity: RuntimeIdentity | None = None) -> ReasoningResponse:
    return ReasoningResponse(
        **correlation, status="FAILED", runtime_identity=identity,
        failure=ReasoningFailure(code=code, message=message[:2000] or "failure", retryable=retryable),
        telemetry=ReasoningTelemetry(duration_ms=int((time.monotonic() - started) * 1000)))


async def reason(payload, runtime: StrandsRuntime, specialist_runtime: StrandsRuntime | None = None, *,
                 build_id: str | None = None) -> ReasoningResponse:
    """Run the unchanged supervisor over the packet. Never raises for protocol or model faults."""
    started = time.monotonic()
    if isinstance(payload, ReasoningRequest):
        request = payload
        correlation = {key: getattr(request, key) for key in CORRELATION_FIELDS}
    else:
        correlation = _correlation(payload)
        if not isinstance(payload, dict) or payload.get("protocol_version") != PROTOCOL_VERSION:
            return _failed(correlation, "PROTOCOL_MISMATCH",
                           f"expected protocol {PROTOCOL_VERSION}", retryable=False, started=started)
        try:
            request = ReasoningRequest.model_validate(payload)
        except ValidationError as exc:
            return _failed(correlation, "PACKET_INVALID", f"reasoning request rejected: {exc.error_count()} error(s)",
                           retryable=False, started=started)
    identity = handler_identity(runtime, specialist_runtime, build_id=build_id)
    drift = identity.drift(request.expected_identity)
    if drift:
        return _failed(correlation, "VERSION_MISMATCH", "runtime identity differs from expected: " + ", ".join(drift),
                       retryable=False, started=started, identity=identity)
    # Call-time import: the application test seam patches this module attribute.
    from core.agents.supervisor import supervise_reliability
    try:
        # Every Strands model/tool generator this run leaves suspended is closed
        # before the handler returns; nothing is left to GC timing or loop shutdown.
        async with AsyncGeneratorScope():
            access = PacketEvidenceAccess(request)
            result = await supervise_reliability(runtime, access, request.context, bounds=request.bounds,
                                                 specialist_runtime=specialist_runtime)
    except asyncio.CancelledError:
        raise
    except RuntimeConfigurationError as exc:
        return _failed(correlation, "MODEL_UNAVAILABLE", f"model configuration refused: {exc}",
                       retryable=False, started=started, identity=identity)
    except (InvalidReference, TypeError, ValueError) as exc:
        return _failed(correlation, "PACKET_INVALID", f"{type(exc).__name__}: {exc}",
                       retryable=False, started=started, identity=identity)
    except Exception as exc:
        return _failed(correlation, "INTERNAL", f"{type(exc).__name__}: {exc}",
                       retryable=True, started=started, identity=identity)
    if (result.termination_reason == "MODEL_FAILED" and not result.delegations
            and not result.assessments and result.tool_calls == 0):
        # Infrastructure failure before any reasoning happened: nothing advisory exists.
        return _failed(correlation, "MODEL_UNAVAILABLE", "model invocation failed before any delegation",
                       retryable=True, started=started, identity=identity)
    return ReasoningResponse(
        **correlation, status="COMPLETED", runtime_identity=identity, result=result.model_dump(mode="json"),
        telemetry=ReasoningTelemetry(duration_ms=int((time.monotonic() - started) * 1000)))
