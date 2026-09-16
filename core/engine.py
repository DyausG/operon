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

Guided Demo (Stage 0): ``start_guided_demo`` replays a deterministic telemetry/failure
*scenario* on the seeded simulator and drives the resulting **real** incident through
the same lifecycle, promotion and governance services as any other incident. Its
reasoning goes through the engine's configured ``ReasoningBackend`` (Gemini, Ollama,
Bedrock or AgentCore); only when no provider is configured does it use the explicitly
labelled ``DeterministicAdvisoryBackend``. The scenario id never masquerades as a
reasoning runtime: every run snapshot freezes the backend/provider/model that ran.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import time

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
from .reasoning.provenance import describe_backend, describe_run_identity, reasoning_label
from .prism import PrismRepository, PrismRuntime
from .prism.slow_path import adapter_from_environment as prism_adapter_from_environment

HISTORY_CAP = 90
# Per-incident automatic retry cadence. The capped monotonic deadline permits
# eventual recovery without retrying on every telemetry tick.
REASONING_RETRY_BASE_SECONDS = 5.0
REASONING_RETRY_MAX_SECONDS = 300.0
LIFECYCLE_STATUS = {
    IncidentPhase.OPEN: "ANALYZING", IncidentPhase.INVESTIGATING: "ANALYZING",
    IncidentPhase.AWAITING_EVIDENCE: "ANALYZING", IncidentPhase.DIAGNOSIS_VALIDATED: "ANALYZING",
    IncidentPhase.PLANNING: "ANALYZING", IncidentPhase.INTERVENTION_VALIDATED: "ANALYZING",
    IncidentPhase.AWAITING_APPROVAL: "PENDING_APPROVAL", IncidentPhase.READY: "APPROVED",
    IncidentPhase.EXECUTING: "APPROVED", IncidentPhase.OBSERVING: "APPROVED",
    IncidentPhase.EXECUTION_FAILED: "EXECUTION_FAILED", IncidentPhase.ESCALATED: "ESCALATED",
    IncidentPhase.CLOSED: "CLOSED", IncidentPhase.CANCELLED: "CANCELLED",
}
# Guided Demo: bounded retries when a supervisor run cannot start (RETRY disposition).
GUIDED_DIAGNOSIS_ATTEMPTS = 3
GUIDED_PREPARING_STATUSES = ("factory_healthy", "degrading", "risk_rising", "incident_open", "investigating",
                             "diagnosing", "awaiting_evidence", "trusted_inspection", "diagnosis_validated",
                             "planning", "intervention_review", "awaiting_human_approval")
GUIDED_PHASE_STATUS = {
    IncidentPhase.READY: "ready", IncidentPhase.EXECUTING: "executing", IncidentPhase.OBSERVING: "observing",
    IncidentPhase.CLOSED: "complete", IncidentPhase.CANCELLED: "cancelled",
    IncidentPhase.EXECUTION_FAILED: "execution_failed", IncidentPhase.ESCALATED: "escalated",
}
LIFECYCLE_ERRORS = (LifecycleRefused, ApprovalRefused, GovernanceBlocked, ExecutionRefused, ReconciliationRequired,
                    ExecutionBusy, PromotionRefused, StaleRevision, InvalidReference, LookupError, KeyError, TypeError,
                    ValueError)
logger = logging.getLogger(__name__)


