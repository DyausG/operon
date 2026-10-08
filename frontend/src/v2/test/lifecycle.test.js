// F4.1 lifecycle model: approval state, suspension, command availability (mirrors the preconditions
// in core/reliability/lifecycle.py and server/main.py), action gating, stage line, navigator hash
// routing, safe refusals and the isolated F1.2 work-boundary wording. Pure functions, small inputs.
import { describe, expect, it } from "vitest";
import { actionGate, approvalStateOf, approverRoleBlock, availableCommands, commandRequest, revisionOf, sectionForHash, sectionStates, stageLineOf, suspensionOf } from "../model/lifecycle.js";
import { responseFor, waitingOn } from "../model/status.js";
import { cleanServerText, refusalFrom, serverReason } from "../model/refusal.js";
import { fieldStatus, workFacts, VERIFICATION_BASIS } from "../model/workBoundary.js";

const NOW = Date.parse("2026-10-09T12:00:00Z");
const iso = (minutes) => new Date(NOW + minutes * 60000).toISOString();
const ev = (event_type, payload, minutes = 0) => ({ id: `${event_type}-${minutes}`, event_type, payload, created_at: iso(minutes), revision: 1 });
const alert = (lifecycle) => ({ incident_id: "i-1", equipment_id: "A-1", lifecycle: { read_model: { events: [], requirements: [] }, ...lifecycle } });
const commandsOf = (a) => availableCommands(a, { now: NOW }).map((c) => c.command);

describe("approval state while AWAITING_APPROVAL", () => {
  const req = (id, minutes, interventionId = "iv-1") => ({ id, intervention_id: interventionId, expires_at: iso(minutes), created_at: iso(minutes - 1440) });

  it("pending while the projected requirement has time left", () => {
    const a = alert({ phase: "AWAITING_APPROVAL", requirement_id: "r1", intervention_id: "iv-1", authority_valid: true, read_model: { requirements: [req("r1", 30)] } });
    expect(approvalStateOf(a, NOW).state).toBe("pending");
  });
  it("expired by the clock once expires_at passes, before the backend refreshes", () => {
    const a = alert({ phase: "AWAITING_APPROVAL", requirement_id: "r1", intervention_id: "iv-1", authority_valid: true, read_model: { requirements: [req("r1", -1)] } });
    expect(approvalStateOf(a, NOW)).toMatchObject({ state: "expired", basis: "clock" });
  });
  it("expired when the backend no longer projects a pending requirement (it only projects PENDING)", () => {
    const a = alert({ phase: "AWAITING_APPROVAL", requirement_id: null, intervention_id: "iv-1", authority_valid: true, read_model: { requirements: [req("r0", -2000, "iv-0"), req("r1", 30)] } });
    const s = approvalStateOf(a, NOW);
    expect(s).toMatchObject({ state: "expired", basis: "backend" });
    expect(s.requirement.id).toBe("r1");
  });
  it("invalidated when newer evidence voids the promoted plan's authority", () => {
    const a = alert({ phase: "AWAITING_APPROVAL", requirement_id: null, intervention_id: "iv-1", authority_valid: false, authority_reason: "evidence changed" });
    expect(approvalStateOf(a, NOW)).toEqual({ state: "invalidated", reason: "evidence changed" });
  });
  it("none outside AWAITING_APPROVAL", () => expect(approvalStateOf(alert({ phase: "PLANNING" }), NOW).state).toBe("none"));
});

describe("analysis suspension (F1.1)", () => {
  it("is read from lifecycle.analysis and is not a phase", () => {
    expect(suspensionOf({ analysis: { suspended: true, attempts: 3, codes: { TIMEOUT: 3 }, last_code: "TIMEOUT" } })).toMatchObject({ attempts: 3, lastCode: "TIMEOUT" });
    expect(suspensionOf({ analysis: { suspended: false, attempts: 1 } })).toBeNull();
    expect(suspensionOf({ analysis: null })).toBeNull();
  });
  it("puts a reliability engineer on the case and asks for a resume", () => {
    expect(waitingOn("INVESTIGATING", { suspended: true }).key).toBe("reliability_engineer");
    expect(responseFor("INVESTIGATING", { suspended: true }).verb).toBe("Resume suspended analysis");
    expect(waitingOn("CLOSED", { suspended: true }).key).toBe("none");
  });
});

