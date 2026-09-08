"""Explicit evidence allowlist. No executor, service registry, SQL, or state tools.

Only request_evidence can write, through the existing application EvidenceService.
Its incident, asset, role, and purpose come from the trusted per-run scope.
"""
from __future__ import annotations

import asyncio

from pydantic import AwareDatetime, BaseModel, Field, JsonValue, model_validator
from strands import ToolContext, tool
from strands.types.tools import AgentTool

from core.reliability.evidence import EvidenceService
from .contracts import AdvisoryContract, DiagnosticContext, Reference, Text

DIAGNOSTIC_TOOL_NAMES = frozenset({
    "get_asset_context", "get_telemetry_window", "get_maintenance_history",
    "get_related_incidents", "get_operating_context", "request_evidence",
})
MAX_TOOL_OUTPUT_BYTES = 48_000
MAX_EVIDENCE_TOOL_CALLS = 12


class EvidenceQuery(AdvisoryContract):
    capability: Reference
    question: Text
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_parameters(self):
        if len(self.model_dump_json().encode()) > 4000:
            raise ValueError("evidence request exceeds 4000 bytes")
        return self


def bounded_result(result: BaseModel) -> dict:
    """Never silently truncate provenance or present partial content as complete."""
    if len(result.model_dump_json().encode()) > MAX_TOOL_OUTPUT_BYTES:
        raise ValueError("evidence response exceeds 48000 bytes; request a smaller window/limit")
    return {
        "status": "success",
        "content": [{"json": result.model_dump(mode="json")}],
    }


def diagnostic_tools(service: EvidenceService, scope: DiagnosticContext,
                     collected_evidence_ids: set[str]) -> list[AgentTool]:
    """Fresh closures per invocation; the set tracks returned citations, not domain state."""
    calls = 0

    def check_context(context: ToolContext):
        nonlocal calls
        expected = {"incident_id": scope.incident_id, "run_id": scope.run_id,
                    "input_revision": scope.input_revision}
        if any(context.invocation_state.get(key) != value for key, value in expected.items()):
            raise ValueError("tool invocation does not match trusted incident/run scope")
        if calls >= MAX_EVIDENCE_TOOL_CALLS:
            raise ValueError("evidence tool call budget exhausted")
        calls += 1

    async def read(capability: str, parameters: dict, context: ToolContext) -> dict:
        check_context(context)
        result = await asyncio.to_thread(
            service.capabilities.collect, capability, scope.asset_id, parameters,
            incident_id=scope.incident_id,
        )
        return bounded_result(result)

    @tool(context=True)
    async def get_asset_context(tool_context: ToolContext) -> dict:
        """Read the scoped asset and sensor context; unknown OEM limits stay explicit."""
        return await read("get_asset_context", {}, tool_context)

    @tool(context=True)
    async def get_telemetry_window(tool_context: ToolContext, sensor_type: str | None = None,
                                   start_at: AwareDatetime | None = None,
                                   end_at: AwareDatetime | None = None,
                                   sample_limit: int = 60) -> dict:
        """Read persisted scoped telemetry; sample_limit is 1..500 per sensor."""
        return await read("get_telemetry_window", dict(sensor_type=sensor_type,
                          start_at=start_at, end_at=end_at, sample_limit=sample_limit), tool_context)

    @tool(context=True)
    async def get_maintenance_history(tool_context: ToolContext,
                                      limit: int = 20,
                                      before: AwareDatetime | None = None) -> dict:
        """Read scoped persisted maintenance records; limit is 1..100."""
        return await read("get_maintenance_history", dict(limit=limit, before=before), tool_context)

    @tool(context=True)
    async def get_related_incidents(tool_context: ToolContext,
                                    limit: int = 20) -> dict:
        """Read same-asset incident history, excluding this incident; limit is 1..100."""
        return await read("get_related_incidents", dict(limit=limit), tool_context)

    @tool(context=True)
    async def get_operating_context(tool_context: ToolContext) -> dict:
        """Read scoped operational context with unavailable calendar data explicit."""
        return await read("get_operating_context", {}, tool_context)

    @tool(context=True)
    async def request_evidence(query: EvidenceQuery, tool_context: ToolContext) -> dict:
        """Request one supported capability via Operon; returns durable evidence IDs and provenance.

        Args:
            query: Capability, question, and its bounded capability-specific parameters.
        """
        check_context(tool_context)
        query = EvidenceQuery.model_validate(query)
        collection = await asyncio.to_thread(
            service.request_and_collect, scope.incident_id, requested_by="diagnostic",
            equipment_ids=(scope.asset_id,), question=query.question, capability=query.capability,
            required_for="diagnosis", parameters=query.parameters,
        )
        result = bounded_result(collection)
        collected_evidence_ids.add(collection.evidence.id)
        return result

    return [get_asset_context, get_telemetry_window, get_maintenance_history,
            get_related_incidents, get_operating_context, request_evidence]
