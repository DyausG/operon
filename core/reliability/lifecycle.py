"""Durable incident lifecycle: promoted authority -> governance -> approval -> execution.

AGENTS REASON. THE APPLICATION OWNS AUTHORITY.
prediction != diagnosis != intervention != approval != execution != outcome

Every authoritative transition here is one BEGIN IMMEDIATE transaction that checks
its prerequisites and performs its state change together. Authority is never
inferred from the incident phase: each command revalidates PromotionService
lineage for the current promoted intervention and its diagnosis. Model reasoning
happens only through PromotionService.run_supervisor, outside any transaction.
External adapter calls happen between the execution-claim transaction and the
receipt transaction; receipts are recorded against the execution claim identity,
never against the pre-call incident revision.

Step 14: a CONFIRMED receipt only reaches OBSERVING. ``verify_outcome`` is the one
route to CLOSED: it binds the exact executed lineage, freezes an observation plan,
collects durable post-intervention evidence and applies the deterministic outcome
policy (core/reliability/outcome.py); the authoritative Outcome and the phase
change commit together. No receipt, phase, model or caller can close an incident.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from pydantic_core import to_jsonable_python

from core import config, db
from core.agents.contracts import CriticAssessment
from core.agents.contracts import SupervisorResult
from . import models as m
from .execution import (
    AMBIGUOUS_CLAIM_AFTER, TRUSTED_EXECUTOR, ExecutionAmbiguous, ExecutionAuthorization,
    ExecutionBusy, ExecutionFailed, ExecutionReport, GovernedExecutor, _AUTHORITY_SEAL, failure_status,
)
from .governance import CAPABILITY_POLICY, WorkPackageParameters, artifact_hash, validate_step_parameters
from .freshness import revalidate
from .investigation import (
    BASELINE_CAPABILITIES, PINNED_BOUNDARY, DeterministicInvestigator, InvestigationResult, baseline_parameters,
)
from .outcome import OutcomeVerification, OutcomeVerifier, observation_start as _observation_start
from .promotion import (
    CONFIRM_MECHANISM, HYPOTHESIS_REF_MISSING, POLICY_VERSION as PROMOTION_POLICY, PromotionRefused, PromotionService,
)
from .actors import ActorRefused, authorize
from .repository import (
    IncidentRepository, InvalidReference, StaleRevision, content_hash, manifest_authority, new_id, utcnow,
)
from .state import TERMINAL_PHASES, validate_transition

POLICY_VERSION = "operon-lifecycle-1"
BOUNDARY = "operon.application.lifecycle"
APPROVER_ROLE = "maintenance_approver"
APPROVAL_TTL = timedelta(hours=24)
# Fields a re-delivered completion callback legitimately regenerates: the artifact
# identity and the moments it was materialised. Every other receipt field (claim
# identity, attempt, status, adapter, executor, external_ids, error_code/message,
# attempted_at) is consequential content and defines semantic equality.
RECEIPT_REGENERATED_FIELDS = frozenset({"id", "created_at", "completed_at"})
# F1.2 work boundary. A claimed performed_at may run ahead of the server clock by at most
# this skew; the server-recorded report time, never the claim, bounds observation.
WORK_ELIGIBILITY_POLICY = "operon-work-eligibility-1"
PERFORMED_AT_SKEW = timedelta(seconds=60)
# Derived attention flags only (no automatic transition in F1.2).
WORK_ACK_GRACE = timedelta(minutes=30)
WORK_REPORT_GRACE = timedelta(hours=8)
VERIFICATION_STALL_AFTER = timedelta(minutes=2)


def work_eligibility(assignment: m.WorkAssignment, report: m.WorkReport) -> tuple[bool, tuple[str, ...]]:
    """``operon-work-eligibility-1`` over one immutable assignment and its report.

    Only content is judged here; that the report is the single report on the current
    assignment of an OBSERVING case's executed dispatch, acknowledged first, is enforced
    by the work commands and by ``LifecycleService._qualifying_work``. An eligible
    report may open outcome verification. It is never evidence that the plant recovered.
    """
    reasons: list[str] = []
    if report.result == "NOT_PERFORMED":
        reasons.append("NOT_PERFORMED")
    else:
        if report.asset_intervened is not True:
            # Administrative-only completion, or a pre-F1.2 report that never attested physical work.
            reasons.append("NO_PHYSICAL_INTERVENTION" if report.asset_intervened is False else "ATTESTATION_MISSING")
        if (report.performed_at is None or report.performed_at < assignment.created_at
                or report.performed_at > report.created_at + PERFORMED_AT_SKEW):
            reasons.append("PERFORMED_AT_OUT_OF_BOUNDS")
        total = len(assignment.instructions)
        completed = tuple(sorted(set(report.completed_instructions or ())))
        if any(not 0 <= index < total for index in completed):
            reasons.append("INVALID_INSTRUCTIONS")
        if report.result == "COMPLETED" and completed != tuple(range(total)):
            reasons.append("INCOMPLETE_COVERAGE")
        if report.result == "PARTIAL":
            if not total or not completed:
                reasons.append("NO_COMPLETED_INSTRUCTIONS")
            if not any(item.strip() for item in report.findings):
                reasons.append("REMAINING_WORK_NOT_STATED")
    return not reasons, tuple(reasons)


class LifecycleRefused(ValueError):
    """Prerequisite for an authoritative transition is not met; nothing was written."""
    def __init__(self, reason: str, *, disposition: str = "BLOCKED"):
        super().__init__(reason)
        self.disposition = disposition


class AuthorityRefused(LifecycleRefused):
    """Current pointers do not identify valid, current application promotion lineage."""


class GovernanceBlocked(PermissionError):
    def __init__(self, assessment: "GovernanceAssessment"):
        super().__init__("; ".join(assessment.blockers))
        self.assessment = assessment


class ApprovalRefused(LifecycleRefused):
    pass


class ExecutionRefused(PermissionError):
    pass


class ReconciliationRequired(RuntimeError):
    """A prior consequential action may have committed; no automatic replay."""


def _require(condition, reason, *, disposition="BLOCKED", error=LifecycleRefused):
    if not condition:
        if issubclass(error, LifecycleRefused):
            raise error(reason, disposition=disposition)
        raise error(reason)


def _identity(incident_id):
    return dict(id=new_id(), incident_id=incident_id, created_at=utcnow())


class GovernanceAssessment(BaseModel):
    """Deterministic application governance over one exact promoted intervention."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy_version: str = POLICY_VERSION
    disposition: Literal["BLOCKED", "REQUIRES_HUMAN_APPROVAL"]
    intervention_id: str
    intervention_hash: str
    promotion_id: str
    checks: dict[str, bool]
    blockers: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class ApprovalState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"]
    requirement_id: str
    decision_ids: tuple[str, ...] = ()


class Settlement(BaseModel):
    """Typed classification of one reasoning stage result (F1). Never authority by itself.

    ``category`` separates TECHNICAL failures (retried, then suspended for an explicit
    resume) from EVIDENCE failures (the case waits for evidence), GOVERNANCE exceptions
    (back to planning) and true ESCALATION. ``counted`` is False for retries that are not
    failures (inputs changed concurrently) and so do not spend the retry budget.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["PROMOTE", "NEEDS_EVIDENCE", "RETRY", "ESCALATED"]
    category: m.FailureCategory | None = None
    code: str
    reason: str
    counted: bool = True


class StageOutcome(BaseModel):
    """Result of one application-driven reasoning stage; never authority by itself."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal["DIAGNOSIS", "INTERVENTION_REVIEW"]
    disposition: Literal["PROMOTED", "NEEDS_EVIDENCE", "ESCALATED", "RETRY", "SUSPENDED", "APPROVAL_REQUESTED",
                         "GOVERNANCE_BLOCKED"]
    phase: m.IncidentPhase
    revision: int
    reason: str
    report_id: str | None = None
    promotion_id: str | None = None
    draft_id: str | None = None
    requirement_id: str | None = None
    category: m.FailureCategory | None = None
    code: str | None = None


