import { money0 } from "../lib/format.js";
import { Count } from "../primitives/index.jsx";

export function ProvenanceFooter({ state }) {
  const biz = state.business || {}, demo = state.demoScenario || {}, prov = state.reasoningProvenance || {};
  const runtime = demo.active ? demo.runtime : prov.runtime || prov.backend || "local";
  const provenance = demo.active ? "SIMULATED" : prov.provenance || "LOCAL";
  const live = demo.active ? false : prov.live_model ?? (prov.backend === "agentcore");
  return (
    <footer className="foot">
      <span>Recovered value <b>{money0(biz.recovered_value || 0)}</b></span>
      <span>Events recovered <b><Count value={biz.events_prevented || 0} /></b></span>
      {biz.estimated_downtime_avoided_minutes != null ? <span>Planned <b>{biz.planned_maintenance_minutes ?? "—"} min</b> vs unplanned <b>{biz.estimated_downtime_avoided_minutes} min</b></span> : null}
      {biz.oee_baseline != null ? <span>OEE <b>{Math.round(biz.oee_baseline * 100)}%</b></span> : null}
      {biz.provenance === "SIMULATED" || demo.active ? <span className="tag tag-hatched">economics simulated</span> : null}
      <span className="foot-right">
        <span>runtime <b>{runtime}</b></span>
        <span>live_model <b>{String(live)}</b></span>
        <span>provenance <b>{provenance}</b></span>
        <span>{state.connected ? "stream connected" : "stream reconnecting"}</span>
      </span>
    </footer>
  );
}
