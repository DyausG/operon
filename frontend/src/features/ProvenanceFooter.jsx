import { money0 } from "../lib/format.js";
import { Count } from "../primitives/index.jsx";

export function ProvenanceFooter({ state }) {
  const biz = state.business || {}, demo = state.demoScenario || {}, prov = state.reasoningProvenance || {};
  // During a Guided Demo the scenario's own reasoning descriptor is authoritative for what ran.
  const reasoning = demo.active && demo.reasoning ? demo.reasoning : prov;
  const runtime = reasoning.backend || "none";
  const provenance = reasoning.provenance || "none";
  const live = reasoning.live_model ?? false;
  const model = live ? `${reasoning.provider}${reasoning.model ? ` · ${reasoning.model}` : ""}` : "none";
  return (
    <footer className="foot">
      <span>Recovered value <b>{money0(biz.recovered_value || 0)}</b></span>
      <span>Events recovered <b><Count value={biz.events_prevented || 0} /></b></span>
      {biz.estimated_downtime_avoided_minutes != null ? <span>Planned <b>{biz.planned_maintenance_minutes ?? "—"} min</b> vs unplanned <b>{biz.estimated_downtime_avoided_minutes} min</b></span> : null}
      {biz.oee_baseline != null ? <span>OEE <b>{Math.round(biz.oee_baseline * 100)}%</b></span> : null}
      {biz.provenance === "SIMULATED" || demo.active ? <span className="tag tag-hatched">economics simulated</span> : null}
      {demo.active && demo.scenario ? <span className="tag tag-hatched" title={`scenario ${demo.scenario.id} · seed ${demo.scenario.seed}`}>scenario {demo.scenario.id}</span> : null}
      <span className="foot-right">
        <span>backend <b>{runtime}</b></span>
        <span>model <b>{model}</b></span>
        <span>live_model <b>{String(live)}</b></span>
        <span>provenance <b>{provenance}</b></span>
        <span>{state.connected ? "stream connected" : "stream reconnecting"}</span>
      </span>
    </footer>
  );
}
