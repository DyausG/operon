"""Application validation boundary; deliberately no promotion/persistence API.

Strands specialist advice -> scope/citation validation -> future independent
review and promotion. Passing these checks is not causal
validation, acceptance, approval, or permission to transition an incident.
"""
from __future__ import annotations

from typing import Literal

from core.agents.contracts import (
    AdvisoryInput, Assessment, CriticAssessment, DiagnosticAssessment, DiagnosticContext,
    EngineeringAssessment, MaintenancePlanAssessment, OperationsAssessment, SpecialistContext,
)
from .models import Diagnosis, Evidence, Intervention, ValidationVerdict
from .repository import IncidentRepository, InvalidReference, content_hash


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


def prepare_specialist_context(repository: IncidentRepository, incident_id: str, *,
                               asset_id: str, run_id: str, evidence_ids: tuple[str, ...],
                               artifact_ids: tuple[str, ...] = (),
                               advisory_inputs: tuple[AdvisoryInput, ...] = (),
                               evidence_purpose: Literal["diagnosis", "intervention"] = "diagnosis",
                               run_purpose: Literal["INVESTIGATION", "DIAGNOSIS", "INTERVENTION_REVIEW"] = "INVESTIGATION",
                               review_target_id: str | None = None, review_target_hash: str | None = None,
                               question: str = "Assess the supplied inputs within your specialist responsibility.") -> SpecialistContext:
    base = prepare_diagnostic_context(repository, incident_id, asset_id=asset_id,
                                      run_id=run_id, evidence_ids=evidence_ids)
    if len(artifact_ids) > 10 or len(advisory_inputs) > 5:
        raise ValueError("select at most 10 artifacts and 5 advisory inputs")
    artifacts = tuple(repository.get_artifact(incident_id, key) for key in artifact_ids)
    if any(not isinstance(item, (Diagnosis, Intervention, ValidationVerdict)) for item in artifacts):
        raise InvalidReference("specialist artifact context requires diagnosis, intervention, or verdict")
    context = SpecialistContext(**(base.model_dump() | {"question": question}),
                                lifecycle_state=repository.fetch_incident(incident_id).phase,
                                artifacts=artifacts, advisory_inputs=advisory_inputs,
                                evidence_purpose=evidence_purpose, run_purpose=run_purpose,
                                review_target_id=review_target_id, review_target_hash=review_target_hash)
    return validate_specialist_context(repository, context)


def validate_specialist_context(repository: IncidentRepository,
                               context: DiagnosticContext) -> DiagnosticContext:
    """Recheck even hand-built snapshots against durable records before model access."""
    cls = SpecialistContext if isinstance(context, SpecialistContext) else DiagnosticContext
    scope = cls.model_validate(context.model_dump())
    incident = repository.fetch_incident(scope.incident_id)
    if scope.asset_id not in incident.equipment_ids:
        raise InvalidReference("specialist asset outside incident scope")
    artifacts = scope.artifacts if isinstance(scope, SpecialistContext) else ()
    for item in (*scope.evidence, *artifacts):
        stored = repository.get_artifact(scope.incident_id, item.id)
        if stored != item:
            raise InvalidReference("context content differs from durable artifact")
        equipment = getattr(item, "equipment_ids", ())
        if equipment and scope.asset_id not in equipment:
            raise InvalidReference("context artifact outside selected asset")
        if isinstance(item, Intervention) and any(
                set(step.equipment_ids) - {scope.asset_id} for step in item.steps):
            raise InvalidReference("context intervention outside selected asset")
    if isinstance(scope, SpecialistContext):
        if scope.run_purpose == "INTERVENTION_REVIEW":
            target = next((item for item in scope.artifacts if item.id == scope.review_target_id), None)
            if (not isinstance(target, Intervention) or target.status != "DRAFT"
                    or content_hash(target.model_dump(mode="json")) != scope.review_target_hash):
                raise InvalidReference("exact draft review context requires the stored target and hash")
        for item in scope.advisory_inputs:
            if item.key in item.assessment.input_assessment_keys:
                raise InvalidReference("advisory input cannot cite itself")
            validate_specialist_assessment(repository, item.assessment, scope, set())
    return scope


def validate_specialist_assessment(repository: IncidentRepository, assessment: Assessment,
                                  scope: DiagnosticContext,
                                  collected_evidence_ids: set[str]) -> Assessment:
    """Schema and reference checks only: this returns advice and never promotes it."""
    validated = type(assessment).model_validate(assessment.model_dump())
    if validated.incident_id != scope.incident_id:
        raise InvalidReference("assessment belongs to a different incident")
    available = {item.id for item in scope.evidence} | collected_evidence_ids
    if not set(validated.evidence_reviewed) <= available:
        raise InvalidReference("assessment cites evidence not supplied or collected in this invocation")
    for key in validated.evidence_reviewed:
        evidence = repository.get_artifact(scope.incident_id, key)
        if not isinstance(evidence, Evidence) or scope.asset_id not in evidence.equipment_ids:
            raise InvalidReference("assessment evidence outside selected asset")
    artifacts = {item.id: item for item in scope.artifacts} if isinstance(scope, SpecialistContext) else {}
    advice = {item.key: item.assessment for item in scope.advisory_inputs} if isinstance(scope, SpecialistContext) else {}
    if not set(validated.input_assessment_keys) <= advice.keys():
        raise InvalidReference("assessment references an unsupplied advisory key")

    def require_artifact(key, cls):
        if key not in artifacts or not isinstance(artifacts[key], cls):
            raise InvalidReference("required artifact reference is absent or has the wrong type")
        if repository.get_artifact(scope.incident_id, key) != artifacts[key]:
            raise InvalidReference("artifact reference differs from durable record")

    if validated.reviewed_intervention_id is not None:
        require_artifact(validated.reviewed_intervention_id, Intervention)
        if content_hash(artifacts[validated.reviewed_intervention_id].model_dump(mode="json")) != validated.reviewed_intervention_hash:
            raise InvalidReference("review must bind the exact draft hash")
    elif validated.reviewed_intervention_hash is not None:
        raise InvalidReference("review hash requires a draft identity")

    if isinstance(validated, EngineeringAssessment):
        if validated.diagnosis_id:
            require_artifact(validated.diagnosis_id, Diagnosis)
        elif not any(isinstance(advice[key], DiagnosticAssessment) for key in validated.input_assessment_keys):
            raise InvalidReference("engineering requires a diagnosis or supplied diagnostic advisory input")
    elif isinstance(validated, OperationsAssessment):
        if validated.intervention_id:
            require_artifact(validated.intervention_id, Intervention)
        elif not validated.input_assessment_keys:
            raise InvalidReference("operations requires an intervention or supplied advisory input")
    elif isinstance(validated, CriticAssessment):
        if validated.subject_kind == "assessment":
            if validated.subject_id not in advice or validated.subject_id not in validated.input_assessment_keys:
                raise InvalidReference("critic subject requires a supplied advisory key and input reference")
        else:
            require_artifact(validated.subject_id, Diagnosis if validated.subject_kind == "diagnosis" else Intervention)
    elif isinstance(validated, MaintenancePlanAssessment):
        if not validated.validated_input_ids and not validated.input_assessment_keys:
            raise InvalidReference("planner requires referenced inputs")
        for key in validated.validated_input_ids:
            require_artifact(key, (Diagnosis, Intervention, ValidationVerdict))
        for step in validated.proposed_steps:
            if set(step.equipment_ids) - {scope.asset_id}:
                raise InvalidReference("plan step equipment outside selected asset")
    return validated
