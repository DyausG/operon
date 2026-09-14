import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useEngine } from "./useEngine.js";
import { TriageExceptionRail } from "./components/TriageExceptionRail.jsx";
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
  CopyIcon,
  LockIcon,
  UnlockIcon,
  EyeIcon,
  RefreshCwIcon,
  ZapIcon,
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
  const {
    state,
    approve,
    reject,
    verifyOutcome,
    reset,
    stop,
    resume,
    startDemo,
    refreshState,
    clearError,
  } = useEngine();
  const alerts = useMemo(
    () => Object.values(state.alerts).sort((a, b) => (a.triage_rank || 99) - (b.triage_rank || 99)),
    [state.alerts]
  );

  const [selectedEquipmentId, setSelectedEquipmentId] = useState(null);
  const [selectedIncidentId, setSelectedIncidentId] = useState(null);
  const [sessionFilter, setSessionFilter] = useState("ACTIVE"); // "ACTIVE" | "PAST" | "NOMINAL"

  const activeAlerts = useMemo(
    () => alerts.filter((a) => !["CLOSED", "FAILED", "CANCELLED"].includes(a.lifecycle?.phase || a.status)),
    [alerts]
  );

  const resolvedAlerts = useMemo(
    () => alerts.filter((a) => ["CLOSED", "FAILED", "CANCELLED"].includes(a.lifecycle?.phase || a.status)),
    [alerts]
  );

  // Resolved equipment in focus
  const focusEquipmentId = selectedEquipmentId || activeAlerts[0]?.equipment_id || state.fleet[0]?.equipment_id || "AC-COMP-01";
  const focusedAsset = state.fleet.find((a) => a.equipment_id === focusEquipmentId) || state.fleet[0] || {
    equipment_id: focusEquipmentId,
    name: focusEquipmentId,
    equipment_class: "compressor",
    status: "HEALTHY",
    failure_prob: 0.01,
  };

  // Machine-scoped active and resolved incidents (only for the selected machine)
  const assetActiveIncidents = useMemo(
    () => activeAlerts.filter((a) => a.equipment_id === focusEquipmentId),
    [activeAlerts, focusEquipmentId]
  );

  const assetResolvedIncidents = useMemo(
    () => resolvedAlerts.filter((a) => a.equipment_id === focusEquipmentId),
    [resolvedAlerts, focusEquipmentId]
  );

  // Resolve incident based on active view and selection (strictly scoped to focused asset)
  const currentActiveIncident = useMemo(() => {
    if (selectedIncidentId) {
      const inc = assetActiveIncidents.find((a) => a.incident_id === selectedIncidentId);
      if (inc) return inc;
    }
    return assetActiveIncidents[0] || null;
  }, [selectedIncidentId, assetActiveIncidents]);

  const currentPastIncident = useMemo(() => {
    if (selectedIncidentId) {
      const inc = assetResolvedIncidents.find((a) => a.incident_id === selectedIncidentId);
      if (inc) return inc;
    }
    return assetResolvedIncidents[0] || null;
  }, [selectedIncidentId, assetResolvedIncidents]);

  const handleSelectAsset = (equipmentId) => {
    setSelectedEquipmentId(equipmentId);
    const activeInc = activeAlerts.find((a) => a.equipment_id === equipmentId);
    const pastInc = resolvedAlerts.find((a) => a.equipment_id === equipmentId);

    if (activeInc) {
      setSelectedIncidentId(activeInc.incident_id);
      setSessionFilter("ACTIVE");
    } else if (pastInc && sessionFilter === "PAST") {
      setSelectedIncidentId(pastInc.incident_id);
    } else {
      setSelectedIncidentId(null);
      setSessionFilter("NOMINAL");
    }
  };

  const handleSelectIncident = (incidentItem) => {
    setSelectedIncidentId(incidentItem.incident_id);
    setSelectedEquipmentId(incidentItem.equipment_id);
    const isPast = ["CLOSED", "FAILED", "CANCELLED"].includes(incidentItem.lifecycle?.phase || incidentItem.status);
    setSessionFilter(isPast ? "PAST" : "ACTIVE");
  };

  const handleFilterChange = (newFilter) => {
    setSessionFilter(newFilter);
    if (newFilter === "ACTIVE") {
      const matchingActive = activeAlerts.find((a) => a.equipment_id === focusEquipmentId);
      if (matchingActive) {
        setSelectedIncidentId(matchingActive.incident_id);
      } else {
        setSelectedIncidentId(null);
      }
    } else if (newFilter === "PAST") {
      const matchingPast = resolvedAlerts.find((a) => a.equipment_id === focusEquipmentId);
      if (matchingPast) {
        setSelectedIncidentId(matchingPast.incident_id);
      } else {
        setSelectedIncidentId(null);
      }
    } else {
      setSelectedIncidentId(null);
    }
  };

  return (
    <div className="app-shell">
      <Header
        state={state}
        onReset={() => {
          setSelectedEquipmentId(null);
          setSelectedIncidentId(null);
          setSessionFilter("ACTIVE");
          reset();
        }}
        onStop={stop}
        onResume={resume}
        onDemo={() => {
          const target = focusEquipmentId || "AC-COMP-01";
          setSelectedEquipmentId(target);
          setSessionFilter("ACTIVE");
          startDemo(target);
        }}
      />
      <ImpactBar state={state} alerts={alerts} />
      {state.action.error && <div className="action-error">Action refused: {state.action.error}</div>}
      <main className="workspace">
        <aside className="overview-stack">
          <TriageExceptionRail fleet={state.fleet} selected={focusEquipmentId} onSelect={handleSelectAsset} />
        </aside>
        <section className="command-stack">
          <SessionPipeline
            activeAlerts={assetActiveIncidents}
            resolvedAlerts={assetResolvedIncidents}
            currentIncidentId={
              sessionFilter === "ACTIVE"
                ? currentActiveIncident?.incident_id
                : sessionFilter === "PAST"
                ? currentPastIncident?.incident_id
                : null
            }
            sessionFilter={sessionFilter}
            onFilterChange={handleFilterChange}
            onSelect={handleSelectIncident}
            focusedAsset={focusedAsset}
          />

          {sessionFilter === "ACTIVE" && (
            currentActiveIncident ? (
              <IncidentCommand
                incident={currentActiveIncident}
                state={state}
                approve={approve}
                reject={reject}
                verifyOutcome={verifyOutcome}
                clearError={clearError}
                refreshState={refreshState}
              />
            ) : (
              <NoActiveIncidentState
                asset={focusedAsset}
                activeAlerts={activeAlerts}
                onViewNominal={() => setSessionFilter("NOMINAL")}
                onSelectActive={(eid) => handleSelectAsset(eid)}
                onSimulate={() => {
                  setSessionFilter("ACTIVE");
                  startDemo(focusedAsset?.equipment_id || "AC-COMP-01");
                }}
              />
            )
          )}

          {sessionFilter === "PAST" && (
            currentPastIncident ? (
              <IncidentCommand
                incident={currentPastIncident}
                state={state}
                approve={approve}
                reject={reject}
                verifyOutcome={verifyOutcome}
                clearError={clearError}
                refreshState={refreshState}
                isResolved
              />
            ) : (
              <NoPastIncidentState
                asset={focusedAsset}
                resolvedAlerts={resolvedAlerts}
                onViewNominal={() => setSessionFilter("NOMINAL")}
                onSelectResolved={(eid) => handleSelectAsset(eid)}
              />
            )
          )}

          {sessionFilter === "NOMINAL" && (
            <AssetNominalCommand
              asset={focusedAsset}
              state={state}
              onSimulate={() => {
                setSessionFilter("ACTIVE");
                startDemo(focusedAsset?.equipment_id || "AC-COMP-01");
              }}
            />
          )}
        </section>
      </main>
    </div>
  );
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


