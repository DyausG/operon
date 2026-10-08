// Server-renders the Phase 4A routes for every engine fixture frame (test/make_fixtures.py: the real
// engine and lifecycle, no provider) and asserts the backend-truth rules of 08 §11.3 check 6.
import { readFileSync } from "node:fs";
import { renderToString } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../App.jsx";
import { applySnapshot, initialState } from "../../state/engineState.js";
import { fixtureNow } from "../../../test/fixture-era.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../../../test/fixtures/${name}`, import.meta.url), "utf8"));
const FRAMES = [...load("demo-frames.json"), ...load("demo-frames-reject.json"),
  ...load("demo-frames-material.json"), ...load("demo-frames-blocking.json")];
const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-09-15T18:40:00Z", mode: "demo" };
const noop = () => Promise.resolve({ ok: true });
const ACTIONS = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };

function render(path, state) {
  return renderToString(<App engine={{ state, ...ACTIONS }} session={SESSION} settings={null} theme="light" router="memory" initialEntries={[path]} />);
}

function statesFor() {
  let st = initialState;
  return FRAMES.map((f) => { st = applySnapshot(st, f); return { frame: f, state: st }; });
}

// Pin the clock to the fixture era so requirement deadlines are pending, as they were when captured.
beforeAll(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(fixtureNow(FRAMES)); });
afterAll(() => vi.useRealTimers());

const FORBIDDEN = [
  /confidence\W{0,3}(?:of\s)?\d/i, /\d\s?%\s?confiden/i, // a model self-reported confidence value (PO-A); the backend's basis text may say none exists
  /\b0\.72\b|\b72(\.\d)?\s?%/, /\b0\.18\b/, // the run's uncalibrated hypothesis confidences in the fixtures
  /\bOEE\b/i, /fleet projection/i, /downtime cost per hour/i, /recovered per event/i, // `business` constants
  /assets crossed/i, // burst grouping is not implemented (G5)
  /\bAI\b|AI-powered|smart|Our AI/, // copy bans (07 §19)
];

describe.each(statesFor().map((x, i) => [`${i} ${x.frame.demo_scenario?.status} / ${x.frame.alerts?.[0]?.lifecycle?.phase || "no case"}`, x]))("frame %s", (_label, { state }) => {
  const alert = Object.values(state.alerts)[0];
  const routes = ["/app/overview", "/app/actions", "/app/system/simulation"];
  if (alert) routes.push(`/app/cases/${alert.incident_id}`, `/app/actions?preview=${alert.incident_id}`);

  it.each(routes)("%s renders inside the V2 shell", (path) => {
    const html = render(path, state);
    expect(html).toContain('class="wb-root"');
    expect(html).toContain('aria-label="Primary"');
    // No simulator / engine controls in the operational header.
    const header = html.split('<header class="wb-header">')[1].split("</header>")[0];
    expect(header).not.toMatch(/Start guided demo|Pause simulation|Reset/);
  });

  it.each(routes)("%s shows only backend truth", (path) => {
    const text = render(path, state).replace(/<[^>]+>/g, " ");
    for (const re of FORBIDDEN) expect(text).not.toMatch(re);
    expect(text).not.toMatch(/\s—\s*$/m); // missing values are words, never a bare dash (R-15)
  });

  it.each(routes)("%s keeps title blocks ≤ 6 cells and status shapes ≥ 14 px", (path) => {
    const html = render(path, state);
    for (const block of html.split('class="wb-titleblock"').slice(1)) {
      const cells = block.split("</dl>")[0].match(/class="wb-tb-cell"/g) || [];
      expect(cells.length).toBeLessThanOrEqual(6);
    }
    for (const m of html.matchAll(/<svg class="wb-shape[^"]*" width="(\d+)"/g)) expect(Number(m[1])).toBeGreaterThanOrEqual(14);
    for (const m of html.matchAll(/<svg class="wb-prov" width="(\d+)"/g)) expect(Number(m[1])).toBe(10);
  });
});

describe("decision surface (screen 8) over the AWAITING_APPROVAL fixture", () => {
  const { state } = statesFor().find((x) => x.frame.alerts?.[0]?.lifecycle?.phase === "AWAITING_APPROVAL");
  const alert = Object.values(state.alerts)[0];
  const lc = alert.lifecycle;

  it("binds the exact identifiers and shows the binding token above the controls", () => {
    const html = render(`/app/cases/${alert.incident_id}`, state);
    expect(html).toContain("Decision required");
    const text = html.replace(/<!-- -->/g, "");
    expect(text).toContain(`Binding <span class="wb-mono">${lc.intervention_hash.slice(0, 6)} · R${lc.context_revision}</span>`);
    expect(text.indexOf("Binding <span")).toBeLessThan(text.indexOf("<span>Approve and dispatch</span>"));
    expect(html).toContain("Rejecting returns the case to planning for a revised plan."); // F1: reject no longer escalates
    expect(html).toContain("declared, not verified: G8");
  });

  it("Approve is active while connected and inactive (aria-disabled, focusable) when disconnected", () => {
    const live = render(`/app/cases/${alert.incident_id}`, state);
    const approveLive = live.match(/<button[^>]*>(?:(?!<\/button>).)*Approve and dispatch/s)[0];
    expect(approveLive).not.toContain("aria-disabled");
    const off = render(`/app/cases/${alert.incident_id}`, { ...state, connected: false });
    const approveOff = off.match(/<button[^>]*>(?:(?!<\/button>).)*Approve and dispatch/s)[0];
    expect(approveOff).toContain('aria-disabled="true"');
    expect(approveOff).not.toMatch(/\sdisabled=""/);
    expect(off).toContain("Reconnect to make decisions.");
    expect(off).toContain("Live connection lost.");
  });

  it("violet appears only as the person glyph tone and the short role word", () => {
    const html = render(`/app/cases/${alert.incident_id}`, state);
    const decision = html.split('id="decision-surface"')[1].split("</section>")[0];
    expect(decision.match(/wb-tone-decision/g)?.length).toBe(1); // the heading glyph only
    expect(decision).not.toMatch(/wb-role-word/);
  });

  it("the preview never contains decision controls", () => {
    const html = render(`/app/actions?preview=${alert.incident_id}`, state);
    const pane = html.split('role="complementary"')[1] || "";
    expect(pane).not.toContain("Approve and dispatch");
    expect(pane).toContain("Open case");
  });
});
