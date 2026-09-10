"""Bounded advisory reports, deliberately outside the domain Artifact hierarchy.

No report grants approval, accepts a diagnosis, or constitutes an executable command.
IDs reference durable application records; hypothesis keys are report-local labels.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from core.reliability.models import Diagnosis, Evidence, IncidentPhase, Intervention, Score, ValidationVerdict

Reference = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Text = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
References = Annotated[tuple[Reference, ...], Field(max_length=64)]
Observations = Annotated[tuple[Text, ...], Field(max_length=20)]


class AdvisoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False,
                              revalidate_instances="always")
    schema_version: Literal[1] = 1


class EvidenceNeed(AdvisoryContract):
    """An unanswered question, not a persisted EvidenceRequest or a tool command."""
    capability: Reference
    question: Text


class HypothesisSuggestion(AdvisoryContract):
    key: Reference
    mechanism: Text
    supporting_evidence_ids: References = ()
    contradicting_evidence_ids: References = ()
    confidence: Annotated[Score, Field(strict=True)]
    falsification_tests: Observations


class SpecialistAssessment(AdvisoryContract):
    incident_id: Reference
    evidence_reviewed: References
    reasoning_summary: Text
    # Application-assigned packet keys, explicitly NOT durable artifact IDs.
    input_assessment_keys: References = ()
    uncertainties: Observations = ()
    reviewed_intervention_id: Reference | None = None
    reviewed_intervention_hash: Reference | None = None


class DiagnosticAssessment(SpecialistAssessment):
    competing_hypotheses: tuple[HypothesisSuggestion, ...] = Field(max_length=8)
    recommended_hypothesis: Reference | None
    confidence: Annotated[Score, Field(strict=True)]
    missing_evidence_requests: tuple[EvidenceNeed, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def check_hypotheses(self):
        keys = [item.key for item in self.competing_hypotheses]
        if len(keys) != len(set(keys)):
            raise ValueError("hypothesis keys must be unique within this report")
        if self.recommended_hypothesis is not None and self.recommended_hypothesis not in keys:
            raise ValueError("recommended hypothesis must reference a report-local hypothesis key")
        for item in self.competing_hypotheses:
            if not set((*item.supporting_evidence_ids, *item.contradicting_evidence_ids)) <= set(self.evidence_reviewed):
                raise ValueError("hypothesis citations must be in evidence_reviewed")
        return self


class EngineeringAssessment(SpecialistAssessment):
    diagnosis_id: Reference | None = None
    constraints_considered: Observations
    intervention_feasibility: Literal["FEASIBLE", "CONDITIONAL", "INFEASIBLE", "UNKNOWN", "UNSAFE"]
    missing_constraints: Observations = ()
    blockers: Observations
    safety_concerns: Observations
    recommended_intervention_elements: Observations

    @model_validator(mode="after")
    def feasibility_consistency(self):
        if self.intervention_feasibility == "FEASIBLE" and (self.missing_constraints or self.blockers):
            raise ValueError("unconditional feasibility conflicts with missing constraints or blockers")
        return self


class OperationsAssessment(SpecialistAssessment):
    intervention_id: Reference | None = None
    resource_feasibility: Literal["FEASIBLE", "INFEASIBLE", "UNKNOWN"]
    inventory_observations: Observations
    workforce_observations: Observations
    scheduling_observations: Observations
    blockers: Observations
    operational_recommendations: Observations


class CriticAssessment(SpecialistAssessment):
    subject_id: Reference
    subject_kind: Literal["diagnosis", "intervention", "assessment"]
    evidence_gaps: Observations
    contradictions: Observations
    unsupported_claims: Observations
    recommendation: Literal["ACCEPT", "REJECT", "NEEDS_EVIDENCE"]
    requested_additional_evidence: tuple[EvidenceNeed, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def recommendation_consistency(self):
        if self.recommendation == "ACCEPT" and (
                self.evidence_gaps or self.contradictions or self.unsupported_claims or self.requested_additional_evidence):
            raise ValueError("advisory acceptance conflicts with unresolved objections")
        return self


class ProposedMaintenanceStep(AdvisoryContract):
    description: Text
    equipment_ids: References
    evidence_ids: References
    preconditions: Observations
    verification_criteria: Observations
    # Zero-based indices into proposed_steps; these are not executable step IDs.
    depends_on: tuple[Annotated[int, Field(strict=True, ge=0)], ...] = Field(default=(), max_length=20)


class MaintenancePlanAssessment(SpecialistAssessment):
    validated_input_ids: References
    proposed_steps: tuple[ProposedMaintenanceStep, ...] = Field(min_length=1, max_length=20)
    estimated_exposure: float | None = Field(ge=0, strict=True)
    exposure_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None
    exposure_assumptions: Observations
    reversible: Annotated[bool, Field(strict=True)] | None
    safety_relevant: Annotated[bool, Field(strict=True)] | None
    external_commitment: Annotated[bool, Field(strict=True)] | None
    approval_considerations: Observations
    unresolved_blockers: Observations = ()
    expected_operational_exposure: Observations = ()

    @model_validator(mode="after")
    def check_plan(self):
        for index, step in enumerate(self.proposed_steps):
            if any(dependency >= index for dependency in step.depends_on):
                raise ValueError("step dependencies must reference preceding steps")
            if not step.equipment_ids:
                raise ValueError("proposed steps require equipment references")
            if not set(step.evidence_ids) <= set(self.evidence_reviewed):
                raise ValueError("step citations must be in evidence_reviewed")
        if (self.estimated_exposure is None) != (self.exposure_currency is None):
            raise ValueError("exposure amount and currency must both be known or unknown")
        return self


class DiagnosticContext(AdvisoryContract):
    """Trusted application snapshot for one asset/run; never model-supplied authority."""
    incident_id: Reference
    asset_id: Reference
    run_id: Reference
    input_revision: int = Field(ge=1)
    question: Text = "Assess competing causal hypotheses and identify missing evidence."
    evidence: tuple[Evidence, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def bounded_scope(self):
        for item in self.evidence:
            if item.incident_id != self.incident_id or self.asset_id not in item.equipment_ids:
                raise ValueError("evidence must belong to the incident and selected asset")
        if len({item.id for item in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate evidence IDs")
        if len(self.model_dump_json().encode()) > 64_000:
            raise ValueError("diagnostic context exceeds 64000 bytes; select a smaller evidence packet")
        return self


Assessment = DiagnosticAssessment | EngineeringAssessment | OperationsAssessment | CriticAssessment | MaintenancePlanAssessment


class AdvisoryInput(AdvisoryContract):
    """One supplied report, without inventing a persisted assessment record."""
    key: Reference
    assessment: Assessment


class SpecialistContext(DiagnosticContext):
    """Disposable application snapshot; selected durable artifacts retain their IDs."""
    question: Text = "Assess the supplied inputs within your specialist responsibility."
    lifecycle_state: IncidentPhase
    evidence_purpose: Literal["diagnosis", "intervention"] = "diagnosis"
    run_purpose: Literal["INVESTIGATION", "DIAGNOSIS", "INTERVENTION_REVIEW"] = "INVESTIGATION"
    review_target_id: Reference | None = None
    review_target_hash: Reference | None = None
    artifacts: tuple[Diagnosis | Intervention | ValidationVerdict, ...] = Field(default=(), max_length=10)
    advisory_inputs: tuple[AdvisoryInput, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def input_scope(self):
        keys = [item.key for item in self.advisory_inputs]
        ids = [item.id for item in (*self.evidence, *self.artifacts)]
        if len(set(keys)) != len(keys) or len(set(ids)) != len(ids) or set(keys) & set(ids):
            raise ValueError("packet keys and durable IDs must be unique and disjoint")
        if any(item.incident_id != self.incident_id for item in self.artifacts):
            raise ValueError("artifact belongs to a different incident")
        if any(item.assessment.incident_id != self.incident_id for item in self.advisory_inputs):
            raise ValueError("advisory input belongs to a different incident")
        return self


SpecialistRole = Literal["diagnostic", "engineering", "operations", "critic", "planner"]
AdvisoryDisposition = Literal["ADVISORY_CONCLUSION", "UNRESOLVED", "NEEDS_EVIDENCE", "BLOCKED", "ESCALATED"]


class SupervisorBounds(AdvisoryContract):
    """Application settings, never model-selected tool arguments."""
    max_delegations: int = Field(default=10, strict=True, ge=1, le=12)
    max_iterations: int = Field(default=12, strict=True, ge=1, le=12)
    max_role_invocations: int = Field(default=3, strict=True, ge=1, le=4)
    max_evidence_requests: int = Field(default=3, strict=True, ge=0, le=10)
    max_tool_calls: int = Field(default=24, strict=True, ge=1, le=64)
    timeout_seconds: float = Field(default=240, gt=0, le=600)


class DelegationQuery(AdvisoryContract):
    question: Text
    input_assessment_keys: tuple[Reference, ...] = Field(default=(), max_length=5)


class EvidenceFollowup(AdvisoryContract):
    assessment_key: Reference
    need_index: int = Field(strict=True, ge=0, le=9)
    query_parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_parameters(self):
        if len(self.model_dump_json().encode()) > 4000:
            raise ValueError("evidence followup exceeds 4000 bytes")
        return self


class SupervisorDecision(AdvisoryContract):
    """Native model output. All references are checked against the actual run."""
    incident_id: Reference
    run_id: Reference
    disposition: AdvisoryDisposition
    reasoning_summary: Text
    evidence_used: References = ()
    candidate_diagnosis_key: Reference | None = None
    engineering_key: Reference | None = None
    operations_key: Reference | None = None
    critic_keys: References = ()
    maintenance_plan_key: Reference | None = None
    unresolved_evidence_needs: tuple[EvidenceNeed, ...] = Field(default=(), max_length=20)
    blockers: Observations = ()


class DelegationRecord(AdvisoryContract):
    key: Reference
    role: SpecialistRole
    question: Text
    input_revision: int = Field(ge=1)
    input_assessment_keys: References
    evidence_ids: References
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    error_code: Reference | None = None


class EvidenceRequestRecord(AdvisoryContract):
    requested_by: Literal["supervisor", "diagnostic", "critic"]
    capability: Reference
    question: Text
    status: Literal["COLLECTED", "UNAVAILABLE", "FAILED", "CANCELLED"]
    evidence_id: Reference | None = None
    request_id: Reference | None = None
    error_code: Reference | None = None


class SupervisorResult(AdvisoryContract):
    """Application-assembled advisory audit; never a promotable domain Artifact.

    Assessments retain full citations and uncertainty. Keys identify ephemeral
    packets, not durable Diagnosis/Intervention records. Counters are not model claims.
    """
    incident_id: Reference
    run_id: Reference
    input_revision: int = Field(ge=1)
    disposition: AdvisoryDisposition
    decision: SupervisorDecision | None
    assessments: tuple[AdvisoryInput, ...] = Field(max_length=17)
    delegations: tuple[DelegationRecord, ...] = Field(max_length=12)
    evidence_requests: tuple[EvidenceRequestRecord, ...] = Field(max_length=10)
    evidence_used: References
    candidate_diagnosis_key: Reference | None
    engineering_key: Reference | None
    operations_key: Reference | None
    critic_keys: References
    maintenance_plan_key: Reference | None
    unresolved_evidence_needs: tuple[EvidenceNeed, ...] = Field(max_length=256)
    # Union of bounded specialist observations; retain objections without truncation.
    blockers: tuple[Text, ...] = Field(max_length=2048)
    human_review_required: Literal[True] = True
    termination_reason: Literal["MODEL_COMPLETED", "LIMIT_EXHAUSTED", "TIMEOUT", "MODEL_FAILED", "INVALID_OUTPUT", "CANCELLED"]
    exhausted_limits: References
    tool_calls: int = Field(ge=0, le=64)
    bounds: SupervisorBounds
    invalid_output: bool = False
