"""
Demo engine — the beating heart of the loop.

Owns the fleet simulation, the ML scoring, concurrent alert management + triage,
the durable incident lifecycle trigger, and the governed write-back. UI-agnostic:
it emits plain dict events that any transport (the FastAPI WebSocket, a notebook,
a test) can consume.

Step 13B: the default path is the authoritative lifecycle. A model signal opens a
durable incident, deterministic baseline investigation moves it to INVESTIGATING,
and only PromotionService/LifecycleService commands create diagnosis, intervention,
approval and execution authority. The pre-13B proposal shortcut
(prepare_legacy_intervention) is deprecated compatibility/demo code and runs only
when OPERON_LEGACY_DEMO is explicitly enabled.

Step 14: execution success reaches OBSERVING only. Every tick the engine asks the
lifecycle to verify the outcome of each OBSERVING incident deterministically from
persisted evidence; the lifecycle, not the engine or the simulator, decides
CLOSED / re-investigation / escalation. The simulator's post-dispatch response is
explicitly simulated demo provenance and is never read by verification.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import logging

from . import config, agent, services
from .db import get_conn, reset_transactional
from .model import load_or_train
from .simulator import PlantSimulator
from .seed_data import CLASS_DEFAULT_MODE, SENSOR_FEATURES
from .tools import get_failure_mode_by_code
from .reliability.coordinator import IncidentCoordinator, legacy_projection
from .reliability.evidence import EvidenceService
from .reliability.execution import ExecutionAmbiguous, ExecutionBusy, ExecutionFailed, GovernedExecutor
from .reliability.governance import ApprovalLedger
from .reliability.legacy import prepare_legacy_intervention
from .reliability.lifecycle import (
    ApprovalRefused, GovernanceBlocked, LifecycleRefused, LifecycleService, ExecutionRefused,
    ReconciliationRequired, POLICY_VERSION as LIFECYCLE_POLICY,
)
from .reliability import models as m
from .reliability.models import ApprovalRequirement, IncidentPhase, Intervention, ModelSignal
from .reliability.promotion import PromotionRefused
from .reliability.repository import IncidentRepository, InvalidReference, StaleRevision
from .reliability.signals import from_prediction, model_version

HISTORY_CAP = 90
# Bounded automatic supervisor attempts per incident revision; further reasoning
# requires an explicit trusted command (evidence, confirmation, retry).
MAX_AUTOMATIC_RUNS = 3
LIFECYCLE_STATUS = {
    IncidentPhase.OPEN: "ANALYZING", IncidentPhase.INVESTIGATING: "ANALYZING",
    IncidentPhase.AWAITING_EVIDENCE: "ANALYZING", IncidentPhase.DIAGNOSIS_VALIDATED: "ANALYZING",
    IncidentPhase.PLANNING: "ANALYZING", IncidentPhase.INTERVENTION_VALIDATED: "ANALYZING",
    IncidentPhase.AWAITING_APPROVAL: "PENDING_APPROVAL", IncidentPhase.READY: "APPROVED",
    IncidentPhase.EXECUTING: "APPROVED", IncidentPhase.OBSERVING: "APPROVED",
    IncidentPhase.EXECUTION_FAILED: "EXECUTION_FAILED", IncidentPhase.ESCALATED: "ESCALATED",
    IncidentPhase.CLOSED: "CLOSED", IncidentPhase.CANCELLED: "CANCELLED",
}
LIFECYCLE_ERRORS = (LifecycleRefused, ApprovalRefused, GovernanceBlocked, ExecutionRefused, ReconciliationRequired,
                    ExecutionBusy, PromotionRefused, StaleRevision, InvalidReference, LookupError, KeyError, TypeError,
                    ValueError)
logger = logging.getLogger(__name__)


def status_for(prob: float) -> str:
    if prob >= config.TRIGGER_THRESHOLD:
        return "CRITICAL"
    if prob >= config.WARN_THRESHOLD:
        return "WARNING"
    return "HEALTHY"


class DemoEngine:
    def __init__(self, *, runtime=None, specialist_runtime=None, legacy_demo: bool | None = None, clock=None):
        # Tick clock seam: tests advance it deterministically instead of sleeping.
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.model = load_or_train()
        self.sim = PlantSimulator()
        self.clients: set = set()
        self.running = False
        self.tick_i = 0
        self.assets: dict[str, dict] = {}
        self.histories: dict[str, list] = {}
        self.alerts: dict[str, dict] = {}          # eid -> alert record
        self.status_override: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._analyzing: set[str] = set()
        self.meta = self._load_meta()
        self.coordinator = IncidentCoordinator(IncidentRepository())
        self.lifecycle = LifecycleService(self.coordinator.repository)
        self.evidence_service = EvidenceService(self.coordinator.repository)
        self.legacy_demo = config.legacy_demo_enabled() if legacy_demo is None else bool(legacy_demo)
        if self.legacy_demo:
            logger.warning("OPERON_LEGACY_DEMO is enabled: the deprecated proposal shortcut is active; "
                           "its artifacts carry no application promotion lineage")
        self.runtime = runtime if runtime is not None else self._default_runtime()
        self._base_runtime = self.runtime
        self.specialist_runtime = specialist_runtime
        self._guided_demo: dict | None = None
        self._guided_task: asyncio.Task | None = None
        self.demo_step_delay = 5.0
        self.incidents = {}
        self._resume: set[str] = set()
        self._lifecycle_tasks: dict[str, asyncio.Task] = {}
        self._attempts: dict[str, tuple[int | None, int]] = {}
        # Outcome messages produced by the synchronous tick progression, flushed by the tick.
        self._pending_broadcasts: list[dict] = []
        # Supervisor runs are serialized: 13A's source checkpoint treats another
        # incident's revision change during a run as staleness.
        self._reasoning_lock = asyncio.Lock()
        self._model_version = model_version(config.MODEL_PATH)
        self._observed_at = self._clock()
        self._recover_incidents()

    @staticmethod
    def _default_runtime():
        """Reasoning backend only when explicitly configured; never a silent fallback.

        Returns a ``core.reasoning.backend.ReasoningBackend`` (Step 15) selected by
        OPERON_REASONING_BACKEND; unset keeps the legacy Bedrock selector behaviour.
        """
        if config.reasoning_backend() == "none":
            return None
        try:
            from .reasoning.backend import backend_from_environment
            return backend_from_environment()
        except Exception:
            logger.exception("Supervisor reasoning backend unavailable; incidents will wait in INVESTIGATING")
            return None

    def _recover_incidents(self):
        for incident, checkpoint in self.coordinator.recover():
            # This runner only resumes its own single-asset signals.
            if not incident.signal_evidence_ids or len(incident.equipment_ids) != 1:
                continue
            eid = incident.equipment_ids[0]
            self.incidents[eid] = incident
            if eid not in self.sim.assets:
                continue
            if checkpoint is None and incident.legacy_alert_id is None and not self.legacy_demo:
                self._recover_lifecycle(eid, incident)
                continue
            if checkpoint:
                self.alerts[eid] = legacy_projection(checkpoint)
                st = self.sim.assets[eid]
                st.prog, st.tick = checkpoint.simulator_progress, checkpoint.simulator_tick
                self.tick_i = max(self.tick_i, st.tick)
                mode, status = {"APPROVED": ("recovering", "SCHEDULED"),
                                "REJECTED": ("failing", "CRITICAL"),
                                "FAILED": ("arrested", "DOWN")}.get(checkpoint.status, ("arrested", "CRITICAL"))
                self.sim.set_mode(eid, mode)
                self.status_override[eid] = status
            if incident.phase == IncidentPhase.OPEN and (checkpoint is None or checkpoint.status == "ANALYZING"):
                self._resume.add(eid)
        self._retriage()

    def _recover_lifecycle(self, eid: str, incident):
        """Reconstruct from durable pointers and lineage. Never dispatches automatically."""
        status = self.lifecycle.reconcile(incident.id)
        incident = self.coordinator.repository.fetch_incident(incident.id)
        self.incidents[eid] = incident
        if incident.phase in (IncidentPhase.OPEN, IncidentPhase.INVESTIGATING):
            self._resume.add(eid)
        mode, override = "arrested", "CRITICAL"
        if incident.phase == IncidentPhase.OBSERVING:
            # Simulated plant response to the confirmed package, not verified recovery:
            # verification resumes from durable evidence on the next tick.
            mode, override = self.sim.respond_to_intervention(eid), "SCHEDULED"
        elif incident.phase == IncidentPhase.ESCALATED and self._rejected(incident.id):
            mode, override = "failing", "CRITICAL"
        if mode != self.sim.assets[eid].mode:
            self.sim.set_mode(eid, mode)
        self.status_override[eid] = override
        self.alerts[eid] = self._lifecycle_alert(eid, status=status)
        if status.reconciliation_required:
            logger.warning("Incident %s requires execution reconciliation (claim %s); no automatic replay",
                           incident.id, status.claim_state)

    def _rejected(self, incident_id: str) -> bool:
        return any(d.decision == "REJECT" for d in self.coordinator.repository.list_approval_decisions(incident_id))

    def _checkpoint_alert(self, eid: str):
        # Hand-built legacy alerts remain supported by old callers/tests (legacy demo only).
        if self.legacy_demo and eid in self.incidents and self.alerts.get(eid, {}).get("lifecycle") is None:
            self.incidents[eid] = self.coordinator.checkpoint_legacy(
                self.incidents[eid], self.alerts[eid], self.sim.assets[eid])

    def _load_meta(self) -> dict:
        with get_conn() as c:
            rows = c.execute("SELECT equipment_id, equipment_name, equipment_class, "
                             "criticality, product_tier FROM equipment").fetchall()
        return {r["equipment_id"]: dict(r) for r in rows}

    # -- lifecycle ---------------------------------------------------------
    async def start(self):
        if self._task and not self._task.done():
            return
        self.running = True
        self._task = asyncio.create_task(self._run())
        await self.broadcast({"type": "control", "running": True})

    async def stop(self):
        """Pause the simulation loop without touching state — resume with start()."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.running = False
        await self.broadcast({"type": "control", "running": False})

    async def reset(self):
        guided = self._guided_task
        if guided and guided is not asyncio.current_task() and not guided.done():
            guided.cancel()
        self._guided_task = None
        self._guided_demo = None
        self.runtime = self._base_runtime
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for task in self._lifecycle_tasks.values():
            task.cancel()
        await self.drain()
        reset_transactional()
        self.sim = PlantSimulator()
        self.tick_i = 0
        self.assets = {}
        self.histories = {}
        self.alerts = {}
        self.status_override = {}
        self._analyzing = set()
        self.incidents = {}
        self._resume = set()
        self._lifecycle_tasks = {}
        self._attempts = {}
        self._pending_broadcasts = []
        await self.broadcast({"type": "reset"})
        await self.start()

    def _demo_projection(self) -> dict:
        if self._guided_demo is None:
            return {"active": False}
        value = dict(self._guided_demo)
        eid = value.get("equipment_id")
        incident = self.incidents.get(eid)
        if incident is not None:
            current = self.coordinator.repository.fetch_incident(incident.id)
            value.update({"incident_id": current.id, "phase": current.phase.value})
            if current.phase == IncidentPhase.AWAITING_APPROVAL:
                value["status"] = "awaiting_human_approval"
            elif current.phase == IncidentPhase.OBSERVING:
                value["status"] = "observing"
            elif current.phase == IncidentPhase.CLOSED:
                value["status"] = "complete"
        return {"active": True, **value}

    async def _broadcast_demo(self):
        await self.broadcast({"type": "demo", "demo_scenario": self._demo_projection()})

    async def start_guided_demo(self, equipment_id: str) -> dict:
        """Prepare one explicit simulator-backed recording flow.

        This controls only simulator inputs and trusted typed submissions.  Every
        authoritative transition remains inside LifecycleService.
        """
        if equipment_id not in self.sim.assets:
            return {"ok": False, "error": "unknown demo equipment"}
        await self.reset()
        await self.stop()
        from .demo_scenario import DemoReasoningBackend
        self.runtime = DemoReasoningBackend()
        for eid, state in self.sim.assets.items():
            state.mode, state.prog = "healthy", 0.0
        selected = self.sim.assets[equipment_id]
        mode_id = CLASS_DEFAULT_MODE[selected.profile.equipment_class]
        selected.profile.scenario = mode_id.removeprefix("FM-")
        selected.profile.start_tick, selected.profile.ramp_ticks = 1, 6
        selected.profile.intervention_response = "RECOVERS"
        selected.mode, selected.prog = "degrading", 0.05
        self._guided_demo = {"equipment_id": equipment_id, "status": "degrading",
                             "reasoning_provenance": "SIMULATED_TYPED_ADVISORY",
                             "physical_provenance": "SIMULATED"}
        await self.start()
        self._guided_task = asyncio.create_task(self._guide_to_approval(equipment_id))
        await self._broadcast_demo()
        return {"ok": True, "demo_scenario": self._demo_projection()}

    async def _wait_demo_phase(self, equipment_id: str, phases: set[IncidentPhase], timeout=45):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            incident = self.incidents.get(equipment_id)
            if incident is not None:
                current = self.coordinator.repository.fetch_incident(incident.id)
                if current.phase in phases:
                    return current
                if current.phase in {IncidentPhase.ESCALATED, IncidentPhase.EXECUTION_FAILED, IncidentPhase.CANCELLED}:
                    raise RuntimeError(f"guided demo reached {current.phase.value}")
            await asyncio.sleep(0.1)
        raise TimeoutError("guided demo timed out waiting for authoritative lifecycle")

    async def _guide_to_approval(self, equipment_id: str):
        from .demo_scenario import binding_fields, resource_confirmation, technical_confirmation
        try:
            await asyncio.sleep(self.demo_step_delay)
            # Accelerate only the simulator degradation; incident admission still
            # depends on the real persisted model prediction crossing its threshold.
            self.sim.assets[equipment_id].prog = 1.0
            await self._wait_demo_phase(equipment_id, {IncidentPhase.AWAITING_EVIDENCE})
            self._guided_demo["status"] = "trusted_inspection"
            await self._broadcast_demo()
            await asyncio.sleep(self.demo_step_delay)
            confirmation = technical_confirmation(self, equipment_id)
            response = self.submit_technical_confirmation(
                confirmation, expected_revision=self.coordinator.repository.fetch_incident(confirmation.incident_id).revision)
            await self._refresh_lifecycle(equipment_id, "demo_technical_confirmation",
                                          reason="explicit SIMULATED trusted inspection submitted")
            if not response["ok"]:
                raise RuntimeError("technical confirmation was refused")
            await self._wait_demo_phase(equipment_id, {IncidentPhase.DIAGNOSIS_VALIDATED})
            self._guided_demo["status"] = "planning"
            await self._broadcast_demo()
            await asyncio.sleep(self.demo_step_delay)
            # Freeze the simulated source briefly while the trusted application
            # binds and reviews the exact work package. This satisfies the same
            # dependency-freshness checks as a live caller; it grants no authority.
            await self.stop()
            resource = resource_confirmation(self, equipment_id)
            response = self.submit_resource_confirmation(
                resource, expected_revision=self.coordinator.repository.fetch_incident(resource.incident_id).revision)
            resource_evidence = self.coordinator.repository.get_artifact(resource.incident_id, response["evidence_id"])
            await self._refresh_lifecycle(equipment_id, "demo_resource_confirmation",
                                          reason="explicit SIMULATED resource attestation submitted")
            incident = self.coordinator.repository.fetch_incident(resource.incident_id)
            result = await self.plan(incident.id, expected_revision=incident.revision,
                                     **binding_fields(self, equipment_id, resource_evidence))
            if not result["ok"]:
                raise RuntimeError(result.get("outcome", {}).get("reason", "demo plan was refused"))
            self._guided_demo["status"] = "awaiting_human_approval"
            await self.start()
            await self._broadcast_demo()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Guided demo preparation failed")
            if self._guided_demo is not None:
                self._guided_demo.update({"status": "failed", "error": str(exc)})
                await self.start()
                await self._broadcast_demo()

    async def _run(self):
        try:
            while True:
                await asyncio.sleep(config.TICK_SECONDS)
                await self._advance()
        except asyncio.CancelledError:
            pass

    # -- core tick ---------------------------------------------------------
    async def _advance(self):
        self.tick_i += 1
        feats = self.sim.tick()
        self._observed_at = self._clock()
        now = self._observed_at.isoformat(timespec="seconds")
        fleet_msg, readings, healths = [], [], []
        for eid, f in feats.items():
            pred = self.model.predict(f)
            mode = self.model.predict_mode(f)
            meta = self.meta.get(eid, {})
            base_status = status_for(pred["failure_prob"])
            status = self.status_override.get(eid, base_status)
            self.assets[eid] = {**f, **pred, "predicted_mode": mode, "equipment_id": eid,
                                "name": meta.get("equipment_name"),
                                "equipment_class": meta.get("equipment_class"),
                                "criticality": meta.get("criticality"), "status": status}
            point = {"t": self.tick_i, "prob": round(pred["failure_prob"], 3),
                     "health": round(pred["health_score"], 3),
                     "torque": f["torque"], "tool_wear": f["tool_wear"],
                     "temp_diff": round(f["process_temp"] - f["air_temp"], 2),
                     "rot_speed": f["rot_speed"]}
            self.histories.setdefault(eid, []).append(point)
            self.histories[eid] = self.histories[eid][-HISTORY_CAP:]
            fleet_msg.append(self._asset_summary(eid))
            for feature_key, sensor_type, _unit in SENSOR_FEATURES:
                readings.append((f"{eid}-{sensor_type}", now,
                                 float(f[feature_key]), "GOOD"))
            healths.append((eid, now, pred["health_score"], pred["failure_prob"], mode["mode"]))
        self._persist(readings, healths)

        await self.broadcast({"type": "tick", "tick": self.tick_i,
                              "plant_time_min": self.tick_i * config.MINUTES_PER_TICK,
                              "agent_mode": config.agent_mode(), "fleet": fleet_msg,
                              "business": self._business_summary()})

        # detect NEW alerts (assets crossing the threshold while still degrading)
        for eid, a in self.assets.items():
            st = self.sim.assets[eid]
            if (eid in self._resume or
                    (a["failure_prob"] >= config.TRIGGER_THRESHOLD and eid not in self.alerts
                     and eid not in self._analyzing and st.mode == "degrading")):
                try:
                    await self._fire_agent(eid)
                except Exception:
                    logger.exception("Incident admission/planning persistence failed for %s", eid)
                    await self.broadcast({"type": "error", "equipment_id": eid,
                                          "error": "incident admission or legacy planning failed; retrying"})
        if not self.legacy_demo:
            self._progress_lifecycle()
            for message in self._pending_broadcasts:
                await self.broadcast(message)
            self._pending_broadcasts = []

        # unplanned failures for rejected assets
        for eid in list(self.alerts):
            if self.alerts[eid]["status"] == "REJECTED" and self.sim.failed(eid):
                await self._unplanned_failure(eid)

    def _asset_summary(self, eid: str) -> dict:
        a = self.assets[eid]
        return {"equipment_id": eid, "name": a["name"], "equipment_class": a["equipment_class"],
                "criticality": a["criticality"], "status": a["status"],
                "health_score": round(a["health_score"], 3),
                "failure_prob": round(a["failure_prob"], 3),
                "predicted_mode": a["predicted_mode"]["mode"],
                "predicted_mode_label": a["predicted_mode"]["mode_label"],
                "torque": a["torque"], "tool_wear": a["tool_wear"],
                "rot_speed": a["rot_speed"],
                "temp_diff": round(a["process_temp"] - a["air_temp"], 2),
                "point": self.histories[eid][-1] if self.histories.get(eid) else None}

    def _persist(self, readings, healths):
        """Persist both streams independently and report any degraded write.

        Telemetry and health scores deliberately use separate transactions: one
        bad sensor record is visible in logs but cannot roll back valid health
        scores or stop the demo loop.
        """
        result = {"telemetry": True, "health_scores": True}
        try:
            with get_conn() as c:
                c.executemany("INSERT INTO sensor_reading VALUES (?,?,?,?)", readings)
        except Exception:
            result["telemetry"] = False
            logger.exception(
                "Telemetry persistence failed for %d readings (sensor IDs: %s); "
                "continuing the demo loop",
                len(readings), ", ".join(str(row[0]) for row in readings),
            )
        try:
            with get_conn() as c:
                c.executemany("INSERT INTO health_score "
                              "(equipment_id, scored_at, health_score, failure_prob, predicted_mode) "
                              "VALUES (?,?,?,?,?)", healths)
        except Exception:
            result["health_scores"] = False
            logger.exception(
                "Health-score persistence failed for %d scores (equipment IDs: %s); "
                "continuing the demo loop",
                len(healths), ", ".join(str(row[0]) for row in healths),
            )
        return result

    # -- agent + triage ----------------------------------------------------
    def _build_ctx(self, eid: str, signal: ModelSignal | None = None) -> dict:
        a = self.assets[eid]
        mode_code = signal.candidate_failure_mode if signal else a["predicted_mode"]["mode"]
        fm = get_failure_mode_by_code(mode_code)
        if not fm:  # NONE / unknown -> fall back to the class's characteristic mode
            fallback_id = CLASS_DEFAULT_MODE.get(a["equipment_class"], "FM-OSF")
            fm = get_failure_mode_by_code(fallback_id.split("-")[1])
        drivers = [item.model_dump(exclude={"schema_version"}) for item in signal.attribution] if signal else self.model.attribute(a)
        mode_prediction = ({"mode": mode_code, "distribution": signal.mode_distribution}
                           if signal else a["predicted_mode"])
        prediction = ({"failure_prob": signal.risk_score, "health_score": signal.health_score}
                      if signal else {"failure_prob": a["failure_prob"], "health_score": a["health_score"]})
        return {"equipment_id": eid, "equipment_name": a["name"],
                "equipment_class": a["equipment_class"], "criticality": a["criticality"],
                "failure_mode": fm, "mode_prediction": mode_prediction,
                "prediction": prediction,
                "drivers": drivers}

    async def _fire_agent(self, eid: str):
        try:
            if self.legacy_demo:
                await self._plan_legacy_alert(eid)
            else:
                await self._admit_lifecycle(eid)
        finally:
            self._analyzing.discard(eid)

    # -- authoritative lifecycle (default) ---------------------------------
    def _signal(self, eid: str, ctx: dict) -> ModelSignal:
        return from_prediction(eid, self.assets[eid], ctx["drivers"], observed_at=self._observed_at,
                               source=f"{type(self.model).__module__}.{type(self.model).__qualname__}",
                               version=self._model_version)

    async def _admit_lifecycle(self, eid: str):
        ctx = self._build_ctx(eid)
        incident, created = self.lifecycle.admit(
            self._signal(eid, ctx), severity="CRITICAL" if ctx["criticality"] == "HIGH" else "HIGH",
            triage_score=agent.triage_score(ctx))
        self.incidents[eid] = incident
        self._analyzing.add(eid)
        self.sim.set_mode(eid, "arrested")
        self.status_override[eid] = "CRITICAL"
        if created:
            try:
                services.notifications().raise_alert(
                    equipment_id=eid, severity="CRITICAL" if ctx["criticality"] == "HIGH" else "HIGH",
                    summary=(f"{ctx['failure_mode'].get('mode_code', '?')} candidate on {eid} at "
                             f"{ctx['prediction']['failure_prob']:.0%} model risk score."),
                    source="operon-signal-admission")
            except Exception:
                logger.exception("Operational alert persistence failed for %s; continuing the demo loop", eid)
        self.alerts[eid] = self._lifecycle_alert(eid, ctx)
        await self.broadcast({"type": "alert", "alert": self.alerts[eid], "phase": "analyzing"})
        if incident.phase == IncidentPhase.OPEN:
            # Deterministic baseline evidence only; the classifier is never a diagnosis.
            self.incidents[eid] = self.lifecycle.investigate(incident.id).incident
        self._resume.discard(eid)
        self.alerts[eid] = self._lifecycle_alert(eid, ctx)
        self._retriage()
        await self.broadcast({"type": "alert", "alert": self.alerts[eid], "phase": "investigating",
                              "triage": self._triage_msg()})
        self._schedule_diagnosis(eid)

    def _schedule_diagnosis(self, eid: str):
        incident = self.incidents.get(eid)
        if self.runtime is None or incident is None or incident.phase != IncidentPhase.INVESTIGATING:
            return
        task = self._lifecycle_tasks.get(eid)
        if task is not None and not task.done():
            return
        last_revision, attempts = self._attempts.get(eid, (None, 0))
        if last_revision == incident.revision or attempts >= MAX_AUTOMATIC_RUNS:
            return
        self._attempts[eid] = (incident.revision, attempts + 1)
        self._lifecycle_tasks[eid] = asyncio.create_task(self._diagnose(eid))

    async def _diagnose(self, eid: str):
        incident = self.incidents[eid]
        outcome = None
        try:
            async with self._reasoning_lock:
                current = self.coordinator.repository.fetch_incident(incident.id)
                if current.phase != IncidentPhase.INVESTIGATING:
                    return
                outcome = await self.lifecycle.diagnose(
                    incident.id, asset_id=eid, runtime=self.runtime, evidence_service=self.evidence_service,
                    specialist_runtime=self.specialist_runtime)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Durable supervisor diagnosis failed for %s; incident remains %s", eid, incident.phase.value)
        await self._refresh_lifecycle(eid, outcome.disposition.lower() if outcome else "error",
                                      reason=outcome.reason if outcome else None)

    async def drain(self):
        """Await pending lifecycle tasks (tests/reset); model runs are never awaited under a lock."""
        tasks = [task for task in self._lifecycle_tasks.values() if not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _progress_lifecycle(self):
        for eid, incident in list(self.incidents.items()):
            if self.alerts.get(eid, {}).get("lifecycle") is None:
                continue
            current = self.coordinator.repository.fetch_incident(incident.id)
            if current.revision != incident.revision:
                self.incidents[eid] = current
                self.alerts[eid] = self._lifecycle_alert(eid)
            if current.phase == IncidentPhase.OBSERVING:
                self._verify_outcome(eid)
            self._schedule_diagnosis(eid)

    def _verify_outcome(self, eid: str):
        """Deterministic, model-free outcome verification of one OBSERVING incident (tick-driven).

        Only durable evidence and the lifecycle policy decide; a refusal leaves the
        incident OBSERVING and is logged for reconciliation.
        """
        incident = self.incidents.get(eid)
        if incident is None:
            return None
        try:
            verification = self.lifecycle.verify_outcome(incident.id)
        except LIFECYCLE_ERRORS as exc:
            logger.warning("Outcome verification refused for %s (incident %s): %s", eid, incident.id, exc)
            self.incidents[eid] = self.coordinator.repository.fetch_incident(incident.id)
            self.alerts[eid] = self._lifecycle_alert(eid, reason=f"outcome verification refused: {exc}")
            return None
        if verification.disposition in ("OBSERVING", "RETRY"):
            return verification
        self._apply_outcome(eid, verification)
        return verification

    def _apply_outcome(self, eid: str, verification):
        """Project an authoritative lifecycle outcome onto the demo state. Grants nothing."""
        self.incidents[eid] = self.coordinator.repository.fetch_incident(verification.incident_id)
        alert = self.alerts.get(eid) or {}
        result = dict(alert.get("result") or {})
        result.update({"outcome": verification.result, "outcome_id": verification.outcome_id,
                       "verification_reason": verification.reason, "policy_version": verification.policy_version})
        alert["result"] = result
        if verification.disposition == "CLOSED":
            # The plant status is no longer overridden: the fleet shows what the model scores now.
            self.status_override.pop(eid, None)
        elif verification.disposition == "REINVESTIGATE":
            self.sim.set_mode(eid, "arrested")
            self.status_override[eid] = "CRITICAL"
        elif verification.disposition == "ESCALATED":
            self.sim.set_mode(eid, "arrested")
            self.status_override[eid] = "CRITICAL"
        self.alerts[eid] = self._lifecycle_alert(eid, reason=verification.reason)
        self.alerts[eid]["result"] = result
        self._retriage()
        self._pending_broadcasts.append({"type": "outcome", "equipment_id": eid, "result": result,
                                         "phase": self.incidents[eid].phase.value, "alert": self.alerts[eid],
                                         "business": self._business_summary(), "triage": self._triage_msg()})
        if self._guided_demo and self._guided_demo.get("equipment_id") == eid:
            self._guided_demo["status"] = "complete" if verification.disposition == "CLOSED" else verification.disposition.lower()

    async def verify_outcome(self, incident_id: str) -> dict:
        """Explicit deterministic verification attempt (API); the same authority as the tick path."""
        eid = self._eid_for(incident_id)
        try:
            verification = await asyncio.to_thread(self.lifecycle.verify_outcome, incident_id)
        except LIFECYCLE_ERRORS as exc:
            if eid:
                await self._refresh_lifecycle(eid, "outcome_refused", reason=str(exc))
                return {"ok": False, "error": str(exc), "incident": self.lifecycle.projection(incident_id)}
            return {"ok": False, "error": str(exc)}
        if eid and verification.disposition not in ("OBSERVING", "RETRY"):
            self._apply_outcome(eid, verification)
            for message in self._pending_broadcasts:
                await self.broadcast(message)
            self._pending_broadcasts = []
        elif eid:
            await self._refresh_lifecycle(eid, "observing", reason=verification.reason)
        return {"ok": True, "verification": verification.model_dump(mode="json"),
                "incident": self.lifecycle.projection(incident_id)}

    async def _refresh_lifecycle(self, eid: str, phase: str, *, reason: str | None = None, message_type="alert"):
        incident = self.incidents.get(eid)
        if incident is None:
            return
        self.incidents[eid] = self.coordinator.repository.fetch_incident(incident.id)
        self.alerts[eid] = self._lifecycle_alert(eid, reason=reason)
        self._retriage()
        await self.broadcast({"type": message_type, "alert": self.alerts[eid], "equipment_id": eid,
                              "phase": phase, "triage": self._triage_msg()})

    def _incident_read_model(self, incident) -> dict:
        """Presentation-only view over committed records; grants no lifecycle authority."""
        repo = self.coordinator.repository
        artifacts = repo.list_artifacts(incident.id)
        of_type = lambda cls: [item for item in artifacts if isinstance(item, cls)]
        evidence, diagnoses = of_type(m.Evidence), of_type(m.Diagnosis)
        verdicts, interventions = of_type(m.ValidationVerdict), of_type(m.Intervention)
        requirements, actions = of_type(m.ApprovalRequirement), of_type(m.AgentAction)
        snapshots, reports = of_type(m.SupervisorRunSnapshot), of_type(m.SupervisorReport)
        bindings, plans, outcomes = (of_type(m.WorkPackageBinding), of_type(m.ObservationPlan), of_type(m.Outcome))
        current_diagnosis = next((item for item in diagnoses if item.id == incident.current_diagnosis_id), None)
        current_intervention = next((item for item in interventions if item.id == incident.current_intervention_id), None)
        current_binding = next((item for item in bindings
                                if current_intervention and item.id == current_intervention.binding_id), None)
        snapshots_by_run = {item.run_id: item for item in snapshots}
        agent_runs = []
        for report in reports:
            result, snapshot = report.result_payload, snapshots_by_run.get(report.run_id)
            agent_runs.append({
                "run_id": report.run_id, "stage": snapshot.stage if snapshot else None,
                "status": report.completion, "input_revision": report.input_revision,
                "checkpoint_revision": report.checkpoint_revision,
                "runtime_identity": snapshot.runtime_identity if snapshot else {},
                "version_identity": snapshot.version_identity if snapshot else {},
                "disposition": result.get("disposition"),
                "summary": (result.get("decision") or {}).get("reasoning_summary"),
                "delegations": result.get("delegations", []), "assessments": result.get("assessments", []),
                "evidence_requests": result.get("evidence_requests", []), "blockers": result.get("blockers", []),
                "human_review_required": result.get("human_review_required", True),
                "tool_calls": result.get("tool_calls", 0), "stale_reasons": list(report.stale_reasons),
            })
        return {
            "incident": incident.model_dump(mode="json"),
            "events": [item.model_dump(mode="json") for item in repo.list_events(incident.id)[-80:]],
            "evidence": [{
                "id": item.id, "kind": item.kind, "summary": item.summary,
                "quality": item.quality, "provenance": item.provenance,
                "source_uri": item.source_uri, "source_locator": item.source_locator,
                "source_version": item.source_version, "source_capability": item.source_capability,
                "source_system": item.source_system,
                "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                "retrieved_at": item.retrieved_at.isoformat(), "payload": item.payload,
                "derived_from_ids": list(item.derived_from_ids),
            } for item in evidence],
            "hypotheses": [item.model_dump(mode="json") for item in of_type(m.Hypothesis)],
            "diagnosis": current_diagnosis.model_dump(mode="json") if current_diagnosis else None,
            "verdicts": [item.model_dump(mode="json") for item in verdicts],
            "intervention": current_intervention.model_dump(mode="json") if current_intervention else None,
            "binding": current_binding.model_dump(mode="json") if current_binding else None,
            "requirements": [item.model_dump(mode="json") for item in requirements],
            "approval_decisions": [item.model_dump(mode="json") for item in repo.list_approval_decisions(incident.id)],
            "execution_receipts": [item.model_dump(mode="json") for item in repo.list_execution_receipts(incident.id)],
            "observation_plans": [item.model_dump(mode="json") for item in plans],
            "outcomes": [item.model_dump(mode="json") for item in outcomes],
            "agent_actions": [item.model_dump(mode="json") for item in actions], "agent_runs": agent_runs,
            "correlation": {"incident_id": incident.id, "active_run_id": incident.active_run_id,
                            "demo_run_id": incident.demo_run_id,
                            "latest_run_id": agent_runs[-1]["run_id"] if agent_runs else None},
        }

    def _lifecycle_alert(self, eid: str, ctx: dict | None = None, *, status=None, reason: str | None = None) -> dict:
        """UI projection of durable state. Carries exact approval identifiers, never authority."""
        incident = self.incidents[eid]
        previous = self.alerts.get(eid) or {}
        view = self.lifecycle.projection(incident.id)
        meta = self.meta.get(eid, {})
        a = self.assets.get(eid, {})
        mode = ctx["failure_mode"] if ctx else None
        requirement = view.get("requirement")
        proposal = None
        if incident.current_intervention_id and (view.get("authority_valid") or view.get("execution_lineage_valid")):
            intervention = self.coordinator.repository.get_artifact(incident.id, incident.current_intervention_id)
            step = intervention.steps[0]
            proposal = {
                "trace": [{"actor": "operon", "title": e.payload["to"], "text": e.payload.get("reason", "")}
                          for e in self.coordinator.repository.list_events(incident.id) if e.event_type == "PHASE_CHANGED"],
                "governance": {"decision": "CONDITIONS" if requirement else "APPROVE",
                               "reasons": list(requirement["conditions"]) if requirement else ["Exact human approval recorded."],
                               "conditions": ["Exact human approval of this promoted work package is required."] if requirement else [],
                               "policy_version": LIFECYCLE_POLICY},
                "business": {"recovered_value": intervention.estimated_avoided_loss,
                             "estimated_cost": intervention.estimated_cost,
                             "downtime_hours_avoided": round(config.UNPLANNED_OUTAGE_HOURS - config.PLANNED_SWAP_HOURS, 2),
                             "business_assumption_version": intervention.business_assumption_version},
                "intervention": {"intervention_id": intervention.id, "intervention_hash": view.get("intervention_hash"),
                                 "capability": step.capability, "parameters": step.parameters,
                                 "window_start": intervention.window_start.isoformat() if intervention.window_start else None,
                                 "window_end": intervention.window_end.isoformat() if intervention.window_end else None},
            }
        status_label = LIFECYCLE_STATUS[incident.phase]
        if incident.phase == IncidentPhase.ESCALATED and self._rejected(incident.id):
            status_label = "REJECTED"
        return {
            "incident_id": incident.id, "equipment_id": eid,
            "equipment_name": previous.get("equipment_name") or meta.get("equipment_name"),
            "equipment_class": previous.get("equipment_class") or meta.get("equipment_class"),
            "criticality": previous.get("criticality") or meta.get("criticality"),
            "failure_prob": previous.get("failure_prob", round(float(a.get("failure_prob", 0)), 3)),
            "predicted_mode": (mode or {}).get("mode_code", previous.get("predicted_mode")),
            "predicted_mode_label": (mode or {}).get("failure_mode_name", previous.get("predicted_mode_label")),
            "status": status_label, "created_tick": previous.get("created_tick", self.tick_i),
            "triage_rank": previous.get("triage_rank"),
            "triage_score": previous.get("triage_score", float(incident.triage_score)),
            "proposal": proposal, "result": previous.get("result"),
            "intervention_id": incident.current_intervention_id,
            "approval_requirement_id": requirement["requirement_id"] if requirement else None,
            "execution_receipt_ids": list(view.get("receipt_ids", ())),
            "lifecycle": {
                "phase": incident.phase.value, "revision": incident.revision,
                "context_revision": incident.revision, "diagnosis_id": incident.current_diagnosis_id,
                "intervention_id": incident.current_intervention_id, "intervention_hash": view.get("intervention_hash"),
                "requirement_id": requirement["requirement_id"] if requirement else None,
                "authority_valid": view.get("authority_valid"), "authority_reason": view.get("authority_reason"),
                "reconciliation_required": view.get("reconciliation_required"),
                "execution_lineage_valid": view.get("execution_lineage_valid"),
                "plan_id": view.get("plan_id"), "outcome_id": view.get("outcome_id"),
                "outcome_result": view.get("outcome_result"),
                "supervisor_available": self.runtime is not None,
                "last_reason": reason or previous.get("lifecycle", {}).get("last_reason"),
                "read_model": self._incident_read_model(incident),
            },
        }

    # -- deprecated compatibility demo path (OPERON_LEGACY_DEMO) -------------
    async def _plan_legacy_alert(self, eid: str):
        ctx = self._build_ctx(eid)
        signal = from_prediction(eid, self.assets[eid], ctx["drivers"],
                                 observed_at=self._observed_at,
                                 source=f"{type(self.model).__module__}.{type(self.model).__qualname__}",
                                 version=self._model_version)
        incident, created = self.coordinator.admit(
            signal, severity="CRITICAL" if ctx["criticality"] == "HIGH" else "HIGH",
            triage_score=agent.triage_score(ctx))
        self.incidents[eid] = incident
        if not created and incident.legacy_alert_id and eid not in self._resume:
            checkpoint = self.coordinator.repository.get_artifact(incident.id, incident.legacy_alert_id)
            self.alerts[eid] = legacy_projection(checkpoint)
            return
        if incident.phase != IncidentPhase.OPEN:
            return
        if not created:
            evidence = self.coordinator.repository.get_artifact(incident.id, incident.signal_evidence_ids[0])
            ctx = self._build_ctx(eid, ModelSignal.model_validate(evidence.payload))
        self._resume.add(eid)
        self._analyzing.add(eid)
        self.sim.set_mode(eid, "arrested")
        self.status_override[eid] = "CRITICAL"
        # Record a governed operational alert (foundation for the monitoring layer).
        # Best-effort: a notification-backend hiccup must never stall the loop.
        try:
            sev = "CRITICAL" if ctx["criticality"] == "HIGH" else "HIGH"
            if created:
                services.notifications().raise_alert(
                    equipment_id=eid, severity=sev,
                    summary=(f"{ctx['failure_mode'].get('mode_code','?')} candidate on {eid} at "
                             f"{ctx['prediction']['failure_prob']:.0%} model risk score."),
                    source="operon-signal-admission")
        except Exception:
            logger.exception(
                "Operational alert persistence failed for %s; continuing the demo loop", eid
            )
        # announce the alert immediately (agent is "thinking")
        alert = {"incident_id": incident.id, "equipment_id": eid, "equipment_name": ctx["equipment_name"],
                 "equipment_class": ctx["equipment_class"], "criticality": ctx["criticality"],
                 "failure_prob": round(ctx["prediction"]["failure_prob"], 3),
                 "predicted_mode": ctx["failure_mode"].get("mode_code"),
                 "predicted_mode_label": ctx["failure_mode"].get("failure_mode_name"),
                 "status": "ANALYZING", "created_tick": self.tick_i,
                 "triage_rank": None, "triage_score": agent.triage_score(ctx),
                 "proposal": None, "result": None, "intervention_id": None,
                 "approval_requirement_id": None, "execution_receipt_ids": []}
        self.alerts[eid] = alert
        self._checkpoint_alert(eid)
        await self.broadcast({"type": "alert", "alert": alert, "phase": "analyzing"})

        proposal = agent.decide(ctx)
        alert["proposal"] = proposal
        alert["status"] = "PENDING_APPROVAL"
        prepared = prepare_legacy_intervention(self.coordinator.repository, incident.id, proposal)
        alert["intervention_id"] = prepared.intervention.id
        alert["approval_requirement_id"] = prepared.requirement.id if prepared.requirement else None
        self.incidents[eid] = self.coordinator.repository.fetch_incident(incident.id)
        self._checkpoint_alert(eid)
        self._resume.discard(eid)
        self._analyzing.discard(eid)
        self._retriage()
        await self.broadcast({"type": "alert", "alert": alert, "phase": "ready",
                              "triage": self._triage_msg()})

    def _pending_ctxs(self) -> list[dict]:
        ctxs = []
        for eid, al in self.alerts.items():
            if al["status"] in ("ANALYZING", "PENDING_APPROVAL"):
                ctxs.append({"equipment_id": eid, "criticality": al["criticality"],
                             "prediction": {"failure_prob": al["failure_prob"]}})
        return ctxs

    def _retriage(self):
        ranked = agent.rank_alerts(self._pending_ctxs())
        for c in ranked:
            if c["equipment_id"] in self.alerts:
                self.alerts[c["equipment_id"]]["triage_rank"] = c["triage_rank"]

    def _triage_msg(self) -> dict:
        ranked = agent.rank_alerts(self._pending_ctxs())
        msg = {"count": len(ranked), "rationale": agent.triage_rationale(ranked),
               "order": [c["equipment_id"] for c in ranked]}
        # Monitoring peer: reason over the active alert set for systemic patterns.
        # Best-effort — an unavailable peer must never stall the loop.
        try:
            active = [self.alerts[e] for e in msg["order"] if e in self.alerts]
            snap = {"alerts": [{"equipment_id": a["equipment_id"],
                                "equipment_class": a.get("equipment_class"),
                                "predicted_mode": a.get("predicted_mode"),
                                "failure_prob": a.get("failure_prob"),
                                "criticality": a.get("criticality")} for a in active]}
            # The dashboard renders monitoring as its own banner from this object,
            # so the triage rationale stays purely about alert contention.
            msg["monitoring"] = services.monitoring().assess(snap)
        except Exception:
            pass
        return msg

    # -- human-in-the-loop -------------------------------------------------
    def _lifecycle_target(self, eid: str, command: dict | None):
        al = self.alerts.get(eid)
        incident = self.incidents.get(eid)
        if not al or incident is None or al.get("lifecycle") is None:
            return None, None, {"ok": False, "error": "no active lifecycle incident for this asset"}
        required = ("requirement_id", "intervention_id", "intervention_hash", "context_revision")
        if not command or any(not command.get(key) for key in required):
            return None, None, {"ok": False, "error": "approval must identify the exact requirement, intervention, "
                                                      "intervention hash and context revision",
                                "incident": self.lifecycle.projection(incident.id)}
        return al, incident, None

    async def approve(self, eid: str, command: dict | None = None) -> dict:
        if self.legacy_demo:
            return await self._approve_legacy(eid)
        al, incident, error = self._lifecycle_target(eid, command)
        if error:
            return error
        try:
            decision = self.lifecycle.decide_approval(
                incident.id, requirement_id=str(command["requirement_id"]), intervention_id=str(command["intervention_id"]),
                intervention_hash=str(command["intervention_hash"]), context_revision=int(command["context_revision"]),
                actor_id=str(command.get("actor_id") or "dashboard-operator"),
                actor_role=str(command.get("actor_role") or "maintenance_approver"), decision="APPROVE",
                rationale=str(command.get("rationale") or "approved in Operon dashboard"))
        except LIFECYCLE_ERRORS as exc:
            await self._refresh_lifecycle(eid, "approval_refused", reason=str(exc))
            return {"ok": False, "error": str(exc), "incident": self.lifecycle.projection(incident.id)}
        return await self.execute(incident.id, decision.intervention_id, intervention_hash=decision.intervention_hash)

    async def execute(self, incident_id: str, intervention_id: str, *, intervention_hash: str | None = None) -> dict:
        """Governed dispatch of the exact promoted, approved intervention (READY -> EXECUTING -> receipt)."""
        eid = self._eid_for(incident_id)
        try:
            execution = await asyncio.to_thread(self.lifecycle.execute, incident_id, intervention_id,
                                                intervention_hash=intervention_hash)
        except (ExecutionFailed, ExecutionAmbiguous) as exc:
            if eid:
                await self._refresh_lifecycle(eid, "execution_failed", reason=str(exc))
            return {"ok": False, "error": str(exc), "phase": exc.report.phase.value,
                    "receipt_ids": list(exc.report.receipt_ids), "incident": self.lifecycle.projection(incident_id)}
        except LIFECYCLE_ERRORS as exc:
            if eid:
                await self._refresh_lifecycle(eid, "execution_refused", reason=str(exc))
                return {"ok": False, "error": str(exc), "incident": self.lifecycle.projection(incident_id)}
            return {"ok": False, "error": str(exc)}
        if eid is None:
            return {"ok": True, "phase": execution.phase.value, "receipt_ids": list(execution.receipt_ids),
                    "external_objects": execution.external_objects}
        al = self.alerts[eid]
        intervention = self.coordinator.repository.get_artifact(incident_id, intervention_id)
        # Simulated plant response to a dispatched package (profile-dependent). Execution
        # SUCCESS means the commanded work-package action was confirmed, not that the
        # machine recovered; only lifecycle outcome verification can establish that.
        self.sim.respond_to_intervention(eid)
        self.status_override[eid] = "SCHEDULED"
        wo = execution.external_objects
        al["result"] = {"outcome": "DISPATCHED", "wo_number": wo.get("wo_number"),
                        "package_number": wo.get("package_number"),
                        "recovered_value": intervention.estimated_avoided_loss,
                        "downtime_hours_avoided": round(config.UNPLANNED_OUTAGE_HOURS - config.PLANNED_SWAP_HOURS, 2),
                        "oee_before": config.OEE_BASELINE,
                        "oee_after": min(config.OEE_TARGET, config.OEE_BASELINE + 0.031)}
        await self._refresh_lifecycle(eid, "dispatched", message_type="resolved")
        await self.broadcast({"type": "resolved", "equipment_id": eid, "result": al["result"],
                              "business": self._business_summary(), "triage": self._triage_msg()})
        return {"ok": True, "result": al["result"], "phase": execution.phase.value,
                "receipt_ids": list(execution.receipt_ids)}

    def _eid_for(self, incident_id: str) -> str | None:
        return next((eid for eid, incident in self.incidents.items() if incident.id == incident_id), None)

    async def reject(self, eid: str, command: dict | None = None) -> dict:
        if self.legacy_demo:
            return await self._reject_legacy(eid)
        al, incident, error = self._lifecycle_target(eid, command)
        if error:
            return error
        try:
            self.lifecycle.decide_approval(
                incident.id, requirement_id=str(command["requirement_id"]), intervention_id=str(command["intervention_id"]),
                intervention_hash=str(command["intervention_hash"]), context_revision=int(command["context_revision"]),
                actor_id=str(command.get("actor_id") or "dashboard-operator"),
                actor_role=str(command.get("actor_role") or "maintenance_approver"), decision="REJECT",
                rationale=str(command.get("rationale") or "rejected in Operon dashboard"))
        except LIFECYCLE_ERRORS as exc:
            await self._refresh_lifecycle(eid, "rejection_refused", reason=str(exc))
            return {"ok": False, "error": str(exc), "incident": self.lifecycle.projection(incident.id)}
        self.sim.set_mode(eid, "failing")   # demo run-to-failure scenario after human rejection
        self.status_override[eid] = "CRITICAL"
        await self._refresh_lifecycle(eid, "rejected", message_type="rejected")
        return {"ok": True, "phase": self.incidents[eid].phase.value}

    # -- trusted application submissions (caller authenticates the actor) ----
    def submit_technical_confirmation(self, confirmation, *, expected_revision: int) -> dict:
        evidence, incident = self.lifecycle.submit_technical_confirmation(confirmation, expected_revision=expected_revision)
        self._adopt(incident)
        return {"ok": True, "evidence_id": evidence.id, "incident": self.lifecycle.projection(incident.id)}

    def submit_resource_confirmation(self, confirmation, *, expected_revision: int) -> dict:
        evidence, incident = self.lifecycle.submit_resource_confirmation(confirmation, expected_revision=expected_revision)
        self._adopt(incident)
        return {"ok": True, "evidence_id": evidence.id, "incident": self.lifecycle.projection(incident.id)}

    async def plan(self, incident_id: str, *, expected_revision: int, **binding_fields) -> dict:
        if self.runtime is None:
            return {"ok": False, "error": "no supervisor runtime configured; exact-draft review cannot run"}
        async with self._reasoning_lock:
            outcome = await self.lifecycle.plan(incident_id, runtime=self.runtime, evidence_service=self.evidence_service,
                                                specialist_runtime=self.specialist_runtime,
                                                expected_revision=expected_revision, **binding_fields)
        eid = self._eid_for(incident_id)
        if eid:
            await self._refresh_lifecycle(eid, outcome.disposition.lower(), reason=outcome.reason)
        return {"ok": outcome.disposition == "APPROVAL_REQUESTED", "outcome": outcome.model_dump(mode="json"),
                "incident": self.lifecycle.projection(incident_id)}

    def _adopt(self, incident):
        eid = self._eid_for(incident.id)
        if eid:
            self.incidents[eid] = incident
            self.alerts[eid] = self._lifecycle_alert(eid)

    def incident_view(self, incident_id: str) -> dict:
        projection = self.lifecycle.projection(incident_id)
        incident = self.coordinator.repository.fetch_incident(incident_id)
        return {**projection, "read_model": self._incident_read_model(incident)}

    async def _approve_legacy(self, eid: str) -> dict:
        al = self.alerts.get(eid)
        if not al or al["status"] != "PENDING_APPROVAL":
            return {"ok": False, "error": "no pending proposal for this asset"}
        incident = self.incidents.get(eid)
        if not incident or not al.get("intervention_id") or not al.get("approval_requirement_id"):
            return {"ok": False, "error": "proposal has no governed intervention approval request"}
        ledger = ApprovalLedger(self.coordinator.repository)
        try:
            ledger.decide(
                incident.id, al["approval_requirement_id"],
                actor_id="dashboard-operator", actor_role="maintenance_approver",
                decision="APPROVE", rationale="approved in Operon dashboard",
            )
            execution = GovernedExecutor(self.coordinator.repository).execute(
                incident.id, al["intervention_id"])
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        wo = execution.external_objects
        self.sim.set_mode(eid, "recovering")
        self.status_override[eid] = "SCHEDULED"
        b = al["proposal"]["business"]
        result = {"outcome": "PREVENTED", "wo_number": wo.get("wo_number"),
                  "package_number": wo.get("package_number"),
                  "recovered_value": b["recovered_value"],
                  "downtime_hours_avoided": b["downtime_hours_avoided"],
                  "oee_before": config.OEE_BASELINE,
                  "oee_after": min(config.OEE_TARGET, config.OEE_BASELINE + 0.031)}
        al["status"] = "APPROVED"
        al["result"] = result
        al["execution_receipt_ids"] = list(execution.receipt_ids)
        self.incidents[eid] = self.coordinator.repository.fetch_incident(incident.id)
        self._checkpoint_alert(eid)
        self._retriage()
        await self.broadcast({"type": "resolved", "equipment_id": eid, "result": result,
                              "business": self._business_summary(), "triage": self._triage_msg()})
        return {"ok": True, "result": result}

    async def _reject_legacy(self, eid: str) -> dict:
        al = self.alerts.get(eid)
        if not al or al["status"] != "PENDING_APPROVAL":
            return {"ok": False, "error": "no pending proposal for this asset"}
        incident = self.incidents.get(eid)
        if not incident or not al.get("approval_requirement_id"):
            return {"ok": False, "error": "proposal has no governed intervention approval request"}
        ledger = ApprovalLedger(self.coordinator.repository)
        try:
            ledger.decide(
                incident.id, al["approval_requirement_id"],
                actor_id="dashboard-operator", actor_role="maintenance_approver",
                decision="REJECT", rationale="rejected in Operon dashboard",
            )
            current = self.coordinator.repository.fetch_incident(incident.id)
            current = self.coordinator.transition(
                current.id, IncidentPhase.ESCALATED, expected_revision=current.revision,
                reason="intervention rejected; human reconciliation required")
            self.incidents[eid] = current
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        self.sim.set_mode(eid, "failing")
        self.status_override[eid] = "CRITICAL"
        al["status"] = "REJECTED"
        self._checkpoint_alert(eid)
        self._retriage()
        await self.broadcast({"type": "rejected", "equipment_id": eid, "triage": self._triage_msg()})
        return {"ok": True}

    async def _unplanned_failure(self, eid: str):
        self.status_override[eid] = "DOWN"
        result = {"outcome": "UNPLANNED_FAILURE", "loss": config.unplanned_loss(),
                  "downtime_hours": config.UNPLANNED_OUTAGE_HOURS,
                  "oee_before": config.OEE_BASELINE,
                  "oee_after": round(config.OEE_BASELINE - 0.06, 3)}
        self.alerts[eid]["status"] = "FAILED"
        self.alerts[eid]["result"] = result
        self._checkpoint_alert(eid)
        await self.broadcast({"type": "failure", "equipment_id": eid, "result": result,
                              "business": self._business_summary()})

    # -- aggregates + snapshot --------------------------------------------
    def _business_summary(self) -> dict:
        # Lifecycle incidents can be APPROVED (READY/EXECUTING) before any dispatch result exists.
        # A verified closure keeps its dispatched result; NOT_RECOVERED/REGRESSED incidents leave
        # the APPROVED status (re-investigation/escalation) and therefore drop out here.
        prevented = [a for a in self.alerts.values() if a["status"] in ("APPROVED", "CLOSED") and a.get("result")
                     and a["result"].get("outcome") in ("DISPATCHED", "PREVENTED", "VERIFIED_RECOVERY")]
        lost = [a for a in self.alerts.values() if a["status"] == "FAILED" and a.get("result")]
        recovered = sum(a["result"]["recovered_value"] for a in prevented)
        loss = sum(a["result"]["loss"] for a in lost)
        return {"events_prevented": len(prevented), "events_failed": len(lost),
                "recovered_value": recovered, "loss_incurred": loss,
                "net_value": recovered - loss,
                "fleet_projection": round(recovered * config.FLEET_LINES, 0),
                "oee_baseline": config.OEE_BASELINE, "oee_target": config.OEE_TARGET,
                "downtime_cost_per_hour": config.DOWNTIME_COST_PER_HOUR,
                "recovered_per_event": round(config.recovered_value(), 0)}

    def snapshot(self) -> dict:
        backend = getattr(self.runtime, "name", None) or config.reasoning_backend()
        return {"type": "snapshot", "tick": self.tick_i, "running": self.running,
                "agent_mode": config.agent_mode(), "app_name": config.APP_NAME,
                "authority_path": "legacy-demo" if self.legacy_demo else "lifecycle",
                "supervisor_available": self.runtime is not None,
                "reasoning_provenance": {
                    "backend": backend,
                    "status": "available" if self.runtime is not None else "awaiting_runtime",
                    "application": "Operon",
                    "runtime": ("AgentCore Runtime" if backend == "agentcore" else
                                "Offline typed advisory fixture" if backend == "demo" else "Local application runtime"),
                    "framework": "Operon typed advisory contracts" if backend == "demo" else "Strands Agents",
                    "model_provider": "Amazon Bedrock" if backend in {"agentcore", "local", "packet"} else None,
                    "provenance": "SIMULATED" if backend == "demo" else "LIVE" if backend == "agentcore" else "LOCAL",
                },
                "tagline": config.APP_TAGLINE, "plant_name": config.PLANT_NAME,
                "trigger_threshold": config.TRIGGER_THRESHOLD, "warn_threshold": config.WARN_THRESHOLD,
                "fleet": [self._asset_summary(e) for e in self.meta if e in self.assets],
                "histories": self.histories,
                "alerts": list(self.alerts.values()),
                "triage": self._triage_msg(),
                "business": self._business_summary(), "demo_scenario": self._demo_projection()}

    async def broadcast(self, msg: dict):
        import json
        dead, data = [], json.dumps(msg, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)