describe("waiting-on corrections (F0 #19)", () => {
  it("resource confirmation is a planning input, not an approval", () => expect(waitingOn("DIAGNOSIS_VALIDATED").key).toBe("planner"));
  it("a READY case needs an explicit dispatch by a person, never automatic", () => {
    expect(waitingOn("READY").human).toBe(true);
    expect(responseFor("READY").verb).toBe("Dispatch approved work package");
  });
  it("no response is ever offered on a terminal case", () => {
    for (const p of ["CLOSED", "CANCELLED"]) expect(responseFor(p, { suspended: true, expired: true })).toBeNull();
  });
  it("escalations and dispatch failures are resolvable now (no G2 / G3 gap)", () => {
    expect(responseFor("ESCALATED").gap).toBeNull();
    expect(responseFor("EXECUTION_FAILED").gap).toBeNull();
    expect(responseFor("AWAITING_EVIDENCE").gap).toBe("G1");
  });
});

describe("available commands mirror the backend preconditions", () => {
  const approving = (extra = {}) => alert({ phase: "AWAITING_APPROVAL", requirement_id: "r1", intervention_id: "iv-1", intervention_hash: "h", authority_valid: true,
    read_model: { requirements: [{ id: "r1", intervention_id: "iv-1", expires_at: iso(60), created_at: iso(-60) }], events: [] }, ...extra });

  it.each([
    ["OPEN", ["escalate", "cancel"]], ["INVESTIGATING", ["escalate", "cancel"]], ["AWAITING_EVIDENCE", ["escalate", "cancel"]],
    ["DIAGNOSIS_VALIDATED", ["escalate", "cancel"]], ["PLANNING", ["escalate", "cancel"]], ["OBSERVING", ["escalate", "cancel"]],
    ["EXECUTING", []], ["CLOSED", []], ["CANCELLED", []],
  ])("%s → %j", (phase, expected) => expect(commandsOf(alert({ phase }))).toEqual(expected));

  it("a pending, valid approval offers no command: the decision surface is the act", () => {
    expect(commandsOf(approving())).toEqual(["escalate", "cancel"]);
  });
  it("an expired approval offers renewal first, then return to planning", () => {
    expect(commandsOf(approving({ requirement_id: null }))).toEqual(["renew_approval", "return_to_planning", "escalate", "cancel"]);
  });
  it("an invalidated plan offers reinvestigation (resume) and return to planning, never renewal", () => {
    const c = availableCommands(approving({ requirement_id: null, authority_valid: false }), { now: NOW });
    expect(c.map((x) => x.command)).toEqual(["resume", "return_to_planning", "escalate", "cancel"]);
    expect(c[0].label).toBe("Reinvestigate");
  });
  it("an escalated case can be resumed or cancelled, not escalated again", () => {
    expect(commandsOf(alert({ phase: "ESCALATED" }))).toEqual(["resume", "cancel"]);
  });
  it("a definitive dispatch failure offers retry and reinvestigation; an ambiguous one does not", () => {
    expect(commandsOf(alert({ phase: "EXECUTION_FAILED", reconciliation_required: false }))).toEqual(["retry_execution", "resume", "escalate", "cancel"]);
    expect(commandsOf(alert({ phase: "EXECUTION_FAILED", reconciliation_required: true }))).toEqual(["escalate", "cancel"]);
  });
  it("READY offers the explicit dispatch only with a valid exact plan", () => {
    const ready = alert({ phase: "READY", intervention_id: "iv-1", intervention_hash: "h", authority_valid: true });
    const c = availableCommands(ready, { now: NOW });
    expect(c.map((x) => [x.command, x.endpoint])).toEqual([["execute", "execute"], ["return_to_planning", "command"], ["escalate", "command"], ["cancel", "command"]]);
    expect(commandsOf(alert({ phase: "READY", intervention_id: "iv-1", intervention_hash: null, authority_valid: true }))).not.toContain("execute");
  });
  it("a suspended analysis is resumed before anything else", () => {
    expect(commandsOf(alert({ phase: "INVESTIGATING", analysis: { suspended: true, attempts: 3 } }))).toEqual(["resume", "escalate", "cancel"]);
  });
  it("offers at most one primary action and never an unknown command", () => {
    const all = ["OPEN", "INVESTIGATING", "AWAITING_EVIDENCE", "PLANNING", "READY", "EXECUTION_FAILED", "ESCALATED", "OBSERVING"]
      .flatMap((phase) => [alert({ phase, intervention_id: "iv", intervention_hash: "h", authority_valid: true, analysis: { suspended: phase === "PLANNING" } })]);
    for (const a of [...all, approving({ requirement_id: null })]) {
      const c = availableCommands(a, { now: NOW });
      expect(c.filter((x) => x.intent === "primary").length).toBeLessThanOrEqual(1);
      for (const x of c) expect(["resume", "cancel", "escalate", "renew_approval", "return_to_planning", "retry_execution", "execute"]).toContain(x.command);
    }
  });
});

