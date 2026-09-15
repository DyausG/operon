// Portal-level derivations over engine state: machines, incidents, maintenance, activity, analytics.
// Pure functions over the mirrored read model; nothing here fabricates a record.
import { isActive, ledgerEntries, ownerOf, phaseOf, phaseTitle, sortedAlerts, statusTone, viewOf, last } from "./selectors.js";
import { title, words } from "../lib/format.js";

export const asset = (state, id) => (state.fleet || []).find((a) => a.equipment_id === id) || null;
export const alertsFor = (state, id) => Object.values(state.alerts || {}).filter((a) => a.equipment_id === id);
export const alertByIncident = (state, incidentId) => Object.values(state.alerts || {}).find((a) => a.incident_id === incidentId) || null;

export function openedAt(alert) { const ev = viewOf(alert).events || []; return ev[0]?.created_at || null; }
export function updatedAt(alert) { const ev = viewOf(alert).events || []; return ev[ev.length - 1]?.created_at || null; }

/** Machines table rows. */
export function machineRows(state) {
  return (state.fleet || []).map((a) => {
    const alerts = alertsFor(state, a.equipment_id);
    const active = alerts.filter(isActive);
    const hist = state.histories?.[a.equipment_id] || [];
    const point = a.point || last(hist);
    return {
      id: a.equipment_id, name: a.name, cls: a.equipment_class, criticality: a.criticality, status: a.status,
      tone: statusTone(a.status), risk: a.failure_prob, health: a.health_score, mode: a.predicted_mode && a.predicted_mode !== "NONE" ? a.predicted_mode_label : null,
      statusReason: a.status_reason, statusSource: a.status_source, incidents: alerts.length, activeIncidents: active.length,
      activeAlert: active[0] || null, point, lastTick: point?.t ?? null, history: hist, asset: a,
    };
  });
}

/** Incidents table rows across every alert the engine has projected. */
export function incidentRows(state) {
  return sortedAlerts(state).map((a) => {
    const phase = phaseOf(a);
    const view = viewOf(a);
    return {
      id: a.incident_id || a.equipment_id, incidentId: a.incident_id, equipmentId: a.equipment_id,
      machine: a.equipment_name || asset(state, a.equipment_id)?.name || a.equipment_id, cls: a.equipment_class,
      criticality: a.criticality, phase, phaseLabel: phaseTitle(a, state), status: a.status, tone: statusTone(phase || a.status),
      active: isActive(a), owner: ownerOf(a, state), risk: a.failure_prob, mode: a.predicted_mode_label,
      openedAt: openedAt(a), updatedAt: updatedAt(a), revision: a.lifecycle?.revision, reason: a.lifecycle?.last_reason,
      events: (view.events || []).length, runs: (view.agent_runs || []).length, provenance: a.provenance || a.lifecycle?.provenance,
      alert: a, view,
    };
  });
}

/** Maintenance work items: interventions, requirements, work orders and receipts from the read models. */
export function maintenanceRows(state) {
  const rows = [];
  for (const a of Object.values(state.alerts || {})) {
    const view = viewOf(a);
    const machine = a.equipment_name || asset(state, a.equipment_id)?.name || a.equipment_id;
    const base = { equipmentId: a.equipment_id, machine, incidentId: a.incident_id, criticality: a.criticality, phase: phaseOf(a) };
    const item = view.intervention, binding = view.binding;
    if (item) {
      const validated = String(item.status || "").toUpperCase().includes("VALIDATED") || ["AWAITING_APPROVAL", "READY", "EXECUTING", "OBSERVING", "CLOSED"].includes(base.phase);
      rows.push({ ...base, id: item.id, kind: "intervention", task: item.summary || item.steps?.[0]?.parameters?.description || "Intervention", priority: item.priority || null,
        status: item.status || (validated ? "VALIDATED" : "DRAFT"), origin: validated ? "application" : "advisory", createdAt: item.created_at,
        windowStart: item.window_start, windowEnd: item.window_end, technician: binding?.technician_id, part: item.part_id || binding?.parts?.[0]?.part_id,
        cost: item.estimated_cost, downtime: item.estimated_downtime_minutes, artifactId: item.artifact_id || item.id });
    }
    for (const r of view.requirements || []) {
      rows.push({ ...base, id: r.id, kind: "approval", task: `Approval requirement for ${r.intervention_id || "intervention"}`, priority: null, status: base.phase === "AWAITING_APPROVAL" && a.lifecycle?.requirement_id === r.id ? "PENDING" : (view.approval_decisions || []).some((d) => d.requirement_id === r.id) ? "DECIDED" : "SUPERSEDED",
        origin: "application", createdAt: r.created_at, artifactId: r.artifact_id || r.id, technician: null, part: null });
    }
    for (const wo of view.work_orders || []) {
      rows.push({ ...base, id: wo.id, kind: "work_order", task: wo.summary || "Work order", priority: item?.priority || null, status: wo.status || "DISPATCHED", origin: "application",
        createdAt: wo.dispatched_at || wo.created_at, artifactId: wo.artifact_id || wo.id, technician: binding?.technician_id, part: binding?.parts?.[0]?.part_id, workPackage: wo.work_package_id });
    }
    for (const rc of view.execution_receipts || []) {
      rows.push({ ...base, id: rc.id, kind: "receipt", task: rc.performed_action || "Execution receipt", priority: null, status: rc.status || "RECORDED", origin: "trusted",
        createdAt: rc.completed_at || rc.started_at || rc.created_at, artifactId: rc.artifact_id || rc.id, technician: rc.technician_id, part: (rc.resources_consumed || [])[0]?.part_id });
    }
  }
  return rows.sort((x, y) => String(y.createdAt || "").localeCompare(String(x.createdAt || "")));
}

