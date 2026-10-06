// The decision surface (08 screen 8): the only authoritative approval UI. Framed, raised, 2 px INK
// top rule (CH-1: never violet); violet appears only on the person glyph. Order: action → what will
// happen → if not approved → why → reviews → contradicting evidence → conditions → estimates →
// bound identifiers → decider → acknowledgement → rationale → binding token → controls.
import { useEffect, useId, useRef, useState } from "react";
import { IconSquareCheck, IconSquareX } from "@tabler/icons-react";
import { Shape } from "../components/glyphs.jsx";
import { Button, Checkbox, InlineAlert, Ledger, TextArea } from "../components/ui.jsx";
import { assessment, contradictingEvidence, criticChallenges, latestRun } from "../model/cases.js";
import { clock, when, dayClock, duration, middle, number, score, zoneAbbr } from "../model/format.js";

const bindingOf = (c) => ({
  requirement_id: c.alert?.lifecycle?.requirement_id || null,
  intervention_id: c.alert?.lifecycle?.intervention_id || null,
  intervention_hash: c.alert?.lifecycle?.intervention_hash || null,
  context_revision: c.alert?.lifecycle?.context_revision ?? null,
});
const sameBinding = (a, b) => a.requirement_id === b.requirement_id && a.intervention_hash === b.intervention_hash && a.context_revision === b.context_revision;

function consequences(c) {
  const rm = c.rm || {};
  const out = [];
  for (const step of rm.intervention?.steps || []) {
    if (step.capability === "create_work_package") {
      const p = step.parameters || {};
      const parts = (p.parts || []).map((x) => `${x.part_id} × ${x.qty}`).join(", ");
      const [ws, we] = String(p.window || "").split("/");
      out.push(<>Creates a work package for <span className="wb-mono">{p.equipment_id}</span> through the local CMMS adapter: a work order{parts ? <>, reservation of <span className="wb-mono">{parts}</span></> : null}, a labour booking for <span className="wb-mono">{p.technician_id || "the bound technician"}</span>{ws && we ? <> in the window {dayClock(ws)}–{clock(we)}</> : null}, and a dispatch notification record (delivery not tracked).</>);
    } else if (step.capability === "notify") {
      out.push(<>Sends a notification through the notification adapter.</>);
    } else {
      out.push(<>Runs the governed step <span className="wb-mono">{step.capability}</span>.</>);
    }
  }
  out.push(<>Starts post-work verification under the application’s outcome policy once the work order is confirmed.</>);
  return out;
}

function reviewsLine(rm) {
  const run = latestRun(rm, "INTERVENTION_REVIEW") || latestRun(rm, "DIAGNOSIS");
  if (!run) return "No review runs recorded.";
  const critic = assessment(run, "critic");
  const plan = assessment(run, "plan");
  const eng = assessment(run, "engineering");
  const ops = assessment(run, "operations");
  const parts = [];
  if (eng) parts.push(`Engineering: ${String(eng.intervention_feasibility || "no verdict").toLowerCase()}`);
  if (ops) parts.push(`Operations: resources ${String(ops.resource_feasibility || "not assessed").toLowerCase()}`);
  if (critic) parts.push(`Critic: ${String(critic.recommendation || "no recommendation").toLowerCase()}`);
  if (plan) parts.push(`Planner: ${plan.reversible ? "reversible" : "not reversible"}, ${plan.safety_relevant ? "safety-relevant" : "not safety-relevant"}`);
  const reviewed = (critic || eng || ops)?.reviewed_intervention_id;
  const scope = reviewed && reviewed !== rm.intervention?.id ? `; reviewed draft ${String(reviewed).slice(0, 8)}, superseded by the bound plan` : "";
  return parts.length ? `${parts.join(" · ")} (advisory, run ${String(run.run_id).slice(0, 8)}${scope})` : "Reviews recorded without a verdict.";
}