const DOMAIN_ATTRIBUTIONS = {
  "AC-COMP-01": [
    { label: "Discharge Press", value: "5.4 bar", ref: "7.2 bar", delta: "-1.8 bar" },
    { label: "Motor Amperage", value: "82 A", ref: "64 A", delta: "+18 A" },
    { label: "Vibration (DE)", value: "4.8 mm/s", ref: "1.8 mm/s", delta: "+3.0 mm/s" },
  ],
  "CONV-02": [
    { label: "Motor Winding Temp", value: "118°C", ref: "85°C", delta: "+33°C" },
    { label: "Belt Slip Velocity", value: "0.42 m/s", ref: "0.02 m/s", delta: "+0.40 m/s" },
    { label: "Drive Amperage", value: "94 A", ref: "68 A", delta: "+26 A" },
  ],
  "COOL-PMP-09": [
    { label: "Suction Pressure", value: "0.8 bar", ref: "2.4 bar", delta: "-1.6 bar" },
    { label: "Impeller Vibration", value: "6.2 mm/s", ref: "2.1 mm/s", delta: "+4.1 mm/s" },
    { label: "Seal Cavity Temp", value: "92°C", ref: "65°C", delta: "+27°C" },
  ],
  "PRESS-08": [
    { label: "Hydraulic Pressure", value: "245 bar", ref: "190 bar", delta: "+55 bar" },
    { label: "Oil Reservoir Temp", value: "84°C", ref: "55°C", delta: "+29°C" },
    { label: "Cycle Dwell Time", value: "4.2 s", ref: "2.8 s", delta: "+1.4 s" },
  ],
  "WELD-ROB-03": [
    { label: "Axis-3 Backlash", value: "0.38 mm", ref: "0.05 mm", delta: "+0.33 mm" },
    { label: "Joint 2 Current", value: "38 A", ref: "22 A", delta: "+16 A" },
    { label: "Tip Temp", value: "440°C", ref: "320°C", delta: "+120°C" },
  ],
  "CNC-MILL-04": [
    { label: "Spindle Vibration", value: "5.1 mm/s", ref: "1.5 mm/s", delta: "+3.6 mm/s" },
    { label: "Bearing Temp", value: "78°C", ref: "45°C", delta: "+33°C" },
    { label: "Tool Runout", value: "32 µm", ref: "8 µm", delta: "+24 µm" },
  ],
  "HYD-PUMP-02": [
    { label: "Discharge Ripple", value: "18.5 bar", ref: "4.0 bar", delta: "+14.5 bar" },
    { label: "Case Drain Flow", value: "14 L/min", ref: "4 L/min", delta: "+10 L/min" },
    { label: "Fluid Viscosity", value: "28 cSt", ref: "46 cSt", delta: "-18 cSt" },
  ],
  "GRIND-05": [
    { label: "Wheel Unbalance", value: "14.2 g·mm", ref: "2.5 g·mm", delta: "+11.7 g·mm" },
    { label: "Spindle Power", value: "18.4 kW", ref: "12.0 kW", delta: "+6.4 kW" },
    { label: "Coolant Flow", value: "22 L/min", ref: "45 L/min", delta: "-23 L/min" },
  ],
};

const EQUIPMENT_MODES = {
  "AC-COMP-01": "Discharge Pressure Anomaly",
  "CONV-02": "Drive Motor Thermal Overload",
  "COOL-PMP-09": "Impeller Cavitation / Seal",
  "PRESS-08": "Hydraulic Overpressure",
  "WELD-ROB-03": "Servo Backlash Drift",
  "CNC-MILL-04": "Spindle Bearing Wear",
  "HYD-PUMP-02": "Fluid Aeration / Cavitation",
  "GRIND-05": "Wheel Unbalance / Runout",
};

function assetContextMode(asset) {
  if (asset.status === "HEALTHY" || asset.status === "NOMINAL" || asset.failure_prob < 0.15) {
    return "Nominal envelope";
  }
  if (asset.predicted_mode && asset.predicted_mode !== "NONE" && asset.predicted_mode !== "FM-TWF" && asset.predicted_mode_label !== "Tool Wear Failure") {
    return asset.predicted_mode_label;
  }
  return EQUIPMENT_MODES[asset.equipment_id] || asset.name || "Elevated anomaly";
}

