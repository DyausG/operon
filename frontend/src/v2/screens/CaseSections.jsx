// Case content sections for the F4.1 navigator (layout D). One section is shown at a time; order is
// fixed (Evidence → Investigation → Plan & decision → Work & verification → Record, 07 §2). Advisory
// content keeps the dashed rule, authoritative records the solid rule. No confidence values.
import { Link } from "react-router-dom";
import { IconArrowUpRight } from "@tabler/icons-react";
import { EmptyLine, Icon, Ledger, Muted, Provenance, SimulatedTag } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { RiskChart } from "../components/RiskChart.jsx";
import { assessment, latestRun, openRequests } from "../model/cases.js";
import { OUTCOME, PROVENANCE_LABEL, provenanceOf, withoutConfidence } from "../model/status.js";
import { clock, dayClock, score, sentence, shortId, when, zoneAbbr } from "../model/format.js";
import { DISPATCH_IS_NOT_WORK, VERIFICATION_BASIS, fieldStatus, observingSince, workFacts } from "../model/workBoundary.js";
import { curatedRecord } from "./caseCopy.js";

const QUALITY = { GOOD: "Good", SUSPECT: "Suspect", MISSING: "Missing" };
const HYP = { SUPPORTED: { word: "Supported", shape: "supported" }, REFUTED: { word: "Refuted", shape: "refuted" }, UNRESOLVED: { word: "Unresolved", shape: "unresolved" }, OPEN: { word: "Open", shape: "open" } };
const ROLE_ABBR = { diagnostic: "DX", critic: "CRT", plan: "PLN", planner: "PLN", engineering: "ENG", operations: "OPS" };
export const RUN_STAGE = { DIAGNOSIS: "Diagnosis review", INTERVENTION_REVIEW: "Work package review" };
const RUN_STATUS = { MODEL_COMPLETED: "completed", LIMIT_EXHAUSTED: "stopped: limit reached", TIMEOUT: "stopped: timed out", MODEL_FAILED: "stopped: model failed", INVALID_OUTPUT: "stopped: invalid output", CANCELLED: "cancelled" };

export function runtimeWords(run) {
  const r = run?.reasoning || run?.runtime_identity || {};
  if (r.live_model) return `${r.provider || "provider"} · ${r.model || "model"}`;
  if (r.backend === "deterministic") return "deterministic advisory (no live model)";
  return r.runtime || "runtime not reported";
}

export function runLine(run) {
  if (!run) return null;
  return <>{RUN_STAGE[run.stage] || sentence(run.stage)} · run <span className="wb-mono">{shortId(run.run_id)}</span> · input <span className="wb-mono">R{run.input_revision}</span> · {RUN_STATUS[run.status] || RUN_STATUS[run.termination_reason] || sentence(run.status || run.termination_reason || "status not recorded")} · {runtimeWords(run)}</>;
}

/** Short case summary used in Now: what happened, the current finding, the recommended action. */
export function CaseSummary({ c, trigger }) {
  const rm = c.rm || {};
  const dx = rm.diagnosis;
  const run = latestRun(rm, "DIAGNOSIS");
  const dxA = assessment(run, "diagnostic");
  const lead = (dxA?.competing_hypotheses || []).find((h) => h.key === dxA?.recommended_hypothesis);
  const opened = (rm.events || []).find((e) => e.event_type === "INCIDENT_OPENED");
  return (
    <Ledger rows={[
      { label: "What happened", value: <>Model risk score above the action gate on <span className="wb-mono">{c.assetId}</span>: <span className="wb-num">{score(c.alert?.failure_prob)}</span> when the case opened{opened ? ` at ${clock(opened.created_at)}` : ""} (gate <span className="wb-num">{score(trigger)}</span>){c.alert?.predicted_mode_label ? <>; predicted failure mode: {c.alert.predicted_mode_label.toLowerCase()} (model output)</> : null}.</> },
      { label: "Current finding", value: dx?.status === "ACCEPTED"
        ? <span className="wb-rule-solid">Diagnosis accepted by application promotion: {dx.conclusion}</span>
        : lead ? <span className="wb-rule-dashed">Leading hypothesis (advisory): {lead.mechanism}. Supported by {(lead.supporting_evidence_ids || []).length}, contradicted by {(lead.contradicting_evidence_ids || []).length}.</span>
          : <span className="wb-secondary">Not yet established.</span> },
      rm.binding ? { label: "Recommended action", value: (rm.binding.work_instructions || []).join(" ") } : null,
    ]} />
  );
}

