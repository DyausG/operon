import { Inspectable, Stamp, EmptySlot, Dot, KV } from "../../primitives/index.jsx";
import { ReceiptBlock } from "./ExecutionRecord.jsx";
import { OutcomeBlock } from "./OutcomeRecord.jsx";
import { last } from "../../state/selectors.js";
import { num } from "../../lib/format.js";

export function RecoveryMonitor({ view, phase, verified }) {
  const receipt = last(view.execution_receipts);
  const plan = last(view.observation_plans);
  const outcome = last(view.outcomes);
  const obs = plan?.observations || [];
  const minimum = plan?.minimum_samples ?? 3;
  const slots = Math.max(minimum, obs.length);
  const limit = plan?.recovery_risk_max ?? plan?.policy_parameters?.recovery_risk_max;
  return (
    <div className="obj">
      {!verified ? <div className="banner banner-auth"><Dot tone="auth" /><span><b>Execution confirmed. Recovery not established.</b> The application evaluates post-intervention telemetry against the observation plan before any outcome exists.</span></div> : null}
      {receipt ? <ReceiptBlock receipt={receipt} compact /> : null}
      <Inspectable id={plan?.artifact_id || plan?.id} className="rec rec-auth">
        <div className="rec-head"><span className="lbl">Observation plan</span>{plan ? <Stamp tone={verified ? "ok" : "auth"}>{verified ? "Complete" : "Active"}</Stamp> : <Stamp tone="pending">Pending</Stamp>}<span className="ph-meta mono">{obs.length}/{minimum} samples{limit != null ? ` · accept ≤ ${num(limit, 2)} risk` : ""}</span></div>
        <p className="rec-body">{plan?.description || plan?.summary || "The observation plan is created by the application when execution is confirmed."}</p>
        <div className="samples">
          {Array.from({ length: slots }).map((_, i) => {
            const o = obs[i];
            if (!o) return <EmptySlot key={i} label={`Sample ${i + 1}`} hint="awaiting telemetry" />;
            const ok = limit != null ? (o.failure_risk ?? 1) <= limit : String(o.status).toUpperCase() === "HEALTHY";
            return (
              <Inspectable key={o.id || i} id={o.artifact_id || o.id} className={`slot sample ${ok ? "sample-ok" : "sample-improving"}`}>
                <span className="lbl">Sample {o.sequence ?? i + 1}<Dot tone={ok ? "ok" : "warn"} className="sample-dot" /></span>
                <span className="sample-risk mono">{num(o.failure_risk, 2)}<small>risk</small></span>
                <span className="sample-meta mono t3">h {num(o.health_score, 2)}{o.vibration_mm_s != null ? ` · ${num(o.vibration_mm_s, 1)} mm/s` : ""}</span>
              </Inspectable>
            );
          })}
        </div>
      </Inspectable>
      {outcome ? <OutcomeBlock outcome={outcome} /> : (
        <div className="slot slot-empty outcome-pending"><span className="lbl">Outcome</span><span className="slot-hint">Recovery not established. Verified recovery requires {minimum} post-intervention samples within policy; execution alone never closes an incident.</span></div>
      )}
      {verified ? <div className="note"><span className="t3">Outcome recorded by the application's deterministic verifier. Closure follows as a separate authoritative step.</span></div> : null}
    </div>
  );
}
