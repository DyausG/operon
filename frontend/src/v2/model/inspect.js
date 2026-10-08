// The case inspector's URL state (F4.1): `?inspect=asset|identifiers|record|evidence|artifact:<id>`.
// It sits beside the section hash, so a deep link names both the section and what is inspected, and
// opening pushes a history entry so Back closes the inspector.
export const INSPECT_VIEWS = {
  asset: "Asset",
  identifiers: "Identifiers",
  record: "Full record",
  evidence: "All evidence",
};

/** { kind, id? } from the query value, or null for anything unrecognised. */
export function parseInspect(value) {
  const v = String(value || "");
  if (v.startsWith("artifact:")) {
    const id = v.slice("artifact:".length);
    return id ? { kind: "artifact", id } : null;
  }
  return Object.hasOwn(INSPECT_VIEWS, v) ? { kind: v } : null;
}

export const inspectValue = (target) => (target.kind === "artifact" ? `artifact:${target.id}` : target.kind);

/** A location for `target` that keeps every other query parameter and the hash. */
export function inspectHref({ pathname, search, hash }, target) {
  const params = new URLSearchParams(search || "");
  if (target) params.set("inspect", inspectValue(target));
  else params.delete("inspect");
  const q = params.toString();
  return `${pathname}${q ? `?${q}` : ""}${hash || ""}`;
}
