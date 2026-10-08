// "Now" (F0 §14 layout D): the current-stage workspace. It states what is true now, who the case
// waits on and since when, and what a person can do. When a decision is pending the decision surface
// lives here, not 3,000 px down a document. Every sentence comes from the alert or the journal.
import { SimulatedTag, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { latestRun, openRequests } from "../model/cases.js";
import { OUTCOME, stageOf } from "../model/status.js";
import { ACTOR_KIND_WORDS, cancellationOf, exceptionCauseOf, lastPhaseChange, rejectionOf } from "../model/lifecycle.js";
import { clock, when, zoneAbbr } from "../model/format.js";
import { VERIFICATION_BASIS, fieldStatus, observingSince, workFacts } from "../model/workBoundary.js";
import { actorWords, nextStepSentence } from "./caseCopy.js";
import { CaseSummary, OpenRequests, runLine } from "./CaseSections.jsx";
import { DecisionSurface } from "./DecisionSurface.jsx";

/** One framed-by-rule block (07 §9.3: rules, not frames; the decision surface is the only frame). */
function NowBlock({ tone = "info", title, id, children }) {
  return (
    <section className={`wb-now-block is-${tone}`} aria-labelledby={id}>
      <h3 className="wb-now-title" id={id}>
        {tone === "exception" ? <Shape name="critical" size={14} decorative tone="critical" /> : null}
        {title}
      </h3>
      <div className="wb-now-body">{children}</div>
    </section>
  );
}

function rejectionLine(rejection) {
  if (!rejection) return null;
  return <>Rejected by <span className="wb-mono">{rejection.actorId || "an unrecorded actor"}</span> ({ACTOR_KIND_WORDS[rejection.actorKind] || "declared, not verified"}) at {clock(rejection.at, { seconds: true })}{rejection.rationale ? <> · “{rejection.rationale}”</> : null}</>;
}

function Situation({ c, now, trigger, decide }) {
  const lc = c.alert?.lifecycle || {};
  const rm = c.rm || {};
  const phase = c.phase;

  if (c.approval?.state === "pending") return <DecisionSurface c={c} {...decide} now={now} trigger={trigger} />;

  if (c.approval?.state === "expired") {
    const req = c.approval.requirement;
    return (
      <NowBlock tone="action" id="now-expired" title="Approval request expired">
        <p>The approval requirement {req?.expires_at ? <>expired at {when(req.expires_at)} {zoneAbbr(new Date(req.expires_at))}</> : "expired"}. Nothing was dispatched. The work package is unchanged: renew the approval for the same package, or return the case to planning.</p>
      </NowBlock>
    );
  }
  if (c.approval?.state === "invalidated") {
    return (
      <NowBlock tone="action" id="now-invalid" title="The promoted plan was invalidated">
        <p>Newer evidence invalidated the authority of the plan awaiting approval, so it can no longer be approved. Reinvestigate, or return the case to planning.</p>
        {c.approval.reason ? <p className="wb-secondary">Reason recorded: {c.approval.reason}</p> : null}
      </NowBlock>
    );
  }
  if (c.suspension) {
    const s = c.suspension;
    const codes = Object.entries(s.codes || {}).map(([code, n]) => `${code} × ${n}`).join(", ");
    return (
      <NowBlock tone="action" id="now-suspended" title="Analysis suspended">
        <p>Automated analysis stopped after {s.attempts ?? "repeated"} technical failures{codes ? ` (${codes})` : ""}{s.lastReason ? `. Last: ${s.lastReason}` : ""}. It doesn’t resume or escalate by itself: a person resumes it, escalates or cancels the case.</p>
      </NowBlock>
    );
  }

  switch (phase) {
    case "AWAITING_EVIDENCE": {
      const requests = openRequests(c);
      const cause = exceptionCauseOf(rm, phase);
      return (
        <NowBlock tone="action" id="now-evidence" title={requests.length ? "Technician inspection required" : "Waiting for evidence"}>
          <OpenRequests c={c} />
          {cause?.reason ? <p><span className="wb-ledger-key">Why the case waits</span> {cause.reason}</p> : null}
          <p className="wb-caption">Inspection submission from this interface isn’t available yet (G1, X7). The case stays here until evidence is recorded.</p>
        </NowBlock>
      );
    }
    case "DIAGNOSIS_VALIDATED":
      return (
        <NowBlock tone="action" id="now-resources" title="Resources need confirmation">
          <p>The diagnosis was accepted. Maintenance planning confirms the technician, parts and window, then the exact work package is drafted and reviewed.</p>
          <p className="wb-caption">Resource confirmation from this interface isn’t available yet (G1).</p>
        </NowBlock>
      );
    case "ESCALATED": {
      const cause = exceptionCauseOf(rm, phase);
      const from = cause?.from ? stageOf(cause.from) : null;
      return (
        <NowBlock tone="exception" id="now-escalated" title={`Escalated${from && !from.exception ? ` from ${from.label}` : ""}`}>
          {cause?.reason ? <p>{cause.reason}.</p> : null}
          {rejectionOf(rm) && cause?.from === "AWAITING_APPROVAL" ? <p className="wb-secondary">{rejectionLine(rejectionOf(rm))}</p> : null}
          <p>Evidence, the diagnosis and the plan state are kept. {(rm.execution_receipts || []).length ? "The dispatch receipts below stay on record." : "Nothing was dispatched."} This asset can’t open a new case until this one is resumed or cancelled.</p>
        </NowBlock>
      );
    }
    case "EXECUTION_FAILED": {
      const cause = exceptionCauseOf(rm, phase);
      return (
        <NowBlock tone="exception" id="now-failed" title="Dispatch failed">
          <p>The work order wasn’t confirmed{cause?.status ? ` (receipt ${String(cause.status).toLowerCase()})` : ""}{cause?.reason ? `: ${cause.reason}` : ""}.</p>
          {lc.reconciliation_required
            ? <p>The dispatch outcome is unknown, so it can’t be retried or abandoned yet. Reconciliation isn’t available from this interface; it runs when the engine restarts.</p>
            : <p>The failure is definitive: nothing was dispatched. Retry the dispatch, reinvestigate or cancel.</p>}
        </NowBlock>
      );
    }
    case "READY":
      return (
        <NowBlock tone="action" id="now-ready" title="Approved; waiting for dispatch">
          <p>The work package is approved but not dispatched. Dispatch is an explicit step: nothing dispatches it automatically.</p>
        </NowBlock>
      );
    case "EXECUTING":
      return (
        <NowBlock id="now-executing" title="Dispatch in progress">
          <p>The work order is being committed through the work-order adapter. Nothing is required from you, and nothing can change until the dispatch outcome is recorded.</p>
        </NowBlock>
      );
    case "OBSERVING": {
      const plan = (rm.observation_plans || []).slice(-1)[0];
      const facts = workFacts(lc);
      return (
        <NowBlock id="now-observing" title="Verifying recovery">
          <p>Nothing required. {observingSince(plan ? clock(plan.observation_start, { seconds: true }) : null)} under the outcome policy {plan?.policy_version ? <span className="wb-mono">{plan.policy_version}</span> : "(not recorded)"}.</p>
          {facts.length ? <p><span className="wb-ledger-key">Field status</span> {fieldStatus(lc)}</p> : null}
          <p className="wb-caption">{VERIFICATION_BASIS}</p>
        </NowBlock>
      );
    }
    case "CLOSED": {
      const outcome = (rm.outcomes || []).slice(-1)[0];
      return (
        <NowBlock id="now-closed" title="Closed">
          {outcome ? <p><Shape name={OUTCOME[outcome.result]?.shape || "unknown"} size={14} decorative /> {OUTCOME[outcome.result]?.label || "Outcome not recognised"}{outcome.basis === "SIMULATED" ? <> (simulated) <SimulatedTag /></> : null}{outcome.created_at ? ` · recorded ${clock(outcome.created_at, { seconds: true })}` : ""}</p> : <p>No outcome is recorded on this case.</p>}
          <p className="wb-secondary">No further action.</p>
        </NowBlock>
      );
    }
    case "CANCELLED": {
      const cancelled = cancellationOf(rm);
      return (
        <NowBlock id="now-cancelled" title="Cancelled">
          <p>{cancelled ? <>Cancelled by {actorWords(cancelled.actor)} at {clock(cancelled.at, { seconds: true })}{cancelled.rationale ? <> · “{cancelled.rationale}”</> : null}.</> : "This case was cancelled."} The full record is kept; the asset can open a new case.</p>
        </NowBlock>
      );
    }
    default: {
      const run = latestRun(rm);
      const rejection = phase === "PLANNING" || phase === "INTERVENTION_VALIDATED" ? rejectionOf(rm) : null;
      const resumed = phase === "INVESTIGATING" ? (rm.events || []).filter((e) => e.event_type === "LIFECYCLE_COMMAND" && e.payload?.command === "resume").slice(-1)[0] : null;
      return (
        <NowBlock id="now-automated" title="Nothing required from you">
          <p>{nextStepSentence(c)}</p>
          {rejection ? <p className="wb-rule-ink">Returned to planning after a rejection. {rejectionLine(rejection)}</p> : null}
          {resumed ? <p className="wb-rule-ink">Resumed by {actorWords(resumed.payload?.actor)} at {clock(resumed.created_at, { seconds: true })}{resumed.payload?.rationale ? <> · “{resumed.payload.rationale}”</> : null}</p> : null}
          {run ? <p className="wb-secondary">Latest analysis: {runLine(run)}</p> : null}
          {c.analysisPaused ? <p className="wb-secondary">Analysis is paused: no model provider is configured.</p> : null}
        </NowBlock>
      );
    }
  }
}

export function CaseNow({ c, now, trigger, decide, actions }) {
  const rm = c.rm || {};
  const since = lastPhaseChange(rm, c.phase)?.created_at || c.openedAt;
  const terminal = c.phase === "CLOSED" || c.phase === "CANCELLED";
  return (
    <div className="wb-now">
      {!terminal ? (
        <p className="wb-now-waiting">
          <WaitingOn role={c.waiting} prefix />
          {since ? <span className="wb-secondary"> · since {clock(since)}</span> : null}
          {c.response?.verb && c.waiting?.human ? <span className="wb-secondary"> · {c.response.verb}</span> : null}
        </p>
      ) : null}
      <Situation c={c} now={now} trigger={trigger} decide={decide} />
      {actions}
      <h3 className="wb-subhead">Case summary</h3>
      <CaseSummary c={c} trigger={trigger} />
      {c.demo ? <p className="wb-caption">Guided Demo case · simulated plant data <SimulatedTag /></p> : null}
      {c.environment && c.environment !== "UNSPECIFIED" ? <p className="wb-caption">Environment: {String(c.environment).toLowerCase()}</p> : null}
    </div>
  );
}
