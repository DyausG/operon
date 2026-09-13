import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useEngine } from "./useEngine.js";
import {
  ClassIcon,
  ShieldMark,
  ShieldCheckIcon,
  PlayIcon,
  PauseIcon,
  ResetIcon,
  SparkIcon,
  CpuIcon,
  CloudIcon,
  FactoryIcon,
  CheckCircleIcon,
  AlertTriangleIcon,
  ActivityIcon,
  TrendingUpIcon,
  money0,
  pct,
  STATUS_ORDER,
} from "./lib.jsx";

const FLOW = ["OPEN", "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED", "PLANNING", "INTERVENTION_VALIDATED", "AWAITING_APPROVAL", "READY", "EXECUTING", "OBSERVING", "CLOSED"];
const FLOW_LABELS = { OPEN: "Signal", INVESTIGATING: "Investigate", AWAITING_EVIDENCE: "Evidence", DIAGNOSIS_VALIDATED: "Diagnosis", PLANNING: "Plan", INTERVENTION_VALIDATED: "Validated", AWAITING_APPROVAL: "Approval", READY: "Ready", EXECUTING: "Execute", OBSERVING: "Observe", CLOSED: "Recovered" };
const SERIES = ["#ff5d73", "#f6b94a", "#748ffc", "#30c7d2", "#31d6a0", "#b478f2"];

export default function App() {
  const { state, approve, reject, reset, stop, resume, startDemo } = useEngine();
  const alerts = useMemo(() => Object.values(state.alerts).sort((a, b) => (a.triage_rank || 99) - (b.triage_rank || 99)), [state.alerts]);
  const [selected, setSelected] = useState(null);
  const active = alerts.filter((a) => !["CLOSED", "FAILED", "CANCELLED"].includes(a.lifecycle?.phase || a.status));
  const focusId = selected || active[0]?.equipment_id || alerts[0]?.equipment_id || state.fleet[0]?.equipment_id;
  const incident = alerts.find((a) => a.equipment_id === focusId) || null;
  return <div className="app-shell">
    <Header state={state} onReset={() => { setSelected(null); reset(); }} onStop={stop} onResume={resume}
      onDemo={() => { const target = focusId || "AC-COMP-01"; setSelected(target); startDemo(target); }} />
    <ImpactBar state={state} alerts={alerts} />
    {state.action.error && <div className="action-error">Action refused: {state.action.error}</div>}
    <main className="workspace">
      <aside className="overview-stack"><FleetPanel fleet={state.fleet} selected={focusId} onSelect={setSelected} /><RiskChart state={state} focusId={focusId} /></aside>
      <section className="command-stack"><IncidentQueue alerts={alerts} selected={focusId} onSelect={setSelected} />
        {incident ? <IncidentCommand incident={incident} state={state} approve={approve} reject={reject} /> : <EmptyCommand threshold={state.triggerThreshold} />}
      </section>
    </main>
  </div>;
}

