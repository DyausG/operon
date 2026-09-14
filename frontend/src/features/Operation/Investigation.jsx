import { EvidenceSlots } from "./EvidenceSlots.jsx";
import { SpecialistChain } from "../SpecialistChain.jsx";
import { runFor, verdictFor, hasInspection } from "../../state/selectors.js";
import { Icons } from "../../primitives/index.jsx";

export function Investigation({ incident, view, phase }) {
  const received = hasInspection(view);
  const blocked = phase === "AWAITING_EVIDENCE" && !received;
  const run = runFor(view, "DIAGNOSIS");
  const actions = (view.agent_actions || []).filter((a) => a.status);
  return (
    <div className="obj">
      {blocked ? <div className="banner banner-warn">{Icons.warn({})}<span><b>Progression blocked.</b> Physical inspection is required before any diagnosis can be validated. The advisory chain has requested trusted input; it cannot supply it.</span></div> : null}
      {phase === "AWAITING_EVIDENCE" && received ? <div className="banner banner-auth"><Icons.check /><span><b>Trusted inspection received.</b> The application now validates the diagnosis against the complete evidence packet.</span></div> : null}
      <EvidenceSlots evidence={view.evidence || []} blocked={blocked} />
      {run ? <SpecialistChain run={run} verdict={verdictFor(view, "diagnosis")} stage="DIAGNOSIS" /> : (
        <div className="note">
          {actions.length ? actions.map((a) => <span key={a.id} className="note-line"><span className="mono t3">{a.actor}</span><span>{a.summary}</span></span>) : null}
          <span className="t3">{incident.lifecycle?.supervisor_available === false && !incident.lifecycle?.provenance ? "Durable evidence is ready; the reasoning runtime is not connected." : "Structured investigation in progress. Specialist output appears here as it is recorded."}</span>
        </div>
      )}
    </div>
  );
}
