import { ClassIcon, Dot, StatusTag } from "../../primitives/index.jsx";
import { risk as fmtRisk, num } from "../../lib/format.js";
import { statusTone } from "../../state/selectors.js";

export function AssetNominalBoard({ state, focusId }) {
  const asset = (state.fleet || []).find((a) => a.equipment_id === focusId) || state.fleet?.[0] || {};
  const tone = statusTone(asset.status || "HEALTHY");
  const point = asset.point || {};

  const channels = [
    { label: "Rotational Speed", val: point.rot_speed ?? 1460, unit: "rpm", normal: "1380 – 1520 rpm", status: "Nominal" },
    { label: "Torque", val: num(point.torque ?? 40.0, 1), unit: "N·m", normal: "30.0 – 50.0 N·m", status: "Nominal" },
    { label: "Temperature Rise", val: num(point.temp_diff ?? 7.1, 1), unit: "°C", normal: "< 10.0 °C", status: "Nominal" },
    { label: "Tool Wear", val: point.tool_wear ?? 38, unit: "min", normal: "< 200 min", status: "Nominal" },
    { label: "Vibration", val: num(point.vibration ?? 1.6, 1), unit: "mm/s", normal: "< 2.5 mm/s", status: "Nominal" },
  ];

  const failureModes = [
    { code: "TWF", label: "Tool Wear Failure", status: "Guarded" },
    { code: "HDF", label: "Heat Dissipation Failure", status: "Guarded" },
    { code: "PWF", label: "Power Failure", status: "Guarded" },
    { code: "OSF", label: "Overstrain Failure", status: "Guarded" },
    { code: "RNF", label: "Random Component Failure", status: "Guarded" },
  ];

  return (
    <div className="nominal-board">
      <div className="nominal-header">
        <div className="nominal-title-group">
          <span className="lbl">EQUIPMENT OPERATIONAL BASELINE</span>
          <h2 className="nominal-asset-name">
            <ClassIcon cls={asset.equipment_class} size={15} />
            <span>{asset.name || focusId}</span>
            <span className="t4">·</span>
            <span className="mono">{asset.equipment_id}</span>
          </h2>
        </div>
        <div className="nominal-metrics">
          <div className="nominal-metric-block">
            <span className="lbl">HEALTH SCORE</span>
            <span className="mono t1">{num(asset.health_score ?? 0.95, 2)}</span>
          </div>
          <div className="nominal-metric-block">
            <span className="lbl">24H FAILURE RISK</span>
            <span className={`mono tone-${tone}`}>{fmtRisk(asset.failure_prob ?? 0.09)}</span>
          </div>
          <div className="nominal-metric-block">
            <span className="lbl">STATUS</span>
            <StatusTag value={asset.status || "HEALTHY"} />
          </div>
        </div>
      </div>

      <div className="nominal-section">
        <div className="nominal-sec-head">
          <span className="lbl">PHYSICAL SCADA TELEMETRY ENVELOPES</span>
          <span className="ph-meta mono">5 continuous sensor channels active</span>
        </div>
        <div className="nominal-channel-grid">
          {channels.map((ch) => (
            <div key={ch.label} className="nominal-ch-card">
              <span className="ch-lbl">{ch.label}</span>
              <div className="ch-val-row">
                <span className="ch-val mono">{ch.val}</span>
                <span className="ch-unit">{ch.unit}</span>
              </div>
              <div className="ch-foot">
                <span className="ch-range mono">{ch.normal}</span>
                <span className="ch-status ok"><Dot tone="ok" />{ch.status}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="nominal-section">
        <div className="nominal-sec-head">
          <span className="lbl">PREDICTIVE FAILURE MODE SURVEILLANCE</span>
          <span className="ph-meta mono">AI4I multi-class sensor model</span>
        </div>
        <div className="nominal-modes-grid">
          {failureModes.map((fm) => (
            <div key={fm.code} className="nominal-mode-card">
              <span className="mode-code mono">{fm.code}</span>
              <span className="mode-name">{fm.label}</span>
              <span className="mode-state ok"><Dot tone="auth" />{fm.status}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="nominal-guarantee">
        <Dot tone="auth" />
        <span>Continuous automated surveillance active. Telemetry scored against warning band {fmtRisk(state.warnThreshold ?? 0.45)} and incident trigger gate {fmtRisk(state.triggerThreshold ?? 0.80)}.</span>
      </div>
    </div>
  );
}
