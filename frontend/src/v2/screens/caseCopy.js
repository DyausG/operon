// Copy derived from backend facts (07 §19). Plain language; no invented values.
import { stageOf, PHASE_STAGE } from "../model/status.js";
import { ACTOR_KIND_WORDS } from "../model/lifecycle.js";

const STAGE_WORD = (phase) => stageOf(phase)?.label || phase;

const COMMAND_WORD = {
  resume: "Resumed", cancel: "Cancelled", escalate: "Escalated", renew_approval: "Approval renewed",
  return_to_planning: "Returned to planning", retry_execution: "Dispatch retry requested",
};

const RETURN_TO_WORD = { PLANNING: "returned to planning", INVESTIGATING: "returned to investigation", ESCALATED: "escalated" };

/** "fixture-operator (declared, not verified)" from an ActorRef.public() payload. */
export function actorWords(actor) {
  if (!actor) return "an unrecorded actor";
  const kind = ACTOR_KIND_WORDS[actor.kind] || "kind not recorded";
  return `${actor.id || "unrecorded"} (${kind})`;
}

/** Case record event → plain-language line (08 §8). Stream noise (ARTIFACT_ADDED) is kept typed. */
export function eventCopy(e) {
  if (!e) return null;
  const p = e.payload || {};
  const base = { id: e.id, at: e.created_at, revision: e.revision, type: e.event_type, authoritative: true };
  switch (e.event_type) {
    case "INCIDENT_OPENED": return { ...base, text: "Case opened" };
    case "SIGNAL_RECORDED": return { ...base, text: "Model signal recorded" };
    case "EVIDENCE_REQUESTED": return { ...base, text: `Evidence requested · ${p.capability || "capability not recorded"}`, authoritative: false, group: "evidence" };
    case "EVIDENCE_COLLECTED": return { ...base, text: `Evidence collected · ${p.capability || ""}`.trim(), group: "evidence" };
    case "EVIDENCE_REQUEST_RESOLVED": return { ...base, text: `Evidence request resolved · ${p.capability || ""}`.trim(), group: "evidence" };
    case "PHASE_CHANGED": {
      const from = STAGE_WORD(p.from), to = STAGE_WORD(p.to);
      return { ...base, text: from === to ? `Stage: ${to} (${p.from} → ${p.to})` : `Stage: ${from} → ${to}`, reason: p.reason, phase: true };
    }
    case "APPROVAL_REQUESTED": return { ...base, text: "Approval requested" };
    case "APPROVAL_RECORDED": {
      const who = p.actor_id ? ` by ${p.actor_id}${p.actor_kind ? ` (${ACTOR_KIND_WORDS[p.actor_kind] || p.actor_kind})` : ""}` : "";
      if (p.decision === "REJECT") return { ...base, text: `Rejected${who}${p.return_to ? ` · ${RETURN_TO_WORD[p.return_to] || p.return_to}` : ""}`, reason: p.rationale };
      return { ...base, text: `Approved${who}`, reason: p.rationale };
    }
    case "EXECUTION_CLAIMED": return { ...base, text: "Dispatch claimed" };
    case "EXECUTION_RECORDED": return { ...base, text: p.status && p.status !== "CONFIRMED" ? `Dispatch receipt recorded · ${String(p.status).toLowerCase()}` : "Dispatch receipt recorded" };
    case "OBSERVATION_PLANNED": return { ...base, text: "Observation planned" };
    case "OUTCOME_RECORDED": return { ...base, text: "Outcome recorded" };
    case "INCIDENT_ESCALATED": return { ...base, text: "Case escalated" };
    case "INCIDENT_CLOSED": return { ...base, text: "Case closed" };
    case "INCIDENT_CANCELLED": return { ...base, text: `Case cancelled by ${actorWords(p.actor)}`, reason: p.rationale };
    case "LIFECYCLE_COMMAND": return { ...base, text: `${COMMAND_WORD[p.command] || "Command"} by ${actorWords(p.actor)}`, reason: p.rationale };
    case "ANALYSIS_RETRY_SCHEDULED": return { ...base, text: `Analysis retry scheduled · attempt ${p.attempt ?? "?"} of ${p.budget ?? "?"}`, reason: p.code ? `${String(p.category || "").toLowerCase()} · ${p.code}` : null };
    case "ANALYSIS_SUSPENDED": return { ...base, text: `Analysis suspended after ${p.attempt ?? "?"} technical failures`, reason: p.code ? `${String(p.category || "").toLowerCase()} · ${p.code}` : null };
    case "ANALYSIS_RESUMED": return { ...base, text: "Analysis resumed" };
    case "HYPOTHESES_REGISTERED": return { ...base, text: `Hypotheses registered${(p.new || []).length ? ` · ${(p.new || []).join(", ")}` : ""}`, authoritative: false };
    case "WORK_ASSIGNED": return { ...base, text: `Work requested · ${p.assignee?.reference || "assignee not recorded"}` };
    case "WORK_ACKNOWLEDGED": return { ...base, text: `Work request acknowledged by ${actorWords(p.actor)}` };
    case "WORK_REPORTED": return { ...base, text: `Work reported (${String(p.result || "result not recorded").toLowerCase().replace(/_/g, " ")}) by ${actorWords(p.actor)}` };
    case "ARTIFACT_ADDED": return { ...base, text: `Artifact added · ${p.kind || "record"}`, authoritative: false, group: "artifact" };
    default: return { ...base, text: e.event_type ? e.event_type.replace(/_/g, " ").toLowerCase() : "Event" };
  }
}

/** Authoritative transitions and human acts for the curated inline record (~10; R-12). */
export function curatedRecord(events) {
  return (events || []).map(eventCopy).filter((e) => e && e.authoritative && e.group !== "evidence");
}

/** One sentence: what happens next. `c` is a derived case (model/cases.js). */
export function nextStepSentence(c) {
  if (c.suspension) return "Automated analysis is suspended after repeated technical failures. A person resumes it or escalates the case.";
  if (c.phase === "AWAITING_APPROVAL" && c.approval?.state === "invalidated") return "Newer evidence invalidated the promoted plan. Reinvestigate, or return the case to planning.";
  if (c.phase === "AWAITING_APPROVAL" && c.approval?.state === "expired") return "The approval request expired; nothing was dispatched. Renew it for the same work package, or return the case to planning.";
  switch (c.phase) {
    case "AWAITING_APPROVAL": return "Decision required: approve or reject the exact work package before the requirement expires.";
    case "AWAITING_EVIDENCE": return "The case waits for a recorded technician inspection. Investigation resumes once the inspection is recorded.";
    case "DIAGNOSIS_VALIDATED": return "Resources (technician, parts, window) need confirmation before the work package can be drafted.";
    case "ESCALATED": return "A person resumes the investigation or cancels the case.";
    case "EXECUTION_FAILED": return "The work order wasn’t confirmed. Once the dispatch outcome is definitive, retry it, reinvestigate or cancel.";
    case "READY": return "The work package is approved but not dispatched. Dispatch is an explicit step; nothing dispatches it automatically.";
    case "EXECUTING": return "Nothing required. The work order is being committed.";
    case "OBSERVING": return "Nothing required. Verification (system) continues against the outcome policy.";
    case "CLOSED": return "Closed. No further action.";
    case "CANCELLED": return "Cancelled. No further action; the asset can open a new case.";
    default: return "Nothing required from you. Waiting on analysis (automated).";
  }
}

export { PHASE_STAGE };
