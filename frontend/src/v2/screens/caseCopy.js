// Copy derived from backend facts (07 §19). Plain language; no invented values.
import { stageOf, PHASE_STAGE } from "../model/status.js";

const STAGE_WORD = (phase) => stageOf(phase)?.label || phase;

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
    case "APPROVAL_RECORDED": return { ...base, text: `${p.decision === "REJECT" ? "Rejected" : "Approved"}${p.actor_id ? ` by ${p.actor_id}` : ""}` };
    case "EXECUTION_CLAIMED": return { ...base, text: "Dispatch claimed" };
    case "EXECUTION_RECORDED": return { ...base, text: "Dispatch receipt recorded" };
    case "OBSERVATION_PLANNED": return { ...base, text: "Observation planned" };
    case "OUTCOME_RECORDED": return { ...base, text: "Outcome recorded" };
    case "INCIDENT_ESCALATED": return { ...base, text: "Case escalated" };
    case "INCIDENT_CLOSED": return { ...base, text: "Case closed" };
    case "ARTIFACT_ADDED": return { ...base, text: `Artifact added · ${p.kind || "record"}`, authoritative: false, group: "artifact" };
    default: return { ...base, text: e.event_type ? e.event_type.replace(/_/g, " ").toLowerCase() : "Event" };
  }
}

/** Authoritative transitions and human acts for the curated inline record (~10; R-12). */
export function curatedRecord(events) {
  return (events || []).map(eventCopy).filter((e) => e && e.authoritative && e.group !== "evidence");
}

export function nextStepSentence(c) {
  switch (c.phase) {
    case "AWAITING_APPROVAL": return "Decision required: approve or reject the exact work package before the requirement expires.";
    case "AWAITING_EVIDENCE": return "Technician inspection required to confirm the suspected mechanism.";
    case "DIAGNOSIS_VALIDATED": return "Resources (technician, parts, window) need confirmation before planning completes.";
    case "ESCALATED": return "Engineering decision required. Resolving escalations isn’t available in this version (G2).";
    case "EXECUTION_FAILED": return "Work order not confirmed. Retry isn’t available in this version (G3).";
    case "OBSERVING": return "Nothing required. Verification (system) continues against the outcome policy.";
    case "READY": case "EXECUTING": return "Nothing required. Dispatch (system) is committing the work order.";
    case "CLOSED": return "Closed. No further action.";
    default: return `Nothing required from you. Waiting on analysis (automated).`;
  }
}

export { PHASE_STAGE };