class LifecycleStatus(BaseModel):
    """Durable-pointer reconstruction used for restart and projections."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    incident_id: str
    phase: m.IncidentPhase
    revision: int
    diagnosis_id: str | None
    intervention_id: str | None
    intervention_hash: str | None
    promotion_id: str | None
    authority_valid: bool
    authority_reason: str | None
    approval: ApprovalState | None
    claim_state: str | None
    claim_started_at: str | None
    receipt_ids: tuple[str, ...]
    reconciliation_required: bool
    # Step 14: the exact executed lineage (OBSERVING/CLOSED only) and durable outcome
    # pointers. ``authority_valid`` keeps its 13B meaning (approval/execution authority,
    # which new technical evidence legitimately invalidates); closure exists only
    # where outcome_result is VERIFIED_RECOVERY.
    execution_lineage_valid: bool = False
    execution_lineage_reason: str | None = None
    plan_id: str | None = None
    outcome_id: str | None = None
    outcome_result: str | None = None


@dataclass(frozen=True)
class _Claimed:
    incident: m.Incident
    intervention: m.Intervention
    step: m.InterventionStep
    claim: m.ExecutionClaim
    parameters: WorkPackageParameters
    adapter: object
    external: dict[str, str]


class LifecycleService:
    def __init__(self, repository: IncidentRepository):
        self.repository = repository
        self.promotion = PromotionService(repository)
        self.investigator = DeterministicInvestigator(repository)

    # ----------------------------------------------------------------- reads
    def _all(self, conn, incident_id, cls):
        return self.promotion._all(conn, incident_id, cls)

    def _decisions(self, conn, incident_id, requirement_id=None):
        rows = conn.execute("SELECT body_json FROM approval_decision WHERE incident_id=? ORDER BY created_at, decision_id",
                            (incident_id,)).fetchall()
        decisions = [m.ApprovalDecision.model_validate_json(row[0]) for row in rows]
        if requirement_id is not None:
            decisions = [item for item in decisions if item.requirement_id == requirement_id]
        return decisions

    def _receipts(self, conn, incident_id):
        return [m.ExecutionReceipt.model_validate_json(row[0]) for row in conn.execute(
            "SELECT body_json FROM execution_receipt WHERE incident_id=? ORDER BY created_at, receipt_id", (incident_id,))]

    def _claim_row(self, conn, key):
        row = conn.execute("SELECT * FROM execution_claim WHERE idempotency_key=?", (key,)).fetchone()
        return self.repository._claim_from_row(row) if row else None

    def _claims_for(self, conn, incident_id, intervention_id):
        return [self.repository._claim_from_row(row) for row in conn.execute(
            "SELECT * FROM execution_claim WHERE incident_id=? AND intervention_id=? ORDER BY started_at",
            (incident_id, intervention_id))]

    # ------------------------------------------------------------- authority
    def _authority(self, conn, incident):
        """Current promoted intervention with complete, current application lineage."""
        _require(incident.current_intervention_id, "incident has no current promoted intervention", error=AuthorityRefused)
        try:
            return self.promotion._lineage(conn, incident, incident.current_intervention_id, "intervention", current=True)
        except PromotionRefused as exc:
            raise AuthorityRefused(f"promotion lineage invalid: {exc}", disposition=exc.disposition) from exc
        except InvalidReference as exc:
            raise AuthorityRefused(f"promotion lineage invalid: {exc}") from exc

    def _governance(self, conn, incident, intervention, record) -> GovernanceAssessment:
        """Deterministic; consumes only the exact promoted artifact, its lineage and local rows."""
        checks: dict[str, bool] = {}
        blockers: list[str] = []

        def check(name, condition, reason):
            checks[name] = bool(condition)
            if not condition:
                blockers.append(reason)

        steps = intervention.steps
        rule = CAPABILITY_POLICY.get(steps[0].capability) if steps else None
        check("single_governed_step", len(steps) == 1 and steps[0].capability == "create_work_package"
              and rule is not None and rule.consequential and rule.executable_now and not steps[0].depends_on,
              "lifecycle execution supports exactly one governed create_work_package step")
        check("risk_permitted", intervention.risk != "PROHIBITED", "intervention risk is prohibited")
        metadata = intervention.risk_metadata or {}
        check("risk_metadata_bound", metadata.get("policy") == PROMOTION_POLICY and metadata.get("safety_relevant") is True
              and metadata.get("external_commitment") is True and metadata.get("reversible") is False,
              "risk metadata does not match the promoted work-package policy")
        parameters = None
        if checks["single_governed_step"]:
            try:
                parameters = validate_step_parameters(steps[0])
            except Exception as exc:  # deterministic schema failure is a blocker, never an approval
                parameters = None
                check("parameters_valid", False, f"work package parameters are invalid: {exc}")
            else:
                check("parameters_valid", isinstance(parameters, WorkPackageParameters)
                      and set(steps[0].equipment_ids) <= set(incident.equipment_ids)
                      and parameters.equipment_id == steps[0].equipment_ids[0],
                      "work package parameters do not match the promoted step scope")
        else:
            checks["parameters_valid"] = False
        now = utcnow()
        check("window_not_started", intervention.window_start is not None and now < intervention.window_start,
              "confirmed maintenance window has already started or expired")
        binding = None
        if intervention.binding_id:
            try:
                binding = self.promotion._get(conn, incident.id, intervention.binding_id, m.WorkPackageBinding)
            except (PromotionRefused, InvalidReference):
                binding = None
        check("binding_present", binding is not None and binding.diagnosis_id == intervention.diagnosis_id,
              "promoted intervention lacks its application binding")
        if binding is not None and parameters is not None:
            check("binding_matches_parameters", parameters.technician_id == binding.technician_id
                  and parameters.equipment_id == binding.asset_id and parameters.failure_mode_id == binding.failure_mode_id
                  and {part.part_id: part.qty for part in parameters.parts} == {part.part_id: part.quantity for part in binding.parts},
                  "work package parameters differ from the application binding")
            try:
                self.promotion._resource_rows(conn, binding.asset_id, binding.technician_id, binding.parts)
            except PromotionRefused as exc:
                check("resources_consistent", False, f"resources can no longer be established: {exc}")
            else:
                checks["resources_consistent"] = True
        else:
            checks["binding_matches_parameters"] = checks["resources_consistent"] = False
        rejections = [item for item in self._all(conn, incident.id, m.ValidationVerdict)
                      if item.target_id == intervention.id and (item.decision != "ACCEPT" or item.blocking_issues)]
        check("no_application_rejection", not rejections, "an application verdict rejects the current intervention")
        common = dict(intervention_id=intervention.id, intervention_hash=artifact_hash(intervention),
                      promotion_id=record.id, checks=checks)
        if blockers:
            return GovernanceAssessment(disposition="BLOCKED", blockers=tuple(dict.fromkeys(blockers)), **common)
        # Step 13B policy: every promoted work package is an external, safety-relevant,
        # irreversible commitment and therefore requires exact human authorization.
        return GovernanceAssessment(disposition="REQUIRES_HUMAN_APPROVAL", reasons=(
            "governed work package creates an external safety-relevant commitment",
            f"promotion lineage {record.id} validated under {PROMOTION_POLICY}"), **common)

    def _current_requirement(self, conn, incident, intervention):
        requirements = self._all(conn, incident.id, m.ApprovalRequirement)
        superseded = {item.supersedes_id for item in requirements if item.supersedes_id}
        matching = [item for item in requirements if item.id not in superseded
                    and item.policy_version == POLICY_VERSION and item.mode == "HUMAN"
                    and item.intervention_id == intervention.id and item.intervention_hash == artifact_hash(intervention)]
        return matching[-1] if matching else None

    def _approval_state(self, conn, incident, requirement) -> ApprovalState:
        decisions = [item for item in self._decisions(conn, incident.id, requirement.id)
                     if item.intervention_id == requirement.intervention_id
                     and item.intervention_hash == requirement.intervention_hash]
        ids = tuple(item.id for item in decisions)
        if any(item.decision == "REJECT" for item in decisions):
            return ApprovalState(state="REJECTED", requirement_id=requirement.id, decision_ids=ids)
        approvals = {item.actor_id: item for item in decisions if item.decision == "APPROVE"
                     and (not requirement.required_roles or item.actor_role in requirement.required_roles)
                     and (requirement.expires_at is None or item.created_at < requirement.expires_at)}
        if len(approvals) >= max(requirement.minimum_distinct_approvers, 1):
            return ApprovalState(state="APPROVED", requirement_id=requirement.id,
                                 decision_ids=tuple(item.id for item in approvals.values()))
        if requirement.expires_at is not None and requirement.expires_at <= utcnow():
            return ApprovalState(state="EXPIRED", requirement_id=requirement.id, decision_ids=ids)
        return ApprovalState(state="PENDING", requirement_id=requirement.id, decision_ids=ids)

    def _checkpoint(self, conn, incident, artifacts=(), *, phase=None, events=(), reason=BOUNDARY, **changes):
        """One revision for the whole command: artifacts, pointer changes, phase, events.

        CLOSED is accepted only together with the authoritative VERIFIED_RECOVERY
        Outcome that justifies it (Step 14); every other internal caller is refused.
        """
        if phase == m.IncidentPhase.CLOSED:
            _require(any(isinstance(item, m.Outcome) and item.result == "VERIFIED_RECOVERY" for item in artifacts),
                     "CLOSED requires the authoritative verified outcome in the same commit")
        for artifact in artifacts:
            self.repository._store_artifact(conn, incident, artifact, historical_input=True)
        if phase is not None and phase != incident.phase:
            validate_transition(incident.phase, phase)
            changes["phase"] = phase
        if artifacts:
            changes["artifact_ids"] = (*incident.artifact_ids, *(item.id for item in artifacts))
        updated = self.repository._update(conn, incident, **changes)
        for artifact in artifacts:
            self.repository._event(conn, updated, "ARTIFACT_ADDED", {
                "artifact_id": artifact.id, "kind": type(artifact).__name__, "boundary": BOUNDARY})
        for event_type, payload in events:
            self.repository._event(conn, updated, event_type, payload)
        if phase is not None and phase != incident.phase:
            self.repository._event(conn, updated, "PHASE_CHANGED", {
                "from": incident.phase.value, "to": phase.value, "reason": reason})
            if phase == m.IncidentPhase.ESCALATED:
                self.repository._event(conn, updated, "INCIDENT_ESCALATED", {"reason": reason})
            elif phase == m.IncidentPhase.CLOSED:
                self.repository._event(conn, updated, "INCIDENT_CLOSED", {
                    "reason": reason, "outcome_id": next(item.id for item in artifacts if isinstance(item, m.Outcome))})
        return updated

    # ------------------------------------------------- admission/investigation
    def admit(self, signal: m.ModelSignal, *, severity="HIGH", triage_score=0.0) -> tuple[m.Incident, bool]:
        """Atomic signal admission; repeated admission adopts the active incident."""
        return self.repository.admit_signal(signal, severity=severity, triage_score=triage_score)

    def investigate(self, incident_id: str) -> InvestigationResult:
        """Deterministic baseline evidence; OPEN -> INVESTIGATING. Never a diagnosis."""
        return self.investigator.investigate(incident_id)

    def refresh_baseline_evidence(self, incident_id: str, asset_id: str, evidence_service) -> tuple[str, ...]:
        """Re-request baseline reads whose dependency manifest no longer validates (INVESTIGATING only).

        Each baseline request is re-issued with its own stored parameters, including
        the application-pinned snapshot boundary, so EvidenceService reuses records
        whose exact source reads are unchanged and appends superseding ones only when
        a read they depend on changed. Unrelated telemetry, incidents, technicians or
        bookings therefore cause no refresh. Nothing here touches trusted
        confirmations, which must be resubmitted by their trusted actor.
        """
        from .evidence import SUPPORTED_CAPABILITIES
        incident = self.repository.fetch_incident(incident_id)
        _require(incident.phase in {m.IncidentPhase.INVESTIGATING, m.IncidentPhase.AWAITING_EVIDENCE},
                 "baseline refresh is only valid before diagnosis authority exists")
        artifacts = self.repository.list_artifacts(incident_id)
        requests = [a for a in artifacts if isinstance(a, m.EvidenceRequest)]
        evidence = {a.id: a for a in artifacts if isinstance(a, m.Evidence)}
        superseded = {item.supersedes_id for item in requests if item.supersedes_id}
        baseline = {(capability, question) for capability, question, _ in BASELINE_CAPABILITIES}
        collected_at = utcnow()
        refreshed = []
        # Every current durable read request is re-issued with its own identity, so a
        # stale resolution is superseded rather than silently left out of the packet.
        for item in requests:
            if item.id in superseded or item.status == "OPEN" or item.capability not in SUPPORTED_CAPABILITIES:
                continue
            if item.equipment_ids != (asset_id,):
                continue
            parameters = dict(item.parameters)
            usable = all(evidence[key].quality == "GOOD" for key in item.resolved_by_evidence_ids if key in evidence)
            if (item.capability == "get_telemetry_window" and (item.capability, item.question) in baseline
                    and item.requested_by == "supervisor" and not usable):
                # A pinned baseline window that found too few samples stays a truthful
                # historical record, but a later window may have them: pin a new
                # boundary instead of re-asking the identical sparse window. Context
                # snapshots are never re-pinned (operating context is PARTIAL by design).
                parameters.pop(PINNED_BOUNDARY[item.capability], None)
                parameters = baseline_parameters(item.capability, parameters, collected_at=collected_at)
            refreshed.append(evidence_service.request_and_collect(
                incident_id, requested_by=item.requested_by, equipment_ids=item.equipment_ids, question=item.question,
                capability=item.capability, required_for=item.required_for, parameters=parameters).evidence.id)
        seen = {item.capability for item in requests if item.id not in superseded and item.equipment_ids == (asset_id,)}
        for capability, question, parameters in BASELINE_CAPABILITIES:
            if capability not in seen:
                refreshed.append(evidence_service.request_and_collect(
                    incident_id, requested_by="supervisor", equipment_ids=(asset_id,), question=question,
                    capability=capability, required_for="diagnosis",
                    parameters=baseline_parameters(capability, parameters, collected_at=collected_at)).evidence.id)
        return tuple(dict.fromkeys(refreshed))

    def current_evidence_ids(self, incident_id: str, asset_id: str) -> tuple[str, ...]:
        """GOOD, current evidence whose dependency closure still validates, for a run packet.

        Freshness is decided per artifact by replaying its own source dependencies and
        those of its provenance parents. Legacy records carrying only the whole-store
        hash are excluded (except dated model signals) and get collected again by
        ``refresh_baseline_evidence``; trusted confirmations drop out only when their
        supporting evidence is superseded or its dependencies changed.
        """
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            evidence = {item.id: item for item in self._all(conn, incident_id, m.Evidence)}
            superseded = {item.supersedes_id for item in evidence.values() if item.supersedes_id}
            cache, verdicts = {}, {}

            def fresh(key, trail=()):
                if key in verdicts:
                    return verdicts[key]
                item = evidence.get(key)
                ok = (item is not None and key not in trail and key not in superseded
                      and item.content_hash == content_hash(item.payload))
                if ok:
                    manifest = item.source_dependencies
                    if manifest_authority(item) is not None:
                        ok = False
                    elif manifest is None:
                        ok = item.kind == "model_signal"
                    elif manifest.basis == "DERIVED":
                        ok = bool(item.derived_from_ids)
                    else:
                        ok = not revalidate(conn, manifest, cache=cache)
                if ok:
                    ok = all(fresh(parent, (*trail, key)) for parent in item.derived_from_ids)
                verdicts[key] = ok
                return ok

            return tuple(key for key, item in evidence.items()
                         if key not in superseded and asset_id in item.equipment_ids
                         and item.quality == "GOOD" and item.source_system != "legacy.unspecified"
                         and item.source_capability != "legacy.unspecified" and fresh(key))

    # ------------------------------------------------------- trusted evidence
    def submit_technical_confirmation(self, confirmation: m.TrustedTechnicalConfirmation, *, expected_revision: int):
        """Trusted application submission; AWAITING_EVIDENCE resumes INVESTIGATING."""
        evidence = self.promotion.submit_technical_confirmation(confirmation, expected_revision=expected_revision)
        incident = self.repository.fetch_incident(confirmation.incident_id)
        if incident.phase == m.IncidentPhase.AWAITING_EVIDENCE:
            incident = self.repository.transition(incident.id, m.IncidentPhase.INVESTIGATING,
                                                  expected_revision=incident.revision,
                                                  reason="trusted technical confirmation received")
        return evidence, incident

    def submit_resource_confirmation(self, confirmation: m.ResourceConfirmation, *, expected_revision: int):
        evidence = self.promotion.submit_resource_confirmation(confirmation, expected_revision=expected_revision)
        return evidence, self.repository.fetch_incident(confirmation.incident_id)

    # -------------------------------------------------------- reasoning stages
    def _settle(self, incident_id, report, stage) -> Settlement:
        """Classify a durable report deterministically into a typed Settlement (F1).

        Technical failures (provider, budget, schema, failed specialists, incomplete
        reviews) are retried and never escalate a case by themselves. Evidence failures
        park the case. Only an explicit advisory escalation or an UNSAFE engineering
        review is a true escalation.
        """
        from .orchestration import latest_assessments
        if report.stale_reasons:
            return Settlement(disposition="RETRY", category="TECHNICAL", code="STALE_INPUTS", counted=False,
                              reason="run inputs changed during reasoning: " + ", ".join(report.stale_reasons))
        result = SupervisorResult.model_validate(report.result_payload)
        if report.completion != "MODEL_COMPLETED" or result.exhausted_limits or result.invalid_output:
            failure = next((item for item in result.blockers if item.startswith("Model invocation failed")), None)
            code = ("INVALID_OUTPUT" if result.invalid_output else
                    "LIMIT_EXHAUSTED" if result.exhausted_limits else report.completion)
            return Settlement(disposition="RETRY", category="TECHNICAL", code=code,
                              reason=f"supervisor run terminated with {report.completion}" + (f": {failure}" if failure else ""))
        advice = {item.key: item for item in result.assessments}
        latest = latest_assessments(advice)
        # A genuinely unsafe exact intervention is a true escalation whatever else the run reported.
        if stage == "INTERVENTION_REVIEW" and "engineering" in latest and \
                advice[latest["engineering"]].assessment.intervention_feasibility == "UNSAFE":
            return Settlement(disposition="ESCALATED", category="ESCALATION", code="UNSAFE_INTERVENTION",
                              reason="engineering review judged the exact intervention unsafe")
        failed = [item for item in result.delegations if item.status != "SUCCEEDED"]
        failed_requests = [item for item in result.evidence_requests if item.status == "FAILED"]
        if result.disposition == "BLOCKED":
            model_declared = result.decision is not None and result.decision.disposition == "BLOCKED"
            if failed or failed_requests or not model_declared:
                detail = ", ".join(f"{item.role}:{item.error_code or item.status}" for item in failed) or "tool invocation"
                return Settlement(disposition="RETRY", category="TECHNICAL", code="SPECIALIST_FAILURE",
                                  reason=f"advisory run blocked by an invocation failure ({detail})")
            return Settlement(disposition="NEEDS_EVIDENCE", category="EVIDENCE", code="ADVISORY_BLOCKED",
                              reason="advisory run is blocked: " + "; ".join(result.blockers[:3]))
        if result.disposition == "ESCALATED":
            return Settlement(disposition="ESCALATED", category="ESCALATION", code="ADVISORY_ESCALATION",
                              reason="advisory run escalated: " + "; ".join(result.blockers[:3]))
        if result.disposition in {"UNRESOLVED", "NEEDS_EVIDENCE"} or result.unresolved_evidence_needs:
            if stage == "DIAGNOSIS":
                diagnostic = latest.get("diagnostic")
                incomplete = diagnostic is None or not any(
                    isinstance(item.assessment, CriticAssessment) and item.assessment.subject_id == diagnostic
                    for item in advice.values())
            else:
                incomplete = not {"engineering", "operations", "critic"} <= latest.keys()
            if incomplete and not result.unresolved_evidence_needs:
                return Settlement(disposition="RETRY", category="TECHNICAL", code="INCOMPLETE_REVIEW",
                                  reason="advisory run omitted a required specialist review")
            return Settlement(disposition="NEEDS_EVIDENCE", category="EVIDENCE", code="INSUFFICIENT_EVIDENCE",
                              reason=f"supervisor disposition {result.disposition}")
        return Settlement(disposition="PROMOTE", code="ADVISORY_CONCLUSION",
                          reason="advisory conclusion ready for application gates")

    def _refusal(self, incident_id, report, exc: PromotionRefused, stage) -> Settlement:
        """Classify an application gate refusal; a gate never escalates by itself (F1)."""
        if exc.disposition == "NEEDS_EVIDENCE":
            return Settlement(disposition="NEEDS_EVIDENCE", category="EVIDENCE", code="GATE_NEEDS_EVIDENCE", reason=str(exc))
        if self._refusal_is_stale(incident_id, report):
            return Settlement(disposition="RETRY", category="TECHNICAL", code="STALE_INPUTS", counted=False,
                              reason=f"promotion inputs changed: {exc}")
        code = exc.code or ("CONTRACT_VIOLATION" if exc.disposition == "CONTRACT" else "APPLICATION_GATE_REFUSED")
        return Settlement(disposition="RETRY", category="TECHNICAL", code=code,
                          reason=f"application {stage.lower().replace('_', ' ')} gate refused the advisory output: {exc}")

    def _refusal_is_stale(self, incident_id, report):
        """A BLOCKED refusal caused by concurrent change is retryable, not an escalation.

        Only a change to a dependency the run actually froze counts; a legacy snapshot
        without a dependency manifest is retried with a fresh run.
        """
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            incident = self.repository._fetch(conn, incident_id)
            snapshot = self.repository._artifact(conn, incident_id, report.snapshot_id)
            changed = (snapshot.source_dependency_manifest is None
                       or bool(revalidate(conn, snapshot.source_dependency_manifest)))
        return (incident.active_run_id != report.run_id or incident.revision != report.checkpoint_revision
                or changed)

    def _transition(self, incident_id, target, reason):
        incident = self.repository.fetch_incident(incident_id)
        try:
            return self.repository.transition(incident.id, target, expected_revision=incident.revision, reason=reason)
        except StaleRevision:
            return self.repository.fetch_incident(incident_id)

    def _outcome(self, incident_id, stage, disposition, reason, **extra):
        incident = self.repository.fetch_incident(incident_id)
        return StageOutcome(stage=stage, disposition=disposition, phase=incident.phase, revision=incident.revision,
                            reason=reason, **extra)

    def _technical_failure(self, incident_id, settlement: Settlement) -> bool:
        """Spend one attempt of the technical retry budget; suspend analysis when it is spent.

        Durable (incident state + event), so a restart cannot reset the budget. Returns
        True when analysis is now suspended. Suspension is not a phase and not an
        escalation: an explicit, audited ``resume`` re-enables automatic reasoning.
        """
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase in TERMINAL_PHASES:
                return False
            state = incident.analysis or m.AnalysisState()
            attempts, budget = state.attempts + 1, config.technical_retry_attempts()
            suspended = attempts >= budget
            analysis = m.AnalysisState(
                attempts=attempts, suspended=suspended,
                codes={**state.codes, settlement.code: state.codes.get(settlement.code, 0) + 1},
                last_category=settlement.category, last_code=settlement.code, last_reason=settlement.reason[:500],
                updated_at=utcnow())
            updated = self.repository._update(conn, incident, analysis=analysis)
            self.repository._event(conn, updated, "ANALYSIS_SUSPENDED" if suspended else "ANALYSIS_RETRY_SCHEDULED", {
                "category": settlement.category, "code": settlement.code, "reason": settlement.reason[:500],
                "attempt": attempts, "budget": budget, "phase": incident.phase.value})
            return suspended

    def _apply(self, incident_id, stage, settlement: Settlement, *, report=None, **extra) -> StageOutcome:
        """Apply a non-promoting Settlement through explicit, graph-valid writes only."""
        disposition = settlement.disposition
        if disposition == "NEEDS_EVIDENCE" and stage == "DIAGNOSIS":
            if report is not None:
                # Park and give the competing hypotheses durable identity in one commit, so a
                # human confirmation can name exactly which hypothesis it confirms.
                self.promotion.register_hypotheses(incident_id, report_id=report.id,
                                                   phase=m.IncidentPhase.AWAITING_EVIDENCE, reason=settlement.reason)
            else:
                self._transition(incident_id, m.IncidentPhase.AWAITING_EVIDENCE, settlement.reason)
        elif disposition == "ESCALATED":
            self._transition(incident_id, m.IncidentPhase.ESCALATED, settlement.reason)
        elif disposition == "RETRY" and settlement.counted and self._technical_failure(incident_id, settlement):
            disposition = "SUSPENDED"
        return self._outcome(incident_id, stage, disposition, settlement.reason, category=settlement.category,
                             code=settlement.code, report_id=report.id if report is not None else None, **extra)

    def _suspended(self, incident_id, stage, **extra) -> StageOutcome | None:
        incident = self.repository.fetch_incident(incident_id)
        if incident.analysis is not None and incident.analysis.suspended:
            return self._outcome(incident_id, stage, "SUSPENDED",
                                 "analysis is suspended after repeated technical failures; an explicit resume is required",
                                 category=incident.analysis.last_category, code=incident.analysis.last_code, **extra)
        return None

    async def diagnose(self, incident_id: str, *, asset_id: str, runtime, evidence_service,
                       specialist_runtime=None, bounds=None, confirmation_id: str | None = None) -> StageOutcome:
        """INVESTIGATING -> durable supervisor run -> application diagnosis gates.

        Only PromotionService.promote_diagnosis creates authority. Evidence failures park
        the incident in AWAITING_EVIDENCE with durable hypotheses; technical failures
        spend the retry budget and then suspend analysis; only true escalation escalates.
        """
        incident = self.repository.fetch_incident(incident_id)
        _require(incident.phase == m.IncidentPhase.INVESTIGATING, "diagnosis requires INVESTIGATING")
        suspended = self._suspended(incident_id, "DIAGNOSIS")
        if suspended is not None:
            return suspended
        self.refresh_baseline_evidence(incident_id, asset_id, evidence_service)
        incident = self.repository.fetch_incident(incident_id)
        evidence_ids = self.current_evidence_ids(incident_id, asset_id)
        # The structural hypothesis-link fallback is allowed only on the attempt that would
        # spend the technical budget, after at least one contract retry for the missing ID.
        state = incident.analysis
        allow_fallback = (state is not None and state.codes.get(HYPOTHESIS_REF_MISSING, 0) >= 1
                          and state.attempts + 1 >= config.technical_retry_attempts())
        try:
            report = await self.promotion.run_supervisor(
                incident_id, service=evidence_service, runtime=runtime, specialist_runtime=specialist_runtime,
                asset_id=asset_id, stage="DIAGNOSIS", expected_revision=incident.revision,
                evidence_ids=evidence_ids, bounds=bounds)
        except PromotionRefused as exc:
            return self._outcome(incident_id, "DIAGNOSIS", "RETRY" if exc.disposition != "NEEDS_EVIDENCE" else "NEEDS_EVIDENCE",
                                 f"run could not start: {exc}",
                                 category="TECHNICAL" if exc.disposition != "NEEDS_EVIDENCE" else "EVIDENCE",
                                 code="RUN_NOT_STARTED")
        settlement = self._settle(incident_id, report, "DIAGNOSIS")
        if settlement.disposition == "PROMOTE":
            if confirmation_id is None:
                confirmation_id = self._confirmation_for(incident_id, report)
            if confirmation_id is None:
                settlement = Settlement(disposition="NEEDS_EVIDENCE", category="EVIDENCE", code="CONFIRMATION_REQUIRED",
                                        reason="trusted technical confirmation has not been supplied")
            else:
                try:
                    promotion = self.promotion.promote_diagnosis(
                        incident_id, report_id=report.id, confirmation_id=confirmation_id,
                        expected_revision=report.checkpoint_revision, allow_link_fallback=allow_fallback)
                    return self._outcome(incident_id, "DIAGNOSIS", "PROMOTED", "application promoted the diagnosis",
                                         report_id=report.id, promotion_id=promotion.id)
                except PromotionRefused as exc:
                    settlement = self._refusal(incident_id, report, exc, "DIAGNOSIS")
        return self._apply(incident_id, "DIAGNOSIS", settlement, report=report)

    def _confirmation_for(self, incident_id, report) -> str | None:
        """The trusted confirmation in the run's packet for the recommended hypothesis, else the latest one."""
        confirmations = []
        for key in report.evidence_manifest:
            item = self.repository.get_artifact(incident_id, key)
            if getattr(item, "source_capability", None) == CONFIRM_MECHANISM:
                confirmations.append(item)
        if not confirmations:
            return None
        result = SupervisorResult.model_validate(report.result_payload)
        advice = {item.key: item.assessment for item in result.assessments}
        diagnostic = advice.get(result.candidate_diagnosis_key)
        selected = next((item for item in getattr(diagnostic, "competing_hypotheses", ())
                         if item.key == getattr(diagnostic, "recommended_hypothesis", None)), None)
        confirmations.sort(key=lambda item: (item.created_at, item.id))
        matching = [item for item in confirmations if selected is not None and selected.hypothesis_ref is not None
                    and item.payload.get("hypothesis_ref") == selected.hypothesis_ref]
        return (matching or confirmations)[-1].id

    async def plan(self, incident_id: str, *, runtime, evidence_service, expected_revision: int,
                   specialist_runtime=None, bounds=None, **binding_fields) -> StageOutcome:
        """Trusted binding -> DRAFT -> fresh exact-draft review -> promotion -> approval requirement."""
        draft = self.promotion.create_draft(incident_id, expected_revision=expected_revision, **binding_fields)
        return await self.review_draft(incident_id, draft_id=draft.id, runtime=runtime, evidence_service=evidence_service,
                                       specialist_runtime=specialist_runtime, bounds=bounds)

    async def review_draft(self, incident_id: str, *, draft_id: str, runtime, evidence_service,
                           specialist_runtime=None, bounds=None) -> StageOutcome:
        incident = self.repository.fetch_incident(incident_id)
        _require(incident.phase == m.IncidentPhase.PLANNING, "draft review requires PLANNING")
        draft = self.repository.get_artifact(incident_id, draft_id)
        _require(isinstance(draft, m.Intervention) and draft.status == "DRAFT", "review target must be a DRAFT intervention")
        suspended = self._suspended(incident_id, "INTERVENTION_REVIEW", draft_id=draft.id)
        if suspended is not None:
            return suspended
        try:
            report = await self.promotion.run_supervisor(
                incident_id, service=evidence_service, runtime=runtime, specialist_runtime=specialist_runtime,
                asset_id=draft.steps[0].equipment_ids[0], stage="INTERVENTION_REVIEW", expected_revision=incident.revision,
                evidence_ids=draft.evidence_ids, draft_id=draft.id, bounds=bounds)
        except PromotionRefused as exc:
            return self._outcome(incident_id, "INTERVENTION_REVIEW", "RETRY" if exc.disposition != "NEEDS_EVIDENCE" else "NEEDS_EVIDENCE",
                                 f"review could not start: {exc}", draft_id=draft.id,
                                 category="TECHNICAL" if exc.disposition != "NEEDS_EVIDENCE" else "EVIDENCE",
                                 code="RUN_NOT_STARTED")
        settlement = self._settle(incident_id, report, "INTERVENTION_REVIEW")
        promotion = None
        if settlement.disposition == "PROMOTE":
            try:
                promotion = self.promotion.promote_intervention(
                    incident_id, report_id=report.id, draft_id=draft.id, expected_revision=report.checkpoint_revision)
            except PromotionRefused as exc:
                settlement = self._refusal(incident_id, report, exc, "INTERVENTION_REVIEW")
        if promotion is None:
            # Evidence needs discovered at planning stay in PLANNING: a new trusted
            # binding/draft is required; no authority exists yet to invalidate.
            return self._apply(incident_id, "INTERVENTION_REVIEW", settlement, report=report, draft_id=draft.id)
        incident = self.repository.fetch_incident(incident_id)
        try:
            requirement = self.request_approval(incident_id, expected_revision=incident.revision)
        except GovernanceBlocked as exc:
            # A governance exception is not an escalation: the exact intervention cannot be
            # approved as promoted, so it is consumed and the case returns to planning.
            self._return_to_planning(incident_id, reason=f"governance blocked: {exc}",
                                     actor=m.ActorRef(kind="SYSTEM", id=BOUNDARY), command="governance_blocked")
            return self._outcome(incident_id, "INTERVENTION_REVIEW", "GOVERNANCE_BLOCKED", str(exc),
                                 report_id=report.id, promotion_id=promotion.id, draft_id=draft.id,
                                 category="GOVERNANCE", code="GOVERNANCE_BLOCKED")
        return self._outcome(incident_id, "INTERVENTION_REVIEW", "APPROVAL_REQUESTED", "human approval required",
                             report_id=report.id, promotion_id=promotion.id, draft_id=draft.id, requirement_id=requirement.id)

    # ---------------------------------------------------------------- approval
    def assess_governance(self, incident_id: str) -> GovernanceAssessment:
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            incident = self.repository._fetch(conn, incident_id)
            intervention, record = self._authority(conn, incident)
            return self._governance(conn, incident, intervention, record)

    def request_approval(self, incident_id: str, *, expected_revision: int) -> m.ApprovalRequirement:
        """Atomic: authority + governance -> ApprovalRequirement + AWAITING_APPROVAL.

        Governance blockers raise; they are never converted into a waivable request.
        """
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            self.repository._check(incident, expected_revision)
            return self._request_approval_in(conn, incident)

    def _material_uncertainties(self, conn, incident, record) -> tuple[m.RecordedUncertainty, ...]:
        """MATERIAL uncertainty recorded by the intervention and diagnosis promotions (F1)."""
        verdicts = [self.promotion._get(conn, incident.id, record.verdict_id, m.ValidationVerdict)]
        if record.source_diagnosis_promotion_id:
            diagnosis_record = self.promotion._get(conn, incident.id, record.source_diagnosis_promotion_id, m.PromotionRecord)
            verdicts.insert(0, self.promotion._get(conn, incident.id, diagnosis_record.verdict_id, m.ValidationVerdict))
        return tuple(item for verdict in verdicts for item in (verdict.uncertainties or ()) if item.severity == "MATERIAL")

    def _request_approval_in(self, conn, incident, *, events=()) -> m.ApprovalRequirement:
        _require(incident.phase in {m.IncidentPhase.INTERVENTION_VALIDATED, m.IncidentPhase.AWAITING_APPROVAL},
                 f"approval request requires INTERVENTION_VALIDATED, found {incident.phase.value}")
        intervention, record = self._authority(conn, incident)
        governance = self._governance(conn, incident, intervention, record)
        if governance.disposition == "BLOCKED":
            raise GovernanceBlocked(governance)
        existing = self._current_requirement(conn, incident, intervention)
        if existing is not None and incident.phase == m.IncidentPhase.AWAITING_APPROVAL:
            state = self._approval_state(conn, incident, existing)
            if state.state == "PENDING":
                return existing
            _require(state.state == "EXPIRED", f"requirement {existing.id} is already {state.state}", error=ApprovalRefused)
        now = utcnow()
        expires = now + APPROVAL_TTL
        if intervention.window_start is not None:
            expires = min(expires, intervention.window_start)
        # F1: decision-relevant uncertainty is part of what the approver approves; it
        # is bound to the requirement and listed with its source among the conditions.
        material = self._material_uncertainties(conn, incident, record)
        requirement = m.ApprovalRequirement(
            **_identity(incident.id), intervention_id=intervention.id, intervention_hash=artifact_hash(intervention),
            policy_version=POLICY_VERSION, mode="HUMAN", required_roles=(APPROVER_ROLE,), minimum_distinct_approvers=1,
            conditions=(*governance.reasons, *(f"MATERIAL uncertainty ({item.source_role}): {item.statement}"
                                               for item in material)),
            expires_at=expires, promotion_id=record.id,
            supersedes_id=existing.id if existing is not None else None, material_uncertainties=material or None)
        self._checkpoint(conn, incident, [requirement], phase=m.IncidentPhase.AWAITING_APPROVAL,
                         reason="deterministic governance requires human approval",
                         events=[*events, ("APPROVAL_REQUESTED", {
                             "requirement_id": requirement.id, "intervention_id": intervention.id,
                             "intervention_hash": requirement.intervention_hash, "promotion_id": record.id,
                             "policy_version": POLICY_VERSION, "governance": governance.model_dump(mode="json")})])
        return requirement

    def decide_approval(self, incident_id: str, *, requirement_id: str, intervention_id: str, intervention_hash: str,
                        context_revision: int, actor_id: str, actor_role: str,
                        decision: Literal["APPROVE", "REJECT"], rationale: str, actor_kind: str | None = None,
                        return_to: Literal["PLANNING", "INVESTIGATING", "ESCALATED"] = "PLANNING") -> m.ApprovalDecision:
        """Atomic: exact decision + AWAITING_APPROVAL -> READY (APPROVE) or ``return_to`` (REJECT).

        Approval authorizes an exact, currently promoted intervention. It never
        validates a diagnosis or intervention and never overrides governance. F1: a
        rejection consumes the intervention and returns the case to PLANNING by
        default; INVESTIGATING or an explicit ESCALATED are the approver's choice.
        """
        _require(return_to in {"PLANNING", "INVESTIGATING", "ESCALATED"}, f"unsupported rejection target {return_to}",
                 error=ApprovalRefused)
        _require(actor_id.strip() and actor_role.strip() and rationale.strip(),
                 "approval actor, role and rationale are required", error=ApprovalRefused)
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            actor_kind = authorize(actor_kind, incident)
            requirement = self.repository._artifact(conn, incident.id, requirement_id)
            _require(isinstance(requirement, m.ApprovalRequirement) and requirement.policy_version == POLICY_VERSION
                     and requirement.mode == "HUMAN", "requirement is not a lifecycle human approval requirement",
                     error=ApprovalRefused)
            prior = [item for item in self._decisions(conn, incident.id, requirement.id) if item.actor_id == actor_id]
            if prior:
                same = prior[-1]
                _require((same.decision, same.intervention_id, same.intervention_hash) == (decision, intervention_id, intervention_hash),
                         "conflicting duplicate decision for the same requirement and actor", error=ApprovalRefused)
                return same  # idempotent retry of the same semantic decision; no mutation
            _require(incident.revision == context_revision,
                     f"stale approval context: revision {context_revision} is not current {incident.revision}",
                     error=ApprovalRefused)
            _require(incident.phase == m.IncidentPhase.AWAITING_APPROVAL,
                     f"approval requires AWAITING_APPROVAL, found {incident.phase.value}", error=ApprovalRefused)
            intervention, record = self._authority(conn, incident)
            current_hash = artifact_hash(intervention)
            _require(requirement.intervention_id == intervention.id == intervention_id
                     and requirement.intervention_hash == current_hash == intervention_hash,
                     "decision does not identify the exact current promoted intervention", error=ApprovalRefused)
            _require(requirement.promotion_id == record.id, "requirement lineage differs from current promotion",
                     error=ApprovalRefused)
            _require(self._current_requirement(conn, incident, intervention) is not None
                     and self._current_requirement(conn, incident, intervention).id == requirement.id,
                     "approval requirement has been superseded", error=ApprovalRefused)
            state = self._approval_state(conn, incident, requirement)
            _require(state.state == "PENDING", f"approval requirement is {state.state}", error=ApprovalRefused)
            _require(actor_role in requirement.required_roles, "actor role cannot satisfy this requirement",
                     error=ApprovalRefused)
            governance = self._governance(conn, incident, intervention, record)
            if governance.disposition == "BLOCKED":
                raise GovernanceBlocked(governance)
            record_decision = m.ApprovalDecision(
                **_identity(incident.id), requirement_id=requirement.id, intervention_id=intervention.id,
                intervention_hash=current_hash, actor_id=actor_id, actor_role=actor_role, decision=decision,
                rationale=rationale, context_revision=incident.revision, promotion_id=record.id, actor_kind=actor_kind)
            self.repository._validate_references(conn, incident, record_decision)
            conn.execute("INSERT INTO approval_decision VALUES (?,?,?,?,?,?,?)",
                         (record_decision.id, incident.id, record_decision.intervention_id, record_decision.intervention_hash,
                          record_decision.actor_id, record_decision.created_at.isoformat(), record_decision.model_dump_json()))
            target = m.IncidentPhase.READY if decision == "APPROVE" else m.IncidentPhase(return_to)
            changes = {}
            if decision == "REJECT" and target != m.IncidentPhase.ESCALATED:
                changes["current_intervention_id"] = None  # the rejected intervention is consumed
            self._checkpoint(conn, incident, phase=target,
                             reason=("exact human approval recorded" if decision == "APPROVE"
                                     else f"human rejected the promoted intervention; returned to {target.value}"),
                             events=[("APPROVAL_RECORDED", {
                                 "decision_id": record_decision.id, "decision": decision, "requirement_id": requirement.id,
                                 "intervention_id": intervention.id, "intervention_hash": current_hash,
                                 "promotion_id": record.id, "actor_id": actor_id, "actor_role": actor_role,
                                 "actor_kind": actor_kind, "rationale": rationale,
                                 **({"return_to": target.value} if decision == "REJECT" else {})})],
                             **changes)
            return record_decision

    # --------------------------------------------------------------- execution
    @staticmethod
    def _request_hash(step):
        return content_hash({"capability": step.capability, "parameters": step.parameters})

    def _eligibility(self, conn, incident, intervention_id, intervention_hash):
        """All execution prerequisites, evaluated under the claim transaction."""
        intervention, record = self._authority(conn, incident)
        _require(intervention.id == intervention_id and intervention.status == "VALIDATED",
                 "execution target is not the current VALIDATED promoted intervention", error=ExecutionRefused)
        current_hash = artifact_hash(intervention)
        _require(intervention_hash is None or intervention_hash == current_hash,
                 "execution target hash differs from the current promoted intervention", error=ExecutionRefused)
        governance = self._governance(conn, incident, intervention, record)
        if governance.disposition == "BLOCKED":
            raise GovernanceBlocked(governance)
        requirement = self._current_requirement(conn, incident, intervention)
        _require(requirement is not None and requirement.promotion_id == record.id,
                 "no current approval requirement binds this promoted intervention", error=ExecutionRefused)
        approval = self._approval_state(conn, incident, requirement)
        _require(approval.state == "APPROVED", f"exact human approval is {approval.state}", error=ExecutionRefused)
        step = intervention.steps[0]
        parameters = WorkPackageParameters.model_validate(step.parameters)
        return intervention, record, requirement, approval, step, parameters

    def _claim(self, incident_id, intervention_id, intervention_hash, adapter) -> _Claimed | None:
        adapter_name = f"{type(adapter).__module__}.{type(adapter).__qualname__}"
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase == m.IncidentPhase.EXECUTING:
                raise ExecutionBusy("incident already has execution in flight; reconcile before retrying")
            _require(incident.phase == m.IncidentPhase.READY, f"execution requires READY, found {incident.phase.value}",
                     error=ExecutionRefused)
            intervention, record, requirement, approval, step, parameters = self._eligibility(
                conn, incident, intervention_id, intervention_hash)
            request_hash = self._request_hash(step)
            key = GovernedExecutor._idempotency_key(incident, intervention, step, request_hash)
            existing = self._claim_row(conn, key)
            now = utcnow()
            if existing is not None:
                bound = (existing.incident_id, existing.intervention_id, existing.intervention_hash, existing.step_id,
                         existing.capability, existing.request_hash)
                _require(bound == (incident.id, intervention.id, artifact_hash(intervention), step.id, step.capability, request_hash),
                         "idempotency key is bound to a different action", error=ExecutionRefused)
                if existing.state == "IN_FLIGHT":
                    raise ExecutionBusy("execution step already in progress")
                if existing.state in {"UNKNOWN", "CONFIRMED"}:
                    raise ReconciliationRequired(
                        f"prior execution claim is {existing.state}; reconciliation is required before any new dispatch")
                attempt = existing.attempt + 1
                conn.execute("UPDATE execution_claim SET state='IN_FLIGHT',attempt=?,started_at=?,updated_at=?,"
                             "adapter=?,executor=?,error_message=NULL WHERE idempotency_key=? AND state='FAILED'",
                             (attempt, now.isoformat(), now.isoformat(), adapter_name, TRUSTED_EXECUTOR, key))
            else:
                attempt = 1
                conn.execute(
                    "INSERT INTO execution_claim (idempotency_key,incident_id,intervention_id,intervention_hash,step_id,"
                    "capability,request_hash,executor,state,attempt,started_at,updated_at,error_message,adapter) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, incident.id, intervention.id, artifact_hash(intervention), step.id, step.capability, request_hash,
                     TRUSTED_EXECUTOR, "IN_FLIGHT", attempt, now.isoformat(), now.isoformat(), None, adapter_name))
            claim = m.ExecutionClaim(
                idempotency_key=key, incident_id=incident.id, intervention_id=intervention.id,
                intervention_hash=artifact_hash(intervention), step_id=step.id, capability=step.capability,
                request_hash=request_hash, adapter=adapter_name, executor=TRUSTED_EXECUTOR, state="IN_FLIGHT",
                attempt=attempt, started_at=now, updated_at=now)
            updated = self._checkpoint(conn, incident, phase=m.IncidentPhase.EXECUTING,
                                       reason="execution eligibility validated; claim established",
                                       events=[("EXECUTION_CLAIMED", {
                                           "idempotency_key": key, "step_id": step.id, "attempt": attempt,
                                           "intervention_id": intervention.id, "intervention_hash": claim.intervention_hash,
                                           "promotion_id": record.id, "requirement_id": requirement.id,
                                           "decision_ids": list(approval.decision_ids)})])
            return _Claimed(updated, intervention, step, claim, parameters, adapter, {})

    def _receipt(self, claimed: _Claimed, *, status, external_ids=None, error_code=None, error_message=None):
        now = utcnow()
        claim = claimed.claim
        return m.ExecutionReceipt(
            **_identity(claim.incident_id), intervention_id=claim.intervention_id, intervention_hash=claim.intervention_hash,
            step_id=claim.step_id, capability=claim.capability, idempotency_key=claim.idempotency_key,
            operation_key=f"{claim.idempotency_key}:attempt:{claim.attempt}:{status.lower()}", adapter=claim.adapter,
            executor=TRUSTED_EXECUTOR, request_hash=claim.request_hash, status=status, external_ids=external_ids or {},
            attempted_at=claim.started_at, completed_at=now, attempt=claim.attempt, error_code=error_code,
            error_message=error_message)

    def record_receipt(self, receipt: m.ExecutionReceipt) -> m.Incident:
        """Atomic: receipt + claim checkpoint + terminal execution phase.

        CAS is the claim identity only. New evidence or any revision advance during
        the external call must not prevent recording what physically happened.
        CONFIRMED -> OBSERVING; FAILED/UNKNOWN -> EXECUTION_FAILED. Never CLOSED.
        """
        receipt = m.ExecutionReceipt.model_validate_json(receipt.model_dump_json())
        _require(receipt.status in {"CONFIRMED", "FAILED", "UNKNOWN"}, "completion requires a terminal receipt")
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, receipt.incident_id)
            claim = self._claim_row(conn, receipt.idempotency_key)
            _require(claim is not None, "execution claim does not exist", error=ReconciliationRequired)
            identity = (claim.incident_id, claim.intervention_id, claim.intervention_hash, claim.step_id,
                        claim.capability, claim.request_hash)
            _require(identity == (receipt.incident_id, receipt.intervention_id, receipt.intervention_hash, receipt.step_id,
                                  receipt.capability, receipt.request_hash),
                     "receipt does not match the execution claim identity", error=ReconciliationRequired)
            if claim.state != "IN_FLIGHT" or claim.attempt != receipt.attempt:
                settled = [item for item in self._receipts(conn, incident.id)
                           if item.idempotency_key == receipt.idempotency_key and item.attempt == receipt.attempt]
                if settled and claim.attempt == receipt.attempt and any(
                        receipt_content(item) == receipt_content(receipt) for item in settled):
                    return incident  # exact semantic duplicate of the persisted completion: idempotent
                if settled and all(item.status == receipt.status for item in settled):
                    raise ReconciliationRequired(
                        "duplicate completion carries different consequential content than the persisted receipt")
                raise ReconciliationRequired("conflicting completion for an already settled execution claim")
            conn.execute("INSERT INTO execution_receipt VALUES (?,?,?,?,?,?,?)",
                         (receipt.id, incident.id, receipt.intervention_id, receipt.operation_key, receipt.status,
                          receipt.created_at.isoformat(), receipt.model_dump_json()))
            conn.execute("UPDATE execution_claim SET state=?,updated_at=?,error_message=? "
                         "WHERE idempotency_key=? AND state='IN_FLIGHT' AND attempt=?",
                         (receipt.status, receipt.created_at.isoformat(), receipt.error_message,
                          receipt.idempotency_key, receipt.attempt))
            target = m.IncidentPhase.OBSERVING if receipt.status == "CONFIRMED" else m.IncidentPhase.EXECUTION_FAILED
            events = [("EXECUTION_RECORDED", {
                "receipt_id": receipt.id, "step_id": receipt.step_id, "status": receipt.status, "attempt": receipt.attempt,
                "intervention_id": receipt.intervention_id, "intervention_hash": receipt.intervention_hash,
                "claim_revision_advanced": incident.revision != claim_started_revision(conn, incident.id, receipt.idempotency_key)})]
            artifacts = []
            if receipt.status == "CONFIRMED":
                assignment = self._work_assignment(conn, incident, receipt)
                artifacts.append(assignment)
                events.append(("WORK_ASSIGNED", {
                    "assignment_id": assignment.id, "receipt_id": receipt.id, "assignee": assignment.assignee.model_dump(
                        mode="json", exclude={"schema_version"}), "delivery_channel": assignment.delivery_channel,
                    "external_refs": assignment.external_refs}))
            if incident.phase != m.IncidentPhase.EXECUTING:
                # Reality is recorded; the phase left EXECUTING through another explicit
                # command, so the application flags reconciliation instead of guessing.
                events.append(("INCIDENT_UPDATED", {"reconciliation": "receipt recorded outside EXECUTING",
                                                     "phase": incident.phase.value, "receipt_id": receipt.id}))
                return self._checkpoint(conn, incident, artifacts, events=events)
            return self._checkpoint(conn, incident, artifacts, phase=target, events=events,
                                    reason=("work-package action confirmed; outcome observation required"
                                            if receipt.status == "CONFIRMED" else
                                            f"execution {receipt.status.lower()}; explicit reconciliation or retry required"))

    def execute(self, incident_id: str, intervention_id: str, *, intervention_hash: str | None = None) -> ExecutionReport:
        """READY -> claim (txn) -> adapter call (no lock) -> receipt (txn) -> OBSERVING/EXECUTION_FAILED."""
        from core import services
        adapter = services.cmms()  # registry lookup only; resolved before any lock is held
        claimed = self._claim(incident_id, intervention_id, intervention_hash, adapter)
        authorization = ExecutionAuthorization(
            incident_id=claimed.incident.id, intervention_id=claimed.intervention.id,
            intervention_hash=claimed.claim.intervention_hash, step_id=claimed.step.id,
            idempotency_key=claimed.claim.idempotency_key, executor=TRUSTED_EXECUTOR, _seal=_AUTHORITY_SEAL)
        try:
            result = adapter.create_work_package(GovernedExecutor._legacy_work_package(claimed.parameters),
                                                 authorization=authorization)
        except Exception as exc:
            status = failure_status(adapter, exc)
            receipt = self._receipt(claimed, status=status, error_code=type(exc).__name__, error_message=str(exc))
            incident = self.record_receipt(receipt)
            report = ExecutionReport(incident_id=incident.id, intervention_id=claimed.intervention.id, phase=incident.phase,
                                     receipt_ids=(receipt.id,))
            error = ExecutionFailed if status == "FAILED" else ExecutionAmbiguous
            raise error(f"work package step {claimed.step.id} {status.lower()}: {exc}", report) from exc
        external = {str(key): str(value) for key, value in result.items()
                    if value is not None and (key.endswith("_id") or key.endswith("_number"))}
        receipt = self._receipt(claimed, status="CONFIRMED", external_ids=external)
        incident = self.record_receipt(receipt)
        return ExecutionReport(incident_id=incident.id, intervention_id=claimed.intervention.id, phase=incident.phase,
                               receipt_ids=(receipt.id,), external_objects=external)

    def retry_execution(self, incident_id: str, *, expected_revision: int, actor: m.ActorRef | None = None,
                        rationale: str | None = None) -> m.Incident:
        """EXECUTION_FAILED -> READY only after a definitive FAILED claim; UNKNOWN never replays.

        F1: a human retry names its actor and rationale and is audited as a command.
        """
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            self.repository._check(incident, expected_revision)
            if actor is not None:
                authorize(actor.kind, incident)
                _require(isinstance(rationale, str) and rationale.strip(), "retry_execution requires a rationale")
            _require(incident.phase == m.IncidentPhase.EXECUTION_FAILED, "retry requires EXECUTION_FAILED",
                     error=ExecutionRefused)
            intervention, *_ = self._eligibility(conn, incident, incident.current_intervention_id, None)
            claims = self._claims_for(conn, incident.id, intervention.id)
            _require(all(item.state == "FAILED" for item in claims),
                     "a prior claim is not definitively FAILED; reconciliation is required",
                     error=ReconciliationRequired)
            events = [] if actor is None else [("LIFECYCLE_COMMAND", {
                "command": "retry_execution", "actor": actor.public(), "rationale": rationale.strip(),
                "from": incident.phase.value, "to": m.IncidentPhase.READY.value})]
            return self._checkpoint(conn, incident, phase=m.IncidentPhase.READY, events=events,
                                    reason="explicit retry after definitive execution failure")

    def reconcile(self, incident_id: str) -> LifecycleStatus:
        """Restart-safe reconciliation. Never dispatches; may settle a stale claim as UNKNOWN."""
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase == m.IncidentPhase.EXECUTING and incident.current_intervention_id:
                for claim in self._claims_for(conn, incident.id, incident.current_intervention_id):
                    if claim.state == "IN_FLIGHT" and utcnow() - claim.started_at >= AMBIGUOUS_CLAIM_AFTER:
                        intervention = self.repository._artifact(conn, incident.id, claim.intervention_id)
                        step = next(item for item in intervention.steps if item.id == claim.step_id)
                        unknown = self._receipt(_Claimed(incident, intervention, step, claim, None, None, {}),
                                                status="UNKNOWN", error_code="AMBIGUOUS_COMMIT",
                                                error_message="in-flight claim outlived reconciliation window")
                        conn.execute("INSERT INTO execution_receipt VALUES (?,?,?,?,?,?,?)",
                                     (unknown.id, incident.id, unknown.intervention_id, unknown.operation_key, unknown.status,
                                      unknown.created_at.isoformat(), unknown.model_dump_json()))
                        conn.execute("UPDATE execution_claim SET state='UNKNOWN',updated_at=?,error_message=? "
                                     "WHERE idempotency_key=? AND state='IN_FLIGHT'",
                                     (unknown.created_at.isoformat(), unknown.error_message, claim.idempotency_key))
                        incident = self._checkpoint(conn, incident, phase=m.IncidentPhase.EXECUTION_FAILED,
                                                    reason="execution outcome is ambiguous after restart",
                                                    events=[("EXECUTION_RECORDED", {
                                                        "receipt_id": unknown.id, "step_id": claim.step_id,
                                                        "status": "UNKNOWN", "attempt": claim.attempt})])
                        break
            return self._status(conn, incident)

    # ------------------------------------------------------- recovery commands (F1)
    # Every command: one transaction, the caller's expected revision, an admissible
    # actor, a rationale, a graph-valid transition through _checkpoint and an audited
    # LIFECYCLE_COMMAND event. None of them writes authority or sets state directly.
    def _command(self, conn, incident, *, command, actor: m.ActorRef, rationale, phase=None, events=(), artifacts=(),
                 extra: dict | None = None, **changes):
        _require(isinstance(rationale, str) and rationale.strip(), f"{command} requires a rationale")
        authorize(actor.kind, incident)
        target = phase or incident.phase
        payload = {"command": command, "actor": actor.public(), "rationale": rationale.strip(),
                   "from": incident.phase.value, "to": target.value, **(extra or {})}
        return self._checkpoint(conn, incident, artifacts, phase=phase, reason=f"{command}: {rationale.strip()}",
                                events=[("LIFECYCLE_COMMAND", payload), *events], **changes)

    def _open(self, conn, incident_id, expected_revision):
        incident = self.repository._fetch(conn, incident_id)
        self.repository._check(incident, expected_revision)  # also refuses CLOSED/CANCELLED
        return incident

    def resume(self, incident_id: str, *, expected_revision: int, actor: m.ActorRef, rationale: str) -> m.Incident:
        """Re-enter the state machine through an explicit, valid transition (never a state write).

        * analysis suspended after technical failures (INVESTIGATING/PLANNING): clear the
          suspension; the next run starts with a fresh retry budget;
        * ESCALATED -> INVESTIGATING;
        * AWAITING_APPROVAL whose promoted plan was invalidated by newer evidence -> INVESTIGATING;
        * EXECUTION_FAILED with only definitive FAILED claims -> INVESTIGATING (dispatch abandoned);
        * F1.2, narrowly: OBSERVING whose current work was declined or reported without
          qualifying (no observation can start), or whose verification is BLOCKED as a
          pre-version-2 case -> INVESTIGATING. The dispatched intervention is consumed and
          the abandoned work (with its external work-order references) is recorded.
        """
        with self.repository._write() as conn:
            incident = self._open(conn, incident_id, expected_revision)
            phase = incident.phase
            if phase == m.IncidentPhase.OBSERVING:
                return self._resume_observing(conn, incident, actor=actor, rationale=rationale)
            if incident.analysis is not None and incident.analysis.suspended:
                return self._command(conn, incident, command="resume", actor=actor, rationale=rationale, analysis=None,
                                     events=[("ANALYSIS_RESUMED", {"previous": incident.analysis.model_dump(mode="json")})])
            if phase == m.IncidentPhase.ESCALATED:
                return self._command(conn, incident, command="resume", actor=actor, rationale=rationale,
                                     phase=m.IncidentPhase.INVESTIGATING)
            if phase == m.IncidentPhase.AWAITING_APPROVAL:
                try:
                    self._authority(conn, incident)
                except AuthorityRefused as exc:
                    return self._command(conn, incident, command="resume", actor=actor, rationale=rationale,
                                         phase=m.IncidentPhase.INVESTIGATING, current_intervention_id=None,
                                         events=[("INCIDENT_UPDATED", {"invalidated_plan": str(exc)})])
                _require(False, "the approval is still valid; decide, renew or return it to planning instead")
            if phase == m.IncidentPhase.EXECUTION_FAILED:
                claims = self._claims_for(conn, incident.id, incident.current_intervention_id) if incident.current_intervention_id else []
                _require(all(item.state == "FAILED" for item in claims),
                         "a dispatch outcome is not definitively FAILED; reconcile it before abandoning dispatch",
                         error=ReconciliationRequired)
                return self._command(conn, incident, command="resume", actor=actor, rationale=rationale,
                                     phase=m.IncidentPhase.INVESTIGATING, current_intervention_id=None)
            _require(False, f"nothing to resume in {phase.value}")

    def cancel(self, incident_id: str, *, expected_revision: int, actor: m.ActorRef, rationale: str) -> m.Incident:
        """Explicit human abandonment -> CANCELLED. Releases the asset's admission key.

        Refused while a dispatch is in flight (EXECUTING): what physically happened must
        be recorded first. A cancelled case keeps its full durable record.
        """
        with self.repository._write() as conn:
            incident = self._open(conn, incident_id, expected_revision)
            _require(incident.phase != m.IncidentPhase.EXECUTING,
                     "a dispatch is in flight; record or reconcile it before cancelling")
            claims = self._claims_for(conn, incident.id, incident.current_intervention_id) if incident.current_intervention_id else []
            work = self._work_disposition(conn, incident)
            return self._command(conn, incident, command="cancel", actor=actor, rationale=rationale,
                                 phase=m.IncidentPhase.CANCELLED, active_run_id=None,
                                 events=[("INCIDENT_CANCELLED", {
                                     "actor": actor.public(), "rationale": rationale.strip(),
                                     "claim_states": [item.state for item in claims],
                                     **({"work": work} if work else {})})])

    def escalate(self, incident_id: str, *, expected_revision: int, actor: m.ActorRef, rationale: str) -> m.Incident:
        """Explicit human escalation to higher authority (a separate act from rejection)."""
        with self.repository._write() as conn:
            incident = self._open(conn, incident_id, expected_revision)
            _require(incident.phase not in {m.IncidentPhase.EXECUTING, m.IncidentPhase.ESCALATED},
                     f"cannot escalate from {incident.phase.value}")
            work = self._work_disposition(conn, incident)
            return self._command(conn, incident, command="escalate", actor=actor, rationale=rationale,
                                 phase=m.IncidentPhase.ESCALATED, extra={"work": work} if work else None)

    def renew_approval(self, incident_id: str, *, expected_revision: int, actor: m.ActorRef,
                       rationale: str) -> m.ApprovalRequirement:
        """Issue a fresh requirement for the same exact intervention after the previous one EXPIRED.

        Governance is re-evaluated; if the confirmed window has passed it refuses
        (GovernanceBlocked) and the case must return to planning instead.
        """
        with self.repository._write() as conn:
            incident = self._open(conn, incident_id, expected_revision)
            _require(incident.phase == m.IncidentPhase.AWAITING_APPROVAL, "renewal requires AWAITING_APPROVAL",
                     error=ApprovalRefused)
            authorize(actor.kind, incident)
            _require(isinstance(rationale, str) and rationale.strip(), "renew_approval requires a rationale")
            intervention, _ = self._authority(conn, incident)
            existing = self._current_requirement(conn, incident, intervention)
            _require(existing is not None and self._approval_state(conn, incident, existing).state == "EXPIRED",
                     "only an expired approval requirement can be renewed", error=ApprovalRefused)
            return self._request_approval_in(conn, incident, events=[("LIFECYCLE_COMMAND", {
                "command": "renew_approval", "actor": actor.public(), "rationale": rationale.strip(),
                "from": incident.phase.value, "to": incident.phase.value, "expired_requirement_id": existing.id})])

    def return_to_planning(self, incident_id: str, *, expected_revision: int, actor: m.ActorRef,
                           rationale: str) -> m.Incident:
        """Withdraw the current promoted intervention (expired window, changed resources,
        requested changes): INTERVENTION_VALIDATED/AWAITING_APPROVAL/READY -> PLANNING."""
        with self.repository._write() as conn:
            incident = self._open(conn, incident_id, expected_revision)
            _require(incident.phase in {m.IncidentPhase.INTERVENTION_VALIDATED, m.IncidentPhase.AWAITING_APPROVAL,
                                        m.IncidentPhase.READY}, f"cannot return to planning from {incident.phase.value}")
            return self._command(conn, incident, command="return_to_planning", actor=actor, rationale=rationale,
                                 phase=m.IncidentPhase.PLANNING, current_intervention_id=None)

    def _return_to_planning(self, incident_id, *, reason, actor: m.ActorRef, command):
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if incident.phase not in {m.IncidentPhase.INTERVENTION_VALIDATED, m.IncidentPhase.AWAITING_APPROVAL,
                                      m.IncidentPhase.READY}:
                return incident
            return self._command(conn, incident, command=command, actor=actor, rationale=reason,
                                 phase=m.IncidentPhase.PLANNING, current_intervention_id=None)

    # --------------------------------------------------------- work (F1, F1.2)
    # Work requested (WorkAssignment at the confirmed dispatch), acknowledged, declined,
    # reassigned and reported are separate durable facts about people. None of them is
    # evidence that the plant recovered. F1.2: only an eligible report
    # (operon-work-eligibility-1) on the current assignment of the executed dispatch
    # opens outcome verification, and even then post-report telemetry alone decides.
    # Every command: one transaction, the caller's expected revision (except an exact
    # idempotent replay), an admissible actor and a typed WORK_* event.
    def _work_assignment(self, conn, incident, receipt, *, assignee: m.WorkAssignee | None = None,
                         supersedes: str | None = None) -> m.WorkAssignment:
        intervention = self.repository._artifact(conn, incident.id, receipt.intervention_id)
        step = next(item for item in intervention.steps if item.id == receipt.step_id)
        parameters = WorkPackageParameters.model_validate(step.parameters)
        return m.WorkAssignment(
            **_identity(incident.id), equipment_ids=tuple(step.equipment_ids), intervention_id=intervention.id,
            intervention_hash=receipt.intervention_hash, step_id=step.id, execution_claim_key=receipt.idempotency_key,
            receipt_id=receipt.id, external_refs=dict(receipt.external_ids),
            assignee=assignee or m.WorkAssignee(kind="WORKER", reference=parameters.technician_id,
                                                reference_system="operon.local.technician_roster"),
            delivery_channel="operon.local", instructions=tuple(line for line in parameters.detail.split("\n") if line),
            window_start=intervention.window_start, window_end=intervention.window_end,
            supersedes_assignment_id=supersedes)

    def _dispatch_receipt(self, conn, incident) -> m.ExecutionReceipt | None:
        """The CONFIRMED receipt of the current intervention (the executed dispatch), if any."""
        if not incident.current_intervention_id:
            return None
        confirmed = [item for item in self._receipts(conn, incident.id)
                     if item.status == "CONFIRMED" and item.intervention_id == incident.current_intervention_id]
        return confirmed[-1] if confirmed else None

    def _work_states(self, conn, incident_id) -> dict[str, dict]:
        """Durable work facts per assignment, in creation order. Descriptive only, never authority."""
        assignments = self._all(conn, incident_id, m.WorkAssignment)
        reports = {item.assignment_id: item for item in self._all(conn, incident_id, m.WorkReport)}
        successors = {item.supersedes_assignment_id: item.id for item in assignments if item.supersedes_assignment_id}
        confirmed = [item.id for item in self._receipts(conn, incident_id) if item.status == "CONFIRMED"]
        latest_receipt = confirmed[-1] if confirmed else None
        by_id = {item.id: item for item in assignments}
        states = {item.id: {
            "assignment_id": item.id, "state": "ASSIGNED",
            "current": item.id not in successors and item.receipt_id == latest_receipt,
            "receipt_id": item.receipt_id, "supersedes_assignment_id": item.supersedes_assignment_id,
            "superseded_by": successors.get(item.id),
            "assignee": item.assignee.model_dump(mode="json", exclude={"schema_version"}),
            "delivery_channel": item.delivery_channel, "external_refs": item.external_refs,
            "instructions": list(item.instructions),
            "window_start": item.window_start.isoformat() if item.window_start else None,
            "window_end": item.window_end.isoformat() if item.window_end else None,
            "assigned_at": item.created_at.isoformat(), "acknowledged_at": None, "acknowledged_by": None,
            "declined_at": None, "declined_by": None, "decline_reason": None,
            "report_id": None, "result": None, "reported_at": None, "reported_by": None,
            "performed_at_claimed": None, "asset_intervened": None, "completed_instructions": None,
            "provenance": None, "eligible": None, "eligibility_reasons": [],
        } for item in assignments}
        rows = conn.execute("SELECT created_at,event_type,payload_json FROM incident_event WHERE incident_id=? "
                            "AND event_type IN ('WORK_ACKNOWLEDGED','WORK_DECLINED','WORK_REPORTED') ORDER BY event_id",
                            (incident_id,)).fetchall()
        for created_at, event_type, payload_json in rows:
            payload = json.loads(payload_json)
            state = states.get(payload.get("assignment_id"))
            if state is None:
                continue
            if event_type == "WORK_ACKNOWLEDGED":
                state.update(state="ACKNOWLEDGED", acknowledged_at=created_at, acknowledged_by=payload.get("actor"))
            elif event_type == "WORK_DECLINED":
                state.update(state="DECLINED", declined_at=created_at, declined_by=payload.get("actor"),
                             decline_reason=payload.get("reason"))
        for assignment_id, report in reports.items():
            state = states.get(assignment_id)
            if state is None:
                continue
            eligible, reasons = work_eligibility(by_id[assignment_id], report)
            # reported_at is the server-recorded report time: the F1.2 verification boundary.
            state.update(state="REPORTED", report_id=report.id, result=report.result,
                         reported_at=report.created_at.isoformat(), reported_by=report.actor.public(),
                         performed_at_claimed=report.performed_at.isoformat() if report.performed_at else None,
                         asset_intervened=report.asset_intervened,
                         completed_instructions=(None if report.completed_instructions is None
                                                 else list(report.completed_instructions)),
                         provenance=report.provenance, eligible=eligible, eligibility_reasons=list(reasons))
        return states

    def work_status(self, incident_id: str) -> list[dict]:
        with db.get_conn(self.repository.path) as conn:
            return list(self._work_states(conn, incident_id).values())

    def _current_work(self, conn, incident) -> dict | None:
        """The current assignment state of the executed dispatch, or None."""
        receipt = self._dispatch_receipt(conn, incident)
        if receipt is None:
            return None
        current = [item for item in self._work_states(conn, incident.id).values()
                   if item["current"] and item["receipt_id"] == receipt.id]
        return current[-1] if current else None

    def _qualifying_work(self, conn, incident, receipt) -> tuple[m.WorkAssignment, m.WorkReport] | None:
        """The eligible report on the current assignment of ``receipt`` (operon-work-eligibility-1), or None."""
        assignments = [item for item in self._all(conn, incident.id, m.WorkAssignment) if item.receipt_id == receipt.id]
        superseded = {item.supersedes_assignment_id for item in assignments if item.supersedes_assignment_id}
        current = [item for item in assignments if item.id not in superseded]
        if not current:
            return None
        assignment = current[-1]
        reports = [item for item in self._all(conn, incident.id, m.WorkReport) if item.assignment_id == assignment.id]
        if len(reports) != 1 or not work_eligibility(assignment, reports[0])[0]:
            return None
        return assignment, reports[0]

    def _work_disposition(self, conn, incident) -> dict | None:
        """What leaving OBSERVING abandons: open assignments and the external work orders not recalled."""
        receipt = self._dispatch_receipt(conn, incident)
        if receipt is None or incident.phase != m.IncidentPhase.OBSERVING:
            return None
        states = [item for item in self._work_states(conn, incident.id).values() if item["receipt_id"] == receipt.id]
        return {"receipt_id": receipt.id, "external_refs": dict(receipt.external_ids),
                "assignments": [{"assignment_id": item["assignment_id"], "state": item["state"],
                                 "eligible": item["eligible"]} for item in states],
                "note": "OPERON has no work-order cancel capability; dispatched work orders are not recalled"}

    def _work_guard(self, conn, incident, assignment_id) -> dict:
        """A work command acts only on the current assignment of the executed dispatch of an OBSERVING case."""
        _require(incident.phase == m.IncidentPhase.OBSERVING,
                 f"work commands require OBSERVING; the case is {incident.phase.value}")
        legacy = self._legacy_verification(conn, incident)
        _require(legacy is None, (legacy or {}).get("reason", ""))
        state = self._work_states(conn, incident.id).get(assignment_id)
        _require(state is not None, "unknown work assignment")
        _require(state["current"], f"work assignment {assignment_id} is not current"
                 + (f"; it was superseded by {state['superseded_by']}" if state["superseded_by"] else ""))
        return state

    @staticmethod
    def _request_digest(command: str, assignment_id: str, actor: m.ActorRef, **fields) -> str:
        return content_hash({"command": command, "assignment_id": assignment_id,
                             "actor": actor.model_dump(mode="json", exclude={"schema_version"}),
                             "fields": to_jsonable_python(fields)})

    def _replay(self, conn, incident_id, request_key, digest) -> dict | None:
        """The recorded payload of an identical earlier work request, or None.

        A client retry with the same ``request_key`` and identical content is answered
        from the durable record (no second write, no revision check); the same key with
        different content is refused. Keys are scoped to the case's work commands.
        """
        if request_key is None:
            return None
        _require(isinstance(request_key, str) and 0 < len(request_key.strip()) <= 128,
                 "request_key must be 1-128 characters")
        row = conn.execute("SELECT payload_json FROM incident_event WHERE incident_id=? AND event_type IN "
                           "('WORK_ACKNOWLEDGED','WORK_DECLINED','WORK_REPORTED','WORK_REASSIGNED') "
                           "AND json_extract(payload_json,'$.request_key')=? ORDER BY event_id LIMIT 1",
                           (incident_id, request_key)).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        _require(payload.get("request_digest") == digest,
                 "request_key was already used for a different work request", disposition="CONFLICT")
        return payload

    def request_recorded(self, incident_id: str, request_key: str | None) -> bool:
        """Whether a work request with ``request_key`` is already durable (descriptive; for API replay flags)."""
        if not request_key:
            return False
        with db.get_conn(self.repository.path) as conn:
            return conn.execute("SELECT 1 FROM incident_event WHERE incident_id=? AND event_type IN "
                                "('WORK_ACKNOWLEDGED','WORK_DECLINED','WORK_REPORTED','WORK_REASSIGNED') "
                                "AND json_extract(payload_json,'$.request_key')=?",
                                (incident_id, request_key)).fetchone() is not None

    @staticmethod
    def _keyed(request_key, digest) -> dict:
        return {"request_key": request_key, "request_digest": digest} if request_key is not None else {}

    def acknowledge_work(self, incident_id: str, *, assignment_id: str, expected_revision: int, actor: m.ActorRef,
                         note: str | None = None, request_key: str | None = None) -> m.Incident:
        """The assignee acknowledges the request. Separate from assignment; not performance."""
        digest = self._request_digest("acknowledge_work", assignment_id, actor, note=note)
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if self._replay(conn, incident.id, request_key, digest) is not None:
                return incident
            self.repository._check(incident, expected_revision)
            authorize(actor.kind, incident)
            state = self._work_guard(conn, incident, assignment_id)
            _require(state["state"] == "ASSIGNED", f"work assignment is already {state['state']}")
            return self._checkpoint(conn, incident, events=[("WORK_ACKNOWLEDGED", {
                "assignment_id": assignment_id, "actor": actor.public(), "note": (note or "").strip() or None,
                **self._keyed(request_key, digest)})])

    def decline_work(self, incident_id: str, *, assignment_id: str, expected_revision: int, actor: m.ActorRef,
                     reason: str, request_key: str | None = None) -> m.Incident:
        """The assignee declines an unacknowledged request. The plant is never actuated; the
        coordinator may reassign (history kept), resume to re-investigate, escalate or cancel."""
        _require(isinstance(reason, str) and reason.strip(), "declining work requires a reason")
        digest = self._request_digest("decline_work", assignment_id, actor, reason=reason.strip())
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            if self._replay(conn, incident.id, request_key, digest) is not None:
                return incident
            self.repository._check(incident, expected_revision)
            authorize(actor.kind, incident)
            state = self._work_guard(conn, incident, assignment_id)
            _require(state["state"] == "ASSIGNED",
                     f"only an unacknowledged assignment can be declined; it is {state['state']} "
                     "(report NOT_PERFORMED after acknowledging)" if state["state"] == "ACKNOWLEDGED"
                     else f"work assignment is already {state['state']}")
            return self._checkpoint(conn, incident, events=[("WORK_DECLINED", {
                "assignment_id": assignment_id, "actor": actor.public(), "reason": reason.strip(),
                **self._keyed(request_key, digest)})])

    def report_work(self, incident_id: str, *, assignment_id: str, expected_revision: int, actor: m.ActorRef,
                    result: m.WorkResult, summary: str, findings: tuple[str, ...] = (), performed_at=None,
                    provenance: Literal["OBSERVED", "SIMULATED"] = "OBSERVED", asset_intervened: bool | None = None,
                    completed_instructions: tuple[int, ...] | None = None,
                    request_key: str | None = None) -> m.WorkReport:
        """The assignee reports the work. Requires acknowledgement first; never verification.

        Malformed or contradictory reports are refused and write nothing. A well-formed
        report is recorded exactly once per assignment; whether it may open outcome
        verification is decided by ``work_eligibility`` (operon-work-eligibility-1) and
        recorded on the WORK_REPORTED event. The report's ``created_at`` (server time) is
        the observation boundary; ``performed_at`` is the reporter's attributed claim.
        """
        from .actors import refuse_simulated_in_production
        findings = tuple(item.strip() for item in findings if isinstance(item, str) and item.strip())
        digest = self._request_digest(
            "report_work", assignment_id, actor, result=result, summary=summary, findings=findings,
            performed_at=performed_at, provenance=provenance, asset_intervened=asset_intervened,
            completed_instructions=None if completed_instructions is None else tuple(completed_instructions))
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            replay = self._replay(conn, incident.id, request_key, digest)
            if replay is not None:
                return self.promotion._get(conn, incident.id, replay["report_id"], m.WorkReport)
            self.repository._check(incident, expected_revision)
            authorize(actor.kind, incident)
            refuse_simulated_in_production(incident, provenance)
            state = self._work_guard(conn, incident, assignment_id)
            _require(state["state"] == "ACKNOWLEDGED",
                     "work must be acknowledged before it is reported" if state["state"] == "ASSIGNED"
                     else f"work assignment is already {state['state']}")
            assignment = self.promotion._get(conn, incident.id, assignment_id, m.WorkAssignment)
            completed = self._validated_work_report(assignment, result=result, findings=findings,
                                                    performed_at=performed_at, asset_intervened=asset_intervened,
                                                    completed_instructions=completed_instructions)
            report = m.WorkReport(**_identity(incident.id), equipment_ids=assignment.equipment_ids,
                                  assignment_id=assignment.id, result=result, summary=summary, findings=findings,
                                  performed_at=performed_at, actor=actor, provenance=provenance,
                                  asset_intervened=asset_intervened, completed_instructions=completed)
            eligible, reasons = work_eligibility(assignment, report)
            self._checkpoint(conn, incident, [report], events=[("WORK_REPORTED", {
                "assignment_id": assignment.id, "report_id": report.id, "result": result, "actor": actor.public(),
                "provenance": provenance, "asset_intervened": asset_intervened,
                "completed_instructions": None if completed is None else list(completed),
                "performed_at_claimed": performed_at.isoformat() if performed_at else None,
                "eligible": eligible, "eligibility_reasons": list(reasons),
                "eligibility_policy": WORK_ELIGIBILITY_POLICY, **self._keyed(request_key, digest)})])
            return report

    @staticmethod
    def _validated_work_report(assignment, *, result, findings, performed_at, asset_intervened,
                               completed_instructions) -> tuple[int, ...] | None:
        """Refuse malformed or self-contradictory reports; return the resolved completed instructions."""
        total = len(assignment.instructions)
        given = None if completed_instructions is None else tuple(completed_instructions)
        if given is not None:
            _require(all(isinstance(index, int) and not isinstance(index, bool) and 0 <= index < total for index in given)
                     and len(set(given)) == len(given),
                     f"completed_instructions must be distinct indices of the {total} assignment instruction(s)")
        if result == "NOT_PERFORMED":
            _require(asset_intervened is not True, "NOT_PERFORMED contradicts asset_intervened=true")
            _require(not given, "NOT_PERFORMED cannot list completed instructions")
            _require(performed_at is None, "NOT_PERFORMED cannot carry a performed_at time")
            return None
        _require(isinstance(asset_intervened, bool),
                 f"a {result} report must state asset_intervened (whether physical work was performed on the asset)")
        _require(performed_at is not None, "performed work requires performed_at")
        _require(performed_at >= assignment.created_at, "performed_at precedes the work assignment (the dispatch)")
        _require(performed_at <= utcnow() + PERFORMED_AT_SKEW, "performed_at is in the future")
        if result == "COMPLETED":
            _require(given is None or set(given) == set(range(total)),
                     "a COMPLETED report must cover every assignment instruction; report PARTIAL otherwise")
            return tuple(range(total))
        _require(total > 0, "PARTIAL requires assignment instructions to name the completed work")
        _require(bool(given), "a PARTIAL report must name the completed instructions")
        _require(bool(findings), "a PARTIAL report must state the remaining work in findings")
        return tuple(sorted(given))

    def reassign_work(self, incident_id: str, *, assignment_id: str, expected_revision: int, actor: m.ActorRef,
                      rationale: str, assignee_reference: str | None = None,
                      request_key: str | None = None) -> m.WorkAssignment:
        """Issue a new assignment for the same dispatch after the current one was declined or
        reported without qualifying. The superseded assignment and its facts stay as history."""
        from .resources import ResourceUnavailable, require_qualified_technician
        digest = self._request_digest("reassign_work", assignment_id, actor, rationale=(rationale or "").strip(),
                                      assignee_reference=assignee_reference)
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            replay = self._replay(conn, incident.id, request_key, digest)
            if replay is not None:
                return self.promotion._get(conn, incident.id, replay["assignment_id"], m.WorkAssignment)
            self.repository._check(incident, expected_revision)
            authorize(actor.kind, incident)
            state = self._work_guard(conn, incident, assignment_id)
            _require(state["state"] == "DECLINED" or (state["state"] == "REPORTED" and state["eligible"] is False),
                     "only a declined assignment or one whose report does not qualify for verification can be "
                     f"reassigned; it is {state['state']}" + (" and its report qualifies" if state["eligible"] else ""))
            previous = self.promotion._get(conn, incident.id, assignment_id, m.WorkAssignment)
            assignee = previous.assignee
            if assignee_reference is not None:
                try:
                    require_qualified_technician(conn, previous.equipment_ids[0], assignee_reference)
                except ResourceUnavailable as exc:
                    _require(False, f"assignee {assignee_reference} cannot take this work: {exc}")
                assignee = m.WorkAssignee(kind="WORKER", reference=assignee_reference,
                                          reference_system="operon.local.technician_roster")
            receipt = self.repository._receipt(conn, incident.id, previous.receipt_id)
            assignment = self._work_assignment(conn, incident, receipt, assignee=assignee, supersedes=previous.id)
            self._command(conn, incident, command="reassign_work", actor=actor, rationale=rationale,
                          artifacts=[assignment], extra={"from_assignment_id": previous.id, "assignment_id": assignment.id},
                          events=[("WORK_REASSIGNED", {
                              "from_assignment_id": previous.id, "assignment_id": assignment.id,
                              "previous_state": state["state"], "actor": actor.public(),
                              "rationale": (rationale or "").strip(), **self._keyed(request_key, digest)}),
                                  ("WORK_ASSIGNED", {
                              "assignment_id": assignment.id, "receipt_id": receipt.id,
                              "supersedes_assignment_id": previous.id,
                              "assignee": assignment.assignee.model_dump(mode="json", exclude={"schema_version"}),
                              "delivery_channel": assignment.delivery_channel,
                              "external_refs": assignment.external_refs})])
            return assignment

    def _resume_observing(self, conn, incident, *, actor: m.ActorRef, rationale: str) -> m.Incident:
        """Narrow F1.2 resume from OBSERVING: only when no observation can start for this dispatch."""
        legacy = self._legacy_verification(conn, incident)
        if legacy is None:
            current = self._current_work(conn, incident)
            _require(current is not None and (current["state"] == "DECLINED"
                                              or (current["state"] == "REPORTED" and current["eligible"] is False)),
                     "resume from OBSERVING is allowed only after the current work was declined or reported without "
                     "qualifying, or for a blocked pre-version-2 case; otherwise report the work, escalate or cancel")
        extra = {"work": self._work_disposition(conn, incident)}
        if legacy is not None:
            extra["legacy_verification"] = legacy
        return self._command(conn, incident, command="resume", actor=actor, rationale=rationale,
                             phase=m.IncidentPhase.INVESTIGATING, current_intervention_id=None, extra=extra)

    # ------------------------------------------------------ plant actuation (F1.2)
    # The engine asks the PlantActuator to respond to an eligible report, outside any
    # transaction, then records what the actuator did. These records describe the
    # (simulated) plant; outcome verification never reads them.
    def _eligible_reports(self, conn, incident_id) -> list[m.WorkReport]:
        assignments = {item.id: item for item in self._all(conn, incident_id, m.WorkAssignment)}
        return [item for item in self._all(conn, incident_id, m.WorkReport)
                if item.assignment_id in assignments and work_eligibility(assignments[item.assignment_id], item)[0]]

    def pending_actuations(self, incident_id: str) -> list[m.WorkReport]:
        """Eligible work reports whose plant effect has not been recorded yet (replayed after a restart)."""
        with db.get_conn(self.repository.path) as conn:
            recorded = {item.report_id for item in self._all(conn, incident_id, m.PlantActuation)}
            return [item for item in self._eligible_reports(conn, incident_id) if item.id not in recorded]

    def dispatch_actuated(self, incident_id: str) -> bool:
        """Whether the plant applied the eligible work of the case's current dispatch (sandbox fact)."""
        with db.get_conn(self.repository.path) as conn:
            incident = self.repository._fetch(conn, incident_id)
            receipt = self._dispatch_receipt(conn, incident)
            if receipt is None:
                return False
            assignments = {item.id for item in self._all(conn, incident.id, m.WorkAssignment)
                           if item.receipt_id == receipt.id}
            return any(item.status == "APPLIED" and item.assignment_id in assignments
                       for item in self._all(conn, incident.id, m.PlantActuation))

    def record_actuation(self, incident_id: str, *, report_id: str, result) -> m.PlantActuation:
        """Record what the actuator did for one eligible report. Idempotent per report (index 009).

        A SYSTEM fact about the plant, recorded whatever the case's phase now is: the
        work was reported performed, so the plant's response is part of its history.
        """
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            existing = [item for item in self._all(conn, incident.id, m.PlantActuation) if item.report_id == report_id]
            if existing:
                return existing[0]
            report = self.promotion._get(conn, incident.id, report_id, m.WorkReport)
            assignment = self.promotion._get(conn, incident.id, report.assignment_id, m.WorkAssignment)
            _require(work_eligibility(assignment, report)[0], "only an eligible work report actuates the plant")
            _require(result.cause == "WORK_PERFORMED" and result.equipment_id in report.equipment_ids,
                     "actuation result does not belong to this work report")
            actuation = m.PlantActuation(
                **_identity(incident.id), equipment_ids=report.equipment_ids, report_id=report.id,
                assignment_id=report.assignment_id, status=result.status, actuator=result.actuator,
                actuator_kind=result.actuator_kind, work_result=report.result, response_profile=result.response_profile,
                mode_before=result.mode_before, mode_after=result.mode_after,
                provenance="SIMULATED" if result.applied else None, reason=result.reason)
            self._checkpoint(conn, incident, [actuation], events=[("PLANT_ACTUATION_RECORDED", {
                "actuation_id": actuation.id, "report_id": report.id, "assignment_id": report.assignment_id,
                "status": actuation.status, "actuator": actuation.actuator, "actuator_kind": actuation.actuator_kind,
                "mode_before": actuation.mode_before, "mode_after": actuation.mode_after,
                "response_profile": actuation.response_profile, "provenance": actuation.provenance,
                "actor": m.ActorRef(kind="SYSTEM", id="operon.plant-actuator").public()})])
            return actuation

    def record_actuation_failure(self, incident_id: str, *, report_id: str, error: str) -> None:
        """The actuator raised: nothing about the plant may be assumed; the report stays pending (replayed at restart)."""
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            self._checkpoint(conn, incident, events=[("PLANT_ACTUATION_FAILED", {
                "report_id": report_id, "error": (error or "")[:400],
                "actor": m.ActorRef(kind="SYSTEM", id="operon.plant-actuator").public()})])

    def _plant_view(self, conn, incident_id) -> dict:
        actuations = self._all(conn, incident_id, m.PlantActuation)
        recorded = {item.report_id for item in actuations}
        failures = [{"report_id": payload.get("report_id"), "error": payload.get("error"), "at": created_at}
                    for created_at, payload in ((row[0], json.loads(row[1])) for row in conn.execute(
                        "SELECT created_at,payload_json FROM incident_event WHERE incident_id=? "
                        "AND event_type='PLANT_ACTUATION_FAILED' ORDER BY event_id", (incident_id,)))]
        return {"actuations": [{"actuation_id": item.id, "report_id": item.report_id, "status": item.status,
                                "cause": item.cause, "actuator_kind": item.actuator_kind, "work_result": item.work_result,
                                "response_profile": item.response_profile, "mode_before": item.mode_before,
                                "mode_after": item.mode_after, "provenance": item.provenance, "reason": item.reason,
                                "recorded_at": item.created_at.isoformat()} for item in actuations],
                "pending_report_ids": [item.id for item in self._eligible_reports(conn, incident_id)
                                       if item.id not in recorded],
                "failures": [item for item in failures if item["report_id"] not in recorded]}

    def _legacy_verification(self, conn, incident) -> dict | None:
        """D4: classify an OBSERVING case whose dispatch cannot be verified under operon-outcome-2.

        Derived on every read from durable records; nothing is rewritten, upgraded or
        closed. ``LEGACY_RECEIPT_BOUND_PLAN``: verification of this dispatch already began
        under operon-outcome-1 from the receipt (one plan per receipt, migration 007, so
        no work-bound plan can be attached). ``LEGACY_NO_WORK_ASSIGNMENT``: the dispatch
        predates work assignments, so no work evidence can ever be attached to it. Both
        are BLOCKED; the supported operator actions are resume, escalate and cancel.
        """
        if incident.phase != m.IncidentPhase.OBSERVING:
            return None
        receipt = self._dispatch_receipt(conn, incident)
        if receipt is None:
            return None
        allowed = ["resume", "escalate", "cancel"]
        plans = [item for item in self._all(conn, incident.id, m.ObservationPlan) if item.receipt_id == receipt.id]
        if plans and plans[0].policy_version == m.OUTCOME_POLICY_V1:
            return {"code": "LEGACY_RECEIPT_BOUND_PLAN", "policy_version": m.OUTCOME_POLICY_V1, "plan_id": plans[0].id,
                    "receipt_id": receipt.id, "allowed_commands": allowed,
                    "reason": "verification of this dispatch began under operon-outcome-1 from the dispatch receipt, "
                              "without work evidence; it is not evaluated again and work reports cannot be attached to "
                              "it. Resume (re-investigate), escalate or cancel the case"}
        if not any(item.receipt_id == receipt.id for item in self._all(conn, incident.id, m.WorkAssignment)):
            return {"code": "LEGACY_NO_WORK_ASSIGNMENT", "policy_version": m.OUTCOME_POLICY_V1, "plan_id": None,
                    "receipt_id": receipt.id, "allowed_commands": allowed,
                    "reason": "this dispatch predates work assignments (operon-outcome-1 era); no work evidence can be "
                              "attached to it, so it cannot be verified. Resume (re-investigate), escalate or cancel the case"}
        return None

    def _post_scores(self, conn, asset_id, start) -> tuple[int, str | None]:
        row = conn.execute("SELECT COUNT(*) AS n, MAX(scored_at) AS latest FROM health_score "
                           "WHERE equipment_id=? AND scored_at>=?", (asset_id, start.isoformat())).fetchone()
        return int(row["n"]), row["latest"]

    def _verification_view(self, conn, incident, status: "LifecycleStatus", now) -> dict:
        """What verification is actually doing for the latest confirmed dispatch (derived, never authority).

        AWAITING_WORK and WORK_NOT_PERFORMED mean nothing is being observed: they are
        not "verifying". COLLECTING/EVALUATING observe post-report scores only.
        """
        from .outcome import MAX_POST_SCORES, MIN_POST_SCORES
        view = {"state": "NOT_STARTED", "code": None, "reason": None, "policy_version": None, "plan_id": None,
                "work_assignment_id": None, "work_report_id": None, "observation_start": None, "post_score_count": 0,
                "minimum_scores": MIN_POST_SCORES, "maximum_scores": MAX_POST_SCORES, "latest_score_at": None,
                "stalled": False, "outcome_id": None, "allowed_commands": []}
        confirmed = [item for item in self._receipts(conn, incident.id) if item.status == "CONFIRMED"]
        if not confirmed:
            return view
        receipt = confirmed[-1]
        plans = [item for item in self._all(conn, incident.id, m.ObservationPlan) if item.receipt_id == receipt.id]
        plan = plans[0] if plans else None
        outcomes = [item for item in self._all(conn, incident.id, m.Outcome) if plan and item.plan_id == plan.id]
        if plan is not None:
            view.update(plan_id=plan.id, policy_version=plan.policy_version, work_assignment_id=plan.work_assignment_id,
                        work_report_id=plan.work_report_id, observation_start=plan.observation_start.isoformat())
        if outcomes:
            outcome = outcomes[-1]
            return {**view, "state": outcome.result, "outcome_id": outcome.id, "reason": outcome.reason,
                    "policy_version": outcome.policy_version,
                    "post_score_count": int(outcome.after_metrics.get("post_score_count", 0)),
                    "latest_score_at": outcome.observation_end.isoformat()}
        if incident.phase != m.IncidentPhase.OBSERVING:
            return {**view, "state": "ENDED_WITHOUT_OUTCOME",
                    "reason": f"the case left OBSERVING ({incident.phase.value}) before any verified outcome"}
        legacy = self._legacy_verification(conn, incident)
        if legacy is not None:
            return {**view, "state": "BLOCKED", "code": legacy["code"], "reason": legacy["reason"],
                    "policy_version": legacy["policy_version"], "plan_id": legacy["plan_id"],
                    "allowed_commands": legacy["allowed_commands"]}
        if not status.execution_lineage_valid:
            return {**view, "state": "BLOCKED", "code": "LINEAGE_INVALID", "reason": status.execution_lineage_reason,
                    "allowed_commands": ["escalate", "cancel"]}
        work = self._qualifying_work(conn, incident, receipt)
        if plan is None and work is None:
            current = self._current_work(conn, incident)
            not_performed = current is not None and (current["state"] == "DECLINED" or (
                current["state"] == "REPORTED" and current["eligible"] is False))
            if not_performed:
                why = (f"declined: {current['decline_reason']}" if current["state"] == "DECLINED"
                       else "report does not qualify: " + ", ".join(current["eligibility_reasons"]))
                return {**view, "state": "WORK_NOT_PERFORMED", "code": "WORK_NOT_PERFORMED",
                        "work_assignment_id": current["assignment_id"], "work_report_id": current["report_id"],
                        "reason": f"no observation can start ({why})",
                        "allowed_commands": ["reassign_work", "resume", "escalate", "cancel"]}
            waiting = "acknowledgement" if current is None or current["state"] == "ASSIGNED" else "a work report"
            return {**view, "state": "AWAITING_WORK", "code": "AWAITING_WORK",
                    "work_assignment_id": current["assignment_id"] if current else None,
                    "reason": f"dispatch confirmed; waiting for {waiting}. Nothing is observed until eligible work is reported",
                    "allowed_commands": ["escalate", "cancel"]}
        assignment, report = work if work is not None else (None, None)
        start = plan.observation_start if plan is not None else _observation_start(report.created_at)
        asset_id = plan.asset_id if plan is not None else assignment.equipment_ids[0]
        count, latest = self._post_scores(conn, asset_id, start)
        reference = datetime.fromisoformat(latest) if latest else start
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=start.tzinfo)
        return {**view, "state": "COLLECTING" if count < MIN_POST_SCORES else "EVALUATING",
                "work_assignment_id": view["work_assignment_id"] or assignment.id,
                "work_report_id": view["work_report_id"] or report.id, "observation_start": start.isoformat(),
                "post_score_count": count, "latest_score_at": latest, "stalled": now - reference > VERIFICATION_STALL_AFTER,
                "reason": f"observing post-work scores: {count} since {start.isoformat()} "
                          f"(policy needs {MIN_POST_SCORES}, at most {MAX_POST_SCORES})",
                "allowed_commands": ["escalate", "cancel"]}

    # ----------------------------------------------------------------- outcome
    def verify_outcome(self, incident_id: str, *, evidence_service=None) -> OutcomeVerification:
        """OBSERVING -> deterministic outcome verification; the only route to CLOSED.

        Requires OBSERVING, binds the exact executed lineage (promoted intervention,
        diagnosis lineage, approval, CONFIRMED claim and receipt), freezes or loads
        the observation plan, collects durable post-intervention evidence outside any
        lock, evaluates the versioned policy, and commits the authoritative Outcome
        together with the phase change: CLOSED (VERIFIED_RECOVERY), INVESTIGATING
        (NOT_RECOVERED), ESCALATED (REGRESSED); INCONCLUSIVE stays OBSERVING and
        writes no outcome. Repeated and concurrent calls are idempotent.
        """
        return OutcomeVerifier(self, evidence_service).verify(incident_id)

    # ---------------------------------------------------------------- recovery
    def _status(self, conn, incident) -> LifecycleStatus:
        intervention_hash = promotion_id = reason = executed_reason = None
        approval = None
        valid = executed_valid = False
        plan = outcome = None
        observed = incident.phase in {m.IncidentPhase.OBSERVING, m.IncidentPhase.CLOSED}
        if incident.current_intervention_id:
            try:
                intervention, record = self._authority(conn, incident)
                valid, promotion_id, intervention_hash = True, record.id, artifact_hash(intervention)
                requirement = self._current_requirement(conn, incident, intervention)
                approval = self._approval_state(conn, incident, requirement) if requirement else None
            except AuthorityRefused as exc:
                reason = str(exc)
            if observed:
                # After execution the exact executed lineage is what outcome
                # verification binds; post-intervention evidence legitimately postdates
                # the diagnosis promotion, so it is reported separately from
                # approval/execution authority rather than replacing it.
                verifier = OutcomeVerifier(self)
                try:
                    lineage = verifier._executed(conn, incident)
                    executed_valid = True
                    promotion_id, intervention_hash = lineage.record.id, lineage.intervention_hash
                    approval = approval or self._approval_state(conn, incident, lineage.requirement)
                    plan = verifier._plan_for(conn, incident, lineage.receipt.id)
                except AuthorityRefused as exc:
                    executed_reason = str(exc)
        if plan is not None:
            outcome = OutcomeVerifier(self)._outcome_for(conn, incident, plan.id)
        elif observed or not incident.current_intervention_id:
            outcomes = self._all(conn, incident.id, m.Outcome)
            outcome = outcomes[-1] if outcomes else None
        claims = self._claims_for(conn, incident.id, incident.current_intervention_id) if incident.current_intervention_id else []
        latest = claims[-1] if claims else None
        receipts = self._receipts(conn, incident.id)
        # An outcome that exists while still OBSERVING was not committed by the verifier
        # with its phase change: never treated as closure, always flagged. F1.2 (D4): a
        # pre-version-2 dispatch that can no longer be verified is flagged the same way.
        stray_outcome = incident.phase == m.IncidentPhase.OBSERVING and outcome is not None
        stray_outcome = stray_outcome or self._legacy_verification(conn, incident) is not None
        return LifecycleStatus(
            incident_id=incident.id, phase=incident.phase, revision=incident.revision,
            diagnosis_id=incident.current_diagnosis_id, intervention_id=incident.current_intervention_id,
            intervention_hash=intervention_hash, promotion_id=promotion_id, authority_valid=valid, authority_reason=reason,
            approval=approval, claim_state=latest.state if latest else None,
            claim_started_at=latest.started_at.isoformat() if latest else None,
            receipt_ids=tuple(item.id for item in receipts),
            reconciliation_required=bool(latest and latest.state in {"UNKNOWN", "IN_FLIGHT"}) or stray_outcome,
            execution_lineage_valid=executed_valid, execution_lineage_reason=executed_reason,
            plan_id=plan.id if plan else None, outcome_id=outcome.id if outcome else None,
            outcome_result=outcome.result if outcome else None)

    def status(self, incident_id: str) -> LifecycleStatus:
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            return self._status(conn, self.repository._fetch(conn, incident_id))

    def recover(self) -> list[LifecycleStatus]:
        """Reconstruct every active incident from durable pointers; never dispatch, never verify.

        An OBSERVING incident stays OBSERVING: its execution lineage and any plan or
        post-intervention evidence are durable, so verification can resume through an
        explicit ``verify_outcome`` call. A receipt alone never becomes an outcome
        here, and CLOSED incidents (already inactive) are final.
        """
        return [self.reconcile(incident.id) for incident in self.repository.list_active_incidents()]

    def verification(self, incident_id: str, *, now=None) -> dict:
        """The derived verification sub-state alone (cheap; the engine polls it while observing)."""
        status = self.status(incident_id)
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            return self._verification_view(conn, self.repository._fetch(conn, incident_id), status, now or utcnow())

    @staticmethod
    def _work_view(states: list[dict], now) -> list[dict]:
        """Work facts plus derived attention flags (D9: flags only, never a transition)."""
        def at(value):
            return None if value is None else datetime.fromisoformat(value)
        view = []
        for state in states:
            ack_due = at(state["assigned_at"]) + WORK_ACK_GRACE
            report_due = at(state["window_end"]) or ((at(state["acknowledged_at"]) or ack_due) + WORK_REPORT_GRACE)
            view.append({**state, "ack_due_at": ack_due.isoformat(), "report_due_at": report_due.isoformat(),
                         "ack_overdue": bool(state["current"] and state["state"] == "ASSIGNED" and now > ack_due),
                         "report_overdue": bool(state["current"] and state["state"] == "ACKNOWLEDGED" and now > report_due)})
        return view

    def projection(self, incident_id: str, *, now=None, actuator_kind: str | None = None) -> dict[str, JsonValue]:
        """UI/API view of durable state. Contains no authority; approval needs exact identifiers.

        ``now`` (default: the server clock) only drives derived attention flags;
        ``actuator_kind`` is the engine's plant actuator ("simulator" / "none"), if known.
        """
        now = now or utcnow()
        status = self.status(incident_id)
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            verification = self._verification_view(conn, self.repository._fetch(conn, incident_id), status, now)
            plant = {"actuator": actuator_kind, **self._plant_view(conn, incident_id)}
        incident = self.repository.fetch_incident(incident_id)
        requirement = None
        if status.approval and status.approval.state == "PENDING":
            requirement = self.repository.get_artifact(incident_id, status.approval.requirement_id)
        return {
            **status.model_dump(mode="json"),
            "equipment_ids": list(incident.equipment_ids), "severity": incident.severity,
            "requirement": None if requirement is None else {
                "requirement_id": requirement.id, "intervention_id": requirement.intervention_id,
                "intervention_hash": requirement.intervention_hash, "expires_at": requirement.expires_at.isoformat(),
                "required_roles": list(requirement.required_roles), "conditions": list(requirement.conditions),
                "context_revision": incident.revision,
                "material_uncertainties": [item.model_dump(mode="json", exclude={"schema_version"})
                                           for item in requirement.material_uncertainties or ()],
            },
            # F1 additions: all descriptive, none of them authority.
            "environment": incident.environment,
            "analysis": None if incident.analysis is None else incident.analysis.model_dump(
                mode="json", exclude={"schema_version"}),
            "hypotheses": [{"reference": item.reference, "status": item.status, "mechanism": item.mechanism,
                            "hypothesis_id": item.id, "link_basis": item.link_basis}
                           for item in sorted(self.promotion.current_hypotheses(incident_id).values(),
                                              key=lambda value: value.reference)],
            "work": self._work_view(self.work_status(incident_id), now),
            # F1.2: what verification is actually doing; AWAITING_WORK is not "verifying".
            "verification": verification,
            # F1.2: what the plant actuator did for eligible reports (simulated plant facts; never evidence).
            "plant": plant,
        }


def receipt_content(receipt: m.ExecutionReceipt) -> dict:
    """Consequential receipt content: everything except RECEIPT_REGENERATED_FIELDS."""
    return receipt.model_dump(mode="json", exclude=set(RECEIPT_REGENERATED_FIELDS))


def claim_started_revision(conn, incident_id, key) -> int | None:
    """Revision recorded by the claim event; used only for audit metadata."""
    row = conn.execute("SELECT revision FROM incident_event WHERE incident_id=? AND event_type='EXECUTION_CLAIMED' "
                       "AND json_extract(payload_json,'$.idempotency_key')=? ORDER BY event_id DESC LIMIT 1",
                       (incident_id, key)).fetchone()
    return row[0] if row else None
