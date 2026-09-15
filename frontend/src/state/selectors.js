// Pure derivations over engine state. Nothing here grants or infers authority; it reads the read model.
import { title, words } from "../lib/format.js";

export const STEPS = [
  { key: "SENSE", label: "Sense" }, { key: "DETECT", label: "Detect" }, { key: "INVESTIGATE", label: "Investigate" },
  { key: "DIAGNOSE", label: "Diagnose" }, { key: "VALIDATE", label: "Validate" }, { key: "PLAN", label: "Plan" },
  { key: "APPROVE", label: "Approve" }, { key: "EXECUTE", label: "Execute" }, { key: "OBSERVE", label: "Observe" },
  { key: "VERIFY", label: "Verify" }, { key: "CLOSE", label: "Close" },
];
const STEP_INDEX = Object.fromEntries(STEPS.map((s, i) => [s.key, i]));
export const EXCEPTIONAL = new Set(["ESCALATED", "EXECUTION_FAILED", "CANCELLED"]);
export const TERMINAL = new Set(["CLOSED", "CANCELLED", "FAILED"]);

export const ROLE_NAMES = {
  supervisor: "Reliability Supervisor", diagnostic: "Diagnostic Specialist", engineering: "Engineering Specialist",
  operations: "Operations Specialist", critic: "Critic / Validator", planner: "Maintenance Planner", system: "Application Investigator",
};
export const roleName = (role) => ROLE_NAMES[role] || (role ? title(role) : "Specialist");
export const STAGE_LABEL = { DIAGNOSIS: "Diagnosis", INTERVENTION_REVIEW: "Intervention review" };

export function sortedAlerts(state) {
  return Object.values(state.alerts).sort((a, b) => (a.triage_rank || 99) - (b.triage_rank || 99));
}
export function phaseOf(alert) { return alert?.lifecycle?.phase || alert?.status || null; }
export function isActive(alert) { const p = phaseOf(alert); return p && !TERMINAL.has(p); }

/** Which asset the command view is about. */
export function focusAsset(state, selected) {
  const alerts = sortedAlerts(state);
  const active = alerts.filter(isActive);
  return selected || state.demoScenario?.equipment_id || active[0]?.equipment_id || alerts[0]?.equipment_id || state.fleet[0]?.equipment_id || null;
}
export function incidentFor(state, equipmentId) { return equipmentId ? state.alerts[equipmentId] || null : null; }
export function viewOf(incident) { return incident?.lifecycle?.read_model || {}; }

/** Map lifecycle + read model to the process-line step that is current. */
export function currentStep(incident, state) {
  const demo = state.demoScenario || {};
  if (!incident) {
    if (demo.active && (demo.phase === "FACTORY_DEGRADING" || demo.phase === "PREDICTIVE_RISK_RISING")) return { key: "DETECT", sub: demo.phase === "PREDICTIVE_RISK_RISING" ? "risk rising" : "degrading" };
    return { key: "SENSE", sub: null };
  }
  const phase = phaseOf(incident), view = viewOf(incident);
  switch (phase) {
    case "OPEN": return { key: "DETECT", sub: "incident" };
    case "INVESTIGATING": return view.diagnosis ? { key: "DIAGNOSE", sub: "diagnosis recorded" } : { key: "INVESTIGATE", sub: null };
    case "AWAITING_EVIDENCE":
      if (view.diagnosis) return { key: "DIAGNOSE", sub: "diagnosis recorded" };
      return hasInspection(view) ? { key: "INVESTIGATE", sub: "inspected" } : { key: "INVESTIGATE", sub: "blocked", blocked: true };
    case "DIAGNOSIS_VALIDATED": return { key: "VALIDATE", sub: "diagnosis" };
    case "PLANNING": return { key: "PLAN", sub: null };
    case "INTERVENTION_VALIDATED": return { key: "PLAN", sub: "validated" };
    case "AWAITING_APPROVAL": return { key: "APPROVE", sub: "hold point", hold: true };
    case "READY": return { key: "EXECUTE", sub: "ready" };
    case "EXECUTING": return { key: "EXECUTE", sub: null };
    case "OBSERVING": return (view.outcomes || []).length ? { key: "VERIFY", sub: "outcome recorded" } : { key: "OBSERVE", sub: null };
    case "CLOSED": return { key: "CLOSE", sub: null };
    default: return null; // exceptional
  }
}

