// The work boundary as this build presents it: dispatch ≠ work ≠ recovery ≠ verification.
// F1.2 (backend) changes this boundary: verification is to start only after a work report, and the
// plant response stops following dispatch. Everything about that presentation lives in this one
// module, so the F1.2 integration updates wording and mapping here without touching the screens.

/** F1.1 work facts (`alerts[].lifecycle.work[]`, derived by the backend from events). */
export const WORK_STATE = {
  ASSIGNED: { label: "Requested", sentence: "Work requested" },
  ACKNOWLEDGED: { label: "Acknowledged", sentence: "Request acknowledged by the assignee" },
  REPORTED: { label: "Reported", sentence: "Work reported by the assignee" },
};

export const REPORT_RESULT = { COMPLETED: "completed", PARTIAL: "partially completed", NOT_PERFORMED: "not performed" };

/** One line per assignment, from backend facts only. */
export function workFacts(lifecycle) {
  return (lifecycle?.work || []).map((w) => {
    const state = WORK_STATE[w.state] || { label: w.state || "Not reported", sentence: "Work state not reported" };
    const assignee = w.assignee?.reference || "an unrecorded assignee";
    const kind = String(w.assignee?.kind || "").toLowerCase().replace(/_/g, " ");
    return {
      id: w.assignment_id,
      state: w.state,
      label: state.label,
      text: `${state.sentence} · ${assignee}${kind ? ` (${kind})` : ""}`,
      workOrder: w.external_refs?.wo_number || null,
      assignedAt: w.assigned_at || null,
      acknowledgedAt: w.acknowledged_at || null,
      reportedAt: w.reported_at || null,
      result: w.result ? REPORT_RESULT[w.result] || w.result : null,
    };
  });
}

/** Field status line. A work fact is about people, never evidence that the plant recovered. */
export function fieldStatus(lifecycle) {
  const facts = workFacts(lifecycle);
  if (!facts.length) return "No work has been requested.";
  return facts.map((f) => (f.state === "REPORTED" ? `Work reported${f.result ? ` (${f.result})` : ""}` : f.state === "ACKNOWLEDGED" ? "Acknowledged; no work report yet" : "Requested; not acknowledged; no work report")).join(" · ");
}

/** When verification begins in this build (pre-F1.2): at the dispatch receipt, not at a work report. */
export const VERIFICATION_BASIS = "Verification starts at the dispatch receipt in this build. A work report isn’t required before observation begins; that changes with the work boundary (F1.2).";

export const DISPATCH_IS_NOT_WORK = "A confirmed dispatch means the work order was committed. It doesn’t mean the work was done or that the asset recovered.";

/** Plain wording for the observation line (pre-F1.2). */
export function observingSince(at) {
  return at ? `Observing since ${at} (from the dispatch receipt)` : "Observing (start not recorded)";
}
