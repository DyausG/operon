"""
FastAPI application — serves the dashboard, streams live fleet telemetry + agent
activity over a WebSocket, and exposes the human-in-the-loop control endpoints
(approve / reject / reset) for the concurrent-alert queue.

Trust boundary (Step 13B). This host has no authentication layer. Endpoint
presence therefore establishes no actor identity:

* Approval/rejection/execution endpoints accept only exact identifiers
  (requirement, intervention, hash, context revision); the lifecycle service
  rejects stale or mismatched intent atomically. The actor recorded is the
  caller-declared dashboard operator; a real deployment must authenticate it.
* Human-input endpoints (technical/resource confirmation, draft binding, sandbox
  work acknowledgement and report) are enabled by OPERON_ENVIRONMENT=sandbox (F1).
  The pre-F1 OPERON_TRUSTED_SUBMISSIONS flag is a TEMPORARY fallback outside
  production only. They accept the typed schemas only; no endpoint accepts
  PromotionRecord, ValidationVerdict, SupervisorReport or any other authority JSON.
* F1 actor kinds are assigned here, never chosen by the caller: SANDBOX in a
  sandbox environment, DECLARED in the unspecified local environment. Production
  refuses every human command until authenticated identity exists (F3).
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Literal

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core import config
from core.reliability import models as m
from core.reliability.actors import ActorRefused, request_actor_kind
from core.seed_data import seed
from core.engine import DemoEngine
from server.prism_api import register_prism_routes
from server.providers_api import register_provider_routes

app = FastAPI(title=f"{config.APP_NAME} — {config.APP_TAGLINE}")
engine: DemoEngine | None = None


class ApprovalIntent(BaseModel):
    """Exact approval intent; equipment ID alone can never approve."""
    model_config = ConfigDict(extra="forbid")
    requirement_id: str = Field(min_length=1)
    intervention_id: str = Field(min_length=1)
    intervention_hash: str = Field(min_length=1)
    context_revision: int = Field(ge=1)
    actor_id: str = "dashboard-operator"
    actor_role: str = "maintenance_approver"
    rationale: str = "decided in Operon dashboard"
    # F1: where a rejection sends the case. Default: back to planning (not escalation).
    return_to: Literal["PLANNING", "INVESTIGATING", "ESCALATED"] = "PLANNING"


class ApprovalCommand(ApprovalIntent):
    decision: Literal["APPROVE", "REJECT"]


class ActorFields(BaseModel):
    """The caller's declared id and role. The kind is assigned by the server (F1)."""
    model_config = ConfigDict(extra="forbid")
    actor_id: str = Field(min_length=1, max_length=200)
    actor_role: str | None = Field(default=None, max_length=100)


class LifecycleCommandBody(ActorFields):
    expected_revision: int = Field(ge=1)
    rationale: str = Field(min_length=1, max_length=2000)


class WorkAcknowledgement(ActorFields):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)
    # F1.2: optional client key; an identical retry is answered from the durable record.
    request_key: str | None = Field(default=None, min_length=1, max_length=128)


class WorkReportSubmission(ActorFields):
    expected_revision: int = Field(ge=1)
    result: Literal["COMPLETED", "PARTIAL", "NOT_PERFORMED"]
    summary: str = Field(min_length=1, max_length=2000)
    findings: tuple[str, ...] = Field(default=(), max_length=20)
    performed_at: datetime | None = None
    # F1.2 (operon-work-eligibility-1): COMPLETED/PARTIAL must attest whether physical work
    # was performed on the asset; PARTIAL names the completed instruction indices.
    asset_intervened: bool | None = None
    completed_instructions: tuple[int, ...] | None = Field(default=None, max_length=50)
    request_key: str | None = Field(default=None, min_length=1, max_length=128)


class WorkDecline(ActorFields):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    request_key: str | None = Field(default=None, min_length=1, max_length=128)


class ReassignWorkBody(LifecycleCommandBody):
    assignment_id: str = Field(min_length=1)
    assignee_reference: str | None = Field(default=None, min_length=1, max_length=200)
    request_key: str | None = Field(default=None, min_length=1, max_length=128)


class ExecutionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intervention_id: str = Field(min_length=1)
    intervention_hash: str = Field(min_length=1)


class TechnicalSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    confirmation: m.TrustedTechnicalConfirmation


class ResourceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    confirmation: m.ResourceConfirmation


class DraftSubmission(BaseModel):
    """Structured trusted binding fields; planner prose is never accepted here."""
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    binding: dict