function FleetPanel({ fleet, selected, onSelect }) {
  const sorted = [...fleet].sort((a, b) => (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || b.failure_prob - a.failure_prob);
  return (
    <Panel title="Fleet Assets" meta={`${fleet.length || 8} Monitored`}>
      <div className="fleet-list">
        {sorted.map((asset) => (
          <AssetRow
            key={asset.equipment_id}
            asset={asset}
            selected={selected === asset.equipment_id}
            onClick={() => onSelect(asset.equipment_id)}
          />
        ))}
      </div>
    </Panel>
  );
}

function AssetRow({ asset, selected, onClick }) {
  return (
    <button
      className={`asset-row ${asset.status.toLowerCase()} ${selected ? "selected" : ""}`}
      onClick={onClick}
      title={`${asset.equipment_id} (${asset.name}) — ${asset.status}`}
    >
      <div className="asset-row-left">
        <span className={`status-indicator-dot ${tone(asset.status)}`} />
        <div className="asset-id-col">
          <span className="asset-id">{asset.equipment_id}</span>
          <span className="asset-sub">{assetContextMode(asset)}</span>
        </div>
      </div>
      <div className="asset-row-right">
        <div className="asset-risk-col">
          <b className={`asset-risk-val ${tone(asset.status)}`}>{pct(asset.failure_prob)}</b>
          <span className="asset-risk-label">24h risk</span>
        </div>
        <div className="asset-spark-col">
          <Spark point={asset.point} status={asset.status} />
        </div>
      </div>
    </button>
  );
}

function Spark({ point, status }) {
  const history = useRef([]);
  if (point) history.current = [...history.current, point.prob].slice(-26);
  const color = { CRITICAL: "#ff5d73", WARNING: "#f6b94a", SCHEDULED: "#67a5ff", HEALTHY: "#31d6a0", DOWN: "#7b849a" }[status] || "#31d6a0";
  return (
    <div className="spark-wrapper">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={history.current.map((p, i) => ({ i, p }))} margin={{ top: 1, right: 0, bottom: 1, left: 0 }}>
          <YAxis hide domain={[0, 1]} />
          <Area dataKey="p" type="monotone" stroke={color} fill={color} fillOpacity={0.12} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function RiskChart({ state, focusId, title = "Telemetry & Anomaly Signal Curve" }) {
  const [showFleet, setShowFleet] = useState(false);

  const ids = useMemo(() => {
    const value = new Set(state.fleet.filter((a) => a.status !== "HEALTHY").map((a) => a.equipment_id));
    if (focusId) value.add(focusId);
    return [...value].slice(0, 6);
  }, [state.fleet, focusId]);

  const data = useMemo(() => {
    const times = new Map();
    ids.forEach((id) => (state.histories[id] || []).forEach((point) => {
      if (!times.has(point.t)) times.set(point.t, { t: point.t });
      times.get(point.t)[id] = point.prob;
    }));
    return [...times.values()].sort((a, b) => a.t - b.t).slice(-70);
  }, [ids, state.histories]);

  const focusColor = "#ff5d73";

  return (
    <Card
      title={title}
      icon="📈"
      meta={
        <div className="chart-meta-toolbar">
          <button
            className={`chart-scope-toggle ${!showFleet ? "active" : ""}`}
            onClick={() => setShowFleet(false)}
            title="Isolate target asset telemetry"
          >
            ● Scoped Asset Only
          </button>
          <button
            className={`chart-scope-toggle ${showFleet ? "active" : ""}`}
            onClick={() => setShowFleet(true)}
            title="Show fleet background comparison"
          >
            Fleet Comparison
          </button>
        </div>
      }
    >
      <div className="risk-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: -22, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="rgba(139,158,191,.09)" />
            <ReferenceArea y1={state.triggerThreshold} y2={1} fill="rgba(255,93,115,.06)" />
            <XAxis dataKey="t" tick={{ fill: "#67748b", fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={28} />
            <YAxis domain={[0, 1]} tickFormatter={(v) => Math.round(v * 100)} tick={{ fill: "#67748b", fontSize: 10 }} axisLine={false} tickLine={false} />
            <ReferenceLine y={state.triggerThreshold} stroke="#ff5d73" strokeDasharray="4 4" />
            <Tooltip formatter={(value) => pct(value)} contentStyle={{ background: "#101722", border: "1px solid #2a3547", borderRadius: 8 }} />
            {showFleet
              ? ids.map((id, i) => {
                  const isFocus = id === focusId;
                  return (
                    <Line
                      key={id}
                      dataKey={id}
                      type="monotone"
                      stroke={isFocus ? focusColor : SERIES[i % SERIES.length]}
                      strokeWidth={isFocus ? 2.8 : 1.2}
                      strokeOpacity={isFocus ? 1 : 0.25}
                      strokeDasharray={isFocus ? undefined : "3 3"}
                      dot={false}
                      connectNulls
                      isAnimationActive={false}
                    />
                  );
                })
              : (
                <Line
                  dataKey={focusId}
                  type="monotone"
                  stroke={focusColor}
                  strokeWidth={2.8}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        <span className="active-series">
          <i style={{ background: focusColor }} />
          <b>{focusId}</b> (Target Anomaly)
        </span>
        {showFleet &&
          ids.filter((id) => id !== focusId).map((id, i) => (
            <span key={id} className="fleet-series">
              <i style={{ background: SERIES[i % SERIES.length], opacity: 0.35 }} />
              {id}
            </span>
          ))}
      </div>
    </Card>
  );
}

const ASSET_SENSORS = {
  compressor: [
    { name: "Discharge Pressure", value: "7.8 bar", status: "good", envelope: "6.5 – 8.5 bar" },
    { name: "Intercooler Temp", value: "48.2 °C", status: "good", envelope: "< 65.0 °C" },
    { name: "Shaft Vibration", value: "1.4 mm/s", status: "good", envelope: "< 4.5 mm/s" },
    { name: "Motor Power", value: "45.1 kW", status: "good", envelope: "40 – 55 kW" },
  ],
  conveyor: [
    { name: "Belt Speed", value: "1.8 m/s", status: "good", envelope: "1.5 – 2.0 m/s" },
    { name: "Drive Motor Temp", value: "54.0 °C", status: "good", envelope: "< 75.0 °C" },
    { name: "Roller Vibration", value: "0.8 mm/s", status: "good", envelope: "< 2.8 mm/s" },
    { name: "Belt Tension", value: "12.4 kN", status: "good", envelope: "10 – 15 kN" },
  ],
  pump: [
    { name: "Suction Pressure", value: "2.1 bar", status: "good", envelope: "> 1.5 bar" },
    { name: "Discharge Flow", value: "120 L/min", status: "good", envelope: "100 – 140 L/min" },
    { name: "Impeller Vibration", value: "1.1 mm/s", status: "good", envelope: "< 3.5 mm/s" },
    { name: "Seal Temp", value: "42.5 °C", status: "good", envelope: "< 60.0 °C" },
  ],
  press: [
    { name: "Hydraulic Pressure", value: "210 bar", status: "good", envelope: "190 – 230 bar" },
    { name: "Cycle Time", value: "3.2 sec", status: "good", envelope: "3.0 – 3.5 sec" },
    { name: "Ram Alignment", value: "0.02 mm", status: "good", envelope: "< 0.05 mm" },
    { name: "Fluid Temp", value: "46.8 °C", status: "good", envelope: "< 60.0 °C" },
  ],
  robot: [
    { name: "Joint 1 Torque", value: "42 Nm", status: "good", envelope: "< 85 Nm" },
    { name: "Joint 2 Backlash", value: "0.01 mm", status: "good", envelope: "< 0.04 mm" },
    { name: "Servo Drive Temp", value: "39.5 °C", status: "good", envelope: "< 65.0 °C" },
    { name: "Repeatability", value: "±0.02 mm", status: "good", envelope: "±0.05 mm" },
  ],
  mill: [
    { name: "Spindle Speed", value: "4,500 RPM", status: "good", envelope: "0 – 8,000 RPM" },
    { name: "Spindle Bearing Temp", value: "41.0 °C", status: "good", envelope: "< 60.0 °C" },
    { name: "Axis Runout", value: "0.008 mm", status: "good", envelope: "< 0.02 mm" },
    { name: "Coolant Flow", value: "18.5 L/min", status: "good", envelope: "> 15.0 L/min" },
  ],
  grinder: [
    { name: "Wheel Speed", value: "3,200 RPM", status: "good", envelope: "3,000 – 3,500 RPM" },
    { name: "Wheel Vibration", value: "0.6 mm/s", status: "good", envelope: "< 2.0 mm/s" },
    { name: "Spindle Power", value: "8.4 kW", status: "good", envelope: "< 15.0 kW" },
    { name: "Hydrostatic Pressure", value: "28 bar", status: "good", envelope: "25 – 35 bar" },
  ],
};

function SessionPipeline({
  activeAlerts,
  resolvedAlerts,
  currentIncidentId,
  sessionFilter,
  onFilterChange,
  onSelect,
  focusedAsset,
}) {
  const formatShortId = (id) => {
    if (!id) return "INC-000";
    const parts = id.split("-");
    if (parts.length > 1 && !isNaN(parts[1])) {
      return `INC-${parts[1]}`;
    }
    return `#${id.slice(0, 6)}…`;
  };

  const formatPhaseName = (phase = "") => {
    const clean = phase.replaceAll("_", " ").toLowerCase();
    return clean.charAt(0).toUpperCase() + clean.slice(1);
  };

  return (
    <div className="session-pipeline-bar">
      <div className="pipeline-lead">
        <span className="pipeline-title">Incidents</span>
        <div className="pipeline-dropdown-wrapper">
          <select
            className="pipeline-select-filter"
            value={sessionFilter}
            onChange={(e) => onFilterChange(e.target.value)}
            title="Switch operational workspace view: Active incidents, past resolutions, or nominal baseline"
          >
            <option value="ACTIVE">Active Incidents ({activeAlerts.length})</option>
            <option value="PAST">Past Incidents ({resolvedAlerts.length})</option>
            <option value="NOMINAL">Nominal Status ({focusedAsset?.equipment_id})</option>
          </select>
          <span className="dropdown-chevron-icon" aria-hidden="true">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </span>
        </div>
      </div>

      {sessionFilter === "ACTIVE" && (
        <div className="pipeline-tabs">
          {activeAlerts.map((item) => {
            const isSelected = currentIncidentId === item.incident_id;
            const phase = item.lifecycle?.phase || item.status || "OPEN";
            const riskTone = item.failure_prob > 0.8 ? "bad" : item.failure_prob > 0.4 ? "warn" : "good";

            const isApproval = phase === "AWAITING_APPROVAL";
            return (
              <button
                key={item.incident_id}
                className={`session-tab ${isSelected ? "active" : ""} ${isApproval ? "awaiting-approval" : ""}`}
                onClick={() => onSelect(item)}
                title={`Incident ${item.incident_id} · ${formatPhaseName(phase)}`}
              >
                <span className={`session-pulse-dot ${isApproval ? "pulse-amber" : "pulse-cyan"}`} />
                <span className="session-tab-id">{formatShortId(item.incident_id)}</span>
                <span className="session-tab-sep">·</span>
                <span className="session-tab-phase">{formatPhaseName(phase)}</span>
              </button>
            );
          })}

          {activeAlerts.length === 0 && (
            <span className="pipeline-empty-text">Continuous surveillance · Zero active incidents for {focusedAsset?.equipment_id || "selected machine"}</span>
          )}
        </div>
      )}

      {sessionFilter === "PAST" && (
        <div className="pipeline-tabs">
          {resolvedAlerts.map((item) => {
            const isSelected = currentIncidentId === item.incident_id;

            return (
              <button
                key={item.incident_id}
                className={`session-tab resolved ${isSelected ? "active" : ""}`}
                onClick={() => onSelect(item)}
                title={`Resolved Incident ${item.incident_id} · Closed`}
              >
                <span className="status-indicator-dot good" />
                <span className="session-tab-id">{formatShortId(item.incident_id)}</span>
                <span className="session-tab-sep">·</span>
                <span className="session-tab-phase">Closed</span>
              </button>
            );
          })}

          {resolvedAlerts.length === 0 && (
            <span className="pipeline-empty-text">No archived incidents for {focusedAsset?.equipment_id || "selected machine"}</span>
          )}
        </div>
      )}

      {sessionFilter === "NOMINAL" && (
        <div className="pipeline-nominal-strip">
          <span className="nominal-asset-badge">
            <span className={`status-indicator-dot ${tone(focusedAsset?.status || "HEALTHY")}`} />
            <b>{focusedAsset?.equipment_id}</b>
            <small>{focusedAsset?.name}</small>
          </span>
          <span className="nominal-status-text">
            <CheckCircleIcon size={12} color="var(--green)" />
            <span>Continuous Telemetry Surveillance Active</span>
          </span>
        </div>
      )}
    </div>
  );
}

function NoActiveIncidentState({ asset, activeAlerts, onViewNominal, onSelectActive, onSimulate }) {
  return (
    <div className="empty-command asset-empty-state">
      <span className="empty-state-icon"><CheckCircleIcon size={36} color="var(--green)" /></span>
      <h2>{asset ? `${asset.equipment_id} is Operating Normally` : "No Active Incidents"}</h2>
      <p>
        {asset
          ? `${asset.name} has no open faults or active agent investigations. 24h risk is ${pct(asset.failure_prob || 0.01)}. All telemetry indicators are within deterministic safety thresholds.`
          : "All plant assets are currently operating within their deterministic safety envelopes."}
      </p>
      <div className="empty-state-actions">
        <button className="empty-action-btn primary" onClick={onViewNominal}>
          View Live Sensor Telemetry
        </button>
        {activeAlerts.length > 0 && (
          <button
            className="empty-action-btn secondary"
            onClick={() => onSelectActive(activeAlerts[0].equipment_id)}
          >
            Switch to Active Incident ({activeAlerts[0].equipment_id})
          </button>
        )}
        {asset && (
          <button className="empty-action-btn demo" onClick={onSimulate}>
            <SparkIcon size={12} />
            <span>Simulate Fault on {asset.equipment_id}</span>
          </button>
        )}
      </div>
    </div>
  );
}

function NoPastIncidentState({ asset, resolvedAlerts, onViewNominal, onSelectResolved }) {
  return (
    <div className="empty-command asset-empty-state">
      <span className="empty-state-icon"><CheckCircleIcon size={36} color="var(--faint)" /></span>
      <h2>No Past Incidents on Record for {asset ? asset.equipment_id : "Selected Machine"}</h2>
      <p>
        Zero recorded downtime interventions or recovered fault receipts exist for this unit in the active session database.
      </p>
      <div className="empty-state-actions">
        <button className="empty-action-btn primary" onClick={onViewNominal}>
          View Live Sensor Telemetry
        </button>
        {resolvedAlerts.length > 0 && (
          <button
            className="empty-action-btn secondary"
            onClick={() => onSelectResolved(resolvedAlerts[0].equipment_id)}
          >
            View Resolved Incident ({resolvedAlerts[0].equipment_id})
          </button>
        )}
      </div>
    </div>
  );
}

function AssetNominalCommand({ asset, state, onSimulate }) {
  if (!asset) return <EmptyCommand threshold={state.triggerThreshold} />;

  const sensorConfig = ASSET_SENSORS[asset.equipment_class] || ASSET_SENSORS.compressor;
  const failureProb = asset.failure_prob || 0.01;

  return (
    <motion.div
      key={`nominal-${asset.equipment_id}`}
      className="incident-command nominal-command"
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className="incident-hero nominal-hero">
        <div className="hero-lead">
          <div className="hero-title-row">
            <span className="asset-class-icon-lg"><ClassIcon cls={asset.equipment_class} /></span>
            <div>
              <span className="eyebrow">Continuous Machine Surveillance · Operational Baseline</span>
              <h1>{asset.name} <span className="hero-eid">({asset.equipment_id})</span></h1>
              <p>Type: {asset.equipment_class.toUpperCase()} · Criticality: HIGH · Monitored Baseline</p>
            </div>
          </div>
        </div>

        <div className="hero-risk">
          <small>24h Failure Risk</small>
          <b className={tone(asset.status)}>{pct(failureProb)}</b>
        </div>

        <Status value={asset.status}>{asset.status}</Status>
      </div>

      <div className="nominal-safety-banner">
        <ShieldCheckIcon size={14} color="var(--green)" />
        <span><b>Deterministic Safety Envelopes:</b> All continuous physical parameters verified within nominal operating bounds.</span>
      </div>

      <div className="command-grid">
        {/* Left Column: Physical Sensor Telemetry */}
        <div className="command-column">
          <Card title="Live Operating Telemetry" icon="◎" meta="Deterministic sensor streams">
            <div className="nominal-sensors-grid">
              {sensorConfig.map((s) => (
                <div key={s.name} className="nominal-sensor-card">
                  <div className="sensor-card-head">
                    <span className="sensor-name">{s.name}</span>
                    <span className={`sensor-tag ${s.status}`}>{s.status.toUpperCase()}</span>
                  </div>
                  <b className="sensor-val">{s.value}</b>
                  <small className="sensor-envelope">Safe Envelope: {s.envelope}</small>
                </div>
              ))}
            </div>

            <div className="nominal-chart-section">
              <div className="section-title">
                <span>Telemetry Stability Envelope</span>
                <small>Last 60 ticks · Zero threshold breaches</small>
              </div>
              <div className="nominal-spark-box">
                <Spark point={asset.point} status={asset.status} />
              </div>
            </div>
          </Card>
        </div>

        {/* Right Column: Readiness & Reliability Operations */}
        <div className="command-column">
          <Card title="Equipment Reliability Readiness" icon="◈" meta="Autonomous agent surveillance">
            <div className="readiness-card-body">
              <div className="readiness-status-row">
                <span className="shield-large"><ShieldCheckIcon size={24} color="var(--green)" /></span>
                <div>
                  <b>Continuous Monitoring Active</b>
                  <p>Operon agents are continuously streaming high-frequency vibration, thermal, and electrical telemetry.</p>
                </div>
              </div>

              <div className="readiness-kv-grid">
                <KV label="Health Status" value={`${asset.status} (Zero active faults)`} />
                <KV label="Attributed Bottleneck" value="None (100% Availability)" />
                <KV label="Preventive Overhaul" value="Scheduled in 42 Days" />
                <KV label="Autonomous Response" value="Standby (Gate Armed)" />
              </div>

              <div className="simulate-box">
                <div className="simulate-lead">
                  <b>Reliability Testing & Anomaly Injection</b>
                  <p>Simulate an anomalous operational drift on {asset.equipment_id} to trigger the multi-agent diagnostic pipeline, policy gate, and human-in-the-loop intervention workflow.</p>
                </div>
                <button
                  className="simulate-anomaly-btn"
                  onClick={onSimulate}
                  title={`Trigger guided reliability scenario on ${asset.equipment_id}`}
                >
                  <SparkIcon size={12} />
                  <span>Simulate Fault & Trigger Agent on {asset.equipment_id}</span>
                </button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </motion.div>
  );
}

function formatDetectionTime(ts) {
  if (!ts) return null;
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return null;
    const now = Date.now();
    const diffSec = Math.max(0, Math.floor((now - d.getTime()) / 1000));
    const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (diffSec < 45) return { label: "Detected just now", full: timeStr };
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return { label: `Detected ${diffMin}m ago`, full: timeStr };
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return { label: `Detected ${diffHours}h ${diffMin % 60}m ago`, full: timeStr };
    return { label: `Detected on ${d.toLocaleDateString([], { month: "short", day: "numeric" })} at ${timeStr}`, full: timeStr };
  } catch {
    return null;
  }
}

function IncidentCommand({
  incident,
  state,
  approve,
  reject,
  verifyOutcome,
  clearError,
  refreshState,
  isResolved,
}) {
  const lifecycle = incident.lifecycle || {}, view = lifecycle.read_model || {}, phase = lifecycle.phase || "OPEN";
  const isResolvedIncident = isResolved || ["CLOSED", "FAILED", "CANCELLED"].includes(phase || incident.status);

  // Authoritative asset telemetry from state.fleet (same data source used in rail, ticker, and tabs)
  const asset = (state.fleet || []).find((a) => a.equipment_id === incident.equipment_id) || incident;
  const failureProb = isResolvedIncident
    ? (asset.failure_prob ?? 0.01)
    : (asset.failure_prob ?? incident.failure_prob ?? 0.01);
  const riskLabel = isResolvedIncident
    ? "Recovered · In Spec"
    : assetContextMode(asset);
  const riskTone = tone(asset.status || (failureProb > 0.8 ? "CRITICAL" : failureProb > 0.4 ? "WARNING" : "HEALTHY"));
  const detectionTimestamp =
    view.incident?.created_at ||
    view.events?.[0]?.created_at ||
    view.events?.[0]?.timestamp ||
    incident.created_at;
  const detected = formatDetectionTime(detectionTimestamp);

  return (
    <motion.div key={incident.incident_id} className="incident-command" initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}>
      <div className="incident-hero">
        <div>
          <h1>{incident.equipment_name || asset.name} <span className="hero-eid">({incident.equipment_id})</span></h1>
          <p className="incident-hero-subline">
            <span>Incident <CopyId value={incident.incident_id} /></span>
            {detected && (
              <>
                <span className="meta-sep">·</span>
                <span title={`Exact detection timestamp: ${detected.full}`}>{detected.label}</span>
              </>
            )}
          </p>
        </div>
        <div className="hero-risk">
          <small>24h Failure Risk</small>
          <b className={riskTone}>{pct(failureProb)}</b>
        </div>
        <Status value={phase}>{phase.replaceAll("_", " ")}</Status>
      </div>

      <Lifecycle phase={phase} events={view.events || []} />

      <div className="command-grid">
        {/* Left Column: Agent Investigation & Evidence (The "Why") */}
        <div className="command-column">
          <DiagnosisCard incident={incident} view={view} />
          <AgentCard view={view} lifecycle={lifecycle} provenance={state.reasoningProvenance} />
          <RiskChart state={state} focusId={incident.equipment_id} title="Telemetry & Anomaly Signal Curve" />
        </div>

        {/* Right Column: Action & Human-in-the-Loop Governance (The "What to Do") */}
        <div className="command-column">
          <InterventionCard incident={incident} view={view} />
          <ApprovalCard
            incident={incident}
            view={view}
            approve={approve}
            reject={reject}
            pending={state.action.pending}
            actionError={state.action.error}
            clearError={clearError}
            refreshState={refreshState}
          />
          <OutcomeCard
            incident={incident}
            view={view}
            verifyOutcome={verifyOutcome}
            pending={state.action.pending}
          />
        </div>
      </div>

      {/* Unified Full-Width Bottom Drawer: Evidence Ledger & Audit Trail */}
      <AuditLedgerDrawer evidence={view.evidence || []} events={view.events || []} />
    </motion.div>
  );
}

const STAGES = [
  { id: "detection", number: 1, title: "Detection", subline: "Signal Admitted" },
  { id: "diagnosis", number: 2, title: "Diagnosis", subline: "Consensus Validated" },
  { id: "planning", number: 3, title: "Planning", subline: "Package Formulated" },
  { id: "dispatch", number: 4, title: "Dispatch", subline: "CMMS Execution" },
  { id: "verification", number: 5, title: "Verification", subline: "Recovery Proven" },
];

function Lifecycle({ phase = "OPEN", events = [] }) {
  // Compute stage statuses based strictly on authoritative lineage
  const stageStatuses = useMemo(() => {
    const s = {};
    const p = phase || "OPEN";

    // Exceptional terminal states
    if (["ESCALATED", "CANCELLED", "EXECUTION_FAILED"].includes(p)) {
      s.detection = "done";
      s.diagnosis = "done";
      s.planning = "done";
      s.gate = p === "ESCALATED" ? "refused" : "passed";
      s.dispatch = p === "EXECUTION_FAILED" ? "failed" : "pending";
      s.verification = "pending";
      return s;
    }

    if (p === "OPEN") {
      s.detection = "active";
      s.diagnosis = "pending";
      s.planning = "pending";
      s.gate = "standby";
      s.dispatch = "pending";
      s.verification = "pending";
    } else if (["INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED"].includes(p)) {
      s.detection = "done";
      s.diagnosis = "active";
      s.planning = "pending";
      s.gate = "standby";
      s.dispatch = "pending";
      s.verification = "pending";
    } else if (["PLANNING", "INTERVENTION_VALIDATED"].includes(p)) {
      s.detection = "done";
      s.diagnosis = "done";
      s.planning = "active";
      s.gate = "standby";
      s.dispatch = "pending";
      s.verification = "pending";
    } else if (p === "AWAITING_APPROVAL") {
      s.detection = "done";
      s.diagnosis = "done";
      s.planning = "done";
      s.gate = "armed";
      s.dispatch = "pending";
      s.verification = "pending";
    } else if (p === "READY") {
      s.detection = "done";
      s.diagnosis = "done";
      s.planning = "done";
      s.gate = "passed";
      s.dispatch = "ready";
      s.verification = "pending";
    } else if (p === "EXECUTING") {
      s.detection = "done";
      s.diagnosis = "done";
      s.planning = "done";
      s.gate = "passed";
      s.dispatch = "active";
      s.verification = "pending";
    } else if (p === "OBSERVING") {
      s.detection = "done";
      s.diagnosis = "done";
      s.planning = "done";
      s.gate = "passed";
      s.dispatch = "done";
      s.verification = "active";
    } else if (p === "CLOSED") {
      s.detection = "done";
      s.diagnosis = "done";
      s.planning = "done";
      s.gate = "passed";
      s.dispatch = "done";
      s.verification = "done";
    }
    return s;
  }, [phase]);

  const getSubtext = (stageId, status) => {
    if (status === "done") {
      if (stageId === "detection") return "Signal Admitted";
      if (stageId === "diagnosis") return "Critic Validated";
      if (stageId === "planning") return "Package Validated";
      if (stageId === "dispatch") return "Execution Confirmed";
      if (stageId === "verification") return "Recovery Proven";
    }
    if (status === "active") {
      if (stageId === "detection") return "Evaluating Signal";
      if (stageId === "diagnosis") {
        if (phase === "INVESTIGATING") return "Gathering Telemetry";
        if (phase === "AWAITING_EVIDENCE") return "Missing Evidence";
        return "Consensus Validated";
      }
      if (stageId === "planning") {
        if (phase === "PLANNING") return "Synthesizing Plan";
        return "Package Validated";
      }
      if (stageId === "dispatch") return "CMMS Executing";
      if (stageId === "verification") return "Sensor Watch Active";
    }
    return STAGES.find((s) => s.id === stageId)?.subline || "Pending";
  };

  const gateState = useMemo(() => {
    const s = stageStatuses.gate;
    if (s === "armed") {
      return {
        status: "armed",
        icon: <AlertTriangleIcon size={12} color="#f59e0b" />,
        label: "Sign-Off Required",
        subtext: "Governance Gate Armed",
        beacon: true,
      };
    }
    if (s === "passed") {
      return {
        status: "passed",
        icon: <ShieldCheckIcon size={12} color="var(--signal-nominal-text)" />,
        label: "Approved",
        subtext: "Human Gate Passed",
        beacon: false,
      };
    }
    if (s === "refused") {
      return {
        status: "refused",
        icon: <LockIcon size={12} color="#ef4444" />,
        label: "Gate Refused",
        subtext: "Escalated / Rejected",
        beacon: false,
      };
    }
    return {
      status: "standby",
      icon: <LockIcon size={12} color="var(--text-muted)" />,
      label: "Approval Gate",
      subtext: "Governance Boundary",
      beacon: false,
    };
  }, [stageStatuses.gate]);

  const renderStageNode = (st) => {
    const status = stageStatuses[st.id] || "pending";
    const isDone = status === "done";
    const isActive = status === "active" || status === "ready";
    const isFailed = status === "failed";
    const sub = getSubtext(st.id, status);

    return (
      <div key={st.id} className={`pipeline-stage ${status}`}>
        <div className="stage-node-container">
          <div className="stage-node">
            {isDone ? (
              <i className="node-icon check">✓</i>
            ) : isFailed ? (
              <i className="node-icon fail">!</i>
            ) : (
              <i className="node-icon num">{st.number}</i>
            )}
            {isActive && <span className="active-ring" />}
          </div>
        </div>
        <div className="stage-meta">
          <span className="stage-title">{st.title}</span>
          <span className="stage-sub">{sub}</span>
        </div>
      </div>
    );
  };

  const renderRail = (fromStatus) => {
    const filled = fromStatus === "done";
    return (
      <div className={`pipeline-rail ${filled ? "filled" : ""}`}>
        <div className="rail-fill" />
      </div>
    );
  };

  return (
    <section className="lifecycle-pipeline-card">
      <div className="pipeline-header">
        <span className="pipeline-badge">Lifecycle</span>
        <div className="pipeline-phase-tag">
          <span className="phase-indicator-dot" />
          <span>Active Phase: <b>{phase.replaceAll("_", " ")}</b></span>
        </div>
      </div>

      <div className="pipeline-track">
        {/* Stage 1: Detection */}
        {renderStageNode(STAGES[0])}
        {renderRail(stageStatuses.detection)}

        {/* Stage 2: Diagnosis */}
        {renderStageNode(STAGES[1])}
        {renderRail(stageStatuses.diagnosis)}

        {/* Stage 3: Planning */}
        {renderStageNode(STAGES[2])}

        {/* --- CENTRAL GOVERNANCE AIR-GAP GATE --- */}
        <div className="pipeline-gate-segment">
          <div className={`gate-rail left ${stageStatuses.planning === "done" ? "filled" : ""}`} />
          <div className={`gate-capsule ${gateState.status}`}>
            <span className="gate-icon-wrap">{gateState.icon}</span>
            <div className="gate-text-wrap">
              <span className="gate-headline">{gateState.label}</span>
              <span className="gate-tagline">{gateState.subtext}</span>
            </div>
            {gateState.beacon && <span className="gate-beacon-ping" />}
          </div>
          <div className={`gate-rail right ${["passed", "active", "done"].includes(stageStatuses.dispatch) ? "filled" : ""}`} />
        </div>

        {/* Stage 4: Dispatch */}
        {renderStageNode(STAGES[3])}
        {renderRail(stageStatuses.dispatch)}

        {/* Stage 5: Verification */}
        {renderStageNode(STAGES[4])}
      </div>
    </section>
  );
}

function Invariant() {
  return (
    <div className="invariant">
      <span>Prediction</span><i>≠</i><span>Diagnosis</span><i>≠</i><span>Intervention</span><i>≠</i><span>Approval</span><i>≠</i><span>Execution</span><i>≠</i><span>Outcome</span>
    </div>
  );
}

function DiagnosisCard({ incident, view }) {
  const diagnosis = view.diagnosis, verdict = [...(view.verdicts || [])].reverse().find((item) => item.target_kind === "diagnosis"), signal = (view.evidence || []).find((item) => item.kind === "model_signal");
  const domainDrivers = DOMAIN_ATTRIBUTIONS[incident.equipment_id];

  return (
    <Card title="Evidence → Diagnosis" icon="◎" meta={diagnosis ? "Application Validated" : "Investigation Active"}>
      <div className="signal-box">
        <div>
          <small>Predictive Signal</small>
          <b>{incident.predicted_mode_label || "Elevated Failure Risk"}</b>
        </div>
        <Status value="signal">Prediction, not cause</Status>
      </div>
      {domainDrivers ? (
        <div className="drivers">
          {domainDrivers.map((item) => (
            <span key={item.label} className="driver-chip">
              <b>{item.label}:</b> {item.value} <small>(Ref: {item.ref})</small>
              {item.delta && <em>{item.delta}</em>}
            </span>
          ))}
        </div>
      ) : signal?.payload?.attribution?.length > 0 ? (
        <div className="drivers">
          {signal.payload.attribution.slice(0, 3).map((item) => (
            <span key={item.feature} className="driver-chip">
              <b>{item.label || item.feature}:</b> {Number(item.value).toFixed(1)} <em>+{Number(item.contribution).toFixed(2)}</em>
            </span>
          ))}
        </div>
      ) : null}
      {diagnosis ? (
        <div className="diagnosis">
          <span className="validated-mark">✓</span>
          <div>
            <small>Validated Diagnosis</small>
            <h3>{diagnosis.conclusion}</h3>
            <p>{diagnosis.evidence_ids.length} cited evidence records · confidence {diagnosis.confidence == null ? "not asserted" : pct(diagnosis.confidence)}</p>
          </div>
        </div>
      ) : (
        <div className="awaiting-synthesis">
          <span className="synthesis-spinner" />
          <div>
            <b>Correlating Sensor Telemetry</b>
            <p>Reasoning runtime is evaluating physical anomaly features against historical failure baselines.</p>
          </div>
        </div>
      )}
      {verdict && <Verdict item={verdict} />}
    </Card>
  );
}

function AgentCard({ view, lifecycle, provenance }) {
  const runs = view.agent_runs || [], run = runs[runs.length - 1], assessments = run?.assessments || [], delegations = run?.delegations || [], baseline = (view.agent_actions || []).filter((item) => item.actor === "operon.investigation");
  return (
    <Card title="Strands Agent Activity" icon="✦" meta={run ? `${run.status} · ${run.tool_calls} Tool Calls` : "Reasoning Runtime Connected"}>
      <div className="agent-boundary">
        <span>Advisory Reasoning</span>
        <i>Cannot Transition Lifecycle</i>
      </div>
      {run ? (
        <>
          <div className="run-strip">
            <span><small>Run ID</small><CopyId value={run.run_id} /></span>
            <span><small>Stage</small><b>{run.stage}</b></span>
            <span><small>Backend</small><b>{run.runtime_identity?.backend || provenance?.backend || "local"}</b></span>
          </div>
          {run.summary && <p className="run-summary">{run.summary}</p>}
          <div className="agent-list">
            <AgentLine name="Reliability Supervisor" role="supervisor" status={run.status} text={run.disposition} />
            {delegations.map((item) => (
              <AgentLine key={item.key} name={roleName(item.role)} role={item.role} status={item.status} text={item.question} />
            ))}
            {assessments.filter((item) => !delegations.some((d) => d.key === item.key)).map((item) => (
              <AgentLine key={item.key} name={roleName(inferRole(item.assessment))} role={inferRole(item.assessment)} status="SUCCEEDED" text={item.assessment.reasoning_summary} />
            ))}
          </div>
          {run.blockers?.length > 0 && (
            <ul className="blockers">
              {run.blockers.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <>
          {baseline.map((item) => (
            <AgentLine key={item.id} name="Application Investigator" role="system" status={item.status} text={item.summary} />
          ))}
          <div className="awaiting-synthesis">
            <span className="synthesis-spinner" />
            <div>
              <b>Strands Supervisor Dispatched</b>
              <p>{lifecycle.supervisor_available ? "Autonomous reasoning active. Multi-agent reports will stream in." : "Durable telemetry ready; awaiting reasoning response."}</p>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

function AgentLine({ name, role, status, text }) {
  return (
    <div className="agent-line">
      <span className={`agent-avatar ${role}`}>{role === "supervisor" ? "S" : role?.[0]?.toUpperCase() || "A"}</span>
      <div>
        <b>{name}</b>
        <p>{text || "Structured report recorded"}</p>
      </div>
      <Status value={status}>{status}</Status>
    </div>
  );
}

function InterventionCard({ incident, view }) {
  const item = view.intervention, binding = view.binding, verdict = [...(view.verdicts || [])].reverse().find((entry) => entry.target_kind === "intervention");
  return (
    <Card title="Proposed Intervention" icon="⌁" meta={item?.status || "Awaiting Diagnosis"}>
      {item ? (
        <>
          <div className="plan-head">
            <div>
              <small>Typed Maintenance Action</small>
              <h3>{item.steps[0]?.parameters?.description || item.steps[0]?.capability?.replaceAll("_", " ")}</h3>
            </div>
            <Status value={item.risk}>{item.risk} risk</Status>
          </div>
          <div className="plan-grid">
            <KV label="Capability" value={item.steps[0]?.capability} />
            <KV label="Technician" value={binding?.technician_id} />
            <KV label="Estimated Cost" value={money0(item.estimated_cost)} />
            <KV label="Downtime" value={`${item.estimated_downtime_minutes} min`} />
            <KV label="Window" value={formatWindow(item.window_start, item.window_end)} />
            <KV label="Avoided Loss" value={money0(item.estimated_avoided_loss)} />
          </div>
          {binding?.parts?.length > 0 && (
            <div className="parts">
              <small>Reserved Parts</small>
              {binding.parts.map((part) => (
                <span key={part.part_id}>{part.quantity}× {part.part_id}</span>
              ))}
            </div>
          )}
          {verdict && <Verdict item={verdict} />}
        </>
      ) : (
        <div className="awaiting-synthesis">
          <span className="synthesis-spinner" />
          <div>
            <b>Awaiting Agent Synthesis</b>
            <p>Reliability Planner will formulate typed parameter deltas and technician bindings once diagnosis validation is committed.</p>
          </div>
        </div>
      )}
    </Card>
  );
}

function ApprovalCard({ incident, view, approve, reject, pending, actionError, clearError, refreshState }) {
  const [inspectOpen, setInspectOpen] = useState(false);
  const phase = incident.lifecycle?.phase;
  const current = [...(view.requirements || [])].reverse()[0];
  const decision = [...(view.approval_decisions || [])].reverse()[0];
  const canApprove = phase === "AWAITING_APPROVAL" && incident.lifecycle?.requirement_id;
  const intervention = view.intervention;
  const step = intervention?.steps?.[0];
  const binding = view.binding;

  return (
    <Card title="Governance & Policy Gate" icon="◇" meta={current?.policy_version || "Gate Armed"} accent={canApprove ? "approval" : ""}>
      {actionError && (
        <div className="inline-action-error">
          <div className="error-header">
            <AlertTriangleIcon size={12} color="#ef4444" />
            <b>Approval Refused by Application Gate</b>
          </div>
          <p>{actionError}</p>
          <button type="button" className="btn-refresh-state" onClick={() => { clearError?.(); refreshState?.(); }}>
            <RefreshCwIcon size={10} />
            <span>Refresh State & Re-validate</span>
          </button>
        </div>
      )}

      {canApprove ? (
        <>
          <div className="governance-result">
            <span className="shield-small"><ShieldCheckIcon size={14} color="var(--amber)" /></span>
            <div>
              <small>Deterministic Application Policy</small>
              <b>Human Sign-Off Required (HITL)</b>
              <p>{(current?.conditions || []).join(" · ") || "Exact promoted work package binding enforced."}</p>
            </div>
          </div>
          <div className="binding-strip">
            <span>Bound to</span><CopyId value={current.intervention_id} short />
            <span>hash</span><CopyId value={current.intervention_hash} short />
            <button
              type="button"
              className="btn-inspect-plan"
              onClick={() => setInspectOpen(!inspectOpen)}
              title="Inspect work package specification"
            >
              <EyeIcon size={10} />
              <span>{inspectOpen ? "Hide Spec" : "Inspect Spec"}</span>
            </button>
          </div>

          {inspectOpen && (
            <div className="work-package-inspector">
              <div className="inspector-header">
                <b>Signed Work Package Specification</b>
                <small>SHA-256 Verified</small>
              </div>
              <div className="inspector-details">
                <KV label="Action" value={step?.parameters?.description || step?.capability} />
                <KV label="Technician" value={binding?.technician_id || "Lead Technician"} />
                <KV label="Downtime" value={`${intervention?.estimated_downtime_minutes ?? 45} min`} />
                <KV label="Cost / Avoided" value={`${money0(intervention?.estimated_cost)} / +${money0(intervention?.estimated_avoided_loss)}`} />
                {step?.parameters && (
                  <div className="inspector-params">
                    <small>Dispatched Parameters</small>
                    <code>{JSON.stringify(step.parameters, null, 2)}</code>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="approver-identity-strip">
            <span className="identity-dot" />
            <span>Signing Role: <b>Maintenance Approver</b> (dashboard-operator)</span>
          </div>

          <div className="approval-actions">
            <button disabled={!!pending} onClick={() => approve(incident)}>
              {pending ? "Signing & Dispatching…" : "Approve Exact Plan & Dispatch"}
            </button>
            <button disabled={!!pending} className="reject" onClick={() => reject(incident)}>
              Reject
            </button>
          </div>
        </>
      ) : current ? (
        <>
          <div className="governance-result">
            <span className="shield-small"><ShieldCheckIcon size={14} color="var(--green)" /></span>
            <div>
              <small>Application Policy Result</small>
              <b>{current?.status || "Evaluated"}</b>
              <p>{(current?.conditions || []).join(" · ") || "Exact promoted work package binding enforced."}</p>
            </div>
          </div>
          <div className="binding-strip">
            <span>Bound to</span><CopyId value={current.intervention_id} short />
            <span>hash</span><CopyId value={current.intervention_hash} short />
            <button
              type="button"
              className="btn-inspect-plan"
              onClick={() => setInspectOpen(!inspectOpen)}
              title="Inspect work package specification"
            >
              <EyeIcon size={10} />
              <span>{inspectOpen ? "Hide Spec" : "Inspect Spec"}</span>
            </button>
          </div>
          {inspectOpen && (
            <div className="work-package-inspector">
              <div className="inspector-header">
                <b>Signed Work Package Specification</b>
                <small>SHA-256 Verified</small>
              </div>
              <div className="inspector-details">
                <KV label="Action" value={step?.parameters?.description || step?.capability} />
                <KV label="Technician" value={binding?.technician_id || "Lead Technician"} />
                <KV label="Downtime" value={`${intervention?.estimated_downtime_minutes ?? 45} min`} />
                <KV label="Cost / Avoided" value={`${money0(intervention?.estimated_cost)} / +${money0(intervention?.estimated_avoided_loss)}`} />
                {step?.parameters && (
                  <div className="inspector-params">
                    <small>Dispatched Parameters</small>
                    <code>{JSON.stringify(step.parameters, null, 2)}</code>
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="awaiting-synthesis">
          <span className="synthesis-shield"><ShieldCheckIcon size={14} color="var(--amber)" /></span>
          <div>
            <b>Policy Gate Armed · Deterministic Boundary</b>
            <p>Application gate enforces cryptographic hash binding and human authorization on all promoted machine actions.</p>
          </div>
        </div>
      )}
      {decision && (
        <div className={`decision ${decision.decision.toLowerCase()}`}>
          <b>{decision.decision}</b>
          <span>{decision.actor_role} · {decision.actor_id}</span>
          <small>bound to the viewed intervention hash</small>
        </div>
      )}
    </Card>
  );
}

function OutcomeCard({ incident, view, verifyOutcome, pending }) {
  const receipts = view.execution_receipts || [], receipt = receipts[receipts.length - 1];
  const plans = view.observation_plans || [], plan = plans[plans.length - 1];
  const outcomes = view.outcomes || [], outcome = outcomes[outcomes.length - 1];
  const phase = incident.lifecycle?.phase;
  const isObserving = phase === "OBSERVING" && !outcome;
  const [verifying, setVerifying] = useState(false);

  const handleVerify = async () => {
    if (!verifyOutcome || verifying) return;
    setVerifying(true);
    try {
      await verifyOutcome(incident.incident_id);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <Card title="Execution & Outcome" icon="◉" meta="Deterministic Verification">
      <div className="outcome-flow">
        <div className={receipt ? "done" : ""}>
          <i>{receipt ? "✓" : "1"}</i>
          <span><b>Execution</b><small>{receipt?.status || "Pending"}</small></span>
        </div>
        <em>→</em>
        <div className={plan ? "active" : ""}>
          <i>{plan ? "◌" : "2"}</i>
          <span><b>Observe</b><small>{plan ? "Active" : "Pending"}</small></span>
        </div>
        <em>→</em>
        <div className={outcome ? "done" : ""}>
          <i>{outcome ? "✓" : "3"}</i>
          <span><b>Verify</b><small>{outcome?.result || "Pending"}</small></span>
        </div>
      </div>

      {receipt ? (
        <div className="receipt">
          <span><small>Execution Receipt</small><CopyId value={receipt.id} /></span>
          <Status value={receipt.status}>{receipt.status}</Status>
          <p>{Object.entries(receipt.external_ids || {}).map(([key, value]) => `${key}: ${value}`).join(" · ") || receipt.adapter}</p>
        </div>
      ) : (
        <div className="awaiting-synthesis">
          <span className="synthesis-dot" />
          <div>
            <b>Execution Standby</b>
            <p>Awaiting intervention authorization and technician dispatch.</p>
          </div>
        </div>
      )}

      {isObserving && (
        <div className="observing-station">
          <div className="observing-callout">
            <span className="pulse-ring" />
            <div>
              <b>Execution Confirmed · Telemetry Observation Active</b>
              <p>Physical sensor telemetry is being gathered and evaluated against nominal safety envelopes.</p>
            </div>
          </div>
          <button
            type="button"
            className="btn-verify-outcome"
            disabled={verifying || !!pending}
            onClick={handleVerify}
            title="Explicitly evaluate post-maintenance telemetry against safety envelope (Step 14)"
          >
            <ZapIcon size={12} />
            <span>{verifying ? "Verifying Sensor Envelopes…" : "Run Verification Now (Step 14)"}</span>
          </button>
        </div>
      )}

      {outcome && (
        <div className={`outcome-result ${tone(outcome.result)}`}>
          <b>{outcome.result.replaceAll("_", " ")}</b>
          <p>{outcome.reason}</p>
          <div>
            {Object.entries(outcome.before_metrics || {}).slice(0, 3).map(([key, value]) => (
              <span key={`b-${key}`}>{key}: {Number(value).toFixed(2)} before</span>
            ))}
            {Object.entries(outcome.after_metrics || {}).slice(0, 3).map(([key, value]) => (
              <span key={`a-${key}`}>{key}: {Number(value).toFixed(2)} after</span>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function AuditLedgerDrawer({ evidence, events }) {
  const [tab, setTab] = useState("evidence");
  const [expanded, setExpanded] = useState(false);
  const evidenceItems = useMemo(() => [...evidence].reverse(), [evidence]);
  const eventItems = useMemo(() => [...events].reverse(), [events]);

  return (
    <section className="audit-ledger-drawer detail-card">
      <div className="drawer-header">
        <div className="drawer-tabs">
          <button
            className={`drawer-tab-btn ${tab === "evidence" ? "active" : ""}`}
            onClick={() => setTab("evidence")}
          >
            <span>▤</span>
            <b>Evidence Ledger</b>
            <small>{evidence.length}</small>
          </button>
          <button
            className={`drawer-tab-btn ${tab === "events" ? "active" : ""}`}
            onClick={() => setTab("events")}
          >
            <span>⋮</span>
            <b>Application Audit Trail</b>
            <small>{events.length}</small>
          </button>
        </div>
        <button
          className="drawer-expand-toggle"
          onClick={() => setExpanded(!expanded)}
          title={expanded ? "Collapse drawer" : "Expand drawer"}
        >
          {expanded ? "Show Compact ▲" : "Expand Full Audit ▼"}
        </button>
      </div>

      <div className={`drawer-content ${expanded ? "expanded" : ""}`}>
        {tab === "evidence" && (
          <div className="evidence-list">
            {evidenceItems.slice(0, expanded ? 120 : 6).map((item) => (
              <div key={item.id} className="evidence-row">
                <span className={`source-mark ${item.provenance?.toLowerCase()}`}>
                  {item.kind === "model_signal" ? "◆" : "●"}
                </span>
                <div>
                  <b>{item.kind.replaceAll("_", " ")}</b>
                  <p>{item.summary}</p>
                  <small>{item.source_system} · {item.provenance} · {item.quality}</small>
                </div>
                <CopyId value={item.id} short />
              </div>
            ))}
            {evidenceItems.length === 0 && <EmptyLine text="No durable evidence records recorded." />}
          </div>
        )}

        {tab === "events" && (
          <div className="event-list">
            {eventItems.slice(0, expanded ? 150 : 8).map((event) => (
              <div key={event.id}>
                <i className={tone(event.event_type)} />
                <span>
                  <b>{event.event_type.replaceAll("_", " ")}</b>
                  <small>revision {event.revision} · {relativeTime(event.created_at)}</small>
                </span>
              </div>
            ))}
            {eventItems.length === 0 && <EmptyLine text="No application events committed yet." />}
          </div>
        )}
      </div>
    </section>
  );
}

function EmptyCommand({ threshold }) { return <div className="empty-command"><ShieldMark /><h2>Operon is monitoring the factory</h2><p>A predictive signal at {pct(threshold)} opens a durable incident. Every step after that is evidence-bound and independently governed.</p><Invariant /><div className="empty-pipeline">Telemetry → predictive signal → incident → investigation → human-governed action → observed outcome</div></div>; }
function Panel({ title, meta, children }) { return <section className="panel"><div className="panel-title"><h2>{title}</h2><span>{meta}</span></div>{children}</section>; }
function Card({ title, icon, meta, accent = "", children }) { return <section className={`detail-card ${accent}`}><div className="card-title"><span>{icon}</span><h2>{title}</h2><small>{meta}</small></div>{children}</section>; }
function Status({ value, children }) { return <span className={`status ${tone(value)}`}>{children}</span>; }
function KV({ label, value }) { return <div className="kv"><small>{label}</small><b>{value || "Not recorded"}</b></div>; }
function EmptyLine({ text }) { return <div className="empty-line"><i />{text}</div>; }
function CopyId({ value, short = false }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span>—</span>;

  const handleCopy = (e) => {
    e.stopPropagation();
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    }
  };

  const displayText = short
    ? `${value.slice(0, 7)}…`
    : value.length > 22
    ? `${value.slice(0, 12)}…${value.slice(-5)}`
    : value;

  return (
    <span className="copy-id-group">
      <code
        className={`copy-id-badge ${copied ? "copied" : ""}`}
        title={copied ? "Copied to clipboard!" : `Click to copy ID: ${value}`}
        onClick={handleCopy}
      >
        {displayText}
      </code>
      <button
        type="button"
        className={`copy-id-btn ${short ? "compact" : ""} ${copied ? "copied" : ""}`}
        title={copied ? "Copied to clipboard!" : `Copy ID: ${value}`}
        onClick={handleCopy}
        aria-label="Copy ID"
      >
        {copied ? (
          <>
            <CheckCircleIcon size={10} color="var(--green)" />
            {!short && <span>Copied!</span>}
          </>
        ) : (
          <>
            <CopyIcon size={10} />
            {!short && <span>Copy</span>}
          </>
        )}
      </button>
    </span>
  );
}
function Verdict({ item }) { return <div className={`verdict ${tone(item.decision)}`}><b>{item.decision === "ACCEPT" ? "✓ Critic + application validation passed" : item.decision}</b>{(item.blocking_issues || []).length > 0 && <p>{item.blocking_issues.join(" · ")}</p>}<small>{item.validation_policy_version || "validation policy"}</small></div>; }
function tone(value = "") { const v = String(value).toUpperCase(); if (["HEALTHY", "CLOSED", "CONFIRMED", "ACCEPT", "APPROVE", "APPROVED", "SUCCEEDED", "VERIFIED_RECOVERY", "READY"].includes(v)) return "good"; if (["WARNING", "AWAITING_APPROVAL", "AWAITING_EVIDENCE", "OBSERVING", "PENDING", "CONDITIONS", "SIGNAL"].includes(v)) return "warn"; if (["CRITICAL", "ESCALATED", "EXECUTION_FAILED", "FAILED", "REJECT", "REJECTED", "REGRESSED", "NOT_RECOVERED", "ERROR"].includes(v)) return "bad"; if (v.includes("CLOSED") || v.includes("OUTCOME_RECORDED")) return "good"; if (v.includes("EXECUTION") || v.includes("APPROVAL")) return "warn"; return "info"; }
function roleName(role) { return ({ diagnostic: "Diagnostic Specialist", engineering: "Engineering Specialist", operations: "Operations Specialist", critic: "Critic / Validator", planner: "Maintenance Planner", supervisor: "Reliability Supervisor" })[role] || "Specialist"; }
function inferRole(value = {}) { if ("competing_hypotheses" in value) return "diagnostic"; if ("intervention_feasibility" in value) return "engineering"; if ("resource_feasibility" in value) return "operations"; if ("recommendation" in value) return "critic"; if ("proposed_steps" in value) return "planner"; return "agent"; }
function formatWindow(start, end) { if (!start) return null; const fmt = (v) => new Date(v).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); return `${fmt(start)} – ${fmt(end)}`; }
function relativeTime(value) { return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""; }
