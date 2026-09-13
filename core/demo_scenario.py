"""Explicit offline recording scenario inputs; never an authority shortcut.

The backend produces typed advisory fixtures only.  Confirmations are visibly
SIMULATED trusted application inputs.  Promotion, governance, approval,
execution and outcome verification remain owned by their normal services.
"""
from __future__ import annotations

from datetime import timedelta

from core import config, db
from core.agents.contracts import SupervisorBounds, SupervisorResult
from core.reasoning.backend import ReasoningBackend
from core.reliability import models as m
from core.reliability.governance import artifact_hash
from core.reliability.promotion import PromotionService
from core.reliability.repository import utcnow
from core.seed_data import CLASS_DEFAULT_MODE


class DemoReasoningBackend(ReasoningBackend):
    """Deterministic, typed advisory fixture with unambiguous demo provenance."""

    name = "demo"

    def identity(self) -> dict:
        return {
            "backend": self.name,
            "provenance": "SIMULATED",
            "implementation": "operon.guided-demo.typed-advisory-v1",
            "framework_contract": "SupervisorResult",
            "live_model": False,
        }

    async def supervise(self, service, context, *, bounds: SupervisorBounds,
                        snapshot=None, cancellation_result_handler=None) -> SupervisorResult:
        if snapshot is None:
            raise ValueError("guided demo reasoning requires a durable run snapshot")
        evidence_ids = list(snapshot.evidence_manifest)
        evidence = list(context.evidence)
        history = next((item for item in reversed(evidence) if item.kind == "maintenance_history"), evidence[0])
        confirmation = next((item for item in reversed(evidence)
                             if item.source_capability == "operon.confirm_mechanism"), None)
        confirmed = m.TrustedTechnicalConfirmation.model_validate(confirmation.payload) if confirmation else None
        mechanism = confirmed.confirmed_mechanism if confirmed else "Mechanical degradation requires physical confirmation"
        common = {
            "incident_id": context.incident_id,
            "evidence_reviewed": evidence_ids,
            "reasoning_summary": "Deterministic demo advisory over the application-frozen evidence packet.",
        }
        if context.review_target_id is None:
            diagnostic = common | {
                "competing_hypotheses": [
                    {"key": "primary", "mechanism": mechanism,
                     "supporting_evidence_ids": [history.id], "confidence": 0.72,
                     "falsification_tests": ["Perform an independent physical inspection."]},
                    {"key": "sensor", "mechanism": "Sensor bias remains an alternative until inspection.",
                     "supporting_evidence_ids": [], "confidence": 0.18,
                     "falsification_tests": ["Verify sensor calibration against a reference instrument."]},
                ],
                "recommended_hypothesis": "primary", "confidence": 0.72,
                "missing_evidence_requests": [] if confirmed else [{
                    "capability": "operon.confirm_mechanism",
                    "question": "Obtain trusted physical confirmation of the suspected mechanism.",
                }],
            }
            critic = common | {
                "subject_kind": "assessment", "subject_id": "diagnostic",
                "input_assessment_keys": ["diagnostic"], "evidence_gaps": [],
                "contradictions": [], "unsupported_claims": [], "recommendation": "ACCEPT",
                "requested_additional_evidence": [],
            }
            planner = common | {
                "input_assessment_keys": ["diagnostic", "critic"], "validated_input_ids": [],
                "proposed_steps": [{"description": "Prepare a governed physical maintenance work package.",
                    "equipment_ids": [context.asset_id], "evidence_ids": [history.id],
                    "preconditions": ["Application validation and exact approval binding"],
                    "verification_criteria": ["Evaluate post-maintenance classifier risk"]}],
                "estimated_exposure": 12000.0, "exposure_currency": "USD",
                "exposure_assumptions": ["Explicit guided-demo business input; application binds actual values later."],
                "reversible": False, "safety_relevant": True, "external_commitment": True,
                "approval_considerations": ["Human approval is mandatory."], "unresolved_blockers": [],
            }
            assessments = [("diagnostic", "diagnostic", diagnostic), ("critic", "critic", critic),
                           ("planner", "plan", planner)]
            selections = {"candidate_diagnosis_key": "diagnostic", "engineering_key": None,
                          "operations_key": None, "maintenance_plan_key": "plan", "critic_keys": ["critic"]}
        else:
            draft = next(item for item in context.artifacts if isinstance(item, m.Intervention)
                         and item.id == context.review_target_id)
            exact = {"reviewed_intervention_id": draft.id, "reviewed_intervention_hash": artifact_hash(draft)}
            engineering = common | exact | {
                "diagnosis_id": draft.diagnosis_id, "constraints_considered": ["Isolation and mechanical hazards reviewed."],
                "intervention_feasibility": "FEASIBLE", "missing_constraints": [], "blockers": [],
                "safety_concerns": [], "recommended_intervention_elements": ["Execute the exact supplied draft."],
            }
            operations = common | exact | {
                "intervention_id": draft.id, "input_assessment_keys": ["engineering"],
                "resource_feasibility": "FEASIBLE", "inventory_observations": ["Seeded demo stock was checked."],
                "workforce_observations": ["Dated simulated qualification was confirmed."],
                "scheduling_observations": ["The explicit maintenance window was confirmed."],
                "blockers": [], "operational_recommendations": ["Recheck resources at execution."],
            }
            critic = common | exact | {
                "subject_kind": "intervention", "subject_id": draft.id,
                "input_assessment_keys": ["engineering", "operations"], "evidence_gaps": [],
                "contradictions": [], "unsupported_claims": [], "recommendation": "ACCEPT",
                "requested_additional_evidence": [],
            }
            assessments = [("engineering", "engineering", engineering), ("operations", "operations", operations),
                           ("critic", "critic", critic)]
            selections = {"candidate_diagnosis_key": None, "engineering_key": "engineering",
                          "operations_key": "operations", "maintenance_plan_key": None, "critic_keys": ["critic"]}
        return SupervisorResult.model_validate({
            "incident_id": context.incident_id, "run_id": context.run_id,
            "input_revision": context.input_revision, "disposition": "ADVISORY_CONCLUSION",
            "decision": {"incident_id": context.incident_id, "run_id": context.run_id,
                "disposition": "ADVISORY_CONCLUSION",
                "reasoning_summary": "Advisory complete; only Operon application gates may promote it.",
                "evidence_used": evidence_ids, **selections},
            "assessments": [{"key": key, "assessment": value} for _, key, value in assessments],
            "delegations": [{"key": key, "role": role, "question": "Review the frozen demo evidence packet.",
                "input_revision": context.input_revision,
                "input_assessment_keys": value.get("input_assessment_keys", []),
                "evidence_ids": evidence_ids, "status": "SUCCEEDED"} for role, key, value in assessments],
            "evidence_requests": [], "evidence_used": evidence_ids, **selections,
            "unresolved_evidence_needs": [], "blockers": [], "human_review_required": True,
            "termination_reason": "MODEL_COMPLETED", "exhausted_limits": [], "tool_calls": 4,
            "bounds": bounds.model_dump(mode="json"),
        })


