// V2 application shell (08 §3): 48 px header (name text, plant, system status, updates, account),
// nav rail (Operate / Review, System at the foot), one working sheet that owns its scroll.
// Engine, Guided Demo and simulator controls are NOT in the header: they live in
// System → Simulation & Demo (/app/system/simulation). No global search (07 §22).
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  IconAdjustments, IconBell, IconBuildingFactory2, IconChartLine, IconChecklist, IconChevronDown,
  IconFolders, IconHistory, IconLayoutDashboard, IconLayoutSidebarLeftCollapse, IconLayoutSidebarLeftExpand, IconTool,
} from "@tabler/icons-react";
import { useSession, ROLES as SESSION_ROLES } from "../../state/session.jsx";
import { WbThemeProvider, useWbTheme } from "../theme.jsx";
import { WbProvider, useWb } from "./WbContext.jsx";
import { FreshnessIndicator, Icon, Segmented } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { useMedia } from "../components/Overlay.jsx";
import { clock } from "../model/format.js";
import { ROLES } from "../model/status.js";
import { WB_ROUTES } from "./routes.js";

const NAV = [
  { group: "Operate", items: [
    { key: "overview", label: "Overview", to: WB_ROUTES.overview, icon: IconLayoutDashboard },
    { key: "actions", label: "My actions", to: WB_ROUTES.actions, icon: IconChecklist, count: true },
    { key: "cases", label: "Cases", to: "/app/incidents", icon: IconFolders, legacy: true },
    { key: "assets", label: "Assets", to: "/app/machines", icon: IconBuildingFactory2, legacy: true },
    { key: "work", label: "Work orders", to: "/app/maintenance", icon: IconTool, legacy: true },
  ] },
  { group: "Review", secondary: true, items: [
    { key: "reliability", label: "Reliability", to: "/app/analytics", icon: IconChartLine, legacy: true },
    { key: "audit", label: "Audit log", to: "/app/activity", icon: IconHistory, legacy: true },
  ] },
];

export function roleOfSession(session) {
  const id = session?.role || "maintenance_approver";
  return { id, label: SESSION_ROLES.find((r) => r.id === id)?.label || id };
}

/** Action-required items for the declared role (the only nav count; 08 §3.1). */
export function myActionCount(cases, roleId) {
  return cases.filter((c) => c.attention === "action" && c.waiting && Object.values(ROLES).some((r) => r.sessionRole === roleId && r.key === c.waiting.key)).length;
}

function AnalysisWord({ state, demo }) {
  const rp = state.reasoningProvenance || {};
  if (rp.status === "available") return <>Analysis: {rp.live_model ? `${rp.provider || "provider"} · ${rp.model || "model"}` : "deterministic"}</>;
  if (demo?.active && demo?.reasoning?.backend === "deterministic") return <>Analysis: not configured · demo uses deterministic advisory</>;
  if (rp.status === "awaiting_runtime") return <>Analysis: not configured</>;
  return <>Analysis: not reported</>;
}

function StatusIndicator() {
  const { fresh, state, demo } = useWb();
  return (
    <div className="wb-status" role="status" aria-label="System status">
      <FreshnessIndicator fresh={fresh} />
      <span className="wb-status-sep" aria-hidden="true" />
      <span className="wb-status-analysis"><AnalysisWord state={state} demo={demo} /></span>
      {demo?.active ? <span className="wb-demotag" title="Guided Demo active: simulated plant data">DEMO</span> : null}
    </div>
  );
}

