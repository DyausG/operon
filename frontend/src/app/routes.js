// Route table. Every page lives under /app; /login is the only public route.
export const ROUTES = {
  login: "/login",
  app: "/app",
  dashboard: "/app/dashboard",
  machines: "/app/machines",
  machine: (id) => `/app/machines/${encodeURIComponent(id)}`,
  incidents: "/app/incidents",
  incident: (id) => `/app/incidents/${encodeURIComponent(id)}`,
  agent: "/app/agent",
  maintenance: "/app/maintenance",
  analytics: "/app/analytics",
  activity: "/app/activity",
  notifications: "/app/notifications",
  profile: "/app/profile",
  settings: "/app/settings",
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