def technical_confirmation(engine, equipment_id: str) -> m.TrustedTechnicalConfirmation:
    incident = engine.coordinator.repository.fetch_incident(engine.incidents[equipment_id].id)
    engine.lifecycle.refresh_baseline_evidence(incident.id, equipment_id, engine.evidence_service)
    incident = engine.coordinator.repository.fetch_incident(incident.id)
    artifacts = engine.coordinator.repository.list_artifacts(incident.id)
    superseded = {item.supersedes_id for item in artifacts if getattr(item, "supersedes_id", None)}
    history = [item for item in artifacts if isinstance(item, m.Evidence)
               and item.kind == "maintenance_history" and item.id not in superseded][-1]
    with db.get_conn(engine.coordinator.repository.path) as conn:
        equipment = conn.execute("SELECT equipment_class FROM equipment WHERE equipment_id=?", (equipment_id,)).fetchone()
        mode = conn.execute("SELECT * FROM failure_mode WHERE failure_mode_id=?",
                            (CLASS_DEFAULT_MODE[equipment["equipment_class"]],)).fetchone()
    return m.TrustedTechnicalConfirmation(
        incident_id=incident.id, asset_id=equipment_id,
        confirmed_mechanism=f"Guided-demo inspection confirmed: {mode['failure_mode_name']}", failure_mode_code=mode["mode_code"],
        supporting_evidence_ids=(history.id,),
        performed_checks=(m.PerformedCheck(check="Simulator physical inspection",
                                           result=f"Signature consistent with {mode['mode_code']}", passed=True),),
        observed_at=utcnow(), source="operon-guided-demo-simulator", actor_id="demo-trusted-inspector",
        provenance="SIMULATED")