export function hasInspection(view) {
  return (view.evidence || []).some((e) => e.kind === "inspection" || String(e.source_capability || "").includes("confirm_mechanism"));
}

/** Full process-line model: steps with state, plus an exceptional branch if any. */
export function processModel(incident, state) {
  const phase = phaseOf(incident);
  let cur = currentStep(incident, state);
  let branch = null;
  if (incident && EXCEPTIONAL.has(phase)) {
    const events = viewOf(incident).events || [];
    const departure = [...events].reverse().find((e) => e.event_type === "PHASE_CHANGED" && e.payload?.to === phase);
    const from = departure?.payload?.from;
    const pseudo = from ? { lifecycle: { phase: from, read_model: viewOf(incident) } } : null;
    cur = pseudo ? currentStep(pseudo, state) : { key: "DETECT" };
    branch = { key: phase, label: title(phase), reason: incident.lifecycle?.last_reason || departure?.payload?.reason };
  }
  const idx = cur ? STEP_INDEX[cur.key] : -1;
  const steps = STEPS.map((s, i) => ({
    ...s,
    state: branch ? (i <= idx ? "done" : "future") : i < idx ? "done" : i === idx ? "current" : "future",
    hold: s.key === "APPROVE" && !(i < idx) && !(phase === "CLOSED"),
    blocked: i === idx && !!cur?.blocked,
    sub: i === idx ? cur?.sub : null,
  }));
  return { steps, current: cur, branch, index: idx };
}

/** Who holds the next move. */
export function ownerOf(incident, state) {
  const phase = phaseOf(incident);
  if (!incident) return { kind: "application", label: "Application · monitoring" };
  switch (phase) {
    case "OPEN": case "INVESTIGATING": case "PLANNING": return { kind: "advisory", label: "AI advisory" };
    case "AWAITING_EVIDENCE": return hasInspection(viewOf(incident)) ? { kind: "application", label: "Application" } : { kind: "trusted", label: "Trusted input required" };
    case "AWAITING_APPROVAL": return { kind: "human", label: "Human · required" };
    case "CANCELLED": case "ESCALATED": case "EXECUTION_FAILED": return { kind: "application", label: "Application · " + words(phase) };
    default: return { kind: "application", label: "Application" };
  }
}

export const PHASE_TITLES = {
  OPEN: "Incident opened", INVESTIGATING: "Investigating", AWAITING_EVIDENCE: "Awaiting evidence",
  DIAGNOSIS_VALIDATED: "Diagnosis validated", PLANNING: "Planning intervention", INTERVENTION_VALIDATED: "Intervention validated",
  AWAITING_APPROVAL: "Awaiting approval", READY: "Approved · ready to execute", EXECUTING: "Executing", OBSERVING: "Observing recovery",
  CLOSED: "Closed", CANCELLED: "Cancelled", ESCALATED: "Escalated", EXECUTION_FAILED: "Execution failed",
};
export function phaseTitle(incident, state) {
  const p = phaseOf(incident);
  if (p) {
    if (p === "OBSERVING" && (viewOf(incident).outcomes || []).length) return "Recovery verified";
    return PHASE_TITLES[p] || title(p);
  }
  const d = state.demoScenario || {};
  if (d.active) return d.phase === "PREDICTIVE_RISK_RISING" ? "Predictive risk rising" : d.phase === "FACTORY_DEGRADING" ? "Signature degrading" : "Factory healthy";
  return state.running ? "Monitoring" : "Paused";
}

/** Index every compact read-model row that carries an artifact id. */
export function rowIndex(view) {
  const out = new Map();
  const walk = (v) => {
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") {
      if (v.artifact_id && v.id === v.artifact_id && !out.has(v.id)) out.set(v.id, v);
      else if (v.id && !v.artifact_id && typeof v.id === "string" && v.summary && !out.has(v.id)) out.set(v.id, v);
      Object.values(v).forEach(walk);
    }
  };
  walk(view);
  return out;
}

