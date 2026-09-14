import { IdToken, Tag } from "../primitives/index.jsx";
import { processModel } from "../state/selectors.js";

export function ProcessLine({ incident, state }) {
  const model = processModel(incident, state);
  const branchAt = model.branch ? model.index : -1;
  return (
    <div className="proc" aria-label="Reliability lifecycle">
      <ol className="proc-steps">
        {model.steps.map((s, i) => (
          <li key={s.key} className={`seg seg-${s.state} ${s.hold ? "seg-hold" : ""} ${s.blocked ? "seg-blocked" : ""}`}
            title={s.key === "APPROVE" && s.state !== "done" ? "Hold point: cannot proceed without explicit human approval" : s.label}>
            <div className="seg-bar" />
            <span className="seg-label">{s.label}{s.state === "current" && s.sub ? <span className="seg-sub"> · {s.sub}</span> : s.key === "APPROVE" && s.hold ? <span className="seg-sub"> · hold point</span> : null}</span>
            {i === branchAt && model.branch ? <span className="seg-branch" title={model.branch.reason || ""}>{model.branch.label}</span> : null}
          </li>
        ))}
      </ol>
      {incident ? (
        <div className="proc-incident">
          <span className="lbl">Incident</span><IdToken value={incident.incident_id} full />
          <span className="lbl">Revision</span><span className="mono t2">{incident.lifecycle?.revision ?? "—"}</span>
          {incident.lifecycle?.provenance === "SIMULATED" ? <Tag hatched>Simulated lifecycle</Tag> : <Tag tone="auth">Committed lifecycle</Tag>}
        </div>
      ) : null}
    </div>
  );
}
