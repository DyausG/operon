// Case view derived from the engine's WebSocket projection (one alert per asset, G5).
// `alerts[].lifecycle.read_model` already carries the incident record, requirements, evidence,
// hypotheses, verdicts, runs and the last 80 events, so the workspace renders without a fetch.
import { attentionOf, conditionOf, expiryOf, responseFor, stageOf, waitingOn } from "./status.js";
import { dayClock, score } from "./format.js";

export function pendingRequirement(alert) {
  const lc = alert?.lifecycle || {};
  const reqs = lc.read_model?.requirements || [];
  if (!lc.requirement_id) return null;
  return reqs.find((r) => r.id === lc.requirement_id) || null;
}

/** Interim case reference (G6): asset tag + opened time. UUID lives in Identifiers. */
export function caseRef(alert) {
  const opened = alert?.lifecycle?.read_model?.incident?.created_at;
  return opened ? `${alert.equipment_id} · ${dayClock(opened)}` : alert?.equipment_id || "Case";
}

export function deriveCase(alert, { fleetById = {}, warn, trigger, now = Date.now(), demoIncidentId = null, analysisPaused = false } = {}) {
  if (!alert) return null;
  const lc = alert.lifecycle || {};
  const rm = lc.read_model || {};
  const phase = lc.phase || null;
  const asset = fleetById[alert.equipment_id] || {};
  const failureProb = Number.isFinite(asset.failure_prob) ? asset.failure_prob : null;
  const condition = conditionOf(failureProb, { warn, trigger });
  const requirement = pendingRequirement(alert);
  const expiry = requirement ? expiryOf(requirement.expires_at, now, requirement.status) : null;
  const expired = expiry?.state === "expired";
  const demo = !!demoIncidentId && demoIncidentId === alert.incident_id;
  return {
    alert,
    incidentId: alert.incident_id,
    assetId: alert.equipment_id,
    assetName: alert.equipment_name || asset.name || null,
    assetClass: alert.equipment_class || asset.equipment_class || null,
    criticality: alert.criticality || asset.criticality || null,
    phase,
    stage: stageOf(phase),
    waiting: waitingOn(phase),
    response: responseFor(phase, { expired }),
    attention: attentionOf({ phase, condition, expired, outcomeResult: lc.outcome_result, analysisPaused: analysisPaused && !demo }),
    analysisPaused: analysisPaused && !demo,
    condition,
    failureProb,
    severity: rm.incident?.severity || null,
    openedAt: rm.incident?.created_at || null,
    updatedAt: rm.incident?.updated_at || null,
    ref: caseRef(alert),
    requirement,
    expiry,
    revision: lc.context_revision ?? lc.revision ?? null,
    outcomeResult: lc.outcome_result || null,
    lastReason: lc.last_reason || null,
    demo,
    rm,
  };
}

/** Sort: attention → deadline ascending (only expires_at) → severity → age (08 screen 3). */
export function compareCases(a, b) {
  const rank = { action: 3, risk: 2, watch: 1, info: 0 };
  const ra = rank[a.attention] ?? -1, rb = rank[b.attention] ?? -1;
  if (ra !== rb) return rb - ra;
  const da = a.requirement?.expires_at ? Date.parse(a.requirement.expires_at) : Infinity;
  const db = b.requirement?.expires_at ? Date.parse(b.requirement.expires_at) : Infinity;
  if (da !== db) return da - db;
  const sev = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };
  const sa = sev[a.severity] || sev[a.criticality] || 0, sb = sev[b.severity] || sev[b.criticality] || 0;
  if (sa !== sb) return sb - sa;
  return String(a.openedAt || "").localeCompare(String(b.openedAt || ""));
}

/** One-line reason from backend facts only (07 §12.5 item 3). */
export function reasonLine(c, { trigger }) {
  const parts = [];
  if (c.attention === "risk" && c.analysisPaused && c.waiting?.key === "analysis") parts.push("Analysis paused: no model provider configured");
  if (Number.isFinite(c.failureProb)) {
    parts.push(`Risk score ${score(c.failureProb)}${Number.isFinite(trigger) && c.failureProb >= trigger ? ` ≥ gate ${score(trigger)}` : ""}`);
  }
  const dx = c.rm?.diagnosis;
  if (dx?.status === "ACCEPTED" && dx.failure_mode_code) parts.push(`diagnosis accepted (${dx.failure_mode_code})`);
  else if (c.alert?.predicted_mode_label) parts.push(`predicted ${c.alert.predicted_mode_label.toLowerCase()} (model output)`);
  if (c.response?.gap) parts.push(`${c.response.gap === "G1" ? "submission from this UI not available" : "resolution not available"} (${c.response.gap})`);
  return parts.join(" · ");
}

/** The latest analysis run of a stage (agent_runs are appended in order). */
export function latestRun(rm, stage) {
  const runs = (rm?.agent_runs || []).filter((r) => !stage || r.stage === stage);
  return runs[runs.length - 1] || null;
}

export function assessment(run, key) {
  return (run?.assessments || []).find((a) => a.key === key)?.assessment || null;
}

/** Open requests: from the latest diagnosis run while the case waits for evidence (X6 fallback). */
export function openRequests(c) {
  if (c?.phase !== "AWAITING_EVIDENCE") return [];
  const run = latestRun(c.rm, "DIAGNOSIS");
  const dx = assessment(run, "diagnostic");
  const since = (c.rm?.events || []).filter((e) => e.event_type === "PHASE_CHANGED" && e.payload?.to === "AWAITING_EVIDENCE").pop()?.created_at || null;
  return (dx?.missing_evidence_requests || []).map((r, i) => ({
    id: `${run?.run_id || "run"}-${i}`, question: r.question, capability: r.capability,
    requestedBy: "Diagnostic review", runId: run?.run_id || null, since,
  }));
}

/** Evidence ids that contradict the current diagnosis (via hypotheses' contradicting ids). */
export function contradictingEvidence(rm) {
  const dx = rm?.diagnosis;
  const ids = new Set();
  for (const h of rm?.hypotheses || []) {
    if (dx && !(dx.hypothesis_ids || []).includes(h.id)) continue;
    if (h.status === "REFUTED") continue;
    if (dx && h.mechanism !== dx.conclusion) continue;
    for (const id of h.contradicting_evidence_ids || []) ids.add(id);
  }
  return [...ids];
}

/** Unresolved critic challenges in the latest runs (contradictions, gaps, unsupported claims). */
export function criticChallenges(rm) {
  const out = [];
  for (const stage of ["DIAGNOSIS", "INTERVENTION_REVIEW"]) {
    const critic = assessment(latestRun(rm, stage), "critic");
    if (!critic) continue;
    for (const k of ["contradictions", "evidence_gaps", "unsupported_claims"]) for (const t of critic[k] || []) out.push({ stage, kind: k, text: typeof t === "string" ? t : JSON.stringify(t) });
  }
  return out;
}
