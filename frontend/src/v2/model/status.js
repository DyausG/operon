// Pure status derivations (07 §12–§13, 08 §1). No authority, no invented values: every output is
// computed from a backend field or is an explicit "not available" word.

/** The 8 user stages plus exceptions (07 §13.1). `n` is the position shown as "n/8". */
export const STAGES = [
  { key: "DETECTED", label: "Detected", n: 1, next: "Baseline evidence is collected automatically." },
  { key: "INVESTIGATING", label: "Investigating", n: 2, next: "A diagnosis is promoted, an inspection is requested, or the case escalates." },
  { key: "DIAGNOSED", label: "Diagnosed", n: 3, next: "Resources (technician, parts, window) are confirmed." },
  { key: "PLANNING", label: "Planning", n: 4, next: "The exact work package goes to a human decision." },
  { key: "AWAITING_DECISION", label: "Awaiting decision", n: 5, next: "Approve and dispatch, or reject, before the requirement expires." },
  { key: "IN_WORK", label: "In work", n: 6, next: "The work order is committed and observation begins." },
  { key: "VERIFYING", label: "Verifying", n: 7, next: "Verified closes the case; not recovered returns it to investigation." },
  { key: "CLOSED", label: "Closed", n: 8, next: "No further action." },
];

// F1.1 made the exits callable (resume, cancel, retry_execution); the copy says what a person can do.
export const EXCEPTIONS = {
  ESCALATED: { key: "ESCALATED", label: "Escalated", next: "A person resumes the investigation or cancels the case." },
  DISPATCH_FAILED: { key: "DISPATCH_FAILED", label: "Dispatch failed", next: "Once the dispatch outcome is definitive: retry the dispatch, reinvestigate or cancel." },
  CANCELLED: { key: "CANCELLED", label: "Cancelled", next: "No further action. The asset can open a new case." },
};

const AWAITING_INSPECTION = { key: "AWAITING_INSPECTION", label: "Awaiting inspection", n: 2, loop: true,
  next: "A technician inspects the asset and records the result; then investigation resumes." };

/** Internal lifecycle phase (14 values) → user stage. */
export const PHASE_STAGE = {
  OPEN: "DETECTED",
  INVESTIGATING: "INVESTIGATING",
  AWAITING_EVIDENCE: "AWAITING_INSPECTION",
  DIAGNOSIS_VALIDATED: "DIAGNOSED",
  PLANNING: "PLANNING",
  INTERVENTION_VALIDATED: "PLANNING",
  AWAITING_APPROVAL: "AWAITING_DECISION",
  READY: "IN_WORK",
  EXECUTING: "IN_WORK",
  OBSERVING: "VERIFYING",
  CLOSED: "CLOSED",
  ESCALATED: "ESCALATED",
  EXECUTION_FAILED: "DISPATCH_FAILED",
  CANCELLED: "CANCELLED",
};

export function stageOf(phase) {
  const key = PHASE_STAGE[phase];
  if (!key) return null;
  if (key === "AWAITING_INSPECTION") return AWAITING_INSPECTION;
  if (EXCEPTIONS[key]) return { ...EXCEPTIONS[key], exception: true };
  return STAGES.find((s) => s.key === key);
}

/** "Awaiting decision · 5/8" (word plus position; exceptions carry no position). */
export function stageCompact(phase) {
  const s = stageOf(phase);
  if (!s) return "Stage not reported";
  return s.n ? `${s.label} · ${s.n}/8` : s.label;
}

/** Waiting-on roles (07 §12.2). `human` roles take the decision cue. "Maintenance planner" extends
 *  the 07 vocabulary (F0 #19): resource confirmation and the work-package draft are planning inputs,
 *  not an approval. No declarable session role maps to it yet, so it is never "mine". */