function AccountMenu() {
  const { session, signOut } = useSession();
  const { mode, setMode } = useWbTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const role = roleOfSession(session);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const initials = (session?.name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className="wb-account" ref={ref}>
      <button type="button" className="wb-account-btn" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="wb-actor" aria-hidden="true">{initials}</span>
        <span className="wb-account-name">{session?.name || "Signed out"}</span>
        <Icon as={IconChevronDown} size={16} />
      </button>
      {open ? (
        <div className="wb-menu" role="menu" aria-label="Account">
          <div className="wb-menu-head">
            <p className="wb-menu-name">{session?.name}</p>
            <p className="wb-menu-meta">{role.label} · declared, not verified (G8)</p>
          </div>
          <div className="wb-menu-group">
            <p className="wb-label">Theme</p>
            <Segmented label="Theme" value={mode} onChange={setMode}
              options={[{ value: "system", label: "System" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
          </div>
          <Link role="menuitem" className="wb-menu-item" to="/app/profile">Preferences (current page)</Link>
          <button role="menuitem" type="button" className="wb-menu-item" onClick={signOut}>Sign out</button>
        </div>
      ) : null}
    </div>
  );
}

function Rail({ collapsed, onToggle }) {
  const { cases } = useWb();
  const { session } = useSession();
  const count = myActionCount(cases, roleOfSession(session).id);
  const item = (it) => (
    <li key={it.key}>
      <NavLink to={it.to} className={({ isActive }) => `wb-nav-item ${isActive ? "is-active" : ""}`}
        title={collapsed ? it.label : it.legacy ? `${it.label} (current page; V2 redesign follows Phase 4A)` : undefined}
        aria-label={collapsed ? `${it.label}${it.count && count ? `, ${count} require action` : ""}` : undefined}>
        <Icon as={it.icon} size={20} />
        <span className="wb-nav-label">{it.label}</span>
        {it.count && count ? <span className="wb-nav-count" aria-label={`${count} require action`}>{count}</span> : null}
      </NavLink>
    </li>
  );
  return (
    <nav className={`wb-rail ${collapsed ? "is-collapsed" : ""}`} aria-label="Primary">
      {NAV.map((g) => (
        <div key={g.group} className={`wb-nav-group ${g.secondary ? "is-secondary" : ""}`}>
          <p className="wb-eyebrow wb-nav-group-label">{g.group}</p>
          <ul>{g.items.map(item)}</ul>
        </div>
      ))}
      <div className="wb-rail-foot">
        <ul>{item({ key: "system", label: "System", to: WB_ROUTES.simulation, icon: IconAdjustments })}</ul>
        <button type="button" className="wb-rail-toggle" onClick={onToggle} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} title={collapsed ? "Expand navigation" : "Collapse navigation"}>
          <Icon as={collapsed ? IconLayoutSidebarLeftExpand : IconLayoutSidebarLeftCollapse} size={20} />
        </button>
      </div>
    </nav>
  );
}

/** One banner per cause (07 §15.3). Disconnected outranks everything; never a toast for an outage. */
function Banners() {
  const { fresh, demo } = useWb();
  const items = [];
  if (fresh.state === "disconnected") {
    items.push(
      <div key="disc" className="wb-banner wb-banner-critical" id="wb-connection-banner" tabIndex={-1}>
        <Shape name="offline" size={16} decorative />
        <p>
          <strong>Live connection lost.</strong> {fresh.lastReceipt ? `Last data received ${clock(fresh.lastReceipt, { seconds: true })} (browser time). ` : "No data received. "}
          Showing last received data. Reconnecting… Decisions are unavailable until the connection returns.
        </p>
      </div>,
    );
  }
  if (demo?.active) {
    items.push(
      <div key="demo" className="wb-banner wb-banner-demo">
        <span className="wb-simtag">DEMO</span>
        <p>Demo mode · simulated plant data · {demo.label || "Guided Demo"}. Approvals here are real lifecycle decisions on simulated inputs.</p>
      </div>,
    );
  }
  return items.length ? <div className="wb-banners">{items}</div> : null;
}

/** Announcements, once each (07 §15.3): Delayed / Stale politely, Disconnected assertively. */
function Announcer() {
  const { fresh } = useWb();
  const [polite, setPolite] = useState("");
  const [assertive, setAssertive] = useState("");
  const prev = useRef(fresh.state);
  useEffect(() => {
    if (prev.current === fresh.state) return;
    const was = prev.current;
    prev.current = fresh.state;
    if (fresh.state === "disconnected") setAssertive("Live connection lost. Showing last received data.");
    else if ((fresh.state === "delayed" || fresh.state === "stale") && was === "live") setPolite(`Plant data ${fresh.state}.`);
    else if (fresh.state === "live" && was === "disconnected") setPolite("Live connection restored.");
  }, [fresh.state]);
  return (
    <>
      <div className="wb-sr" aria-live="polite">{polite}</div>
      <div className="wb-sr" aria-live="assertive">{assertive}</div>
    </>
  );
}

function ShellFrame() {
  const { state } = useWb();
  const { resolved } = useWbTheme();
  const wide = useMedia("(min-width: 1280px)", true);
  const [userCollapsed, setUserCollapsed] = useState(null);
  const collapsed = userCollapsed ?? !wide;
  const location = useLocation();
  const name = state.meta?.appName || "Operon";
  return (
    <div className="wb-root" data-theme={resolved}>
      <div className="wb-app" data-wb-inert>
        <a className="wb-skip" href="#wb-main">Skip to content</a>
        <header className="wb-header">
          <Link to={WB_ROUTES.overview} className="wb-name">
            <span className="wb-name-mark" aria-hidden="true" />
            <span className="wb-name-text">{name}</span>
          </Link>
          <span className="wb-plant">{state.meta?.plant || "Plant not reported"}</span>
          <span className="wb-header-fill" />
          <StatusIndicator />
          <Link className="wb-iconbtn" to="/app/notifications" aria-label="Updates (this session only, G7)" title="Updates (this session only, G7)">
            <Icon as={IconBell} size={20} />
          </Link>
          <AccountMenu />
        </header>
        <div className="wb-body">
          <Rail collapsed={collapsed} onToggle={() => setUserCollapsed(!collapsed)} />
          <div className="wb-sheet-wrap">
            <Banners />
            <main className="wb-sheet" id="wb-main" key={location.pathname}>
              <Outlet />
            </main>
          </div>
        </div>
        <Announcer />
      </div>
      <div data-wb-portal />
    </div>
  );
}

export function WbShell() {
  return (
    <WbThemeProvider>
      <WbProvider>
        <ShellFrame />
      </WbProvider>
    </WbThemeProvider>
  );
}

export function usePageTitle(title) {
  const { state } = useWb();
  const name = state.meta?.appName || "Operon";
  useEffect(() => { document.title = `${title} · ${name}`; }, [title, name]);
}

export function useRoleScope() {
  const { session } = useSession();
  return useMemo(() => roleOfSession(session), [session]);
}

export function useGo() {
  return useNavigate();
}