class DemoScenarioCommand(BaseModel):
    """Explicit entry into the Guided Demo Scenario (real lifecycle, configured reasoning)."""
    model_config = ConfigDict(extra="forbid")
    equipment_id: str = "AC-COMP-01"


def _status(result: dict, *, refused=409):
    return JSONResponse(result, status_code=200 if result.get("ok") else refused)


def _trusted_disabled():
    return JSONResponse({"ok": False, "error": "human-input endpoints are disabled outside a sandbox; set "
                         "OPERON_ENVIRONMENT=sandbox for synthetic plant validation"}, status_code=403)


def _human_inputs_enabled() -> bool:
    """F1 sandbox gate; the pre-F1 trusted-host flag is a temporary fallback, never in production."""
    environment = config.environment()
    return environment == "sandbox" or (environment != "production" and config.trusted_submissions_enabled())


def _actor_kind():
    try:
        return request_actor_kind(), None
    except ActorRefused as exc:
        return None, JSONResponse({"ok": False, "error": str(exc)}, status_code=403)


def _actor(fields: ActorFields):
    kind, refused = _actor_kind()
    if refused is not None:
        return None, refused
    return m.ActorRef(kind=kind, id=fields.actor_id, role=fields.actor_role), None


@app.on_event("startup")
async def _startup():
    global engine
    seed(reset=False)
    engine = DemoEngine()
    await engine.start()


# ---- REST ----------------------------------------------------------------
@app.get("/api/health")
async def health():
    registry = config.provider_registry()
    return {"ok": True, "agent_mode": config.agent_mode(), "provider": registry.resolve_kind(),
            "reasoning_backend": config.reasoning_backend(),
            "supervisor_available": bool(engine and engine.runtime is not None),
            "running": engine.running if engine else False}


# ---- AI provider configuration (Stage 0; no secrets are ever returned) ----
register_provider_routes(app, lambda: engine)

# ---- PRISM interruptible runtime (Stage 1): sessions, operator messages, reconnect ----
register_prism_routes(app, lambda: engine.prism if engine is not None else None)


@app.get("/api/state")
async def state():
    return JSONResponse(engine.snapshot())


@app.get("/api/demo/artifacts/{artifact_id}")
async def demo_artifact(artifact_id: str):
    """Inspector detail for one durable artifact of an active incident (Guided Demo or live)."""
    try:
        return JSONResponse(engine.demo_artifact(artifact_id))
    except LookupError:
        return JSONResponse({"ok": False, "error": "unknown demo artifact"}, status_code=404)


@app.post("/api/start")
async def start():
    await engine.start()
    return {"ok": True, "running": engine.running}


@app.post("/api/stop")
async def stop():
    await engine.stop()
    return {"ok": True, "running": engine.running}


@app.post("/api/approve/{equipment_id}")
async def approve(equipment_id: str, intent: ApprovalIntent | None = Body(default=None)):
    """Lifecycle mode requires exact intent in the body; the legacy demo ignores it."""
    if engine.legacy_demo:
        return await engine.approve(equipment_id)
    if intent is None:
        return _status({"ok": False, "error": "approval must identify the exact requirement, intervention, "
                        "intervention hash and context revision"}, refused=400)
    kind, refused = _actor_kind()
    if refused is not None:
        return refused
    return _status(await engine.approve(equipment_id, intent.model_dump() | {"actor_kind": kind}))


@app.post("/api/reject/{equipment_id}")
async def reject(equipment_id: str, intent: ApprovalIntent | None = Body(default=None)):
    if engine.legacy_demo:
        return await engine.reject(equipment_id)
    if intent is None:
        return _status({"ok": False, "error": "rejection must identify the exact requirement, intervention, "
                        "intervention hash and context revision"}, refused=400)
    kind, refused = _actor_kind()
    if refused is not None:
        return refused
    return _status(await engine.reject(equipment_id, intent.model_dump() | {"actor_kind": kind}))


# ---- Durable lifecycle (Step 13B) ----------------------------------------
@app.get("/api/incidents/{incident_id}")
async def incident(incident_id: str):
    try:
        return engine.incident_view(incident_id)
    except LookupError:
        return JSONResponse({"ok": False, "error": "unknown incident"}, status_code=404)