const EVENT_TITLES = {
  INCIDENT_OPENED: "Incident opened", EVIDENCE_ACQUIRED: "Evidence acquired", SPECIALIST_ACTIVITY_RECORDED: "Specialist activity recorded",
  DIAGNOSIS_CREATED: "Diagnosis recorded", DIAGNOSIS_VALIDATED: "Diagnosis validated", INTERVENTION_CREATED: "Intervention drafted",
  INTERVENTION_VALIDATED: "Intervention validated", APPROVAL_REQUESTED: "Approval requested", APPROVAL_RECORDED: "Approval recorded",
  WORK_ORDER_DISPATCHED: "Work order dispatched", EXECUTION_CONFIRMED: "Execution receipt confirmed",
  RECOVERY_OBSERVATION_RECORDED: "Recovery sample recorded", RECOVERY_VERIFIED: "Recovery verified", INCIDENT_CLOSED: "Incident closed",
  PHASE_CHANGED: "Phase changed", SIGNAL_RECORDED: "Signal recorded", ARTIFACT_ADDED: "Artifact added",
  EVIDENCE_REQUESTED: "Evidence requested", EVIDENCE_COLLECTED: "Evidence collected", EVIDENCE_REQUEST_RESOLVED: "Evidence request resolved",
  EVIDENCE_REQUEST_DEFERRED: "Evidence request deferred", SUPERVISOR_RUN_STARTED: "Supervisor run started", SUPERVISOR_RUN_COMPLETED: "Supervisor run completed",
};

/** Unified chronological record: authoritative events, trusted inputs, advisory specialist outputs. */
export function ledgerEntries(view) {
  const index = rowIndex(view);
  const entries = [];
  for (const ev of view.events || []) {
    const type = ev.event_type;
    const linked = ev.artifact_id && ev.artifact_id !== ev.id ? ev.artifact_id : (ev.represented_artifact_id || null);
    const row = linked ? index.get(linked) : null;
    let lane = "authority", titleText = EVENT_TITLES[type] || title(type), detail = ev.payload?.reason || row?.summary || ev.summary || "";
    if (type === "EVIDENCE_ACQUIRED") {
      const kind = ev.payload?.kind || row?.kind;
      titleText = `Evidence acquired · ${words(kind)}`;
      if (kind === "inspection") { lane = "trusted"; titleText = "Technician inspection received"; }
    } else if (type === "PHASE_CHANGED") {
      titleText = `Phase → ${title(ev.payload?.to)}`;
    } else if (type === "RECOVERY_OBSERVATION_RECORDED") {
      titleText = `Recovery sample ${ev.payload?.sequence ?? ""}`.trim();
    } else if (type === "SPECIALIST_ACTIVITY_RECORDED") {
      titleText = `Specialist activity recorded · ${words(ev.payload?.stage || row?.stage || "")}`.trim();
    } else if (type === "ARTIFACT_ADDED" && ev.payload?.kind) {
      titleText = `Artifact added · ${String(ev.payload.kind).replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase()}`;
      detail = detail || (ev.payload.boundary ? `boundary ${ev.payload.boundary}` : "");
    } else if (/^EVIDENCE_REQUEST/.test(type) || type === "EVIDENCE_COLLECTED") {
      const kind = ev.payload?.kind || ev.payload?.evidence_kind || ev.payload?.capability;
      if (kind) titleText = `${titleText} · ${words(kind)}`;
      detail = detail || ev.payload?.status || "";
    }
    if (!linked && ev.payload?.artifact_id && typeof ev.payload.artifact_id === "string") {
      // ARTIFACT_ADDED carries the artifact id in its payload; make the row inspectable.
      entries.push({ id: `ev:${ev.id}`, lane, title: titleText, detail, at: ev.created_at || "", revision: ev.revision,
        artifactId: ev.payload.artifact_id, eventType: type, row: row || ev, kind: "event" });
      continue;
    }
    entries.push({ id: `ev:${ev.id}`, lane, title: titleText, detail, at: ev.created_at || "", revision: ev.revision,
      artifactId: linked || ev.event_artifact_id || (typeof ev.id === "string" ? ev.id : null), eventType: type, row: row || ev, kind: "event" });
  }
  for (const run of view.agent_runs || []) {
    for (const d of run.delegations || []) {
      entries.push({ id: `adv:${run.run_id || run.id}:${d.key}`, lane: "advisory", title: `${roleName(d.role)} · ${STAGE_LABEL[run.stage] || words(run.stage)}`,
        detail: d.summary || d.short_conclusion || d.question || "", at: d.created_at || run.created_at || "", revision: null,
        artifactId: d.artifact_id || null, row: d, kind: "advisory", status: d.status });
    }
    for (const a of run.assessments || []) {
      if ((run.delegations || []).some((d) => d.key === a.key)) continue;
      entries.push({ id: `ass:${run.run_id}:${a.key}`, lane: "advisory", title: `${roleName(inferRole(a.assessment))} · ${STAGE_LABEL[run.stage] || words(run.stage)}`,
        detail: a.assessment?.reasoning_summary || "", at: run.created_at || "", revision: null, artifactId: null, row: a.assessment, kind: "advisory", status: "SUCCEEDED" });
    }
  }
  entries.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
  return entries.reverse();
}

