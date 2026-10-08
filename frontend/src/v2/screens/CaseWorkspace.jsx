// Case workspace (08 screens 5–8 template): sticky header (title, title block ≤ 6 cells, stage
// track), section index, one scrolling document (not tabs), context rail at ≥ 1280. Sections in a
// fixed order: Summary → Evidence → Investigation → Plan & decision → Work & verification → Record.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { IconArrowUpRight } from "@tabler/icons-react";
import { useWb } from "../shell/WbContext.jsx";
import { usePageTitle, useRoleScope } from "../shell/WbShell.jsx";
import { useSession } from "../../state/session.jsx";
import { ConditionMarker, CopyId, EmptyLine, FreshnessIndicator, Icon, InlineAlert, Ledger, Muted, Provenance, SectionHeading, SeverityMarker, SimulatedTag, TitleBlock, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { StageTrack } from "../components/StageTrack.jsx";
import { RiskChart } from "../components/RiskChart.jsx";
import { useMedia } from "../components/Overlay.jsx";
import { assessment, latestRun, openRequests } from "../model/cases.js";
import { OUTCOME, PROVENANCE_LABEL, provenanceOf, stageCompact, withoutConfidence } from "../model/status.js";
import { clock, dayClock, duration, score, sentence, shortId, when, zoneAbbr } from "../model/format.js";
import { curatedRecord, eventCopy, nextStepSentence } from "./caseCopy.js";
import { DecisionSurface } from "./DecisionSurface.jsx";
import { WB_ROUTES } from "../shell/routes.js";

const SECTIONS = [
  { id: "summary", n: "01", title: "Summary & next step" },
  { id: "evidence", n: "02", title: "Evidence" },
  { id: "investigation", n: "03", title: "Investigation" },
  { id: "decision", n: "04", title: "Plan & decision" },
  { id: "work", n: "05", title: "Work & verification" },
  { id: "record", n: "06", title: "Record" },
];

const QUALITY = { GOOD: "Good", SUSPECT: "Suspect", MISSING: "Missing" };
const HYP = { SUPPORTED: { word: "Supported", shape: "supported" }, REFUTED: { word: "Refuted", shape: "refuted" }, UNRESOLVED: { word: "Unresolved", shape: "unresolved" }, OPEN: { word: "Open", shape: "open" } };
const ROLE_ABBR = { diagnostic: "DX", critic: "CRT", plan: "PLN", planner: "PLN", engineering: "ENG", operations: "OPS" };
const RUN_STAGE = { DIAGNOSIS: "Diagnosis review", INTERVENTION_REVIEW: "Work package review" };
const RUN_STATUS = { MODEL_COMPLETED: "completed", LIMIT_REACHED: "stopped: limit reached", TIMED_OUT: "stopped: timed out", MODEL_FAILED: "stopped: model failed", INVALID_OUTPUT: "stopped: invalid output" };

function runtimeWords(run) {
  const r = run?.reasoning || run?.runtime_identity || {};
  if (r.live_model) return `${r.provider || "provider"} · ${r.model || "model"}`;
  if (r.backend === "deterministic") return "deterministic advisory (no live model)";
  return r.runtime || "runtime not reported";
}

function useSectionInView(ids) {
  const [inView, setInView] = useState(ids[0]);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return undefined;
    const els = ids.map((id) => document.getElementById(`sec-${id}`)).filter(Boolean);
    const io = new IntersectionObserver((entries) => {
      const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setInView(visible[0].target.id.replace("sec-", ""));
    }, { rootMargin: "-120px 0px -55% 0px" });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [ids]);
  return inView;
}

function useVisible(id, key) {
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const el = document.getElementById(id);
    if (!el || typeof IntersectionObserver === "undefined") return undefined;
    const io = new IntersectionObserver(([e]) => setVis(e.isIntersecting), { threshold: 0.05 });
    io.observe(el);
    return () => io.disconnect();
  }, [id, key]);
  return vis;
}

