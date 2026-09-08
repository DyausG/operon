"""Versioned contracts. Completed records are replaced by new artifacts, never edited.

Frozen models prevent field reassignment; JSON payloads are defensively serialized
at the repository boundary (Pydantic freezing alone does not freeze nested dicts).
LegacyAlert is deliberately separate from validated reliability artifacts.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

Identifier = Annotated[str, Field(min_length=1)]
Score = Annotated[float, Field(ge=0, le=1)]
Role = Literal["supervisor", "diagnostic", "engineering", "operations", "critic", "planner", "procurement"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1


class Record(Contract):
    id: Identifier
    created_at: AwareDatetime


class IncidentPhase(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    DIAGNOSIS_VALIDATED = "DIAGNOSIS_VALIDATED"
    PLANNING = "PLANNING"
    INTERVENTION_VALIDATED = "INTERVENTION_VALIDATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    CANCELLED = "CANCELLED"


class Incident(Record):
    equipment_ids: tuple[Identifier, ...] = Field(min_length=1)
    admission_key: Identifier
    revision: int = Field(default=1, ge=1)
    updated_at: AwareDatetime
    phase: IncidentPhase = IncidentPhase.OPEN
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    triage_score: float = Field(default=0, ge=0)
    demo_run_id: str | None = None
    active_run_id: str | None = None
    mode: Literal["LIVE", "DETERMINISTIC", "MIXED"] = "DETERMINISTIC"
    artifact_ids: tuple[Identifier, ...] = ()
    signal_evidence_ids: tuple[Identifier, ...] = ()
    # Compatibility snapshots never imply accepted diagnoses or approved plans.
    legacy_alert_id: str | None = None


class Artifact(Record):
    incident_id: Identifier


class Attribution(Contract):
    feature: Identifier
    label: str
    value: float
    contribution: float


class ModelSignal(Record):
    """Classifier output, not a causal diagnosis, calibrated forecast, or RUL."""
    equipment_id: Identifier
    observed_at: AwareDatetime
    risk_score: Score
    health_score: Score
    candidate_failure_mode: str
    mode_distribution: dict[str, Score] = Field(default_factory=dict)
    attribution: tuple[Attribution, ...] = ()
    features: dict[str, float]
    model_source: Identifier
    model_version: Identifier
    input_source: Identifier
    input_provenance: Literal["OBSERVED", "SIMULATED"]


class Evidence(Artifact):
    equipment_ids: tuple[Identifier, ...] = Field(min_length=1)
    kind: Literal["telemetry", "model_signal", "maintenance_history", "document",
                  "asset_relation", "operational_context", "resource_availability", "inspection", "outcome"]
    source_uri: Identifier
    source_locator: Identifier
    source_version: Identifier
    content_hash: Identifier
    observed_at: AwareDatetime
    retrieved_at: AwareDatetime
    quality: Literal["GOOD", "SUSPECT", "MISSING"]
    provenance: Literal["OBSERVED", "SIMULATED", "DERIVED"]
    summary: str
    payload: dict[str, JsonValue]
    derived_from_ids: tuple[Identifier, ...] = ()
    supersedes_id: str | None = None

    @model_validator(mode="after")
    def validate_signal(self):
        if self.kind == "model_signal":
            signal = ModelSignal.model_validate(self.payload)
            if signal.equipment_id not in self.equipment_ids:
                raise ValueError("signal equipment is outside evidence scope")
            if signal.observed_at != self.observed_at or self.provenance != "DERIVED":
                raise ValueError("model evidence must preserve observation time and derived provenance")
        return self


class EvidenceRequest(Artifact):
    requested_by: Role
    equipment_ids: tuple[Identifier, ...] = Field(min_length=1)
    question: str
    capability: Identifier
    required_for: Literal["diagnosis", "intervention", "outcome"]
    status: Literal["OPEN", "SATISFIED", "UNAVAILABLE"] = "OPEN"
    resolved_by_evidence_ids: tuple[Identifier, ...] = ()
    supersedes_id: str | None = None


class Hypothesis(Artifact):
    equipment_ids: tuple[Identifier, ...] = Field(min_length=1)
    mechanism: str
    failure_mode_code: str | None = None
    status: Literal["OPEN", "SUPPORTED", "REFUTED", "UNRESOLVED"] = "OPEN"
    supporting_evidence_ids: tuple[Identifier, ...] = ()
    contradicting_evidence_ids: tuple[Identifier, ...] = ()
    confidence: Score
    confidence_basis: str
    calibrated: Literal[False] = False
    falsification_tests: tuple[str, ...]
    evidence_request_ids: tuple[Identifier, ...] = ()
    supersedes_id: str | None = None


class Diagnosis(Artifact):
    equipment_ids: tuple[Identifier, ...] = Field(min_length=1)
    hypothesis_ids: tuple[Identifier, ...] = Field(min_length=1)
    conclusion: str
    failure_mode_code: str | None = None
    evidence_ids: tuple[Identifier, ...]
    alternative_hypothesis_ids: tuple[Identifier, ...] = ()
    unresolved_assumptions: tuple[str, ...] = ()
    confidence: Score
    status: Literal["CANDIDATE", "ACCEPTED", "SUPERSEDED"] = "CANDIDATE"
    supersedes_id: str | None = None


class ValidationVerdict(Artifact):
    target_kind: Literal["diagnosis", "intervention"]
    target_id: Identifier
    target_hash: Identifier
    input_revision: int = Field(ge=1)
    decision: Literal["ACCEPT", "REJECT", "NEEDS_EVIDENCE"]
    challenges: tuple[str, ...] = ()
    falsification_attempts: tuple[str, ...] = ()
    evidence_ids: tuple[Identifier, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    evidence_request_ids: tuple[Identifier, ...] = ()
    validator_run_id: Identifier


class InterventionStep(Record):
    capability: Literal["inspect", "create_work_package", "notify", "verify_recovery",
                        "propose_procurement", "raise_quality_case"]
    equipment_ids: tuple[Identifier, ...] = Field(min_length=1)
    parameters: dict[str, JsonValue]
    depends_on: tuple[Identifier, ...] = ()
    preconditions: tuple[str, ...] = ()
    verification_criteria: tuple[str, ...] = ()


class Intervention(Artifact):
    diagnosis_id: Identifier
    revision: int = Field(ge=1)
    steps: tuple[InterventionStep, ...] = Field(min_length=1)
    evidence_ids: tuple[Identifier, ...] = ()
    risk: Literal["LOW", "MEDIUM", "HIGH", "PROHIBITED"]
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    estimated_cost: float = Field(ge=0)
    estimated_downtime_minutes: int = Field(ge=0)
    estimated_avoided_loss: float = Field(ge=0)
    business_assumption_version: Identifier
    status: Literal["DRAFT", "VALIDATED", "AWAITING_APPROVAL", "READY", "EXECUTING",
                    "DISPATCHED", "REJECTED", "SUPERSEDED"] = "DRAFT"
    supersedes_id: str | None = None

    @model_validator(mode="after")
    def validate_order(self):
        seen = set()
        for step in self.steps:
            if step.id in seen or not set(step.depends_on) <= seen:
                raise ValueError("steps must have unique IDs and depend only on preceding steps")
            seen.add(step.id)
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("both window boundaries are required")
        if self.window_start and self.window_end <= self.window_start:
            raise ValueError("window end must follow start")
        return self


class AgentAction(Artifact):
    run_id: Identifier
    actor: Identifier
    kind: Literal["HANDOFF", "TOOL_CALL", "REPORT", "TRANSITION", "APPROVAL", "EXECUTION", "FALLBACK", "ERROR"]
    input_revision: int = Field(ge=1)
    input_artifact_ids: tuple[Identifier, ...] = ()
    output_artifact_ids: tuple[Identifier, ...] = ()
    status: Literal["STARTED", "SUCCEEDED", "FAILED", "CANCELLED"]
    mode: Literal["LIVE", "DETERMINISTIC", "SYSTEM"]
    model_id: str | None = None
    prompt_version: str | None = None
    tool_name: str | None = None
    summary: str
    error_code: str | None = None
    completed_at: AwareDatetime | None = None
    supersedes_id: str | None = None


class ApprovalRequirement(Artifact):
    intervention_id: Identifier
    intervention_hash: Identifier
    policy_version: Identifier
    mode: Literal["AUTOMATIC", "HUMAN", "PROHIBITED"]
    required_roles: tuple[str, ...] = ()
    minimum_distinct_approvers: int = Field(ge=0)
    conditions: tuple[str, ...] = ()
    expires_at: AwareDatetime | None = None
    status: Literal["PENDING", "SATISFIED", "REJECTED", "EXPIRED", "INVALIDATED"] = "PENDING"
    supersedes_id: str | None = None


class ApprovalDecision(Artifact):
    requirement_id: Identifier
    intervention_id: Identifier
    intervention_hash: Identifier
    actor_id: Identifier
    actor_role: Identifier
    decision: Literal["APPROVE", "REJECT"]
    rationale: str


class ExecutionReceipt(Artifact):
    intervention_id: Identifier
    operation_key: Identifier
    adapter: Identifier
    request_hash: Identifier
    status: Literal["CLAIMED", "CONFIRMED", "FAILED", "UNKNOWN"]
    external_ids: dict[str, str] = Field(default_factory=dict)


class Outcome(Artifact):
    intervention_id: str | None = None
    execution_receipt_ids: tuple[Identifier, ...] = ()
    result: Literal["RECOVERED", "NO_IMPROVEMENT", "FAILED", "NO_INTERVENTION", "INCONCLUSIVE"]
    basis: Literal["OBSERVED", "SIMULATED"]
    verification_evidence_ids: tuple[Identifier, ...]
    observation_start: AwareDatetime
    observation_end: AwareDatetime
    before_metrics: dict[str, float] = Field(default_factory=dict)
    after_metrics: dict[str, float] = Field(default_factory=dict)
    estimated_avoided_loss: float | None = None
    measured_cost: float | None = None
    diagnosis_confirmed: bool | None = None
    lesson: str
    supersedes_id: str | None = None

    @model_validator(mode="after")
    def validate_window(self):
        if self.observation_end < self.observation_start:
            raise ValueError("observation end precedes start")
        return self


class LegacyAlert(Artifact):
    """Temporary UI checkpoint; proposal/result retain the existing API shapes.

    APPROVED/PREVENTED here carry only the old demo semantics. They are neither
    ApprovalDecision nor ExecutionReceipt nor verified Outcome records.
    """
    equipment_id: Identifier
    equipment_name: str | None
    equipment_class: str
    criticality: str
    failure_prob: Score
    predicted_mode: str | None
    predicted_mode_label: str | None
    status: Literal["ANALYZING", "PENDING_APPROVAL", "APPROVED", "REJECTED", "FAILED"]
    created_tick: int = Field(ge=0)
    triage_rank: int | None = None
    triage_score: float
    proposal: dict[str, JsonValue] | None = None
    result: dict[str, JsonValue] | None = None
    simulator_progress: float = Field(ge=0)
    simulator_tick: int = Field(ge=0)


class IncidentEvent(Contract):
    id: int = Field(ge=1)
    incident_id: Identifier
    created_at: AwareDatetime
    revision: int = Field(ge=1)
    event_type: Literal["INCIDENT_OPENED", "SIGNAL_RECORDED", "PHASE_CHANGED",
                        "ARTIFACT_ADDED", "INCIDENT_ESCALATED", "INCIDENT_CLOSED",
                        "INCIDENT_UPDATED", "APPROVAL_RECORDED", "EXECUTION_RECORDED"]
    payload: dict[str, JsonValue]
