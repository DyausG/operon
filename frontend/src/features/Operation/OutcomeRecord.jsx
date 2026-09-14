import { Inspectable, KV, Stamp, Tag, ArtifactChip, ProvenanceTag } from "../../primitives/index.jsx";
import { last, statusTone } from "../../state/selectors.js";
import { clock, money0, num, title, words } from "../../lib/format.js";

export function OutcomeBlock({ outcome }) {
  const tone = statusTone(outcome.result);
  const before = outcome.before_metrics || {}, after = outcome.after_metrics || {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return (
    <Inspectable id={outcome.artifact_id || outcome.id} className={`rec rec-auth outcome ${tone === "ok" ? "outcome-ok" : ""}`}>
      <div className="rec-head"><span className="lbl">Outcome verification</span><Stamp tone={tone === "ok" ? "ok" : tone === "crit" ? "crit" : "auth"}>{title(outcome.result)}</Stamp><ProvenanceTag provenance={outcome.provenance} runtime={outcome.runtime} live={outcome.live_model} compact /><span className="ph-meta mono">{outcome.verifier || outcome.verifier_identity || ""}</span></div>
      <p className="rec-body">{outcome.reason}</p>
      {keys.length ? (
        <table className="tbl tbl-ba">
          <thead><tr><th>Metric</th><th className="r">Before</th><th className="r">After</th><th className="r">Δ</th></tr></thead>
          <tbody>{keys.map((k) => { const b = before[k], a = after[k]; return <tr key={k}><td className="t3">{words(k)}</td><td className="r mono">{num(b, 2)}</td><td className="r mono t1">{num(a, 2)}</td><td className={`r mono ${a != null && b != null ? (a < b ? "t-ok" : "t-warn") : ""}`}>{a != null && b != null ? num(a - b, 2) : "—"}</td></tr>; })}</tbody>
        </table>
      ) : null}
      {(outcome.observation_ids || outcome.verification_evidence_ids || []).length ? <div className="rec-refs"><span className="lbl">Verified from</span><div className="chips">{(outcome.observation_ids || outcome.verification_evidence_ids).map((id) => <ArtifactChip key={id} id={id} push={false} />)}</div></div> : null}
    </Inspectable>
  );
}

export function OutcomeRecord({ view, state }) {
  const outcome = last(view.outcomes), closure = last(view.closures), receipt = last(view.execution_receipts);
  const biz = state.business || {};
  return (
    <div className="obj">
      {outcome ? <OutcomeBlock outcome={outcome} /> : null}
      <Inspectable id={closure?.artifact_id || closure?.id} className="rec rec-auth">
        <div className="rec-head"><span className="lbl">Closure</span><Stamp tone="ok">Closed</Stamp>{closure?.provenance ? <ProvenanceTag provenance={closure.provenance} runtime={closure.runtime} live={closure.live_model} compact /> : null}<span className="ph-meta mono">{closure?.closed_at ? clock(closure.closed_at) : ""}</span></div>
        <p className="rec-body">{closure?.summary || "The incident closed after the application verified recovery."}</p>
        <div className="kvgrid kvgrid-4">
          <KV label="Final phase" value={closure?.final_phase || "CLOSED"} mono />
          <KV label="Outcome" mono value={closure?.outcome_id || outcome?.id} />
          <KV label="Execution receipt" mono value={closure?.execution_receipt_id || receipt?.id} />
          <KV label="Incident status" value={closure?.final_incident_status ? words(closure.final_incident_status) : "closed"} />
        </div>
      </Inspectable>
      <div className="rec rec-quiet">
        <div className="rec-head"><span className="lbl">Business impact</span>{biz.provenance === "SIMULATED" || state.demoScenario?.active ? <Tag hatched>Simulated economics</Tag> : <Tag>Configured economics</Tag>}</div>
        <div className="kvgrid kvgrid-4">
          <KV label="Recovered value" mono value={money0(biz.recovered_value)} />
          <KV label="Net impact" mono value={money0(biz.net_value)} />
          <KV label="Planned vs unplanned" mono value={biz.planned_maintenance_minutes != null ? `${biz.planned_maintenance_minutes} min vs ${biz.estimated_downtime_avoided_minutes ?? "—"} min` : null} />
          <KV label="Production impact" value={biz.production_impact} />
        </div>
      </div>
    </div>
  );
}
