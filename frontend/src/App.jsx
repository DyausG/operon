import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ResponsiveContainer, LineChart, Line, Area, AreaChart, XAxis, YAxis,
  ReferenceLine, ReferenceArea, Tooltip, CartesianGrid,
} from "recharts";
import { useEngine } from "./useEngine.js";
import { pct, money0, STATUS_ORDER, ClassIcon, ShieldMark, actorGlyph } from "./lib.jsx";

const SERIES_COLORS = ["#ff5470", "#ffb84d", "#7c8cff", "#23d5e0", "#34e2b0", "#c77dff"];

export default function App() {
  const { state, approve, reject, reset, stop, resume } = useEngine();
  const [selected, setSelected] = useState(null);

  const alerts = useMemo(
    () => Object.values(state.alerts).sort((a, b) => (a.triage_rank || 99) - (b.triage_rank || 99)),
    [state.alerts]
  );
  const activeAlerts = alerts.filter((a) => ["ANALYZING", "PENDING_APPROVAL"].includes(a.status));

  // focus = clicked asset, else the top-priority active alert
  const focusId = selected || activeAlerts[0]?.equipment_id || null;

  return (
    <div className="app">
      <Header state={state} onReset={() => { setSelected(null); reset(); }}
        onStop={stop} onResume={resume} />
      <div className="grid">
        <div className="col">
          <FleetPanel fleet={state.fleet} selected={focusId} onSelect={setSelected}
            warn={state.warnThreshold} />
          <ChartPanel state={state} focusId={focusId} />
        </div>
        <div className="col">
          <AgentPanel alerts={alerts} triage={state.triage} focusId={focusId}
            onSelect={setSelected} approve={approve} reject={reject}
            threshold={state.triggerThreshold} />
          <BusinessPanel biz={state.business} />
        </div>
      </div>
      <Toasts lastEvent={state.lastEvent} fleet={state.fleet} />
    </div>
  );
}

/* -------------------------------------------------------------- Header ---- */
function Header({ state, onReset, onStop, onResume }) {
  const { agentMode, connected, meta, plantMin, running } = state;
  const hrs = Math.floor(plantMin / 60), mins = plantMin % 60;
  const isLive = agentMode && agentMode !== "deterministic";
  const modeChip = isLive
    ? <span className="chip bedrock"><span className="dot" />{agentMode.toUpperCase()} · LIVE AGENT</span>
    : <span className="chip det"><span className="dot" />DETERMINISTIC PLANNER</span>;
  return (
    <header className="header">
      <div className="brand">
        <div className="brand-mark"><ShieldMark /></div>
        <div>
          <h1>{meta.appName || "Operon"}</h1>
          <div className="tag">{meta.tagline || "Autonomous Reliability Operations for Industrial Systems"}</div>
        </div>
      </div>
      <div className="header-spacer" />
      <span className="chip">{meta.plant || "Plant"} · shift A · +{String(hrs).padStart(2, "0")}:{String(mins).padStart(2, "0")}</span>
      {modeChip}
      <span className={"chip " + (connected ? (running ? "live" : "offline") : "offline")}>
        <span className="dot" />{!connected ? "RECONNECTING" : running ? "STREAMING" : "PAUSED"}
      </span>
      {running
        ? <button className="btn ghost" onClick={onStop}>⏸ Stop</button>
        : <button className="btn ghost" onClick={onResume}>▶ Resume</button>}
      <button className="btn ghost" onClick={onReset}>↻ Reset demo</button>
    </header>
  );
}

