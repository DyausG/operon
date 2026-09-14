import { Inspectable, KV, Stamp, Tag, ArtifactChip, ProvenanceTag } from "../../primitives/index.jsx";
import { SpecialistChain } from "../SpecialistChain.jsx";
import { runFor, verdictFor } from "../../state/selectors.js";
import { num, title, words } from "../../lib/format.js";

export function DiagnosisRecord({ view, phase, compact = false }) {
  const d = view.diagnosis;
  const verdict = verdictFor(view, "diagnosis");
  const run = runFor(view, "DIAGNOSIS");
  if (!d) return null;
  const validated = phase === "DIAGNOSIS_VALIDATED" || String(d.validation_status || d.status || "").toUpperCase().includes("VALIDATED") || (verdict && verdict.decision === "ACCEPT");
  return (
    <div className="obj">
      <Inspectable id={d.artifact_id || d.id} className="rec rec-auth">
        <div className="rec-head">
          <span className="lbl">Diagnosis</span>
          {validated ? <Stamp>Validated</Stamp> : <Stamp tone="pending">Candidate</Stamp>}
          <ProvenanceTag provenance={d.provenance} runtime={d.runtime} live={d.live_model} compact />
        </div>
        <h2 className="rec-title">{d.conclusion}</h2>
        <div className="kvgrid kvgrid-4">
          <KV label="Likely failure mode" value={d.likely_failure_mode || (d.failure_mode_code ? title(d.failure_mode_code) : null)} />
          <KV label="Affected component" value={d.affected_component} />
          <KV label="Confidence"><span className="conf"><span className="conf-bar"><i style={{ width: `${Math.round((d.confidence ?? 0) * 100)}%` }} /></span><span className="mono">{d.confidence == null ? "not asserted" : num(d.confidence, 2)}</span></span></KV>
          <KV label="Validation" value={d.validation_status ? words(d.validation_status) : d.status ? words(d.status) : null} />
        </div>
        {(d.key_observations || []).length ? <ul className="obs">{d.key_observations.map((o) => <li key={o}>{o}</li>)}</ul> : null}
        {(d.evidence_ids || []).length ? <div className="rec-refs"><span className="lbl">Cited evidence</span><div className="chips">{d.evidence_ids.map((id) => <ArtifactChip key={id} id={id} push={false} />)}</div></div> : null}
      </Inspectable>
      {verdict ? (
        <Inspectable id={verdict.artifact_id || verdict.id} className={`verdict ${verdict.decision === "ACCEPT" ? "" : "verdict-bad"}`}>
          <Stamp tone={verdict.decision === "ACCEPT" ? "auth" : "crit"}>{title(verdict.decision)}</Stamp>
          <span className="verdict-text">{verdict.concise_justification || verdict.validation_summary || (verdict.blocking_issues || []).join(" · ")}</span>
          <span className="verdict-meta mono">{verdict.validation_policy_version || "validation policy"}</span>
        </Inspectable>
      ) : null}
      {!compact && run ? <SpecialistChain run={run} verdict={verdict} stage="DIAGNOSIS" compact /> : null}
      {phase === "DIAGNOSIS_VALIDATED" ? <div className="note"><span className="t3">Diagnosis accepted by the application. Maintenance planning is next; nothing is scheduled or executed from a diagnosis.</span></div> : null}
      {!validated && !verdict ? <div className="note"><Tag tone="adv" dashed>Advisory</Tag><span className="t3">Candidate diagnosis recorded. It carries no authority until the application validates it.</span></div> : null}
    </div>
  );
}
