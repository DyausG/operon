import { Inspectable, KV, Stamp, EmptySlot, ArtifactChip, ProvenanceTag, Tag } from "../../primitives/index.jsx";
import { SpecialistChain } from "../SpecialistChain.jsx";
import { runFor, verdictFor } from "../../state/selectors.js";
import { money0, windowLabel, title, words } from "../../lib/format.js";

export function planFields(item, binding) {
  if (!item) return null;
  const step = item.steps?.[0];
  return {
    action: step?.parameters?.description || item.summary || (step?.capability ? words(step.capability) : null),
    part: item.part_id || binding?.parts?.[0]?.part_id ? `${item.part_id || binding?.parts?.[0]?.part_id}${binding?.parts?.[0]?.quantity ? ` ×${binding.parts[0].quantity}` : ""}` : null,
    technician: binding?.technician_id, skill: item.required_skill || binding?.qualification,
    window: windowLabel(item.window_start, item.window_end), priority: item.priority ? title(item.priority) : null,
    cost: item.estimated_cost != null ? money0(item.estimated_cost) : null, avoided: item.estimated_avoided_loss != null ? money0(item.estimated_avoided_loss) : null,
    downtime: item.estimated_downtime_minutes != null ? `${item.estimated_downtime_minutes} min planned` : null,
    risk: item.risk ? title(item.risk) : null, component: item.component,
  };
}

export function PlanGrid({ item, binding, dense = false }) {
  const f = planFields(item, binding);
  const cell = (label, v, mono) => (f && f[v] != null ? <KV key={label} label={label} value={f[v]} mono={mono} /> : <EmptySlot key={label} label={label} hint="assembling" className="kv-slot" />);
  return (
    <div className={`kvgrid kvgrid-4 ${dense ? "kvgrid-dense" : ""}`}>
      {cell("Action", "action")}{cell("Part", "part", true)}{cell("Technician", "technician", true)}{cell("Window", "window", true)}
      {cell("Priority", "priority")}{cell("Cost", "cost", true)}{cell("Avoided loss", "avoided", true)}{cell("Downtime", "downtime", true)}
    </div>
  );
}

export function PlanAssembly({ view, phase }) {
  const item = view.intervention, binding = view.binding;
  const verdict = verdictFor(view, "intervention");
  const run = runFor(view, "INTERVENTION_REVIEW");
  const validated = phase === "INTERVENTION_VALIDATED" || (verdict && verdict.decision === "ACCEPT") || String(item?.status || "").toUpperCase() === "VALIDATED";
  return (
    <div className="obj">
      <Inspectable id={item?.artifact_id || item?.id} className={`rec ${validated ? "rec-auth" : "rec-adv"}`}>
        <div className="rec-head">
          <span className="lbl">Intervention</span>
          {validated ? <Stamp>Validated</Stamp> : item ? <Tag tone="adv" dashed>Draft · advisory</Tag> : <Tag tone="adv" dashed>Assembling</Tag>}
          {item ? <ProvenanceTag provenance={item.provenance} runtime={item.runtime} live={item.live_model} compact /> : null}
          {item?.risk ? <span className="ph-meta mono">risk {words(item.risk)}</span> : null}
        </div>
        <h2 className="rec-title">{item?.summary || item?.steps?.[0]?.parameters?.description || "Maintenance plan is being assembled from engineering, operations, critic, inventory, technician and schedule inputs."}</h2>
        <PlanGrid item={item} binding={binding} />
        {item?.operational_constraint || item?.safety_note ? (
          <div className="rec-lines">
            {item.operational_constraint ? <span><span className="lbl">Constraint</span>{item.operational_constraint}</span> : null}
            {item.safety_note ? <span><span className="lbl">Safety</span>{item.safety_note}</span> : null}
          </div>
        ) : null}
      </Inspectable>
      <div className="bindings">
        <span className="lbl">Bound resources</span>
        {binding ? (
          <div className="chips">
            {binding.work_package_id ? <ArtifactChip id={binding.work_package_id} type="work package" push={false} /> : null}
            {binding.inventory_reservation_id ? <ArtifactChip id={binding.inventory_reservation_id} label={`${binding.parts?.[0]?.part_id || "part"} · ${words(binding.inventory_status || binding.parts?.[0]?.status || "")}`} type="inventory" push={false} /> : null}
            {binding.technician_assignment_id ? <ArtifactChip id={binding.technician_assignment_id} label={`${binding.technician_id} · ${words(binding.technician_availability || "")}`} type="technician" push={false} /> : null}
            {binding.scheduling_record_id ? <ArtifactChip id={binding.scheduling_record_id} label={windowLabel(binding.schedule, binding.window_end) || "window"} type="schedule" push={false} /> : null}
            {!binding.work_package_id ? <span className="t3">{binding.technician_id} · {binding.qualification}</span> : null}
          </div>
        ) : <span className="t3">Not yet bound.</span>}
      </div>
      {run ? <SpecialistChain run={run} verdict={verdict} stage="INTERVENTION_REVIEW" /> : <div className="note"><span className="t3">Engineering, operations and critic review will be recorded here.</span></div>}
    </div>
  );
}