const STREAM_TITLES = {
  control: (e) => (e.running ? "Simulator resumed" : "Simulator paused"),
  reset: () => "Engine reset",
  demo: (e) => `Guided demo · ${words(e.status || "")}`,
  alert: (e) => `Phase → ${title(e.phase)}`,
  outcome: (e) => (e.result ? title(e.result) : "Outcome recorded"),
  resolved: (e) => "Intervention dispatched",
  rejected: (e) => "Plan rejected by operator",
  failure: (e) => "Unplanned failure",
  error: (e) => "Action refused",
};

/** Unified activity: authoritative/advisory ledger entries of every incident plus the stream log. */
export function activityRows(state, { equipmentId = null } = {}) {
  const rows = [];
  for (const a of Object.values(state.alerts || {})) {
    if (equipmentId && a.equipment_id !== equipmentId) continue;
    const machine = a.equipment_name || asset(state, a.equipment_id)?.name || a.equipment_id;
    for (const e of ledgerEntries(viewOf(a))) rows.push({ ...e, source: "ledger", equipmentId: a.equipment_id, machine, incidentId: a.incident_id, key: `${a.incident_id}:${e.id}` });
  }
  for (const e of state.eventLog || []) {
    if (equipmentId && e.id !== equipmentId) continue;
    if (e.kind === "alert" && e.incidentId) continue; // the ledger already carries phase changes for durable incidents
    const machine = e.id ? asset(state, e.id)?.name || e.id : null;
    rows.push({ id: `stream:${e.seq}`, key: `stream:${e.seq}`, source: "stream", lane: e.kind === "rejected" ? "human" : "application", title: (STREAM_TITLES[e.kind] || (() => title(e.kind)))(e),
      detail: e.reason || e.error || (e.id ? `${machine}` : ""), at: e.at, equipmentId: e.id || null, machine, incidentId: e.incidentId || null, artifactId: null, kind: "stream" });
  }
  rows.sort((x, y) => String(y.at || "").localeCompare(String(x.at || "")));
  return rows;
}

/** Analytics inputs computed from histories, alerts, runs and economics. */
export function analytics(state) {
  const fleet = state.fleet || [];
  const histories = state.histories || {};
  const ticks = new Set();
  for (const pts of Object.values(histories)) for (const p of pts) if (p.t != null) ticks.add(p.t);
  const axis = [...ticks].sort((a, b) => a - b);
  const byTick = (key) => axis.map((t) => {
    const vals = fleet.map((a) => (histories[a.equipment_id] || []).find((p) => p.t === t)?.[key]).filter((v) => v != null);
    return { t, mean: vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null, max: vals.length ? Math.max(...vals) : null, n: vals.length };
  });
  const riskSeries = fleet.map((a) => ({ id: a.equipment_id, name: a.name, tone: statusTone(a.status), points: (histories[a.equipment_id] || []).map((p) => ({ t: p.t, v: p.prob ?? null })) }));
  const healthSeries = fleet.map((a) => ({ id: a.equipment_id, name: a.name, tone: statusTone(a.status), points: (histories[a.equipment_id] || []).map((p) => ({ t: p.t, v: p.health ?? null })) }));
  const statusDist = ["CRITICAL", "WARNING", "HEALTHY"].map((s) => ({ key: s, label: title(s), tone: statusTone(s), n: fleet.filter((a) => a.status === s).length }));
  const otherStatus = fleet.filter((a) => !["CRITICAL", "WARNING", "HEALTHY"].includes(a.status)).length;
  if (otherStatus) statusDist.push({ key: "OTHER", label: "Other", tone: "normal", n: otherStatus });
  const alerts = Object.values(state.alerts || {});
  const phaseCounts = new Map();
  for (const a of alerts) { const p = phaseOf(a) || "UNKNOWN"; phaseCounts.set(p, (phaseCounts.get(p) || 0) + 1); }
  const phaseDist = [...phaseCounts.entries()].map(([p, n]) => ({ key: p, label: title(p), tone: statusTone(p), n }));
  const critDist = ["HIGH", "MEDIUM", "LOW"].map((c) => ({ key: c, label: title(c), n: fleet.filter((a) => a.criticality === c).length, incidents: alerts.filter((a) => a.criticality === c).length }));
  const modeCounts = new Map();
  for (const a of fleet) { if (a.predicted_mode && a.predicted_mode !== "NONE") modeCounts.set(a.predicted_mode_label, (modeCounts.get(a.predicted_mode_label) || 0) + 1); }
  const modeDist = [...modeCounts.entries()].map(([label, n]) => ({ key: label, label, n }));
  const runs = alerts.flatMap((a) => (viewOf(a).agent_runs || []).map((r) => ({ ...r, equipmentId: a.equipment_id })));
  const runCounts = new Map();
  for (const r of runs) { const k = r.disposition || r.status || "UNKNOWN"; runCounts.set(k, (runCounts.get(k) || 0) + 1); }
  const runDist = [...runCounts.entries()].map(([k, n]) => ({ key: k, label: title(k), tone: statusTone(k), n }));
  const verdicts = alerts.flatMap((a) => viewOf(a).verdicts || []);
  const outcomes = alerts.flatMap((a) => viewOf(a).outcomes || []);
  const receipts = alerts.flatMap((a) => viewOf(a).execution_receipts || []);
  return {
    axis, meanRisk: byTick("prob"), meanHealth: byTick("health"), riskSeries, healthSeries, statusDist, phaseDist, critDist, modeDist,
    runs, runDist, verdicts, outcomes, receipts, alerts, business: state.business || {},
    sampleCount: Object.values(histories).reduce((n, p) => n + p.length, 0),
  };
}