@app.post("/api/incidents/{incident_id}/approval")
async def approval(incident_id: str, command: ApprovalCommand):
    eid = engine._eid_for(incident_id)
    if eid is None:
        return JSONResponse({"ok": False, "error": "unknown incident"}, status_code=404)
    kind, refused = _actor_kind()
    if refused is not None:
        return refused
    handler = engine.approve if command.decision == "APPROVE" else engine.reject
    return _status(await handler(eid, command.model_dump(exclude={"decision"}) | {"actor_kind": kind}))


@app.post("/api/incidents/{incident_id}/commands/reassign_work")
async def reassign_work(incident_id: str, body: ReassignWorkBody):
    """F1.2: a new assignment for the same dispatch after the current one was declined or did not qualify."""
    actor, refused = _actor(body)
    if refused is not None:
        return refused
    return _status(await engine.lifecycle_command(
        incident_id, "reassign_work", assignment_id=body.assignment_id, expected_revision=body.expected_revision,
        actor=actor, rationale=body.rationale, assignee_reference=body.assignee_reference, request_key=body.request_key))


@app.post("/api/incidents/{incident_id}/commands/{command}")
async def lifecycle_command(incident_id: str, command: Literal["resume", "cancel", "escalate", "renew_approval",
                                                               "return_to_planning", "retry_execution"],
                            body: LifecycleCommandBody):
    """F1 recovery commands. Each re-enters the state machine through one validated transition."""
    actor, refused = _actor(body)
    if refused is not None:
        return refused
    return _status(await engine.lifecycle_command(incident_id, command, expected_revision=body.expected_revision,
                                                  actor=actor, rationale=body.rationale))


@app.post("/api/incidents/{incident_id}/work/{assignment_id}/acknowledge")
async def acknowledge_work(incident_id: str, assignment_id: str, body: WorkAcknowledgement):
    """Sandbox field response: the assignee acknowledges the work request (not performance)."""
    if not _human_inputs_enabled():
        return _trusted_disabled()
    actor, refused = _actor(body)
    if refused is not None:
        return refused
    return _status(await engine.lifecycle_command(incident_id, "acknowledge_work", assignment_id=assignment_id,
                                                  expected_revision=body.expected_revision, actor=actor, note=body.note,
                                                  request_key=body.request_key))


@app.post("/api/incidents/{incident_id}/work/{assignment_id}/decline")
async def decline_work(incident_id: str, assignment_id: str, body: WorkDecline):
    """Sandbox field response (F1.2): the assignee declines an unacknowledged request. No plant actuation."""
    if not _human_inputs_enabled():
        return _trusted_disabled()
    actor, refused = _actor(body)
    if refused is not None:
        return refused
    return _status(await engine.lifecycle_command(incident_id, "decline_work", assignment_id=assignment_id,
                                                  expected_revision=body.expected_revision, actor=actor,
                                                  reason=body.reason, request_key=body.request_key))


@app.post("/api/incidents/{incident_id}/work/{assignment_id}/response")
async def report_work(incident_id: str, assignment_id: str, body: WorkReportSubmission):
    """Sandbox field response: the assignee reports the work. Never verification of recovery.

    F1.2: whatever the caller says, a report about the simulated plant is SIMULATED
    provenance; only a production process (which refuses unauthenticated humans until
    F3) could record OBSERVED work.
    """
    if not _human_inputs_enabled():
        return _trusted_disabled()
    actor, refused = _actor(body)
    if refused is not None:
        return refused
    return _status(await engine.lifecycle_command(
        incident_id, "report_work", assignment_id=assignment_id, expected_revision=body.expected_revision,
        actor=actor, result=body.result, summary=body.summary, findings=body.findings,
        performed_at=body.performed_at, asset_intervened=body.asset_intervened,
        completed_instructions=body.completed_instructions, request_key=body.request_key,
        provenance="OBSERVED" if config.environment() == "production" else "SIMULATED"))


@app.post("/api/incidents/{incident_id}/execute")
async def execute(incident_id: str, command: ExecutionCommand):
    """Explicit dispatch of a READY incident (e.g. after a restart). Never automatic."""
    return _status(await engine.execute(incident_id, command.intervention_id,
                                        intervention_hash=command.intervention_hash))


@app.post("/api/incidents/{incident_id}/outcome")
async def verify_outcome(incident_id: str):
    """Explicit deterministic outcome verification of an OBSERVING incident (Step 14).

    The same application authority the engine tick applies; no body is accepted and
    no caller can supply an outcome, evidence or closure.
    """
    return _status(await engine.verify_outcome(incident_id))