export const ROLES = {
  analysis: { key: "analysis", label: "Analysis (automated)", short: "Analysis", human: false },
  technician: { key: "technician", label: "Technician", short: "Technician", human: true },
  planner: { key: "planner", label: "Maintenance planner", short: "Planner", human: true },
  approver: { key: "approver", label: "Approver", short: "Approver", human: true, sessionRole: "maintenance_approver" },
  reliability_engineer: { key: "reliability_engineer", label: "Reliability engineer", short: "Reliability engineer", human: true, sessionRole: "reliability_engineer" },
  dispatch: { key: "dispatch", label: "Dispatch (system)", short: "Dispatch", human: false },
  verification: { key: "verification", label: "Verification (system)", short: "Verification", human: false },
  none: { key: "none", label: "No one", short: "No one", human: false },
};

// READY persists only when nothing dispatches it (after a restart or an explicit retry): dispatch is
// an explicit act then (`POST /execute`, never automatic), so a person is the blocker (F0 #19).
const PHASE_WAITING = {
  OPEN: "analysis", INVESTIGATING: "analysis", AWAITING_EVIDENCE: "technician",
  DIAGNOSIS_VALIDATED: "planner", PLANNING: "analysis", INTERVENTION_VALIDATED: "analysis",
  AWAITING_APPROVAL: "approver", READY: "approver", EXECUTING: "dispatch", OBSERVING: "verification",
  CLOSED: "none", ESCALATED: "reliability_engineer", EXECUTION_FAILED: "approver", CANCELLED: "none",
};

export const TERMINAL = new Set(["CLOSED", "CANCELLED"]);

/** What a declarable role's queue holds (My actions), from PHASE_WAITING and waitingOn above. */
export const ROLE_QUEUE = {
  approver: "approval decisions, expired or invalidated approvals, approved work awaiting dispatch and dispatch failures",
  reliability_engineer: "escalations and suspended analysis",
};

/** Who the case waits on. `suspended` (F1.1 analysis suspension) needs a person to resume it. */
export function waitingOn(phase, { suspended = false } = {}) {
  if (suspended && !TERMINAL.has(phase)) return ROLES.reliability_engineer;
  return ROLES[PHASE_WAITING[phase]] || null;
}

/** Required response for human-blocked states (08 screen 3 response types). `gap` only where the
 *  interface still can't do it (G1: inspection and resource inputs are sandbox-only, no UI yet). */
const RESPONSES = {
  AWAITING_APPROVAL: { verb: "Approve work package", gap: null, section: "now" },
  AWAITING_EVIDENCE: { verb: "Inspect asset", gap: "G1", section: "now" },
  DIAGNOSIS_VALIDATED: { verb: "Confirm resources", gap: "G1", section: "now" },
  READY: { verb: "Dispatch approved work package", gap: null, section: "now" },
  ESCALATED: { verb: "Resolve escalation", gap: null, section: "now" },
  EXECUTION_FAILED: { verb: "Resolve dispatch failure", gap: null, section: "now" },
};

export function responseFor(phase, { expired = false, invalidated = false, suspended = false } = {}) {
  if (TERMINAL.has(phase)) return null;
  if (suspended) return { verb: "Resume suspended analysis", gap: null, section: "now" };
  if (phase === "AWAITING_APPROVAL" && invalidated) return { verb: "Review invalidated plan", gap: null, section: "now" };
  if (phase === "AWAITING_APPROVAL" && expired) return { verb: "Renew or withdraw expired approval", gap: null, section: "now" };
  return RESPONSES[phase] || null;
}

/** Asset condition from the model risk score only, never from case existence (07 §12.4 rule 1). */
export function conditionOf(failureProb, { warn, trigger }) {
  if (!Number.isFinite(failureProb) || !Number.isFinite(warn) || !Number.isFinite(trigger)) return "unknown";
  if (failureProb >= trigger) return "critical";
  if (failureProb >= warn) return "elevated";
  return "normal";
}

