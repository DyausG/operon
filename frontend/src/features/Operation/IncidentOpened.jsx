import { Inspectable, KV, Readout, Tag, ProvenanceTag } from "../../primitives/index.jsx";
import { num } from "../../lib/format.js";

export function IncidentOpened({ incident, view, asset }) {
  const signal = (view.evidence || []).find((e) => e.kind === "model_signal");
  const attribution = signal?.payload?.attribution || [];
  const max = Math.max(...attribution.map((a) => Math.abs(a.contribution || 0)), 0.0001);
  return (
    <div className="obj">
      <Inspectable id={signal?.artifact_id || signal?.id} className="signal-card">
        <div className="signal-head">
          <div><span className="lbl">Predictive signal</span><h2 className="obj-title">{incident.predicted_mode_label || "Elevated failure risk"}</h2></div>
          <Readout value={incident.failure_prob} decimals={2} size="m" tone="crit" unit="failure risk" />
        </div>
        <div className="signal-body">
          <div className="kvgrid kvgrid-3">
            <KV label="Threshold" mono value={signal?.payload?.threshold != null ? num(signal.payload.threshold, 2) : "—"} />
            <KV label="Source" value={signal?.source_system || signal?.source || "model"} />
            <KV label="Quality">{signal?.quality ? <Tag>{String(signal.quality).replaceAll("SIMULATED", "").replaceAll("_", " ").trim().toLowerCase() || "synthetic"}</Tag> : "—"}</KV>
          </div>
          {attribution.length ? (
            <div className="drivers">
              <span className="lbl">Dominant drivers</span>
              {attribution.slice(0, 4).map((a) => (
                <div key={a.feature} className="driver">
                  <span className="driver-l">{a.label || a.feature}</span>
                  <span className="driver-bar"><i style={{ width: `${(Math.abs(a.contribution || 0) / max) * 100}%` }} /></span>
                  <span className="driver-v mono">{num(a.value, 1)}</span>
                  <span className="driver-c mono">+{num(a.contribution, 2)}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
        <div className="signal-foot"><ProvenanceTag provenance={signal?.provenance || incident.provenance} runtime={signal?.runtime || incident.runtime} live={signal?.live_model ?? incident.live_model} /><span className="t3">Prediction is not a diagnosis. Investigation opens next; nothing is executed from a signal.</span></div>
      </Inspectable>
    </div>
  );
}
