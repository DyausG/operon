// F1.1 behaviour as the V2 workbench shows it, over frames the real engine produced
// (test/make_fixtures.py): a rejection returns the case to planning, MATERIAL uncertainty reaches the
// approver as a condition, BLOCKING uncertainty refuses promotion and the case stays parked, and
// hypotheses are durable records. The first block guards the fixtures themselves against going stale.
//
// Not covered here because V2 has no consumer yet (documented, not manufactured): `environment`,
// `analysis` (retry/suspension) and `work` (assignment facts) on the alert lifecycle, and hypothesis
// references (HYP-00n). They are asserted as data below so a later UI slice starts from real frames.
import { readFileSync } from "node:fs";
import { renderToString } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../App.jsx";
import { applySnapshot, initialState } from "../../state/engineState.js";
import { pendingRequirement } from "../model/cases.js";
import { WB_ROUTES } from "../shell/routes.js";
import { fixtureNow } from "../../../test/fixture-era.js";

const raw = (name) => readFileSync(new URL(`../../../test/fixtures/${name}`, import.meta.url), "utf8");
const load = (name) => JSON.parse(raw(name));
const FRAMES = load("demo-frames.json");
const [AWAITING, REJECTED] = load("demo-frames-reject.json");
const [MATERIAL] = load("demo-frames-material.json");
const [BLOCKING] = load("demo-frames-blocking.json");
const MATERIAL_TEXT = "Fixture: maintenance history before the last service is incomplete";
const BLOCKING_TEXT = "Fixture: shaft condition has not been inspected";

const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-10-08T21:00:00Z", mode: "demo" };
const noop = () => Promise.resolve({ ok: true });
const ACTIONS = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };

const lifecycle = (frame) => frame.alerts?.[0]?.lifecycle;
const incident = (frame) => frame.alerts[0].incident_id;
const render = (path, frame) => renderToString(
  <App engine={{ state: applySnapshot(initialState, frame), ...ACTIONS }} session={SESSION} settings={null} theme="light" router="memory" initialEntries={[path]} />);
const text = (html) => html.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const casePage = (frame) => render(WB_ROUTES.case(incident(frame)), frame);
const currentStage = (html) => text(/<li[^>]*aria-current="step"[^>]*>(.*?)<\/li>/s.exec(html)?.[1] || "").trim();
const decisionSurface = (html) => html.split('id="decision-surface"')[1]?.split("</section>")[0] ?? null;
const myActionCount = (html) => Number(/class="wb-nav-count" aria-label="(\d+) require action"/.exec(html)?.[1] || 0);

beforeAll(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(fixtureNow(FRAMES)); });
afterAll(() => vi.useRealTimers());

describe("fixtures reflect the F1.1 contract (regenerate with test/make_fixtures.py)", () => {
  it.each(["demo-frames.json", "demo-frames-reject.json", "demo-frames-material.json", "demo-frames-blocking.json", "demo-artifacts.json"])(
    "%s carries no retired mechanism-text verdict check", (name) => {
      expect(raw(name)).not.toContain("trusted_mechanism_match");
    });

  it("promotion is recorded by durable hypothesis identity", () => {
    expect(raw("demo-frames.json")).toContain("trusted_hypothesis_identity");
  });

  it("the approved Guided Demo walks the full lifecycle", () => {
    expect(FRAMES.map((f) => f.demo_scenario.status)).toEqual([
      "factory_healthy", "degrading", "investigating", "awaiting_evidence", "diagnosis_validated",
      "awaiting_human_approval", "observing", "complete"]);
  });

  it("every case frame carries the F1.1 lifecycle fields", () => {
    const cases = [...FRAMES, AWAITING, REJECTED, MATERIAL, BLOCKING].filter(lifecycle);
    expect(cases.length).toBeGreaterThan(5);
    for (const frame of cases) {
      const lc = lifecycle(frame);
      for (const key of ["environment", "analysis", "hypotheses", "work", "material_uncertainties"]) expect(lc).toHaveProperty(key);
      expect(lc.environment).toBe("UNSPECIFIED");
    }
  });

  it("hypotheses are durable references once registered", () => {
    const parked = FRAMES.find((f) => lifecycle(f)?.phase === "AWAITING_EVIDENCE");
    expect(lifecycle(parked).hypotheses.map((h) => h.reference)).toEqual(["HYP-001", "HYP-002"]);
  });

  it("dispatch records an assigned work fact; nothing is reported, so it is not recovery", () => {
    const observing = FRAMES.find((f) => lifecycle(f)?.phase === "OBSERVING");
    expect(lifecycle(observing).work.map((w) => [w.state, w.assignee.kind])).toEqual([["ASSIGNED", "WORKER"]]);
    const events = lifecycle(FRAMES.at(-1)).read_model.events.map((e) => e.event_type);
    expect(events).toContain("WORK_ASSIGNED");
    expect(events).not.toContain("WORK_REPORTED");
  });

  it("a recorded rejection returns the case to PLANNING and consumes the intervention", () => {
    const lc = lifecycle(REJECTED);
    expect([lc.phase, lc.intervention_id, lc.requirement_id]).toEqual(["PLANNING", null, null]);
    const recorded = lc.read_model.events.filter((e) => e.event_type === "APPROVAL_RECORDED").at(-1).payload;
    expect(recorded).toMatchObject({ decision: "REJECT", return_to: "PLANNING", actor_kind: "DECLARED" });
    const phaseChanges = lc.read_model.events.filter((e) => e.event_type === "PHASE_CHANGED").map((e) => e.payload?.to);
    expect(phaseChanges.at(-1)).toBe("PLANNING");
    expect(phaseChanges).not.toContain("ESCALATED");
  });

  it("MATERIAL uncertainty promotes and is bound to the approval requirement", () => {
    const requirement = pendingRequirement(MATERIAL.alerts[0]);
    expect(requirement.material_uncertainties.map((u) => [u.statement, u.severity, u.source_role])).toEqual([[MATERIAL_TEXT, "MATERIAL", "diagnostic"]]);
    expect(requirement.conditions).toContain(`MATERIAL uncertainty (diagnostic): ${MATERIAL_TEXT}`);
  });

  it("BLOCKING uncertainty refuses promotion and leaves the case parked with the reason recorded", () => {
    const lc = lifecycle(BLOCKING);
    expect([lc.phase, lc.requirement_id, lc.read_model.diagnosis]).toEqual(["AWAITING_EVIDENCE", null, null]);
    const parked = lc.read_model.events.filter((e) => e.event_type === "PHASE_CHANGED").at(-1).payload;
    expect(parked).toMatchObject({ to: "AWAITING_EVIDENCE", reason: `blocking uncertainty remains: ${BLOCKING_TEXT}` });
  });
});

