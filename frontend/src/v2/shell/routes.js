// V2 routes (08 §2). The workbench owns /app; the legacy portal lives under /legacy and is never
// reached by falling through a V2 route. Destinations not yet built render a V2 placeholder
// (screens/Planned.jsx) at their planned path, never a legacy page.
export const WB_ROUTES = {
  overview: "/app/overview",
  actions: "/app/actions",
  cases: "/app/cases",
  case: (id, section) => `/app/cases/${encodeURIComponent(id)}${section ? `#${section}` : ""}`,
  assets: "/app/assets",
  workOrders: "/app/work-orders",
  reliability: "/app/reliability",
  audit: "/app/audit",
  system: "/app/system",
  simulation: "/app/system/simulation",
  updates: "/app/updates",
  preferences: "/app/preferences",
  specimen: "/app/dev/specimen",
};

/** Planned V2 destinations without a screen yet (08 §2, §9). `legacy` names the current page an
 *  explicit, labelled link may open in the legacy portal. */
export const WB_PLANNED = [
  { path: "assets", label: "Assets", legacy: { to: "/legacy/machines", label: "Machines" } },
  { path: "assets/:equipmentId", label: "Asset", legacy: { to: "/legacy/machines", label: "Machines" } },
  { path: "work-orders", label: "Work orders", legacy: { to: "/legacy/maintenance", label: "Maintenance" } },
  { path: "reliability", label: "Reliability", legacy: { to: "/legacy/analytics", label: "Analytics" } },
  { path: "audit", label: "Audit log", legacy: { to: "/legacy/activity", label: "Activity" } },
  { path: "system", label: "System", legacy: { to: "/legacy/settings", label: "Settings" } },
  { path: "system/:section", label: "System", legacy: { to: "/legacy/settings", label: "Settings" } },
  { path: "updates", label: "Updates", legacy: { to: "/legacy/notifications", label: "Notifications" } },
  { path: "preferences", label: "Preferences", legacy: { to: "/legacy/profile", label: "Profile" } },
];

/** Legacy page segments that used to live under /app. Old URLs keep working: /app/<segment>/…
 *  redirects to /legacy/<segment>/… with query and hash intact. When a later slice retires a
 *  legacy page (08 §9), its redirect moves to the V2 replacement here. */
export const LEGACY_SEGMENTS = [
  "dashboard", "machines", "incidents", "agent", "maintenance", "analytics",
  "activity", "notifications", "profile", "settings",
];

/** Where an old /app/<legacy segment> URL now lives, or null when the path is not a legacy one. */
export function legacyCompatTarget({ pathname = "", search = "", hash = "" }) {
  const m = /^\/app\/([^/?#]+)(\/.*)?$/.exec(pathname);
  const segment = m?.[1].toLowerCase(); // route matching is case-insensitive; so is this
  if (!m || !LEGACY_SEGMENTS.includes(segment)) return null;
  return `/legacy/${segment}${m[2] || ""}${search}${hash}`;
}
