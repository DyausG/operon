import React, { useState, useMemo, useRef } from "react";
import { ResponsiveContainer, AreaChart, Area, YAxis } from "recharts";
import {
  ClassIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  pct,
  STATUS_ORDER
} from "../lib.jsx";

export function TriageExceptionRail({ fleet = [], selected, onSelect }) {
  const [filterMode, setFilterMode] = useState("ALL"); // "ALL" | "EXCEPTIONS" | "NOMINAL"
  const [collapsedNominal, setCollapsedNominal] = useState(false);

  // Partition assets into exceptions vs nominal
  const { exceptions, nominal } = useMemo(() => {
    const sorted = [...fleet].sort(
      (a, b) =>
        (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) ||
        (b.failure_prob ?? 0) - (a.failure_prob ?? 0)
    );

    const exc = [];
    const nom = [];

    sorted.forEach((asset) => {
      if (asset.status === "CRITICAL" || asset.status === "WARNING" || (asset.failure_prob ?? 0) >= 0.4) {
        exc.push(asset);
      } else {
        nom.push(asset);
      }
    });

    return { exceptions: exc, nominal: nom };
  }, [fleet]);

  return (
    <aside className="triage-rail-industrial" aria-label="Triage By Exception Asset Rail">
      {/* Rail Header */}
      <div className="triage-rail-header">
        <div className="triage-header-top">
          <span className="triage-rail-title">SUPERVISORY RAIL</span>
          <span className="triage-total-badge">{fleet.length} ASSETS</span>
        </div>
        <div className="triage-filter-bar">
          <button
            className={`triage-filter-tab ${filterMode === "ALL" ? "active" : ""}`}
            onClick={() => setFilterMode("ALL")}
          >
            All ({fleet.length})
          </button>
          <button
            className={`triage-filter-tab ${filterMode === "EXCEPTIONS" ? "active" : ""}`}
            onClick={() => setFilterMode("EXCEPTIONS")}
          >
            Exceptions ({exceptions.length})
          </button>
          <button
            className={`triage-filter-tab ${filterMode === "NOMINAL" ? "active" : ""}`}
            onClick={() => setFilterMode("NOMINAL")}
          >
            Nominal ({nominal.length})
          </button>
        </div>
      </div>

      <div className="triage-rail-content">
        {/* SECTION 1: PRIORITY EXCEPTIONS (ISA-101 TRIAGE) */}
        {(filterMode === "ALL" || filterMode === "EXCEPTIONS") && (
          <div className="triage-group exceptions-group">
            <div className="triage-group-label">
              <span className="group-title-text">
                <AlertTriangleIcon size={12} color="var(--signal-warning)" />
                <span>ACTIVE EXCEPTIONS ({exceptions.length})</span>
              </span>
              <span className="group-subtext">PRIORITY TRIAGE</span>
            </div>

            {exceptions.length === 0 ? (
              <div className="triage-empty-exceptions">
                <CheckCircleIcon size={13} color="var(--signal-nominal)" />
                <span>Zero active exceptions. Fleet within operating envelope.</span>
              </div>
            ) : (
              <div className="triage-asset-list">
                {exceptions.map((asset) => (
                  <ExceptionAssetItem
                    key={asset.equipment_id}
                    asset={asset}
                    isSelected={selected === asset.equipment_id}
                    onSelect={() => onSelect(asset.equipment_id)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* SECTION 2: NOMINAL ASSETS (MUTED SCADA FLOOR) */}
        {(filterMode === "ALL" || filterMode === "NOMINAL") && (
          <div className="triage-group nominal-group">
            <div
              className="triage-group-label clickable"
              onClick={() => setCollapsedNominal(!collapsedNominal)}
              title="Click to expand/collapse nominal assets"
            >
              <span className="group-title-text">
                <CheckCircleIcon size={12} color="var(--signal-nominal)" />
                <span>IN-ENVELOPE ASSETS ({nominal.length})</span>
              </span>
              <span className="group-toggle-btn">{collapsedNominal ? "Show" : "Hide"}</span>
            </div>

            {!collapsedNominal && (
              <div className="triage-asset-list nominal-list">
                {nominal.map((asset) => (
                  <NominalAssetItem
                    key={asset.equipment_id}
                    asset={asset}
                    isSelected={selected === asset.equipment_id}
                    onSelect={() => onSelect(asset.equipment_id)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function ExceptionAssetItem({ asset, isSelected, onSelect }) {
  const isCritical = asset.status === "CRITICAL";
  const statusLabel = isCritical ? "CRITICAL ALARM" : "WARNING DRIFT";
  const riskValue = asset.failure_prob != null ? pct(asset.failure_prob) : "0%";

  return (
    <div
      role="button"
      tabIndex={0}
      className={`exception-item ${isCritical ? "critical" : "warning"} ${isSelected ? "selected" : ""}`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="exception-item-main">
        <div className="exception-header-row">
          <div className="asset-tag-block">
            <span className={`status-pill-badge ${isCritical ? "critical" : "warning"}`}>
              {statusLabel}
            </span>
            <span className="asset-id-text">{asset.equipment_id}</span>
          </div>
          <div className="asset-risk-box">
            <span className="risk-metric">{riskValue}</span>
            <span className="risk-label">24h Risk</span>
          </div>
        </div>

        <div className="exception-meta-row">
          <span className="asset-name-truncate">{asset.name || asset.equipment_id}</span>
          <span className="telemetry-spark-slot">
            <MicroSpark point={asset.point} status={asset.status} />
          </span>
        </div>
      </div>
    </div>
  );
}

function NominalAssetItem({ asset, isSelected, onSelect }) {
  const riskValue = asset.failure_prob != null ? pct(asset.failure_prob) : "0%";

  return (
    <div
      role="button"
      tabIndex={0}
      className={`nominal-item ${isSelected ? "selected" : ""}`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="nominal-left">
        <span className="nominal-pip" />
        <span className="nominal-id">{asset.equipment_id}</span>
        <span className="nominal-name">{asset.name || asset.equipment_class}</span>
      </div>
      <div className="nominal-right">
        <span className="nominal-risk">{riskValue}</span>
        <span className="nominal-spark-slot">
          <MicroSpark point={asset.point} status={asset.status} isNominal />
        </span>
      </div>
    </div>
  );
}

function MicroSpark({ point, status, isNominal }) {
  const history = useRef([]);
  if (point) history.current = [...history.current, point.prob].slice(-24);

  const strokeColor = isNominal
    ? "#64748b"
    : status === "CRITICAL"
    ? "#ef4444"
    : status === "WARNING"
    ? "#f59e0b"
    : "#10b981";

  const chartData = history.current.map((p, i) => ({ i, p }));

  return (
    <div className="micro-spark-container">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 1, right: 0, bottom: 1, left: 0 }}>
          <YAxis hide domain={[0, 1]} />
          <Area
            dataKey="p"
            type="monotone"
            stroke={strokeColor}
            fill="none"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
