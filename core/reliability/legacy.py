"""DEPRECATED compatibility-only demo shortcut. Not the authoritative path.

Step 13B replaced this with core.reliability.lifecycle.LifecycleService. These
artifacts carry no PromotionRecord, application ValidationVerdict identity, or
authority pointers, so they fail every PromotionService lineage check and are
refused by the lifecycle approval/execution commands. The engine only calls this
when OPERON_LEGACY_DEMO is explicitly enabled; every call emits DeprecationWarning.
"""
from __future__ import annotations

from dataclasses import dataclass
import warnings

from . import models as m
from .governance import ApprovalLedger
from .repository import IncidentRepository, content_hash, new_id, utcnow


@dataclass(frozen=True)
class LegacyIntervention:
    intervention: m.Intervention
    requirement: m.ApprovalRequirement | None


def _identity(incident_id: str) -> dict:
    return {"id": new_id(), "incident_id": incident_id, "created_at": utcnow()}


def prepare_legacy_intervention(repository: IncidentRepository, incident_id: str,
                                proposal: dict) -> LegacyIntervention:
    """Persist only the fields required by the one legacy work-package action.

    The original proposal remains a UI compatibility snapshot. It is never passed
    to execution; this adapter copies its known fields into a validated step schema.
    """
    warnings.warn("prepare_legacy_intervention is deprecated compatibility code; it manufactures no "
                  "application promotion lineage and is not the Operon authoritative path",
                  DeprecationWarning, stacklevel=2)
    incident = repository.fetch_incident(incident_id)
    existing = [a for a in repository.list_artifacts(incident_id)
                if isinstance(a, m.Intervention)]
    if existing:
        intervention = existing[-1]
        requirement = ApprovalLedger(repository).request(incident_id, intervention.id)
        return LegacyIntervention(intervention, requirement)

    if incident.phase == m.IncidentPhase.OPEN:
        incident = repository.transition(incident.id, m.IncidentPhase.INVESTIGATING,
                                         expected_revision=incident.revision,
                                         reason="legacy compatibility investigation")
    evidence_ids = incident.signal_evidence_ids
    hypothesis = m.Hypothesis(
        **_identity(incident.id), equipment_ids=incident.equipment_ids,
        mechanism="legacy model candidate requiring governed maintenance",
        supporting_evidence_ids=evidence_ids, confidence=proposal.get("prediction", {}).get("failure_prob", 0),
        confidence_basis="legacy classifier signal; not calibrated causal confidence",
        falsification_tests=("verify the suspected failure mode during maintenance",),
    )
    incident = repository.add_artifact(hypothesis, expected_revision=incident.revision)
    diagnosis = m.Diagnosis(
        **_identity(incident.id), equipment_ids=incident.equipment_ids,
        hypothesis_ids=(hypothesis.id,), conclusion="legacy compatibility diagnosis",
        failure_mode_code=proposal.get("failure_mode", {}).get("mode_code"),
        evidence_ids=evidence_ids, confidence=hypothesis.confidence, status="ACCEPTED",
    )
    incident = repository.add_artifact(diagnosis, expected_revision=incident.revision)
    diagnosis_verdict = m.ValidationVerdict(
        **_identity(incident.id), target_kind="diagnosis", target_id=diagnosis.id,
        target_hash=content_hash(diagnosis.model_dump(mode="json")),
        input_revision=incident.revision, decision="ACCEPT",
        challenges=("legacy deterministic compatibility path",),
        falsification_attempts=("checked exact persisted classifier evidence binding",),
        evidence_ids=evidence_ids, validator_run_id="operon.legacy.adapter",
    )
    incident = repository.add_artifact(diagnosis_verdict, expected_revision=incident.revision)
    incident = repository.transition(incident.id, m.IncidentPhase.DIAGNOSIS_VALIDATED,
                                     expected_revision=incident.revision,
                                     reason="legacy adapter validation recorded")
    incident = repository.transition(incident.id, m.IncidentPhase.PLANNING,
                                     expected_revision=incident.revision,
                                     reason="legacy proposal adaptation")

    actions = proposal.get("actions") or {}
    work_order = actions.get("work_order") or {}
    schedule = actions.get("schedule") or {}
    technician = actions.get("technician") or {}
    parts = [{
        "part_id": part.get("part_id"), "part_number": part.get("part_number"),
        "qty": int(part.get("qty_per_service") or 1),
        "is_critical_spare": bool(part.get("is_critical_spare")),
    } for part in (actions.get("parts") or {}).get("parts", [])
        if part.get("is_critical_spare")]
    parameters = {
        "equipment_id": proposal.get("equipment_id"),
        "failure_mode_id": (proposal.get("failure_mode") or {}).get("failure_mode_id"),
        "technician_id": technician.get("technician_id"),
        "priority": work_order.get("priority", "HIGH"),
        "detail": work_order.get("detail"),
        "parts": parts,
        "window": schedule.get("window"),
        "window_min": schedule.get("window_min"),
        "prediction_failure_prob": (proposal.get("prediction") or {}).get("failure_prob"),
    }
    business = proposal.get("business") or {}
    exposure = float(business.get("unplanned_loss") or business.get("recovered_value") or 0)
    intervention = m.Intervention(
        **_identity(incident.id), diagnosis_id=diagnosis.id, revision=1,
        steps=(m.InterventionStep(
            id=new_id(), created_at=utcnow(), capability="create_work_package",
            equipment_ids=incident.equipment_ids, parameters=parameters,
            preconditions=tuple((proposal.get("governance") or {}).get("conditions") or ()),
            verification_criteria=("observe post-dispatch equipment behavior",),
        ),), evidence_ids=evidence_ids,
        risk="HIGH" if proposal.get("criticality") == "HIGH" else "MEDIUM",
        estimated_cost=max(0, float(business.get("unplanned_loss") or 0)
                           - float(business.get("recovered_value") or 0)),
        estimated_downtime_minutes=int(schedule.get("window_min") or 0),
        estimated_avoided_loss=exposure,
        business_assumption_version="legacy-demo-1", status="VALIDATED",
    )
    incident = repository.add_artifact(intervention, expected_revision=incident.revision)
    legacy_verdict = proposal.get("governance") or {}
    accepted = legacy_verdict.get("decision") != "VETO"
    intervention_verdict = m.ValidationVerdict(
        **_identity(incident.id), target_kind="intervention", target_id=intervention.id,
        target_hash=content_hash(intervention.model_dump(mode="json")),
        input_revision=incident.revision, decision="ACCEPT" if accepted else "REJECT",
        challenges=tuple(legacy_verdict.get("reasons") or ()),
        blocking_issues=() if accepted else tuple(legacy_verdict.get("reasons") or ("legacy governance veto",)),
        evidence_ids=evidence_ids, validator_run_id="operon.legacy.adapter",
    )
    incident = repository.add_artifact(intervention_verdict, expected_revision=incident.revision)
    if not accepted:
        return LegacyIntervention(intervention, None)
    incident = repository.transition(incident.id, m.IncidentPhase.INTERVENTION_VALIDATED,
                                     expected_revision=incident.revision,
                                     reason="typed legacy intervention validated")
    requirement = ApprovalLedger(repository).request(incident.id, intervention.id)
    return LegacyIntervention(intervention, requirement)