describe("action gate", () => {
  it("production refuses every human action until authenticated identity exists", () => {
    expect(actionGate({ environment: "PRODUCTION", sessionRole: "maintenance_approver", connected: true })).toMatchObject({ allowed: false });
  });
  it("observer is read-only; a lost connection makes actions inactive with a reason", () => {
    expect(actionGate({ environment: "UNSPECIFIED", sessionRole: "observer", connected: true }).allowed).toBe(false);
    expect(actionGate({ environment: "UNSPECIFIED", sessionRole: "reliability_engineer", connected: false })).toMatchObject({ allowed: true, inactive: "Reconnect to act on this case." });
  });
  it("never implies a verified identity", () => {
    expect(actionGate({ environment: "SANDBOX", sessionRole: "reliability_engineer", connected: true }).recordedAs).toMatch(/unauthenticated/);
    expect(actionGate({ environment: "UNSPECIFIED", sessionRole: "reliability_engineer", connected: true }).recordedAs).toMatch(/not verified/);
  });
  it("approval decisions need a required role (lifecycle.decide_approval refuses others, rejection too)", () => {
    const req = { required_roles: ["maintenance_approver"] };
    expect(approverRoleBlock(req, "maintenance_approver")).toBeNull();
    expect(approverRoleBlock(req, "reliability_engineer")).toBe("This approval needs the maintenance approver role; your declared role is reliability engineer. The backend refuses decisions from other roles.");
    expect(approverRoleBlock({ required_roles: [] }, "observer")).toBeNull(); // not reported: the backend decides
  });
});

describe("command requests", () => {
  const bound = { revision: 33, interventionId: "iv-1", interventionHash: "h-1" };
  it("a lifecycle command names the reviewed revision, a declared actor and a trimmed reason, never a kind", () => {
    const r = commandRequest("INC/7", { command: "renew_approval", endpoint: "command" }, { actorId: "a@example.com", actorRole: "maintenance_approver", rationale: "  window still open  ", bound });
    expect(r).toEqual({ url: "/api/incidents/INC%2F7/commands/renew_approval",
      body: { actor_id: "a@example.com", actor_role: "maintenance_approver", expected_revision: 33, rationale: "window still open" } });
    expect(r.body).not.toHaveProperty("actor_kind");
  });
  it("dispatch sends the exact approved intent and nothing else", () => {
    expect(commandRequest("i-1", { command: "execute", endpoint: "execute" }, { actorId: "a", actorRole: "r", rationale: "x", bound }))
      .toEqual({ url: "/api/incidents/i-1/execute", body: { intervention_id: "iv-1", intervention_hash: "h-1" } });
  });
  it("the revision is the incident revision the backend checks", () => {
    expect(revisionOf({ lifecycle: { revision: 40, context_revision: 40 } })).toBe(40);
    expect(revisionOf({ lifecycle: { context_revision: 12 } })).toBe(12);
    expect(revisionOf({})).toBeNull();
  });
  it("after a dispatch, cancel and escalate say what they don't undo", () => {
    const observing = alert({ phase: "OBSERVING", read_model: { events: [], requirements: [], execution_receipts: [{ status: "CONFIRMED" }] } });
    const c = Object.fromEntries(availableCommands(observing, { now: NOW }).map((x) => [x.command, x.consequence]));
    expect(c.cancel).toContain("A dispatched work order isn’t withdrawn by cancelling the case.");
    expect(c.escalate).toContain("resuming returns the case to Investigating, not to verification");
    expect(availableCommands(alert({ phase: "PLANNING" }), { now: NOW }).find((x) => x.command === "cancel").consequence).not.toContain("withdrawn");
  });
});

