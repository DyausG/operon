// Case situation (F4.1, layout D): what is true now, who must act, which F1.1 commands are valid,
// and the one-line lifecycle position. Pure derivations from the WebSocket alert: the backend stays
// the authority, and every command it refuses is shown with its reason. Preconditions mirror
// core/reliability/lifecycle.py (resume, cancel, escalate, renew_approval, return_to_planning,
// retry_execution) and server/main.py (/execute: exact intent, READY only).
import { STAGES, TERMINAL, stageOf } from "./status.js";

const byTime = (a, b) => String(a.created_at || "").localeCompare(String(b.created_at || ""));
const events = (rm, type) => (rm?.events || []).filter((e) => !type || e.event_type === type).slice().sort(byTime);
const lastOf = (list) => list[list.length - 1] || null;

/** The latest PHASE_CHANGED into `to` (journal, authoritative), or null. */
export function lastPhaseChange(rm, to) {
  return lastOf(events(rm, "PHASE_CHANGED").filter((e) => !to || e.payload?.to === to));
}

/** F1.1 analysis suspension (technical retry budget spent). Not a phase and never an escalation. */
export function suspensionOf(lifecycle) {
  const a = lifecycle?.analysis;
  if (!a || !a.suspended) return null;
  return { attempts: a.attempts ?? null, codes: a.codes || {}, lastCode: a.last_code || null, lastReason: a.last_reason || null, at: a.updated_at || null };
}

/** Approval state while AWAITING_APPROVAL. The projection carries a requirement only while it is
 *  PENDING, so a missing requirement with valid authority means the backend no longer treats it as
 *  pending (expired); invalid authority means newer evidence invalidated the promoted plan. */
export function approvalStateOf(alert, now = Date.now()) {
  const lc = alert?.lifecycle || {};
  if (lc.phase !== "AWAITING_APPROVAL") return { state: "none" };
  const reqs = (lc.read_model?.requirements || []).slice().sort(byTime);
  if (lc.authority_valid === false) return { state: "invalidated", reason: lc.authority_reason || null };
  const pending = lc.requirement_id ? reqs.find((r) => r.id === lc.requirement_id) || null : null;
  if (pending) {
    const t = Date.parse(pending.expires_at);
    return Number.isFinite(t) && t <= now ? { state: "expired", requirement: pending, basis: "clock" } : { state: "pending", requirement: pending };
  }
  const latest = lastOf(reqs.filter((r) => !lc.intervention_id || r.intervention_id === lc.intervention_id));
  return { state: "expired", requirement: latest, basis: "backend" };
}

/** The latest recorded rejection (F1.1: default return_to PLANNING). */
export function rejectionOf(rm) {
  const e = lastOf(events(rm, "APPROVAL_RECORDED").filter((x) => x.payload?.decision === "REJECT"));
  if (!e) return null;
  const p = e.payload || {};
  return { at: e.created_at, actorId: p.actor_id || null, actorKind: p.actor_kind || null, rationale: p.rationale || null, returnTo: p.return_to || null };
}

/** Why the case left the normal path, from the journal. */
export function exceptionCauseOf(rm, phase) {
  if (phase === "ESCALATED") {
    const e = lastPhaseChange(rm, "ESCALATED");
    return e ? { at: e.created_at, from: e.payload?.from || null, reason: e.payload?.reason || null } : null;
  }
  if (phase === "EXECUTION_FAILED") {
    const e = lastOf(events(rm, "EXECUTION_RECORDED").filter((x) => x.payload?.status && x.payload.status !== "CONFIRMED"));
    const receipt = lastOf((rm?.execution_receipts || []).filter((r) => r.status !== "CONFIRMED").slice().sort((a, b) => String(a.completed_at || a.created_at || "").localeCompare(String(b.completed_at || b.created_at || ""))));
    return { at: e?.created_at || null, status: e?.payload?.status || receipt?.status || null, reason: receipt?.error_message || null };
  }
  if (phase === "AWAITING_EVIDENCE") {
    const e = lastPhaseChange(rm, "AWAITING_EVIDENCE");
    return e ? { at: e.created_at, reason: e.payload?.reason || null } : null;
  }
  return null;
}

/** Cancellation record (INCIDENT_CANCELLED carries the actor and rationale). */
export function cancellationOf(rm) {
  const e = lastOf(events(rm, "INCIDENT_CANCELLED"));
  if (!e) return null;
  return { at: e.created_at, actor: e.payload?.actor || null, rationale: e.payload?.rationale || null };
}

