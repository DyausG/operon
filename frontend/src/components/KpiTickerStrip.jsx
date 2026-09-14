import React from "react";
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  ActivityIcon,
  TrendingUpIcon,
  money0,
  pct
} from "../lib.jsx";

export function KpiTickerStrip({ state, alerts }) {
  // Zone 1: Fleet Telemetry & Exception Aggregates
  const totalAssets = state.fleet?.length || 8;
  const criticalAssets = (state.fleet || []).filter((a) => a.status === "CRITICAL");
  const warningAssets = (state.fleet || []).filter((a) => a.status === "WARNING");
  const hasCritical = criticalAssets.length > 0;
  const hasWarning = warningAssets.length > 0;
  const nominalCount = totalAssets - criticalAssets.length - warningAssets.length;

  // Active Incident Pipeline
  const investigating = (alerts || []).filter((a) =>
    ["INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED", "PLANNING"].includes(
      a.lifecycle?.phase || a.status
    )
  ).length;

  const observing = (alerts || []).filter((a) =>
    ["EXECUTING", "OBSERVING", "READY"].includes(a.lifecycle?.phase || a.status)
  ).length;

  const activeAlert = (alerts || []).find(
    (a) => !["CLOSED", "FAILED", "CANCELLED"].includes(a.lifecycle?.phase || a.status)
  );

  const activePhase = activeAlert?.lifecycle?.phase || activeAlert?.status || "IDLE";

  // Zone 2: Industrial Efficiency (Line OEE)
  const currentOee = state.business?.current_oee ?? 0.874;
  const targetOee = state.business?.target_oee ?? 0.85;
  const isOeeBelow = currentOee < targetOee;
  const oeeDelta = currentOee - targetOee;

  // Zone 3: Economic Exposure & Return
  const recoveredVal = state.business?.averted_downtime_cost ?? 0;
  const eventsPrevented = state.business?.failures_prevented ?? 0;
  const hasActiveRisk =
    hasCritical ||
    hasWarning ||
    (activeAlert && !["CLOSED", "FAILED", "CANCELLED"].includes(activeAlert.lifecycle?.phase));
  const netVal = state.business?.net_impact ?? 0;
  const netFormatted = netVal > 0 ? `+${money0(netVal)}` : netVal < 0 ? `-${money0(Math.abs(netVal))}` : "$0";
  const dtCostFormatted = state.business?.downtime_cost_per_hour
    ? "$" + Math.round(state.business.downtime_cost_per_hour).toLocaleString() + "/hr"
    : "$25,000/hr";

  return (
    <nav className="kpi-ticker-strip" aria-label="Telemetry Benchmarks and Operational Ticker">
      {/* Module 1: Fleet Health & Exception Summary */}
      <div className={`ticker-cell ${hasCritical ? "state-critical" : hasWarning ? "state-warning" : "state-nominal"}`}>
        <div className="ticker-cell-header">
          <span className="ticker-tag">FLEET HEALTH</span>
          <span className="ticker-meta">{totalAssets} Monitored</span>
        </div>
        <div className="ticker-cell-body">
          <span className="ticker-metric">
            {hasCritical ? `${criticalAssets.length} Critical` : hasWarning ? `${warningAssets.length} Degrading` : "100% In-Spec"}
          </span>
        </div>
        <div className="ticker-cell-footer">
          {hasCritical ? (
            <span className="ticker-status-pill critical">
              <span className="status-pip red" />
              <span>Alarm: {criticalAssets[0].equipment_id}</span>
            </span>
          ) : hasWarning ? (
            <span className="ticker-status-pill warning">
              <span className="status-pip amber" />
              <span>Drift: {warningAssets[0].equipment_id}</span>
            </span>
          ) : (
            <span className="ticker-status-pill nominal">
              <span className="status-pip green" />
              <span>All {totalAssets} within envelope</span>
            </span>
          )}
        </div>
      </div>

      <div className="ticker-divider" />

      {/* Module 2: Active Incident & Agent Triage State */}
      <div className={`ticker-cell ${investigating > 0 ? "state-warning" : observing > 0 ? "state-active" : "state-idle"}`}>
        <div className="ticker-cell-header">
          <span className="ticker-tag">AGENT ORCHESTRATION</span>
          <span className="ticker-meta">{activeAlert ? "Run in Progress" : "Supervisor Idle"}</span>
        </div>
        <div className="ticker-cell-body">
          <span className="ticker-metric">
            {investigating > 0 ? `${investigating} Investigating` : observing > 0 ? `${observing} Verifying` : "Standby"}
          </span>
        </div>
        <div className="ticker-cell-footer">
          <span className="ticker-status-pill active-phase">
            <ActivityIcon size={11} color={activeAlert ? "var(--signal-active)" : "var(--text-muted)"} />
            <span className="mono-truncate">{activeAlert ? `${activeAlert.equipment_id} · ${activePhase}` : "Continuous floor telemetry"}</span>
          </span>
        </div>
      </div>

      <div className="ticker-divider" />

      {/* Module 3: Line OEE Telemetry with Target Benchmark Bar */}
      <div className="ticker-cell oee-cell">
        <div className="ticker-cell-header">
          <span className="ticker-tag">LINE OEE</span>
          <span className="ticker-meta">Target: {pct(targetOee)}</span>
        </div>
        <div className="ticker-cell-body oee-row">
          <span className="ticker-metric mono">{pct(currentOee)}</span>
          <span className={`oee-delta-badge ${isOeeBelow ? "negative" : "positive"}`}>
            {oeeDelta >= 0 ? `+${(oeeDelta * 100).toFixed(1)}%` : `${(oeeDelta * 100).toFixed(1)}%`}
          </span>
        </div>
        <div className="ticker-cell-footer oee-benchmark-footer">
          <div className="oee-benchmark-track" title={`Current: ${pct(currentOee)}, Benchmark Target: ${pct(targetOee)}`}>
            <div
              className={`oee-benchmark-fill ${isOeeBelow ? "below-target" : "above-target"}`}
              style={{ width: `${Math.min(100, Math.max(0, currentOee * 100))}%` }}
            />
            <div
              className="oee-target-tick"
              style={{ left: `${Math.min(99, targetOee * 100)}%` }}
              title={`Benchmark target: ${pct(targetOee)}`}
            />
          </div>
          <span className="oee-target-label">
            {hasCritical ? "Bottleneck: Alarm Trip" : hasWarning ? "Bottleneck: Vibration Drift" : "Optimal Throughput"}
          </span>
        </div>
      </div>

      <div className="ticker-divider" />

      {/* Module 4: Averted Downtime Loss vs Active Exposure */}
      <div className="ticker-cell economic-cell">
        <div className="ticker-cell-header">
          <span className="ticker-tag">AVERTED LOSS</span>
          <span className="ticker-meta">Exposure Ledger</span>
        </div>
        <div className="ticker-cell-body">
          <span className="ticker-metric mono positive">
            {recoveredVal > 0 ? money0(recoveredVal) : hasActiveRisk ? "~$25k Risk" : "$0"}
          </span>
        </div>
        <div className="ticker-cell-footer">
          <span className={`ticker-status-pill ${recoveredVal > 0 ? "nominal" : hasActiveRisk ? "warning" : "idle"}`}>
            {recoveredVal > 0 ? (
              <>
                <TrendingUpIcon size={11} color="var(--signal-nominal)" />
                <span>{eventsPrevented} {eventsPrevented === 1 ? "breakdown mitigated" : "breakdowns mitigated"}</span>
              </>
            ) : hasActiveRisk ? (
              <>
                <AlertTriangleIcon size={11} color="var(--signal-warning)" />
                <span>Unmitigated downtime exposure</span>
              </>
            ) : (
              <span>{dtCostFormatted} baseline rate</span>
            )}
          </span>
        </div>
      </div>

      <div className="ticker-divider" />

      {/* Module 5: Realized Economic Net Value */}
      <div className="ticker-cell economic-cell">
        <div className="ticker-cell-header">
          <span className="ticker-tag">NET REALIZED ROI</span>
          <span className="ticker-meta">Intervention Ledger</span>
        </div>
        <div className="ticker-cell-body">
          <span className={`ticker-metric mono ${netVal > 0 ? "positive" : netVal < 0 ? "negative" : "idle"}`}>
            {netFormatted}
          </span>
        </div>
        <div className="ticker-cell-footer">
          <span className="ticker-status-pill idle">
            <span>{hasActiveRisk ? "Evaluating intervention cost" : "Safety margin locked"}</span>
          </span>
        </div>
      </div>
    </nav>
  );
}
