import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useSettings, DEFAULT_SETTINGS } from "../state/settings.jsx";
import { useTheme, THEME_MODES } from "../state/theme.jsx";
import { useSession } from "../state/session.jsx";
import { useEngineState } from "../state/engine.jsx";
import { clearOperonKeys } from "../lib/storage.js";
import { PageHeader, Section, Toggle, Select, Modal } from "../components/index.jsx";
import { Btn, Icons, Tag, KV, Dot } from "../primitives/index.jsx";
import { risk as fmtRisk, title } from "../lib/format.js";
import { ROUTES } from "../app/routes.js";

const SECTIONS = [["general", "General"], ["appearance", "Appearance"], ["notifications", "Notifications"], ["agent", "Agent preferences"], ["plant", "Plant & system"], ["account", "Account"]];
const Scope = ({ children = "browser-local" }) => <Tag className="scope-tag" tone="normal">{children}</Tag>;

export function SettingsPage() {
  const { settings, set, reset } = useSettings();
  const { mode, resolved, setMode } = useTheme();
  const { session, signOut } = useSession();
  const { state, stop, resume, reset: resetEngine, startDemo } = useEngineState();
  const location = useLocation();
  const navigate = useNavigate();
  const [active, setActive] = useState(location.hash.replace("#", "") || "general");
  const [confirm, setConfirm] = useState(null);
  useEffect(() => { const h = location.hash.replace("#", ""); if (h) { setActive(h); document.getElementById(`s-${h}`)?.scrollIntoView({ block: "start" }); } }, [location.hash]);
  const g = settings.general, n = settings.notifications, ag = settings.agent, pl = settings.plant;
  return (
    <div className="page">
      <div className="page-body">
        <PageHeader eyebrow="Account" title="Settings" meta={<span>Preferences marked <Scope /> live in this browser until the engine offers a preference store.</span>} actions={<Btn small quiet onClick={() => setConfirm("reset-prefs")}>Reset preferences</Btn>} />
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="Settings sections">{SECTIONS.map(([k, l]) => <a key={k} href={`#${k}`} className={active === k ? "is-active" : ""} onClick={() => setActive(k)}>{l}</a>)}</nav>
          <div className="settings-sections">
            <Section label="General" actions={<Scope />} className="" >
              <div id="s-general" />
              <div className="form-grid">
                <Select label="Timestamps" value={g.timeMode} onChange={(v) => set("general", { timeMode: v })} options={[{ value: "utc", label: "UTC (engine canonical)" }, { value: "local", label: "Browser local time" }]} />
                <Select label="Density" value={g.density} onChange={(v) => set("general", { density: v })} options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} />
                <Select label="Landing page" value={g.landing} onChange={(v) => set("general", { landing: v })} options={[{ value: ROUTES.dashboard, label: "Dashboard" }, { value: ROUTES.incidents, label: "Incidents" }, { value: ROUTES.agent, label: "Operon Agent" }, { value: ROUTES.machines, label: "Machines" }]} />
              </div>
            </Section>
            <Section label="Appearance" actions={<Scope />}>
              <div id="s-appearance" />
              <div className="choice-row" role="radiogroup" aria-label="Theme">
                {THEME_MODES.map((m) => (
                  <button key={m} type="button" role="radio" aria-checked={mode === m} className={`choice ${mode === m ? "is-active" : ""}`} onClick={() => setMode(m)}>
                    <span className="choice-title">{m === "light" ? Icons.sun({}) : m === "dark" ? Icons.moon({}) : Icons.monitor({})}{title(m)}</span>
                    <span className="choice-hint">{m === "system" ? `Follows the OS · currently ${resolved}` : m === "dark" ? "Graphite command-room palette" : "Designed light palette, same tokens"}</span>
                  </button>
                ))}
              </div>
              <p className="t3">Both palettes are intentionally designed from the same semantic tokens: surfaces, hairlines, text, brand, status and chart colours each have their own steps. Reduced motion follows the operating system.</p>
            </Section>
            <Section label="Notifications" actions={<Scope />}>
              <div id="s-notifications" />
              <Toggle label="Critical incidents" hint="Incident opened, escalated, execution failed, cancelled, unplanned failure." checked={n.critical} onChange={(v) => set("notifications", { critical: v })} />
              <Toggle label="Approvals" hint="Human hold point reached, plan rejected." checked={n.approvals} onChange={(v) => set("notifications", { approvals: v })} />
              <Toggle label="Maintenance" hint="Dispatch, execution and closure." checked={n.maintenance} onChange={(v) => set("notifications", { maintenance: v })} />
              <Toggle label="Agent events" hint="Evidence requests, recovery observation, outcomes, refused actions." checked={n.agent} onChange={(v) => set("notifications", { agent: v })} />
              <Toggle label="Engine control" hint="Pause, resume, reset and guided demo milestones." checked={n.connection} onChange={(v) => set("notifications", { connection: v })} />
              <Toggle label="Sound" hint="Not available: no audio channel is wired." checked={false} onChange={() => {}} disabled />
            </Section>
            <Section label="Agent preferences" actions={<Scope />}>
              <div id="s-agent" />
              <Toggle label="Confirm before approving or rejecting" hint="Shows the bound intervention hash and revision before the decision is sent." checked={ag.confirmBeforeApprove} onChange={(v) => set("agent", { confirmBeforeApprove: v })} />
              <Toggle label="Show advisory lane in the agent console" hint="Dashed specialist outputs alongside authoritative records." checked={ag.showAdvisoryLane} onChange={(v) => set("agent", { showAdvisoryLane: v })} />
              <Toggle label="Open inspector from #artifact deep links" hint="Shared links can open an artifact directly." checked={ag.autoOpenDeepLink} onChange={(v) => set("agent", { autoOpenDeepLink: v })} />
              <div className="note-box">{Icons.lock({})}<span>Runtime behaviour (fast/slow path, interruption budgets, re-planning policy) is owned by the reasoning runtime and is not configurable from the portal. Those controls will appear here once the Samsung PRISM runtime exposes them.</span></div>
            </Section>
            <Section label="Plant & system" actions={<Tag className="scope-tag" tone="auth">engine</Tag>}>
              <div id="s-plant" />
              <div className="kvgrid kvgrid-4">
                <KV label="Plant" value={state.meta.plant || null} /><KV label="Warning band" mono value={fmtRisk(state.warnThreshold)} /><KV label="Incident gate" mono value={fmtRisk(state.triggerThreshold)} /><KV label="Agent mode" mono value={state.agentMode || null} />
                <KV label="Reasoning backend" mono value={state.reasoningProvenance?.backend || null} /><KV label="Runtime" value={state.reasoningProvenance?.runtime || null} /><KV label="Authority path" mono value={state.authorityPath || null} /><KV label="Stream" value={<span className="row-wrap"><Dot tone={state.connected ? "ok" : "crit"} />{state.connected ? `connected · tick ${state.tick}` : "reconnecting"}</span>} />
              </div>
              <p className="t3">Thresholds and the reasoning backend are engine configuration (see <span className="mono">core/config.py</span> and the <span className="mono">OPERON_*</span> environment). They are shown here, not edited.</p>
              <div className="row-wrap">
                {!state.demoScenario?.active ? <Btn small onClick={state.running ? stop : resume}>{state.running ? Icons.pause({}) : Icons.play({})} {state.running ? "Pause simulator" : "Resume simulator"}</Btn> : null}
                <Btn small onClick={() => startDemo(state.demoScenario?.equipment_id || "AC-COMP-01")}>{Icons.demo({})} {state.demoScenario?.active ? "Restart guided demo" : "Start guided demo"}</Btn>
                <Btn small quiet onClick={() => setConfirm("reset-engine")}>{Icons.reset({})} Reset engine…</Btn>
              </div>
              <Toggle label="Show economics on the dashboard" hint="KPI deck economic cells (recovered value, value at risk)." checked={pl.showEconomics} onChange={(v) => set("plant", { showEconomics: v })} />
            </Section>
            <Section label="Account" actions={<Scope />}>
              <div id="s-account" />
              <div className="kvgrid kvgrid-3"><KV label="Signed in as" value={session?.name} /><KV label="Email" mono value={session?.email} /><KV label="Session" value={session?.remember ? "Persistent on this device" : "This tab only"} /></div>
              <div className="row-wrap">
                <Btn small onClick={() => navigate(ROUTES.profile)}>{Icons.user({})} Edit profile</Btn>
                <Btn small quiet onClick={() => setConfirm("clear")}>{Icons.close({})} Clear local data…</Btn>
                <Btn small quiet onClick={() => { signOut(); navigate(ROUTES.login); }}>{Icons.logout({})} Sign out</Btn>
              </div>
            </Section>
          </div>
        </div>
        <Modal open={confirm === "reset-prefs"} onClose={() => setConfirm(null)} title="Reset preferences?" actions={<><Btn onClick={() => setConfirm(null)}>Cancel</Btn><Btn primary onClick={() => { reset(); setConfirm(null); }}>Reset</Btn></>}><p className="t2">Restores the defaults for general, notification, agent and plant preferences. Theme and session are kept.</p></Modal>
        <Modal open={confirm === "reset-engine"} onClose={() => setConfirm(null)} title="Reset the engine?" actions={<><Btn onClick={() => setConfirm(null)}>Cancel</Btn><Btn primary onClick={() => { resetEngine(); setConfirm(null); }}>Reset</Btn></>}><p className="t2">Clears projected incidents and telemetry and starts a new artifact generation. Committed database records are kept.</p></Modal>
        <Modal open={confirm === "clear"} onClose={() => setConfirm(null)} title="Clear local Operon data?" actions={<><Btn onClick={() => setConfirm(null)}>Cancel</Btn><Btn primary onClick={() => { clearOperonKeys(); setConfirm(null); signOut(); navigate(ROUTES.login); }}>Clear and sign out</Btn></>}><p className="t2">Removes the session, theme, preferences, sidebar state and notification read marks from this browser. Nothing on the engine changes.</p></Modal>
      </div>
    </div>
  );
}