function NextStep({ c, now }) {
  const r = c.requirement;
  const verb = c.response?.verb || "Nothing required from you";
  let action = null;
  if (c.phase === "AWAITING_APPROVAL" && c.expiry?.state !== "expired") {
    // Always secondary: the header CTA is the single primary while the decision surface is off screen (R-5).
    action = <a className="wb-btn wb-btn-secondary wb-btn-md" href="#decision-surface"><span>Go to decision</span></a>;
  }
  return (
    <div className="wb-nextstep" aria-label="Next step">
      <p className="wb-nextstep-verb">{verb}{c.response ? <> · <span className="wb-mono">{c.assetId}</span></> : null}</p>
      <p className="wb-nextstep-text">{nextStepSentence(c)}</p>
      <Ledger className="is-compact" rows={[
        { label: "Owner", value: <WaitingOn role={c.waiting} /> },
        r?.expires_at ? { label: "By", value: <>{when(r.expires_at)} {zoneAbbr(new Date(r.expires_at))} · in {duration(Date.parse(r.expires_at) - now)}</> } : null,
      ]} />
      {c.phase === "AWAITING_EVIDENCE" ? (
        <p className="wb-caption">Inspection submission from this interface isn’t available yet (G1, X7). The case stays here until an inspection is recorded.</p>
      ) : null}
      {action}
    </div>
  );
}

function Identifiers({ c }) {
  const run = latestRun(c.rm);
  return (
    <Ledger className="is-compact wb-identifiers" rows={[
      { label: "Case reference", value: <span className="wb-mono-sm">{c.ref}</span> },
      { label: "Incident UUID", value: <CopyId value={c.incidentId} label="incident UUID" /> },
      { label: "Analysis run", value: run ? <CopyId value={run.run_id} label="analysis run" /> : <Muted>No run recorded</Muted> },
      { label: "Revision", value: <span className="wb-mono-sm">R{c.revision ?? "?"}</span> },
      { label: "Intervention hash", value: c.alert?.lifecycle?.intervention_hash ? <CopyId value={c.alert.lifecycle.intervention_hash} label="intervention hash" /> : <Muted>No work package yet</Muted> },
    ]} />
  );
}

function RailContent({ c, now, history, latestTick, warn, trigger }) {
  const requests = openRequests(c);
  return (
    <>
      <NextStep c={c} now={now} />
      <div className="wb-rail-block">
        <h3 className="wb-rail-head">Asset condition</h3>
        <p><ConditionMarker condition={c.condition} /> <span className="wb-num">{score(c.failureProb)}</span> <span className="wb-secondary">model risk score</span></p>
        <RiskChart points={history} latestTick={latestTick} warn={warn} trigger={trigger} compact title="Risk · this run" assetId={c.assetId} />
      </div>
      <div className="wb-rail-block">
        <h3 className="wb-rail-head">Open requests</h3>
        {requests.length ? requests.map((r) => (
          <p key={r.id} className="wb-rule-ink">{r.question} <span className="wb-secondary">· {r.requestedBy}{r.since ? ` · since ${clock(r.since)}` : ""}</span></p>
        )) : <EmptyLine>No open evidence requests.</EmptyLine>}
      </div>
      <div className="wb-rail-block">
        <h3 className="wb-rail-head">Identifiers</h3>
        <Identifiers c={c} />
      </div>
    </>
  );
}

function Summary({ c, now, narrow, railProps, trigger }) {
  const rm = c.rm || {};
  const dx = rm.diagnosis;
  const run = latestRun(rm, "DIAGNOSIS");
  const lead = (assessment(run, "diagnostic")?.competing_hypotheses || []).find((h) => h.key === assessment(run, "diagnostic")?.recommended_hypothesis);
  const opened = (rm.events || []).find((e) => e.event_type === "INCIDENT_OPENED");
  const milestones = (rm.events || []).filter((e) => e.event_type === "PHASE_CHANGED" || e.event_type === "INCIDENT_OPENED").map(eventCopy);
  return (
    <>
      {narrow ? <div className="wb-summary-rail"><RailContent {...railProps} /></div> : null}
      <Ledger rows={[
        { label: "What happened", value: <>Model risk score above the action gate on <span className="wb-mono">{c.assetId}</span>: <span className="wb-num">{score(c.alert?.failure_prob)}</span> when the case opened{opened ? ` at ${clock(opened.created_at)}` : ""} (gate <span className="wb-num">{score(trigger)}</span>){c.alert?.predicted_mode_label ? <>; predicted failure mode: {c.alert.predicted_mode_label.toLowerCase()} (model output)</> : null}.</> },
        { label: "Current finding", value: dx?.status === "ACCEPTED"
          ? <span className="wb-rule-solid">Diagnosis accepted by application promotion: {dx.conclusion}</span>
          : lead ? <span className="wb-rule-dashed">Leading hypothesis (advisory): {lead.mechanism}. Supported by {(lead.supporting_evidence_ids || []).length}, contradicted by {(lead.contradicting_evidence_ids || []).length}.</span>
            : <span className="wb-secondary">Not yet established.</span> },
        rm.binding ? { label: "Recommended action", value: (rm.binding.work_instructions || []).join(" ") } : null,
        { label: "Done so far", value: <ol className="wb-milestones">{milestones.map((m) => <li key={m.id}><span className="wb-num wb-tertiary">{clock(m.at)}</span> {m.text}</li>)}</ol> },
      ]} />
    </>
  );
}

