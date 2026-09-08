"""Application validation boundary; deliberately no promotion/persistence API.

Strands DiagnosticAssessment -> scope/citation validation -> future independent
Hypothesis / Diagnosis review and promotion. Passing these checks is not causal
validation, acceptance, approval, or permission to transition an incident.
"""
from __future__ import annotations

from core.agents.contracts import DiagnosticAssessment, DiagnosticContext
from .models import Evidence
from .repository import IncidentRepository, InvalidReference


def prepare_diagnostic_context(repository: IncidentRepository, incident_id: str, *,
                               asset_id: str, run_id: str,
                               evidence_ids: tuple[str, ...]) -> DiagnosticContext:
    incident = repository.fetch_incident(incident_id)
    if asset_id not in incident.equipment_ids:
        raise InvalidReference("diagnostic asset outside incident scope")
    if len(evidence_ids) > 20:
        raise ValueError("select at most 20 evidence records")
    evidence = tuple(repository.get_artifact(incident_id, key) for key in evidence_ids)
    if any(not isinstance(item, Evidence) for item in evidence):
        raise InvalidReference("diagnostic context requires Evidence records")
    return DiagnosticContext(incident_id=incident.id, asset_id=asset_id, run_id=run_id,
                             input_revision=incident.revision, evidence=evidence)


def validate_diagnostic_assessment(assessment: DiagnosticAssessment, *,
                                   incident_id: str,
                                   available_evidence_ids: set[str]) -> DiagnosticAssessment:
    """Pure checks over trusted input/returned citations. Never writes domain records."""
    validated = DiagnosticAssessment.model_validate(assessment)
    if validated.incident_id != incident_id:
        raise InvalidReference("assessment belongs to a different incident")
    if not set(validated.evidence_reviewed) <= available_evidence_ids:
        raise InvalidReference("assessment cites evidence not supplied or collected in this invocation")
    return validated
