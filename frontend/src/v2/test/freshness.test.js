import { describe, expect, it } from "vitest";
import { assetLag, classifyStream, expectedInterval, segmentsOf } from "../model/freshness.js";
import { when } from "../model/format.js";

describe("X8 fallback: expected interval from receipt times", () => {
  it("is unknown until two arrivals", () => {
    expect(expectedInterval([])).toBeNull();
    expect(expectedInterval([1000])).toBeNull();
  });
  it("is the median gap over the last 10 ticks, robust to one slow tick", () => {
    const arrivals = [0, 1000, 2000, 3000, 9000, 10000, 11000];
    expect(expectedInterval(arrivals)).toBe(1000);
  });
  it("only looks at the last 10 gaps", () => {
    const old = Array.from({ length: 20 }, (_, i) => i * 5000);
    const recent = Array.from({ length: 11 }, (_, i) => 100000 + i * 1000);
    expect(expectedInterval(old.concat(recent))).toBe(1000);
  });
});

describe("stream freshness states (07 §15.1)", () => {
  const base = { connected: true, running: true, lastReceipt: 10000, interval: 1000 };
  it.each([[11000, "live"], [12000, "live"], [12001, "delayed"], [15000, "delayed"], [15001, "stale"]])(
    "now=%s → %s", (now, state) => expect(classifyStream({ ...base, now }).state).toBe(state));
  it("disconnected outranks everything", () => expect(classifyStream({ ...base, connected: false, now: 10500 }).state).toBe("disconnected"));
  it("a paused engine is not Live", () => expect(classifyStream({ ...base, running: false, now: 10100 }).state).toBe("paused"));
  it("can't claim Live before the interval is measured", () => expect(classifyStream({ ...base, interval: null, now: 10100 }).state).toBe("measuring"));
  it("no data yet is stated", () => expect(classifyStream({ ...base, lastReceipt: null, now: 1 }).state).toBe("waiting"));
});

describe("per-asset staleness and the gap rule", () => {
  it("counts ticks behind the latest tick", () => {
    expect(assetLag([{ t: 100 }], 104)).toEqual({ lastTick: 100, behind: 4, stale: false });
    expect(assetLag([{ t: 100 }], 106).stale).toBe(true);
    expect(assetLag([], 10).stale).toBe(true);
  });
  it("breaks the series at missing tick indices and never interpolates", () => {
    const { segments, gaps } = segmentsOf([{ t: 1 }, { t: 2 }, { t: 5 }, { t: 6 }]);
    expect(segments.map((s) => s.map((p) => p.t))).toEqual([[1, 2], [5, 6]]);
    expect(gaps).toEqual([{ from: 2, to: 5 }]);
  });
});

describe("times never lose their date", () => {
  it("shows a bare time only for today", () => {
    const now = new Date(2026, 9, 6, 15, 0, 0);
    expect(when(new Date(2026, 9, 6, 13, 50, 7), { seconds: true, now })).toBe("13:50:07");
    expect(when(new Date(2026, 9, 7, 13, 50), { now })).toBe("07 Oct 13:50");
    expect(when(new Date(2026, 7, 18, 14, 0), { now })).toBe("18 Aug 14:00");
  });
});