describe("stage line and navigator", () => {
  it("states the position in one line, with loops and exceptions in words", () => {
    const parked = alert({ phase: "AWAITING_EVIDENCE", read_model: { events: [ev("PHASE_CHANGED", { to: "AWAITING_EVIDENCE" }, 1), ev("PHASE_CHANGED", { to: "INVESTIGATING" }, 2), ev("PHASE_CHANGED", { to: "AWAITING_EVIDENCE" }, 3)] } });
    expect(stageLineOf(parked)).toMatchObject({ text: "Investigating · Awaiting inspection · stage 2 of 8", position: 2, context: ["inspection requested 2×"] });
    const escalated = alert({ phase: "ESCALATED", read_model: { events: [ev("PHASE_CHANGED", { from: "AWAITING_APPROVAL", to: "ESCALATED" }, 4)] } });
    expect(stageLineOf(escalated)).toMatchObject({ text: "Escalated · from Awaiting decision", exception: true, position: 5 });
    const replanning = alert({ phase: "PLANNING", read_model: { events: [ev("APPROVAL_RECORDED", { decision: "REJECT", return_to: "PLANNING" }, 5)] } });
    expect(stageLineOf(replanning).context).toEqual(["returned to planning after rejection"]);
  });
  it("routes legacy and V2 hashes: #decision opens Now while a decision is pending", () => {
    expect(sectionForHash("#decision", { decisionPending: true })).toBe("now");
    expect(sectionForHash("#decision", { decisionPending: false })).toBe("decision");
    expect(sectionForHash("#work")).toBe("work");
    expect(sectionForHash("#summary")).toBe("now");
    expect(sectionForHash("#nonsense")).toBe("now");
    expect(sectionForHash("")).toBe("now");
  });
  it("marks Now as action-required only when a person is required", () => {
    const s = sectionStates(alert({ phase: "INVESTIGATING" }), { requiresPerson: false });
    expect(s.map((x) => x.id)).toEqual(["now", "evidence", "investigation", "decision", "work", "record"]);
    expect(s[0].state).toBe("current");
    expect(sectionStates(alert({ phase: "ESCALATED" }), { requiresPerson: true })[0].state).toBe("action");
  });
});

describe("backend refusals are shown safely", () => {
  it("keeps one bounded plain-text line from a string reason", () => {
    expect(cleanServerText("refused\u0000 <b>now</b>\n\n twice")).toBe("refused <b>now</b> twice");
    expect(cleanServerText("x".repeat(400)).length).toBe(300);
    expect(cleanServerText({ html: "<script>" })).toBeNull();
  });
  it("takes the first FastAPI validation message, never the whole body", () => {
    expect(serverReason({ detail: [{ loc: ["body", "rationale"], msg: "String should have at least 1 character" }, { msg: "other" }] }))
      .toBe("rationale: String should have at least 1 character");
    expect(serverReason({ ok: false, error: "nothing to resume in PLANNING", incident: { huge: true } })).toBe("nothing to resume in PLANNING");
    expect(serverReason("<html>")).toBeNull();
  });
  it("keeps the status and a lead that says what happened", () => {
    expect(refusalFrom(403, { error: "production refuses" })).toEqual({ status: 403, lead: "Not permitted here. The server refused this action.", detail: "production refuses" });
    expect(refusalFrom(409, null).detail).toBeNull();
    expect(refusalFrom(0, null).lead).toMatch(/Couldn’t reach the server/);
    expect(refusalFrom(502, {}).lead).toMatch(/server failed/);
  });
});

describe("work boundary (isolated for F1.2)", () => {
  const lc = { work: [{ assignment_id: "w1", state: "ASSIGNED", assignee: { kind: "WORKER", reference: "TECH-201" }, external_refs: { wo_number: "WO-3" } }] };
  it("maps backend work facts and never calls them recovery", () => {
    expect(workFacts(lc)).toMatchObject([{ label: "Requested", text: "Work requested · TECH-201 (worker)", workOrder: "WO-3" }]);
    expect(fieldStatus(lc)).toBe("Requested; not acknowledged; no work report");
    expect(fieldStatus({ work: [] })).toBe("No work has been requested.");
    expect(VERIFICATION_BASIS).toMatch(/dispatch receipt/);
  });
});