describe("the V2 workbench shows F1.1 behaviour", () => {
  it("after a recorded rejection the case is in Planning, waiting on analysis, with no decision offered", () => {
    const html = casePage(REJECTED);
    const page = text(html);
    expect(currentStage(html)).toBe("Planning (current)");
    expect(page).toContain("Stage Planning · 4/8");
    expect(page).toContain("Waiting on Analysis (automated)");
    expect(page).toContain("Stage: Awaiting decision → Planning");
    expect(page).toContain("Rejected by dashboard-operator");
    expect(decisionSurface(html)).toBeNull();
    expect(page).not.toMatch(/Decision required|Approve and dispatch|Escalated \(current\)/);
  });

  it("the approver's queue holds the case while approval is pending and releases it after the rejection", () => {
    expect(myActionCount(render(WB_ROUTES.actions, AWAITING))).toBe(1);
    expect(myActionCount(render(WB_ROUTES.actions, REJECTED))).toBe(0);
  });

  it("MATERIAL uncertainty is listed as a condition on the decision, and approval stays available", () => {
    const decision = decisionSurface(casePage(MATERIAL));
    expect(decision).not.toBeNull();
    expect(text(decision)).toContain(`Conditions`);
    expect(text(decision)).toContain(`MATERIAL uncertainty (diagnostic): ${MATERIAL_TEXT}`);
    expect(decision).toMatch(/<button(?![^>]*aria-disabled)[^>]*>(?:(?!<\/button>).)*Approve and dispatch/s);
    // A decision without material uncertainty lists none.
    expect(text(decisionSurface(casePage(AWAITING)))).not.toContain("MATERIAL uncertainty");
  });

  it("BLOCKING uncertainty: no decision is offered, the case waits on a technician and the record says why", () => {
    const html = casePage(BLOCKING);
    const page = text(html);
    expect(page).toContain("Stage Awaiting inspection · 2/8");
    expect(page).toContain("Waiting on Technician");
    expect(page).toContain(`blocking uncertainty remains: ${BLOCKING_TEXT}`);
    expect(decisionSurface(html)).toBeNull();
    expect(page).not.toMatch(/Decision required|Approve and dispatch/);
    expect(myActionCount(render(WB_ROUTES.actions, BLOCKING))).toBe(0);
  });

  it("durable hypotheses are shown as recorded, not as run proposals", () => {
    const parked = FRAMES.find((f) => lifecycle(f)?.phase === "AWAITING_EVIDENCE");
    const page = text(casePage(parked));
    expect(page).toContain("basis: Advisory suggestion registered for durable identity; not validated");
    expect(page).not.toContain("not yet recorded as a hypothesis");
  });

  it.each([["rejected", REJECTED], ["material", MATERIAL], ["blocking", BLOCKING]])("the %s case renders inside the V2 shell", (_name, frame) => {
    const html = casePage(frame);
    expect(html).toContain('class="wb-root"');
    expect(html).not.toContain('class="app ');
  });
});