@app.post("/api/incidents/{incident_id}/confirmations/technical")
async def technical_confirmation(incident_id: str, submission: TechnicalSubmission):
    if not _human_inputs_enabled():
        return _trusted_disabled()
    if submission.confirmation.incident_id != incident_id:
        return _status({"ok": False, "error": "confirmation incident mismatch"}, refused=400)
    kind, refused = _actor_kind()
    if refused is not None:
        return refused
    confirmation = submission.confirmation.model_copy(update={"actor_kind": kind})  # never caller-chosen
    try:
        return engine.submit_technical_confirmation(confirmation, expected_revision=submission.expected_revision)
    except Exception as exc:  # typed refusals from the promotion boundary
        return _status({"ok": False, "error": str(exc)})


@app.post("/api/incidents/{incident_id}/confirmations/resource")
async def resource_confirmation(incident_id: str, submission: ResourceSubmission):
    if not _human_inputs_enabled():
        return _trusted_disabled()
    if submission.confirmation.incident_id != incident_id:
        return _status({"ok": False, "error": "confirmation incident mismatch"}, refused=400)
    kind, refused = _actor_kind()
    if refused is not None:
        return refused
    confirmation = submission.confirmation.model_copy(update={"actor_kind": kind})  # never caller-chosen
    try:
        return engine.submit_resource_confirmation(confirmation, expected_revision=submission.expected_revision)
    except Exception as exc:
        return _status({"ok": False, "error": str(exc)})


@app.post("/api/incidents/{incident_id}/drafts")
async def draft(incident_id: str, submission: DraftSubmission):
    """Trusted binding -> DRAFT -> fresh exact-draft review -> promotion -> approval requirement."""
    if not _human_inputs_enabled():
        return _trusted_disabled()
    try:
        return _status(await engine.plan(incident_id, expected_revision=submission.expected_revision, **submission.binding))
    except (ValidationError, TypeError) as exc:
        return _status({"ok": False, "error": f"invalid binding: {exc}"}, refused=400)
    except Exception as exc:
        return _status({"ok": False, "error": str(exc)})


@app.post("/api/reset")
async def reset():
    await engine.reset()
    return {"ok": True, "state": engine.snapshot()}


@app.post("/api/demo/scenario")
async def guided_demo(command: DemoScenarioCommand):
    """Start the Guided Demo Scenario on the real lifecycle with the configured reasoning backend."""
    return _status(await engine.start_guided_demo(command.equipment_id), refused=400)


# ---- WebSocket -----------------------------------------------------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    engine.clients.add(websocket)
    await websocket.send_text(json.dumps(engine.snapshot(), default=str))
    # NB: don't auto-start here — the loop is started at app startup, and a
    # reconnect must not override a deliberate Stop. Resume is explicit (/api/start).
    try:
        while True:
            await websocket.receive_text()  # keepalive; inbound ignored
    except WebSocketDisconnect:
        engine.clients.discard(websocket)
    except Exception:
        engine.clients.discard(websocket)


# ---- Static frontend (mounted LAST so /api and /ws win) ------------------
_PLACEHOLDER = f"""<!doctype html><html><head><meta charset=utf-8>
<title>{config.APP_NAME}</title><style>body{{font-family:system-ui;background:#0b0f17;color:#e6edf3;
display:grid;place-items:center;height:100vh;margin:0}}code{{color:#7ee787}}</style></head>
<body><div><h1>{config.APP_NAME} · {config.APP_TAGLINE}</h1>
<p>Backend is running. The React dashboard build was not found.</p>
<p>Build it with <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>,
then reload — or use the API at <code>/api/state</code>.</p></div></body></html>"""


@app.get("/")
async def index():
    if config.FRONTEND_BUILD.exists() and (config.FRONTEND_BUILD / "index.html").exists():
        return FileResponse(str(config.FRONTEND_BUILD / "index.html"))
    return HTMLResponse(_PLACEHOLDER)


if (config.FRONTEND_BUILD / "assets").exists():
    # Serve built assets (JS/CSS) under the SPA. HTML index handled above.
    app.mount("/assets", StaticFiles(directory=str(config.FRONTEND_BUILD / "assets")), name="assets")


@app.get("/{path:path}")
async def spa_fallback(path: str):
    """Client-side routes (/login, /app/...) resolve to the SPA on a hard refresh.

    Registered last so every /api route and /ws keep precedence. Unknown API paths stay
    JSON 404s; nothing under /api or /assets ever falls through to the HTML document.
    """
    if path.startswith(("api/", "api", "assets/", "ws")):
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return await index()