export function DecisionSurface({ c, session, roleLabel, connected, now, trigger, onDecide }) {
  const rm = c.rm || {};
  const req = c.requirement;
  const current = bindingOf(c);
  const opened = useRef(current);
  const [, setChangeAck] = useState(0);
  const changed = !sameBinding(opened.current, current);
  const contradicting = contradictingEvidence(rm);
  const challenges = criticChallenges(rm);
  const needsAck = contradicting.length > 0 || challenges.length > 0;
  const [ack, setAck] = useState(false);
  const [rationale, setRationale] = useState("");
  const [touched, setTouched] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(null);
  const [refusal, setRefusal] = useState(null);
  const [recorded, setRecorded] = useState(null);
  const ackId = useId(), reasonId = useId(), changeId = useId(), rationaleId = useId();
  const ackBox = useRef(null);

  useEffect(() => { if (!changed) return; setAck(false); }, [changed]);

  const expired = c.expiry?.state === "expired";
  const near = c.expiry?.state === "approaching" || c.expiry?.state === "final";
  const dx = rm.diagnosis;
  const alternatives = (rm.hypotheses || []).filter((h) => (dx?.alternative_hypothesis_ids || []).includes(h.id) && h.status !== "REFUTED");
  const conditions = [...new Set([...(req?.conditions || []), ...(c.alert?.proposal?.governance?.conditions || [])])];
  const iv = rm.intervention || {};
  const hasEstimates = [iv.estimated_cost, iv.estimated_downtime_minutes, iv.estimated_avoided_loss].some(Number.isFinite);

  // Inactive reasons in priority order (R-3). Each moves focus to its blocker.
  let block = null;
  if (!connected) block = { text: "Reconnect to make decisions.", focus: () => document.getElementById("wb-connection-banner")?.focus() };
  else if (changed) block = { text: "The case changed since you opened it. Review the change first.", focus: () => document.getElementById(changeId)?.focus() };
  else if (needsAck && !ack) block = { text: "Confirm that you have reviewed the contradicting evidence first.", focus: () => document.getElementById(ackId)?.focus() };

  const rationaleLevel = (() => {
    if (!(touched || submitted) || !rejectOpen) return null;
    if (!rationale.trim()) return "error";
    if (rationale.trim().length < 10) return "warning";
    return null;
  })();
  const rationaleMsg = rationaleLevel === "error" ? "A reason is required to reject." : rationaleLevel === "warning" ? "This reason is short. It will be recorded as written." : null;

  const decide = async (decision) => {
    setRefusal(null);
    if (decision === "REJECT") {
      setSubmitted(true);
      if (!rationale.trim()) { document.getElementById(rationaleId)?.focus(); return; }
    }
    setBusy(decision);
    const body = {
      ...current, decision,
      actor_id: session?.email || "declared-operator",
      actor_role: session?.role || "maintenance_approver",
      ...(rationale.trim() ? { rationale: rationale.trim() } : {}),
    };
    const result = await onDecide(body);
    setBusy(null);
    if (result?.ok === false) setRefusal(result.error || "The decision was refused.");
    else setRecorded({ decision, at: Date.now() });
  };

  if (expired) {
    return (
      <section className="wb-decision" aria-labelledby="wb-decision-title">
        <div className="wb-decision-head">
          <h3 className="wb-decision-title" id="wb-decision-title">Approval request expired at {when(req?.expires_at)}</h3>
        </div>
        <p>Nothing was dispatched. Renewal isn’t available in this version (G11). The case remains in Awaiting decision.</p>
      </section>
    );
  }

  if (recorded) {
    return (
      <section className="wb-decision is-recorded" aria-labelledby="wb-decision-title" role="status">
        <div className="wb-decision-head">
          <h3 className="wb-decision-title" id="wb-decision-title">
            {recorded.decision === "APPROVE" ? "Approved" : "Rejected and escalated"} by {session?.name || "declared operator"} at {clock(recorded.at, { seconds: true })}
          </h3>
        </div>
        <p>{recorded.decision === "APPROVE" ? "Dispatching the bound work package…" : "Automated progress has stopped; an engineering decision is required."} The record updates when the backend confirms.</p>
      </section>
    );
  }

  return (
    <section className="wb-decision" aria-labelledby="wb-decision-title" id="decision-surface">
      <div className="wb-decision-head">
        <h3 className="wb-decision-title" id="wb-decision-title">
          <Shape name="decision" size={16} decorative tone="decision" />
          Decision required
        </h3>
        <span className={`wb-decision-deadline ${near ? "wb-deadline-near" : ""}`}>
          {near ? <Shape name="elevated" size={14} label="Deadline approaching" tone="warning" /> : null}
          {req?.expires_at ? <>by {when(req.expires_at)} {zoneAbbr(new Date(req.expires_at))} · in {duration(Date.parse(req.expires_at) - now)}</> : "Deadline not reported"}
        </span>
      </div>
      <p className="wb-decision-action">Approve the exact work package for <span className="wb-mono">{c.assetId}</span> · {c.assetName}</p>

      <div className="wb-decision-block">
        <h4 className="wb-decision-key">What will happen if you approve (immediately)</h4>
        <ul className="wb-bullets">{consequences(c).map((x, i) => <li key={i}>{x}</li>)}</ul>
        <p className="wb-decision-note">Cannot be undone from this application: the dispatched work order and reservations.</p>
      </div>

      <Ledger className="wb-decision-ledger" rows={[
        { label: "If not approved", value: <>The requirement expires at {req?.expires_at ? dayClock(req.expires_at) : "an unreported time"}; nothing is dispatched. Current model risk score <span className="wb-num">{score(c.failureProb)}</span> (action gate <span className="wb-num">{score(trigger)}</span>).</> },
        { label: "Why", value: dx ? <>Diagnosis accepted {dx.created_at ? clock(dx.created_at) : ""}: {dx.conclusion} · cites {(dx.evidence_ids || []).length} evidence</> : "No accepted diagnosis recorded." },
        { label: "Reviews", value: reviewsLine(rm) },
        { label: "Contradicting", value: needsAck
          ? <>{contradicting.length ? `${contradicting.length} evidence ${contradicting.length === 1 ? "item contradicts" : "items contradict"} the diagnosis` : ""}{contradicting.length && challenges.length ? " · " : ""}{challenges.length ? `${challenges.length} unresolved critic ${challenges.length === 1 ? "challenge" : "challenges"}` : ""} (acknowledgement required)</>
          : <>No evidence contradicts the diagnosis; no unresolved critic challenges.{alternatives.length ? <> Alternative hypothesis unresolved (advisory): {alternatives.map((h) => h.mechanism).join("; ")}</> : null}</> },
        { label: "Conditions", value: conditions.length ? <ul className="wb-bullets">{conditions.map((t) => <li key={t}>{t}</li>)}</ul> : "None recorded." },
        hasEstimates ? { label: "Estimates", value: <>Cost {number(iv.estimated_cost)} · downtime {iv.estimated_downtime_minutes} min · avoided loss {number(iv.estimated_avoided_loss)} <span className="wb-secondary">— estimates · assumption set <span className="wb-mono">{iv.business_assumption_version || "not recorded"}</span> · currency not recorded</span></> } : null,
        { label: "Bound to", value: (
          <>
            <span className="wb-bound">requirement <span className="wb-mono" title={current.requirement_id}>{middle(current.requirement_id, 4, 3)}</span> · intervention <span className="wb-mono" title={current.intervention_id}>{middle(current.intervention_id, 4, 3)}</span> · hash <span className="wb-mono" title={current.intervention_hash}>{middle(current.intervention_hash, 6, 4)}</span> · <span className="wb-mono">R{current.context_revision}</span></span>
            <span className="wb-secondary">Any change to the case or plan voids this approval.</span>
          </>
        ) },
        { label: "Decider", value: <>Required role: {(req?.required_roles || []).map((r) => r.replace(/_/g, " ")).join(", ") || "not reported"} · recorded as: {session?.name || "declared operator"}, {roleLabel.toLowerCase()} <span className="wb-secondary">(declared, not verified: G8)</span></> },
      ]} />

      {changed ? (
        <div className="wb-decision-change" id={changeId} tabIndex={-1} role="alert">
          <p><strong>Changed since you opened this</strong> (R{opened.current.context_revision} → R{current.context_revision}). New binding <span className="wb-mono">{middle(current.intervention_hash, 6, 4)} · R{current.context_revision}</span>. Review before deciding.</p>
          <Button variant="secondary" size="sm" onClick={() => { opened.current = current; setChangeAck((n) => n + 1); }}>I have reviewed the change</Button>
        </div>
      ) : null}

      {needsAck ? (
        <div className="wb-decision-ack" ref={ackBox}>
          <Checkbox id={ackId} checked={ack} onChange={setAck}>
            I have reviewed the contradicting evidence ({contradicting.length + challenges.length} {contradicting.length + challenges.length === 1 ? "item" : "items"})
          </Checkbox>
        </div>
      ) : null}

      <TextArea id={rationaleId} label="Rationale" hint="Optional for approval · required for rejection" value={rationale}
        onChange={(v) => setRationale(v)} onBlur={() => setTouched(true)} message={rationaleMsg} level={rationaleLevel} rows={2} />

      {refusal ? <InlineAlert tone="critical" title="The backend refused this decision" role="alert">{refusal}</InlineAlert> : null}

      <p className="wb-binding">Binding <span className="wb-mono">{String(current.intervention_hash || "").slice(0, 6)} · R{current.context_revision}</span></p>
      {block ? <p className="wb-sr" id={reasonId}>{block.text}</p> : null}
      <div className="wb-decision-controls">
        <Button variant="primary" size="lg" icon={IconSquareCheck} inactive={!!block} reasonId={reasonId} onBlocked={block?.focus}
          busy={busy === "APPROVE"} busyLabel="Recording approval…" onClick={() => decide("APPROVE")}>
          Approve and dispatch
        </Button>
        <Button variant="danger" size="lg" icon={IconSquareX} inactive={!connected} reasonId={reasonId} onBlocked={block?.focus}
          aria-expanded={rejectOpen} onClick={() => setRejectOpen((o) => !o)}>
          Reject and escalate…
        </Button>
        {block ? <span className="wb-decision-reason" aria-hidden="true">{block.text}</span> : null}
      </div>
      {rejectOpen ? (
        <div className="wb-reject" role="group" aria-label="Confirm rejection">
          <p>Rejecting escalates this case. Automated progress stops until an engineer resolves it, which isn’t available in this version (G2). A reason is required and is recorded with your declared identity.</p>
          <div className="wb-reject-controls">
            <Button variant="danger" size="md" inactive={!connected} reasonId={reasonId} onBlocked={block?.focus}
              busy={busy === "REJECT"} busyLabel="Recording rejection…" onClick={() => decide("REJECT")}>Confirm rejection</Button>
            <Button variant="secondary" size="md" onClick={() => setRejectOpen(false)}>Cancel</Button>
          </div>
        </div>
      ) : null}
      <p className="wb-decision-foot">Request changes isn’t available in this version (G4). Rejecting escalates this case; automated progress stops until an engineer resolves it, which isn’t available yet (G2).</p>
    </section>
  );
}
