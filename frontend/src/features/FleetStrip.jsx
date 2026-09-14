import { ClassIcon, Dot } from "../primitives/index.jsx";
import { risk as fmtRisk } from "../lib/format.js";
import { statusTone } from "../state/selectors.js";

function Trace({ points }) {
  if (!points || points.length < 2) return <svg className="tile-trace" viewBox="0 0 56 16" preserveAspectRatio="none"><line x1="0" y1="14" x2="56" y2="14" stroke="var(--text-4)" strokeWidth="1" strokeDasharray="2 2" /></svg>;
  const p = points.slice(-26);
  const pts = p.map((pt, i) => `${(i / (p.length - 1)) * 56},${15 - Math.max(0, Math.min(1, pt.prob ?? 0)) * 14}`).join(" ");
  return <svg className="tile-trace" viewBox="0 0 56 16" preserveAspectRatio="none"><polyline points={pts} /></svg>;
}

export function FleetStrip({ state, focusId, onSelect, hasIncident }) {
  const fleet = state.fleet || [];
  return (
    <div className="fleet" role="list" aria-label="Fleet">
      {fleet.map((a) => {
        const tone = statusTone(a.status);
        const selected = a.equipment_id === focusId;
        const dim = hasIncident && !selected && tone === "normal";
        const mode = a.status_source === "active_incident" ? a.status_reason : a.predicted_mode && a.predicted_mode !== "NONE" ? a.predicted_mode_label : "Nominal signature";
        return (
          <button type="button" role="listitem" key={a.equipment_id} className={`tile tone-${tone} ${selected ? "is-selected" : ""} ${dim ? "is-dim" : ""}`}
            onClick={() => onSelect(a.equipment_id)} aria-pressed={selected} title={`${a.name} · ${a.status}`}>
            <span className="tile-id"><Dot tone={tone} /><span className="truncate">{a.equipment_id}</span><span className="cls"><ClassIcon cls={a.equipment_class} size={13} /></span></span>
            <span className={`tile-risk tone-${tone}`}>{fmtRisk(a.failure_prob)}</span>
            <span className="tile-name">{a.name}</span>
            <span className="tile-foot"><span className="tile-mode">{mode}</span><Trace points={state.histories?.[a.equipment_id]} /></span>
          </button>
        );
      })}
    </div>
  );
}
