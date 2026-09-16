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
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from core import db
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
from .outcome import OutcomeVerification, OutcomeVerifier
from .promotion import CONFIRM_MECHANISM, POLICY_VERSION as PROMOTION_POLICY, PromotionRefused, PromotionService
from .repository import (
    IncidentRepository, InvalidReference, StaleRevision, content_hash, manifest_authority, new_id, utcnow,
)
from .state import validate_transition

POLICY_VERSION = "operon-lifecycle-1"
BOUNDARY = "operon.application.lifecycle"
APPROVER_ROLE = "maintenance_approver"
APPROVAL_TTL = timedelta(hours=24)
# Fields a re-delivered completion callback legitimately regenerates: the artifact
# identity and the moments it was materialised. Every other receipt field (claim
# identity, attempt, status, adapter, executor, external_ids, error_code/message,
# attempted_at) is consequential content and defines semantic equality.
RECEIPT_REGENERATED_FIELDS = frozenset({"id", "created_at", "completed_at"})


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


class StageOutcome(BaseModel):
    """Result of one application-driven reasoning stage; never authority by itself."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal["DIAGNOSIS", "INTERVENTION_REVIEW"]
    disposition: Literal["PROMOTED", "NEEDS_EVIDENCE", "ESCALATED", "RETRY", "APPROVAL_REQUESTED", "GOVERNANCE_BLOCKED"]
    phase: m.IncidentPhase
    revision: int
    reason: str
    report_id: str | None = None
    promotion_id: str | None = None
    draft_id: str | None = None
    requirement_id: str | None = None


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
    def _settle(self, incident_id, report, stage):
        """Classify a durable report deterministically. Returns (disposition, reason)."""
        if report.stale_reasons:
            return "RETRY", "run inputs changed during reasoning: " + ", ".join(report.stale_reasons)
        result = SupervisorResult.model_validate(report.result_payload)
        if report.completion != "MODEL_COMPLETED" or result.exhausted_limits or result.invalid_output:
            failure = next((item for item in result.blockers if item.startswith("Model invocation failed")), None)
            return "ESCALATED", (f"supervisor run terminated with {report.completion}"
                                 + (f": {failure}" if failure else ""))
        if result.disposition in {"BLOCKED", "ESCALATED"}:
            return "ESCALATED", f"supervisor disposition {result.disposition}: " + "; ".join(result.blockers[:3])
        if result.disposition in {"UNRESOLVED", "NEEDS_EVIDENCE"} or result.unresolved_evidence_needs:
            return "NEEDS_EVIDENCE", f"supervisor disposition {result.disposition}"
        return "PROMOTE", "advisory conclusion ready for application gates"

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

    async def diagnose(self, incident_id: str, *, asset_id: str, runtime, evidence_service,
                       specialist_runtime=None, bounds=None, confirmation_id: str | None = None) -> StageOutcome:
        """INVESTIGATING -> durable supervisor run -> application diagnosis gates.

        Only PromotionService.promote_diagnosis creates authority. NEEDS_EVIDENCE
        parks the incident in AWAITING_EVIDENCE; failed/blocked runs escalate.
        """
        incident = self.repository.fetch_incident(incident_id)
        _require(incident.phase == m.IncidentPhase.INVESTIGATING, "diagnosis requires INVESTIGATING")
        self.refresh_baseline_evidence(incident_id, asset_id, evidence_service)
        incident = self.repository.fetch_incident(incident_id)
        evidence_ids = self.current_evidence_ids(incident_id, asset_id)
        try:
            report = await self.promotion.run_supervisor(
                incident_id, service=evidence_service, runtime=runtime, specialist_runtime=specialist_runtime,
                asset_id=asset_id, stage="DIAGNOSIS", expected_revision=incident.revision,
                evidence_ids=evidence_ids, bounds=bounds)
        except PromotionRefused as exc:
            return self._outcome(incident_id, "DIAGNOSIS", "RETRY" if exc.disposition != "NEEDS_EVIDENCE" else "NEEDS_EVIDENCE",
                                 f"run could not start: {exc}")
        disposition, reason = self._settle(incident_id, report, "DIAGNOSIS")
        if disposition == "PROMOTE":
            if confirmation_id is None:
                confirmations = [key for key in report.evidence_manifest
                                 if getattr(self.repository.get_artifact(incident_id, key), "source_capability", None) == CONFIRM_MECHANISM]
                confirmation_id = confirmations[-1] if confirmations else None
            if confirmation_id is None:
                disposition, reason = "NEEDS_EVIDENCE", "trusted technical confirmation has not been supplied"
            else:
                try:
                    promotion = self.promotion.promote_diagnosis(
                        incident_id, report_id=report.id, confirmation_id=confirmation_id,
                        expected_revision=report.checkpoint_revision)
                    return self._outcome(incident_id, "DIAGNOSIS", "PROMOTED", "application promoted the diagnosis",
                                         report_id=report.id, promotion_id=promotion.id)
                except PromotionRefused as exc:
                    if exc.disposition == "NEEDS_EVIDENCE":
                        disposition, reason = "NEEDS_EVIDENCE", str(exc)
                    elif self._refusal_is_stale(incident_id, report):
                        disposition, reason = "RETRY", f"promotion inputs changed: {exc}"
                    else:
                        disposition, reason = "ESCALATED", f"application diagnosis gate failed: {exc}"
        if disposition == "NEEDS_EVIDENCE":
            self._transition(incident_id, m.IncidentPhase.AWAITING_EVIDENCE, reason)
        elif disposition == "ESCALATED":
            self._transition(incident_id, m.IncidentPhase.ESCALATED, reason)
        return self._outcome(incident_id, "DIAGNOSIS", disposition, reason, report_id=report.id)

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
        try:
            report = await self.promotion.run_supervisor(
                incident_id, service=evidence_service, runtime=runtime, specialist_runtime=specialist_runtime,
                asset_id=draft.steps[0].equipment_ids[0], stage="INTERVENTION_REVIEW", expected_revision=incident.revision,
                evidence_ids=draft.evidence_ids, draft_id=draft.id, bounds=bounds)
        except PromotionRefused as exc:
            return self._outcome(incident_id, "INTERVENTION_REVIEW", "RETRY" if exc.disposition != "NEEDS_EVIDENCE" else "NEEDS_EVIDENCE",
                                 f"review could not start: {exc}", draft_id=draft.id)
        disposition, reason = self._settle(incident_id, report, "INTERVENTION_REVIEW")
        promotion = None
        if disposition == "PROMOTE":
            try:
                promotion = self.promotion.promote_intervention(
                    incident_id, report_id=report.id, draft_id=draft.id, expected_revision=report.checkpoint_revision)
            except PromotionRefused as exc:
                if exc.disposition == "NEEDS_EVIDENCE":
                    disposition, reason = "NEEDS_EVIDENCE", str(exc)
                elif self._refusal_is_stale(incident_id, report):
                    disposition, reason = "RETRY", f"promotion inputs changed: {exc}"
                else:
                    disposition, reason = "ESCALATED", f"application intervention gate failed: {exc}"
        if disposition == "ESCALATED":
            self._transition(incident_id, m.IncidentPhase.ESCALATED, reason)
        if promotion is None:
            # Evidence needs discovered at planning stay in PLANNING: a new trusted
            # binding/draft is required; no authority exists yet to invalidate.
            return self._outcome(incident_id, "INTERVENTION_REVIEW", disposition, reason, report_id=report.id, draft_id=draft.id)
        incident = self.repository.fetch_incident(incident_id)
        try:
            requirement = self.request_approval(incident_id, expected_revision=incident.revision)
        except GovernanceBlocked as exc:
            self._transition(incident_id, m.IncidentPhase.ESCALATED, f"governance blocked: {exc}")
            return self._outcome(incident_id, "INTERVENTION_REVIEW", "GOVERNANCE_BLOCKED", str(exc),
                                 report_id=report.id, promotion_id=promotion.id, draft_id=draft.id)
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
            requirement = m.ApprovalRequirement(
                **_identity(incident.id), intervention_id=intervention.id, intervention_hash=artifact_hash(intervention),
                policy_version=POLICY_VERSION, mode="HUMAN", required_roles=(APPROVER_ROLE,), minimum_distinct_approvers=1,
                conditions=governance.reasons, expires_at=expires, promotion_id=record.id,
                supersedes_id=existing.id if existing is not None else None)
            self._checkpoint(conn, incident, [requirement], phase=m.IncidentPhase.AWAITING_APPROVAL,
                             reason="deterministic governance requires human approval",
                             events=[("APPROVAL_REQUESTED", {
                                 "requirement_id": requirement.id, "intervention_id": intervention.id,
                                 "intervention_hash": requirement.intervention_hash, "promotion_id": record.id,
                                 "policy_version": POLICY_VERSION, "governance": governance.model_dump(mode="json")})])
            return requirement

    def decide_approval(self, incident_id: str, *, requirement_id: str, intervention_id: str, intervention_hash: str,
                        context_revision: int, actor_id: str, actor_role: str,
                        decision: Literal["APPROVE", "REJECT"], rationale: str) -> m.ApprovalDecision:
        """Atomic: exact decision + AWAITING_APPROVAL -> READY (APPROVE) or ESCALATED (REJECT).

        Approval authorizes an exact, currently promoted intervention. It never
        validates a diagnosis or intervention and never overrides governance.
        """
        _require(actor_id.strip() and actor_role.strip() and rationale.strip(),
                 "approval actor, role and rationale are required", error=ApprovalRefused)
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
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
                rationale=rationale, context_revision=incident.revision, promotion_id=record.id)
            self.repository._validate_references(conn, incident, record_decision)
            conn.execute("INSERT INTO approval_decision VALUES (?,?,?,?,?,?,?)",
                         (record_decision.id, incident.id, record_decision.intervention_id, record_decision.intervention_hash,
                          record_decision.actor_id, record_decision.created_at.isoformat(), record_decision.model_dump_json()))
            target = m.IncidentPhase.READY if decision == "APPROVE" else m.IncidentPhase.ESCALATED
            self._checkpoint(conn, incident, phase=target,
                             reason=("exact human approval recorded" if decision == "APPROVE"
                                     else "human rejected the promoted intervention; reconciliation required"),
                             events=[("APPROVAL_RECORDED", {
                                 "decision_id": record_decision.id, "decision": decision, "requirement_id": requirement.id,
                                 "intervention_id": intervention.id, "intervention_hash": current_hash,
                                 "promotion_id": record.id, "actor_id": actor_id})])
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
            if incident.phase != m.IncidentPhase.EXECUTING:
                # Reality is recorded; the phase left EXECUTING through another explicit
                # command, so the application flags reconciliation instead of guessing.
                events.append(("INCIDENT_UPDATED", {"reconciliation": "receipt recorded outside EXECUTING",
                                                     "phase": incident.phase.value, "receipt_id": receipt.id}))
                return self._checkpoint(conn, incident, events=events)
            return self._checkpoint(conn, incident, phase=target, events=events,
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

    def retry_execution(self, incident_id: str, *, expected_revision: int) -> m.Incident:
        """EXECUTION_FAILED -> READY only after a definitive FAILED claim; UNKNOWN never replays."""
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            self.repository._check(incident, expected_revision)
            _require(incident.phase == m.IncidentPhase.EXECUTION_FAILED, "retry requires EXECUTION_FAILED",
                     error=ExecutionRefused)
            intervention, *_ = self._eligibility(conn, incident, incident.current_intervention_id, None)
            claims = self._claims_for(conn, incident.id, intervention.id)
            _require(all(item.state == "FAILED" for item in claims),
                     "a prior claim is not definitively FAILED; reconciliation is required",
                     error=ReconciliationRequired)
            return self._checkpoint(conn, incident, phase=m.IncidentPhase.READY,
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
        # with its phase change: never treated as closure, always flagged.
        stray_outcome = incident.phase == m.IncidentPhase.OBSERVING and outcome is not None
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

    def projection(self, incident_id: str) -> dict[str, JsonValue]:
        """UI/API view of durable state. Contains no authority; approval needs exact identifiers."""
        status = self.status(incident_id)
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
            },
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
