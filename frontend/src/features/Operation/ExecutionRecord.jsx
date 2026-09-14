import { Inspectable, KV, Stamp, IdToken, Dot, ProvenanceTag, When } from "../../primitives/index.jsx";
import { last } from "../../state/selectors.js";
import { clock, title, words } from "../../lib/format.js";

export function DecisionLine({ decision }) {
  if (!decision) return null;
  const ok = decision.decision === "APPROVE";
  return (
    <Inspectable id={decision.artifact_id || decision.id} className="decision">
      <Stamp tone={ok ? "auth" : "crit"}>{ok ? "Approved" : "Rejected"}</Stamp>
      <span className="decision-text"><b>{decision.actor_id}</b> · {words(decision.actor_role)}{decision.approved_at || decision.created_at ? <span className="t3"> · {clock(decision.approved_at || decision.created_at)}</span> : null}</span>
      <span className="decision-meta mono">bound to <IdToken value={decision.intervention_hash} hash /> · {decision.plan_version || `rev ${decision.context_revision ?? "—"}`}</span>
    </Inspectable>
  );
}

export function ReceiptBlock({ receipt, compact = false }) {
  if (!receipt) return null;
  const ok = ["SUCCEEDED", "CONFIRMED"].includes(String(receipt.status).toUpperCase());
  return (
    <Inspectable id={receipt.artifact_id || receipt.id} className="rec rec-auth receipt">
      <div className="rec-head"><span className="lbl">Execution receipt</span><Stamp tone={ok ? "auth" : "crit"}>{ok ? "Receipt · succeeded" : title(receipt.status)}</Stamp><ProvenanceTag provenance={receipt.provenance} runtime={receipt.runtime} live={receipt.live_model} compact /><span className="ph-meta mono">{receipt.id}</span></div>
      {receipt.performed_action ? <p className="rec-body">{receipt.performed_action}</p> : null}
      {!compact ? (
        <div className="kvgrid kvgrid-4">
          <KV label="Technician" mono value={receipt.technician_id} />
          <KV label="Started" mono value={clock(receipt.started_at || receipt.attempted_at)} />
          <KV label="Completed" mono value={clock(receipt.completed_at)} />
          <KV label="Consumed" mono value={(receipt.resources_consumed || []).map((r) => `${r.part_id} ×${r.quantity}`).join(", ") || null} />
        </div>
      ) : null}
      <div className="rec-lines mono t3">{Object.entries(receipt.external_ids || {}).map(([k, v]) => <span key={k}>{k} <b className="t2">{v}</b></span>)}<span>adapter <b className="t2">{receipt.adapter}</b></span></div>
    </Inspectable>
  );
}

export function ExecutionRecord({ view, phase }) {
  const decision = last(view.approval_decisions), wo = last(view.work_orders), receipt = last(view.execution_receipts);
  return (
    <div className="obj">
      <DecisionLine decision={decision} />
      {wo ? (
        <Inspectable id={wo.artifact_id || wo.id} className="rec rec-auth">
          <div className="rec-head"><span className="lbl">Work order</span><Stamp>{words(wo.status || "dispatched")}</Stamp><span className="ph-meta mono">{wo.id}</span></div>
          <h2 className="rec-title">{wo.summary}</h2>
          <div className="kvgrid kvgrid-4">
            <KV label="Work package" mono value={wo.work_package_id} /><KV label="Intervention" mono value={wo.intervention_id} />
            <KV label="Dispatched" mono value={clock(wo.dispatched_at)} /><KV label="Approval" mono value={wo.approval_binding_id} />
          </div>
        </Inspectable>
      ) : phase === "READY" ? <div className="note"><Dot tone="auth" /><span className="t2">Approved. The application dispatches the exact bound work package; no automatic execution from advisory output.</span></div> : null}
      {receipt ? <ReceiptBlock receipt={receipt} /> : phase === "EXECUTING" ? (
        <div className="slot slot-empty slot-running"><span className="lbl"><span className="dot dot-auth pulse" /> Executing</span><span className="slot-hint">Work order dispatched. Awaiting the execution receipt from the executor; execution is not yet confirmed.</span></div>
      ) : null}
      <div className="note"><span className="t3">Execution confirmation moves the incident to observation. Recovery is established only from post-intervention evidence.</span></div>
    </div>
  );
}