export function OpenRequests({ c }) {
  const requests = openRequests(c);
  if (!requests.length) return null;
  return requests.map((r) => (
    <div key={r.id} className="wb-request">
      <p className="wb-request-q"><Shape name="decision" size={14} decorative tone="decision" /> <span className="wb-role-word">Technician</span> · {r.question}</p>
      <p className="wb-secondary">Capability <span className="wb-mono">{r.capability}</span> · requested by {r.requestedBy} (run {shortId(r.runId)}){r.since ? ` · open since ${clock(r.since, { seconds: true })}` : ""}</p>
    </div>
  ));
}

export function EvidenceSection({ c, history, latestTick, warn, trigger, inspect }) {
  const rm = c.rm || {};
  const cited = new Set(rm.diagnosis?.evidence_ids || []);
  const rows = (rm.evidence || []).slice().sort((a, b) => String(b.observed_at || "").localeCompare(String(a.observed_at || "")));
  const shown = rows.slice(0, 10);
  return (
    <>
      <OpenRequests c={c} />
      <div className="wb-table-wrap">
        <table className="wb-table is-compact">
          <caption className="wb-table-caption">Newest first · {rows.length} items · provenance marks: hover a mark for its source</caption>
          <thead><tr>
            <th scope="col" className="wb-col-glyph"><span className="wb-sr">Provenance</span></th>
            <th scope="col">Kind · source</th><th scope="col">Summary</th><th scope="col">Observed</th><th scope="col">Quality</th>
          </tr></thead>
          <tbody>
            {shown.map((e) => {
              const prov = provenanceOf(e);
              return (
                <tr key={e.id}>
                  <td className="wb-col-glyph"><Provenance kind={prov} detail={`${e.source_capability || "source not recorded"}`} /></td>
                  <th scope="row" className="wb-cell-kind">
                    <span className="wb-kind">{sentence(e.kind)}{prov === "simulated" && cited.has(e.id) ? <> <SimulatedTag /></> : null}</span>
                    <span className="wb-cell-sub wb-mono-sm">{e.source_capability || "source not recorded"}</span>
                  </th>
                  <td>{inspect ? inspect.link({ kind: "artifact", id: e.id }, e.summary) : e.summary}<span className="wb-sr"> · {PROVENANCE_LABEL[prov]}</span></td>
                  <td className="wb-num is-nowrap" title={e.observed_at || undefined}>{e.observed_at ? when(e.observed_at, { seconds: true }) : <Muted>No observation</Muted>}</td>
                  <td className="is-nowrap">{e.quality === "GOOD" ? QUALITY.GOOD : <span className="wb-marker"><Shape name={e.quality === "MISSING" ? "unknown" : "elevated"} size={14} decorative tone={e.quality === "MISSING" ? "unknown" : "warning"} /> {QUALITY[e.quality] || sentence(e.quality)}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > 10 ? <p className="wb-caption">Showing 10 of {rows.length}.{inspect ? <> {inspect.link({ kind: "evidence" }, `View all ${rows.length} in the inspector`)}</> : null}</p> : null}
      <RiskChart points={history} latestTick={latestTick} warn={warn} trigger={trigger} title="Risk trajectory" assetId={c.assetId} />
    </>
  );
}

function HypothesisRow({ h, recorded, recommended, runId }) {
  const s = HYP[h.status] || HYP.OPEN;
  return (
    <li className={`wb-hyp ${h.status === "REFUTED" ? "is-refuted" : ""}`}>
      <span className="wb-hyp-status"><Shape name={s.shape} size={14} decorative /> {s.word}</span>
      <div className="wb-hyp-body">
        <p className="wb-hyp-mech">{h.mechanism}{h.failure_mode_code ? <> · <span className="wb-mono">{h.failure_mode_code}</span></> : null}{recommended ? <span className="wb-secondary"> · recommended by diagnostic review</span> : null}</p>
        <p className="wb-hyp-meta">
          supports {(h.supporting_evidence_ids || []).length} · contradicts {(h.contradicting_evidence_ids || []).length}
          {recorded ? (h.confidence_basis ? <> · basis: {h.confidence_basis}</> : null) : <> · proposed in run <span className="wb-mono">{shortId(runId)}</span>, not yet recorded as a hypothesis</>}
        </p>
        {(h.falsification_tests || []).length ? (
          <details className="wb-details"><summary>Falsification tests ({h.falsification_tests.length})</summary>
            <ul className="wb-bullets">{h.falsification_tests.map((t) => <li key={t}>{t}</li>)}</ul>
          </details>
        ) : null}
      </div>
    </li>
  );
}

export function InvestigationSection({ c }) {
  const rm = c.rm || {};
  const runs = rm.agent_runs || [];
  const run = latestRun(rm, "DIAGNOSIS");
  const dxA = assessment(run, "diagnostic");
  const recorded = (rm.hypotheses || []).length > 0;
  const hyps = recorded ? withoutConfidence(rm.hypotheses) : withoutConfidence(dxA?.competing_hypotheses || []);
  const reviewRuns = runs.slice(-2).reverse();
  const verdicts = rm.verdicts || [];
  const dx = rm.diagnosis;
  return (
    <>
      {run ? <p className="wb-runline">{runLine(run)}</p> : <EmptyLine>No analysis run recorded yet.</EmptyLine>}
      {(rm.agent_actions || []).length ? <p className="wb-secondary">{rm.agent_actions.map((a) => a.summary).join(" · ")}</p> : null}

      <h3 className="wb-subhead">Hypotheses</h3>
      {hyps.length ? (
        <ul className="wb-hyp-list wb-advisory">
          {hyps.map((h, i) => <HypothesisRow key={h.id || h.key || i} h={h} recorded={recorded} recommended={!recorded && dxA?.recommended_hypothesis === h.key} runId={run?.run_id} />)}
        </ul>
      ) : <EmptyLine>No hypotheses recorded yet.</EmptyLine>}

      {dx ? (
        <div className="wb-authoritative">
          <p><span className="wb-ledger-key">Diagnosis</span> {dx.status === "ACCEPTED" ? "Accepted by application promotion" : sentence(dx.status)}{dx.created_at ? ` ${clock(dx.created_at, { seconds: true })}` : ""} · {dx.conclusion} · cites {(dx.evidence_ids || []).length} evidence</p>
        </div>
      ) : null}

      <h3 className="wb-subhead">Reviews</h3>
      <ul className="wb-review-list wb-advisory">
        {reviewRuns.flatMap((r) => (r.delegations || []).map((d) => {
          const a = assessment(r, d.key);
          let finding = d.status === "SUCCEEDED" ? "completed" : sentence(d.status);
          if (d.key === "critic" && a) finding = `${sentence(a.recommendation || "no recommendation")} · ${(a.contradictions || []).length} contradictions · ${(a.evidence_gaps || []).length} evidence gaps`;
          if (d.key === "diagnostic" && a) finding = `recommends “${(a.competing_hypotheses || []).find((h) => h.key === a.recommended_hypothesis)?.mechanism || a.recommended_hypothesis || "no hypothesis"}”`;
          if (d.key === "plan" && a) finding = `${(a.proposed_steps || []).length} proposed step · ${a.reversible ? "reversible" : "not reversible"} · ${a.safety_relevant ? "safety-relevant" : "not safety-relevant"}`;
          if (d.key === "engineering" && a) finding = `${sentence(a.intervention_feasibility || "no verdict")} · ${(a.safety_concerns || []).length} safety concerns · ${(a.blockers || []).length} blockers`;
          if (d.key === "operations" && a) finding = `Resources ${String(a.resource_feasibility || "not assessed").toLowerCase()} · ${(a.blockers || []).length} blockers`;
          const reviewed = a?.reviewed_intervention_id;
          if (reviewed) finding += reviewed === rm.intervention?.id ? " · reviewed the current plan" : ` · reviewed draft ${shortId(reviewed)} (superseded by the current plan)`;
          return (
            <li key={`${r.run_id}-${d.key}`} className="wb-review">
              <span className="wb-actor wb-actor-role" aria-label={`${sentence(d.role)} review`}>{ROLE_ABBR[d.key] || ROLE_ABBR[d.role] || "REV"}</span>
              <span className="wb-review-role">{sentence(d.role)}</span>
              <span className="wb-review-finding">{finding}</span>
              <span className="wb-review-run">{RUN_STAGE[r.stage] || sentence(r.stage)} · run <span className="wb-mono">{shortId(r.run_id)}</span></span>
            </li>
          );
        }))}
        {!reviewRuns.length ? <li className="wb-secondary">No reviews recorded.</li> : null}
      </ul>
      {verdicts.length ? (
        <ul className="wb-review-list wb-authoritative-list">
          {verdicts.map((v) => {
            const checks = Object.values(v.check_results || {});
            return (
              <li key={v.id} className="wb-review">
                <span className="wb-actor wb-actor-system" aria-label="Application gate"><Shape name="system" size={14} decorative /></span>
                <span className="wb-review-role">Application gate · {v.target_kind}</span>
                <span className="wb-review-finding">{sentence(v.decision)} · {checks.filter(Boolean).length} of {checks.length} checks passed</span>
                <span className="wb-review-run">{v.validator_identity}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className="wb-caption">
        Directing the investigation (PRISM instruction revisions) stays in the agent workspace of the legacy portal for now:{" "}
        <Link to={`/legacy/agent?incident=${encodeURIComponent(c.incidentId)}`} data-legacy-exit="">open it in the legacy portal <Icon as={IconArrowUpRight} size={16} /></Link>. No chain-of-thought is shown; raw run outputs stay in the inspector.
      </p>
    </>
  );
}

export function PlanSection({ c, trigger, decisionPending, goNow }) {
  const rm = c.rm || {};
  const b = rm.binding;
  const iv = rm.intervention;
  const decisions = rm.approval_decisions || [];
  return (
    <>
      {decisionPending ? (
        <p className="wb-rule-ink wb-pointer">The decision for this work package is in <a href="#now" onClick={goNow}>Now</a>.</p>
      ) : null}
      {iv ? (
        <Ledger rows={[
          { label: "Finding", value: rm.diagnosis ? <>{rm.diagnosis.conclusion} <span className="wb-secondary">(diagnosis accepted {clock(rm.diagnosis.created_at)} · {(rm.diagnosis.evidence_ids || []).length} evidence)</span></> : "No accepted diagnosis." },
          { label: "Consequence", value: <>Model risk score <span className="wb-num">{score(c.failureProb)}</span>{Number.isFinite(trigger) && c.failureProb >= trigger ? " above the action gate" : ""} (model output). Plan risk: {sentence(iv.risk || "not recorded")}{b?.safety_relevant ? " · safety-relevant" : ""}{b?.reversible === false ? " · not reversible" : ""}.</> },
          b ? { label: "Recommended", value: <>{(b.work_instructions || []).join(" ")} <span className="wb-secondary">· parts <span className="wb-mono">{(b.parts || []).map((p) => `${p.part_id} × ${p.quantity}`).join(", ")}</span> · technician <span className="wb-mono">{b.technician_id}</span> · window {dayClock(b.window_start)}–{clock(b.window_end)} · {b.duration_minutes} min</span></> } : null,
          { label: "Steps", value: <ol className="wb-steps">{(iv.steps || []).map((s, i) => <li key={s.id}><span className="wb-mono">{i + 1} {s.capability}</span> · preconditions: {(s.preconditions || []).join("; ") || "none"} · verification: {(s.verification_criteria || []).join("; ") || "none"}</li>)}</ol> },
          { label: "Revision", value: <>Plan revision {iv.revision}{iv.supersedes_id ? <> · supersedes <span className="wb-mono">{shortId(iv.supersedes_id)}</span></> : null} · status {sentence(iv.status)}</> },
        ]} />
      ) : <EmptyLine>{decisions.length ? "No current work package: the last one was withdrawn. A revised plan is drafted and reviewed next." : "Not started · begins after diagnosis."}</EmptyLine>}
      {decisions.length ? (
        <>
          <h3 className="wb-subhead">Decisions recorded</h3>
          <ul className="wb-decisions-recorded">
            {decisions.map((d) => (
              <li key={d.id} className="wb-authoritative">
                <Shape name={d.decision === "APPROVE" ? "approved" : "critical"} size={14} decorative />
                {d.decision === "APPROVE" ? "Approved" : "Rejected"} by <span className="wb-mono">{d.actor_id}</span> ({String(d.actor_role || "").replace(/_/g, " ")}, declared, not verified) at {clock(d.created_at, { seconds: true })} · rationale: “{d.rationale}”
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

export function WorkSection({ c }) {
  const rm = c.rm || {};
  const receipts = rm.execution_receipts || [];
  const plans = rm.observation_plans || [];
  const outcomes = rm.outcomes || [];
  const facts = workFacts(c.alert?.lifecycle);
  if (!receipts.length && !plans.length && !outcomes.length && !facts.length) return <EmptyLine>Not started · begins after approval and dispatch.</EmptyLine>;
  const plan = plans[plans.length - 1];
  const outcome = outcomes[outcomes.length - 1];
  return (
    <>
      <Ledger rows={[
        ...receipts.map((r) => ({ key: r.id, label: "Dispatch", value: r.status === "CONFIRMED"
          ? <><Shape name="committed" size={14} decorative /> Work order <span className="wb-mono">{r.external_ids?.wo_number || "number not recorded"}</span> committed {clock(r.completed_at, { seconds: true })} · local work-order adapter · package <span className="wb-mono">{r.external_ids?.package_number || "not recorded"}</span></>
          : <><Shape name="critical" size={14} decorative /> Dispatch {String(r.status || "").toLowerCase()}{r.completed_at ? ` ${clock(r.completed_at, { seconds: true })}` : ""}{r.error_message ? <> · {r.error_message}</> : null}</> })),
        ...facts.map((f) => ({ key: f.id, label: "Work", value: <>{f.text}{f.workOrder ? <> · work order <span className="wb-mono">{f.workOrder}</span></> : null}</> })),
        { label: "Field status", value: fieldStatus(c.alert?.lifecycle) },
        plan ? { label: "Verification", value: outcome
          ? <><Shape name={OUTCOME[outcome.result]?.shape || "unknown"} size={14} decorative /> {OUTCOME[outcome.result]?.label || "Outcome not recognised"}{outcome.basis === "SIMULATED" ? " (simulated)" : ""}</>
          : <><Shape name="watch" size={14} decorative /> {observingSince(clock(plan.observation_start, { seconds: true }))} · policy <span className="wb-mono">{plan.policy_version}</span></> } : null,
      ]} />
      <p className="wb-caption">{DISPATCH_IS_NOT_WORK} {VERIFICATION_BASIS}</p>
    </>
  );
}

export function RecordSection({ c, inspect }) {
  const all = c.rm?.events || [];
  const curated = curatedRecord(all).slice(-12).reverse();
  return (
    <>
      <p className="wb-caption">Times in {zoneAbbr() || "browser time"} (plant time zone not projected, X3) · {all.length} events loaded{all.length >= 80 ? " · earlier events aren’t loaded in this build (X5)" : ""} · the latest {curated.length} transitions and human acts{inspect ? <> · {inspect.link({ kind: "record" }, "open the full record")}</> : null}</p>
      <ol className="wb-record">
        {curated.map((e) => (
          <li key={e.id} className={`wb-record-row ${e.authoritative ? "is-auth" : "is-adv"}`}>
            <span className="wb-record-time wb-num">{clock(e.at, { seconds: true })}</span>
            <span className="wb-record-node" aria-hidden="true" />
            <span className="wb-record-text">{e.text}{e.reason ? <span className="wb-secondary"> · {e.reason}</span> : null}</span>
            <span className="wb-record-rev wb-mono-sm">R{e.revision}</span>
          </li>
        ))}
      </ol>
    </>
  );
}
