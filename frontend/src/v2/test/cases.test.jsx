// F4.1 Cases list (screen 4, today's variant) over real engine frames: the latest case per asset,
// labelled as limited history; URL-held status, stage, waiting-on, asset filters and sort; and the
// list, My actions, Overview and the preview agreeing on stage, waiting-on and next step.
import { readFileSync } from "node:fs";
import { renderToString } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../App.jsx";
import { applySnapshot, initialState } from "../../state/engineState.js";
import { deriveCase } from "../model/cases.js";
import { filterCases, isException, listState, sortCases, statusCounts } from "../model/caseList.js";
import { WB_ROUTES } from "../shell/routes.js";
import { fixtureNow } from "../../../test/fixture-era.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../../../test/fixtures/${name}`, import.meta.url), "utf8"));
const FRAMES = load("demo-frames.json");
const NOW = fixtureNow(FRAMES);
const APPROVAL = FRAMES.find((f) => f.alerts?.[0]?.lifecycle?.phase === "AWAITING_APPROVAL");
const CLOSED = FRAMES.at(-1);
const [ESCALATED, , CANCELLED] = load("demo-frames-recovery.json");
const [SUSPENDED] = load("demo-frames-suspended.json");
const [EXPIRED] = load("demo-frames-expired.json");
const [FAILED, READY] = load("demo-frames-dispatch.json");
const [BLOCKING] = load("demo-frames-blocking.json");

const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-10-08T21:00:00Z", mode: "demo" };
const noop = () => Promise.resolve({ ok: true });
const ACTIONS = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };
const render = (path, frame, session = SESSION) => renderToString(
  <App engine={{ state: applySnapshot(initialState, frame), ...ACTIONS }} session={session} settings={null} theme="light" router="memory" initialEntries={[path]} />);
const text = (html) => html.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
// Each fixture frame is one case; a list of several is built from the real alerts, one per frame.
const caseOf = (frame) => deriveCase(frame.alerts[0], { now: NOW, warn: frame.warn_threshold, trigger: frame.trigger_threshold });
const ALL = [APPROVAL, CLOSED, ESCALATED, CANCELLED, SUSPENDED, EXPIRED, FAILED, READY, BLOCKING].map(caseOf);
const params = (s) => new URLSearchParams(s);

beforeAll(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(NOW); });
afterAll(() => vi.useRealTimers());

describe("list state from the URL", () => {
  it("defaults to active cases by attention, and ignores what it doesn't recognise", () => {
    expect(listState(params(""))).toEqual({ status: "active", stage: "", waiting: "", q: "", sort: "attention" });
    expect(listState(params("status=bogus&stage=NOPE&waiting=x&sort=?"))).toEqual({ status: "active", stage: "", waiting: "", q: "", sort: "attention" });
    expect(listState(params("status=resolved&stage=ESCALATED&waiting=approver&q=ac&sort=asset"))).toMatchObject({ status: "resolved", stage: "ESCALATED", waiting: "approver", q: "ac", sort: "asset" });
  });
});

describe("segments and filters over real cases", () => {
  it("exceptions: escalated, dispatch failed, suspended analysis and expired approval; never a resolved case", () => {
    const names = (list) => list.map((c) => c.phase + (c.suspension ? "+suspended" : "") + (c.approval?.state === "expired" ? "+expired" : "")).sort();
    expect(names(ALL.filter(isException))).toEqual(["AWAITING_APPROVAL+expired", "ESCALATED", "EXECUTION_FAILED", "INVESTIGATING+suspended"]);
    expect(statusCounts(ALL)).toEqual({ active: 7, exceptions: 4, resolved: 2, all: 9 });
  });

  it("stage, waiting-on and asset filters combine", () => {
    const base = { status: "all", stage: "", waiting: "", q: "" };
    expect(filterCases(ALL, { ...base, stage: "AWAITING_DECISION" }).map((c) => c.phase)).toEqual(["AWAITING_APPROVAL", "AWAITING_APPROVAL"]);
    expect(filterCases(ALL, { ...base, waiting: "reliability_engineer" }).map((c) => c.phase).sort()).toEqual(["ESCALATED", "INVESTIGATING"]);
    expect(filterCases(ALL, { ...base, status: "resolved" }).map((c) => c.phase).sort()).toEqual(["CANCELLED", "CLOSED"]);
    expect(filterCases(ALL, { ...base, q: "no-such-asset" })).toEqual([]);
  });

  it("sorts by attention first, keeping every case", () => {
    const sorted = sortCases(ALL, "attention");
    expect(sorted).toHaveLength(ALL.length);
    expect(sorted[0].attention).toBe("action");
    expect(sorted.at(-1).attention).not.toBe("action");
  });
});

