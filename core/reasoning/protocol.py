"""Strict remote reasoning protocol (``operon-reasoning-1``).

Everything that crosses to a reasoning runtime is application-generated; everything
that returns is untrusted until ``core.reasoning.trust`` validates it. All envelopes
are ``extra="forbid"`` and frozen. Nothing here reads a store or opens a client.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from core.agents.contracts import Reference, SpecialistContext, SupervisorBounds, Text
from core.reliability.models import Incident

PROTOCOL_VERSION = "operon-reasoning-1"
# Hard cap on one request; AgentCore allows 100 MB, the packet is bounded far below.
MAX_REQUEST_BYTES = 1_000_000
# One durable run == one runtime session; AgentCore requires >= 33 characters.
SESSION_PREFIX = "operon-run-"
MIN_SESSION_ID_LENGTH = 33
MAX_PACKET_READS = 32

FailureCode = Literal["PROTOCOL_MISMATCH", "VERSION_MISMATCH", "PACKET_INVALID", "MODEL_UNAVAILABLE", "INTERNAL"]
Stage = Literal["DIAGNOSIS", "INTERVENTION_REVIEW"]


def runtime_session_id(run_id: str) -> str:
    """Deterministic session id derived from the application run id, never chosen remotely."""
    value = f"{SESSION_PREFIX}{run_id}"
    if len(value) < MIN_SESSION_ID_LENGTH or any(char.isspace() for char in value):
        raise ValueError("runtime session id must derive from a run id of at least 22 non-blank characters")
    return value


def read_key(capability: str, parameters: dict) -> str:
    """Canonical key of one pre-materialized read: capability plus normalized parameters."""
    return json.dumps([capability, parameters], sort_keys=True, separators=(",", ":"))


class ProtocolContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RuntimeIdentity(ProtocolContract):
    """Code and configuration identity a runtime must prove before its advice is read.

    Hashes come from ``core.reasoning.identity.code_identity`` on both sides; model
    ids and region come from configuration. ``build_id`` is informational only.
    """
    policy: Reference
    strands_version: Reference
    prompts: Reference
    result_schema: Reference
    context_schema: Reference
    supervisor_model_id: Reference
    specialist_model_id: Reference
    region: Reference
    build_id: Reference | None = None

    def drift(self, expected: "RuntimeIdentity") -> tuple[str, ...]:
        """Names of the identity fields that differ (``build_id`` never counts)."""
        mine, theirs = self.model_dump(), expected.model_dump()
        return tuple(sorted(key for key in mine if key != "build_id" and mine[key] != theirs[key]))

    def matches(self, expected: "RuntimeIdentity") -> bool:
        return not self.drift(expected)


class PacketRead(ProtocolContract):
    """One pre-materialized read-only observation. Not durable evidence; it has no ID."""
    capability: Reference
    parameters: dict[str, JsonValue]
    result: dict[str, JsonValue]


class ReasoningRequest(ProtocolContract):
    """Application -> runtime. The frozen run inputs plus bounded read results."""
    protocol_version: Literal["operon-reasoning-1"] = PROTOCOL_VERSION
    incident_id: Reference
    run_id: Reference
    snapshot_id: Reference
    input_revision: int = Field(ge=1)
    asset_id: Reference
    stage: Stage
    runtime_session_id: Reference
    context: SpecialistContext
    incident: Incident
    bounds: SupervisorBounds
    reads: tuple[PacketRead, ...] = Field(max_length=MAX_PACKET_READS)
    expected_identity: RuntimeIdentity

    @model_validator(mode="after")
    def coherent(self):
        context = self.context
        if (context.incident_id, context.run_id, context.input_revision, context.asset_id, context.run_purpose) != (
                self.incident_id, self.run_id, self.input_revision, self.asset_id, self.stage):
            raise ValueError("packet correlation differs from the frozen context")
        if self.incident.id != self.incident_id or self.asset_id not in self.incident.equipment_ids:
            raise ValueError("packet incident differs from the run correlation")
        if (self.incident.revision != self.input_revision or self.incident.active_run_id != self.run_id
                or self.incident.phase != context.lifecycle_state):
            raise ValueError("packet incident is not the frozen run checkpoint")
        if self.runtime_session_id != runtime_session_id(self.run_id):
            raise ValueError("runtime session id must derive from the run id")
        keys = [read_key(item.capability, item.parameters) for item in self.reads]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate read parameterization in packet")
        if len(self.model_dump_json().encode()) > MAX_REQUEST_BYTES:
            raise ValueError(f"reasoning request exceeds {MAX_REQUEST_BYTES} bytes; no truncation is performed")
        return self


class ReasoningFailure(ProtocolContract):
    code: FailureCode
    message: Text
    retryable: bool


class ReasoningTelemetry(ProtocolContract):
    """Informational only; never read for any application decision."""
    duration_ms: int = Field(ge=0)
    model_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    trace_id: Reference | None = None


class ReasoningResponse(ProtocolContract):
    """Runtime -> application. Untrusted until ``trust.validate_response`` accepts it."""
    protocol_version: Literal["operon-reasoning-1"] = PROTOCOL_VERSION
    incident_id: Reference | None = None
    run_id: Reference | None = None
    snapshot_id: Reference | None = None
    input_revision: int | None = Field(default=None, ge=1)
    status: Literal["COMPLETED", "FAILED"]
    failure: ReasoningFailure | None = None
    runtime_identity: RuntimeIdentity | None = None
    # Advisory SupervisorResult JSON; parsed and re-validated by the application.
    result: dict[str, JsonValue] | None = None
    telemetry: ReasoningTelemetry | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "COMPLETED":
            if self.result is None or self.runtime_identity is None or self.failure is not None:
                raise ValueError("a completed response carries a result and identity and no failure")
            if None in (self.incident_id, self.run_id, self.snapshot_id, self.input_revision):
                raise ValueError("a completed response must echo the full run correlation")
        elif self.failure is None or self.result is not None:
            raise ValueError("a failed response carries a failure and no result")
        return self
