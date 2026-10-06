// V2 routes implemented in Phase 4A (08 §2). Other V2 routes follow in later slices; until then the
// rail links to the current pages, which stay reachable and unchanged (08 §11.4).
export const WB_ROUTES = {
  overview: "/app/overview",
  actions: "/app/actions",
  case: (id, section) => `/app/cases/${encodeURIComponent(id)}${section ? `#${section}` : ""}`,
  simulation: "/app/system/simulation",
  specimen: "/app/dev/specimen",
};