function Evidence({ c }) {
  const rm = c.rm || {};
  const cited = new Set(rm.diagnosis?.evidence_ids || []);
  const rows = (rm.evidence || []).slice().sort((a, b) => String(b.observed_at || "").localeCompare(String(a.observed_at || "")));
  const requests = openRequests(c);
  const shown = rows.slice(0, 10);
  return (
    <>
      {requests.map((r) => (
        <div key={r.id} className="wb-request">
          <p className="wb-request-q"><Shape name="decision" size={14} decorative tone="decision" /> <span className="wb-role-word">Technician</span> · {r.question}</p>
          <p className="wb-secondary">Capability <span className="wb-mono">{r.capability}</span> · requested by {r.requestedBy} (run {shortId(r.runId)}){r.since ? ` · open since ${clock(r.since, { seconds: true })}` : ""}</p>
        </div>
      ))}
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
                  <td>{e.summary}<span className="wb-sr"> · {PROVENANCE_LABEL[prov]}</span></td>
                  <td className="wb-num is-nowrap" title={e.observed_at || undefined}>{e.observed_at ? when(e.observed_at, { seconds: true }) : <Muted>No observation</Muted>}</td>
                  <td className="is-nowrap">{e.quality === "GOOD" ? QUALITY.GOOD : <span className="wb-marker"><Shape name={e.quality === "MISSING" ? "unknown" : "elevated"} size={14} decorative tone={e.quality === "MISSING" ? "unknown" : "warning"} /> {QUALITY[e.quality] || sentence(e.quality)}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > 10 ? <p className="wb-caption">Showing 10 of {rows.length}. The full filterable list opens in the inspector in a later slice.</p> : null}
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

function Investigation({ c }) {
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
      {run ? (
        <p className="wb-runline">{RUN_STAGE[run.stage] || sentence(run.stage)} · run <span className="wb-mono">{shortId(run.run_id)}</span> · input <span className="wb-mono">R{run.input_revision}</span> · {RUN_STATUS[run.status] || sentence(run.status)} · {runtimeWords(run)}</p>
      ) : <EmptyLine>No analysis run recorded yet.</EmptyLine>}
      {(rm.agent_actions || []).length ? (
        <p className="wb-secondary">{rm.agent_actions.map((a) => a.summary).join(" · ")}</p>
      ) : null}

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

function PlanAndDecision({ c, now, session, roleLabel, connected, trigger, onDecide }) {
  const rm = c.rm || {};
  const b = rm.binding;
  const iv = rm.intervention;
  const decisions = rm.approval_decisions || [];
  if (!iv) return <EmptyLine>Not started · begins after diagnosis.</EmptyLine>;
  return (
    <>
      <Ledger rows={[
        { label: "Finding", value: rm.diagnosis ? <>{rm.diagnosis.conclusion} <span className="wb-secondary">(diagnosis accepted {clock(rm.diagnosis.created_at)} · {(rm.diagnosis.evidence_ids || []).length} evidence)</span></> : "No accepted diagnosis." },
        { label: "Consequence", value: <>Model risk score <span className="wb-num">{score(c.failureProb)}</span>{Number.isFinite(trigger) && c.failureProb >= trigger ? " above the action gate" : ""} (model output). Plan risk: {sentence(iv.risk || "not recorded")}{b?.safety_relevant ? " · safety-relevant" : ""}{b?.reversible === false ? " · not reversible" : ""}.</> },
        b ? { label: "Recommended", value: <>{(b.work_instructions || []).join(" ")} <span className="wb-secondary">· parts <span className="wb-mono">{(b.parts || []).map((p) => `${p.part_id} × ${p.quantity}`).join(", ")}</span> · technician <span className="wb-mono">{b.technician_id}</span> · window {dayClock(b.window_start)}–{clock(b.window_end)} · {b.duration_minutes} min</span></> } : null,
        { label: "Steps", value: <ol className="wb-steps">{(iv.steps || []).map((s, i) => <li key={s.id}><span className="wb-mono">{i + 1} {s.capability}</span> · preconditions: {(s.preconditions || []).join("; ") || "none"} · verification: {(s.verification_criteria || []).join("; ") || "none"}</li>)}</ol> },
        { label: "Revision", value: <>Plan revision {iv.revision}{iv.supersedes_id ? <> · supersedes <span className="wb-mono">{shortId(iv.supersedes_id)}</span></> : null} · status {sentence(iv.status)}</> },
      ]} />
      {decisions.length ? (
        <ul className="wb-decisions-recorded">
          {decisions.map((d) => (
            <li key={d.id} className="wb-authoritative">
              <Shape name={d.decision === "APPROVE" ? "approved" : "critical"} size={14} decorative />
              {d.decision === "APPROVE" ? "Approved" : "Rejected"} by <span className="wb-mono">{d.actor_id}</span> ({String(d.actor_role || "").replace(/_/g, " ")}, declared) at {clock(d.created_at, { seconds: true })} · rationale: “{d.rationale}”
            </li>
          ))}
        </ul>
      ) : null}
      {c.phase === "AWAITING_APPROVAL" ? (
        <DecisionSurface c={c} session={session} roleLabel={roleLabel} connected={connected} now={now} trigger={trigger} onDecide={onDecide} />
      ) : null}
    </>
  );
}

function WorkAndVerification({ c }) {
  const rm = c.rm || {};
  const receipts = rm.execution_receipts || [];
  const plans = rm.observation_plans || [];
  const outcomes = rm.outcomes || [];
  if (!receipts.length && !plans.length && !outcomes.length) return <EmptyLine>Not started · begins after approval and dispatch.</EmptyLine>;
  const plan = plans[plans.length - 1];
  const outcome = outcomes[outcomes.length - 1];
  return (
    <Ledger rows={[
      ...receipts.map((r) => ({ key: r.id, label: "Work order", value: <><Shape name="committed" size={14} decorative /> <span className="wb-mono">{r.external_ids?.wo_number || "Work order"}</span> {sentence(r.status)} {clock(r.completed_at, { seconds: true })} · adapter local CMMS · package <span className="wb-mono">{r.external_ids?.package_number || "not recorded"}</span></> })),
      { label: "Field status", value: "Not reported to this system (G10)" },
      plan ? { label: "Verification", value: outcome ? <><Shape name={OUTCOME[outcome.result]?.shape || "unknown"} size={14} decorative /> {OUTCOME[outcome.result]?.label}{outcome.basis === "SIMULATED" ? " (simulated)" : ""}</> : <><Shape name="watch" size={14} decorative /> Observing since {clock(plan.observation_start, { seconds: true })} · policy <span className="wb-mono">{plan.policy_version}</span></> } : null,
    ]} />
  );
}

function Record({ c }) {
  const all = c.rm?.events || [];
  const curated = curatedRecord(all).slice(-10).reverse();
  return (
    <>
      <p className="wb-caption">Times in {zoneAbbr() || "browser time"} (plant time zone not projected, X3) · {all.length} events loaded{all.length >= 80 ? " · earlier events aren’t loaded in this build (X5)" : ""} · showing the latest {curated.length} authoritative transitions</p>
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

export function CaseWorkspace() {
  const { incidentId } = useParams();
  const location = useLocation();
  const { state, cases, now, fresh } = useWb();
  const { session } = useSession();
  const role = useRoleScope();
  const c = cases.find((x) => x.incidentId === incidentId);
  usePageTitle(c ? `${c.assetId} · case` : "Case");
  const wide = useMedia("(min-width: 1280px)", true);
  const sectionIds = useMemo(() => SECTIONS.map((s) => s.id), []);
  const inView = useSectionInView(sectionIds);
  const decisionVisible = useVisible("decision-surface", c?.phase);
  const headRef = useRef(null);
  const [condensed, setCondensed] = useState(false);
  const [missing, setMissing] = useState(null);

  useEffect(() => {
    if (!headRef.current || typeof IntersectionObserver === "undefined") return undefined;
    const io = new IntersectionObserver(([e]) => setCondensed(!e.isIntersecting), { threshold: 0 });
    io.observe(headRef.current);
    return () => io.disconnect();
  }, [c?.incidentId]);

  useEffect(() => {
    if (location.hash) {
      const id = location.hash.slice(1);
      setTimeout(() => document.getElementById(id === "decision" && document.getElementById("decision-surface") ? "decision-surface" : `sec-${id}`)?.scrollIntoView({ block: "start" }), 50);
    }
  }, [location.hash, c?.incidentId]);

  // Not projected over the stream (e.g. after a reset): ask the case endpoint for the verbatim error.
  useEffect(() => {
    if (c || !state.frames) return;
    let cancelled = false;
    fetch(`/api/incidents/${encodeURIComponent(incidentId)}`).then(async (r) => {
      const body = await r.json().catch(() => ({}));
      if (!cancelled) setMissing(r.ok ? "This case exists but isn’t projected over the live stream (latest case per asset, G5)." : `HTTP ${r.status}: ${body.error || "unknown error"}`);
    }).catch((err) => { if (!cancelled) setMissing(err.message); });
    return () => { cancelled = true; };
  }, [c, incidentId, state.frames]);

  if (!c) {
    return (
      <div className="wb-page">
        <h1 className="wb-page-title">{state.frames ? "Couldn’t load the case record" : "Loading case record…"}</h1>
        {missing ? <p className="wb-secondary">{missing}</p> : null}
        <p><Link to={WB_ROUTES.actions}>Back to My actions</Link></p>
      </div>
    );
  }

  const history = state.histories?.[c.assetId] || [];
  const warn = state.warnThreshold, trigger = state.triggerThreshold;
  const connected = fresh.state !== "disconnected";
  const onDecide = async (body) => {
    try {
      const res = await fetch(`/api/incidents/${encodeURIComponent(c.incidentId)}/approval`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const json = await res.json().catch(() => ({}));
      return res.ok && json.ok !== false ? { ok: true, ...json } : { ok: false, error: json.error || json.detail?.[0]?.msg || `HTTP ${res.status}` };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  };

  const railProps = { c, now, history, latestTick: state.tick, warn, trigger, decisionVisible };
  const deadlineCell = c.requirement?.expires_at && c.phase === "AWAITING_APPROVAL" ? {
    label: "Deadline",
    value: c.expiry?.state === "expired" ? <>Expired {when(c.requirement.expires_at)}</>
      : <span className={c.expiry?.state === "approaching" || c.expiry?.state === "final" ? "wb-deadline-near" : ""}>{when(c.requirement.expires_at)} {zoneAbbr(new Date(c.requirement.expires_at))} · in {duration(Date.parse(c.requirement.expires_at) - now)}</span>,
  } : null;
  const cells = [
    { label: "Asset condition", value: <><ConditionMarker condition={c.condition} size={16} /> <span className="wb-num">{score(c.failureProb)}</span></> },
    c.severity ? { label: "Severity", value: <SeverityMarker value={c.severity} /> } : { label: "Asset criticality", value: <SeverityMarker value={c.criticality} basis="Asset criticality" /> },
    { label: "Stage", value: stageCompact(c.phase) },
    { label: "Waiting on", value: <WaitingOn role={c.waiting} size={16} /> },
    deadlineCell,
    { label: "Revision", value: <span className="wb-mono">R{c.revision}</span> },
  ];
  const cta = c.phase === "AWAITING_APPROVAL" && c.expiry?.state !== "expired"
    ? <a className={`wb-btn wb-btn-${decisionVisible ? "secondary" : "primary"} wb-btn-md`} href="#decision-surface"><span>Go to decision</span></a>
    : null;
  const indexMeta = {
    evidence: `${(c.rm?.evidence || []).length}${openRequests(c).length ? ` · ${openRequests(c).length} open request` : ""}`,
    investigation: (c.rm?.agent_runs || []).length ? `${(c.rm.agent_runs || []).length} runs` : "not started",
    decision: c.phase === "AWAITING_APPROVAL" ? "decision required" : c.rm?.intervention ? "plan ready" : "not started",
    work: (c.rm?.execution_receipts || []).length ? "in work" : "not started",
    record: `${(c.rm?.events || []).length} events`,
  };

  return (
    <div className="wb-case">
      {condensed ? (
        <div className="wb-case-condensed" aria-hidden="true">
          <span className="wb-mono">{c.assetId}</span>
          <span>{stageCompact(c.phase)}</span>
          <WaitingOn role={c.waiting} />
          {c.requirement?.expires_at && c.phase === "AWAITING_APPROVAL" ? <span>by {when(c.requirement.expires_at)}</span> : null}
          <span className="wb-header-fill" />
          {cta}
        </div>
      ) : null}
      <header className="wb-case-head" ref={headRef}>
        <nav className="wb-crumbs" aria-label="Breadcrumb">
          <Link to={WB_ROUTES.cases}>Cases</Link><span aria-hidden="true"> / </span><span className="wb-mono" aria-current="page">{c.ref}</span>
        </nav>
        <div className="wb-case-titlerow">
          <h1 className="wb-page-title">Model risk above action gate · {c.assetName}</h1>
          <span className="wb-header-fill" />
          <FreshnessIndicator fresh={fresh} />
          {cta}
        </div>
        <TitleBlock label="Case summary" cells={cells} />
        <StageTrack phase={c.phase} />
      </header>
      {c.phase === "ESCALATED" || c.phase === "EXECUTION_FAILED" ? (
        <InlineAlert tone="critical" title={c.phase === "ESCALATED" ? "Escalated: engineering decision required." : "Work order not confirmed."}>{c.lastReason}</InlineAlert>
      ) : null}
      <div className={`wb-case-body ${wide ? "has-rail" : ""}`}>
        <nav className="wb-index" aria-label="Case sections">
          <ol>
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className={`wb-index-item ${inView === s.id ? "is-current" : ""}`} aria-current={inView === s.id ? "location" : undefined}
                  onClick={(e) => { e.preventDefault(); document.getElementById(`sec-${s.id}`)?.scrollIntoView({ block: "start" }); window.history.replaceState(window.history.state, "", `#${s.id}`); }}>
                  <span className="wb-index-n">{s.n}</span>
                  <span className="wb-index-title">{s.title}</span>
                  {indexMeta[s.id] ? <span className="wb-index-meta">{indexMeta[s.id]}</span> : null}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="wb-doc">
          <section id="sec-summary" className="wb-doc-section" aria-labelledby="h-summary">
            <SectionHeading index="01" id="h-summary" title="Summary & next step" sticky meta={c.demo ? <>Guided Demo case · <SimulatedTag /></> : null} />
            <Summary c={c} now={now} narrow={!wide} railProps={railProps} trigger={trigger} />
          </section>
          <section id="sec-evidence" className="wb-doc-section" aria-labelledby="h-evidence">
            <SectionHeading index="02" id="h-evidence" title="Evidence" sticky meta={`${(c.rm?.evidence || []).length} items`} />
            <Evidence c={c} />
            <RiskChart points={history} latestTick={state.tick} warn={warn} trigger={trigger} title="Risk trajectory" assetId={c.assetId} />
          </section>
          <section id="sec-investigation" className="wb-doc-section" aria-labelledby="h-investigation">
            <SectionHeading index="03" id="h-investigation" title="Investigation" sticky meta={(() => { const r = latestRun(c.rm); return r ? <>Revision {r.input_revision} · {runtimeWords(r)}</> : null; })()} />
            <Investigation c={c} />
          </section>
          <section id="sec-decision" className="wb-doc-section" aria-labelledby="h-decision">
            <SectionHeading index="04" id="h-decision" title="Plan & decision" sticky meta={c.rm?.intervention ? `Plan revision ${c.rm.intervention.revision}` : null} />
            <PlanAndDecision c={c} now={now} session={session} roleLabel={role.label} connected={connected} trigger={trigger} onDecide={onDecide} />
          </section>
          <section id="sec-work" className="wb-doc-section" aria-labelledby="h-work">
            <SectionHeading index="05" id="h-work" title="Work & verification" sticky />
            <WorkAndVerification c={c} />
          </section>
          <section id="sec-record" className="wb-doc-section" aria-labelledby="h-record">
            <SectionHeading index="06" id="h-record" title="Record" sticky />
            <Record c={c} />
          </section>
        </div>
        {wide ? (
          <aside className="wb-context" aria-label="Case context">
            <RailContent {...railProps} />
          </aside>
        ) : null}
      </div>
    </div>
  );
}
