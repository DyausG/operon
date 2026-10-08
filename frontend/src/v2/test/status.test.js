import { describe, expect, it } from "vitest";
import {
  attentionOf, conditionOf, expiryOf, provenanceOf, stageCompact, stageOf, waitingOn, withoutConfidence,
  aggregateConditions, PHASE_STAGE,
} from "../model/status.js";

const PHASES = ["OPEN", "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED", "PLANNING", "INTERVENTION_VALIDATED",
  "AWAITING_APPROVAL", "READY", "EXECUTING", "OBSERVING", "CLOSED", "ESCALATED", "EXECUTION_FAILED", "CANCELLED"];

describe("stage mapping (14 phases → 8 stages + exceptions)", () => {
  it("covers every backend phase", () => {
    expect(Object.keys(PHASE_STAGE).sort()).toEqual(PHASES.slice().sort());
    for (const p of PHASES) expect(stageOf(p)).toBeTruthy();
  });
  it.each([
    ["OPEN", "Detected · 1/8"], ["INVESTIGATING", "Investigating · 2/8"], ["AWAITING_EVIDENCE", "Awaiting inspection · 2/8"],
    ["DIAGNOSIS_VALIDATED", "Diagnosed · 3/8"], ["PLANNING", "Planning · 4/8"], ["INTERVENTION_VALIDATED", "Planning · 4/8"],
    ["AWAITING_APPROVAL", "Awaiting decision · 5/8"], ["READY", "In work · 6/8"], ["EXECUTING", "In work · 6/8"],
    ["OBSERVING", "Verifying · 7/8"], ["CLOSED", "Closed · 8/8"], ["ESCALATED", "Escalated"], ["EXECUTION_FAILED", "Dispatch failed"],
  ])("%s → %s", (phase, word) => expect(stageCompact(phase)).toBe(word));
  it("states an unknown phase in words, never a dash", () => expect(stageCompact("NOPE")).toBe("Stage not reported"));
});

describe("waiting-on and attention", () => {
  it.each([
    // F0 #19 (intentional F4.1 change): resource confirmation is a planning input, not an approval.
    ["INVESTIGATING", "analysis", false], ["AWAITING_EVIDENCE", "technician", true], ["DIAGNOSIS_VALIDATED", "planner", true],
    ["AWAITING_APPROVAL", "approver", true], ["EXECUTING", "dispatch", false], ["OBSERVING", "verification", false],
    ["ESCALATED", "reliability_engineer", true], ["EXECUTION_FAILED", "approver", true], ["CLOSED", "none", false],
  ])("%s waits on %s", (phase, key, human) => {
    expect(waitingOn(phase).key).toBe(key);
    expect(waitingOn(phase).human).toBe(human);
  });
  it("a person blocking is always Action required", () => {
    for (const p of ["AWAITING_APPROVAL", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED", "ESCALATED", "EXECUTION_FAILED"]) {
      expect(attentionOf({ phase: p, condition: "normal" })).toBe("action");
    }
  });
  it("critical condition in an automated stage is At risk; paused analysis too", () => {
    expect(attentionOf({ phase: "INVESTIGATING", condition: "critical" })).toBe("risk");
    expect(attentionOf({ phase: "INVESTIGATING", condition: "normal", analysisPaused: true })).toBe("risk");
    expect(attentionOf({ phase: "INVESTIGATING", condition: "normal" })).toBe("info");
  });
  it("verifying and elevated-without-case are Watch; regressed is At risk", () => {
    expect(attentionOf({ phase: "OBSERVING", condition: "normal" })).toBe("watch");
    expect(attentionOf({ phase: null, condition: "elevated" })).toBe("watch");
    expect(attentionOf({ phase: "OBSERVING", condition: "normal", outcomeResult: "REGRESSED" })).toBe("risk");
  });
  it("expired approvals stay Action required", () => expect(attentionOf({ phase: "AWAITING_APPROVAL", condition: "normal", expired: true })).toBe("action"));
});

describe("asset condition comes from the risk score only", () => {
  const th = { warn: 0.45, trigger: 0.8 };
  it("uses backend thresholds", () => {
    expect(conditionOf(0.02, th)).toBe("normal");
    expect(conditionOf(0.45, th)).toBe("elevated");
    expect(conditionOf(0.8, th)).toBe("critical");
  });
  it("never invents a threshold or a value", () => {
    expect(conditionOf(0.9, { warn: undefined, trigger: 0.8 })).toBe("unknown");
    expect(conditionOf(null, th)).toBe("unknown");
  });
  it("aggregates take the worst member", () => {
    const { worst, counts } = aggregateConditions(["normal", "elevated", "critical", "normal"]);
    expect(worst).toBe("critical");
    expect(counts).toEqual({ normal: 2, elevated: 1, critical: 1 });
  });
});

describe("approval expiry boundaries (08 §7)", () => {
  const now = Date.parse("2026-10-06T12:00:00Z");
  const at = (min) => new Date(now + min * 60000).toISOString();
  it.each([[61, "normal"], [60, "approaching"], [6, "approaching"], [5, "final"], [0.5, "final"], [0, "expired"], [-1, "expired"]])(
    "%s min left → %s", (min, state) => expect(expiryOf(at(min), now).state).toBe(state));
  it("backend EXPIRED wins over the clock", () => expect(expiryOf(at(120), now, "EXPIRED").state).toBe("expired"));
  it("no expires_at is unknown, never a guessed countdown", () => expect(expiryOf(null, now)).toEqual({ state: "unknown", remainingMs: null }));
});

describe("provenance mapping", () => {
  it("model signals are Model-generated although the backend says DERIVED", () => {
    expect(provenanceOf({ kind: "model_signal", provenance: "DERIVED" })).toBe("model");
    expect(provenanceOf({ kind: "health_score", provenance: "DERIVED" })).toBe("model");
  });
  it("simulated always wins; observed is measured", () => {
    expect(provenanceOf({ kind: "model_signal", provenance: "SIMULATED" })).toBe("simulated");
    expect(provenanceOf({ kind: "telemetry", provenance: "OBSERVED" })).toBe("measured");
    expect(provenanceOf({ kind: "asset_relation", provenance: "DERIVED" })).toBe("derived");
  });
});

describe("model self-reported confidence is never surfaced (PO-A)", () => {
  it("strips confidence and calibrated at any depth", () => {
    const out = withoutConfidence({ confidence: 0.72, calibrated: false, h: [{ mechanism: "x", confidence: 0.18, nested: { confidence: 1 } }] });
    expect(JSON.stringify(out)).not.toMatch(/confidence|calibrated/);
    expect(out.h[0].mechanism).toBe("x");
  });
});