function Header({ state, onReset, onStop, onResume, onDemo }) {
  const totalSecs = Math.max(0, Math.floor((state.plantMin || 0) * 60));
  const hrs = Math.floor(totalSecs / 3600);
  const mins = Math.floor((totalSecs % 3600) / 60);
  const secs = totalSecs % 60;
  const timerStr = `T+ ${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;

  const provenance = state.reasoningProvenance || {};
  const isAgentcore = provenance.backend === "agentcore";
  const isLive = provenance.status === "available" || isAgentcore;
  const streamStatus = !state.connected ? "offline" : state.running ? "online" : "paused";
  const streamLabel = !state.connected ? "RECONNECTING" : state.running ? "LIVE" : "PAUSED";

  const formatDemoPhase = (status) => {
    if (!status) return "Active";
    const clean = String(status).toLowerCase().replaceAll("_", " ");
    if (clean === "failed") return "Intervention Discarded";
    return clean.charAt(0).toUpperCase() + clean.slice(1);
  };

  return (
    <header className="topbar">
      {/* Left: Identity & State Enclosure */}
      <div className="topbar-left">
        <div className="brand">
          <span className="brand-mark"><ShieldMark /></span>
          <div className="brand-text">
            <b>{state.meta.appName || "Operon"}</b>
            <small>Industrial Reliability Command</small>
          </div>
        </div>
        <div className="guardrail-badge" title="Deterministic application gate enforces human sign-off on all machine interventions">
          <ShieldCheckIcon size={12} color="var(--green)" />
          <span><b>Policy Gate:</b> Enforced (HITL)</span>
        </div>
      </div>

      {/* Center: System & Agent Telemetry */}
      <div className="topbar-center">
        {isLive ? (
          <div className="status-pill runtime online" title="Amazon Bedrock reasoning runtime operational via AgentCore">
            <CloudIcon size={13} />
            <span className="pill-dot" />
            <span className="pill-text">Bedrock Live · 120ms</span>
          </div>
        ) : (
          <div className="status-pill runtime standby" title="Deterministic local reasoning runtime active">
            <CpuIcon size={13} />
            <span className="pill-dot" />
            <span className="pill-text">Agent Reasoning: Local Fallback</span>
          </div>
        )}

        {state.demoScenario.active ? (
          <div className="status-pill env demo" title="Guided reliability demo scenario active">
            <SparkIcon size={13} />
            <span className="pill-dot" />
            <span className="pill-text">Demo Mode · {formatDemoPhase(state.demoScenario.status)}</span>
          </div>
        ) : (
          <div className="status-pill env" title="Nominal factory telemetry simulation">
            <FactoryIcon size={13} />
            <span className="pill-dot" />
            <span className="pill-text">Simulation Plant</span>
          </div>
        )}
      </div>

      {/* Right: Controls & Clock Toolbar */}
      <div className="topbar-right">
        <div className="telemetry-cluster">
          <span className={`stream-indicator ${streamStatus}`} title={`Connection: ${streamLabel}`}>
            <i className="pulse-dot" />
            <span className="stream-label">{streamLabel}</span>
          </span>
          <span className="telemetry-divider" />
          <span className="digital-timer" title="Elapsed Plant Simulation Time (T+ HH:MM:SS)">
            {timerStr}
          </span>
        </div>

        <div className="segmented-toolbar">
          <button
            className="toolbar-btn icon-only"
            title={state.running ? "Pause simulation" : "Resume simulation"}
            onClick={state.running ? onStop : onResume}
          >
            {state.running ? <PauseIcon size={12} /> : <PlayIcon size={12} />}
          </button>
          <button
            className="toolbar-btn demo-btn"
            disabled={!!state.action.pending}
            title="Trigger guided end-to-end reliability incident scenario"
            onClick={onDemo}
          >
            <SparkIcon size={12} />
            <span>{state.demoScenario.active ? "Restart Demo" : "Guided Demo"}</span>
          </button>
          <button
            className="toolbar-btn reset-btn"
            title="Reset fleet state, clear alerts, and restore nominal telemetry"
            onClick={onReset}
          >
            <ResetIcon size={12} />
            <span>Reset</span>
          </button>
        </div>
      </div>
    </header>
  );
}

function ImpactBar({ state, alerts }) {
  const biz = state.business || {};
  const fleet = state.fleet || [];

  // Card 1: Fleet Operational Health
  const criticalAssets = fleet.filter((a) => a.status === "CRITICAL");
  const warningAssets = fleet.filter((a) => a.status === "WARNING");
  const nominalAssets = fleet.filter((a) => ["HEALTHY", "SCHEDULED", "NOMINAL"].includes(a.status));
  const totalAssets = fleet.length || 8;
  const hasCritical = criticalAssets.length > 0;
  const hasWarning = warningAssets.length > 0;

  let fleetMetric = `${totalAssets} / ${totalAssets} Nominal`;
  if (hasCritical && hasWarning) {
    fleetMetric = `${warningAssets.length} Warn · ${criticalAssets.length} Critical`;
  } else if (hasCritical) {
    fleetMetric = `${nominalAssets.length} Nominal · ${criticalAssets.length} Critical`;
  } else if (hasWarning) {
    fleetMetric = `${nominalAssets.length} Nominal · ${warningAssets.length} Warning`;
  }

  // Card 2: Incident & Agent Pipeline
  const activeAlert = alerts.find((a) => !["CLOSED", "FAILED", "CANCELLED"].includes(a.lifecycle?.phase || a.status));
  const investigating = alerts.filter((a) =>
    ["OPEN", "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED", "PLANNING"].includes(
      a.lifecycle?.phase || a.status
    )
  ).length;
  const observing = alerts.filter((a) => (a.lifecycle?.phase || a.status) === "OBSERVING").length;

  let pipelineSubtext = "Continuous telemetry surveillance";
  if (activeAlert) {
    const phase = activeAlert.lifecycle?.phase || activeAlert.status;
    if (["OPEN", "INVESTIGATING", "AWAITING_EVIDENCE"].includes(phase)) {
      pipelineSubtext = `Correlating telemetry (${activeAlert.equipment_id})`;
    } else if (["DIAGNOSIS_VALIDATED", "PLANNING", "INTERVENTION_VALIDATED"].includes(phase)) {
      pipelineSubtext = `Formulating repair plan (${activeAlert.equipment_id})`;
    } else if (phase === "AWAITING_APPROVAL") {
      pipelineSubtext = `Awaiting human sign-off (${activeAlert.equipment_id})`;
    } else if (["EXECUTING", "READY"].includes(phase)) {
      pipelineSubtext = `Dispatching intervention (${activeAlert.equipment_id})`;
    } else if (phase === "OBSERVING") {
      pipelineSubtext = `Post-repair recovery verification (${activeAlert.equipment_id})`;
    }
  }

  // Card 3: Line OEE
  const currentOee = biz.oee_baseline ?? 0.71;
  const targetOee = biz.oee_target ?? 0.85;
  const isOeeBelow = currentOee < targetOee;

  let oeeSubtext = "Availability: 94% · Performance: 76%";
  if (hasCritical) {
    oeeSubtext = `Bottleneck: ${criticalAssets[0].equipment_id} (-12% Avail)`;
  } else if (hasWarning) {
    oeeSubtext = `Degraded: ${warningAssets[0].equipment_id} (-4% Avail)`;
  }

  // Card 4: Averted Downtime Value
  const recoveredVal = biz.recovered_value || 0;
  const eventsPrevented = biz.events_prevented || 0;
  const dtCostFormatted = biz.downtime_cost_per_hour
    ? `$${Math.round(biz.downtime_cost_per_hour / 1000)}k/hr`
    : "$25k/hr";
  const hasActiveRisk = hasCritical || investigating > 0;

  // Card 5: Net Economic Impact
  const netVal = biz.net_value || 0;
  const netClass = netVal > 0 ? "positive" : netVal < 0 ? "negative" : "neutral";
  const formattedNet = netVal > 0 ? `+${money0(netVal)}` : netVal < 0 ? `-${money0(Math.abs(netVal))}` : "$0";

  return (
    <section className="kpi-strip" aria-label="Operational and economic summary">
      {/* Zone 1: Operational Fleet Health */}
      <div className="kpi-zone operational">
        {/* Card 1: Monitored Assets & Fleet Health */}
        <div className={`kpi-card ${hasCritical ? "has-alert" : hasWarning ? "has-warning" : ""}`}>
          <div className="kpi-head">
            <span className="kpi-title">FLEET HEALTH</span>
            <span className="kpi-subhead">{totalAssets} Monitored</span>
          </div>
          <div className="kpi-value-row">
            <b className="kpi-metric">{fleetMetric}</b>
          </div>
          <div className="kpi-foot">
            {hasCritical ? (
              <span className="kpi-subtext critical" title={`Critical failure risk on ${criticalAssets[0].equipment_id}`}>
                <AlertTriangleIcon size={11} color="var(--red)" />
                <span>Critical: {criticalAssets[0].equipment_id}{criticalAssets.length > 1 ? ` (+${criticalAssets.length - 1})` : ""}</span>
              </span>
            ) : hasWarning ? (
              <span className="kpi-subtext warn" title={`Warning state on ${warningAssets[0].equipment_id}`}>
                <AlertTriangleIcon size={11} color="var(--amber)" />
                <span>Warning: {warningAssets[0].equipment_id}{warningAssets.length > 1 ? ` (+${warningAssets.length - 1})` : ""}</span>
              </span>
            ) : (
              <span className="kpi-subtext nominal">
                <CheckCircleIcon size={11} color="var(--green)" />
                <span>All {totalAssets} Systems Nominal</span>
              </span>
            )}
          </div>
        </div>

        {/* Card 2: Active Incidents & Response */}
        <div className={`kpi-card ${investigating > 0 ? "has-investigation" : ""}`}>
          <div className="kpi-head">
            <span className="kpi-title">ACTIVE INCIDENTS</span>
            <span className="kpi-subhead">Agent Pipeline</span>
          </div>
          <div className="kpi-value-row">
            {investigating > 0 ? (
              <b className="kpi-metric warn">{investigating} Investigating</b>
            ) : observing > 0 ? (
              <b className="kpi-metric positive">{observing} In Recovery</b>
            ) : (
              <b className="kpi-metric neutral">Idle</b>
            )}
          </div>
          <div className="kpi-foot">
            <span className={`kpi-subtext ${activeAlert ? "active-recovery" : ""}`}>
              {activeAlert ? (
                <ActivityIcon size={11} color="var(--cyan)" />
              ) : (
                <CheckCircleIcon size={11} color="var(--faint)" />
              )}
              <span>{pipelineSubtext}</span>
            </span>
          </div>
        </div>

        {/* Card 3: Line OEE with benchmark marker and bottleneck attribution */}
        <div className="kpi-card">
          <div className="kpi-head">
            <span className="kpi-title">LINE OEE</span>
            <span className="kpi-subhead">Target: {pct(targetOee)}</span>
          </div>
          <div className="kpi-value-row">
            <b className="kpi-metric">{pct(currentOee)}</b>
          </div>
          <div className="kpi-foot oee-foot">
            <div className="oee-gauge-track" title={`Current OEE: ${pct(currentOee)}, Target: ${pct(targetOee)}`}>
              <div
                className={`oee-gauge-fill ${isOeeBelow ? "below-target" : "on-target"}`}
                style={{ width: `${Math.min(100, Math.max(0, currentOee * 100))}%` }}
              />
              <div
                className="oee-target-marker"
                style={{ left: `${Math.min(99, targetOee * 100)}%` }}
                title={`Target Benchmark: ${pct(targetOee)}`}
              />
            </div>
            <span className={`oee-bottleneck ${hasCritical ? "critical" : hasWarning ? "warn" : ""}`}>
              {oeeSubtext}
            </span>
          </div>
        </div>
      </div>

      {/* Visual Separation: Physical Telemetry vs Economic ROI */}
      <div className="kpi-divider" aria-hidden="true" />

      {/* Zone 2: Economic Impact */}
      <div className="kpi-zone economic">
        {/* Card 4: Averted Downtime Value */}
        <div className={`kpi-card ${!hasActiveRisk && recoveredVal === 0 ? "is-standby" : ""}`}>
          <div className="kpi-head">
            <span className="kpi-title">AVERTED LOSS</span>
            <span className="kpi-subhead">Downtime Exposure</span>
          </div>
          <div className="kpi-value-row">
            {recoveredVal > 0 ? (
              <b className="kpi-metric positive">{money0(recoveredVal)}</b>
            ) : hasActiveRisk ? (
              <div className="kpi-standby-value">
                <b className="kpi-metric warn">~$25k At Risk</b>
              </div>
            ) : (
              <div className="kpi-standby-value">
                <b className="kpi-metric standby">$0</b>
                <span className="kpi-standby-pill">STANDBY</span>
              </div>
            )}
          </div>
          <div className="kpi-foot">
            {eventsPrevented > 0 ? (
              <span className="kpi-subtext positive-subtext">
                <TrendingUpIcon size={11} color="var(--green)" />
                <span>{eventsPrevented} {eventsPrevented === 1 ? "breakdown mitigated" : "breakdowns mitigated"}</span>
              </span>
            ) : hasActiveRisk ? (
              <span className="kpi-subtext warn-subtext">
                <AlertTriangleIcon size={11} color="var(--amber)" />
                <span>Unmitigated downtime exposure</span>
              </span>
            ) : (
              <span className="kpi-subtext standby">
                <span>{dtCostFormatted} baseline rate</span>
              </span>
            )}
          </div>
        </div>

        {/* Card 5: Net Economic Impact */}
        <div className={`kpi-card ${!hasActiveRisk && netVal === 0 ? "is-standby" : ""}`}>
          <div className="kpi-head">
            <span className="kpi-title">NET ROI</span>
            <span className="kpi-subhead">Realized Value</span>
          </div>
          <div className="kpi-value-row">
            {netVal !== 0 ? (
              <b className={`kpi-metric ${netClass}`}>{formattedNet}</b>
            ) : hasActiveRisk ? (
              <div className="kpi-standby-value">
                <b className="kpi-metric standby">Pending</b>
                <span className="kpi-standby-pill eval">EVALUATING</span>
              </div>
            ) : (
              <div className="kpi-standby-value">
                <b className="kpi-metric standby">$0</b>
                <span className="kpi-standby-pill">MONITORING</span>
              </div>
            )}
          </div>
          <div className="kpi-foot">
            <span className="kpi-subtext">
              {hasActiveRisk && netVal === 0
                ? "Awaiting intervention resolution"
                : "Net value after repair costs"}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function FleetPanel({ fleet, selected, onSelect }) {
  const sorted = [...fleet].sort((a, b) => (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || b.failure_prob - a.failure_prob);
  return <Panel title="Factory overview" meta="8-machine simulated floor"><div className="fleet-grid">{sorted.map((asset) => <AssetCard key={asset.equipment_id} asset={asset} selected={selected === asset.equipment_id} onClick={() => onSelect(asset.equipment_id)} />)}</div></Panel>;
}

function AssetCard({ asset, selected, onClick }) {
  return <button className={`asset-card ${asset.status.toLowerCase()} ${selected ? "selected" : ""}`} onClick={onClick}>
    <div className="asset-top"><span className="asset-icon"><ClassIcon cls={asset.equipment_class} /></span><span className="asset-name"><b>{asset.equipment_id}</b><small>{asset.name}</small></span><Status value={asset.status}>{asset.status}</Status></div>
    <div className="risk-row"><b>{pct(asset.failure_prob)}</b><span>24h risk</span></div><div className="asset-mode">{asset.predicted_mode && asset.predicted_mode !== "NONE" ? asset.predicted_mode_label : "Nominal signature"}</div><Spark point={asset.point} status={asset.status} />
  </button>;
}

function Spark({ point, status }) {
  const history = useRef([]); if (point) history.current = [...history.current, point.prob].slice(-26);
  const color = { CRITICAL: "#ff5d73", WARNING: "#f6b94a", SCHEDULED: "#67a5ff", HEALTHY: "#31d6a0", DOWN: "#7b849a" }[status];
  return <div className="spark"><ResponsiveContainer><AreaChart data={history.current.map((p, i) => ({ i, p }))}><YAxis hide domain={[0, 1]} /><Area dataKey="p" type="monotone" stroke={color} fill={color} fillOpacity={0.08} strokeWidth={1.5} dot={false} isAnimationActive={false} /></AreaChart></ResponsiveContainer></div>;
}

function RiskChart({ state, focusId }) {
  const ids = useMemo(() => { const value = new Set(state.fleet.filter((a) => a.status !== "HEALTHY").map((a) => a.equipment_id)); if (focusId) value.add(focusId); return [...value].slice(0, 6); }, [state.fleet, focusId]);
  const data = useMemo(() => { const times = new Map(); ids.forEach((id) => (state.histories[id] || []).forEach((point) => { if (!times.has(point.t)) times.set(point.t, { t: point.t }); times.get(point.t)[id] = point.prob; })); return [...times.values()].sort((a, b) => a.t - b.t).slice(-70); }, [ids, state.histories]);
  return <Panel title="Predictive signal" meta={`action gate ${pct(state.triggerThreshold)}`}><div className="risk-chart"><ResponsiveContainer><LineChart data={data} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}><CartesianGrid vertical={false} stroke="rgba(139,158,191,.09)" /><ReferenceArea y1={state.triggerThreshold} y2={1} fill="rgba(255,93,115,.06)" /><XAxis dataKey="t" tick={{ fill: "#67748b", fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={28} /><YAxis domain={[0, 1]} tickFormatter={(v) => Math.round(v * 100)} tick={{ fill: "#67748b", fontSize: 10 }} axisLine={false} tickLine={false} /><ReferenceLine y={state.triggerThreshold} stroke="#ff5d73" strokeDasharray="4 4" /><Tooltip formatter={(value) => pct(value)} contentStyle={{ background: "#101722", border: "1px solid #2a3547", borderRadius: 8 }} />{ids.map((id, i) => <Line key={id} dataKey={id} type="monotone" stroke={SERIES[i]} strokeWidth={focusId === id ? 2.4 : 1.4} strokeOpacity={focusId && focusId !== id ? .3 : 1} dot={false} connectNulls isAnimationActive={false} />)}</LineChart></ResponsiveContainer></div><div className="chart-legend">{ids.map((id, i) => <span key={id}><i style={{ background: SERIES[i] }} />{id}</span>)}</div></Panel>;
}

function IncidentQueue({ alerts, selected, onSelect }) {
  if (!alerts.length) return null;
  return <div className="incident-queue">{alerts.map((item) => <button key={item.incident_id} className={selected === item.equipment_id ? "selected" : ""} onClick={() => onSelect(item.equipment_id)}><span className={`phase-dot ${tone(item.lifecycle?.phase)}`} /><span><b>{item.equipment_id}</b><small>{item.lifecycle?.phase || item.status}</small></span><em>{pct(item.failure_prob)}</em></button>)}</div>;
}

function IncidentCommand({ incident, state, approve, reject }) {
  const lifecycle = incident.lifecycle || {}, view = lifecycle.read_model || {}, phase = lifecycle.phase || "OPEN";
  return <motion.div key={incident.incident_id} className="incident-command" initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}>
    <div className="incident-hero"><div><span className="eyebrow">Incident command center</span><h1>{incident.equipment_name}</h1><p><CopyId value={incident.incident_id} /> · {incident.equipment_id} · revision {lifecycle.revision}</p></div><div className="hero-risk"><small>24h failure risk</small><b>{pct(incident.failure_prob)}</b><span>{incident.predicted_mode_label || "Predictive anomaly"}</span></div><Status value={phase}>{phase.replaceAll("_", " ")}</Status></div>
    <Lifecycle phase={phase} events={view.events || []} /><Invariant />
    <div className="command-grid"><div className="command-column"><DiagnosisCard incident={incident} view={view} /><EvidenceCard evidence={view.evidence || []} /><AgentCard view={view} lifecycle={lifecycle} provenance={state.reasoningProvenance} /></div><div className="command-column"><InterventionCard incident={incident} view={view} /><ApprovalCard incident={incident} view={view} approve={approve} reject={reject} pending={state.action.pending} /><OutcomeCard incident={incident} view={view} /><EventCard events={view.events || []} /></div></div>
  </motion.div>;
}

function Lifecycle({ phase, events }) {
  const reached = new Set(events.filter((event) => event.event_type === "PHASE_CHANGED").map((event) => event.payload?.to).filter(Boolean)); reached.add("OPEN"); reached.add(phase);
  const currentIndex = FLOW.indexOf(phase), exceptional = ["ESCALATED", "EXECUTION_FAILED", "CANCELLED"].includes(phase);
  return <section className="lifecycle-block"><div className="section-title"><span>Authoritative lifecycle</span><small>committed application state</small></div><div className="lifecycle-flow">{FLOW.map((step, i) => { const done = reached.has(step) || (!exceptional && currentIndex >= 0 && i < currentIndex); return <div key={step} className={`${done ? "done" : ""} ${phase === step ? "current" : ""}`}><i>{done ? "✓" : i + 1}</i><span>{FLOW_LABELS[step]}</span></div>; })}{exceptional && <div className="exception current"><i>!</i><span>{phase.replaceAll("_", " ")}</span></div>}</div></section>;
}

function Invariant() { return <div className="invariant"><span>Prediction</span><i>≠</i><span>Diagnosis</span><i>≠</i><span>Intervention</span><i>≠</i><span>Approval</span><i>≠</i><span>Execution</span><i>≠</i><span>Outcome</span></div>; }

function DiagnosisCard({ incident, view }) {
  const diagnosis = view.diagnosis, verdict = [...(view.verdicts || [])].reverse().find((item) => item.target_kind === "diagnosis"), signal = (view.evidence || []).find((item) => item.kind === "model_signal");
  return <Card title="Evidence → diagnosis" icon="◎" meta={diagnosis ? "application validated" : "investigation active"}><div className="signal-box"><div><small>Predictive signal</small><b>{incident.predicted_mode_label || "Elevated failure risk"}</b></div><Status value="signal">prediction, not cause</Status></div>
    {signal?.payload?.attribution?.length > 0 && <div className="drivers">{signal.payload.attribution.slice(0, 3).map((item) => <span key={item.feature}><b>{item.label || item.feature}</b> {Number(item.value).toFixed(1)} <em>+{Number(item.contribution).toFixed(2)}</em></span>)}</div>}
    {diagnosis ? <div className="diagnosis"><span className="validated-mark">✓</span><div><small>Validated diagnosis</small><h3>{diagnosis.conclusion}</h3><p>{diagnosis.evidence_ids.length} cited evidence records · confidence {diagnosis.confidence == null ? "not asserted" : pct(diagnosis.confidence)}</p></div></div> : <EmptyLine text="No diagnosis has crossed the application validation boundary." />}{verdict && <Verdict item={verdict} />}</Card>;
}

function EvidenceCard({ evidence }) {
  const [expanded, setExpanded] = useState(false), items = [...evidence].reverse();
  return <Card title="Evidence ledger" icon="▤" meta={`${evidence.length} durable records`}><div className="evidence-list">{items.slice(0, expanded ? 12 : 5).map((item) => <div key={item.id} className="evidence-row"><span className={`source-mark ${item.provenance?.toLowerCase()}`}>{item.kind === "model_signal" ? "◆" : "●"}</span><div><b>{item.kind.replaceAll("_", " ")}</b><p>{item.summary}</p><small>{item.source_system} · {item.provenance} · {item.quality}</small></div><CopyId value={item.id} short /></div>)}</div>{items.length > 5 && <button className="inline-btn" onClick={() => setExpanded(!expanded)}>{expanded ? "Show less" : `Show ${items.length - 5} more`}</button>}</Card>;
}

function AgentCard({ view, lifecycle, provenance }) {
  const runs = view.agent_runs || [], run = runs[runs.length - 1], assessments = run?.assessments || [], delegations = run?.delegations || [], baseline = (view.agent_actions || []).filter((item) => item.actor === "operon.investigation");
  return <Card title="Strands agent activity" icon="✦" meta={run ? `${run.status} · ${run.tool_calls} tool calls` : "awaiting reasoning runtime"}><div className="agent-boundary"><span>Advisory reasoning</span><i>cannot transition lifecycle</i></div>{run ? <><div className="run-strip"><span><small>Run ID</small><CopyId value={run.run_id} /></span><span><small>Stage</small><b>{run.stage}</b></span><span><small>Backend</small><b>{run.runtime_identity?.backend || provenance?.backend || "local"}</b></span></div>{run.summary && <p className="run-summary">{run.summary}</p>}<div className="agent-list"><AgentLine name="Reliability Supervisor" role="supervisor" status={run.status} text={run.disposition} />{delegations.map((item) => <AgentLine key={item.key} name={roleName(item.role)} role={item.role} status={item.status} text={item.question} />)}{assessments.filter((item) => !delegations.some((d) => d.key === item.key)).map((item) => <AgentLine key={item.key} name={roleName(inferRole(item.assessment))} role={inferRole(item.assessment)} status="SUCCEEDED" text={item.assessment.reasoning_summary} />)}</div>{run.blockers?.length > 0 && <ul className="blockers">{run.blockers.map((item) => <li key={item}>{item}</li>)}</ul>}</> : <>{baseline.map((item) => <AgentLine key={item.id} name="Application Investigator" role="system" status={item.status} text={item.summary} />)}<EmptyLine text={lifecycle.supervisor_available ? "Supervisor run will appear here." : "Durable evidence is ready; reasoning runtime is not connected."} /></>}</Card>;
}

function AgentLine({ name, role, status, text }) { return <div className="agent-line"><span className={`agent-avatar ${role}`}>{role === "supervisor" ? "S" : role?.[0]?.toUpperCase() || "A"}</span><div><b>{name}</b><p>{text || "Structured report recorded"}</p></div><Status value={status}>{status}</Status></div>; }

function InterventionCard({ incident, view }) {
  const item = view.intervention, binding = view.binding, verdict = [...(view.verdicts || [])].reverse().find((entry) => entry.target_kind === "intervention");
  return <Card title="Proposed intervention" icon="⌁" meta={item?.status || "not proposed"}>{item ? <><div className="plan-head"><div><small>Typed maintenance action</small><h3>{item.steps[0]?.parameters?.description || item.steps[0]?.capability?.replaceAll("_", " ")}</h3></div><Status value={item.risk}>{item.risk} risk</Status></div><div className="plan-grid"><KV label="Capability" value={item.steps[0]?.capability} /><KV label="Technician" value={binding?.technician_id} /><KV label="Estimated cost" value={money0(item.estimated_cost)} /><KV label="Downtime" value={`${item.estimated_downtime_minutes} min`} /><KV label="Window" value={formatWindow(item.window_start, item.window_end)} /><KV label="Avoided loss" value={money0(item.estimated_avoided_loss)} /></div>{binding?.parts?.length > 0 && <div className="parts"><small>Reserved parts</small>{binding.parts.map((part) => <span key={part.part_id}>{part.quantity}× {part.part_id}</span>)}</div>}{verdict && <Verdict item={verdict} />}</> : <EmptyLine text={incident.lifecycle?.phase === "DIAGNOSIS_VALIDATED" ? "Diagnosis accepted. Maintenance planning is next." : "No intervention has been promoted."} />}</Card>;
}

function ApprovalCard({ incident, view, approve, reject, pending }) {
  const phase = incident.lifecycle?.phase, current = [...(view.requirements || [])].reverse()[0], decision = [...(view.approval_decisions || [])].reverse()[0], canApprove = phase === "AWAITING_APPROVAL" && incident.lifecycle?.requirement_id;
  if (!current && !canApprove) return <Card title="Governance & approval" icon="◇" meta="application gate"><EmptyLine text="No approval requirement has been issued." /></Card>;
  return <Card title="Governance & approval" icon="◇" meta={current?.policy_version || "policy evaluated"} accent={canApprove ? "approval" : ""}><div className="governance-result"><span className="shield-small">◆</span><div><small>Application policy result</small><b>{canApprove ? "Human approval required" : current?.status || "Evaluated"}</b><p>{(current?.conditions || []).join(" · ") || "Exact promoted work package binding enforced."}</p></div></div>{current && <div className="binding-strip"><span>Bound to</span><CopyId value={current.intervention_id} short /><span>hash</span><CopyId value={current.intervention_hash} short /></div>}{canApprove && <div className="approval-actions"><button disabled={!!pending} onClick={() => approve(incident)}>Approve exact plan & dispatch</button><button disabled={!!pending} className="reject" onClick={() => reject(incident)}>Reject</button></div>}{decision && <div className={`decision ${decision.decision.toLowerCase()}`}><b>{decision.decision}</b><span>{decision.actor_role} · {decision.actor_id}</span><small>bound to the viewed intervention hash</small></div>}</Card>;
}

function OutcomeCard({ incident, view }) {
  const receipts = view.execution_receipts || [], receipt = receipts[receipts.length - 1], plans = view.observation_plans || [], plan = plans[plans.length - 1], outcomes = view.outcomes || [], outcome = outcomes[outcomes.length - 1], phase = incident.lifecycle?.phase;
  return <Card title="Execution & outcome" icon="◉" meta="deterministic verification"><div className="outcome-flow"><div className={receipt ? "done" : ""}><i>{receipt ? "✓" : "1"}</i><span><b>Execution</b><small>{receipt?.status || "not dispatched"}</small></span></div><em>→</em><div className={plan ? "active" : ""}><i>{plan ? "◌" : "2"}</i><span><b>Observe</b><small>{plan ? "post-maintenance telemetry" : "not started"}</small></span></div><em>→</em><div className={outcome ? "done" : ""}><i>{outcome ? "✓" : "3"}</i><span><b>Verify</b><small>{outcome?.result || "not established"}</small></span></div></div>{receipt && <div className="receipt"><span><small>Execution receipt</small><CopyId value={receipt.id} /></span><Status value={receipt.status}>{receipt.status}</Status><p>{Object.entries(receipt.external_ids || {}).map(([key, value]) => `${key}: ${value}`).join(" · ") || receipt.adapter}</p></div>}{phase === "OBSERVING" && !outcome && <div className="observing-callout"><span className="pulse-ring" /><div><b>Execution confirmed — recovery not yet established</b><p>Operon is evaluating telemetry after the frozen observation boundary.</p></div></div>}{outcome && <div className={`outcome-result ${tone(outcome.result)}`}><b>{outcome.result.replaceAll("_", " ")}</b><p>{outcome.reason}</p><div>{Object.entries(outcome.before_metrics || {}).slice(0, 3).map(([key, value]) => <span key={`b-${key}`}>{key}: {Number(value).toFixed(2)} before</span>)}{Object.entries(outcome.after_metrics || {}).slice(0, 3).map(([key, value]) => <span key={`a-${key}`}>{key}: {Number(value).toFixed(2)} after</span>)}</div></div>}{!receipt && <EmptyLine text="No governed execution receipt exists." />}</Card>;
}

function EventCard({ events }) { return <Card title="Application activity" icon="⋮" meta={`${events.length} committed events`}><div className="event-list">{[...events].reverse().slice(0, 8).map((event) => <div key={event.id}><i className={tone(event.event_type)} /><span><b>{event.event_type.replaceAll("_", " ")}</b><small>revision {event.revision} · {relativeTime(event.created_at)}</small></span></div>)}</div></Card>; }
function EmptyCommand({ threshold }) { return <div className="empty-command"><ShieldMark /><h2>Operon is monitoring the factory</h2><p>A predictive signal at {pct(threshold)} opens a durable incident. Every step after that is evidence-bound and independently governed.</p><Invariant /><div className="empty-pipeline">Telemetry → predictive signal → incident → investigation → human-governed action → observed outcome</div></div>; }
function Panel({ title, meta, children }) { return <section className="panel"><div className="panel-title"><h2>{title}</h2><span>{meta}</span></div>{children}</section>; }
function Card({ title, icon, meta, accent = "", children }) { return <section className={`detail-card ${accent}`}><div className="card-title"><span>{icon}</span><h2>{title}</h2><small>{meta}</small></div>{children}</section>; }
function Status({ value, children }) { return <span className={`status ${tone(value)}`}>{children}</span>; }
function KV({ label, value }) { return <div className="kv"><small>{label}</small><b>{value || "Not recorded"}</b></div>; }
function EmptyLine({ text }) { return <div className="empty-line"><i />{text}</div>; }
function CopyId({ value, short = false }) { if (!value) return <span>—</span>; return <code title={value}>{short ? `${value.slice(0, 7)}…` : value.length > 22 ? `${value.slice(0, 12)}…${value.slice(-5)}` : value}</code>; }
function Verdict({ item }) { return <div className={`verdict ${tone(item.decision)}`}><b>{item.decision === "ACCEPT" ? "✓ Critic + application validation passed" : item.decision}</b>{(item.blocking_issues || []).length > 0 && <p>{item.blocking_issues.join(" · ")}</p>}<small>{item.validation_policy_version || "validation policy"}</small></div>; }
function tone(value = "") { const v = String(value).toUpperCase(); if (["HEALTHY", "CLOSED", "CONFIRMED", "ACCEPT", "APPROVE", "APPROVED", "SUCCEEDED", "VERIFIED_RECOVERY", "READY"].includes(v)) return "good"; if (["WARNING", "AWAITING_APPROVAL", "AWAITING_EVIDENCE", "OBSERVING", "PENDING", "CONDITIONS", "SIGNAL"].includes(v)) return "warn"; if (["CRITICAL", "ESCALATED", "EXECUTION_FAILED", "FAILED", "REJECT", "REJECTED", "REGRESSED", "NOT_RECOVERED", "ERROR"].includes(v)) return "bad"; if (v.includes("CLOSED") || v.includes("OUTCOME_RECORDED")) return "good"; if (v.includes("EXECUTION") || v.includes("APPROVAL")) return "warn"; return "info"; }
function roleName(role) { return ({ diagnostic: "Diagnostic Specialist", engineering: "Engineering Specialist", operations: "Operations Specialist", critic: "Critic / Validator", planner: "Maintenance Planner", supervisor: "Reliability Supervisor" })[role] || "Specialist"; }
function inferRole(value = {}) { if ("competing_hypotheses" in value) return "diagnostic"; if ("intervention_feasibility" in value) return "engineering"; if ("resource_feasibility" in value) return "operations"; if ("recommendation" in value) return "critic"; if ("proposed_steps" in value) return "planner"; return "agent"; }
function formatWindow(start, end) { if (!start) return null; const fmt = (v) => new Date(v).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); return `${fmt(start)} – ${fmt(end)}`; }
function relativeTime(value) { return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""; }
