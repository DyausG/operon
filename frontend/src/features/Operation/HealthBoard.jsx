import { ClassIcon, Dot, StatusTag } from "../../primitives/index.jsx";
import { risk as fmtRisk, num } from "../../lib/format.js";
import { statusTone } from "../../state/selectors.js";

export function HealthBoard({ state, focusId, onSelect }) {
  const rows = [...(state.fleet || [])].sort((a, b) => (b.failure_prob ?? 0) - (a.failure_prob ?? 0));
  return (
    <div className="board">
      <div className="board-head"><span className="lbl">Fleet health</span><span className="ph-meta mono">{rows.length} assets · warn {fmtRisk(state.warnThreshold)} · gate {fmtRisk(state.triggerThreshold)}</span></div>
      <table className="tbl">
        <thead><tr><th>Asset</th><th>Class</th><th>Criticality</th><th className="r">Risk</th><th className="r">Health</th><th>Status</th><th>Signature</th></tr></thead>
        <tbody>
          {rows.map((a) => {
            const tone = statusTone(a.status);
            return (
              <tr key={a.equipment_id} className={`tbl-select ${a.equipment_id === focusId ? "is-focus" : ""}`} onClick={() => onSelect && onSelect(a.equipment_id)} tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" && onSelect) onSelect(a.equipment_id); }}>
                <td><span className="tbl-id"><Dot tone={tone} /><span className="mono t1">{a.equipment_id}</span><span className="t3 truncate">{a.name}</span></span></td>
                <td><span className="tbl-cls"><ClassIcon cls={a.equipment_class} size={13} />{String(a.equipment_class || "").replaceAll("_", " ").toLowerCase()}</span></td>
                <td className="t3">{String(a.criticality || "").toLowerCase()}</td>
                <td className={`r mono tone-${tone}`}>{fmtRisk(a.failure_prob)}</td>
                <td className="r mono t2">{num(a.health_score, 2)}</td>
                <td><StatusTag value={a.status} /></td>
                <td className="t3">{a.predicted_mode && a.predicted_mode !== "NONE" ? a.predicted_mode_label : "Nominal signature"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