/** Plain words for a backend actor kind; none of them is a verified identity in F1. */
export const ACTOR_KIND_WORDS = {
  SANDBOX: "sandbox identity, unauthenticated",
  DECLARED: "declared, not verified",
  SCENARIO: "scenario driver, simulated",
  SYSTEM: "system",
};

/** Can a person act on this case from this interface? The server still decides every command. */
export function actionGate({ environment, sessionRole, connected }) {
  if (environment === "PRODUCTION") return { allowed: false, reason: "Production refuses human actions until authenticated identity exists (F3). Nothing can be decided here." };
  if (sessionRole === "observer") return { allowed: false, reason: "Observer is a read-only role in this interface." };
  if (connected === false) return { allowed: true, inactive: "Reconnect to act on this case." };
  return {
    allowed: true,
    recordedAs: environment === "SANDBOX" ? "a sandbox identity (declared, unauthenticated)" : "a declared identity (not verified: G8)",
  };
}

const RESUME_LABEL = {
  suspended: { label: "Resume analysis", consequence: "Clears the suspension. The next analysis run starts with a fresh retry budget." },
  ESCALATED: { label: "Resume investigation", consequence: "Returns the case to Investigating. Automated analysis continues from the current evidence." },
  invalidated: { label: "Reinvestigate", consequence: "Withdraws the invalidated plan and returns the case to Investigating." },
  EXECUTION_FAILED: { label: "Abandon dispatch and reinvestigate", consequence: "Abandons the failed dispatch and returns the case to Investigating. Nothing is dispatched." },
};

/**
 * Commands a person may try now, in display order (one primary at most). Mirrors the backend
 * preconditions; `endpoint` is "command" (POST /commands/{command}) or "execute" (POST /execute).
 * A pending, valid approval offers no command: the decision surface is the act (reject returns to
 * planning). Escalate and cancel are always secondary.
 */
export function availableCommands(alert, { now = Date.now() } = {}) {
  const lc = alert?.lifecycle || {};
  const phase = lc.phase;
  if (!phase || TERMINAL.has(phase)) return [];
  const suspended = !!suspensionOf(lc);
  const approval = approvalStateOf(alert, now);
  const out = [];
  const add = (command, label, consequence, intent = "secondary", endpoint = "command") => out.push({ command, label, consequence, intent, endpoint });

  if (suspended) add("resume", RESUME_LABEL.suspended.label, RESUME_LABEL.suspended.consequence, "primary");
  else if (phase === "ESCALATED") add("resume", RESUME_LABEL.ESCALATED.label, RESUME_LABEL.ESCALATED.consequence, "primary");
  else if (approval.state === "invalidated") add("resume", RESUME_LABEL.invalidated.label, RESUME_LABEL.invalidated.consequence, "primary");

  if (phase === "EXECUTION_FAILED" && !lc.reconciliation_required) {
    add("retry_execution", "Retry dispatch", "Returns the approved work package to Ready. Dispatch then needs an explicit dispatch step.", "primary");
    add("resume", RESUME_LABEL.EXECUTION_FAILED.label, RESUME_LABEL.EXECUTION_FAILED.consequence);
  }
  if (approval.state === "expired" && lc.authority_valid !== false) {
    add("renew_approval", "Renew approval", "Issues a fresh approval requirement for the same exact work package. Governance is re-checked; an elapsed window refuses renewal.", "primary");
  }
  if (phase === "READY" && lc.authority_valid !== false && lc.intervention_id && lc.intervention_hash) {
    add("execute", "Dispatch approved work package", "Commits the approved work package through the work-order adapter now. This call records no actor in this build.", "primary", "execute");
  }
  if (phase === "READY" || (phase === "AWAITING_APPROVAL" && approval.state !== "pending")) {
    add("return_to_planning", "Return to planning", "Withdraws the current work package. A revised plan is drafted and reviewed; nothing is dispatched.");
  }
  if (phase !== "EXECUTING" && phase !== "ESCALATED") {
    add("escalate", "Escalate", "Escalates the case to a reliability engineer. Automated progress stops until someone resumes or cancels it.", "danger");
  }
  if (phase !== "EXECUTING") {
    add("cancel", "Cancel case", "Ends the case without further action and keeps its full record. The asset can open a new case.", "danger");
  }
  return out;
}

