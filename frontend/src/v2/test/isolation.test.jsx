// V2 / legacy isolation: the workbench owns /app, the legacy portal owns /legacy, and neither renders
// inside the other's shell. Every link the workbench renders stays in /app (or is an in-page anchor),
// except explicit legacy exits, which carry `data-legacy-exit` and name the legacy portal.
import { readFileSync } from "node:fs";
import { renderToString } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../App.jsx";
import { applySnapshot, initialState } from "../../state/engineState.js";
import { LEGACY_SEGMENTS, WB_PLANNED, WB_ROUTES, legacyCompatTarget } from "../shell/routes.js";
import { fixtureNow } from "../../../test/fixture-era.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../../../test/fixtures/${name}`, import.meta.url), "utf8"));
const FRAMES = [...load("demo-frames.json"), ...load("demo-frames-reject.json"),
  ...load("demo-frames-material.json"), ...load("demo-frames-blocking.json")];
const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-09-15T18:40:00Z", mode: "demo" };
const noop = () => Promise.resolve({ ok: true });
const ACTIONS = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };

const render = (path, state, session = SESSION) =>
  renderToString(<App engine={{ state, ...ACTIONS }} session={session} settings={null} theme="light" router="memory" initialEntries={[path]} />);
const isV2 = (html) => html.includes('class="wb-root"') && !html.includes('class="app ');
const isLegacy = (html) => html.includes('class="app ') && !html.includes('class="wb-root"');
const anchors = (html) => [...html.matchAll(/<a\s[^>]*>/g)].map(([tag]) => ({
  tag, href: /\shref="([^"]*)"/.exec(tag)?.[1] ?? null, exit: /\sdata-legacy-exit=""/.test(tag),
}));

const states = (() => { let st = initialState; return FRAMES.map((f) => (st = applySnapshot(st, f))); })();
const finalState = states[states.length - 1];
const withCase = states.find((s) => Object.values(s.alerts || {}).length) || finalState;
const incidentId = Object.values(withCase.alerts)[0]?.incident_id || "DEMO-INCIDENT-01";

const planned = WB_PLANNED.map((p) => `/app/${p.path.replace(":equipmentId", "AC-COMP-01").replace(":section", "analysis")}`);
const V2_PATHS = [WB_ROUTES.overview, WB_ROUTES.actions, WB_ROUTES.simulation, WB_ROUTES.case(incidentId), `${WB_ROUTES.actions}?preview=${incidentId}`, ...planned, "/app/not-a-page", "/app/cases/x/y/z"];
const LEGACY_PATHS = ["/legacy/dashboard", "/legacy/machines", "/legacy/machines/AC-COMP-01", "/legacy/incidents", `/legacy/incidents/${incidentId}`,
  `/legacy/agent?incident=${incidentId}`, "/legacy/maintenance", "/legacy/analytics", "/legacy/activity", "/legacy/notifications", "/legacy/profile", "/legacy/settings"];

beforeAll(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(fixtureNow(FRAMES)); });
afterAll(() => vi.useRealTimers());

describe("route ownership", () => {
  it.each(V2_PATHS)("%s renders only the V2 shell", (path) => {
    expect(isV2(render(path, withCase))).toBe(true);
  });

  it.each(LEGACY_PATHS)("%s renders only the legacy shell", (path) => {
    expect(isLegacy(render(path, withCase))).toBe(true);
  });

  it.each(WB_PLANNED.map((p) => [p.path, p]))("planned %s says it is not available and never shows legacy content", (_p, p) => {
    const path = `/app/${p.path.replace(":equipmentId", "AC-COMP-01").replace(":section", "analysis")}`;
    const html = render(path, withCase);
    expect(html).toContain(`<h1 class="wb-page-title">${p.label}</h1>`);
    expect(html).toContain("available in this version of the workbench yet");
  });

  it("the audit is not vacuous: placeholders and the case expose their exits and in-shell links", () => {
    const cases = anchors(render(WB_ROUTES.cases, withCase));
    expect(cases.filter((a) => a.exit).map((a) => a.href)).toEqual(["/legacy/incidents"]);
    expect(cases.some((a) => a.href === WB_ROUTES.cases && !a.exit)).toBe(true); // the rail item
    const kase = anchors(render(WB_ROUTES.case(incidentId), withCase));
    // F4.1 layout D: the PRISM legacy exit lives in the Investigation section.
    const investigation = anchors(render(WB_ROUTES.case(incidentId, "investigation"), withCase));
    expect(investigation.some((a) => a.exit && a.href.startsWith("/legacy/agent?incident="))).toBe(true);
    expect(kase.some((a) => a.href === WB_ROUTES.cases && !a.exit)).toBe(true); // breadcrumb + rail
    expect(kase.some((a) => a.href === WB_ROUTES.updates)).toBe(true);
  });

  it("an unknown /app path is a V2 not-found page, not the legacy dashboard", () => {
    const html = render("/app/not-a-page", withCase);
    expect(html).toContain("Page not found");
    expect(html).not.toContain("Operations dashboard");
  });

  it.each(["/app/overview", "/app/cases", "/legacy/dashboard"])("signed out, %s renders neither shell (client redirect to /login)", (path) => {
    const html = render(path, finalState, null);
    expect(html).not.toContain('class="wb-root"');
    expect(html).not.toContain('class="app ');
  });

  it.each(LEGACY_SEGMENTS.map((s) => `/app/${s}`))("old %s renders neither shell (it redirects to /legacy)", (path) => {
    const html = render(path, withCase);
    expect(html).not.toContain('class="wb-root"');
    expect(html).not.toContain('class="app ');
  });
});

