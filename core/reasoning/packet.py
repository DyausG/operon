"""Bounded, application-built evidence packet and read-only packet-backed access.

A reasoning runtime sees only what ``build_request`` materialized inside the
application: the frozen context, this incident's record, pre-read observations and
the run bounds. ``PacketEvidenceAccess`` satisfies the same duck-typed seam as
``EvidenceService`` (``repository``, ``capabilities``, ``request_and_collect``,
``same_store``, ``resource_reads``) without any store, path, connection or write:
requesting evidence raises ``EvidenceDeferred`` so the run can only name the need.

Only ``build_request`` reads, through the application's own ``EvidenceService``.
"""
from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, ValidationError

from core.agents.contracts import SpecialistContext, SupervisorBounds
from core.agents.tools import MAX_TOOL_OUTPUT_BYTES, RESOURCE_TOOL_NAMES
from core.reliability import models as m
from core.reliability.evidence import (
    SUPPORTED_CAPABILITIES, CapabilityResult, EvidenceCapabilities, EvidenceDeferred,
)
from core.reliability.repository import InvalidReference
from core.reliability.resources import InventoryAvailability, MaintenanceWindows, ResourceQuery, WorkforceAvailability
from .protocol import PacketRead, ReasoningRequest, RuntimeIdentity, read_key, runtime_session_id

__all__ = ["EvidenceDeferred", "PacketTooLarge", "PacketCapabilities", "PacketResourceCapabilities",
           "PacketEvidenceAccess", "SnapshotRepository", "build_request",
           "DEFAULT_EVIDENCE_READS", "DEFAULT_RESOURCE_READS"]

# Default parameterization of every read tool a role may call (core/agents/tools.py
# defaults). The packet serves exactly these; other parameterizations are not
# silently approximated, the tool reports that the read is not in the packet.
DEFAULT_EVIDENCE_READS: tuple[tuple[str, dict], ...] = (
    ("get_asset_context", {}),
    ("get_telemetry_window", {"sensor_type": None, "start_at": None, "end_at": None, "sample_limit": 60}),
    ("get_maintenance_history", {"limit": 20, "before": None}),
    ("get_related_incidents", {"limit": 20}),
    ("get_operating_context", {}),
)
DEFAULT_RESOURCE_READS: tuple[tuple[str, dict], ...] = (
    ("check_part_availability", {"limit": 20}),
    ("inspect_available_technicians", {"limit": 20}),
    ("inspect_maintenance_windows", {"limit": 20}),
)
RESOURCE_RESULTS = {"check_part_availability": InventoryAvailability,
                    "inspect_available_technicians": WorkforceAvailability,
                    "inspect_maintenance_windows": MaintenanceWindows}


class PacketTooLarge(ValueError):
    """A read or the whole request exceeds its bound; nothing is truncated."""


def build_request(service, incident: m.Incident, context: SpecialistContext, bounds: SupervisorBounds, *,
                  snapshot_id: str, expected_identity: RuntimeIdentity,
                  extra_reads: tuple[tuple[str, dict], ...] = ()) -> ReasoningRequest:
    """Application side only: materialize the bounded packet for one durable run.

    Reads go through the application's ``EvidenceService`` capabilities exactly as
    the local tools would issue them. Oversized reads and oversized requests are
    refused, never truncated.
    """
    if not service.same_store():
        raise ValueError("evidence capabilities and repository must use the same application store")
    capabilities = service.capabilities
    resources = service.resource_reads()
    reads: list[PacketRead] = []
    for capability, parameters in (*DEFAULT_EVIDENCE_READS, *extra_reads):
        normalized = capabilities.validate_parameters(capability, parameters)
        result = capabilities.collect(capability, context.asset_id, normalized, incident_id=context.incident_id)
        reads.append(PacketRead(capability=capability, parameters=normalized,
                                result=_check_size(result, f"{capability} read")))
    for name, parameters in DEFAULT_RESOURCE_READS:
        limit = ResourceQuery(limit=parameters["limit"]).limit
        result = getattr(resources, name)(context.asset_id, limit=limit)
        reads.append(PacketRead(capability=name, parameters={"limit": limit},
                                result=_check_size(result, f"{name} read")))
    try:
        return ReasoningRequest(
            incident_id=context.incident_id, run_id=context.run_id, snapshot_id=snapshot_id,
            input_revision=context.input_revision, asset_id=context.asset_id, stage=context.run_purpose,
            runtime_session_id=runtime_session_id(context.run_id), context=context, incident=incident,
            bounds=bounds, reads=tuple(reads), expected_identity=expected_identity)
    except ValidationError as exc:
        if "exceeds" in str(exc):
            raise PacketTooLarge(str(exc)) from exc
        raise


def _check_size(result, what: str) -> dict:
    payload = result.model_dump(mode="json")
    if len(result.model_dump_json().encode()) > MAX_TOOL_OUTPUT_BYTES:
        raise PacketTooLarge(f"{what} exceeds {MAX_TOOL_OUTPUT_BYTES} bytes; the packet refuses truncated observations")
    return payload