describe("the Cases screen", () => {
  it("is a V2 page labelled as limited history (latest case per asset)", () => {
    const page = text(render(WB_ROUTES.cases, APPROVAL));
    expect(page).toContain("Cases");
    expect(page).toContain("Latest case per asset");
    expect(page).toContain("Limited history: the live stream carries only the latest case for each asset (G5).");
    expect(page).not.toContain("isn’t available in this version");
  });

  it("an escalated case: stage, why, who it waits on and the response", () => {
    const page = text(render(`${WB_ROUTES.cases}?status=exceptions`, ESCALATED));
    expect(page).toContain("Escalated");
    expect(page).toContain("Reliability engineer Resolve escalation");
    expect(page).toContain("Exceptions · 1");
  });

  it("a suspended analysis is listed as an exception with its reason", () => {
    expect(text(render(`${WB_ROUTES.cases}?status=exceptions`, SUSPENDED))).toContain("analysis suspended");
  });

  it("a cancelled case is resolved, not active", () => {
    expect(text(render(WB_ROUTES.cases, CANCELLED))).toContain("No open cases on the live stream.");
    expect(text(render(`${WB_ROUTES.cases}?status=resolved`, CANCELLED))).toContain("Cancelled");
  });

  it("filters that match nothing say so and offer to clear them", () => {
    const page = text(render(`${WB_ROUTES.cases}?status=all&q=zzz`, APPROVAL));
    expect(page).toContain("No cases match these filters.");
    expect(page).toContain("Clear filters");
  });

  it("the preview opens beside the list with the same truthful deadline wording", () => {
    const expiredId = EXPIRED.alerts[0].incident_id;
    const page = text(render(`${WB_ROUTES.cases}?status=all&preview=${expiredId}`, EXPIRED));
    expect(page).toContain("Case preview");
    expect(page).toContain("approval expired");
    expect(page).toMatch(/Deadline Expired/);
    expect(page).not.toContain("Go to decision");
  });
});

describe("consistency across Overview, My actions, the list and the preview", () => {
  it.each([["escalated", ESCALATED], ["suspended", SUSPENDED], ["expired", EXPIRED], ["failed", FAILED], ["ready", READY]])(
    "%s: the same response verb everywhere it appears", (_n, frame) => {
      const c = caseOf(frame);
      expect(c.response?.verb).toBeTruthy();
      const id = frame.alerts[0].incident_id;
      const surfaces = [render(WB_ROUTES.overview, frame), render(`${WB_ROUTES.cases}?status=all`, frame), render(`${WB_ROUTES.cases}?status=all&preview=${id}`, frame)];
      for (const html of surfaces) expect(text(html)).toContain(c.response.verb);
    });

  it("My actions names what an approver's queue holds (resource confirmation is a planner input now)", () => {
    const page = text(render(WB_ROUTES.actions, APPROVAL));
    expect(page).toContain("approval decisions, expired or invalidated approvals, approved work awaiting dispatch and dispatch failures");
    expect(page).not.toContain("resource confirmations");
  });

  it("Overview counts only confirmed dispatches as work in progress", () => {
    expect(text(render(WB_ROUTES.overview, FAILED))).toContain("No committed work orders.");
    const observing = FRAMES.find((f) => f.alerts?.[0]?.lifecycle?.phase === "OBSERVING");
    expect(text(render(WB_ROUTES.overview, observing))).toContain("Requested; not acknowledged; no work report");
  });
});
