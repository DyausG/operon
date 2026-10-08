// F4.1 exception and recovery presentation over frames the real engine produced (test/make_fixtures.py
// drives each exception through labelled test seams; see that file). Each case's Now states what is
// true and who it waits on, and offers exactly the F1.1 commands whose backend preconditions hold.
// The environment and role gates are exercised on copies of real frames with one field changed; the
// change is named where it is made.
import { readFileSync } from "node:fs";
import { renderToString } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../App.jsx";
import { applySnapshot, initialState } from "../../state/engineState.js";
import { WB_ROUTES } from "../shell/routes.js";
import { fixtureNow } from "../../../test/fixture-era.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../../../test/fixtures/${name}`, import.meta.url), "utf8"));
const FRAMES = load("demo-frames.json");
const [ESCALATED, RESUMED, CANCELLED] = load("demo-frames-recovery.json");
const [SUSPENDED] = load("demo-frames-suspended.json");
const [EXPIRED] = load("demo-frames-expired.json");
const [FAILED, READY] = load("demo-frames-dispatch.json");
const [BLOCKING] = load("demo-frames-blocking.json");
const [AWAITING, PLANNING] = load("demo-frames-reject.json");
const OBSERVING = FRAMES.find((f) => f.alerts?.[0]?.lifecycle?.phase === "OBSERVING");
const CLOSED = FRAMES.at(-1);

const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-10-08T21:00:00Z", mode: "demo" };
const noop = () => Promise.resolve({ ok: true });
const ACTIONS = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };

const render = (path, frame, session = SESSION) => renderToString(
  <App engine={{ state: applySnapshot(initialState, frame), ...ACTIONS }} session={session} settings={null} theme="light" router="memory" initialEntries={[path]} />);
const text = (html) => html.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const now = (frame, session) => render(WB_ROUTES.case(frame.alerts[0].incident_id), frame, session);
const actionsOf = (html) => {
  const block = html.split('class="wb-actions-row"')[1]?.split("</div>")[0] || "";
  return [...block.matchAll(/<button[^>]*>.*?<span>(.*?)<\/span>/gs)].map((m) => text(m[1]).trim());
};
const decisionSurface = (html) => html.split('id="decision-surface"')[1]?.split("</section>")[0] ?? null;
/** A copy of a real frame with one lifecycle field changed (the gate tests below say which). */
const withLifecycle = (frame, patch) => {
  const copy = structuredClone(frame);
  Object.assign(copy.alerts[0].lifecycle, patch);
  return copy;
};

beforeAll(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(fixtureNow(FRAMES)); });
afterAll(() => vi.useRealTimers());

