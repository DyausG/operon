import { Inspectable, IdToken, Btn, ArtifactChip, Tag, Stamp } from "../../primitives/index.jsx";
import { PlanGrid } from "./PlanAssembly.jsx";
import { last, verdictFor, runFor } from "../../state/selectors.js";

export function ApprovalGate({ incident, view, approve, reject, pending }) {
  const lc = incident.lifecycle || {};
  const req = last(view.requirements);
  const item = view.intervention, binding = view.binding;
  const verdict = verdictFor(view, "intervention");
  const runs = view.agent_runs || [];
  const can = !!lc.requirement_id;
  return (
    <div className="obj gate">
      <div className="gate-adv">
        <span className="lbl">Reasoning complete</span>
        <span className="t2">{runs.length} specialist run{runs.length === 1 ? "" : "s"} · {(runs[runs.length - 1]?.delegations || []).length} structured reviews</span>
        {verdict ? <Inspectable id={verdict.artifact_id || verdict.id} as="span" className="gate-verdict"><Stamp>Validated</Stamp><span className="t3">{verdict.concise_justification || verdict.validation_summary}</span></Inspectable> : null}
        <div className="chips">{(item?.review_ids || []).map((id) => <ArtifactChip key={id} id={id} tone="adv" push={false} />)}</div>
      </div>
      <Inspectable id={item?.artifact_id || item?.id} className="rec rec-auth gate-plan">
        <div className="rec-head"><span className="lbl">Exact plan</span><span className="ph-meta">{item?.summary}</span></div>
        <PlanGrid item={item} binding={binding} dense />
      </Inspectable>
      <Inspectable id={req?.artifact_id || req?.id} className="bind">
        <span className="lbl">Bound to</span><IdToken value={lc.intervention_id || req?.intervention_id} full />
        <span className="lbl">Package</span><span className="mono t2">{req?.work_package_id || binding?.work_package_id || "—"}{req?.work_package_version ? ` · v${req.work_package_version}` : ""}</span>
        <span className="lbl">Hash</span><IdToken value={lc.intervention_hash || req?.intervention_hash} hash />
        <span className="lbl">Revision</span><span className="mono t2">{lc.context_revision ?? lc.revision ?? "—"}</span>
        <span className="lbl">Policy</span><span className="mono t2 truncate">{req?.policy_version || "application policy"}</span>
        <span className="lbl">Requirement</span><IdToken value={lc.requirement_id || req?.id} full />
      </Inspectable>
      {(req?.conditions || []).length ? <ul className="conds">{req.conditions.map((c) => <li key={c}>{c}</li>)}</ul> : null}
      <div className="gate-actions">
        <Btn primary disabled={!can || pending} onClick={() => approve(incident)} className="gate-approve">{pending ? "Submitting…" : "Approve exact plan and dispatch"}</Btn>
        <Btn disabled={!can || pending} onClick={() => reject(incident)}>Reject</Btn>
        <span className="gate-note t3">{can ? `Approval binds this hash at revision ${lc.context_revision ?? lc.revision}. Nothing has been executed.` : "Awaiting an approval requirement from the application."}</span>
        {lc.provenance === "SIMULATED" ? <Tag hatched>Simulated · no real dispatch</Tag> : null}
      </div>
    </div>
  );
}