describe.each(states.map((s, i) => [i, s]))("link audit, frame %i", (_i, state) => {
  const id = Object.values(state.alerts || {})[0]?.incident_id;
  const paths = [WB_ROUTES.overview, WB_ROUTES.actions, WB_ROUTES.simulation, ...planned, "/app/not-a-page"];
  // F4.1 layout D renders one case section at a time: audit every section, not just Now.
  if (id) paths.push(WB_ROUTES.case(id), ...["evidence", "investigation", "decision", "work", "record"].map((s) => WB_ROUTES.case(id, s)), `${WB_ROUTES.actions}?preview=${id}`);

  it.each(paths)("every link on %s stays in the workbench or is an explicit legacy exit", (path) => {
    for (const a of anchors(render(path, state))) {
      if (a.exit) {
        expect(a.href, a.tag).toMatch(/^\/legacy\//);
      } else {
        expect(a.href, a.tag).toMatch(/^(\/app\/|#)/);
      }
    }
  });

  it.each(paths)("every legacy exit on %s names the legacy portal", (path) => {
    const html = render(path, state);
    for (const m of html.matchAll(/<a\s[^>]*data-legacy-exit=""[^>]*>(.*?)<\/a>/gs)) expect(m[1]).toContain("legacy portal");
  });
});

describe("legacy links stay in the legacy portal", () => {
  it.each(LEGACY_PATHS)("%s links only to /legacy, /login, anchors or external pages", (path) => {
    for (const a of anchors(render(path, withCase))) {
      if (a.href === null) continue;
      expect(a.href, a.tag).toMatch(/^(\/legacy\/|\/login$|#|https?:)/);
    }
  });
});

describe("legacyCompatTarget", () => {
  it.each(LEGACY_SEGMENTS)("/app/%s moves to /legacy/%s", (seg) => {
    expect(legacyCompatTarget({ pathname: `/app/${seg}` })).toBe(`/legacy/${seg}`);
  });

  it("keeps sub-paths, encoded ids, query strings and hashes", () => {
    expect(legacyCompatTarget({ pathname: "/app/incidents/INC%2F7", search: "?tab=record", hash: "#artifact=a%201" }))
      .toBe("/legacy/incidents/INC%2F7?tab=record#artifact=a%201");
    expect(legacyCompatTarget({ pathname: "/app/agent", search: `?incident=${incidentId}` })).toBe(`/legacy/agent?incident=${incidentId}`);
    expect(legacyCompatTarget({ pathname: "/app/settings", hash: "#plant" })).toBe("/legacy/settings#plant");
  });

  it("matches segments case-insensitively, as the router does, and keeps the id's case", () => {
    expect(legacyCompatTarget({ pathname: "/app/Dashboard" })).toBe("/legacy/dashboard");
    expect(legacyCompatTarget({ pathname: "/app/INCIDENTS/Inc-7", search: "?A=1" })).toBe("/legacy/incidents/Inc-7?A=1");
  });

  it.each(["/app/overview", "/app/actions", "/app/cases", "/app/cases/X", "/app/assets", "/app/system/simulation", "/app", "/app/", "/legacy/dashboard", "/"])(
    "%s is not a legacy URL", (pathname) => {
      expect(legacyCompatTarget({ pathname })).toBeNull();
    });

  it("no planned V2 segment collides with a legacy segment", () => {
    for (const p of WB_PLANNED) expect(LEGACY_SEGMENTS).not.toContain(p.path.split("/")[0]);
  });
});
