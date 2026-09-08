"""Deterministic baseline evidence collection, not a diagnostic agent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import models as m
from .evidence import EvidenceCollection, EvidenceService
from .repository import IncidentRepository, new_id, utcnow


class InvestigationStateError(ValueError):
    pass


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    incident: m.Incident
    evidence_ids: tuple[str, ...]
    evidence_request_ids: tuple[str, ...]
    unavailable_capabilities: tuple[str, ...]
    action_id: str


class DeterministicInvestigator:
    """Collect source records while leaving all causal conclusions unresolved."""

    def __init__(self, repository: IncidentRepository,
                 evidence_service: EvidenceService | None = None):
        self.repository = repository
        self.evidence_service = evidence_service or EvidenceService(repository)

    def investigate(self, incident_id: str, *, telemetry_sample_limit: int = 60) -> InvestigationResult:
        incident = self.repository.fetch_incident(incident_id)
        if incident.phase != m.IncidentPhase.OPEN:
            raise InvestigationStateError(
                f"baseline investigation requires OPEN incident, found {incident.phase.value}"
            )
        incident = self.repository.transition(
            incident.id, m.IncidentPhase.INVESTIGATING,
            expected_revision=incident.revision,
            reason="deterministic baseline evidence collection started",
        )
        asset_id = incident.equipment_ids[0]
        specifications = (
            ("get_asset_context", "Collect persisted asset and sensor context.", {}),
            ("get_telemetry_window", "Collect the bounded recent telemetry window.",
             {"sample_limit": telemetry_sample_limit}),
            ("get_maintenance_history", "Collect persisted maintenance history.", {"limit": 20}),
            ("get_related_incidents", "Collect other persisted incidents for this asset.", {"limit": 20}),
            ("get_operating_context", "Collect the persisted operating context.", {}),
        )
        collections: list[EvidenceCollection] = []
        for capability, question, parameters in specifications:
            collections.append(self.evidence_service.request_and_collect(
                incident.id, requested_by="supervisor", equipment_ids=(asset_id,),
                question=question, capability=capability, required_for="diagnosis",
                parameters=parameters,
            ))

        evidence_ids = tuple(dict.fromkeys((
            *incident.signal_evidence_ids,
            *(collection.evidence.id for collection in collections),
        )))
        unavailable = tuple(collection.request.capability for collection in collections
                            if collection.request.status == "UNAVAILABLE")
        incident = self.repository.fetch_incident(incident.id)
        action = m.AgentAction(
            id=new_id(), incident_id=incident.id, created_at=utcnow(),
            run_id=f"deterministic-baseline:{incident.id}", actor="operon.investigation",
            kind="REPORT", input_revision=incident.revision,
            input_artifact_ids=incident.signal_evidence_ids,
            output_artifact_ids=evidence_ids,
            status="SUCCEEDED", mode="DETERMINISTIC", model_id=None,
            prompt_version=None, tool_name="collect_baseline_evidence",
            summary=(f"Collected {len(collections)} bounded evidence artifacts; "
                     f"{len(unavailable)} capabilities reported unavailable."),
            error_code=None, completed_at=utcnow(),
        )
        incident = self.repository.add_artifact(action, expected_revision=incident.revision)
        return InvestigationResult(
            incident=incident, evidence_ids=evidence_ids,
            evidence_request_ids=tuple(collection.request.id for collection in collections),
            unavailable_capabilities=unavailable, action_id=action.id,
        )
