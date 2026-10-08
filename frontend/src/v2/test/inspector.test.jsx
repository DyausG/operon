// F4.1 case inspector: URL state (?inspect=…) and the server-rendered views over real engine frames.
import { readFileSync } from "node:fs";
import { renderToString } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../App.jsx";
import { applySnapshot, initialState } from "../../state/engineState.js";
import { inspectHref, parseInspect } from "../model/inspect.js";
import { WB_ROUTES } from "../shell/routes.js";
import { fixtureNow } from "../../../test/fixture-era.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../../../test/fixtures/${name}`, import.meta.url), "utf8"));
const FRAMES = load("demo-frames.json");
const APPROVAL = FRAMES.find((f) => f.alerts?.[0]?.lifecycle?.phase === "AWAITING_APPROVAL");
const [EXPIRED] = load("demo-frames-expired.json");
const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-10-08T21:00:00Z", mode: "demo" };
const noop = () => Promise.resolve({ ok: true });
const ACTIONS = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };
const render = (path, frame = APPROVAL) => renderToString(
  <App engine={{ state: applySnapshot(initialState, frame), ...ACTIONS }} session={SESSION} settings={null} theme="light" router="memory" initialEntries={[path]} />);
const text = (html) => html.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const ID = APPROVAL.alerts[0].incident_id;
const pane = (html) => html.split('aria-labelledby="wb-inspector-title"')[1]?.split("</aside>")[0] ?? null;

beforeAll(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(fixtureNow(FRAMES)); });
afterAll(() => vi.useRealTimers());

describe("inspector URL state", () => {
  it("parses the known views and artifacts, and nothing else", () => {
    expect(parseInspect("asset")).toEqual({ kind: "asset" });
    expect(parseInspect("artifact:ev-1")).toEqual({ kind: "artifact", id: "ev-1" });
    for (const bad of ["", "artifact:", "constructor", "toString", "ASSET", null]) expect(parseInspect(bad)).toBeNull();
  });
  it("keeps the other query parameters and the hash", () => {
    const loc = { pathname: "/app/cases/i-1", search: "?from=actions", hash: "#evidence" };
    expect(inspectHref(loc, { kind: "artifact", id: "a b" })).toBe("/app/cases/i-1?from=actions&inspect=artifact%3Aa+b#evidence");
    expect(inspectHref({ ...loc, search: "?inspect=asset&from=actions" }, null)).toBe("/app/cases/i-1?from=actions#evidence");
  });
});

describe("inspector views (server render, docked)", () => {
  it("the identity row offers the asset, identifiers and full record", () => {
    const page = text(render(WB_ROUTES.case(ID)));
    expect(page).toContain("Inspect: asset · identifiers · full record");
    expect(render(WB_ROUTES.case(ID))).not.toContain("wb-inspector-title");
  });

  it("asset: the asset, its thresholds and the limited case scope", () => {
    const html = render(`${WB_ROUTES.case(ID)}?inspect=asset#evidence`);
    const p = text(pane(html));
    expect(p).toContain(`Asset · ${APPROVAL.alerts[0].equipment_id}`);
    expect(p).toContain("latest case per asset (G5)");
    expect(html).toContain('id="wb-case-section"'); // the case stays beside it
    expect(text(html)).toContain("Evidence");
  });

  it("identifiers: the exact identifiers the backend projects", () => {
    const p = pane(render(`${WB_ROUTES.case(ID)}?inspect=identifiers`));
    const lc = APPROVAL.alerts[0].lifecycle;
    for (const v of [ID, lc.intervention_hash, lc.requirement_id]) expect(p).toContain(`title="${v}"`);
  });

  it("an expired requirement is labelled as no longer pending", () => {
    expect(text(pane(render(`${WB_ROUTES.case(EXPIRED.alerts[0].incident_id)}?inspect=identifiers`, EXPIRED)))).toContain("the backend no longer treats as pending");
  });

  it("full record: every event, newest first, with the human acts by default", () => {
    const p = text(pane(render(`${WB_ROUTES.case(ID)}?inspect=record`)));
    const total = APPROVAL.alerts[0].lifecycle.read_model.events.length;
    expect(p).toMatch(new RegExp(`\\d+ of ${total} events · newest first`));
    expect(p).toContain("Approval requested");
  });

  it("all evidence links each item to its record detail, inside the workbench", () => {
    const p = pane(render(`${WB_ROUTES.case(ID)}?inspect=evidence`));
    const ev = APPROVAL.alerts[0].lifecycle.read_model.evidence;
    expect(ev.length).toBeGreaterThan(0);
    expect(p).toContain(`href="/app/cases/${ID}?inspect=artifact%3A${ev[0].id}"`);
  });

  it("an unknown inspector value opens nothing", () => {
    expect(render(`${WB_ROUTES.case(ID)}?inspect=nonsense`)).not.toContain("wb-inspector-title");
  });
});
