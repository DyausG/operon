// Case preview content (08 §4): compact title block, next-step sentence, latest evidence, leading
// hypothesis or diagnosis, plan summary, last 5 record events, Open case / Go to decision.
// Never the decision controls (one approval surface, 07 §20).
import { Link } from "react-router-dom";
import { WB_ROUTES } from "../shell/routes.js";
import { ConditionMarker, Ledger, Muted, Provenance, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { assessment, latestRun } from "../model/cases.js";
import { provenanceOf, stageCompact } from "../model/status.js";
import { clock, when, duration, score } from "../model/format.js";
import { curatedRecord, nextStepSentence } from "./caseCopy.js";

export function CasePreview({ c, now }) {
  const rm = c.rm || {};
  const evidence = (rm.evidence || []).slice().sort((a, b) => String(b.observed_at || "").localeCompare(String(a.observed_at || ""))).slice(0, 3);
  const dx = rm.diagnosis;
  const run = latestRun(rm, "DIAGNOSIS");
  const lead = (assessment(run, "diagnostic")?.competing_hypotheses || [])[0];
  const events = curatedRecord(rm.events).slice(-5).reverse();
  const r = c.requirement;
  return (
    <div className="wb-preview">
      <p className="wb-preview-ref"><span className="wb-mono">{c.ref}</span></p>
      <p className="wb-preview-name">{c.assetName}</p>
      <Ledger className="is-compact" rows={[
        { label: "Asset condition", value: <><ConditionMarker condition={c.condition} /> <span className="wb-num">{score(c.failureProb)}</span></> },
        { label: "Stage", value: stageCompact(c.phase) },
        { label: "Waiting on", value: <WaitingOn role={c.waiting} /> },
        r?.expires_at ? { label: "Deadline", value: <>{when(r.expires_at)} · in {duration(Date.parse(r.expires_at) - now)}</> } : { label: "Deadline", value: <Muted>No deadline</Muted> },
      ]} />
      <p className="wb-preview-next">{nextStepSentence(c)}</p>
      <div className="wb-preview-actions">
        <Link className="wb-btn wb-btn-primary wb-btn-md" to={WB_ROUTES.case(c.incidentId)}><span>Open case</span></Link>
        {c.phase === "AWAITING_APPROVAL" ? <Link className="wb-btn wb-btn-secondary wb-btn-md" to={WB_ROUTES.case(c.incidentId, "decision")}><span>Go to decision</span></Link> : null}
      </div>

      <h3 className="wb-preview-h">Finding</h3>
      {dx?.status === "ACCEPTED"
        ? <p className="wb-rule-solid">Diagnosis accepted by application promotion{dx.created_at ? ` ${clock(dx.created_at)}` : ""}: {dx.conclusion}</p>
        : lead ? <p className="wb-rule-dashed">Leading hypothesis (advisory): {lead.mechanism}</p>
          : <p className="wb-secondary">Not yet established.</p>}
      {rm.intervention ? (
        <>
          <h3 className="wb-preview-h">Plan</h3>
          <p>{(rm.binding?.work_instructions || []).join(" ") || "Work package drafted."} <span className="wb-secondary">Technician <span className="wb-mono">{rm.binding?.technician_id || "not bound"}</span></span></p>
        </>
      ) : null}

      <h3 className="wb-preview-h">Latest evidence</h3>
      <ul className="wb-mini-list">
        {evidence.map((e) => (
          <li key={e.id}><Provenance kind={provenanceOf(e)} /> <span>{e.summary}</span></li>
        ))}
        {!evidence.length ? <li className="wb-secondary">No evidence recorded.</li> : null}
      </ul>

      <h3 className="wb-preview-h">Record · last 5</h3>
      <ul className="wb-mini-list">
        {events.map((e) => (
          <li key={e.id}><span className="wb-num wb-tertiary">{clock(e.at, { seconds: true })}</span> <span>{e.text}</span></li>
        ))}
      </ul>
      <p className="wb-caption"><Shape name="decision" size={14} decorative tone="nominal" /> Decisions are made only in the case’s decision surface.</p>
    </div>
  );
}
