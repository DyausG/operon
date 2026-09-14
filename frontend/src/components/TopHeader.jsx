import React from "react";
import {
  ShieldCheckIcon,
  PlayIcon,
  PauseIcon,
  ResetIcon,
  CpuIcon,
  CloudIcon,
  AlertTriangleIcon
} from "../lib.jsx";

export function TopHeader({ state, onReset, onStop, onResume, onDemo }) {
  const totalSecs = Math.max(0, Math.floor((state.plantMin || 0) * 60));
  const hrs = Math.floor(totalSecs / 3600);
  const mins = Math.floor((totalSecs % 3600) / 60);
  const secs = totalSecs % 60;
  const timerStr = `T+ ${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;

  const provenance = state.reasoningProvenance || {};
  const isAgentcore = provenance.backend === "agentcore";
  const streamStatus = !state.connected ? "offline" : state.running ? "online" : "paused";
  const streamLabel = !state.connected ? "RECONNECTING" : state.running ? "LIVE STREAM" : "STREAM PAUSED";
  const plantName = state.meta?.plant || "PIMA-01 REFINERY";

  return (
    <header className="topbar-industrial" role="banner">
      {/* Left: Brand Identity & Facility Context */}
      <div className="topbar-left-deck">
        <div className="brand-industrial">
          <div className="brand-glyph">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="12 2 2 7 12 12 22 7 12 2" />
              <polyline points="2 17 12 22 22 17" />
              <polyline points="2 12 12 17 22 12" />
            </svg>
          </div>
          <div className="brand-meta">
            <div className="brand-title-row">
              <span className="brand-name">OPERON</span>
              <span className="brand-release-tag">v2.4</span>
            </div>
            <span className="brand-subtitle">RELIABILITY SUPERVISOR</span>
          </div>
        </div>

        <div className="facility-chip" title="Active supervisory sector">
          <span className="facility-label">SECTOR</span>
          <span className="facility-value">{plantName}</span>
        </div>
      </div>

      {/* Center: Real-Time Telemetry & Guardrail Interlock Status */}
      <div className="topbar-center-deck">
        <div className={`telemetry-pill ${streamStatus}`}>
          <span className="telemetry-pip" />
          <span className="telemetry-status-text">{streamLabel}</span>
          <span className="telemetry-freq">1.0 Hz</span>
        </div>

        <div className="runtime-clock" title="Plant Operations Elapsed Mission Time">
          <span className="clock-label">MISSION TIME</span>
          <span className="clock-value">{timerStr}</span>
        </div>

        <div className="guardrail-chip" title="HITL Policy Gate: Deterministic execution enforcement">
          <ShieldCheckIcon size={12} color="var(--signal-nominal)" />
          <span className="guardrail-text">HITL GUARDRAIL ACTIVE</span>
        </div>
      </div>

      {/* Right: Supervisory Controls & Backend Mode */}
      <div className="topbar-right-deck">
        <div className="engine-mode-pill" title={isAgentcore ? "AWS Bedrock AgentCore autonomous reasoning backend" : "Local deterministic safety supervisor engine"}>
          {isAgentcore ? <CloudIcon size={12} /> : <CpuIcon size={12} />}
          <span className="engine-mode-label">{isAgentcore ? "BEDROCK AGENTCORE" : "DETERMINISTIC"}</span>
        </div>

        <div className="control-toolbar">
          {state.running ? (
            <button
              className="tool-btn pause"
              onClick={onStop}
              title="Pause real-time telemetry stream"
              aria-label="Pause telemetry"
            >
              <PauseIcon size={11} />
              <span>Pause</span>
            </button>
          ) : (
            <button
              className="tool-btn resume"
              onClick={onResume}
              title="Resume real-time telemetry stream"
              aria-label="Resume telemetry"
            >
              <PlayIcon size={11} />
              <span>Resume</span>
            </button>
          )}

          <button
            className="tool-btn anomaly"
            onClick={onDemo}
            title="Inject real-time degradation anomaly onto active asset"
            aria-label="Simulate degradation anomaly"
          >
            <AlertTriangleIcon size={12} color="var(--signal-warning)" />
            <span>Simulate Anomaly</span>
          </button>

          <button
            className="tool-btn reset"
            onClick={onReset}
            title="Reset all plant telemetry, alarms, and agent session state"
            aria-label="Reset system"
          >
            <ResetIcon size={11} />
            <span>Reset</span>
          </button>
        </div>
      </div>
    </header>
  );
}
