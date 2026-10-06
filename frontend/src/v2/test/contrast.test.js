// Token contrast check (08 §11.3 gate check 1): parses the shipped tokens.css and asserts the
// reconciled 07 §4 ratios for both themes, including the Phase 4A starting values.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");

function theme(name) {
  const block = css.split(`.wb-root[data-theme="${name}"]`)[1].split("}")[0];
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((m) => [m[1], m[2].toUpperCase()]));
}

function lum(hex) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function ratio(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const LIGHT = theme("light");
const DARK = theme("dark");

describe("Phase 4A starting values are shipped exactly (R-9, R-25, CH-1, R-24)", () => {
  it("light", () => {
    expect(LIGHT["color-surface-base"]).toBe("#F1F0EC");
    expect(LIGHT["color-surface-sheet"]).toBe("#FAFAF8");
    expect(LIGHT["color-status-decision-fg"]).toBe("#674EB0");
    expect(LIGHT["color-action-danger-fg"]).toBe("#C42B3A");
  });
  it("dark", () => {
    expect(DARK["color-surface-sheet"]).toBe("#1A1F21");
    expect(DARK["color-text-primary"]).toBe("#DDE2E4");
    expect(DARK["color-surface-hover"]).toBe("#202527");
    expect(DARK["color-surface-overlay"]).toBe("#202527");
    expect(DARK["color-surface-raised"]).toBe("#1F2426");
    expect(DARK["color-surface-selected"]).toBe("#282D2F");
    expect(DARK["color-status-decision-fg"]).toBe("#AA95E8");
    expect(DARK["color-action-danger-fg"]).toBe("#F0564B");
  });
  it("action.danger is its own token, not a reference to a status token", () => {
    expect(css).not.toMatch(/--color-action-danger-fg:\s*var\(--color-status/);
  });
});

// [token, surface, expected ratio from 07 §4, minimum]
const PAIRS = {
  light: [
    ["color-text-primary", "color-surface-base", 16.31, 4.5], ["color-text-primary", "color-surface-sheet", 17.80, 4.5],
    ["color-text-primary", "color-surface-raised", 18.60, 4.5], ["color-text-secondary", "color-surface-base", 7.09, 4.5],
    ["color-text-tertiary", "color-surface-base", 5.13, 4.5], ["color-text-tertiary", "color-surface-sheet", 5.60, 4.5],
    ["color-text-tertiary", "color-surface-raised", 5.85, 4.5], ["color-border-control", "color-surface-base", 3.38, 3],
    ["color-border-control", "color-surface-sheet", 3.69, 3], ["color-border-control", "color-surface-raised", 3.85, 3],
    ["color-status-critical-fg", "color-surface-sheet", 5.35, 4.5], ["color-status-warning-fg", "color-surface-sheet", 5.85, 4.5],
    ["color-status-warning-fg", "color-surface-base", 5.36, 4.5], ["color-status-decision-fg", "color-surface-sheet", 6.10, 4.5],
    ["color-status-verified-fg", "color-surface-sheet", 5.10, 4.5], ["color-action-danger-fg", "color-surface-raised", null, 4.5],
    ["color-text-tertiary", "color-surface-hover", null, 4.5],
  ],
  dark: [
    ["color-text-primary", "color-surface-base", 14.21, 4.5], ["color-text-primary", "color-surface-sheet", 12.74, 4.5],
    ["color-text-primary", "color-surface-raised", 12.01, 4.5], ["color-text-secondary", "color-surface-sheet", 8.64, 4.5],
    ["color-text-tertiary", "color-surface-base", 5.50, 4.5], ["color-text-tertiary", "color-surface-sheet", 4.93, 4.5],
    ["color-text-tertiary", "color-surface-raised", 4.65, 4.5], ["color-text-tertiary", "color-surface-hover", 4.59, 4.5],
    ["color-text-secondary", "color-surface-selected", 7.24, 4.5], ["color-border-control", "color-surface-base", 3.79, 3],
    ["color-border-control", "color-surface-sheet", 3.40, 3], ["color-border-control", "color-surface-raised", 3.20, 3],
    ["color-status-critical-fg", "color-surface-sheet", 4.86, 4.5], ["color-status-warning-fg", "color-surface-sheet", 8.20, 4.5],
    ["color-status-decision-fg", "color-surface-sheet", 6.48, 4.5], ["color-status-verified-fg", "color-surface-sheet", 6.66, 4.5],
    ["color-action-danger-fg", "color-surface-raised", null, 4.5],
  ],
};

describe.each([["light", LIGHT], ["dark", DARK]])("%s theme contrast (WCAG 2.x)", (name, t) => {
  it.each(PAIRS[name])("%s on %s", (fg, bg, expected, min) => {
    const r = ratio(t[fg], t[bg]);
    expect(r).toBeGreaterThanOrEqual(min);
    if (expected) expect(Math.abs(r - expected)).toBeLessThan(0.02);
  });
  it("primary text reaches AAA (≥ 7:1) on every surface", () => {
    for (const s of ["base", "sheet", "sunken", "raised", "overlay", "hover", "selected"]) {
      expect(ratio(t["color-text-primary"], t[`color-surface-${s}`])).toBeGreaterThanOrEqual(7);
    }
  });
  // 07 §17 claims ≥ 11.8:1 "on every surface". Measured: true for the content surfaces below; the
  // dark selected-row surface (#282D2F) measures 10.67:1 (still AAA). Reported as a Phase 4A finding.
  it("07 §17's ≥ 11.8:1 holds on the content surfaces", () => {
    for (const s of ["base", "sheet", "sunken", "raised", "overlay"]) {
      expect(ratio(t["color-text-primary"], t[`color-surface-${s}`])).toBeGreaterThanOrEqual(11.8);
    }
  });
  it("focus ring is ≥ 3:1 against the sheet", () => expect(ratio(t["color-border-focus"], t["color-surface-sheet"])).toBeGreaterThanOrEqual(3));
});