describe("Now over real exception frames", () => {
  it("ESCALATED after a rejection: the cause from the journal, the rejection, resume / cancel only", () => {
    const html = now(ESCALATED);
    const page = text(html);
    expect(page).toContain("Escalated · from Awaiting decision");
    expect(page).toContain("Waiting on Reliability engineer");
    expect(page).toContain("Escalated from Awaiting decision");
    expect(page).toContain("human rejected the promoted intervention; returned to ESCALATED");
    expect(page).not.toContain("human approval required"); // the stale last_reason is never shown as the cause
    expect(page).not.toContain("returned to planning"); // this rejection's return_to was ESCALATED
    expect(page).toContain("This asset can’t open a new case until this one is resumed or cancelled.");
    expect(actionsOf(html)).toEqual(["Resume investigation…", "Cancel case…"]);
  });

  it("resumed: back to Investigating, the resume recorded with a declared actor, no recovery command left but escalate / cancel", () => {
    const html = now(RESUMED);
    const page = text(html);
    expect(page).toContain("Investigating · stage 2 of 8");
    expect(page).toMatch(/Resumed by fixture-operator \(declared, not verified\)/);
    expect(actionsOf(html)).toEqual(["Escalate…", "Cancel case…"]);
  });

  it("CANCELLED: who cancelled and why, the record kept, no actions", () => {
    const html = now(CANCELLED);
    const page = text(html);
    expect(page).toMatch(/Cancelled by fixture-operator \(declared, not verified\)/);
    expect(page).toContain("The full record is kept; the asset can open a new case.");
    expect(html).not.toContain("wb-actions");
    expect(page).not.toMatch(/Waiting on/);
  });

  it("suspended analysis: a person must resume it; never shown as escalation", () => {
    const html = now(SUSPENDED);
    const page = text(html);
    expect(page).toContain("Analysis suspended");
    expect(page).toContain("Automated analysis stopped after 3 technical failures (TIMEOUT × 3)");
    expect(page).toContain("Waiting on Reliability engineer");
    expect(page).not.toMatch(/Escalated/);
    expect(actionsOf(html)).toEqual(["Resume analysis…", "Escalate…", "Cancel case…"]);
  });

  it("expired approval: no decision surface; renew or return to planning", () => {
    const html = now(EXPIRED);
    const page = text(html);
    expect(decisionSurface(html)).toBeNull();
    expect(page).toContain("Approval request expired");
    expect(page).toContain("Nothing was dispatched.");
    expect(actionsOf(html)).toEqual(["Renew approval…", "Return to planning…", "Escalate…", "Cancel case…"]);
  });

  it("dispatch failed definitively: retry or abandon, with the receipt's reason", () => {
    const html = now(FAILED);
    const page = text(html);
    expect(page).toContain("Dispatch failed");
    expect(page).toContain("Fixture: the work-order system rejected the package (test seam)");
    expect(page).toContain("The failure is definitive: nothing was dispatched.");
    expect(actionsOf(html)).toEqual(["Retry dispatch…", "Abandon dispatch and reinvestigate…", "Escalate…", "Cancel case…"]);
  });

  it("dispatch outcome unknown: neither retry nor abandon is offered (reconciliation first)", () => {
    // reconciliation_required set on a copy of the real failed frame: the backend refuses both.
    const html = now(withLifecycle(FAILED, { reconciliation_required: true }));
    expect(text(html)).toContain("The dispatch outcome is unknown");
    expect(actionsOf(html)).toEqual(["Escalate…", "Cancel case…"]);
  });

  it("READY after a retry: dispatch is an explicit step that records no actor", () => {
    const html = now(READY);
    const page = text(html);
    expect(page).toContain("Approved; waiting for dispatch");
    expect(page).toContain("In work · stage 6 of 8 · approved, not dispatched");
    expect(page).toContain("Waiting on Approver");
    expect(actionsOf(html)).toEqual(["Dispatch approved work package…", "Return to planning…", "Escalate…", "Cancel case…"]);
  });

  it("pending approval: the decision surface is the act; escalate and cancel sit under it", () => {
    const html = now(AWAITING);
    expect(decisionSurface(html)).not.toBeNull();
    expect(text(html)).toContain("Other actions on this case");
    expect(actionsOf(html)).toEqual(["Escalate…", "Cancel case…"]);
  });

  it.each([["blocking inspection wait", BLOCKING], ["planning after a rejection", PLANNING]])(
    "%s: only escalate and cancel", (_name, frame) => {
      expect(actionsOf(now(frame))).toEqual(["Escalate…", "Cancel case…"]);
    });

  it("observing: escalate and cancel stay available", () => {
    // lifecycle.cancel / escalate refuse only EXECUTING (and ESCALATED for escalate).
    expect(actionsOf(now(OBSERVING))).toEqual(["Escalate…", "Cancel case…"]);
  });

  it("closed: no actions", () => {
    expect(now(CLOSED)).not.toContain("wb-actions");
  });
});

describe("gates: environment, declared role, connection", () => {
  it("an observer sees what is valid but no controls", () => {
    const html = now(ESCALATED, { ...SESSION, role: "observer" });
    expect(actionsOf(html)).toEqual([]);
    expect(text(html)).toContain("Observer is a read-only role in this interface.");
    expect(text(html)).toContain("Valid on this case now, for a permitted person: Resume investigation · Cancel case.");
  });

  it("a production incident offers no human action and the decision surface is inactive", () => {
    // environment set to PRODUCTION on copies of real frames (the fixtures run UNSPECIFIED).
    const escalated = now(withLifecycle(ESCALATED, { environment: "PRODUCTION" }));
    expect(actionsOf(escalated)).toEqual([]);
    expect(text(escalated)).toContain("Production refuses human actions until authenticated identity exists (F3).");
    const decision = decisionSurface(now(withLifecycle(AWAITING, { environment: "PRODUCTION" })));
    expect(decision).toMatch(/<button[^>]*aria-disabled="true"[^>]*>(?:(?!<\/button>).)*Approve and dispatch/s);
    expect(decision).toMatch(/<button[^>]*aria-disabled="true"[^>]*>(?:(?!<\/button>).)*Reject and return to planning/s);
  });

  it("a role that cannot satisfy the requirement cannot approve or reject, and is told why", () => {
    const html = now(AWAITING, { ...SESSION, role: "reliability_engineer" });
    const decision = decisionSurface(html);
    expect(text(decision)).toContain("This approval needs the maintenance approver role; your declared role is reliability engineer.");
    expect(decision).toMatch(/<button[^>]*aria-disabled="true"[^>]*>(?:(?!<\/button>).)*Approve and dispatch/s);
  });

  it("sandbox wording never implies a verified identity", () => {
    const html = now(withLifecycle(AWAITING, { environment: "SANDBOX" }));
    expect(text(decisionSurface(html))).toContain("sandbox identity, unauthenticated");
    expect(text(html)).not.toMatch(/verified identity|authenticated as/i);
  });
});