@dataclass
class ReasoningRetryState:
    failures: int = 0
    next_retry_at: float = 0.0
    last_error_key: str | None = None


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
        self._runtime_unavailable_reason: str | None = None
        self.runtime = runtime if runtime is not None else self._build_runtime()
        self._base_runtime = self.runtime
        self.specialist_runtime = specialist_runtime
        self._guided_demo: dict | None = None
        self._guided_task: asyncio.Task | None = None
        self._guided_owner: str | None = None
        self._guided_claim: object | None = None
        self._guided_incident_id: str | None = None
        self._guided_backend = None
        self._guided_started_at: float | None = None
        self.demo_step_delay = 5.0
        self.incidents = {}
        self._resume: set[str] = set()
        self._lifecycle_tasks: dict[str, asyncio.Task] = {}
        self._reasoning_retries: dict[str, ReasoningRetryState] = {}
        self._reasoning_diagnostics: list[dict] = []
        self._monotonic = time.monotonic
        # Outcome messages produced by the synchronous tick progression, flushed by the tick.
        self._pending_broadcasts: list[dict] = []
        # Monitoring peer results per active alert set; refreshed off the event loop.
        self._monitoring_cache: dict[frozenset, dict] = {}
        self._monitoring_tasks: dict[frozenset, asyncio.Task] = {}
        # Supervisor runs are serialized: 13A's source checkpoint treats another
        # incident's revision change during a run as staleness.
        self._reasoning_lock = asyncio.Lock()
        self._model_version = model_version(config.MODEL_PATH)
        self._observed_at = self._clock()
        self._recover_incidents()
        # PRISM runtime: sessions/revisions/runs over the same database; events ride /ws. Stage 2 gives
        # it the production Slow Path around this engine's real reasoning stack (role ``slow``).
        self._prism_backend_cache = None
        self.prism = PrismRuntime(PrismRepository(self.coordinator.repository.path),
                                  incident_repository=self.coordinator.repository, broadcast=self.broadcast,
                                  adapter=prism_adapter_from_environment(services=self._prism_services()))
        self._prism_recovered = False

    # ---- PRISM production Slow Path wiring (Stage 2) -------------------------------------------
    def _prism_services(self) -> dict:
        from .reliability.promotion import PromotionService
        return {"incident_repository": self.coordinator.repository, "lifecycle": self.lifecycle,
                "promotion": PromotionService(self.coordinator.repository), "evidence_service": self.evidence_service,
                "backend_factory": self._prism_backend, "busy": self._prism_busy}

    def _prism_backend(self):
        """The reasoning backend PRISM's Slow Path uses: the provider bound to role ``slow`` through the
        Stage 0 registry (the active provider unless a role override exists), or the labelled deterministic
        advisory when no provider is configured. Rebuilt after Settings changes the provider."""
        if self._prism_backend_cache is None:
            from .prism.operon import default_backend_factory
            self._prism_backend_cache = default_backend_factory()()
        return self._prism_backend_cache

    def _prism_busy(self, incident_id: str) -> str | None:
        """Why the production adapter must wait before claiming a run on ``incident_id`` (or ``None``)."""
        if self._guided_incident_id == incident_id and self._guided_task is not None and not self._guided_task.done():
            return "the Guided Demo controller owns this incident"
        for eid, incident in self.incidents.items():
            if incident.id == incident_id:
                task = self._lifecycle_tasks.get(eid)
                if task is not None and not task.done():
                    return "an engine diagnosis run is in flight for this incident"
        return None

    @staticmethod
    def _default_runtime():
        """Reasoning backend only when explicitly configured; never a silent fallback.

        Returns a ``core.reasoning.backend.ReasoningBackend`` (Step 15) selected by
        OPERON_REASONING_BACKEND; unset resolves to ``local`` over the active model
        provider (Gemini, Ollama or Bedrock) and to ``none`` without a provider.
        """
        if config.reasoning_backend() == "none":
            return None
        try:
            from .reasoning.backend import backend_from_environment
            return backend_from_environment()
        except Exception:
            logger.exception("Supervisor reasoning backend unavailable; incidents will wait in INVESTIGATING")
            return None

    def _build_runtime(self):
        """``_default_runtime`` plus the truthful reason when no runtime is available."""
        self._runtime_unavailable_reason = None
        if config.reasoning_backend() == "none":
            provider = config.provider_registry().active()
            self._runtime_unavailable_reason = (
                provider.not_configured_reason() if provider.kind == "none"
                else "reasoning backend disabled (OPERON_REASONING_BACKEND=none)")
            return None
        try:
            from .reasoning.backend import backend_from_environment
            return backend_from_environment()
        except Exception as exc:  # noqa: BLE001 - reported, never a silent fallback
            logger.exception("Supervisor reasoning backend unavailable; incidents will wait in INVESTIGATING")
            self._runtime_unavailable_reason = f"{type(exc).__name__}: {exc}"[:300]
            return None

    async def reconfigure_runtime(self) -> dict:
        """Rebuild the reasoning backend after the provider configuration changed (Settings API).

        Serialized with supervisor runs; an in-flight run finishes on the runtime it started with.
        """
        async with self._reasoning_lock:
            self.runtime = self._build_runtime()
            self._base_runtime = self.runtime
            self._prism_backend_cache = None
        snapshot = self.snapshot()
        await self.broadcast(snapshot)
        return {"ok": True, "supervisor_available": self.runtime is not None,
                "reasoning_provenance": snapshot.get("reasoning_provenance")}

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
        if not self._prism_recovered:
            # Startup reconstruction of PRISM sessions (explicit policy; never revives superseded work).
            self._prism_recovered = True
            try:
                await self.prism.recover()
            except Exception:  # noqa: BLE001 - recovery problems are logged, the simulation still starts
                logger.exception("PRISM recovery failed")
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

    async def reset(self, *, restore_factory: bool = True, restart: bool = True):
        # A reset cancels any Guided Demo controller first; its incident is ordinary
        # durable state and is wiped with the rest of the transactional store below.
        guided = self._guided_task
        if guided and guided is not asyncio.current_task() and not guided.done():
            guided.cancel()
        if guided and guided is not asyncio.current_task():
            await asyncio.gather(guided, return_exceptions=True)
        self._guided_task = None
        self._guided_demo = None
        self._guided_started_at = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        lifecycle_tasks = list(self._lifecycle_tasks.values())
        for task in lifecycle_tasks:
            task.cancel()
        if lifecycle_tasks:
            results = await asyncio.gather(*lifecycle_tasks, return_exceptions=True)
            for task, result in zip(lifecycle_tasks, results):
                self._trace_reasoning(
                    "task_cancelled_for_reset",
                    cancellation_result=type(result).__name__ if isinstance(result, BaseException) else "completed",
                    task=task,
                )
        self._release_guided_ownership(reason="reset")
        await self.prism.shutdown()
        reset_transactional()
        self.prism.reset_memory()
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
        self._reasoning_retries = {}
        self._reasoning_diagnostics = []
        self._pending_broadcasts = []
        await self.broadcast({"type": "reset"})
        if restore_factory:
            # Reconstruct a complete normal-factory projection before a public
            # reset returns. This is a real simulator tick (and persisted
            # telemetry), not a UI-only placeholder.
            await self._advance()
        if restart:
            await self.start()
        if restore_factory and restart:
            await self.broadcast(self.snapshot())

    # -- Guided Demo Scenario (real lifecycle, configured reasoning) -----------
    def _guided_status(self, guided: dict, incident) -> str:
        if guided.get("status") == "failed":
            return "failed"
        if incident is None:
            asset = self.assets.get(guided["equipment_id"], {})
            state = self.sim.assets[guided["equipment_id"]]
            if state.prog <= 0:
                return "factory_healthy"
            return "risk_rising" if float(asset.get("failure_prob", 0)) >= config.WARN_THRESHOLD else "degrading"
        if incident.phase in GUIDED_PHASE_STATUS:
            if incident.phase == IncidentPhase.ESCALATED and self._rejected(incident.id):
                return "cancelled"
            return GUIDED_PHASE_STATUS[incident.phase]
        return guided.get("status") or "investigating"

    def _guided_phase(self, guided: dict, incident) -> str:
        if incident is not None:
            return incident.phase.value
        state = self.sim.assets[guided["equipment_id"]]
        if state.prog <= 0:
            return "FACTORY_HEALTHY"
        risk = float(self.assets.get(guided["equipment_id"], {}).get("failure_prob", 0))
        return "PREDICTIVE_RISK_RISING" if risk >= config.WARN_THRESHOLD else "FACTORY_DEGRADING"

    def _demo_projection(self) -> dict:
        """Portal view of the Guided Demo: scenario, reasoning and lifecycle progress kept apart."""
        guided = self._guided_demo
        if not guided:
            return {"active": False}
        eid = guided["equipment_id"]
        incident = self.incidents.get(eid)
        if incident is not None and guided.get("incident_id") in (None, incident.id):
            guided["incident_id"] = incident.id
        elif incident is not None and guided.get("incident_id") != incident.id:
            incident = None
        phase = self._guided_phase(guided, incident)
        approval_state = "NOT_REQUESTED"
        if incident is not None:
            if incident.phase == IncidentPhase.AWAITING_APPROVAL:
                approval_state = "PENDING"
            elif incident.phase in (IncidentPhase.READY, IncidentPhase.EXECUTING, IncidentPhase.OBSERVING,
                                    IncidentPhase.CLOSED):
                approval_state = "APPROVED"
            elif incident.phase == IncidentPhase.ESCALATED and self._rejected(incident.id):
                approval_state = "REJECTED"
        started = guided.get("started_at")
        return {
            "active": True, "label": guided["label"], "equipment_id": eid,
            "incident_id": guided.get("incident_id"), "status": self._guided_status(guided, incident),
            "phase": phase, "risk": round(float(self.assets.get(eid, {}).get("failure_prob", 0)), 3),
            "elapsed_seconds": int(self._monotonic() - started) if started is not None else 0,
            "approval_state": approval_state, "error": guided.get("error"),
            "scenario": guided["scenario"], "reasoning": guided["reasoning"],
            "authoritative_persistence": True,
        }

    def _set_guided_status(self, status: str) -> None:
        if self._guided_demo is not None and self._guided_demo.get("status") != "failed":
            self._guided_demo["status"] = status

    def demo_artifact(self, artifact_id: str) -> dict:
        """Inspector view of one durable artifact of an active incident (Guided Demo or live)."""
        repo = self.coordinator.repository
        for eid, incident in self.incidents.items():
            try:
                artifact = repo.get_artifact(incident.id, artifact_id)
            except (LookupError, InvalidReference, KeyError, ValueError):
                continue
            return self._inspector_artifact(artifact, eid)
        raise LookupError(artifact_id)

    def _inspector_artifact(self, artifact, eid: str) -> dict:
        """Map a durable record onto the portal's inspector shape; grants nothing."""
        repo = self.coordinator.repository
        kind = type(artifact).__name__
        payload = artifact.model_dump(mode="json")
        artifact_type, title, summary, status = kind.lower(), kind, "", getattr(artifact, "status", None)
        provenance, runtime, live_model, reasoning = "APPLICATION", "Operon application", None, None
        supporting: list[str] = []
        if isinstance(artifact, m.Evidence):
            provenance = artifact.provenance
            supporting = list(artifact.derived_from_ids)
            summary, status = artifact.summary, artifact.quality
            if artifact.kind == "model_signal":
                artifact_type, title = "predictive_signal", "Predictive risk signal"
                inner = dict(payload.get("payload") or {})
                inner.setdefault("failure_probability", inner.get("risk_score"))
                inner.setdefault("threshold", config.TRIGGER_THRESHOLD)
                payload["payload"] = inner
            elif artifact.kind == "inspection":
                artifact_type, title = "technician_inspection", "Trusted technical confirmation"
            else:
                artifact_type, title = "evidence", f"{artifact.kind.replace('_', ' ').title()} evidence"
        elif isinstance(artifact, m.Hypothesis):
            artifact_type, title, summary = "hypothesis", "Hypothesis", artifact.mechanism
            supporting = list(artifact.supporting_evidence_ids)
        elif isinstance(artifact, m.Diagnosis):
            artifact_type, title, summary = "diagnosis", "Diagnosis", artifact.conclusion
            supporting = [*artifact.evidence_ids, *artifact.hypothesis_ids]
        elif isinstance(artifact, m.ValidationVerdict):
            artifact_type = "diagnosis_validation" if artifact.target_kind == "diagnosis" else "intervention_validation"
            title, summary = f"{artifact.target_kind.title()} validation", getattr(artifact, "validation_summary", "") or ""
            status = getattr(artifact, "decision", None)
            supporting = [getattr(artifact, "target_id", None)] if getattr(artifact, "target_id", None) else []
        elif isinstance(artifact, m.Intervention):
            artifact_type, title = "intervention", "Intervention"
            summary = getattr(artifact, "objective", None) or getattr(artifact, "summary", "") or ""
            supporting = list(artifact.evidence_ids)
        elif isinstance(artifact, m.WorkPackageBinding):
            artifact_type, title = "work_package", "Work package binding"
        elif isinstance(artifact, m.ApprovalRequirement):
            artifact_type, title = "approval_request", "Approval requirement"
            supporting = [artifact.intervention_id]
        elif isinstance(artifact, m.ObservationPlan):
            artifact_type, title = "recovery_observation_plan", "Recovery observation plan"
        elif isinstance(artifact, m.Outcome):
            artifact_type, title = "outcome_verification", "Outcome verification"
            summary, status = getattr(artifact, "reason", "") or "", getattr(artifact, "result", None)
        elif isinstance(artifact, m.SupervisorReport):
            snapshot = next((item for item in repo.list_artifacts(artifact.incident_id)
                             if isinstance(item, m.SupervisorRunSnapshot) and item.run_id == artifact.run_id), None)
            view = self._agent_run_view(artifact, snapshot)
            reasoning = view["reasoning"]
            artifact_type, title, payload = "specialist_activity", "Supervisor run", view
            summary, status = view.get("summary") or "", artifact.completion
            provenance, runtime, live_model = reasoning["provenance"], reasoning_label(reasoning), reasoning["live_model"]
            supporting = list(artifact.evidence_manifest)
        elif isinstance(artifact, m.SupervisorRunSnapshot):
            reasoning = describe_run_identity(artifact.runtime_identity)
            artifact_type, title = "supervisor_run_snapshot", "Supervisor run snapshot"
            provenance, runtime, live_model = reasoning["provenance"], reasoning_label(reasoning), reasoning["live_model"]
            payload.pop("context_payload", None)
            supporting = list(artifact.evidence_manifest)
        elif isinstance(artifact, m.AgentAction):
            artifact_type, title, summary = "agent_action", "Agent action", artifact.summary
            supporting = list(artifact.input_artifact_ids)
        elif isinstance(artifact, m.PromotionRecord):
            artifact_type, title = "promotion_record", "Application promotion"
        elif isinstance(artifact, m.EvidenceRequest):
            artifact_type, title, summary = "evidence_request", "Evidence request", artifact.question
        return {
            "id": artifact.id, "artifact_type": artifact_type, "title": title, "status": status,
            "created_at": artifact.created_at.isoformat(), "incident_id": artifact.incident_id,
            "equipment_id": eid, "source": getattr(artifact, "source_system", None) or "operon-application",
            "provenance": provenance, "runtime": runtime, "live_model": live_model, "reasoning": reasoning,
            "parent_ids": [], "supporting_ids": [item for item in supporting if item], "related_ids": [],
            "summary": summary, "payload": payload,
        }

    async def _broadcast_demo(self):
        await self.broadcast({"type": "demo", "demo_scenario": self._demo_projection()})

    def _scenario_backend(self):
        """The configured reasoning backend, or the explicitly labelled deterministic advisory."""
        if self.runtime is not None:
            return self.runtime
        from .demo_scenario import DeterministicAdvisoryBackend
        return DeterministicAdvisoryBackend()

    async def start_guided_demo(self, equipment_id: str) -> dict:
        """Replay the deterministic Guided Demo Scenario through the real lifecycle.

        The scenario controls only simulator inputs and SIMULATED trusted submissions.
        Admission, reasoning, promotion, governance, approval, execution and outcome
        verification are the ordinary services; reasoning uses the engine's configured
        backend when one exists (selected in Settings, effective for the next demo).
        """
        if equipment_id not in self.sim.assets:
            return {"ok": False, "error": "unknown demo equipment"}
        if self.legacy_demo:
            return {"ok": False, "error": "the Guided Demo requires the authoritative lifecycle (unset OPERON_LEGACY_DEMO)"}
        await self.reset(restart=False)
        backend = self._scenario_backend()
        for state in self.sim.assets.values():
            state.mode, state.prog = "healthy", 0.0
        selected = self.sim.assets[equipment_id]
        from .demo_scenario import GUIDED_RAMP_TICKS, scenario_descriptor
        # The asset's own fleet degradation trajectory (its deltas are tuned to the model's
        # trigger region); healthy-profile assets borrow their class's characteristic mode.
        if selected.profile.scenario == "healthy":
            selected.profile.scenario = CLASS_DEFAULT_MODE[selected.profile.equipment_class].removeprefix("FM-")
        selected.profile.start_tick, selected.profile.ramp_ticks = 1, GUIDED_RAMP_TICKS
        selected.profile.intervention_response = "RECOVERS"
        selected.mode = "degrading"
        claim = object()
        self._guided_owner, self._guided_claim, self._guided_incident_id = equipment_id, claim, None
        self._guided_backend = backend
        self._guided_started_at = self._monotonic()
        reasoning = describe_backend(backend)
        reasoning["status"] = "deterministic" if backend.name == "deterministic" else "configured"
        self._guided_demo = {
            "equipment_id": equipment_id, "status": "factory_healthy", "incident_id": None, "error": None,
            "label": f"Guided Demo · {self.meta.get(equipment_id, {}).get('equipment_name') or equipment_id}",
            "started_at": self._guided_started_at,
            "scenario": scenario_descriptor(equipment_id, selected.profile.scenario, seed=self.sim.seed),
            "reasoning": reasoning,
        }
        self._trace_reasoning("guided_demo_started", equipment_id=equipment_id, backend=backend, task_kind="guided",
                              task_creation_location="core.engine.DemoEngine.start_guided_demo",
                              reasoning_backend_invoked=self._backend_identity(backend))
        await self.start()
        self._guided_task = asyncio.create_task(self._guide_to_approval(equipment_id, claim, backend),
                                                name=f"guided-demo:{equipment_id}")
        await self.broadcast(self.snapshot())
        return {"ok": True, "demo_scenario": self._demo_projection()}

    async def _wait_demo_phase(self, equipment_id: str, phases: set[IncidentPhase], timeout=45,
                               *, accept_progressed=False):
        phase_order = {
            IncidentPhase.OPEN: 0, IncidentPhase.INVESTIGATING: 1,
            IncidentPhase.AWAITING_EVIDENCE: 2, IncidentPhase.DIAGNOSIS_VALIDATED: 3,
            IncidentPhase.PLANNING: 4, IncidentPhase.INTERVENTION_VALIDATED: 5,
            IncidentPhase.AWAITING_APPROVAL: 6, IncidentPhase.READY: 7,
            IncidentPhase.EXECUTING: 8, IncidentPhase.OBSERVING: 9,
            IncidentPhase.CLOSED: 10,
        }
        minimum_progress = min((phase_order[p] for p in phases if p in phase_order), default=None)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            incident = self.incidents.get(equipment_id)
            if incident is not None:
                current = self.coordinator.repository.fetch_incident(incident.id)
                progressed = (accept_progressed and minimum_progress is not None
                              and phase_order.get(current.phase, -1) >= minimum_progress)
                if current.phase in phases or progressed:
                    return current
                if current.phase in {IncidentPhase.ESCALATED, IncidentPhase.EXECUTION_FAILED, IncidentPhase.CANCELLED}:
                    raise RuntimeError(f"guided demo reached {current.phase.value}")
            await asyncio.sleep(0.1)
        raise TimeoutError("guided demo timed out waiting for authoritative lifecycle")

    async def _guided_diagnosis(self, equipment_id: str, incident_id: str, backend, claim: object,
                                expected: set[str]):
        """Run the real diagnosis stage through ``backend``; a RETRY is retried a bounded number of times."""
        self._set_guided_status("diagnosing")
        await self._broadcast_demo()
        for attempt in range(1, GUIDED_DIAGNOSIS_ATTEMPTS + 1):
            outcome = await self._diagnose_guided(equipment_id, incident_id, backend, claim)
            if outcome.disposition in expected:
                return outcome
            if outcome.disposition == "RETRY" and attempt < GUIDED_DIAGNOSIS_ATTEMPTS:
                await asyncio.sleep(self.demo_step_delay)
                continue
            raise RuntimeError(f"diagnosis stage ended with {outcome.disposition}: {outcome.reason}")
        raise RuntimeError("diagnosis stage could not start")  # pragma: no cover - loop always returns/raises

    async def _guide_to_approval(self, equipment_id: str, claim: object, backend):
        from .demo_scenario import binding_fields, resource_confirmation, technical_confirmation
        preparation_complete = False
        try:
            # Pacing only: the seeded simulator ramps the selected asset on its own
            # deterministic schedule and incident admission still depends on the real
            # persisted model prediction crossing its threshold.
            await asyncio.sleep(self.demo_step_delay)
            incident = await self._wait_demo_phase(
                equipment_id, {IncidentPhase.INVESTIGATING}, accept_progressed=True)
            if incident.phase == IncidentPhase.INVESTIGATING:
                await self._guided_diagnosis(equipment_id, incident.id, backend, claim, {"NEEDS_EVIDENCE"})
            elif incident.phase != IncidentPhase.AWAITING_EVIDENCE:
                raise RuntimeError(f"guided demo advanced unexpectedly to {incident.phase.value}")
            await self._wait_demo_phase(equipment_id, {IncidentPhase.AWAITING_EVIDENCE})
            self._set_guided_status("awaiting_evidence")
            await self._broadcast_demo()
            await asyncio.sleep(self.demo_step_delay)
            self._set_guided_status("trusted_inspection")
            await self._broadcast_demo()
            confirmation = technical_confirmation(self, equipment_id)
            response = self.submit_technical_confirmation(
                confirmation, expected_revision=self.coordinator.repository.fetch_incident(confirmation.incident_id).revision)
            await self._refresh_lifecycle(equipment_id, "demo_technical_confirmation",
                                          reason="explicit SIMULATED trusted inspection submitted")
            if not response["ok"]:
                raise RuntimeError("technical confirmation was refused")
            incident = await self._wait_demo_phase(
                equipment_id, {IncidentPhase.INVESTIGATING}, accept_progressed=True)
            if incident.phase == IncidentPhase.INVESTIGATING:
                await self._guided_diagnosis(equipment_id, incident.id, backend, claim, {"PROMOTED"})
            elif incident.phase != IncidentPhase.DIAGNOSIS_VALIDATED:
                raise RuntimeError(f"guided demo advanced unexpectedly to {incident.phase.value}")
            await self._wait_demo_phase(equipment_id, {IncidentPhase.DIAGNOSIS_VALIDATED})
            self._set_guided_status("diagnosis_validated")
            await self._broadcast_demo()
            # Freeze the simulated source briefly while the trusted application
            # binds and reviews the exact work package. This satisfies the same
            # dependency-freshness checks as a live caller; it grants no authority.
            await self.stop()
            await asyncio.sleep(self.demo_step_delay)
            self._set_guided_status("planning")
            await self._broadcast_demo()
            resource = resource_confirmation(self, equipment_id)
            response = self.submit_resource_confirmation(
                resource, expected_revision=self.coordinator.repository.fetch_incident(resource.incident_id).revision)
            resource_evidence = self.coordinator.repository.get_artifact(resource.incident_id, response["evidence_id"])
            await self._refresh_lifecycle(equipment_id, "demo_resource_confirmation",
                                          reason="explicit SIMULATED resource attestation submitted")
            incident = self.coordinator.repository.fetch_incident(resource.incident_id)
            self._set_guided_status("intervention_review")
            await self._broadcast_demo()
            result = await self._plan_with_runtime(
                incident.id, expected_revision=incident.revision, runtime=backend,
                specialist_runtime=None, guided_claim=claim,
                **binding_fields(self, equipment_id, resource_evidence),
            )
            if not result["ok"]:
                raise RuntimeError(result.get("outcome", {}).get("reason") or result.get("error") or "demo plan was refused")
            self._set_guided_status("awaiting_human_approval")
            await self.start()
            await self._broadcast_demo()
            preparation_complete = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Truthful failure: the normalized provider/lifecycle reason is shown; no
            # advisory text is ever substituted for the reasoning that did not happen.
            logger.exception("Guided demo preparation failed")
            if self._guided_demo is not None:
                self._guided_demo.update({"status": "failed", "error": str(exc)[:600]})
                await self.start()
                await self._broadcast_demo()
        finally:
            # A successfully prepared guided incident remains exclusively guided
            # through manual approval and outcome verification. Failure/cancellation
            # releases immediately; terminal outcome/reset releases below.
            if not preparation_complete:
                self._release_guided_ownership(equipment_id, claim=claim, reason="preparation_incomplete")

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
            override = self.status_override.get(eid)
            if override is not None and eid not in self.incidents:
                # An override is meaningful only while backed by lifecycle state.
                self.status_override.pop(eid, None)
                override = None
            status = override or base_status
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
        persistence = self._persist(readings, healths)

        await self.broadcast({"type": "tick", "tick": self.tick_i,
                              "plant_time_min": self.tick_i * config.MINUTES_PER_TICK,
                              "agent_mode": config.agent_mode(), "fleet": fleet_msg,
                              "business": self._business_summary()})

        # detect NEW alerts (assets crossing the threshold while still degrading)
        for eid, a in self.assets.items():
            st = self.sim.assets[eid]
            resume_requested = eid in self._resume
            threshold_met = a["failure_prob"] >= config.TRIGGER_THRESHOLD
            signal_condition = (threshold_met and eid not in self.alerts
                                and eid not in self._analyzing and st.mode == "degrading")
            should_admit = resume_requested or signal_condition
            if self._guided_owner == eid and self._guided_incident_id is None:
                if resume_requested:
                    skip_reason = None
                elif not threshold_met:
                    skip_reason = "failure_probability_below_trigger"
                elif eid in self.alerts:
                    skip_reason = "active_alert_exists"
                elif eid in self._analyzing:
                    skip_reason = "admission_already_in_progress"
                elif st.mode != "degrading":
                    skip_reason = f"simulator_mode_{st.mode}"
                else:
                    skip_reason = None
                self._trace_reasoning(
                    "guided_admission_tick", equipment_id=eid, backend=self._guided_backend,
                    task_kind="guided", task_creation_location="core.engine.DemoEngine._advance",
                    simulator_running=self.running,
                    simulator_state={"mode": st.mode, "scenario": st.profile.scenario,
                                     "progress": st.prog, "asset_tick": st.tick,
                                     "start_tick": st.profile.start_tick,
                                     "ramp_ticks": st.profile.ramp_ticks},
                    raw_telemetry={key: float(a[key]) for key in
                                   ("air_temp", "process_temp", "rot_speed", "torque", "tool_wear")},
                    model_failure_prob=float(a["failure_prob"]),
                    predicted_failure_mode=a["predicted_mode"]["mode"],
                    incident_trigger_threshold=float(config.TRIGGER_THRESHOLD),
                    signal_condition_met=signal_condition,
                    telemetry_persisted=persistence["telemetry"],
                    health_score_persisted=persistence["health_scores"],
                    predictive_signal_persisted=False,
                    admission_decision="attempt" if should_admit else "skipped",
                    admission_skip_reason=skip_reason,
                )
            if should_admit:
                try:
                    await self._fire_agent(eid)
                except Exception as exc:
                    if self._guided_owner == eid:
                        self._trace_reasoning(
                            "guided_admission_rejected", equipment_id=eid, backend=self._guided_backend,
                            task_kind="guided", admission_decision="rejected",
                            admission_skip_reason=f"{type(exc).__name__}: {exc}",
                            predictive_signal_persisted=False,
                        )
                    logger.exception("Incident admission/planning persistence failed for %s", eid)
                    await self.broadcast({"type": "error", "equipment_id": eid,
                                          "error": "incident admission or legacy planning failed; retrying"})
        if not self.legacy_demo:
            self._progress_lifecycle()
            for message in self._pending_broadcasts:
                await self.broadcast(message)
            self._pending_broadcasts = []
        if self._guided_demo is not None:
            await self._broadcast_demo()

        # unplanned failures for rejected assets
        for eid in list(self.alerts):
            if self.alerts[eid]["status"] == "REJECTED" and self.sim.failed(eid):
                await self._unplanned_failure(eid)

    def _asset_summary(self, eid: str) -> dict:
        a = self.assets[eid]
        incident = self.incidents.get(eid)
        override = self.status_override.get(eid)
        status_source = "active_incident" if override is not None and incident is not None else "model_risk"
        return {"equipment_id": eid, "name": a["name"], "equipment_class": a["equipment_class"],
                "criticality": a["criticality"], "status": a["status"],
                "status_source": status_source,
                "status_reason": (f"Active incident {incident.phase.value}" if status_source == "active_incident"
                                  else "Current model risk thresholds"),
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
        signal = self._signal(eid, ctx)
        incident, created = self.lifecycle.admit(
            signal, severity="CRITICAL" if ctx["criticality"] == "HIGH" else "HIGH",
            triage_score=agent.triage_score(ctx))
        self.incidents[eid] = incident
        if self._guided_owner == eid:
            if self._guided_incident_id not in {None, incident.id}:
                raise RuntimeError("guided ownership incident changed without reset")
            self._guided_incident_id = incident.id
            if self._guided_demo is not None:
                self._guided_demo["incident_id"] = incident.id
                self._set_guided_status("incident_open")
            self._trace_reasoning(
                "guided_incident_admitted_and_ownership_bound",
                equipment_id=eid,
                incident_id=incident.id,
                backend=self._guided_backend,
                task_kind="guided",
                ownership_revalidation_result="matched_equipment_and_incident",
                predictive_signal_id=signal.id,
                predictive_signal_persisted=True,
                admission_decision="created" if created else "adopted_existing",
                admission_skip_reason=None,
            )
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
        if self._guided_owner == eid:
            self._trace_reasoning(
                "guided_incident_investigating", equipment_id=eid, incident_id=incident.id,
                backend=self._guided_backend, task_kind="guided",
                ownership_revalidation_result=(
                    "matched_equipment_and_incident"
                    if self._guided_incident_id == incident.id else "incident_mismatch"),
                predictive_signal_id=signal.id, predictive_signal_persisted=True,
                admission_decision="investigated",
                phase_transition_result={"from": incident.phase.value,
                                         "phase": self.incidents[eid].phase.value},
            )
        self._resume.discard(eid)
        if self._guided_owner == eid:
            self._set_guided_status("investigating")
        self.alerts[eid] = self._lifecycle_alert(eid, ctx)
        self._retriage()
        await self.broadcast({"type": "alert", "alert": self.alerts[eid], "phase": "investigating",
                              "triage": self._triage_msg()})
        self._schedule_diagnosis(eid)

    def _guided_claim_is_current(self, eid: str, incident_id: str, claim: object) -> bool:
        return (
            self._guided_owner == eid
            and self._guided_claim is claim
            and self._guided_incident_id == incident_id
            and self.incidents.get(eid) is not None
            and self.incidents[eid].id == incident_id
        )

    @staticmethod
    def _backend_identity(backend) -> dict | None:
        if backend is None:
            return None
        try:
            return backend.identity()
        except Exception as exc:  # diagnostics must never alter scheduling
            return {"implementation": f"{type(backend).__module__}.{type(backend).__qualname__}",
                    "identity_error": type(exc).__name__}

    def _trace_reasoning(self, event: str, *, equipment_id: str | None = None,
                         incident_id: str | None = None, backend=None, task=None, **values):
        """Bounded structured scheduling trace; contains no model prompts or reasoning."""
        equipment_id = equipment_id or self._guided_owner
        incident = self.incidents.get(equipment_id) if equipment_id else None
        incident_id = incident_id or (incident.id if incident is not None else None)
        phase = None
        if incident_id is not None:
            try:
                phase = self.coordinator.repository.fetch_incident(incident_id).phase.value
            except Exception:
                phase = None
        task = task or asyncio.current_task()
        record = {
            "event": event,
            "incident_id": incident_id,
            "equipment_id": equipment_id,
            "current_phase": phase,
            "guided_ownership_claim": (f"claim:{id(self._guided_claim):x}" if self._guided_claim is not None else None),
            "ownership_exists": self._guided_owner == equipment_id if equipment_id else False,
            "task_identity": ({"id": f"task:{id(task):x}", "name": task.get_name()} if task else None),
            "task_creation_location": None,
            "backend_identity_captured": self._backend_identity(backend),
            "task_kind": None,
            "reasoning_backend_invoked": None,
            "runtime_identity_invoked": None,
            "diagnosis_scheduling_decision": None,
            "ownership_revalidation_result": None,
            "cancellation_result": None,
            "lifecycle_diagnose_entry": False,
            "lifecycle_diagnose_exit": False,
            "phase_transition_result": None,
            **values,
        }
        self._reasoning_diagnostics.append(record)
        self._reasoning_diagnostics = self._reasoning_diagnostics[-200:]
        # run.py intentionally serves at warning level. Guided ownership traces are
        # therefore visible in the real launcher; ordinary scheduler traces stay quiet.
        level = logging.WARNING if record["ownership_exists"] or record["task_kind"] == "guided" else logging.INFO
        logger.log(level, "reasoning_diagnostic=%s", json.dumps(record, sort_keys=True, default=str))

    def _release_guided_ownership(self, equipment_id: str | None = None, *, claim: object | None = None,
                                  reason: str) -> bool:
        if equipment_id is not None and self._guided_owner != equipment_id:
            return False
        if claim is not None and self._guided_claim is not claim:
            return False
        if self._guided_owner is None:
            return False
        self._trace_reasoning(
            "guided_ownership_released",
            equipment_id=self._guided_owner,
            incident_id=self._guided_incident_id,
            backend=self._guided_backend,
            task_kind="guided",
            cancellation_result=reason,
        )
        self._guided_owner = None
        self._guided_claim = None
        self._guided_incident_id = None
        self._guided_backend = None
        return True

    def _schedule_diagnosis(self, eid: str):
        incident = self.incidents.get(eid)
        if incident is not None and incident.phase == IncidentPhase.INVESTIGATING and self._guided_owner == eid:
            self._trace_reasoning(
                "normal_diagnosis_suppressed",
                equipment_id=eid,
                incident_id=incident.id,
                backend=self._base_runtime,
                task_kind="normal",
                task_creation_location="core.engine.DemoEngine._schedule_diagnosis",
                diagnosis_scheduling_decision="suppressed_guided_owner",
                ownership_revalidation_result="guided_claim_present",
            )
            return
        runtime, specialist_runtime = self._base_runtime, self.specialist_runtime
        if runtime is None or incident is None or incident.phase != IncidentPhase.INVESTIGATING:
            return
        if incident.id in self.prism.coordinator.active_incident_ids():
            # An operator-driven PRISM revision is reasoning over this incident: the autonomous
            # diagnosis would only supersede its claim. It resumes once the PRISM run is done.
            self._trace_reasoning(
                "normal_diagnosis_suppressed", equipment_id=eid, incident_id=incident.id, backend=runtime,
                task_kind="normal", task_creation_location="core.engine.DemoEngine._schedule_diagnosis",
                diagnosis_scheduling_decision="suppressed_prism_active", ownership_revalidation_result="prism_run_active")
            return
        task = self._lifecycle_tasks.get(eid)
        if task is not None and not task.done():
            return
        retry = self._reasoning_retries.setdefault(eid, ReasoningRetryState())
        if self._monotonic() < retry.next_retry_at:
            return
        created = asyncio.create_task(
            self._diagnose(eid, incident.id, runtime, specialist_runtime),
            name=f"normal-diagnosis:{eid}:{incident.id}",
        )
        self._lifecycle_tasks[eid] = created
        self._trace_reasoning(
            "normal_diagnosis_scheduled",
            equipment_id=eid,
            incident_id=incident.id,
            backend=runtime,
            task=created,
            task_kind="normal",
            task_creation_location="core.engine.DemoEngine._schedule_diagnosis",
            diagnosis_scheduling_decision="scheduled_normal",
            ownership_revalidation_result="no_guided_claim",
        )

    def _record_reasoning_failure(self, eid: str, exc: Exception) -> float:
        retry = self._reasoning_retries.setdefault(eid, ReasoningRetryState())
        retry.failures = min(retry.failures + 1, 7)
        delay = min(REASONING_RETRY_BASE_SECONDS * (2 ** (retry.failures - 1)), REASONING_RETRY_MAX_SECONDS)
        retry.next_retry_at = self._monotonic() + delay
        key = f"{type(exc).__module__}.{type(exc).__qualname__}:{exc}"
        if retry.last_error_key != key:
            logger.error("Durable supervisor diagnosis failed for %s; retry deferred %.1fs", eid, delay,
                         exc_info=(type(exc), exc, exc.__traceback__))
        else:
            logger.warning("Durable supervisor diagnosis still unavailable for %s; retry deferred %.1fs: %s",
                           eid, delay, exc)
        retry.last_error_key = key
        return delay

    async def _diagnose(self, eid: str, incident_id: str, runtime, specialist_runtime):
        outcome = None
        try:
            async with self._reasoning_lock:
                # The normal backend is captured when scheduled, then ownership and
                # incident identity are revalidated immediately before lifecycle authority.
                current = self.incidents.get(eid)
                if self._guided_owner == eid or current is None or current.id != incident_id:
                    self._trace_reasoning(
                        "normal_diagnosis_revalidation_refused",
                        equipment_id=eid,
                        incident_id=incident_id,
                        backend=runtime,
                        task_kind="normal",
                        ownership_revalidation_result=(
                            "guided_claim_present" if self._guided_owner == eid else "incident_mismatch"),
                        diagnosis_scheduling_decision="refused_before_lifecycle",
                    )
                    return
                current = self.coordinator.repository.fetch_incident(incident_id)
                if current.phase != IncidentPhase.INVESTIGATING:
                    return
                identity = self._backend_identity(runtime)
                self._trace_reasoning(
                    "lifecycle_diagnose_entered",
                    equipment_id=eid,
                    incident_id=incident_id,
                    backend=runtime,
                    task_kind="normal",
                    reasoning_backend_invoked=identity,
                    runtime_identity_invoked=identity,
                    ownership_revalidation_result="no_guided_claim",
                    lifecycle_diagnose_entry=True,
                )
                outcome = await self.lifecycle.diagnose(
                    incident_id, asset_id=eid, runtime=runtime, evidence_service=self.evidence_service,
                    specialist_runtime=specialist_runtime)
        except asyncio.CancelledError:
            self._trace_reasoning(
                "normal_diagnosis_cancelled",
                equipment_id=eid,
                incident_id=incident_id,
                backend=runtime,
                task_kind="normal",
                cancellation_result="cancelled_and_propagated",
            )
            raise
        except Exception as exc:
            self._record_reasoning_failure(eid, exc)
        else:
            if outcome is not None and outcome.disposition != "RETRY":
                self._reasoning_retries.pop(eid, None)
            elif outcome is not None:
                self._record_reasoning_failure(eid, RuntimeError(outcome.reason))
        if outcome is not None:
            current = self.coordinator.repository.fetch_incident(incident_id)
            self._trace_reasoning(
                "lifecycle_diagnose_exited",
                equipment_id=eid,
                incident_id=incident_id,
                backend=runtime,
                task_kind="normal",
                lifecycle_diagnose_exit=True,
                phase_transition_result={"phase": current.phase.value, "disposition": outcome.disposition},
            )
        await self._refresh_lifecycle(eid, outcome.disposition.lower() if outcome else "error",
                                      reason=outcome.reason if outcome else None)

    async def _diagnose_guided(self, eid: str, incident_id: str, backend, claim: object):
        """The sole guided diagnosis actor; its backend and claim are immutable inputs."""
        async with self._reasoning_lock:
            claim_valid = self._guided_claim_is_current(eid, incident_id, claim)
            self._trace_reasoning(
                "guided_diagnosis_revalidated",
                equipment_id=eid,
                incident_id=incident_id,
                backend=backend,
                task_kind="guided",
                task_creation_location="core.engine.DemoEngine.start_guided_demo",
                diagnosis_scheduling_decision="guided_controller_invokes",
                ownership_revalidation_result="matched" if claim_valid else "refused",
            )
            if not claim_valid:
                raise RuntimeError("guided diagnosis ownership is no longer current")
            current = self.coordinator.repository.fetch_incident(incident_id)
            if current.phase != IncidentPhase.INVESTIGATING:
                raise RuntimeError(f"guided diagnosis requires INVESTIGATING, got {current.phase.value}")
            identity = self._backend_identity(backend)
            self._trace_reasoning(
                "lifecycle_diagnose_entered",
                equipment_id=eid,
                incident_id=incident_id,
                backend=backend,
                task_kind="guided",
                reasoning_backend_invoked=identity,
                runtime_identity_invoked=identity,
                ownership_revalidation_result="matched",
                lifecycle_diagnose_entry=True,
            )
            try:
                outcome = await self.lifecycle.diagnose(
                    incident_id, asset_id=eid, runtime=backend,
                    evidence_service=self.evidence_service, specialist_runtime=None,
                )
            except asyncio.CancelledError:
                self._trace_reasoning(
                    "guided_diagnosis_cancelled",
                    equipment_id=eid,
                    incident_id=incident_id,
                    backend=backend,
                    task_kind="guided",
                    cancellation_result="cancelled_and_awaited_by_owner",
                )
                raise
        current = self.coordinator.repository.fetch_incident(incident_id)
        self._trace_reasoning(
            "lifecycle_diagnose_exited",
            equipment_id=eid,
            incident_id=incident_id,
            backend=backend,
            task_kind="guided",
            lifecycle_diagnose_exit=True,
            phase_transition_result={"phase": current.phase.value, "disposition": outcome.disposition},
        )
        await self._refresh_lifecycle(eid, outcome.disposition.lower(), reason=outcome.reason)
        return outcome

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
            if verification.disposition in {"CLOSED", "ESCALATED"}:
                self._release_guided_ownership(eid, reason=f"outcome_{verification.disposition.lower()}")
            self._pending_broadcasts.append({"type": "demo", "demo_scenario": self._demo_projection()})

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

    @staticmethod
    def _agent_run_view(report, snapshot) -> dict:
        """One supervisor run for the portal: audit fields plus the normalized reasoning provenance."""
        result = report.result_payload
        identity = snapshot.runtime_identity if snapshot else {}
        return {
            "run_id": report.run_id, "stage": snapshot.stage if snapshot else None,
            "status": report.completion, "input_revision": report.input_revision,
            "checkpoint_revision": report.checkpoint_revision,
            "runtime_identity": identity,
            "version_identity": snapshot.version_identity if snapshot else {},
            "reasoning": describe_run_identity(identity),
            "disposition": result.get("disposition"),
            "summary": (result.get("decision") or {}).get("reasoning_summary"),
            "delegations": result.get("delegations", []), "assessments": result.get("assessments", []),
            "evidence_requests": result.get("evidence_requests", []), "blockers": result.get("blockers", []),
            # A provider/model failure is the primary fact of a failed run; governance
            # completeness gaps (e.g. "requires explicit critic review") still hold but
            # describe the empty run, so the portal shows them second.
            "failure": next((item for item in result.get("blockers", [])
                             if item.startswith("Model invocation failed")), None),
            "termination_reason": result.get("termination_reason"),
            "human_review_required": result.get("human_review_required", True),
            "tool_calls": result.get("tool_calls", 0), "stale_reasons": list(report.stale_reasons),
            "artifact_id": report.id, "snapshot_id": snapshot.id if snapshot else None,
        }

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
        agent_runs = [self._agent_run_view(report, snapshots_by_run.get(report.run_id)) for report in reports]
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

        # The legacy path consults the governance peer (a bounded model call): keep it off the loop.
        proposal = await asyncio.to_thread(agent.decide, ctx)
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
            msg["monitoring"] = self._peer_monitoring(snap)
        except Exception:
            pass
        return msg

    def _peer_monitoring(self, snap: dict) -> dict:
        """Monitoring peer assessment that never blocks the event loop.

        The LLM-backed adapter performs a bounded model call. That call runs in a
        worker thread, keyed by the active alert set and cached once it lands; until
        then the deterministic correlation engine answers immediately (marked
        ``pending``) so no broadcast or websocket frame waits on a model.
        """
        from .services.adapters.local import LocalMonitoringAdapter
        alerts = snap.get("alerts") or []
        key = frozenset(a.get("equipment_id") for a in alerts)
        cached = self._monitoring_cache.get(key)
        if cached is not None:
            return cached
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:  # synchronous caller (tests, scripts): no loop to protect
            result = services.monitoring().assess(snap)
            self._remember_monitoring(key, result)
            return result
        task = self._monitoring_tasks.get(key)
        if task is None or task.done():
            self._monitoring_tasks[key] = loop.create_task(self._refresh_monitoring(snap, key),
                                                           name=f"monitoring-peer:{len(key)}")
        return {**LocalMonitoringAdapter().assess(snap), "pending": True}

    def _remember_monitoring(self, key: frozenset, result: dict) -> None:
        self._monitoring_cache[key] = result
        while len(self._monitoring_cache) > 32:
            self._monitoring_cache.pop(next(iter(self._monitoring_cache)))

    async def _refresh_monitoring(self, snap: dict, key: frozenset) -> None:
        try:
            result = await asyncio.to_thread(services.monitoring().assess, snap)
        except Exception:  # noqa: BLE001 - the peer is best-effort; the deterministic answer stands
            logger.debug("monitoring peer unavailable; deterministic correlation retained", exc_info=True)
            return
        finally:
            self._monitoring_tasks.pop(key, None)
        self._remember_monitoring(key, result)
        if self.alerts and frozenset(self.alerts) & key:
            await self.broadcast({"type": "triage", "triage": self._triage_msg()})

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
                self._release_guided_ownership(eid, reason="execution_failed")
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
        if self._release_guided_ownership(eid, reason="approval_rejected"):
            await self._broadcast_demo()
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
        eid = self._eid_for(incident_id)
        if eid is not None and self._guided_owner == eid:
            return {"ok": False, "error": "guided controller owns reasoning for this incident"}
        return await self._plan_with_runtime(
            incident_id, expected_revision=expected_revision,
            runtime=self._base_runtime, specialist_runtime=self.specialist_runtime,
            **binding_fields,
        )

    async def _plan_with_runtime(self, incident_id: str, *, expected_revision: int, runtime,
                                 specialist_runtime, guided_claim: object | None = None,
                                 **binding_fields) -> dict:
        eid = self._eid_for(incident_id)
        if runtime is None:
            return {"ok": False, "error": "no supervisor runtime configured; exact-draft review cannot run"}
        async with self._reasoning_lock:
            if guided_claim is not None:
                if eid is None or not self._guided_claim_is_current(eid, incident_id, guided_claim):
                    return {"ok": False, "error": "guided planning ownership is no longer current"}
            elif eid is not None and self._guided_owner == eid:
                return {"ok": False, "error": "guided controller owns reasoning for this incident"}
            outcome = await self.lifecycle.plan(incident_id, runtime=runtime, evidence_service=self.evidence_service,
                                                specialist_runtime=specialist_runtime,
                                                expected_revision=expected_revision, **binding_fields)
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
        return {"type": "snapshot", "tick": self.tick_i, "running": self.running,
                "agent_mode": config.agent_mode(), "app_name": config.APP_NAME,
                "authority_path": "legacy-demo" if self.legacy_demo else "lifecycle",
                "supervisor_available": self.runtime is not None,
                "reasoning_provenance": self.reasoning_provenance(),
                "tagline": config.APP_TAGLINE, "plant_name": config.PLANT_NAME,
                "trigger_threshold": config.TRIGGER_THRESHOLD, "warn_threshold": config.WARN_THRESHOLD,
                "fleet": [self._asset_summary(e) for e in self.meta if e in self.assets],
                "histories": self.histories,
                "alerts": list(self.alerts.values()),
                "triage": self._triage_msg(),
                "business": self._business_summary(), "demo_scenario": self._demo_projection(),
                "prism": self.prism.overview()}

    def reasoning_provenance(self) -> dict:
        """Non-secret description of the engine's configured reasoning: backend, provider, model.

        This is what *normal* incidents use. A Guided Demo reports the backend its own
        runs use under ``demo_scenario.reasoning`` (identical when a provider is
        configured, ``deterministic`` otherwise).
        """
        available = self.runtime is not None
        description = describe_backend(self.runtime)
        if not available:
            description["backend"] = config.reasoning_backend()
        return {
            **description,
            "status": "available" if available else "awaiting_runtime",
            "application": "Operon",
            "unavailable_reason": None if available else self._runtime_unavailable_reason,
        }

    async def broadcast(self, msg: dict):
        dead, data = [], json.dumps(msg, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)
