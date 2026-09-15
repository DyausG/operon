// Pure reducer over the engine's WebSocket stream. Holds no authority; mirrors the server.
export const HISTORY_CAP = 90;
export const EVENT_LOG_CAP = 240;

export const initialState = {
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
  eventLog: [],
  generation: 0,
  frames: 0,
};

/** Append a stream event to the client-side log (newest first). Only what the engine actually sent. */
function logged(prev, entry) {
  const seq = (prev.eventLog[0]?.seq || 0) + 1;
  const at = entry.at || new Date().toISOString();
  return [{ seq, at, ...entry }].concat(prev.eventLog).slice(0, EVENT_LOG_CAP);
}

export function applySnapshot(prev, s) {
  const demo = s.demo_scenario || { active: false };
  const alerts = Object.fromEntries((s.alerts || []).map((a) => [a.equipment_id, a]));
  // A scripted demo (re)start returns to a healthy plant with no alerts: a new generation of artifact ids.
  const restarted = demo.active && demo.status === "factory_healthy" && Object.keys(alerts).length === 0 &&
    !(prev.demoScenario.active && prev.demoScenario.status === "factory_healthy");
  const leftDemo = prev.demoScenario.active && !demo.active;
  // Observed transitions between consecutive snapshots: alert phase changes and demo milestones.
  let eventLog = prev.eventLog || [];
  const stamp = (entry) => { const seq = (eventLog[0]?.seq || 0) + 1; eventLog = [{ seq, at: new Date().toISOString(), ...entry }].concat(eventLog).slice(0, EVENT_LOG_CAP); };
  if (demo.active && demo.status && demo.status !== prev.demoScenario?.status) stamp({ kind: "demo", status: demo.status, phase: demo.phase, id: demo.equipment_id });
  if (!(restarted || leftDemo)) {
    for (const a of Object.values(alerts)) {
      const before = prev.alerts?.[a.equipment_id];
      const prevPhase = before ? (before.lifecycle?.phase || before.status || null) : null;
      const phase = a.lifecycle?.phase || a.status || null;
      if (phase && phase !== prevPhase) stamp({ kind: "alert", id: a.equipment_id, incidentId: a.incident_id, phase, from: prevPhase, reason: a.lifecycle?.last_reason || null });
    }
  }
  return {
    ...prev,
    connected: true,
    running: s.running ?? prev.running,
    tick: s.tick ?? 0,
    plantMin: s.plant_time_min ?? prev.plantMin,
    agentMode: s.agent_mode,
    meta: { appName: s.app_name, tagline: s.tagline, plant: s.plant_name },
    triggerThreshold: s.trigger_threshold ?? prev.triggerThreshold,
    warnThreshold: s.warn_threshold ?? prev.warnThreshold,
    fleet: s.fleet || [],
    histories: s.histories || {},
    alerts,
    triage: s.triage || prev.triage,
    business: s.business || {},
    reasoningProvenance: s.reasoning_provenance || {},
    action: { pending: null, error: null },
    demoScenario: demo,
    authorityPath: s.authority_path,
    supervisorAvailable: s.supervisor_available,
    generation: prev.generation + (restarted || leftDemo ? 1 : 0),
    frames: prev.frames + 1,
    eventLog,
  };
}

export function reduce(prev, msg) {
  switch (msg.type) {
    case "snapshot":
      return applySnapshot(prev, msg);
    case "control":
      return { ...prev, running: msg.running, eventLog: logged(prev, { kind: "control", running: msg.running }) };
    case "reset":
      return {
        ...prev, running: true, tick: 0, plantMin: 0, fleet: [], histories: {}, alerts: {},
        triage: { count: 0, rationale: "", order: [] }, business: {}, action: { pending: null, error: null },
        demoScenario: { active: false }, lastEvent: null, generation: prev.generation + 1,
        eventLog: logged(prev, { kind: "reset" }),
      };
    case "demo":
      return { ...prev, demoScenario: msg.demo_scenario || { active: false },
        eventLog: logged(prev, { kind: "demo", status: msg.demo_scenario?.status, phase: msg.demo_scenario?.phase, id: msg.demo_scenario?.equipment_id }) };
    case "tick": {
      const histories = { ...prev.histories };
      for (const a of msg.fleet || []) {
        if (!a.point) continue;
        histories[a.equipment_id] = (histories[a.equipment_id] || []).concat(a.point).slice(-HISTORY_CAP);
      }
      return { ...prev, tick: msg.tick, plantMin: msg.plant_time_min, agentMode: msg.agent_mode,
        fleet: msg.fleet || prev.fleet, histories, business: msg.business || prev.business, frames: prev.frames + 1 };
    }
    case "alert": {
      const a = msg.alert, prevPhase = prev.alerts[a.equipment_id]?.lifecycle?.phase || prev.alerts[a.equipment_id]?.status || null;
      const phase = a.lifecycle?.phase || a.status || msg.phase || null;
      const changed = prevPhase !== phase;
      return { ...prev, alerts: { ...prev.alerts, [a.equipment_id]: a }, triage: msg.triage || prev.triage,
        lastEvent: { kind: "alert", id: a.equipment_id, phase: msg.phase },
        eventLog: changed ? logged(prev, { kind: "alert", id: a.equipment_id, incidentId: a.incident_id, phase, from: prevPhase, reason: a.lifecycle?.last_reason || null }) : prev.eventLog };
    }
    case "outcome":
      return { ...prev, alerts: msg.alert ? { ...prev.alerts, [msg.alert.equipment_id]: msg.alert } : prev.alerts,
        lastEvent: { kind: "outcome", id: msg.equipment_id, phase: msg.phase },
        eventLog: logged(prev, { kind: "outcome", id: msg.equipment_id, incidentId: msg.alert?.incident_id, phase: msg.phase || msg.alert?.lifecycle?.phase, result: msg.alert?.lifecycle?.outcome_result || null }) };
    case "resolved": {
      const a = prev.alerts[msg.equipment_id];
      return { ...prev, alerts: a ? { ...prev.alerts, [msg.equipment_id]: { ...a, status: "APPROVED", result: msg.result } } : prev.alerts,
        business: msg.business || prev.business, triage: msg.triage || prev.triage, lastEvent: { kind: "resolved", id: msg.equipment_id },
        eventLog: logged(prev, { kind: "resolved", id: msg.equipment_id, incidentId: a?.incident_id, outcome: msg.result?.outcome || null }) };
    }
    case "rejected": {
      const a = prev.alerts[msg.equipment_id];
      return { ...prev, alerts: a ? { ...prev.alerts, [msg.equipment_id]: { ...a, status: "REJECTED" } } : prev.alerts,
        triage: msg.triage || prev.triage, lastEvent: { kind: "rejected", id: msg.equipment_id },
        eventLog: logged(prev, { kind: "rejected", id: msg.equipment_id, incidentId: a?.incident_id }) };
    }
    case "failure": {
      const a = prev.alerts[msg.equipment_id];
      return { ...prev, alerts: a ? { ...prev.alerts, [msg.equipment_id]: { ...a, status: "FAILED", result: msg.result } } : prev.alerts,
        business: msg.business || prev.business, lastEvent: { kind: "failure", id: msg.equipment_id },
        eventLog: logged(prev, { kind: "failure", id: msg.equipment_id, incidentId: a?.incident_id, loss: msg.result?.loss ?? null }) };
    }
    case "error":
      return { ...prev, action: { pending: null, error: msg.error }, lastEvent: { kind: "error", id: msg.equipment_id },
        eventLog: logged(prev, { kind: "error", id: msg.equipment_id, error: msg.error }) };
    default:
      return prev;
  }
}