/** "Investigating · Awaiting inspection · stage 2 of 8", plus loop and exception context. */
export function stageLineOf(alert) {
  const lc = alert?.lifecycle || {};
  const rm = lc.read_model || {};
  const s = stageOf(lc.phase);
  if (!s) return { text: "Stage not reported", position: null, context: [] };
  const context = [];
  const inspections = events(rm, "PHASE_CHANGED").filter((e) => e.payload?.to === "AWAITING_EVIDENCE").length;
  if (inspections > 1) context.push(`inspection requested ${inspections}×`);
  const notRecovered = events(rm, "OUTCOME_RECORDED").filter((e) => e.payload?.result === "NOT_RECOVERED").length;
  if (notRecovered) context.push(`reinvestigating after not recovered${notRecovered > 1 ? ` (${notRecovered}×)` : ""}`);
  const rejections = events(rm, "APPROVAL_RECORDED").filter((e) => e.payload?.decision === "REJECT").length;
  if (rejections && lc.phase !== "AWAITING_APPROVAL") context.push(`returned to planning after rejection${rejections > 1 ? ` (${rejections}×)` : ""}`);
  if (s.exception) {
    const from = s.key === "ESCALATED" ? lastPhaseChange(rm, "ESCALATED")?.payload?.from : s.key === "DISPATCH_FAILED" ? "EXECUTING" : null;
    const fromStage = from ? stageOf(from) : null;
    return { text: `${s.label}${fromStage && !fromStage.exception ? ` · from ${fromStage.label}` : ""}`, position: fromStage?.n ?? null, exception: true, context };
  }
  if (s.key === "AWAITING_INSPECTION") return { text: `Investigating · Awaiting inspection · stage ${s.n} of 8`, position: s.n, context };
  return { text: `${s.label} · stage ${s.n} of 8`, position: s.n, context };
}

/** The case navigator (F0 §14 D): Now first, then content sections with their state. */
export const SECTIONS = [
  { id: "now", label: "Now" },
  { id: "evidence", label: "Evidence" },
  { id: "investigation", label: "Investigation" },
  { id: "decision", label: "Plan & decision" },
  { id: "work", label: "Work & verification" },
  { id: "record", label: "Record" },
];

const STAGE_N = (phase) => stageOf(phase)?.n ?? null;

/** Section states: "action" · "current" · "done" · "todo" (not started) · "info". */
export function sectionStates(alert, { openRequestCount = 0, requiresPerson = false } = {}) {
  const lc = alert?.lifecycle || {};
  const rm = lc.read_model || {};
  const phase = lc.phase;
  const n = STAGE_N(phase);
  const terminal = TERMINAL.has(phase);
  const runs = (rm.agent_runs || []).length;
  const receipts = (rm.execution_receipts || []).length;
  const states = {
    now: { state: requiresPerson ? "action" : terminal ? "info" : "current", meta: requiresPerson ? "action required" : terminal ? (phase === "CLOSED" ? "closed" : "cancelled") : "nothing required" },
    evidence: { state: phase === "AWAITING_EVIDENCE" ? "action" : (rm.evidence || []).length ? "info" : "todo", meta: `${(rm.evidence || []).length}${openRequestCount ? ` · ${openRequestCount} open` : ""}` },
    investigation: { state: !runs ? "todo" : rm.diagnosis?.status === "ACCEPTED" ? "done" : (n === 2 ? "current" : "info"), meta: runs ? `${runs} ${runs === 1 ? "run" : "runs"}` : "not started" },
    decision: { state: !rm.intervention ? "todo" : phase === "AWAITING_APPROVAL" ? "action" : (phase === "PLANNING" || phase === "INTERVENTION_VALIDATED") ? "current" : (rm.approval_decisions || []).some((d) => d.decision === "APPROVE") ? "done" : "info", meta: !rm.intervention ? "not started" : phase === "AWAITING_APPROVAL" ? "decision" : `plan R${rm.intervention.revision ?? "?"}` },
    work: { state: !receipts ? "todo" : (rm.outcomes || []).length ? "done" : (phase === "READY" || phase === "EXECUTING" || phase === "OBSERVING") ? "current" : "info", meta: receipts ? `${receipts} ${receipts === 1 ? "receipt" : "receipts"}` : "not started" },
    record: { state: "info", meta: `${(rm.events || []).length} events` },
  };
  return SECTIONS.map((s) => ({ ...s, ...states[s.id] }));
}

/** Where a legacy or V2 deep-link hash lands in the navigator. "#decision" opens Now while a
 *  decision is pending (the decision surface lives there), otherwise Plan & decision. */
export function sectionForHash(hash, { decisionPending = false } = {}) {
  const id = String(hash || "").replace(/^#/, "");
  if (!id) return "now";
  if (id === "decision" || id === "decision-surface") return decisionPending ? "now" : "decision";
  if (id === "summary") return "now";
  return SECTIONS.some((s) => s.id === id) ? id : "now";
}

export { STAGES };
