"""
Demo engine — the beating heart of the loop.

Owns the fleet simulation, the ML scoring, concurrent alert management + triage,
the agent trigger, and the governed write-back. UI-agnostic: it emits plain dict
events that any transport (the FastAPI WebSocket, a notebook, a test) can consume.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import logging

from . import config, agent, services
from .db import get_conn, reset_transactional
from .model import load_or_train
from .simulator import PlantSimulator
from .seed_data import CLASS_DEFAULT_MODE, SENSOR_FEATURES
from .tools import get_failure_mode_by_code, commit_actions, raise_alert

HISTORY_CAP = 90
logger = logging.getLogger(__name__)


def status_for(prob: float) -> str:
    if prob >= config.TRIGGER_THRESHOLD:
        return "CRITICAL"
    if prob >= config.WARN_THRESHOLD:
        return "WARNING"
    return "HEALTHY"


class DemoEngine:
    def __init__(self):
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
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        reset_transactional()
        self.sim = PlantSimulator()
        self.tick_i = 0
        self.assets = {}
        self.histories = {}
        self.alerts = {}
        self.status_override = {}
        self._analyzing = set()
        await self.broadcast({"type": "reset"})
        await self.start()

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
        now = datetime.now().isoformat(timespec="seconds")
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
            if (a["failure_prob"] >= config.TRIGGER_THRESHOLD and eid not in self.alerts
                    and eid not in self._analyzing and st.mode == "degrading"):
                await self._fire_agent(eid)

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
    def _build_ctx(self, eid: str) -> dict:
        a = self.assets[eid]
        mode_code = a["predicted_mode"]["mode"]
        fm = get_failure_mode_by_code(mode_code)
        if not fm:  # NONE / unknown -> fall back to the class's characteristic mode
            fallback_id = CLASS_DEFAULT_MODE.get(a["equipment_class"], "FM-OSF")
            fm = get_failure_mode_by_code(fallback_id.split("-")[1])
        drivers = self.model.attribute(a)
        return {"equipment_id": eid, "equipment_name": a["name"],
                "equipment_class": a["equipment_class"], "criticality": a["criticality"],
                "failure_mode": fm, "mode_prediction": a["predicted_mode"],
                "prediction": {"failure_prob": a["failure_prob"], "health_score": a["health_score"]},
                "drivers": drivers}

    async def _fire_agent(self, eid: str):
        self._analyzing.add(eid)
        self.sim.set_mode(eid, "arrested")
        self.status_override[eid] = "CRITICAL"
        ctx = self._build_ctx(eid)
        # Record a governed operational alert (foundation for the monitoring layer).
        # Best-effort: a notification-backend hiccup must never stall the loop.
        try:
            sev = "CRITICAL" if ctx["criticality"] == "HIGH" else "HIGH"
            raise_alert(eid, sev,
                        f"{ctx['failure_mode'].get('mode_code','?')} predicted on {eid} at "
                        f"{ctx['prediction']['failure_prob']:.0%} failure probability.", "agent")
        except Exception:
            logger.exception(
                "Operational alert persistence failed for %s; continuing the demo loop", eid
            )
        # announce the alert immediately (agent is "thinking")
        alert = {"equipment_id": eid, "equipment_name": ctx["equipment_name"],
                 "equipment_class": ctx["equipment_class"], "criticality": ctx["criticality"],
                 "failure_prob": round(ctx["prediction"]["failure_prob"], 3),
                 "predicted_mode": ctx["failure_mode"].get("mode_code"),
                 "predicted_mode_label": ctx["failure_mode"].get("failure_mode_name"),
                 "status": "ANALYZING", "created_tick": self.tick_i,
                 "triage_rank": None, "triage_score": agent.triage_score(ctx),
                 "proposal": None, "result": None}
        self.alerts[eid] = alert
        await self.broadcast({"type": "alert", "alert": alert, "phase": "analyzing"})

        proposal = await asyncio.to_thread(agent.decide, ctx)
        alert["proposal"] = proposal
        alert["status"] = "PENDING_APPROVAL"
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
    async def approve(self, eid: str) -> dict:
        al = self.alerts.get(eid)
        if not al or al["status"] != "PENDING_APPROVAL":
            return {"ok": False, "error": "no pending proposal for this asset"}
        wo = await asyncio.to_thread(commit_actions, al["proposal"])
        self.sim.set_mode(eid, "recovering")
        self.status_override[eid] = "SCHEDULED"
        b = al["proposal"]["business"]
        result = {"outcome": "PREVENTED", "wo_number": wo["wo_number"],
                  "package_number": wo.get("package_number"),
                  "recovered_value": b["recovered_value"],
                  "downtime_hours_avoided": b["downtime_hours_avoided"],
                  "oee_before": config.OEE_BASELINE,
                  "oee_after": min(config.OEE_TARGET, config.OEE_BASELINE + 0.031)}
        al["status"] = "APPROVED"
        al["result"] = result
        self._retriage()
        await self.broadcast({"type": "resolved", "equipment_id": eid, "result": result,
                              "business": self._business_summary(), "triage": self._triage_msg()})
        return {"ok": True, "result": result}

    async def reject(self, eid: str) -> dict:
        al = self.alerts.get(eid)
        if not al or al["status"] != "PENDING_APPROVAL":
            return {"ok": False, "error": "no pending proposal for this asset"}
        self.sim.set_mode(eid, "failing")
        self.status_override[eid] = "CRITICAL"
        al["status"] = "REJECTED"
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
        await self.broadcast({"type": "failure", "equipment_id": eid, "result": result,
                              "business": self._business_summary()})

    # -- aggregates + snapshot --------------------------------------------
    def _business_summary(self) -> dict:
        prevented = [a for a in self.alerts.values() if a["status"] == "APPROVED"]
        lost = [a for a in self.alerts.values() if a["status"] == "FAILED"]
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
                "tagline": config.APP_TAGLINE, "plant_name": config.PLANT_NAME,
                "trigger_threshold": config.TRIGGER_THRESHOLD, "warn_threshold": config.WARN_THRESHOLD,
                "fleet": [self._asset_summary(e) for e in self.meta if e in self.assets],
                "histories": self.histories,
                "alerts": list(self.alerts.values()),
                "triage": self._triage_msg(),
                "business": self._business_summary()}

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