export function inferRole(value = {}) {
  if ("competing_hypotheses" in value) return "diagnostic";
  if ("intervention_feasibility" in value) return "engineering";
  if ("resource_feasibility" in value) return "operations";
  if ("recommendation" in value) return "critic";
  if ("proposed_steps" in value) return "planner";
  return "agent";
}

export function verdictFor(view, kind) {
  return [...(view.verdicts || [])].reverse().find((v) => v.target_kind === kind) || null;
}
export function runFor(view, stage) {
  return [...(view.agent_runs || [])].reverse().find((r) => r.stage === stage) || null;
}
export const last = (arr) => (Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null);

export const SERIES = [
  { key: "vibration", label: "Vibration", unit: "mm/s", d: 1 },
  { key: "temp_diff", label: "Temp rise", unit: "°C", d: 1 },
  { key: "motor_current", label: "Current", unit: "A", d: 1 },
  { key: "torque", label: "Torque", unit: "N·m", d: 1 },
  { key: "rot_speed", label: "Speed", unit: "rpm", d: 0 },
  { key: "tool_wear", label: "Tool wear", unit: "min", d: 0 },
  { key: "health", label: "Health", unit: "score", d: 2 },
];
export function availableSeries(points) {
  return SERIES.filter((s) => points.some((p) => p[s.key] != null));
}

export function statusTone(value = "") {
  const v = String(value).toUpperCase();
  if (["CRITICAL", "ESCALATED", "EXECUTION_FAILED", "FAILED", "REJECT", "REJECTED", "REGRESSED", "NOT_RECOVERED", "ERROR", "CANCELLED", "DOWN"].includes(v)) return "crit";
  if (["WARNING", "AWAITING_APPROVAL", "AWAITING_EVIDENCE", "PENDING", "CONDITIONS", "NEEDS_EVIDENCE", "IMPROVING", "RUNNING", "STARTED", "CLAIMED"].includes(v)) return "warn";
  if (["VERIFIED_RECOVERY", "CLOSED", "RECOVERED", "HEALTHY"].includes(v)) return v === "HEALTHY" ? "normal" : "ok";
  if (["CONFIRMED", "ACCEPT", "APPROVE", "APPROVED", "SUCCEEDED", "READY", "VALIDATED", "VALIDATED_SIMULATED", "CONFIRMED_SIMULATED", "RESERVED_SIMULATED", "ASSIGNED_SIMULATED", "DISPATCHED_SIMULATED", "PREPARED", "RECORDED", "AVAILABLE", "ACTIVE", "SCHEDULED"].includes(v)) return "auth";
  return "normal";
}