export const CONDITION_LABEL = { normal: "Normal", elevated: "Elevated", critical: "Critical", unknown: "No data", stale: "Stale" };
export const CONDITION_RANK = { critical: 4, stale: 3, unknown: 3, elevated: 2, normal: 1 };

/** Attention (07 §12.5). `ctx.analysisPaused` means reasoning is unavailable for this case. */
export function attentionOf({ phase, condition, expired = false, invalidated = false, suspended = false, outcomeResult = null, analysisPaused = false }) {
  if (phase && responseFor(phase, { expired, invalidated, suspended })) return "action";
  if (outcomeResult === "REGRESSED") return "risk";
  const role = waitingOn(phase);
  if (phase && role && !role.human && role.key !== "none") {
    if (analysisPaused && role.key === "analysis") return "risk";
    if (condition === "critical") return "risk";
  }
  if (phase === "OBSERVING") return "watch";
  if (!phase && condition === "elevated") return "watch";
  if (phase === "CLOSED") return "info";
  return phase ? "info" : null;
}

export const ATTENTION = {
  action: { key: "action", label: "Action required", rank: 3 },
  risk: { key: "risk", label: "At risk", rank: 2 },
  watch: { key: "watch", label: "Watch", rank: 1 },
  info: { key: "info", label: "Info", rank: 0 },
};

export const SEVERITY_LEVEL = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };

/** Approval expiry (08 §7): browser clock against the server's absolute expires_at. */
export function expiryOf(expiresAt, nowMs, status = null) {
  if (status === "EXPIRED") return { state: "expired", remainingMs: 0 };
  const t = expiresAt ? Date.parse(expiresAt) : NaN;
  if (!Number.isFinite(t)) return { state: "unknown", remainingMs: null };
  const remainingMs = t - nowMs;
  if (remainingMs <= 0) return { state: "expired", remainingMs: 0 };
  if (remainingMs <= 5 * 60000) return { state: "final", remainingMs };
  if (remainingMs <= 60 * 60000) return { state: "approaching", remainingMs };
  return { state: "normal", remainingMs };
}

/** Worst-member aggregate (07 §12.4 rule 5). */
export function aggregateConditions(conditions) {
  const counts = {};
  for (const c of conditions) counts[c] = (counts[c] || 0) + 1;
  const worst = conditions.slice().sort((a, b) => (CONDITION_RANK[b] || 0) - (CONDITION_RANK[a] || 0))[0] || null;
  return { worst, counts };
}

/** Evidence provenance → the five UI classes (07 §14 mapping decision). */
export function provenanceOf(evidence) {
  if (!evidence) return "derived";
  if (evidence.provenance === "SIMULATED") return "simulated";
  if (evidence.kind === "model_signal" || evidence.kind === "health_score") return "model";
  if (evidence.provenance === "OBSERVED") return "measured";
  if (evidence.provenance === "HUMAN" || evidence.provenance === "HUMAN_ENTERED") return "human";
  return "derived";
}

export const PROVENANCE_LABEL = {
  measured: "Measured", derived: "Derived", model: "Model-generated", human: "Human-entered", simulated: "Simulated",
};

/** Keys never rendered anywhere in V2 (product-owner correction A; 07 §18.6). */
export const FORBIDDEN_KEYS = ["confidence", "calibrated"];

export function withoutConfidence(value) {
  if (Array.isArray(value)) return value.map(withoutConfidence);
  if (value && typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) if (!FORBIDDEN_KEYS.includes(k)) out[k] = withoutConfidence(v);
    return out;
  }
  return value;
}

/** Outcome results as persisted by the backend (OutcomeResult literal). */
export const OUTCOME = {
  VERIFIED_RECOVERY: { label: "Verified recovery", shape: "verified" },
  NOT_RECOVERED: { label: "Not recovered", shape: "notRecovered" },
  REGRESSED: { label: "Regressed", shape: "critical" },
  INCONCLUSIVE: { label: "Inconclusive", shape: "inconclusive" },
};
