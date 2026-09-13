import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Live connection to the Operon engine.
 *
 * Holds one WebSocket, folds the server's event stream into a single `state`
 * object (fleet, per-asset history, alerts, triage, business), and exposes the
 * human-in-the-loop actions (approve / reject / reset).
 */
const HISTORY_CAP = 90;

function wsURL() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

export function useEngine() {
  const [state, setState] = useState({
    connected: false,
    running: true,
    tick: 0,
    plantMin: 0,
    agentMode: "deterministic",
    meta: { appName: "Operon", tagline: "Autonomous Reliability Operations for Industrial Systems", plant: "" },
    triggerThreshold: 0.8,
    warnThreshold: 0.45,
    fleet: [],
    histories: {},
    alerts: {},
    triage: { count: 0, rationale: "", order: [] },
    business: {},
    reasoningProvenance: {},
    action: { pending: null, error: null },
    demoScenario: { active: false },
    lastEvent: null,
  });
  const wsRef = useRef(null);

  const applySnapshot = useCallback((s) => {
    setState((prev) => ({
      ...prev,
      connected: true,
      running: s.running ?? prev.running,
      tick: s.tick,
      agentMode: s.agent_mode,
      meta: { appName: s.app_name, tagline: s.tagline, plant: s.plant_name },
      triggerThreshold: s.trigger_threshold,
      warnThreshold: s.warn_threshold,
      fleet: s.fleet,
      histories: s.histories || {},
      alerts: Object.fromEntries((s.alerts || []).map((a) => [a.equipment_id, a])),
      triage: s.triage || prev.triage,
      business: s.business || {},
      reasoningProvenance: s.reasoning_provenance || {},
      action: { pending: null, error: null },
      demoScenario: s.demo_scenario || { active: false },
    }));
  }, []);

  useEffect(() => {
    let stop = false;
    let ws;
    const connect = () => {
      ws = new WebSocket(wsURL());
      wsRef.current = ws;
      ws.onopen = () => setState((p) => ({ ...p, connected: true }));
      ws.onclose = () => {
        setState((p) => ({ ...p, connected: false }));
        if (!stop) setTimeout(connect, 1200);
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "snapshot") return applySnapshot(msg);
        setState((prev) => reduce(prev, msg));
      };
    };
    connect();
    return () => {
      stop = true;
      if (ws) ws.close();
    };
  }, [applySnapshot]);

  const post = useCallback(async (path, body) => {
    setState((p) => ({ ...p, action: { pending: path, error: null } }));
    try {
      const response = await fetch(path, {
        method: "POST",
        ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      });
      const result = await response.json();
      setState((p) => ({ ...p, action: { pending: null, error: result.ok === false ? result.error : null } }));
      return result;
    } catch (error) {
      setState((p) => ({ ...p, action: { pending: null, error: error.message } }));
      return { ok: false, error: error.message };
    }
  }, []);
  // Approval intent must name the exact requirement/intervention/hash/revision the
  // operator saw; the server rejects stale or equipment-only intent.
  const intent = (a) => a?.lifecycle?.requirement_id ? {
    requirement_id: a.lifecycle.requirement_id,
    intervention_id: a.lifecycle.intervention_id,
    intervention_hash: a.lifecycle.intervention_hash,
    context_revision: a.lifecycle.context_revision,
  } : undefined;
  const approve = useCallback((a) => post(`/api/approve/${a?.equipment_id ?? a}`, intent(a)), [post]);
  const reject = useCallback((a) => post(`/api/reject/${a?.equipment_id ?? a}`, intent(a)), [post]);
  const reset = useCallback(() => post("/api/reset"), [post]);
  const stop = useCallback(() => post("/api/stop"), [post]);
  const resume = useCallback(() => post("/api/start"), [post]);
  const startDemo = useCallback((equipmentId) => post("/api/demo/scenario", { equipment_id: equipmentId }), [post]);

  return { state, approve, reject, reset, stop, resume, startDemo };
}

function reduce(prev, msg) {
  switch (msg.type) {
    case "control":
      return { ...prev, running: msg.running };
    case "reset":
      return {
        ...prev, running: true, tick: 0, plantMin: 0, fleet: [], histories: {}, alerts: {},
        triage: { count: 0, rationale: "", order: [] }, business: {}, action: { pending: null, error: null },
        demoScenario: { active: false }, lastEvent: null,
      };
    case "demo":
      return { ...prev, demoScenario: msg.demo_scenario || { active: false } };
    case "tick": {
      const histories = { ...prev.histories };
      for (const a of msg.fleet) {
        if (!a.point) continue;
        const arr = (histories[a.equipment_id] || []).concat(a.point);
        histories[a.equipment_id] = arr.slice(-HISTORY_CAP);
      }
      return {
        ...prev, tick: msg.tick, plantMin: msg.plant_time_min, agentMode: msg.agent_mode,
        fleet: msg.fleet, histories, business: msg.business || prev.business,
      };
    }
    case "alert": {
      const alerts = { ...prev.alerts, [msg.alert.equipment_id]: msg.alert };
      return { ...prev, alerts, triage: msg.triage || prev.triage,
               lastEvent: { kind: "alert", id: msg.alert.equipment_id, phase: msg.phase } };
    }
    case "outcome": {
      const alerts = msg.alert
        ? { ...prev.alerts, [msg.alert.equipment_id]: msg.alert }
        : prev.alerts;
      return { ...prev, alerts, lastEvent: { kind: "outcome", id: msg.equipment_id, phase: msg.phase } };
    }
    case "resolved": {
      const a = prev.alerts[msg.equipment_id];
      const alerts = a ? { ...prev.alerts, [msg.equipment_id]: { ...a, status: "APPROVED", result: msg.result } } : prev.alerts;
      return { ...prev, alerts, business: msg.business || prev.business, triage: msg.triage || prev.triage,
               lastEvent: { kind: "resolved", id: msg.equipment_id } };
    }
    case "rejected": {
      const a = prev.alerts[msg.equipment_id];
      const alerts = a ? { ...prev.alerts, [msg.equipment_id]: { ...a, status: "REJECTED" } } : prev.alerts;
      return { ...prev, alerts, triage: msg.triage || prev.triage,
               lastEvent: { kind: "rejected", id: msg.equipment_id } };
    }
    case "failure": {
      const a = prev.alerts[msg.equipment_id];
      const alerts = a ? { ...prev.alerts, [msg.equipment_id]: { ...a, status: "FAILED", result: msg.result } } : prev.alerts;
      return { ...prev, alerts, business: msg.business || prev.business,
               lastEvent: { kind: "failure", id: msg.equipment_id } };
    }
    case "error":
      return { ...prev, action: { pending: null, error: msg.error },
               lastEvent: { kind: "error", id: msg.equipment_id } };
    default:
      return prev;
  }
}
