"""Versioned contracts. Completed records are replaced by new artifacts, never edited.

Frozen models prevent field reassignment; JSON payloads are defensively serialized
at the repository boundary (Pydantic freezing alone does not freeze nested dicts).
LegacyAlert is deliberately separate from validated reliability artifacts.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

import json

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_serializer, model_validator

Identifier = Annotated[str, Field(min_length=1)]
Score = Annotated[float, Field(ge=0, le=1)]
Role = Literal["supervisor", "diagnostic", "engineering", "operations", "critic", "planner", "procurement"]
FRESHNESS_POLICY = "operon-freshness-1"
# Every domain names one exact local read implemented by ``freshness.SourceReads``.
SourceDomain = Literal["asset_registry", "health_score_latest", "sensor_inventory", "telemetry_latest",
                       "telemetry_window", "maintenance_history", "related_incidents"]


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
    current_diagnosis_id: str | None = None
    current_intervention_id: str | None = None
    mode: Literal["LIVE", "DETERMINISTIC", "MIXED"] = "DETERMINISTIC"
    artifact_ids: tuple[Identifier, ...] = ()
    signal_evidence_ids: tuple[Identifier, ...] = ()
    # Compatibility snapshots never imply accepted diagnoses or approved plans.
    legacy_alert_id: str | None = None


class Artifact(Record):
    incident_id: Identifier

    @model_serializer(mode="wrap")
    def preserve_pre_promotion_hashes(self, handler):
        value = handler(self)
        # Additive optional metadata must not alter hashes of pre-004/pre-13C artifacts.
        for field in ("source_state_hash", "validator_identity", "validation_policy_version", "binding_id",
                      "check_results", "risk_metadata", "promotion_id", "source_dependencies",
                      "source_dependency_manifest"):
            if field in value and value[field] in (None, {}):
                value.pop(field)
        return value


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


class SourceDependency(Contract):
    """One recomputable local source read that an evidence result depends on.

    ``domain`` selects the exact query (see ``freshness.SourceReads``); ``scope``
    and ``parameters`` are the exact bound values (asset, sensor, window bounds,
    limits); ``fingerprint`` is a deterministic hash of the rows that query returned.
    Recomputing the same read later and comparing fingerprints decides staleness.
    """
    domain: SourceDomain
    scope: dict[str, JsonValue]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    fingerprint: Identifier

    @property
    def identity(self) -> str:
        return json.dumps([self.domain, self.scope, self.parameters], sort_keys=True, separators=(",", ":"))

    def describe(self) -> str:
        bound = {**self.scope, **self.parameters}
        return self.domain + "[" + ",".join(f"{key}={bound[key]}" for key in sorted(bound)) + "]"


class SourceDependencyManifest(Contract):
    """Application-generated, inspectable freshness contract of one record.

    SOURCE_QUERY: the record reproduces from the listed local reads; it is stale
    only when one of those exact reads changes. IMMUTABLE_OBSERVATION: a dated
    observation (model signal, trusted confirmation) with no mutable local source;
    it never becomes false because sources advance. DERIVED: freshness flows
    entirely from ``derived_from_ids``. CLOSURE: the union frozen by a run snapshot.
    """
    policy_version: Literal["operon-freshness-1"] = FRESHNESS_POLICY
    basis: Literal["SOURCE_QUERY", "IMMUTABLE_OBSERVATION", "DERIVED", "CLOSURE"]
    dependencies: tuple[SourceDependency, ...] = ()

    @model_validator(mode="after")
    def consistent_basis(self):
        identities = [item.identity for item in self.dependencies]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate source dependency identity")
        if self.basis == "SOURCE_QUERY" and not self.dependencies:
            raise ValueError("source-query manifest requires at least one dependency")
        if self.basis in {"IMMUTABLE_OBSERVATION", "DERIVED"} and self.dependencies:
            raise ValueError(f"{self.basis} manifest cannot carry source dependencies")
        return self


class Evidence(Artifact):
    equipment_ids: tuple[Identifier, ...] = Field(min_length=1)
    kind: Literal["telemetry", "model_signal", "maintenance_history", "document",
                  "asset_relation", "operational_context", "resource_availability", "inspection", "outcome"]
    source_uri: Identifier
    source_locator: Identifier
    source_version: Identifier
    content_hash: Identifier
    # Missing evidence has no truthful observation timestamp. Collection time is
    # retained separately and must not be substituted for a nonexistent sample.
    observed_at: AwareDatetime | None
    retrieved_at: AwareDatetime
    quality: Literal["GOOD", "SUSPECT", "MISSING"]
    provenance: Literal["OBSERVED", "SIMULATED", "DERIVED"]
    summary: str
    payload: dict[str, JsonValue]
    source_capability: Identifier = "legacy.unspecified"
    source_system: Identifier = "legacy.unspecified"
    request_id: str | None = None
    collection_key: str | None = None
    derived_from_ids: tuple[Identifier, ...] = ()
    supersedes_id: str | None = None
    # Legacy (pre-13C) whole-store checkpoint. Retained as metadata only; it grants
    # no freshness and is never compared against current sources.
    source_state_hash: str | None = None
    # Step 13C dependency-scoped freshness. Absent on legacy records, which cannot
    # prove scoped freshness and must be collected again for a new promotion.
    source_dependencies: SourceDependencyManifest | None = None

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
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    request_key: str | None = None
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
    confidence: Score | None
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
    confidence: Score | None
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
    validator_identity: str | None = None
    validation_policy_version: str | None = None
    check_results: dict[str, bool] = Field(default_factory=dict)


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
    binding_id: str | None = None
    risk_metadata: dict[str, JsonValue] = Field(default_factory=dict)

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


class SupervisorRunSnapshot(Artifact):
    """Application-owned immutable input checkpoint; persisted before invocation."""
    asset_id: Identifier
    run_id: Identifier
    stage: Literal["DIAGNOSIS", "INTERVENTION_REVIEW"]
    input_revision: int = Field(ge=1)
    evidence_manifest: dict[str, Identifier]
    input_artifact_manifest: dict[str, Identifier]
    advisory_input_manifest: dict[str, Identifier] = Field(default_factory=dict)
    # Legacy (pre-13C) whole-store checkpoint; optional so historical snapshots load.
    source_state_hash: str | None = None
    # Exact dependency closure of the frozen evidence packet, application-generated
    # in start_run before any model reasoning. Legacy snapshots carry none.
    source_dependency_manifest: SourceDependencyManifest | None = None
    context_payload: dict[str, JsonValue]
    bounds: dict[str, JsonValue]
    runtime_identity: dict[str, JsonValue]
    version_identity: dict[str, Identifier]


class SupervisorReport(Artifact):
    snapshot_id: Identifier
    asset_id: Identifier
    run_id: Identifier
    result_payload: dict[str, JsonValue]
    result_hash: Identifier
    input_revision: int = Field(ge=1)
    completion_revision: int = Field(ge=1)
    checkpoint_revision: int = Field(ge=1)
    evidence_manifest: dict[str, Identifier]
    completion: Literal["MODEL_COMPLETED", "LIMIT_EXHAUSTED", "TIMEOUT", "MODEL_FAILED", "INVALID_OUTPUT", "CANCELLED"]
    stale_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_result_payload(self):
        # Runtime-only import: the domain module does not import agents at startup.
        # Stored JSON is always parsed as the explicit contract, never unpickled.
        from core.agents.contracts import SupervisorResult
        from .repository import content_hash
        result = SupervisorResult.model_validate(self.result_payload)
        if (result.incident_id, result.run_id, result.input_revision) != (
                self.incident_id, self.run_id, self.input_revision):
            raise ValueError("report result scope differs from wrapper")
        if result.termination_reason != self.completion:
            raise ValueError("report completion differs from result")
        if content_hash(self.result_payload) != self.result_hash:
            raise ValueError("report result hash mismatch")
        return self


class PromotionRecord(Artifact):
    run_id: Identifier
    stage: Literal["diagnosis", "intervention"]
    source_report_id: Identifier
    source_report_hash: Identifier
    validation_policy_version: Identifier
    input_revision: int = Field(ge=1)
    output_revision: int = Field(ge=1)
    target_id: Identifier
    target_hash: Identifier
    verdict_id: Identifier
    advisory_artifact_mapping: dict[str, Identifier]
    evidence_manifest: dict[str, Identifier]
    idempotency_key: Identifier
    request_hash: Identifier
    source_diagnosis_promotion_id: str | None = None
    reviewed_draft_id: str | None = None
    reviewed_content_hash: str | None = None


class PerformedCheck(Contract):
    check: Identifier
    result: Identifier
    passed: Literal[True]


class TrustedTechnicalConfirmation(Contract):
    incident_id: Identifier
    asset_id: Identifier
    confirmed_mechanism: Identifier
    failure_mode_code: str | None = None
    supporting_evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    performed_checks: tuple[PerformedCheck, ...] = Field(min_length=1)
    observed_at: AwareDatetime
    source: Identifier
    actor_id: Identifier
    provenance: Literal["OBSERVED", "SIMULATED"]


class WorkPackagePart(Contract):
    part_id: Identifier
    quantity: int = Field(strict=True, gt=0)


class ConfirmedInventory(Contract):
    part_id: Identifier
    part_number: Identifier
    on_hand_quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0)
    required_quantity: int = Field(gt=0)


class ResourceConfirmation(Contract):
    """Trusted dated attestation; roster absence of bookings cannot create this."""
    incident_id: Identifier
    asset_id: Identifier
    technician_id: Identifier
    qualification: Identifier
    qualification_valid_until: AwareDatetime
    available_start: AwareDatetime
    available_end: AwareDatetime
    window_start: AwareDatetime
    window_end: AwareDatetime
    window_confirmed: Literal[True]
    parts: tuple[WorkPackagePart, ...] = Field(min_length=1)
    observed_at: AwareDatetime
    source: Identifier
    actor_id: Identifier
    provenance: Literal["OBSERVED", "SIMULATED"]
    # Always recomputed from local records by trusted submission, never accepted
    # as caller-supplied proof. Retains quantities after operational rows change.
    inventory_snapshot: tuple[ConfirmedInventory, ...] = ()

    @model_validator(mode="after")
    def dated_scope(self):
        if not (self.available_start <= self.window_start < self.window_end <= self.available_end
                and self.qualification_valid_until >= self.window_end):
            raise ValueError("dated availability and qualification must cover confirmed window")
        if len({part.part_id for part in self.parts}) != len(self.parts):
            raise ValueError("duplicate parts")
        return self


class WorkPackageBinding(Artifact):
    """Trusted concrete inputs. Unknown executable/business fields have no defaults."""
    diagnosis_id: Identifier
    source_report_id: Identifier
    source_plan_key: Identifier
    asset_id: Identifier
    failure_mode_id: Identifier
    technician_id: Identifier
    parts: tuple[WorkPackagePart, ...] = Field(min_length=1)
    resource_confirmation_id: Identifier
    signal_evidence_id: Identifier
    window_start: AwareDatetime
    window_end: AwareDatetime
    duration_minutes: int = Field(strict=True, gt=0)
    work_instructions: tuple[Identifier, ...] = Field(min_length=1)
    technical_preconditions: tuple[Identifier, ...] = Field(min_length=1)
    verification_criteria: tuple[Identifier, ...] = Field(min_length=1)
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    estimated_cost: float = Field(strict=True, ge=0)
    estimated_downtime_minutes: int = Field(strict=True, ge=0)
    estimated_avoided_loss: float = Field(strict=True, ge=0)
    business_assumption_version: Identifier
    safety_review: Identifier
    safety_relevant: bool = Field(strict=True)
    reversible: bool = Field(strict=True)
    external_commitment: bool = Field(strict=True)

    @model_validator(mode="after")
    def binding_window(self):
        if (self.window_end - self.window_start).total_seconds() < self.duration_minutes * 60:
            raise ValueError("duration exceeds confirmed window")
        if self.estimated_downtime_minutes < self.duration_minutes:
            raise ValueError("downtime must cover maintenance duration")
        if len({part.part_id for part in self.parts}) != len(self.parts):
            raise ValueError("duplicate parts")
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
    # Step 13B lifecycle requirements bind the exact application promotion lineage.
    promotion_id: str | None = None


class ApprovalDecision(Artifact):
    requirement_id: Identifier
    intervention_id: Identifier
    intervention_hash: Identifier
    actor_id: Identifier
    actor_role: Identifier
    decision: Literal["APPROVE", "REJECT"]
    rationale: str
    context_revision: int = Field(default=1, ge=1)
    promotion_id: str | None = None


class ExecutionReceipt(Artifact):
    intervention_id: Identifier
    intervention_hash: Identifier = "legacy-unbound"
    step_id: Identifier = "legacy-step"
    capability: Identifier = "legacy-capability"
    idempotency_key: Identifier | None = None
    operation_key: Identifier
    adapter: Identifier
    executor: Identifier = "legacy-executor"
    request_hash: Identifier
    status: Literal["CLAIMED", "CONFIRMED", "FAILED", "UNKNOWN"]
    external_ids: dict[str, str] = Field(default_factory=dict)
    attempted_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    attempt: int = Field(default=1, ge=1)
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def fill_idempotency_key(self):
        if self.idempotency_key is None:
            object.__setattr__(self, "idempotency_key", self.operation_key)
        return self


class ExecutionClaim(Contract):
    idempotency_key: Identifier
    incident_id: Identifier
    intervention_id: Identifier
    intervention_hash: Identifier
    step_id: Identifier
    capability: Identifier
    request_hash: Identifier
    adapter: Identifier
    executor: Identifier
    state: Literal["IN_FLIGHT", "CONFIRMED", "FAILED", "UNKNOWN"]
    attempt: int = Field(ge=1)
    started_at: AwareDatetime
    updated_at: AwareDatetime
    error_message: str | None = None


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
    intervention_id: str | None = None
    approval_requirement_id: str | None = None
    execution_receipt_ids: tuple[Identifier, ...] = ()
    simulator_progress: float = Field(ge=0)
    simulator_tick: int = Field(ge=0)


class IncidentEvent(Contract):
    id: int = Field(ge=1)
    incident_id: Identifier
    created_at: AwareDatetime
    revision: int = Field(ge=1)
    event_type: Literal["INCIDENT_OPENED", "SIGNAL_RECORDED", "PHASE_CHANGED",
                        "ARTIFACT_ADDED", "INCIDENT_ESCALATED", "INCIDENT_CLOSED",
                        "INCIDENT_UPDATED", "APPROVAL_REQUESTED", "APPROVAL_RECORDED",
                        "EXECUTION_CLAIMED", "EXECUTION_RECORDED",
                        "EVIDENCE_REQUESTED", "EVIDENCE_COLLECTED",
                        "EVIDENCE_REQUEST_RESOLVED"]
    payload: dict[str, JsonValue]
