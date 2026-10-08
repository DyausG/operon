// Cases list (08 screen 4, today's variant): the cases the live stream carries, which is the latest
// case per asset (G5). Filters and sort live in the URL so Back and reload restore them; anything
// unrecognised in the URL falls back to the default instead of hiding cases.
import { EXCEPTIONS, ROLES, STAGES, TERMINAL, stageOf } from "./status.js";
import { compareCases } from "./cases.js";

export const STATUS_SEGMENTS = [
  { value: "active", label: "Active" },
  { value: "exceptions", label: "Exceptions" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

export const SORTS = [
  { value: "attention", label: "Attention, then deadline" },
  { value: "updated", label: "Last updated" },
  { value: "opened", label: "Opened" },
  { value: "asset", label: "Asset" },
];

/** Stage filter options: the eight stages, the inspection loop and the exits. */
export const STAGE_OPTIONS = [
  ...STAGES.map((s) => ({ value: s.key, label: s.label })),
  { value: "AWAITING_INSPECTION", label: "Awaiting inspection" },
  ...Object.values(EXCEPTIONS).map((s) => ({ value: s.key, label: s.label })),
];

export const WAITING_OPTIONS = Object.values(ROLES).map((r) => ({ value: r.key, label: r.label }));

const valid = (options, v, fallback) => (options.some((o) => o.value === v) ? v : fallback);

/** Normalised list state from URL search params. */
export function listState(params) {
  return {
    status: valid(STATUS_SEGMENTS, params.get("status"), "active"),
    stage: valid(STAGE_OPTIONS, params.get("stage"), ""),
    waiting: valid(WAITING_OPTIONS, params.get("waiting"), ""),
    q: (params.get("q") || "").slice(0, 80),
    sort: valid(SORTS, params.get("sort"), "attention"),
  };
}

export const isResolved = (c) => TERMINAL.has(c.phase);

/** Needs recovery: an exit stage, a suspended analysis, or an approval that can't be decided. */
export function isException(c) {
  if (isResolved(c)) return false;
  return !!stageOf(c.phase)?.exception || !!c.suspension || c.approval?.state === "expired" || c.approval?.state === "invalidated";
}

export function statusCounts(cases) {
  return {
    active: cases.filter((c) => !isResolved(c)).length,
    exceptions: cases.filter(isException).length,
    resolved: cases.filter(isResolved).length,
    all: cases.length,
  };
}

/** Why a case is an exception, in a few words (for the stage column). */
export function exceptionWords(c) {
  if (c.suspension) return "analysis suspended";
  if (c.approval?.state === "expired") return "approval expired";
  if (c.approval?.state === "invalidated") return "plan invalidated";
  if (c.phase === "EXECUTION_FAILED" && c.alert?.lifecycle?.reconciliation_required) return "outcome unknown";
  return null;
}

const by = (key) => (a, b) => String(b[key] || "").localeCompare(String(a[key] || ""));

export function filterCases(cases, { status, stage, waiting, q }) {
  const needle = q.trim().toLowerCase();
  return cases.filter((c) => {
    if (status === "active" && isResolved(c)) return false;
    if (status === "exceptions" && !isException(c)) return false;
    if (status === "resolved" && !isResolved(c)) return false;
    if (stage && stageOf(c.phase)?.key !== stage) return false;
    if (waiting && c.waiting?.key !== waiting) return false;
    if (needle && !`${c.assetId} ${c.assetName || ""} ${c.ref || ""}`.toLowerCase().includes(needle)) return false;
    return true;
  });
}

export function sortCases(cases, sort) {
  const list = cases.slice();
  if (sort === "updated") return list.sort(by("updatedAt"));
  if (sort === "opened") return list.sort(by("openedAt"));
  if (sort === "asset") return list.sort((a, b) => String(a.assetId).localeCompare(String(b.assetId)));
  return list.sort(compareCases);
}
