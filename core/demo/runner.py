"""Deterministic recording scenario with an in-memory read model.

This module deliberately does not import Operon's repository, lifecycle,
promotion, reasoning, model, or simulator packages.  It produces only disposable
UI projections and cannot create authoritative product records.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Awaitable, Callable

from .artifacts import DemoArtifactIndex, validate_demo_artifact_graph


PROVENANCE = "SIMULATED"
RUNTIME = "operon.demo.scripted-v1"
BASE_TIME = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
PRE_APPROVAL_SECONDS = 42
POST_APPROVAL_SECONDS = 33

DEGRADATION = (
    (.14, .91, "HEALTHY", "Small vibration anomaly", {"torque": 42.1, "vibration": 2.1, "temp_diff": 7.8, "motor_current": 32.0, "rot_speed": 1450}),
    (.29, .81, "HEALTHY", "Developing bearing signature", {"torque": 45.2, "vibration": 3.0, "temp_diff": 8.6, "motor_current": 34.1, "rot_speed": 1425}),
    (.48, .66, "WARNING", "Moderate bearing signature", {"torque": 49.0, "vibration": 4.6, "temp_diff": 10.1, "motor_current": 37.0, "rot_speed": 1385}),
    (.68, .46, "WARNING", "Elevated drive-end bearing risk", {"torque": 54.8, "vibration": 6.8, "temp_diff": 12.6, "motor_current": 41.2, "rot_speed": 1335}),
    (.86, .25, "CRITICAL", "Drive-end bearing degradation", {"torque": 62.4, "vibration": 9.2, "temp_diff": 14.8, "motor_current": 46.5, "rot_speed": 1280}),
)

RECOVERY = (
    (.64, .49, "WARNING", {"torque": 53.0, "vibration": 6.4, "temp_diff": 12.0, "motor_current": 40.0, "rot_speed": 1340}),
    (.39, .70, "HEALTHY", {"torque": 46.0, "vibration": 3.8, "temp_diff": 9.5, "motor_current": 35.0, "rot_speed": 1400}),
    (.18, .87, "HEALTHY", {"torque": 42.0, "vibration": 2.2, "temp_diff": 7.7, "motor_current": 32.0, "rot_speed": 1440}),
    (.09, .95, "HEALTHY", {"torque": 40.0, "vibration": 1.6, "temp_diff": 7.1, "motor_current": 30.5, "rot_speed": 1460}),
)


class DemoScenarioRunner:
    """Own one disposable scripted lifecycle and stop at human approval."""

    def __init__(self, fleet: list[dict], *, publish: Callable[[], Awaitable[None]] | None = None,
                 time_scale: float = 1.0):
        self._fleet_source = deepcopy(fleet)
        self._publish = publish
        self.time_scale = time_scale
        self._task: asyncio.Task | None = None
        self._generation = 0
        self._state: dict | None = None
        self._elapsed_seconds = 0
        self._artifacts = DemoArtifactIndex()

    @property
    def active(self) -> bool:
        return self._state is not None

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    def owns(self, equipment_id: str) -> bool:
        return bool(self._state and self._state["demo_scenario"]["equipment_id"] == equipment_id)

    def artifact(self, artifact_id: str) -> dict | None:
        """Return a detached demo detail envelope, never a production record."""
        return self._artifacts.get(artifact_id)

    def artifacts(self) -> list[dict]:
        """Return detached details for integrity tests and demo diagnostics."""
        return self._artifacts.values()

    def validate_artifact_graph(self) -> None:
        validate_demo_artifact_graph(self._artifacts.values())

    async def start(self, equipment_id: str) -> dict:
        if not any(item["equipment_id"] == equipment_id for item in self._fleet_source):
            return {"ok": False, "error": "unknown demo equipment"}
        await self.reset(publish=False)
        self._generation += 1
        generation = self._generation
        self._elapsed_seconds = 0
        self._state = self._healthy_state(equipment_id)
        await self._emit()
        self._task = asyncio.create_task(self._run(generation), name=f"operon-demo:{equipment_id}")
        return {"ok": True, "demo_scenario": deepcopy(self._state["demo_scenario"])}

    async def reset(self, *, publish: bool = True) -> None:
        self._generation += 1
        task = self._task
        self._task = None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._state = None
        self._artifacts.clear()
        if publish:
            await self._emit()

    async def approve(self, equipment_id: str, command: dict | None) -> dict:
        if not self.owns(equipment_id):
            return {"ok": False, "error": "no active demo incident for this asset"}
        lifecycle = self._alert()["lifecycle"]
        if lifecycle["phase"] != "AWAITING_APPROVAL":
            return {"ok": False, "error": f"demo approval requires AWAITING_APPROVAL, found {lifecycle['phase']}"}
        required = ("requirement_id", "intervention_id", "intervention_hash", "context_revision")
        if not command or any(command.get(key) != lifecycle.get(key) for key in required):
            return {"ok": False, "error": "approval must match the exact simulated requirement, intervention, hash and revision"}
        view = lifecycle["read_model"]
        view["approval_decisions"].append(self._artifact(
            "DEMO-APPROVAL-01", "approval_binding", "Exact-plan approval binding", status="APPROVED",
            summary="A human approver approved the exact simulated intervention and work package.",
            parent_ids=["DEMO-REQUIREMENT-01"], supporting_ids=["DEMO-VERDICT-INTERVENTION"],
            related_ids=["DEMO-INTERVENTION-01", "DEMO-WP-1042"],
            decision="APPROVE", approval_request_id="DEMO-REQUIREMENT-01",
            intervention_id="DEMO-INTERVENTION-01", work_package_id="DEMO-WP-1042",
            intervention_hash=self._intervention_hash(), plan_version="operon.demo.work-package-v1",
            actor_id=command.get("actor_id", "dashboard-operator"),
            actor_role=command.get("actor_role", "maintenance_approver"),
            approved_at=(BASE_TIME + timedelta(seconds=self._elapsed_seconds)).isoformat(),
            rationale=command.get("rationale", "approved in Operon dashboard"),
        ))
        view["requirements"][0]["status"] = "APPROVED"
        self._transition("READY", "Explicit human approval recorded for the simulated exact plan.")
        self._state["demo_scenario"]["approval_state"] = "APPROVED"
        self._state["demo_scenario"]["status"] = "ready"
        self._event("APPROVAL_RECORDED", {}, artifact_id="DEMO-APPROVAL-01")
        await self._emit()
        generation = self._generation
        self._task = asyncio.create_task(self._run_after_approval(generation), name=f"operon-demo-recovery:{equipment_id}")
        return {"ok": True, "phase": "READY", "demo": True, "provenance": PROVENANCE}

    async def reject(self, equipment_id: str, command: dict | None) -> dict:
        if not self.owns(equipment_id):
            return {"ok": False, "error": "no active demo incident for this asset"}
        lifecycle = self._alert()["lifecycle"]
        if lifecycle["phase"] != "AWAITING_APPROVAL":
            return {"ok": False, "error": f"demo rejection requires AWAITING_APPROVAL, found {lifecycle['phase']}"}
        self._transition("CANCELLED", "Presenter rejected the simulated intervention.")
        self._state["demo_scenario"].update(status="cancelled", approval_state="REJECTED")
        await self._emit()
        return {"ok": True, "phase": "CANCELLED", "demo": True, "provenance": PROVENANCE}

    def snapshot(self) -> dict | None:
        return deepcopy(self._state)

    async def _run(self, generation: int) -> None:
        try:
            for index, (delay, sample) in enumerate(zip((3, 3, 3, 3, 2), DEGRADATION)):
                await self._wait(delay)
                self._assert_current(generation)
                risk, health, status, mode, metrics = sample
                self._set_selected(risk=risk, health=health, status=status, mode=mode, metrics=metrics)
                if index == 0:
                    self._state["demo_scenario"].update(status="degrading", phase="FACTORY_DEGRADING")
                elif index < len(DEGRADATION) - 1:
                    self._state["demo_scenario"].update(status=f"risk_rising_{index}", phase="PREDICTIVE_RISK_RISING")
                else:
                    self._create_incident()
                await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            self._transition("INVESTIGATING", "Structured simulated investigation started.")
            self._state["demo_scenario"]["status"] = "investigating"
            await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            view = self._view()
            acquired = self._baseline_evidence()
            view["evidence"].extend(acquired)
            for evidence in acquired:
                self._event("EVIDENCE_ACQUIRED", {"kind": evidence["kind"]}, artifact_id=evidence["id"])
            view["agent_actions"] = [self._record("DEMO-ACTION-01", actor="operon.demo.scripted",
                status="SUCCEEDED", summary="Reviewed telemetry, operating context, and maintenance history.")]
            self._state["demo_scenario"]["status"] = "evidence_review"
            await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            view["agent_runs"] = [self._agent_run("DIAGNOSIS", "RUNNING", [
                ("diagnostic", "Bearing wear best matches the vibration, thermal, and load trends."),
                ("critic", "Causal support is coherent, but physical confirmation is still required."),
            ])]
            self._event("SPECIALIST_ACTIVITY_RECORDED", {"stage": "DIAGNOSIS"},
                        artifact_id=view["agent_runs"][0]["id"])
            self._state["demo_scenario"]["status"] = "specialist_evidence_review"
            await self._emit()

            await self._wait(2)
            self._assert_current(generation)
            self._transition("AWAITING_EVIDENCE", "Physical inspection is required before diagnosis validation.")
            self._state["demo_scenario"]["status"] = "awaiting_evidence"
            await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            view = self._view()
            inspection = self._inspection_evidence()
            view["evidence"].append(inspection)
            self._event("EVIDENCE_ACQUIRED", {"kind": "inspection"}, artifact_id=inspection["id"])
            self._state["demo_scenario"].update(status="inspection_received", evidence_state="TRUSTED_SIMULATED")
            await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            view["diagnosis"] = self._diagnosis()
            view["verdicts"].append(self._artifact("DEMO-VERDICT-DIAGNOSIS", "diagnosis_validation",
                "Critic diagnosis verdict", status="ACCEPT",
                summary="Inspection and telemetry independently support drive-end bearing wear.",
                parent_ids=["DEMO-DIAGNOSIS-01"], supporting_ids=["DEMO-ADV-CRITIC-01"],
                target_kind="diagnosis", target_id="DEMO-DIAGNOSIS-01", subject_artifact_id="DEMO-DIAGNOSIS-01",
                result="ACCEPT", decision="ACCEPT", concise_justification="Independent simulated inspection corroborates telemetry.",
                blocking_issues=[],
                validation_summary="Inspection and telemetry independently support drive-end bearing wear.",
                validation_policy_version="operon.demo.validation-display-v1"))
            view["agent_runs"][0].update(status="SUCCEEDED", disposition="SIMULATED_ADVISORY",
                summary="Structured diagnosis completed from the simulated evidence packet.")
            self._state["demo_scenario"]["status"] = "diagnosis_validated"
            self._event("DIAGNOSIS_CREATED", {}, artifact_id=view["diagnosis"]["id"])
            self._event("DIAGNOSIS_VALIDATED", {}, artifact_id=view["verdicts"][-1]["id"])
            await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            self._transition("DIAGNOSIS_VALIDATED", "Simulated diagnosis validation recorded in the demo read model.")
            self._state["demo_scenario"]["status"] = "diagnosis_phase_validated"
            await self._emit()

            await self._wait(2)
            self._assert_current(generation)
            self._transition("PLANNING", "Simulated maintenance planning started.")
            view["intervention"] = self._intervention()
            view["binding"] = self._binding()
            view["agent_runs"].append(self._agent_run("INTERVENTION_REVIEW", "SUCCEEDED", [
                ("engineering", "Replace the drive-end bearing; verify alignment, lubrication, and vibration."),
                ("operations", "A 45-minute window, qualified technician, and service kit are available."),
                ("critic", "Evidence, scope, resources, safety constraints, and expected impact are consistent."),
                ("planner", "Executable high-priority work package prepared with lockout/tagout and post-work checks."),
            ]))
            self._event("INTERVENTION_CREATED", {}, artifact_id=view["intervention"]["id"])
            self._event("SPECIALIST_ACTIVITY_RECORDED", {"stage": "INTERVENTION_REVIEW"},
                        artifact_id=view["agent_runs"][-1]["id"])
            self._state["demo_scenario"]["status"] = "specialist_review"
            await self._emit()

            await self._wait(4)
            self._assert_current(generation)
            view["verdicts"].append(self._artifact("DEMO-VERDICT-INTERVENTION", "intervention_validation",
                "Critic intervention verdict", status="ACCEPT",
                summary="The exact simulated work package is feasible and internally consistent.",
                parent_ids=["DEMO-INTERVENTION-01"], supporting_ids=["DEMO-ADV-CRITIC-02"],
                target_kind="intervention", target_id="DEMO-INTERVENTION-01",
                subject_artifact_id="DEMO-INTERVENTION-01", result="ACCEPT", decision="ACCEPT",
                concise_justification="Engineering, operations, resources, safety, and scope are consistent.", blocking_issues=[],
                validation_summary="The exact simulated work package is feasible and internally consistent.",
                validation_policy_version="operon.demo.validation-display-v1"))
            view["intervention"]["status"] = "VALIDATED"
            self._transition("INTERVENTION_VALIDATED", "Engineering, Operations, and Critic reviews accepted the simulated plan.")
            self._state["demo_scenario"]["status"] = "intervention_validated"
            self._event("INTERVENTION_VALIDATED", {}, artifact_id=view["verdicts"][-1]["id"])
            await self._emit()

            await self._wait(2)
            self._assert_current(generation)
            view["requirements"] = [self._requirement()]
            self._transition("AWAITING_APPROVAL", "Mandatory human approval is required; demo automation is paused.")
            lifecycle = self._alert()["lifecycle"]
            lifecycle.update(requirement_id="DEMO-REQUIREMENT-01", intervention_id="DEMO-INTERVENTION-01",
                             intervention_hash=self._intervention_hash(), context_revision=lifecycle["revision"])
            self._state["demo_scenario"].update(status="awaiting_human_approval", approval_state="PENDING")
            self._event("APPROVAL_REQUESTED", {}, artifact_id=view["requirements"][0]["id"])
            await self._emit()
            # Deliberately return. No timer, callback, or background task can approve.
        except asyncio.CancelledError:
            raise

    async def _run_after_approval(self, generation: int) -> None:
        try:
            await self._wait(2)
            self._assert_current(generation)
            self._transition("EXECUTING", "Simulated work order dispatched after explicit human approval.")
            self._view()["work_orders"] = [self._work_order()]
            self._state["demo_scenario"]["status"] = "executing"
            self._event("WORK_ORDER_DISPATCHED", {}, artifact_id="DEMO-WO-1042")
            await self._emit()

            await self._wait(5)
            self._assert_current(generation)
            view = self._view()
            view["execution_receipts"] = [self._execution_receipt()]
            self._state["demo_scenario"].update(status="execution_receipt", execution_receipt="DEMO-WO-1042")
            self._event("EXECUTION_CONFIRMED", {}, artifact_id="DEMO-RECEIPT-01")
            await self._emit()

            await self._wait(4)
            self._assert_current(generation)
            view["observation_plans"] = [self._artifact("DEMO-OBSERVATION-01", "recovery_observation_plan",
                "Post-maintenance recovery observation plan", status="ACTIVE",
                summary="Verify four deterministic post-maintenance samples before declaring recovery.",
                parent_ids=["DEMO-RECEIPT-01"], related_ids=["DEMO-INTERVENTION-01"],
                description="Verify four deterministic post-maintenance samples before declaring recovery.",
                execution_receipt_id="DEMO-RECEIPT-01", intervention_id="DEMO-INTERVENTION-01",
                minimum_samples=4, recovery_risk_max=.40, observations=[])]
            self._transition("OBSERVING", "Simulated execution receipt received; recovery observation started.")
            self._state["demo_scenario"].update(status="observing", execution_receipt="DEMO-WO-1042",
                                                recovery_status="OBSERVING")
            await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            self._state["demo_scenario"]["status"] = "observation_baseline"
            await self._emit()

            for index, (delay, sample) in enumerate(zip((4, 4, 4, 2), RECOVERY), start=1):
                await self._wait(delay)
                self._assert_current(generation)
                risk, health, status, metrics = sample
                self._set_selected(risk=risk, health=health, status=status,
                                   mode="Recovering after simulated maintenance", metrics=metrics)
                observation_id = f"DEMO-RECOVERY-{index:02d}"
                observation = self._artifact(observation_id, "recovery_observation",
                    f"Recovery observation {index}", status="HEALTHY" if risk < .40 else "IMPROVING",
                    summary=f"Post-maintenance sample {index} recorded failure risk {risk:.2f}.",
                    parent_ids=["DEMO-RECEIPT-01"], related_ids=["DEMO-INTERVENTION-01", "DEMO-OBSERVATION-01"],
                    sequence=index, execution_receipt_id="DEMO-RECEIPT-01", intervention_id="DEMO-INTERVENTION-01",
                    failure_risk=risk, health_score=health, vibration_mm_s=metrics["vibration"],
                    temperature_rise_c=metrics["temp_diff"], telemetry={**metrics, "health_score": health})
                view["observation_plans"][0]["observations"].append(observation)
                self._state["demo_scenario"].update(
                    status="telemetry_stable_healthy" if index == len(RECOVERY) else f"telemetry_recovering_{index}",
                    recovery_status=f"OBSERVATION_{index}_OF_{len(RECOVERY)}")
                self._event("RECOVERY_OBSERVATION_RECORDED", {"sequence": index}, artifact_id=observation_id)
                await self._emit()

            await self._wait(2)
            self._assert_current(generation)
            observation_ids = [f"DEMO-RECOVERY-{index:02d}" for index in range(1, len(RECOVERY) + 1)]
            outcome_reason = "Four scripted post-intervention observations show sustained risk and vibration recovery."
            view["outcomes"] = [self._artifact("DEMO-OUTCOME-01", "outcome_verification",
                "Verified recovery outcome", status="VERIFIED_RECOVERY", summary=outcome_reason,
                parent_ids=["DEMO-RECEIPT-01"], supporting_ids=observation_ids,
                related_ids=["DEMO-INTERVENTION-01", "DEMO-WP-1042"], result="VERIFIED_RECOVERY",
                reason=outcome_reason, observation_ids=observation_ids, execution_receipt_id="DEMO-RECEIPT-01",
                intervention_id="DEMO-INTERVENTION-01", work_package_id="DEMO-WP-1042",
                verification_timestamp=(BASE_TIME + timedelta(seconds=self._elapsed_seconds)).isoformat(),
                before_metrics={"failure_risk": .86, "health_score": .25, "vibration_mm_s": 9.2},
                after_metrics={"failure_risk": .09, "health_score": .95, "vibration_mm_s": 1.6},
                verifier="operon.demo.deterministic-observer" )]
            self._state["demo_scenario"].update(status="verified_recovery", recovery_status="VERIFIED_RECOVERY")
            self._event("RECOVERY_VERIFIED", {}, artifact_id="DEMO-OUTCOME-01")
            await self._emit()

            await self._wait(3)
            self._assert_current(generation)
            self._transition("CLOSED", "Simulated recovery verified; demo incident closed.")
            self._alert()["status"] = "CLOSED"
            closure = self._artifact("DEMO-CLOSURE-01", "incident_closure", "Final simulated incident closure",
                status="CLOSED", summary="The incident closed after deterministic recovery verification.",
                parent_ids=["DEMO-OUTCOME-01"], supporting_ids=["DEMO-RECEIPT-01"],
                outcome_id="DEMO-OUTCOME-01", execution_receipt_id="DEMO-RECEIPT-01",
                final_phase="CLOSED", final_incident_status="CLOSED",
                closed_at=(BASE_TIME + timedelta(seconds=self._elapsed_seconds)).isoformat())
            view["closures"] = [closure]
            self._state["business"].update(events_prevented=1, recovered_value=11450, net_value=10900,
                                           verified_outcome="SIMULATED")
            self._state["demo_scenario"].update(status="complete", phase="CLOSED", outcome="VERIFIED_RECOVERY")
            self._event("INCIDENT_CLOSED", {}, artifact_id=closure["id"])
            await self._emit()
        except asyncio.CancelledError:
            raise

    def _healthy_state(self, equipment_id: str) -> dict:
        fleet = []
        histories = {}
        for index, item in enumerate(self._fleet_source):
            eid = item["equipment_id"]
            point = {"t": 0, "prob": .07 + index * .005, "health": .96 - index * .004,
                     "torque": 39.8 + index, "tool_wear": 18 + index, "vibration": 1.5,
                     "temp_diff": 7.0, "motor_current": 30.2, "rot_speed": 1465}
            fleet.append({**item, "status": "HEALTHY", "status_source": "demo_script",
                          "status_reason": "Deterministic simulated healthy baseline", "failure_prob": point["prob"],
                          "health_score": point["health"], "predicted_mode": "NONE",
                          "predicted_mode_label": "Nominal signature", "point": point,
                          "provenance": PROVENANCE, "runtime": RUNTIME, "live_model": False})
            histories[eid] = [point]
        return {"type": "snapshot", "tick": 0, "plant_time_min": 0, "running": True, "agent_mode": "scripted-demo",
                "app_name": "Operon", "tagline": "Autonomous Reliability Operations for Industrial Systems",
                "plant_name": "Guided Demo · Simulated Plant", "authority_path": "demo-read-model-only",
                "supervisor_available": False, "trigger_threshold": .8, "warn_threshold": .45,
                "fleet": fleet, "histories": histories, "alerts": [],
                "triage": {"count": 0, "rationale": "Deterministic scripted presentation", "order": []},
                "business": {"events_prevented": 0, "events_failed": 0, "recovered_value": 0,
                             "loss_incurred": 0, "net_value": 0, "oee_baseline": .84, "oee_target": .91,
                             "estimated_downtime_avoided_minutes": 135, "planned_maintenance_minutes": 45,
                             "production_impact": "Single compressor service window · SIMULATED",
                             "incident_priority": "HIGH", "provenance": PROVENANCE,
                             "runtime": RUNTIME, "live_model": False},
                "reasoning_provenance": {"backend": "scripted-demo", "runtime": RUNTIME,
                    "framework": "Structured simulated specialist activity", "model_provider": None,
                    "status": "simulated", "provenance": PROVENANCE, "live_model": False},
                "demo_scenario": {"active": True, "label": "Guided Demo · Simulated Plant",
                    "equipment_id": equipment_id, "status": "factory_healthy", "phase": "FACTORY_HEALTHY",
                    "risk": next(x["failure_prob"] for x in fleet if x["equipment_id"] == equipment_id),
                    "provenance": PROVENANCE, "runtime": RUNTIME, "live_model": False,
                    "authoritative_persistence": False, "approval_state": "NOT_REQUESTED"}}

    def _create_incident(self) -> None:
        eid = self._state["demo_scenario"]["equipment_id"]
        self._state["demo_scenario"]["incident_id"] = "DEMO-INCIDENT-01"
        signal_summary = "Predictive risk rose from 0.07 to 0.86 and crossed the scripted 0.80 threshold."
        signal = self._artifact("DEMO-EVIDENCE-SIGNAL", "predictive_signal", "Predictive bearing-risk signal",
            status="THRESHOLD_CROSSED", summary=signal_summary, source="operon-guided-demo-simulator",
            kind="model_signal",
            source_system="operon-guided-demo-simulator", source_capability="operon.demo.telemetry",
            quality="SIMULATED_OBSERVATION", payload={"failure_probability": .86, "threshold": .8,
                "live_model": False, "attribution": [
                    {"feature": "torque", "label": "Torque", "value": 62.4, "contribution": .31},
                    {"feature": "vibration", "label": "Vibration", "value": 9.2, "contribution": .28},
                    {"feature": "temp_diff", "label": "Temperature rise", "value": 14.8, "contribution": .25}]})
        lifecycle = {"phase": "OPEN", "revision": 1, "context_revision": 1,
            "diagnosis_id": None, "intervention_id": None, "intervention_hash": None,
            "requirement_id": None, "authority_valid": False, "authority_reason": "SIMULATED demo read model",
            "reconciliation_required": False, "execution_lineage_valid": False, "supervisor_available": False,
            "last_reason": "Scripted risk threshold crossed.", "provenance": PROVENANCE,
            "runtime": RUNTIME, "live_model": False, "read_model": {"phase": "OPEN",
                "evidence": [signal], "events": [], "agent_actions": [], "agent_runs": [], "verdicts": [],
                "diagnosis": None, "intervention": None, "binding": None, "requirements": [],
                "approval_decisions": [], "work_orders": [], "execution_receipts": [],
                "observation_plans": [], "outcomes": [], "closures": []}}
        alert = {"incident_id": "DEMO-INCIDENT-01", "equipment_id": eid,
            "equipment_name": next(x.get("name") for x in self._state["fleet"] if x["equipment_id"] == eid),
            "equipment_class": next(x.get("equipment_class") for x in self._state["fleet"] if x["equipment_id"] == eid),
            "criticality": next(x.get("criticality") for x in self._state["fleet"] if x["equipment_id"] == eid),
            "failure_prob": .86, "predicted_mode": "BEARING_WEAR",
            "predicted_mode_label": "Drive-end bearing degradation", "status": "ANALYZING",
            "created_tick": 5, "triage_rank": 1, "triage_score": .86, "proposal": None,
            "result": None, "intervention_id": None, "approval_requirement_id": None,
            "execution_receipt_ids": [], "provenance": PROVENANCE, "runtime": RUNTIME,
            "live_model": False, "lifecycle": lifecycle}
        self._state["alerts"] = [alert]
        self._state["triage"] = {"count": 1, "rationale": "Single deterministic demo incident", "order": [eid]}
        self._state["demo_scenario"].update(status="incident_open", phase="OPEN", incident_id=alert["incident_id"], risk=.86)
        self._event("INCIDENT_OPENED", {"to": "OPEN", "provenance": PROVENANCE})
        self._event("EVIDENCE_ACQUIRED", {"kind": "model_signal"}, artifact_id=signal["id"])

    def _transition(self, phase: str, reason: str) -> None:
        alert = self._alert()
        lifecycle = alert["lifecycle"]
        previous = lifecycle["phase"]
        lifecycle["phase"] = phase
        lifecycle["read_model"]["phase"] = phase
        lifecycle["revision"] += 1
        lifecycle["context_revision"] = lifecycle["revision"]
        lifecycle["last_reason"] = reason
        alert["status"] = {"AWAITING_APPROVAL": "PENDING_APPROVAL", "READY": "APPROVED",
                           "EXECUTING": "APPROVED", "OBSERVING": "APPROVED", "CLOSED": "CLOSED"}.get(phase, "ANALYZING")
        self._state["demo_scenario"]["phase"] = phase
        self._event("PHASE_CHANGED", {"from": previous, "to": phase, "reason": reason, "provenance": PROVENANCE})

    def _event(self, event_type: str, payload: dict, *, artifact_id: str | None = None) -> None:
        view = self._view()
        revision = self._alert()["lifecycle"]["revision"]
        event_id = f"DEMO-EVENT-{len(view['events']) + 1:02d}"
        event = self._artifact(event_id, "lifecycle_event", event_type.replace("_", " ").title(),
            status="RECORDED", summary=payload.get("reason", event_type.replace("_", " ").title()),
            related_ids=[artifact_id] if artifact_id else [], event_type=event_type, revision=revision,
            payload=payload, represented_artifact_id=artifact_id)
        event["event_artifact_id"] = event_id
        if artifact_id:
            event["artifact_id"] = artifact_id
        view["events"].append(event)

    def _set_selected(self, *, risk: float, health: float, status: str, mode: str, metrics: dict) -> None:
        self._state["tick"] += 1
        self._state["plant_time_min"] = self._state["tick"]
        self._state["demo_scenario"]["risk"] = risk
        eid = self._state["demo_scenario"]["equipment_id"]
        asset = next(item for item in self._state["fleet"] if item["equipment_id"] == eid)
        point = {"t": self._state["tick"], "prob": risk, "health": health,
                 "tool_wear": 38, **metrics}
        asset.update(status=status, failure_prob=risk, health_score=health,
                     predicted_mode="BEARING_WEAR" if risk >= .14 else "NONE", predicted_mode_label=mode, point=point)
        self._state["histories"][eid].append(point)
        if self._state["alerts"]:
            self._alert()["failure_prob"] = risk

    def _baseline_evidence(self) -> list[dict]:
        return [
            self._artifact("DEMO-EVIDENCE-TREND", "evidence", "Telemetry trend evidence",
                status="AVAILABLE", summary="Drive-end vibration climbed 1.5 → 9.2 mm/s as temperature rise reached 14.8 °C.",
                source="operon-guided-demo-simulator", kind="telemetry",
                source_system="operon-guided-demo-simulator", source_capability="operon.demo.telemetry-window",
                quality="SIMULATED_OBSERVATION", payload={"vibration_mm_s": [1.5, 2.1, 3.0, 4.6, 6.8, 9.2],
                    "temperature_rise_c": [7.0, 7.8, 8.6, 10.1, 12.6, 14.8],
                    "motor_current_a": [30.2, 32.0, 34.1, 37.0, 41.2, 46.5]}),
            self._artifact("DEMO-EVIDENCE-OPERATING", "evidence", "Operating-context evidence",
                status="AVAILABLE", summary="Compressor held 78% load; no process upset or commanded speed change explains the trend.",
                source="operon-guided-demo-simulator", kind="operational_context",
                source_system="operon-guided-demo-simulator", source_capability="operon.demo.operating-context",
                quality="SIMULATED_CONTEXT", payload={"load_percent": 78, "duty": "lead compressor",
                    "process_state": "stable", "ambient_c": 27.4}),
            self._artifact("DEMO-EVIDENCE-HISTORY", "evidence", "Maintenance-history evidence",
                status="AVAILABLE", summary="Last bearing service was 4,180 operating hours ago; alignment check was previously satisfactory.",
                source="operon-guided-demo-simulator", kind="maintenance_history",
                source_system="operon-guided-demo-simulator", source_capability="operon.demo.maintenance-history",
                quality="SIMULATED_RECORD", payload={"hours_since_service": 4180,
                    "last_action": "Bearing lubrication and shaft alignment check", "open_defects": 0}),
        ]

    def _inspection_evidence(self) -> dict:
        summary = "Simulated technician inspection confirmed drive-end bearing play and localized vibration."
        return self._artifact("DEMO-EVIDENCE-INSPECTION", "technician_inspection", "Technician technical confirmation",
            status="CONFIRMED_SIMULATED", summary=summary, source="operon-guided-demo-simulator",
            supporting_ids=["DEMO-EVIDENCE-TREND", "DEMO-EVIDENCE-HISTORY"], kind="inspection",
            source_system="operon-guided-demo-simulator", source_capability="operon.demo.inspection",
            quality="TRUSTED_SIMULATED", actor_id="TECH-DEMO-03",
            payload={"finding": "Drive-end bearing radial play above demo tolerance",
                "vibration_mm_s": 9.1, "housing_temperature_c": 72.4,
                "lubrication_condition": "degraded", "inspection_result": "CONFIRMED_SIMULATED"})

    def _diagnosis(self) -> dict:
        conclusion = "Progressive drive-end bearing wear is causing elevated vibration, load, and temperature."
        evidence_ids = ["DEMO-EVIDENCE-SIGNAL", "DEMO-EVIDENCE-TREND",
                        "DEMO-EVIDENCE-HISTORY", "DEMO-EVIDENCE-INSPECTION"]
        return self._artifact("DEMO-DIAGNOSIS-01", "diagnosis", "Validated bearing-wear diagnosis",
            status="VALIDATED_SIMULATED", summary=conclusion, supporting_ids=evidence_ids +
            ["DEMO-ADV-DIAGNOSTIC-01", "DEMO-ADV-CRITIC-01"], conclusion=conclusion,
            likely_failure_mode="Drive-end bearing wear", failure_mode_code="BEARING_WEAR",
            affected_component="Drive-end bearing assembly", confidence=.94, validation_status="VALIDATED_SIMULATED",
            key_observations=["Vibration increased to 9.2 mm/s", "Temperature rise reached 14.8 °C",
                              "Simulated inspection confirmed radial play"],
            evidence_ids=evidence_ids, specialist_advisory_ids=["DEMO-ADV-DIAGNOSTIC-01", "DEMO-ADV-CRITIC-01"],
            validator_verdict_id="DEMO-VERDICT-DIAGNOSIS")

    def _agent_run(self, stage: str, status: str, specialists: list[tuple[str, str]]) -> dict:
        run_number = len(self._view().get("agent_runs", [])) + 1
        delegations = []
        review_types = {"engineering": "engineering_review", "operations": "operations_review",
                        "critic": "critic_intervention_review"}
        for role, text in specialists:
            advisory_id = f"DEMO-ADV-{role.upper()}-{run_number:02d}"
            artifact_type = review_types.get(role, "specialist_advisory") if stage == "INTERVENTION_REVIEW" else "specialist_advisory"
            parent_ids = ["DEMO-INTERVENTION-01"] if stage == "INTERVENTION_REVIEW" else []
            evidence_ids = ["DEMO-EVIDENCE-SIGNAL", "DEMO-EVIDENCE-TREND", "DEMO-EVIDENCE-HISTORY"]
            if stage == "DIAGNOSIS":
                evidence_ids.append("DEMO-EVIDENCE-INSPECTION") if "DEMO-EVIDENCE-INSPECTION" in [x["id"] for x in self._view()["evidence"]] else None
            finding = self._artifact(advisory_id, artifact_type, f"{role.title()} specialist advisory",
                status="SUCCEEDED", summary=text, parent_ids=parent_ids, supporting_ids=evidence_ids,
                specialist_role=role, advisory_id=advisory_id, stage=stage, incident_id=self._alert()["incident_id"],
                short_conclusion=text, structured_findings=[{"finding": text, "severity": "ADVISORY"}],
                recommendations=[text], evidence_references=evidence_ids,
                intervention_id="DEMO-INTERVENTION-01" if stage == "INTERVENTION_REVIEW" else None)
            finding.update(key=f"demo-{role}", role=role, question=text, summary=text)
            delegations.append(finding)
        run_id = f"DEMO-RUN-{run_number:02d}"
        return self._artifact(run_id, "specialist_activity", f"{stage.replace('_', ' ').title()} specialist activity",
            status=status, summary="Scripted specialist outputs; no live Bedrock, AgentCore, or Strands execution.",
            supporting_ids=[item["id"] for item in delegations], run_id=f"DEMO-RUN-{stage}",
            stage=stage, disposition="SIMULATED_ADVISORY", tool_calls=len(specialists),
            runtime_identity={"backend": "scripted-demo", "runtime": RUNTIME, "provenance": PROVENANCE,
                              "live_model": False}, blockers=[], assessments=[],
            delegations=delegations)

    def _intervention(self) -> dict:
        return self._artifact("DEMO-INTERVENTION-01", "intervention", "Drive-end bearing maintenance plan",
            status="DRAFT", summary="Replace the drive-end bearing, align the shaft, and verify vibration.",
            parent_ids=["DEMO-DIAGNOSIS-01"], supporting_ids=["DEMO-VERDICT-DIAGNOSIS"],
            related_ids=["DEMO-WP-1042", "DEMO-ADV-ENGINEERING-02", "DEMO-ADV-OPERATIONS-02",
                         "DEMO-ADV-CRITIC-02"], risk="MEDIUM", priority="HIGH",
            diagnosis_id="DEMO-DIAGNOSIS-01", estimated_cost=550, estimated_downtime_minutes=45,
            estimated_avoided_loss=12000, window_start="2026-01-15T10:00:00+00:00",
            window_end="2026-01-15T10:45:00+00:00", component="Drive-end bearing assembly",
            part_id="DEMO-PART-BRG-04", required_skill="Rotating equipment mechanical maintenance",
            review_ids=["DEMO-ADV-ENGINEERING-02", "DEMO-ADV-OPERATIONS-02", "DEMO-ADV-CRITIC-02"],
            operational_constraint="Maintain standby compressor availability during the service window.",
            safety_note="Lockout/tagout and zero-energy verification required before mechanical work.",
            steps=[{"capability": "replace_drive_end_bearing", "parameters": {
                "description": "Inspect and replace the degraded drive-end bearing assembly; align shaft and verify vibration.",
                "part_id": "DEMO-PART-BRG-04", "quantity": 1,
                "safety": "Lockout/tagout and verify zero energy."}}])

    def _binding(self) -> dict:
        review_ids = ["DEMO-ADV-ENGINEERING-02", "DEMO-ADV-OPERATIONS-02", "DEMO-ADV-CRITIC-02"]
        work_package = self._artifact("DEMO-WP-1042", "work_package", "Bearing replacement work package",
            status="PREPARED", summary="Executable simulated work package for the validated intervention.",
            parent_ids=["DEMO-INTERVENTION-01"], supporting_ids=review_ids,
            related_ids=["DEMO-INVENTORY-01", "DEMO-ASSIGNMENT-01", "DEMO-SCHEDULE-01"],
            intervention_id="DEMO-INTERVENTION-01", diagnosis_id="DEMO-DIAGNOSIS-01", version="1",
            plan_hash=self._intervention_hash(), instructions=["Lock out and verify zero energy.",
                "Replace drive-end bearing kit.", "Align shaft, lubricate, and verify vibration."],
            safety_requirements=["Lockout/tagout", "Zero-energy verification"], duration_minutes=45)
        inventory = self._artifact("DEMO-INVENTORY-01", "inventory_reservation", "Bearing-kit inventory reservation",
            status="RESERVED_SIMULATED", summary="One bearing and seal service kit reserved from two available.",
            parent_ids=[work_package["id"], "DEMO-INTERVENTION-01"],
            work_package_id=work_package["id"], intervention_id="DEMO-INTERVENTION-01",
            part_id="DEMO-PART-BRG-04", description="Bearing and seal service kit", quantity=1,
            available_quantity=2, reserved_at=(BASE_TIME + timedelta(seconds=self._elapsed_seconds)).isoformat())
        assignment = self._artifact("DEMO-ASSIGNMENT-01", "technician_assignment", "Technician assignment",
            status="ASSIGNED_SIMULATED", summary="Qualified rotating-equipment technician assigned.",
            parent_ids=[work_package["id"], "DEMO-INTERVENTION-01"],
            work_package_id=work_package["id"], intervention_id="DEMO-INTERVENTION-01",
            technician_id="TECH-DEMO-03", qualification="Rotating equipment mechanical maintenance",
            availability="AVAILABLE")
        schedule = self._artifact("DEMO-SCHEDULE-01", "scheduling_record", "Maintenance schedule",
            status="CONFIRMED_SIMULATED", summary="A 45-minute simulated maintenance window is confirmed.",
            parent_ids=[work_package["id"], "DEMO-INTERVENTION-01"],
            work_package_id=work_package["id"], intervention_id="DEMO-INTERVENTION-01",
            window_start="2026-01-15T10:00:00+00:00", window_end="2026-01-15T10:45:00+00:00",
            duration_minutes=45, operational_constraint="Maintain standby compressor availability.")
        return {"artifact_id": work_package["id"], "work_package_id": work_package["id"],
                "inventory_reservation_id": inventory["id"], "technician_assignment_id": assignment["id"],
                "scheduling_record_id": schedule["id"], "technician_id": "TECH-DEMO-03",
                "qualification": "Rotating equipment mechanical maintenance",
                "technician_availability": "AVAILABLE", "inventory_status": "IN_STOCK",
                "parts": [{"part_id": "DEMO-PART-BRG-04", "description": "Bearing and seal service kit",
                           "quantity": 1, "available_quantity": 2, "status": "RESERVED_SIMULATED"}],
                "schedule": "2026-01-15T10:00:00Z", "window_end": "2026-01-15T10:45:00Z",
                "estimated_duration_minutes": 45, "priority": "HIGH",
                "provenance": PROVENANCE,
                "runtime": RUNTIME, "live_model": False}

    def _execution_receipt(self) -> dict:
        return self._artifact("DEMO-RECEIPT-01", "execution_receipt", "Maintenance execution receipt",
            status="SUCCEEDED", summary="The exact approved bearing replacement was completed successfully.",
            parent_ids=["DEMO-WO-1042"], supporting_ids=["DEMO-APPROVAL-01"],
            related_ids=["DEMO-WP-1042", "DEMO-INTERVENTION-01"], receipt_id="DEMO-RECEIPT-01",
            adapter="operon.demo.work-order", external_ids={"work_order": "DEMO-WO-1042",
                "work_package": "DEMO-WP-1042"}, technician_id="TECH-DEMO-03", priority="HIGH",
            work_order_id="DEMO-WO-1042", work_package_id="DEMO-WP-1042",
            intervention_id="DEMO-INTERVENTION-01", approval_binding_id="DEMO-APPROVAL-01",
            performed_action="Replaced drive-end bearing kit, aligned shaft, lubricated assembly, and completed vibration check.",
            started_at="2026-01-15T10:00:00+00:00", completed_at="2026-01-15T10:43:00+00:00",
            resources_consumed=[{"part_id": "DEMO-PART-BRG-04", "quantity": 1}],
            approval_reference="DEMO-APPROVAL-01")

    def _work_order(self) -> dict:
        return self._artifact("DEMO-WO-1042", "work_order", "Bearing replacement work order",
            status="DISPATCHED_SIMULATED", summary="The exact approved work package was dispatched to the assigned technician.",
            parent_ids=["DEMO-APPROVAL-01"], supporting_ids=["DEMO-WP-1042"],
            related_ids=["DEMO-INTERVENTION-01", "DEMO-ASSIGNMENT-01", "DEMO-SCHEDULE-01"],
            work_order_id="DEMO-WO-1042", work_package_id="DEMO-WP-1042",
            intervention_id="DEMO-INTERVENTION-01", approval_binding_id="DEMO-APPROVAL-01",
            technician_assignment_id="DEMO-ASSIGNMENT-01", schedule_id="DEMO-SCHEDULE-01",
            dispatched_at=(BASE_TIME + timedelta(seconds=self._elapsed_seconds)).isoformat())

    @staticmethod
    def _intervention_hash() -> str:
        return hashlib.sha256(b"operon-demo-intervention-01").hexdigest()

    def _requirement(self) -> dict:
        return self._artifact("DEMO-REQUIREMENT-01", "approval_request", "Human approval request",
            status="PENDING", summary="Human approval is required for the exact diagnosis-bound work package.",
            parent_ids=["DEMO-WP-1042"], supporting_ids=["DEMO-VERDICT-INTERVENTION"],
            related_ids=["DEMO-INTERVENTION-01"], requirement_id="DEMO-REQUIREMENT-01",
            intervention_id="DEMO-INTERVENTION-01", intervention_hash=self._intervention_hash(),
            work_package_id="DEMO-WP-1042", work_package_version="1",
            policy_version="operon.demo.human-gate-v1", minimum_distinct_approvers=1,
            conditions=["Approve the exact diagnosis-bound intervention and hash.",
                        "Confirm TECH-DEMO-03 and DEMO-PART-BRG-04 remain reserved.",
                        "Maintain standby compressor coverage during the 45-minute window."])

    def _alert(self) -> dict:
        return self._state["alerts"][0]

    def _view(self) -> dict:
        return self._alert()["lifecycle"]["read_model"]

    def _record(self, record_id: str, **values) -> dict:
        return {"id": record_id, "created_at": (BASE_TIME + timedelta(seconds=self._elapsed_seconds)).isoformat(),
                "provenance": PROVENANCE, "runtime": RUNTIME, "live_model": False, **values}

    def _artifact(self, artifact_id: str, artifact_type: str, title: str, *, status: str,
                  summary: str, source: str = "operon.demo.scripted",
                  parent_ids: list[str] | tuple[str, ...] = (),
                  supporting_ids: list[str] | tuple[str, ...] = (),
                  related_ids: list[str] | tuple[str, ...] = (), **payload) -> dict:
        """Register detail data while returning the existing compact projection shape."""
        created_at = (BASE_TIME + timedelta(seconds=self._elapsed_seconds)).isoformat()
        incident_id = self._state["demo_scenario"].get("incident_id") if self._state else None
        equipment_id = self._state["demo_scenario"].get("equipment_id") if self._state else None
        compact = {"id": artifact_id, "artifact_id": artifact_id, "created_at": created_at,
                   "status": status, "summary": summary,
                   "provenance": PROVENANCE, "runtime": RUNTIME, "live_model": False, **payload}
        envelope = {"id": artifact_id, "artifact_type": artifact_type, "title": title, "status": status,
                    "created_at": created_at, "incident_id": incident_id, "equipment_id": equipment_id,
                    "source": source, "provenance": PROVENANCE, "runtime": RUNTIME, "live_model": False,
                    "parent_ids": list(parent_ids), "supporting_ids": list(supporting_ids),
                    "related_ids": list(related_ids), "summary": summary, "payload": deepcopy(payload)}
        self._artifacts.register(envelope)
        return compact

    def _sync_artifact_projections(self, value) -> None:
        if isinstance(value, dict):
            if value.get("artifact_id") and value.get("id") == value.get("artifact_id"):
                self._artifacts.sync_projection(value)
            for child in value.values():
                self._sync_artifact_projections(child)
        elif isinstance(value, list):
            for child in value:
                self._sync_artifact_projections(child)

    async def _wait(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self.time_scale)
        self._elapsed_seconds += seconds

    def _assert_current(self, generation: int) -> None:
        if generation != self._generation or self._state is None:
            raise asyncio.CancelledError

    async def _emit(self) -> None:
        if self._state is not None:
            self._state["demo_scenario"]["elapsed_seconds"] = self._elapsed_seconds
            self._sync_artifact_projections(self._state)
        if self._publish is not None:
            await self._publish()
