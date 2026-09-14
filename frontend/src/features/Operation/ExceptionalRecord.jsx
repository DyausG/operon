import { Stamp, KV, Icons } from "../../primitives/index.jsx";
import { DecisionLine } from "./ExecutionRecord.jsx";
import { last } from "../../state/selectors.js";
import { title } from "../../lib/format.js";

const NEXT = {
  CANCELLED: "Terminal. Admission is released; a new signal opens a new incident.",
  ESCALATED: "Remains active. An explicit application decision resumes investigation or cancels.",
  EXECUTION_FAILED: "Remains active. Policy and durable receipts decide whether a failed step may be retried from READY, or the incident returns to investigation.",
};

export function ExceptionalRecord({ incident, view }) {
  const phase = incident.lifecycle?.phase;
  const decision = last(view.approval_decisions);
  return (
    <div className="obj">
      <div className="banner banner-crit">{Icons.warn({})}<span><b>{title(phase)}.</b> {incident.lifecycle?.last_reason}</span></div>
      {decision ? <DecisionLine decision={decision} /> : null}
      <div className="rec rec-auth">
        <div className="rec-head"><span className="lbl">Lifecycle record</span><Stamp tone="crit">{title(phase)}</Stamp><span className="ph-meta mono">rev {incident.lifecycle?.revision}</span></div>
        <div className="kvgrid kvgrid-3">
          <KV label="Incident" mono value={incident.incident_id} />
          <KV label="Last authoritative revision" mono value={incident.lifecycle?.revision} />
          <KV label="What can happen next" value={NEXT[phase] || "Application decision required."} />
        </div>
      </div>
    </div>
  );
}
