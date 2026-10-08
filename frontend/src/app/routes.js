// Route table for the legacy portal. Every legacy page lives under /legacy (the V2 workbench owns
// /app, 08 §2); /login is the only public route. Old /app/<page> URLs redirect here (App.jsx).
export const ROUTES = {
  login: "/login",
  app: "/legacy",
  dashboard: "/legacy/dashboard",
  machines: "/legacy/machines",
  machine: (id) => `/legacy/machines/${encodeURIComponent(id)}`,
  incidents: "/legacy/incidents",
  incident: (id) => `/legacy/incidents/${encodeURIComponent(id)}`,
  agent: "/legacy/agent",
  maintenance: "/legacy/maintenance",
  analytics: "/legacy/analytics",
  activity: "/legacy/activity",
  notifications: "/legacy/notifications",
  profile: "/legacy/profile",
  settings: "/legacy/settings",
};

/** Sidebar order. `badge` names a live counter computed in the shell. */
export const NAV = [
  { key: "dashboard", label: "Dashboard", to: ROUTES.dashboard, icon: "dashboard", group: "Operate" },
  { key: "machines", label: "Machines", to: ROUTES.machines, icon: "machines", group: "Operate" },
  { key: "incidents", label: "Incidents", to: ROUTES.incidents, icon: "incidents", group: "Operate", badge: "activeIncidents" },
  { key: "agent", label: "Operon Agent", to: ROUTES.agent, icon: "agent", group: "Operate", badge: "approvals" },
  { key: "maintenance", label: "Maintenance", to: ROUTES.maintenance, icon: "wrench", group: "Plan" },
  { key: "analytics", label: "Analytics", to: ROUTES.analytics, icon: "analytics", group: "Plan" },
  { key: "activity", label: "Activity", to: ROUTES.activity, icon: "activity", group: "Review" },
  { key: "notifications", label: "Notifications", to: ROUTES.notifications, icon: "bell", group: "Review", badge: "unread" },
];

export const ACCOUNT_NAV = [
  { key: "profile", label: "Profile", to: ROUTES.profile, icon: "user" },
  { key: "settings", label: "Settings", to: ROUTES.settings, icon: "settings" },
];

export const PAGE_TITLES = {
  dashboard: "Operations dashboard", machines: "Machines", incidents: "Incidents", agent: "Operon Agent",
  maintenance: "Maintenance", analytics: "Analytics", activity: "Activity", notifications: "Notifications",
  profile: "Profile", settings: "Settings",
};
