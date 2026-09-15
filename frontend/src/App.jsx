// Root: providers + router. Engine state is mirrored once; pages read it through context.
import { BrowserRouter, MemoryRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { EngineProvider } from "./state/engine.jsx";
import { SessionProvider, useSession } from "./state/session.jsx";
import { ThemeProvider } from "./state/theme.jsx";
import { SettingsProvider } from "./state/settings.jsx";
import { NotificationsProvider } from "./state/notifications.jsx";
import { AppShell } from "./app/AppShell.jsx";
import { ROUTES } from "./app/routes.js";
import { LoginPage } from "./pages/LoginPage.jsx";
import { DashboardPage } from "./pages/DashboardPage.jsx";
import { MachinesPage } from "./pages/MachinesPage.jsx";
import { MachineDetailPage } from "./pages/MachineDetailPage.jsx";
import { IncidentsPage } from "./pages/IncidentsPage.jsx";
import { IncidentDetailPage } from "./pages/IncidentDetailPage.jsx";
import { AgentPage } from "./pages/AgentPage.jsx";
import { MaintenancePage } from "./pages/MaintenancePage.jsx";
import { AnalyticsPage } from "./pages/AnalyticsPage.jsx";
import { ActivityPage } from "./pages/ActivityPage.jsx";
import { NotificationsPage } from "./pages/NotificationsPage.jsx";
import { ProfilePage } from "./pages/ProfilePage.jsx";
import { SettingsPage } from "./pages/SettingsPage.jsx";

function RequireAuth({ children }) {
  const { signedIn } = useSession();
  const location = useLocation();
  if (!signedIn) return <Navigate to={ROUTES.login} replace state={{ from: location.pathname + location.search + location.hash }} />;
  return children;
}

export function Providers({ engine, session, settings, theme, children }) {
  return (
    <ThemeProvider initialMode={theme}>
      <SettingsProvider initialSettings={settings}>
        <SessionProvider initialSession={session}>
          <EngineProvider engine={engine}>
            <NotificationsProvider>{children}</NotificationsProvider>
          </EngineProvider>
        </SessionProvider>
      </SettingsProvider>
    </ThemeProvider>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path={ROUTES.login} element={<LoginPage />} />
      <Route path={ROUTES.app} element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<Navigate to={ROUTES.dashboard} replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="machines" element={<MachinesPage />} />
        <Route path="machines/:id" element={<MachineDetailPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:id" element={<IncidentDetailPage />} />
        <Route path="agent" element={<AgentPage />} />
        <Route path="maintenance" element={<MaintenancePage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to={ROUTES.dashboard} replace />} />
      </Route>
      <Route path="*" element={<Navigate to={ROUTES.dashboard} replace />} />
    </Routes>
  );
}

/** Browser entry. `engine` lets a harness inject a pre-built engine; `router="memory"` with
 *  `initialEntries` renders a route without a DOM history (server-side smoke test). */
export default function App({ engine, session, settings, theme, router = "browser", initialEntries }) {
  const tree = <Providers engine={engine} session={session} settings={settings} theme={theme}><AppRoutes /></Providers>;
  if (router === "memory") return <MemoryRouter initialEntries={initialEntries || [ROUTES.dashboard]}>{tree}</MemoryRouter>;
  return <BrowserRouter>{tree}</BrowserRouter>;
}
