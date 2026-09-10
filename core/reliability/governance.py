"""Deterministic, application-owned intervention and approval policy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import models as m
from .repository import IncidentRepository, InvalidReference, content_hash, new_id, utcnow


POLICY_VERSION = "operon-execution-1"
AUTO_APPROVE_MAX_COST = 250.0
APPROVAL_TTL_HOURS = 24
DEFAULT_APPROVER_ROLE = "maintenance_approver"


class PolicyDisposition(str, Enum):
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    READY = "READY"


class PolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: PolicyDisposition
    policy_version: str = POLICY_VERSION
    reasons: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    applicable_requirement_id: str | None = None
    applicable_decision_ids: tuple[str, ...] = ()


class ReservedPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    part_id: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    qty: int = Field(ge=1)
    is_critical_spare: bool = True


class WorkPackageParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    equipment_id: str = Field(min_length=1)
    failure_mode_id: str = Field(min_length=1)
    technician_id: str = Field(min_length=1)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    detail: str = Field(min_length=1)
    parts: tuple[ReservedPart, ...]
    window: str = Field(min_length=1)
    window_min: int = Field(gt=0)
    prediction_failure_prob: float = Field(ge=0, le=1)


class NotificationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    recipient_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    channel: Literal["sms", "email", "slack", "dashboard"] = "sms"


@dataclass(frozen=True)
class CapabilityPolicy:
    parameter_model: type[BaseModel] | None
    consequential: bool
    external_commitment: bool
    reversible: bool
    safety_relevant: bool
    executable_now: bool


CAPABILITY_POLICY: dict[str, CapabilityPolicy] = {
    "create_work_package": CapabilityPolicy(WorkPackageParameters, True, True, False, True, True),
    "notify": CapabilityPolicy(NotificationParameters, True, True, False, False, True),
    "inspect": CapabilityPolicy(None, False, False, True, True, False),
    "verify_recovery": CapabilityPolicy(None, False, False, True, True, False),
    "propose_procurement": CapabilityPolicy(None, True, True, False, False, False),
    "raise_quality_case": CapabilityPolicy(None, True, True, True, True, False),
}

POLICY_PHASES = frozenset({
    m.IncidentPhase.INTERVENTION_VALIDATED, m.IncidentPhase.AWAITING_APPROVAL,
    m.IncidentPhase.READY, m.IncidentPhase.EXECUTING, m.IncidentPhase.EXECUTION_FAILED,
})


def artifact_hash(intervention: m.Intervention) -> str:
    return content_hash(intervention.model_dump(mode="json"))


def validate_step_parameters(step: m.InterventionStep) -> BaseModel | None:
    rule = CAPABILITY_POLICY[step.capability]
    if rule.parameter_model is None:
        return None
    return rule.parameter_model.model_validate(step.parameters)


class ExecutionPolicy:
    """Pure policy evaluation over an authoritative snapshot."""

    def evaluate(self, incident: m.Incident, intervention: m.Intervention,
                 artifacts: tuple[m.Artifact, ...] | list[m.Artifact],
                 decisions: tuple[m.ApprovalDecision, ...] | list[m.ApprovalDecision]) -> PolicyEvaluation:
        target_hash = artifact_hash(intervention)
        blockers: list[str] = []
        reasons: list[str] = []

        if intervention.incident_id != incident.id:
            blockers.append("intervention belongs to a different incident")
        if incident.phase not in POLICY_PHASES:
            blockers.append(f"incident phase {incident.phase.value} does not permit execution")
        if intervention.status not in ("VALIDATED", "AWAITING_APPROVAL", "READY", "EXECUTING"):
            blockers.append(f"intervention status {intervention.status} is not validated")
        if intervention.risk == "PROHIBITED":
            blockers.append("intervention risk is prohibited")

        interventions = [a for a in artifacts if isinstance(a, m.Intervention)]
        if any(a.supersedes_id == intervention.id for a in interventions):
            blockers.append("intervention has been superseded")
        if any(a.revision > intervention.revision and a.id != intervention.id for a in interventions):
            blockers.append("intervention is not the current revision")

        verdicts = [a for a in artifacts if isinstance(a, m.ValidationVerdict)
                    and a.target_kind == "intervention" and a.target_id == intervention.id
                    and a.target_hash == target_hash]
        accepted = [v for v in verdicts if v.decision == "ACCEPT" and not v.blocking_issues]
        rejected = [v for v in verdicts if v.decision in ("REJECT", "NEEDS_EVIDENCE") or v.blocking_issues]
        if rejected:
            blockers.extend(issue for verdict in rejected for issue in verdict.blocking_issues)
            blockers.append("current intervention validation does not permit execution")
        elif not accepted:
            blockers.append("current intervention has no accepting validation verdict")

        step_rules: list[CapabilityPolicy] = []
        for step in intervention.steps:
            rule = CAPABILITY_POLICY.get(step.capability)
            if rule is None:
                blockers.append(f"unsupported capability {step.capability}")
                continue
            step_rules.append(rule)
            if not set(step.equipment_ids) <= set(incident.equipment_ids):
                blockers.append(f"step {step.id} exceeds incident equipment scope")
            try:
                validate_step_parameters(step)
            except Exception as exc:
                blockers.append(f"step {step.id} parameters are invalid: {exc}")
            if rule.consequential and not rule.executable_now:
                blockers.append(f"capability {step.capability} has no trusted executor")

        if blockers:
            return PolicyEvaluation(disposition=PolicyDisposition.BLOCKED,
                                    blockers=tuple(dict.fromkeys(blockers)))

        requires_approval = (
            any(r.external_commitment or r.safety_relevant or not r.reversible for r in step_rules)
            or intervention.risk in ("MEDIUM", "HIGH")
            or intervention.estimated_cost > AUTO_APPROVE_MAX_COST
        )
        if not requires_approval:
            return PolicyEvaluation(disposition=PolicyDisposition.READY,
                                    reasons=("low-risk reversible action is within automatic threshold",))

        requirements = [a for a in artifacts if isinstance(a, m.ApprovalRequirement)
                        and a.intervention_id == intervention.id
                        and a.intervention_hash == target_hash
                        and a.policy_version == POLICY_VERSION]
        if not requirements:
            return PolicyEvaluation(disposition=PolicyDisposition.REQUIRES_APPROVAL,
                                    reasons=("action creates a consequential commitment",))
        requirement = requirements[-1]
        now = utcnow()
        if requirement.mode == "PROHIBITED":
            return PolicyEvaluation(disposition=PolicyDisposition.BLOCKED,
                                    blockers=("approval requirement prohibits execution",),
                                    applicable_requirement_id=requirement.id)
        if requirement.expires_at and requirement.expires_at <= now:
            return PolicyEvaluation(disposition=PolicyDisposition.REQUIRES_APPROVAL,
                                    reasons=("approval request expired",),
                                    applicable_requirement_id=requirement.id)

        applicable = [d for d in decisions if d.requirement_id == requirement.id
                      and d.incident_id == incident.id and d.intervention_id == intervention.id
                      and d.intervention_hash == target_hash]
        if any(d.decision == "REJECT" for d in applicable):
            return PolicyEvaluation(disposition=PolicyDisposition.BLOCKED,
                                    blockers=("intervention was rejected",),
                                    applicable_requirement_id=requirement.id,
                                    applicable_decision_ids=tuple(d.id for d in applicable))
        approved = {d.actor_id: d for d in applicable if d.decision == "APPROVE"
                    and (not requirement.required_roles or d.actor_role in requirement.required_roles)}
        if len(approved) < requirement.minimum_distinct_approvers:
            return PolicyEvaluation(disposition=PolicyDisposition.REQUIRES_APPROVAL,
                                    reasons=("required approval has not been recorded",),
                                    applicable_requirement_id=requirement.id,
                                    applicable_decision_ids=tuple(d.id for d in applicable))
        return PolicyEvaluation(disposition=PolicyDisposition.READY,
                                reasons=("exact intervention approval is satisfied",),
                                applicable_requirement_id=requirement.id,
                                applicable_decision_ids=tuple(d.id for d in approved.values()))


class ApprovalLedger:
    """Legacy/compatibility approval commands for non-promoted interventions.

    Since Step 13B, application-promoted interventions are approved only through
    core.reliability.lifecycle.LifecycleService, whose requirement creation and
    decision recording are each atomic with their phase transition. This ledger
    refuses promoted targets so legacy machinery cannot mint authority for them.
    """

    def __init__(self, repository: IncidentRepository, policy: ExecutionPolicy | None = None):
        self.repository = repository
        self.policy = policy or ExecutionPolicy()

    def _refuse_promoted(self, incident_id: str, intervention_id: str) -> None:
        if any(isinstance(item, m.PromotionRecord) and item.target_id == intervention_id
               for item in self.repository.list_artifacts(incident_id)):
            raise PermissionError("promoted interventions use LifecycleService approval commands")

    def evaluate(self, incident_id: str, intervention_id: str) -> PolicyEvaluation:
        incident = self.repository.fetch_incident(incident_id)
        artifact = self.repository.get_artifact(incident_id, intervention_id)
        if not isinstance(artifact, m.Intervention):
            raise InvalidReference("execution target is not an Intervention")
        return self.policy.evaluate(incident, artifact,
                                    self.repository.list_artifacts(incident_id),
                                    self.repository.list_approval_decisions(incident_id,
                                                                            intervention_id=intervention_id))

    def request(self, incident_id: str, intervention_id: str) -> m.ApprovalRequirement | None:
        self._refuse_promoted(incident_id, intervention_id)
        incident = self.repository.fetch_incident(incident_id)
        intervention = self.repository.get_artifact(incident_id, intervention_id)
        if not isinstance(intervention, m.Intervention):
            raise InvalidReference("approval target is not an Intervention")
        artifacts = self.repository.list_artifacts(incident_id)
        evaluation = self.policy.evaluate(incident, intervention, artifacts,
                                          self.repository.list_approval_decisions(incident_id,
                                                                                  intervention_id=intervention_id))
        if evaluation.disposition == PolicyDisposition.BLOCKED:
            raise PermissionError("; ".join(evaluation.blockers))
        if evaluation.disposition == PolicyDisposition.READY:
            return None
        existing = next((a for a in reversed(artifacts) if isinstance(a, m.ApprovalRequirement)
                         and a.intervention_id == intervention.id
                         and a.intervention_hash == artifact_hash(intervention)
                         and a.policy_version == POLICY_VERSION), None)
        if existing:
            return existing
        requirement = m.ApprovalRequirement(
            id=new_id(), incident_id=incident.id, created_at=utcnow(),
            intervention_id=intervention.id, intervention_hash=artifact_hash(intervention),
            policy_version=POLICY_VERSION, mode="HUMAN",
            required_roles=(DEFAULT_APPROVER_ROLE,), minimum_distinct_approvers=1,
            conditions=tuple(evaluation.reasons),
            expires_at=utcnow() + timedelta(hours=APPROVAL_TTL_HOURS),
        )
        incident = self.repository.add_artifact(requirement, expected_revision=incident.revision)
        if incident.phase == m.IncidentPhase.INTERVENTION_VALIDATED:
            self.repository.transition(incident.id, m.IncidentPhase.AWAITING_APPROVAL,
                                       expected_revision=incident.revision,
                                       reason="policy requires human approval")
        return requirement

    def decide(self, incident_id: str, requirement_id: str, *, actor_id: str,
               actor_role: str, decision: Literal["APPROVE", "REJECT"], rationale: str) -> m.ApprovalDecision:
        incident = self.repository.fetch_incident(incident_id)
        requirement = self.repository.get_artifact(incident_id, requirement_id)
        if not isinstance(requirement, m.ApprovalRequirement):
            raise InvalidReference("approval requirement not found")
        self._refuse_promoted(incident_id, requirement.intervention_id)
        if requirement.policy_version != POLICY_VERSION or requirement.mode != "HUMAN":
            raise PermissionError("requirement belongs to the lifecycle approval boundary")
        if not actor_id.strip() or not actor_role.strip() or not rationale.strip():
            raise ValueError("approval actor, role, and rationale are required")
        record = m.ApprovalDecision(
            id=new_id(), incident_id=incident.id, created_at=utcnow(),
            requirement_id=requirement.id, intervention_id=requirement.intervention_id,
            intervention_hash=requirement.intervention_hash, actor_id=actor_id,
            actor_role=actor_role, decision=decision, rationale=rationale,
            context_revision=incident.revision,
        )
        self.repository.add_approval_decision(record, expected_revision=incident.revision)
        return record
