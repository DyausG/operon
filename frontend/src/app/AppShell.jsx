// Persistent application shell: sidebar navigation, top bar, global menus, engine controls.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ACCOUNT_NAV, NAV, PAGE_TITLES, ROUTES } from "./routes.js";
import { useEngineState } from "../state/engine.jsx";
import { useSession, initialsOf, ROLES } from "../state/session.jsx";
import { useTheme } from "../state/theme.jsx";
import { useNotifications } from "../state/notifications.jsx";
import { useSettings } from "../state/settings.jsx";
import { ArtifactProvider, useInspector } from "../state/artifacts.jsx";
import { rowIndex, isActive } from "../state/selectors.js";
import { InspectorTray } from "../features/Inspector/Tray.jsx";
import { Btn, Icons, Dot } from "../primitives/index.jsx";
import { Menu, MenuItem, MenuRule, Modal, ConnectionBanner } from "../components/index.jsx";
import { elapsed, clock, ago, title } from "../lib/format.js";
import { readJSON, writeJSON } from "../lib/storage.js";

const SIDEBAR_KEY = "operon.sidebar";

function useMedia(query) {
  const [m, setM] = useState(() => { try { return window.matchMedia(query).matches; } catch { return false; } });
  useEffect(() => {
    let mq; try { mq = window.matchMedia(query); } catch { return undefined; }
    const on = () => setM(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [query]);
  return m;
}

export function AppShell() {
  const { state, ...actions } = useEngineState();
  const location = useLocation();
  const narrow = useMedia("(max-width: 1100px)");
  const phone = useMedia("(max-width: 800px)");
  const [collapsed, setCollapsed] = useState(() => readJSON(SIDEBAR_KEY, false) === true);
  const [drawer, setDrawer] = useState(false);
  const rail = phone ? false : (narrow || collapsed);

  useEffect(() => { setDrawer(false); }, [location.pathname]);
  const toggleSidebar = useCallback(() => {
    if (phone) { setDrawer((v) => !v); return; }
    setCollapsed((v) => { writeJSON(SIDEBAR_KEY, !v); return !v; });
  }, [phone]);

  // Every read-model row across all incidents is inspectable from any page.
  const index = useMemo(() => rowIndex({ alerts: state.alerts }), [state.alerts]);
  const segment = location.pathname.split("/")[2] || "dashboard";
  useEffect(() => { document.title = `${PAGE_TITLES[segment] || "Operon"} · Operon`; }, [segment]);

  return (
    <ArtifactProvider generation={state.generation} rowIndex={index}>
      <DeepLink ready={state.frames > 0} />
      <div className={`app ${rail ? "is-rail" : ""} ${drawer ? "is-drawer-open" : ""}`} data-page={segment}>
        {phone && drawer ? <div className="sb-backdrop" onClick={() => setDrawer(false)} /> : null}
        <Sidebar rail={rail} onToggle={toggleSidebar} state={state} />
        <div className="main">
          <TopBar state={state} actions={actions} onMenu={toggleSidebar} phone={phone} />
          <ConnectionBanner connected={state.connected} frames={state.frames} />
          <Outlet />
        </div>
        <InspectorTray view={{ alerts: state.alerts }} />
        {state.action.error ? (
          <div className="hdr-error" role="alert">{Icons.warn({})}<span>Action refused: {state.action.error}</span><button type="button" className="btn btn-quiet btn-small" onClick={actions.clearError}>Dismiss</button></div>
        ) : null}
      </div>
    </ArtifactProvider>
  );
}

/** Deep link: #artifact=<id> opens the inspector on load (kept from the single-page dashboard). */
function DeepLink({ ready }) {
  const insp = useInspector();
  const { settings } = useSettings();
  useEffect(() => {
    if (!ready || typeof location === "undefined" || !settings.agent.autoOpenDeepLink) return;
    const m = /#artifact=([^&]+)/.exec(location.hash || "");
    if (m) insp.open(decodeURIComponent(m[1]));
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function Sidebar({ rail, onToggle, state }) {
  const { unread, needsAction } = useNotifications();
  const activeIncidents = Object.values(state.alerts || {}).filter(isActive).length;
  const badges = { activeIncidents: { n: activeIncidents, tone: activeIncidents ? "warn" : "" }, approvals: { n: needsAction, tone: needsAction ? "warn" : "" }, unread: { n: unread, tone: unread ? "brand" : "" } };
  const groups = [...new Set(NAV.map((n) => n.group))];
  const prov = state.reasoningProvenance || {};
  return (
    <aside className="sidebar" aria-label="Primary">
      <div className="sb-brand">
        <Link to={ROUTES.dashboard} className="wordmark" title={state.meta.tagline}><span className="mark" /><span className="wordmark-text">OPERON</span></Link>
        <button type="button" className="btn btn-quiet btn-icon sb-collapse" onClick={onToggle} aria-label={rail ? "Expand navigation" : "Collapse navigation"} title={rail ? "Expand" : "Collapse"}>{rail ? Icons.expand({}) : Icons.collapse({})}</button>
      </div>
      <nav className="sb-nav">
        {groups.map((g) => (
          <div key={g} className="sb-group">
            <span className="sb-group-l lbl">{g}</span>
            {NAV.filter((n) => n.group === g).map((n) => {
              const b = n.badge ? badges[n.badge] : null;
              return (
                <NavLink key={n.key} to={n.to} className={({ isActive: on }) => `sb-link ${on ? "is-active" : ""}`} title={rail ? n.label : undefined}>
                  <span className="sb-ico">{Icons[n.icon]({})}</span>
                  <span className="sb-text">{n.label}</span>
                  {b && b.n ? <span className={`sb-badge mono ${b.tone ? `tone-${b.tone}` : ""}`} aria-label={`${b.n} ${n.label}`}>{b.n}</span> : null}
                </NavLink>
              );
            })}
          </div>
        ))}
        <div className="sb-group">
          <span className="sb-group-l lbl">Account</span>
          {ACCOUNT_NAV.map((n) => (
            <NavLink key={n.key} to={n.to} className={({ isActive: on }) => `sb-link ${on ? "is-active" : ""}`} title={rail ? n.label : undefined}>
              <span className="sb-ico">{Icons[n.icon]({})}</span><span className="sb-text">{n.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>
      <div className="sb-foot">
        <div className="sb-plant"><span className="sb-text truncate" title={state.meta.plant}>{state.meta.plant || "Plant"}</span></div>
        <div className="sb-runtime mono" title={`reasoning backend ${prov.backend || "none"} · ${prov.status || ""}`}>
          <Dot tone={state.connected ? (prov.status === "available" ? "auth" : "normal") : "crit"} />
          <span className="sb-text truncate">{state.connected ? (prov.runtime || "Local runtime") : "Stream offline"}</span>
        </div>
      </div>
    </aside>
  );
}

function TopBar({ state, actions, onMenu, phone }) {
  const location = useLocation();
  const segment = location.pathname.split("/")[2] || "dashboard";
  const demo = state.demoScenario || {}, prov = state.reasoningProvenance || {};
  const clockText = demo.active ? elapsed(demo.elapsed_seconds) : `+${String(Math.floor((state.plantMin || 0) / 60)).padStart(2, "0")}:${String((state.plantMin || 0) % 60).padStart(2, "0")}`;
  const bedrock = prov.status === "available" || prov.backend === "agentcore";
  return (
    <header className="topbar">
      {phone ? <button type="button" className="btn btn-quiet btn-icon" onClick={onMenu} aria-label="Open navigation">{Icons.menu({})}</button> : null}
      <div className="tb-context">
        <span className="tb-title">{PAGE_TITLES[segment] || "Operon"}</span>
        <span className="tb-sub t3 truncate">{demo.active ? `Guided demo · ${demo.label || "simulated plant"}` : state.meta.plant || ""}</span>
      </div>
      <GlobalSearch state={state} />
      <div className="tb-right">
        <div className="tb-badges">
          <span className="hdr-badge badge-gate" title="Human-in-the-loop governance: automated actions require human sign-off">{Icons.shield({ size: 12 })}<span>Policy gate · HITL</span></span>
          <span className={`hdr-badge badge-bedrock ${bedrock ? "online" : "standby"}`} title={bedrock ? `${prov.runtime} connected` : "Reasoning runtime in local standby; deterministic trajectories"}><span className="status-dot" /><span>{bedrock ? "Bedrock · connected" : "Bedrock · standby"}</span></span>
        </div>
        <span className="hdr-clock" title={demo.active ? "Scripted scenario elapsed" : "Plant operating time"}>{clockText}</span>
        <span className={`activity ${!state.connected ? "off" : "on"}`} title={state.connected ? "Telemetry stream connected" : "Reconnecting"} />
        <EngineControls state={state} actions={actions} />
        <ThemeToggle />
        <NotificationMenu />
        <UserMenu />
      </div>
    </header>
  );
}

export function ThemeToggle({ withLabel = false }) {
  const { resolved, mode, toggle } = useTheme();
  return (
    <button type="button" className={`btn btn-quiet ${withLabel ? "btn-small" : "btn-icon"}`} onClick={toggle} title={`Theme: ${mode} (${resolved}). Click to switch.`} aria-label="Toggle theme">
      {resolved === "dark" ? Icons.sun({}) : Icons.moon({})}{withLabel ? <span>{resolved === "dark" ? "Light" : "Dark"}</span> : null}
    </button>
  );
}

function EngineControls({ state, actions }) {
  const [open, setOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const demo = state.demoScenario || {};
  const focus = demo.equipment_id || Object.values(state.alerts || {}).find(isActive)?.equipment_id || state.fleet[0]?.equipment_id || "AC-COMP-01";
  return (
    <>
      <Menu open={open} onOpenChange={setOpen} width={260} button={
        <button type="button" className={`btn btn-quiet btn-small tb-engine ${open ? "is-active" : ""}`} onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} title="Engine controls">
          {Icons.bolt({})}<span className="tb-engine-text">Engine</span>{Icons.chevronDown({ size: 12 })}
        </button>
      }>
        <div className="menu-head"><span className="lbl">Engine</span><span className="mono t3">{state.running ? "running" : "paused"} · tick {state.tick}</span></div>
        <MenuItem icon={Icons.demo({})} onClick={() => { setOpen(false); actions.startDemo(focus); }}>{demo.active ? "Restart guided demo" : "Start guided demo"}</MenuItem>
        {!demo.active ? <MenuItem icon={state.running ? Icons.pause({}) : Icons.play({})} onClick={() => { setOpen(false); (state.running ? actions.stop : actions.resume)(); }}>{state.running ? "Pause simulator" : "Resume simulator"}</MenuItem> : null}
        <MenuRule />
        <MenuItem icon={Icons.reset({})} danger onClick={() => { setOpen(false); setConfirmReset(true); }}>Reset engine…</MenuItem>
        <MenuRule />
        <MenuItem icon={Icons.settings({})} to={`${ROUTES.settings}#plant`} onClick={() => setOpen(false)}>Plant &amp; system settings</MenuItem>
      </Menu>
      <Modal open={confirmReset} onClose={() => setConfirmReset(false)} title="Reset the engine?" actions={<><Btn onClick={() => setConfirmReset(false)}>Cancel</Btn><Btn primary onClick={() => { setConfirmReset(false); actions.reset(); }}>Reset</Btn></>}>
        <p className="t2">This clears every projected incident, telemetry history and the guided demo, and starts a new artifact generation. The durable database keeps its committed records.</p>
      </Modal>
    </>
  );
}

function NotificationMenu() {
  const { items, unread, markRead, markAllRead } = useNotifications();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const latest = items.slice(0, 6);
  return (
    <Menu open={open} onOpenChange={setOpen} width={360} button={
      <button type="button" className={`btn btn-quiet btn-icon tb-bell ${open ? "is-active" : ""}`} onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} title="Notifications">
        {Icons.bell({})}{unread ? <span className="tb-count mono">{unread > 99 ? "99+" : unread}</span> : null}
      </button>
    }>
      <div className="menu-head"><span className="lbl">Notifications</span>{unread ? <button type="button" className="link-btn" onClick={markAllRead}>Mark all read</button> : <span className="t4 mono">all read</span>}</div>
      {latest.length ? latest.map((n) => (
        <button key={n.id} type="button" className={`notif ${n.read ? "" : "is-unread"}`} onClick={() => { markRead(n.id); setOpen(false); navigate(n.incidentId ? ROUTES.incident(n.incidentId) : n.machineId ? ROUTES.machine(n.machineId) : ROUTES.notifications); }}>
          <Dot tone={n.tone === "normal" ? "normal" : n.tone} />
          <span className="notif-body"><span className="notif-title">{n.title}</span><span className="notif-text truncate">{n.body}</span></span>
          <span className="notif-when mono t4">{ago(n.at)}</span>
        </button>
      )) : <div className="menu-empty t3">No notifications yet. Events from the engine stream appear here.</div>}
      <MenuRule />
      <MenuItem to={ROUTES.notifications} onClick={() => setOpen(false)} icon={Icons.next({})}>All notifications</MenuItem>
    </Menu>
  );
}

function UserMenu() {
  const { session, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const role = ROLES.find((r) => r.id === session?.role)?.label || title(session?.role || "operator");
  return (
    <Menu open={open} onOpenChange={setOpen} width={240} button={
      <button type="button" className={`avatar-btn ${open ? "is-active" : ""}`} onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label="Account menu" title={session?.name}>
        <span className="avatar">{initialsOf(session?.name)}</span>
      </button>
    }>
      <div className="menu-user"><span className="avatar avatar-l">{initialsOf(session?.name)}</span><span className="menu-user-text"><span className="t1">{session?.name}</span><span className="t3 truncate">{session?.email}</span><span className="t4">{role} · demo session</span></span></div>
      <MenuRule />
      <MenuItem to={ROUTES.profile} icon={Icons.user({})} onClick={() => setOpen(false)}>Profile</MenuItem>
      <MenuItem to={ROUTES.settings} icon={Icons.settings({})} onClick={() => setOpen(false)}>Settings</MenuItem>
      <MenuRule />
      <MenuItem icon={Icons.logout({})} onClick={() => { setOpen(false); signOut(); navigate(ROUTES.login); }}>Sign out</MenuItem>
    </Menu>
  );
}

function GlobalSearch({ state }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    const out = [];
    for (const a of state.fleet || []) if (`${a.equipment_id} ${a.name} ${a.equipment_class}`.toLowerCase().includes(s)) out.push({ kind: "Machine", label: a.equipment_id, sub: a.name, to: ROUTES.machine(a.equipment_id), tone: a.status });
    for (const a of Object.values(state.alerts || {})) if (`${a.incident_id} ${a.equipment_id} ${a.lifecycle?.phase || a.status}`.toLowerCase().includes(s)) out.push({ kind: "Incident", label: a.incident_id, sub: `${a.equipment_id} · ${title(a.lifecycle?.phase || a.status)}`, to: ROUTES.incident(a.incident_id), tone: a.lifecycle?.phase || a.status });
    return out.slice(0, 8);
  }, [q, state.fleet, state.alerts]);
  const go = (r) => { navigate(r.to); setQ(""); setOpen(false); };
  const ref = useMemo(() => ({ current: null }), []);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, ref]);
  return (
    <div className="gsearch" ref={(el) => { ref.current = el; }}>
      <label className="search">
        {Icons.search({ size: 14 })}
        <input type="search" value={q} placeholder="Search machines, incidents…" onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={(e) => { if (e.key === "Enter" && results[0]) go(results[0]); if (e.key === "Escape") setOpen(false); }} aria-label="Search" />
      </label>
      {open && q.trim() ? (
        <div className="gsearch-pop" role="listbox">
          {results.length ? results.map((r) => <button key={r.to} type="button" className="gsearch-row" role="option" onClick={() => go(r)}><span className="lbl gsearch-kind">{r.kind}</span><span className="mono">{r.label}</span><span className="t3 truncate">{r.sub}</span></button>) : <div className="menu-empty t3">No matches for “{q}”.</div>}
        </div>
      ) : null}
    </div>
  );
}
