"""Amazon Bedrock AgentCore Runtime entrypoint.

The runtime receives only ``ReasoningRequest`` JSON. It constructs ephemeral
Strands/Bedrock runtimes and delegates to the existing packet-only handler; it
never constructs an application repository, database path, or authority service.
"""
from __future__ import annotations

import os
import time

from bedrock_agentcore import BedrockAgentCoreApp
from pydantic import ValidationError

from core.agents.runtime import RuntimeConfigurationError, RuntimeSettings, StrandsRuntime
from core.reasoning.handler import handler_identity, reason
from core.reasoning.protocol import (
    PROTOCOL_VERSION, ReasoningFailure, ReasoningRequest, ReasoningResponse, ReasoningTelemetry,
)

app = BedrockAgentCoreApp()


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeConfigurationError(f"{name} must be configured for the AgentCore runtime")
    return value


def _build_runtimes() -> tuple[StrandsRuntime, StrandsRuntime, str | None]:
    """Pure construction; Bedrock credentials/clients remain lazy in create_agent."""
    region = (os.getenv("OPERON_AWS_REGION", "").strip()
              or os.getenv("AWS_REGION", "").strip()
              or os.getenv("AWS_DEFAULT_REGION", "").strip())
    if not region:
        raise RuntimeConfigurationError("OPERON_AWS_REGION or AWS_REGION must be configured")
    supervisor = StrandsRuntime(RuntimeSettings(
        model_id=_required_environment("OPERON_BEDROCK_SUPERVISOR_MODEL_ID"),
        aws_region=region, live_enabled=True))
    specialists = StrandsRuntime(RuntimeSettings(
        model_id=_required_environment("OPERON_BEDROCK_SPECIALIST_MODEL_ID"),
        aws_region=region, live_enabled=True))
    return supervisor, specialists, os.getenv("OPERON_RUNTIME_BUILD_ID", "").strip() or None


# A narrow test seam. Production always leaves this bound to _build_runtimes.
_runtime_factory = _build_runtimes


def _session_id(context) -> str | None:
    if isinstance(context, dict):
        value = context.get("session_id")
    else:
        value = getattr(context, "session_id", None)
    return value if isinstance(value, str) and value else None


def _failure(request: ReasoningRequest, code: str, message: str, *, started: float,
             runtime: StrandsRuntime | None = None, specialists: StrandsRuntime | None = None,
             build_id: str | None = None) -> ReasoningResponse:
    identity = handler_identity(runtime, specialists, build_id=build_id) if runtime is not None else None
    return ReasoningResponse(
        incident_id=request.incident_id, run_id=request.run_id, snapshot_id=request.snapshot_id,
        input_revision=request.input_revision, status="FAILED", runtime_identity=identity,
        failure=ReasoningFailure(code=code, message=message, retryable=False),
        telemetry=ReasoningTelemetry(duration_ms=int((time.monotonic() - started) * 1000)),
    )


async def _invoke(payload, context) -> ReasoningResponse:
    started = time.monotonic()
    request = None
    if isinstance(payload, dict) and payload.get("protocol_version") == PROTOCOL_VERSION:
        try:
            request = ReasoningRequest.model_validate(payload)
        except ValidationError:
            # The shared handler returns the canonical PACKET_INVALID envelope.
            pass
    try:
        runtime, specialists, build_id = _runtime_factory()
    except RuntimeConfigurationError as exc:
        if request is None:
            raise
        return _failure(request, "MODEL_UNAVAILABLE", str(exc), started=started)
    if request is not None:
        actual_session_id = _session_id(context)
        if actual_session_id != request.runtime_session_id:
            return _failure(
                request, "PACKET_INVALID", "AgentCore session id differs from the reasoning packet",
                started=started, runtime=runtime, specialists=specialists, build_id=build_id)
        payload = request
    return await reason(payload, runtime, specialists, build_id=build_id)


@app.entrypoint
async def invoke(payload, context):
    """AgentCore JSON entrypoint; ``context`` name is required by the SDK.

    Version 1.22 runs async handlers on its long-lived worker loop. Keeping this
    async avoids creating and tearing down a nested event loop per invocation.
    """
    return (await _invoke(payload, context)).model_dump(mode="json")


if __name__ == "__main__":
    app.run()