class SnapshotRepository:
    """Read-only view over the packet: this incident and the artifacts frozen in its context.

    Satisfies the two repository methods the reasoning layer relies on. Unknown or
    foreign references fail exactly like a durable lookup would.
    """

    def __init__(self, incident: m.Incident, context: SpecialistContext):
        if incident.id != context.incident_id:
            raise InvalidReference("packet incident differs from the frozen context")
        self.incident = incident
        self.artifacts: dict[str, m.Artifact] = {item.id: item for item in (*context.evidence, *context.artifacts)}

    def fetch_incident(self, incident_id: str) -> m.Incident:
        if incident_id != self.incident.id:
            raise InvalidReference(f"incident {incident_id} is not in the reasoning packet")
        return self.incident

    def get_artifact(self, incident_id: str, artifact_id: str) -> m.Artifact:
        if incident_id != self.incident.id or artifact_id not in self.artifacts:
            raise InvalidReference(f"artifact {artifact_id} not found in reasoning packet for incident {incident_id}")
        return self.artifacts[artifact_id]


class PacketCapabilities(EvidenceCapabilities):
    """Serves only pre-materialized reads. No store path, no connection, no manifests."""

    def __init__(self, reads: tuple[PacketRead, ...], *, asset_id: str, incident_id: str):
        # Deliberately no super().__init__(): there is no store and no ``path``.
        self.asset_id = asset_id
        self.incident_id = incident_id
        self._reads = {read_key(item.capability, item.parameters): item
                       for item in reads if item.capability in SUPPORTED_CAPABILITIES}

    def _read(self, capability: str, asset_id: str, parameters: dict, incident_id: str | None):
        normalized = self.validate_parameters(capability, parameters)
        if asset_id != self.asset_id or incident_id not in (None, self.incident_id):
            raise InvalidReference("read outside the reasoning packet scope")
        read = self._reads.get(read_key(capability, normalized))
        if read is None:
            raise ValueError(f"{capability} read parameterization is not in the remote packet; "
                             "request evidence so the application can collect it")
        return self.parse_result(capability, read.result), None

    def collect(self, capability: str, asset_id: str, parameters: dict,
                *, incident_id: str | None = None) -> CapabilityResult:
        return self._read(capability, asset_id, parameters, incident_id)[0]

    def collect_with_dependencies(self, *args, **kwargs):
        raise ValueError("source dependency manifests are not available in a remote packet")

    def expected_dependencies(self, *args, **kwargs):
        raise ValueError("source dependency manifests are not available in a remote packet")


class PacketResourceCapabilities:
    """The three read-only resource observations, served from the packet."""

    def __init__(self, reads: tuple[PacketRead, ...], *, asset_id: str):
        self.asset_id = asset_id
        self._reads = {read_key(item.capability, item.parameters): item
                       for item in reads if item.capability in RESOURCE_TOOL_NAMES}

    def _serve(self, name: str, asset_id: str, limit: int):
        limit = ResourceQuery(limit=limit).limit
        if asset_id != self.asset_id:
            raise InvalidReference("resource read outside the reasoning packet scope")
        read = self._reads.get(read_key(name, {"limit": limit}))
        if read is None:
            raise ValueError(f"{name} parameterization is not in the remote packet")
        return RESOURCE_RESULTS[name].model_validate(read.result)

    def check_part_availability(self, asset_id: str, *, limit: int = 20) -> InventoryAvailability:
        return self._serve("check_part_availability", asset_id, limit)

    def inspect_available_technicians(self, asset_id: str, *, limit: int = 20) -> WorkforceAvailability:
        return self._serve("inspect_available_technicians", asset_id, limit)

    def inspect_maintenance_windows(self, asset_id: str, *, limit: int = 20) -> MaintenanceWindows:
        return self._serve("inspect_maintenance_windows", asset_id, limit)


class PacketEvidenceAccess:
    """Duck-typed ``EvidenceService`` stand-in for a reasoning runtime.

    Reads come from the packet; every write request is deferred to the application.
    It cannot mint IDs, persist evidence, or see anything outside this run.
    """

    def __init__(self, request: ReasoningRequest):
        self.request = request
        self.repository = SnapshotRepository(request.incident, request.context)
        self.capabilities = PacketCapabilities(request.reads, asset_id=request.asset_id,
                                               incident_id=request.incident_id)
        self._resources = PacketResourceCapabilities(request.reads, asset_id=request.asset_id)

    def same_store(self) -> bool:
        return True

    def resource_reads(self) -> PacketResourceCapabilities:
        return self._resources

    def request_and_collect(self, incident_id: str, *, requested_by: str, equipment_ids: tuple[str, ...],
                            question: str, capability: str,
                            required_for: Literal["diagnosis", "intervention", "outcome"],
                            parameters: dict | None = None, supersedes_evidence_id: str | None = None):
        if incident_id != self.request.incident_id or tuple(equipment_ids) != (self.request.asset_id,):
            raise InvalidReference("evidence request outside the reasoning packet scope")
        if not str(question).strip():
            raise ValueError("evidence question must not be blank")
        if required_for not in ("diagnosis", "intervention"):
            raise ValueError("reasoning runs may only name diagnosis or intervention evidence needs")
        if supersedes_evidence_id is not None:
            raise ValueError("a reasoning run cannot supersede durable evidence")
        # Unsupported capabilities fail here (UnsupportedEvidenceCapability), exactly
        # as the durable service would; only supportable needs are deferred.
        normalized: dict[str, JsonValue] = self.capabilities.validate_parameters(capability, parameters or {})
        raise EvidenceDeferred(requested_by=requested_by, capability=capability, question=str(question).strip(),
                               parameters=normalized, required_for=required_for)