/* --------------------------------------------------------- Fleet panel ---- */
function FleetPanel({ fleet, selected, onSelect, warn }) {
  const sorted = [...fleet].sort(
    (a, b) => (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || (b.failure_prob - a.failure_prob)
  );
  const critical = fleet.filter((a) => a.status === "CRITICAL").length;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Fleet · Live Asset Health</h2>
        <span className="count">{fleet.length} assets · {critical} critical</span>
      </div>
      <div className="panel-body">
        <div className="fleet">
          <AnimatePresence>
            {sorted.map((a) => (
              <motion.div key={a.equipment_id} layout
                initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
                transition={{ type: "spring", stiffness: 380, damping: 30 }}>
                <AssetCard a={a} selected={selected === a.equipment_id}
                  onClick={() => onSelect(a.equipment_id)} warn={warn} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

function AssetCard({ a, selected, onClick, warn }) {
  const showMode = a.failure_prob >= warn && a.predicted_mode && a.predicted_mode !== "NONE";
  return (
    <div className={`asset s-${a.status} ${selected ? "sel" : ""}`} onClick={onClick}>
      <div className="rail" />
      <div className="asset-top">
        <div className="icon"><ClassIcon cls={a.equipment_class} /></div>
        <div style={{ minWidth: 0 }}>
          <div className="id">{a.equipment_id}</div>
          <div className="nm">{a.name}</div>
        </div>
        <span className={`badge ${a.status}`}>{a.status}</span>
      </div>
      <div className="prob-row">
        <span className="prob">{pct(a.failure_prob)}</span>
        <small>24h fail risk</small>
      </div>
      <div className="mode">{showMode ? `▸ ${a.predicted_mode_label}` : " "}</div>
      <MiniSpark point={a.point} status={a.status} />
    </div>
  );
}

// tiny sparkline that accumulates the last ~24 probs client-side per card
function MiniSpark({ point, status }) {
  const ref = useRef([]);
  if (point) {
    ref.current = [...ref.current, point.prob].slice(-24);
  }
  const data = ref.current.map((p, i) => ({ i, p }));
  const color = { CRITICAL: "#ff5470", WARNING: "#ffb84d", SCHEDULED: "#5aa9ff", HEALTHY: "#34e2b0", DOWN: "#7a8299" }[status];
  return (
    <div className="spark">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, bottom: 0, left: 0, right: 0 }}>
          <defs>
            <linearGradient id={`sg-${status}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.5} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis domain={[0, 1]} hide />
          <Area type="monotone" dataKey="p" stroke={color} strokeWidth={1.6}
            fill={`url(#sg-${status})`} isAnimationActive={false} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/* --------------------------------------------------------- Chart panel ---- */
function ChartPanel({ state, focusId }) {
  // Which assets to plot: everything currently non-healthy, plus the focused one.
  const plotted = useMemo(() => {
    const ids = new Set(state.fleet.filter((a) => a.status !== "HEALTHY").map((a) => a.equipment_id));
    if (focusId) ids.add(focusId);
    return [...ids].slice(0, 6);
  }, [state.fleet, focusId]);

  const { data, series } = useMemo(() => {
    const byT = new Map();
    const series = [];
    plotted.forEach((id, idx) => {
      const hist = state.histories[id] || [];
      const color = SERIES_COLORS[idx % SERIES_COLORS.length];
      const label = state.fleet.find((a) => a.equipment_id === id)?.equipment_id || id;
      series.push({ id, color, label });
      for (const pt of hist) {
        if (!byT.has(pt.t)) byT.set(pt.t, { t: pt.t });
        byT.get(pt.t)[id] = pt.prob;
      }
    });
    const data = [...byT.values()].sort((a, b) => a.t - b.t).slice(-70);
    return { data, series };
  }, [plotted, state.histories, state.fleet]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Failure Probability · 24h Horizon</h2>
        <span className="count">action threshold {pct(state.triggerThreshold)}</span>
      </div>
      <div className="panel-body">
        <div className="hero-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 10, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="rgba(120,140,190,0.10)" vertical={false} />
              <ReferenceArea y1={state.triggerThreshold} y2={1} fill="rgba(255,84,112,0.06)" />
              <XAxis dataKey="t" tick={{ fill: "#5f6d8f", fontSize: 11 }} tickLine={false} axisLine={false}
                minTickGap={28} />
              <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}`}
                tick={{ fill: "#5f6d8f", fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
              <ReferenceLine y={state.triggerThreshold} stroke="#ff5470" strokeDasharray="5 4" strokeOpacity={0.7} />
              <ReferenceLine y={state.warnThreshold} stroke="#ffb84d" strokeDasharray="3 4" strokeOpacity={0.5} />
              <Tooltip contentStyle={{ background: "#0f1729", border: "1px solid rgba(120,140,190,0.3)",
                borderRadius: 10, fontSize: 12 }} labelStyle={{ color: "#94a3c4" }}
                formatter={(v, n) => [pct(v), n]} />
              {series.map((s) => (
                <Line key={s.id} type="monotone" dataKey={s.id} stroke={s.color} strokeWidth={2.2}
                  dot={false} isAnimationActive={false} connectNulls
                  strokeOpacity={focusId && focusId !== s.id ? 0.4 : 1} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="legend">
          {series.length === 0 && <span style={{ color: "#5f6d8f", fontSize: 12 }}>Fleet nominal — monitoring…</span>}
          {series.map((s) => (
            <span className="k" key={s.id}><span className="sw" style={{ background: s.color }} />{s.label}</span>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------- Agent panel ---- */
function AgentPanel({ alerts, triage, focusId, onSelect, approve, reject, threshold }) {
  const active = alerts.filter((a) => ["ANALYZING", "PENDING_APPROVAL", "REJECTED"].includes(a.status));
  const resolved = alerts.filter((a) => ["APPROVED", "FAILED"].includes(a.status));
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Maintenance Agent</h2>
        <span className="count">{active.length} open · {resolved.length} resolved</span>
      </div>
      <div className="panel-body">
        {triage.count > 1 && (
          <div className="triage-banner" style={{ marginBottom: 12 }}>
            <span>⚖️</span><span>{triage.rationale}</span>
          </div>
        )}
        <MonitoringBanner m={triage.monitoring} />
        {alerts.length === 0 && (
          <div className="empty">
            <div className="big">Monitoring the fleet</div>
            The agent activates automatically when an asset's failure probability
            crosses the {pct(threshold)} action threshold.
          </div>
        )}
        <div className="queue">
          <AnimatePresence>
            {alerts.map((a) => (
              <motion.div key={a.equipment_id} layout
                initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                transition={{ type: "spring", stiffness: 320, damping: 30 }}>
                <AlertCard a={a} expanded={focusId === a.equipment_id}
                  onToggle={() => onSelect(a.equipment_id)}
                  approve={approve} reject={reject} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

const GOV_META = {
  APPROVE: { tone: "ok", label: "Approved" },
  CONDITIONS: { tone: "warn", label: "Approve with conditions" },
  VETO: { tone: "bad", label: "Vetoed" },
  UNAVAILABLE: { tone: "muted", label: "Review unavailable" },
};

function GovPill({ g }) {
  if (!g) return null;
  const m = GOV_META[g.decision] || GOV_META.UNAVAILABLE;
  return <span className={`gov-pill ${m.tone}`} title={`Governance: ${m.label}`}>⚖ {g.decision}</span>;
}

function GovernanceVerdict({ g }) {
  if (!g) return null;
  const m = GOV_META[g.decision] || GOV_META.UNAVAILABLE;
  const items = [
    ...(g.reasons || []).map((t) => ({ t, cond: false })),
    ...(g.conditions || []).map((t) => ({ t, cond: true })),
  ];
  return (
    <div className={`gov ${m.tone}`}>
      <div className="gov-head">
        <span className="gov-mark">⚖</span>
        <span className="gov-label">Governance · {m.label}</span>
        {g.decision === "VETO" && <span className="gov-hint">human override required</span>}
      </div>
      {items.length > 0 && (
        <ul className="gov-list">
          {items.map((it, i) => (
            <li key={i} className={it.cond ? "cond" : ""}>{it.cond ? "⚑ " : ""}{it.t}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MonitoringBanner({ m }) {
  if (!m || !m.escalate) return null;
  const ids = [...new Set((m.correlations || []).flatMap((c) => c.equipment_ids || []))];
  return (
    <div className="monitor-banner" style={{ marginBottom: 12 }}>
      <span className="mb-icon">📡</span>
      <div className="mb-body">
        <div className="mb-title">Monitoring · systemic pattern detected</div>
        <div className="mb-text">{m.rationale}</div>
        {ids.length > 0 && (
          <div className="mb-tags">{ids.map((id) => <span key={id} className="mb-tag">{id}</span>)}</div>
        )}
      </div>
    </div>
  );
}

function AlertCard({ a, expanded, onToggle, approve, reject }) {
  const p = a.proposal;
  return (
    <div className={`alert-card ${a.triage_rank === 1 ? "rank1" : ""}`}>
      <div className="alert-head" onClick={onToggle}>
        {a.triage_rank && <span className="rank">{a.triage_rank}</span>}
        <div className="who">
          <span className="a">{a.equipment_name}</span>
          <span className="b">{a.equipment_id} · {a.predicted_mode_label || a.predicted_mode}</span>
        </div>
        {a.status === "PENDING_APPROVAL" && <GovPill g={p?.governance} />}
        <div className="pr">
          <div className="v">{pct(a.failure_prob)}</div>
          <div className="l">{a.criticality}</div>
        </div>
      </div>

      {a.status === "ANALYZING" && (
        <div className="analyzing"><span className="spin" />Agent reasoning over the semantic model…</div>
      )}

      <AnimatePresence initial={false}>
        {expanded && p && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }} style={{ overflow: "hidden" }}>
            <Trace steps={p.trace} />
            {a.status === "PENDING_APPROVAL" && (
              <>
                <GovernanceVerdict g={p.governance} />
                <div className="actions-row">
                  <button className="btn-approve" onClick={() => approve(a.equipment_id)}>
                    ✓ Approve &amp; dispatch
                  </button>
                  <button className="btn-reject" onClick={() => reject(a.equipment_id)}>Reject</button>
                </div>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {a.status === "APPROVED" && a.result && (
        <div className="resolved-tag ok">
          ✓ Dispatched <span className="wo">{a.result.wo_number}</span> · recovered {money0(a.result.recovered_value)}
        </div>
      )}
      {a.status === "REJECTED" && (
        <div className="resolved-tag bad">⚠ Rejected — asset running to unplanned failure…</div>
      )}
      {a.status === "FAILED" && a.result && (
        <div className="resolved-tag bad">✕ Unplanned failure · loss {money0(a.result.loss)} · {a.result.downtime_hours}h down</div>
      )}
    </div>
  );
}

function Trace({ steps }) {
  return (
    <div className="trace">
      <AnimatePresence>
        {(steps || []).map((s, i) => (
          <motion.div key={i} className={`step ${s.actor}`}
            initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.08 }}>
            <span className="marker">{actorGlyph[s.actor] || "•"}</span>
            <div className="body">
              <div className="t">{s.title}</div>
              <div className="x">{s.text}</div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

/* ------------------------------------------------------ Business panel ---- */
function BusinessPanel({ biz }) {
  const oeeBase = biz.oee_baseline ?? 0.712;
  const oeeTarget = biz.oee_target ?? 0.855;
  const prevented = biz.events_prevented || 0;
  const net = biz.net_value || 0;
  return (
    <section className="panel">
      <div className="panel-head"><h2>Business Value</h2>
        <span className="count">illustrative · editable in config</span></div>
      <div className="panel-body">
        <div className="biz">
          <div className="stat pos">
            <div className="l">Recovered value</div>
            <div className="v"><Count value={biz.recovered_value || 0} money /></div>
            <div className="s">{prevented} event{prevented === 1 ? "" : "s"} prevented</div>
          </div>
          <div className={"stat " + (net >= 0 ? "pos" : "neg")}>
            <div className="l">Net impact</div>
            <div className="v"><Count value={net} money signed /></div>
            <div className="s">{biz.events_failed ? `${biz.events_failed} unplanned loss` : "no losses"}</div>
          </div>
          <div className="stat accent">
            <div className="l">Per-event upside</div>
            <div className="v">{money0(biz.recovered_per_event || 0)}</div>
            <div className="s">planned vs unplanned swap</div>
          </div>
          <div className="stat">
            <div className="l">Fleet projection</div>
            <div className="v">{money0(biz.fleet_projection || 0)}</div>
            <div className="s">across {biz.fleet_lines || 7} lines</div>
          </div>
        </div>
        <div style={{ marginTop: 14 }}>
          <div className="l" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.7, color: "#5f6d8f", fontWeight: 600 }}>
            Line OEE
          </div>
          <div className="oee">
            <div className="oee-bar">
              <div className="oee-fill" style={{ width: `${(prevented ? oeeBase + 0.031 : oeeBase) * 100}%` }} />
            </div>
            <div className="oee-nums">
              {pct(oeeBase)} → <b>{pct(prevented ? Math.min(oeeTarget, oeeBase + 0.031) : oeeBase)}</b>
              <span style={{ color: "#5f6d8f" }}> (target {pct(oeeTarget)})</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// count-up animated number
function Count({ value, money: isMoney, signed }) {
  const [disp, setDisp] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const start = from.current, end = value, t0 = performance.now(), dur = 650;
    let raf;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      setDisp(start + (end - start) * e);
      if (k < 1) raf = requestAnimationFrame(step);
      else from.current = end;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  const s = (signed && disp > 0 ? "+" : "") + (isMoney ? money0(disp) : Math.round(disp));
  return <>{s}</>;
}

/* -------------------------------------------------------------- Toasts ---- */
// Stable identity for an engine event, so each transition is surfaced only once.
const eventKey = (ev) => `${ev.kind}:${ev.id}:${ev.phase || ""}`;

// Map an engine event to a user-facing toast — or null to drop it as noise.
// Alerts (red) are alarms that need attention; notifications (green) are
// informative outcomes. Anything not informative returns null and never shows.
function toastFor(ev, name) {
  switch (ev.kind) {
    case "alert":
      // only the moment it crosses the threshold is informative; the later
      // "ready" phase (proposal populated) is not a new thing to announce.
      return ev.phase === "analyzing"
        ? { category: "alert", kind: "bad", msg: `⚠ Alert · ${name(ev.id)} crossed the action threshold` }
        : null;
    case "failure":
      return { category: "alert", kind: "bad", msg: `✕ Unplanned failure · ${name(ev.id)}` };
    case "resolved":
      return { category: "notification", kind: "ok", msg: `✓ Notification · work order dispatched for ${name(ev.id)}` };
    default:
      return null; // rejected / reset / ready — surfaced elsewhere in the UI, not as a toast
  }
}

function Toasts({ lastEvent, fleet }) {
  const [toasts, setToasts] = useState([]);
  const seq = useRef(0);
  const seen = useRef(new Set());   // event keys already surfaced — the dedupe queue
  const timers = useRef([]);
  const fleetRef = useRef(fleet);   // latest fleet for name lookups, WITHOUT re-running on every tick
  fleetRef.current = fleet;

  // cancel any pending removal timers on unmount
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  useEffect(() => {
    // a reset clears lastEvent → forget history so a fresh run can alert again
    if (!lastEvent) { seen.current.clear(); return; }
    const key = eventKey(lastEvent);
    if (seen.current.has(key)) return;                 // already shown once — dedupe
    const name = (id) => fleetRef.current.find((a) => a.equipment_id === id)?.name || id;
    const t = toastFor(lastEvent, name);
    if (!t) return;                                    // not informative — drop
    seen.current.add(key);
    const id = ++seq.current;
    // keep only the 3 most recent so the stack can never wall off the layout
    setToasts((list) => [...list, { id, ...t }].slice(-3));
    const to = setTimeout(() => setToasts((list) => list.filter((x) => x.id !== id)), 3600);
    timers.current.push(to);
  }, [lastEvent]);                                     // NB: not `fleet` — that fired every tick

  return (
    <div className="toast-wrap">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div key={t.id} className={`toast ${t.kind}`}
            initial={{ opacity: 0, y: 20, scale: 0.9 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}>{t.msg}</motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