def resource_confirmation(engine, equipment_id: str) -> m.ResourceConfirmation:
    incident_id = engine.incidents[equipment_id].id
    with db.get_conn(engine.coordinator.repository.path) as conn:
        equipment = conn.execute("SELECT equipment_class FROM equipment WHERE equipment_id=?", (equipment_id,)).fetchone()
        tech = conn.execute("SELECT technician_id FROM technician WHERE skills LIKE ? AND available=1 ORDER BY technician_id",
                            (f"%{equipment['equipment_class']}%",)).fetchone()
        rows = conn.execute("SELECT part_id,qty_per_service FROM equipment_part WHERE equipment_id=? ORDER BY part_id",
                            (equipment_id,)).fetchall()
    if tech is None or not rows:
        raise ValueError("selected demo asset lacks a seeded qualified technician or service parts")
    start = utcnow() + timedelta(days=1)
    return m.ResourceConfirmation(
        incident_id=incident_id, asset_id=equipment_id, technician_id=tech["technician_id"],
        qualification=equipment["equipment_class"], qualification_valid_until=start + timedelta(days=30),
        available_start=start - timedelta(hours=1), available_end=start + timedelta(hours=4),
        window_start=start, window_end=start + timedelta(hours=2), window_confirmed=True,
        parts=tuple(m.WorkPackagePart(part_id=row["part_id"], quantity=row["qty_per_service"]) for row in rows),
        observed_at=utcnow(), source="operon-guided-demo-simulator", actor_id="demo-trusted-dispatcher",
        provenance="SIMULATED")


def binding_fields(engine, equipment_id: str, resource_evidence: m.Evidence) -> dict:
    repo, incident_id = engine.coordinator.repository, engine.incidents[equipment_id].id
    incident = repo.fetch_incident(incident_id)
    lineage = PromotionService(repo).promotion_lineage(incident_id, incident.current_diagnosis_id, "diagnosis")
    report = repo.get_artifact(incident_id, lineage.source_report_id)
    resource = m.ResourceConfirmation.model_validate(resource_evidence.payload)
    diagnosis = repo.get_artifact(incident_id, incident.current_diagnosis_id)
    with db.get_conn(repo.path) as conn:
        mode = conn.execute("SELECT * FROM failure_mode WHERE mode_code=?", (diagnosis.failure_mode_code,)).fetchone()
    return {
        "diagnosis_id": lineage.target_id, "source_report_id": report.id, "source_plan_key": "plan",
        "asset_id": equipment_id, "failure_mode_id": mode["failure_mode_id"],
        "technician_id": resource.technician_id, "parts": resource.parts,
        "resource_confirmation_id": resource_evidence.id, "signal_evidence_id": incident.signal_evidence_ids[0],
        "window_start": resource.window_start, "window_end": resource.window_end,
        "duration_minutes": int(mode["est_planned_minutes"]),
        "work_instructions": ("Isolate equipment and verify zero energy.", mode["recommended_action"]),
        "technical_preconditions": ("Isolation verified by the qualified demo technician",),
        "verification_criteria": ("Persist and evaluate post-maintenance classifier risk",),
        "evidence_ids": tuple(sorted(set(report.evidence_manifest) | {resource_evidence.id})),
        "estimated_cost": 550.0, "estimated_downtime_minutes": int(mode["est_planned_minutes"]),
        "estimated_avoided_loss": round(config.recovered_value(), 0),
        "business_assumption_version": "operon-guided-demo-1",
        "safety_review": "Guided-demo isolation and mechanical hazards reviewed",
        "safety_relevant": True, "reversible": False, "external_commitment": True,
    }
