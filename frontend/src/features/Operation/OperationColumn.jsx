import { Swap } from "../../motion/index.jsx";
import { OwnerChip, ClassIcon } from "../../primitives/index.jsx";
import { ownerOf, phaseOf, phaseTitle, viewOf, EXCEPTIONAL, last } from "../../state/selectors.js";
import { risk as fmtRisk } from "../../lib/format.js";
import { HealthBoard } from "./HealthBoard.jsx";
import { IncidentOpened } from "./IncidentOpened.jsx";
import { Investigation } from "./Investigation.jsx";
import { DiagnosisRecord } from "./DiagnosisRecord.jsx";
import { PlanAssembly } from "./PlanAssembly.jsx";
import { ApprovalGate } from "./ApprovalGate.jsx";
import { ExecutionRecord } from "./ExecutionRecord.jsx";
import { RecoveryMonitor } from "./RecoveryMonitor.jsx";
import { OutcomeRecord } from "./OutcomeRecord.jsx";
import { ExceptionalRecord } from "./ExceptionalRecord.jsx";

function stageKey(incident, view) {
  const p = phaseOf(incident);
  if (!p) return "monitoring";
  if ((p === "INVESTIGATING" || p === "AWAITING_EVIDENCE") && view.diagnosis) return "DIAGNOSIS";
  if (p === "OBSERVING" && (view.outcomes || []).length) return "VERIFIED";
  return p;
}

function reasonFor(incident, state, asset) {
  if (incident?.lifecycle?.last_reason) return incident.lifecycle.last_reason;
  const d = state.demoScenario || {};
  if (d.active) {
    if (d.phase === "PREDICTIVE_RISK_RISING") return `${asset?.predicted_mode_label || "Signature developing"}. Predictive risk ${fmtRisk(asset?.failure_prob)} against a gate of ${fmtRisk(state.triggerThreshold)}. Prediction is not a diagnosis.`;
    if (d.phase === "FACTORY_DEGRADING") return `${asset?.predicted_mode_label || "Small anomaly"} on ${asset?.equipment_id}. Risk ${fmtRisk(asset?.failure_prob)}; below the warning band.`;
    return "All assets within nominal signature on the simulated plant. Scripted demo; no live model.";
  }
  return state.running ? `Model risk scored every tick. Warning band ${fmtRisk(state.warnThreshold)}; incident gate ${fmtRisk(state.triggerThreshold)}.` : "Simulator paused.";
}

export function OperationColumn({ state, incident, focusId, approve, reject, onSelect }) {
  const view = viewOf(incident);
  const phase = phaseOf(incident);
  const asset = state.fleet.find((a) => a.equipment_id === focusId);
  const key = stageKey(incident, view);
  const owner = ownerOf(incident, state);
  const pending = !!state.action.pending;
  let object;
  switch (key) {
    case "monitoring": object = <HealthBoard state={state} focusId={focusId} onSelect={onSelect} />; break;
    case "OPEN": object = <IncidentOpened incident={incident} view={view} asset={asset} />; break;
    case "INVESTIGATING": case "AWAITING_EVIDENCE": object = <Investigation incident={incident} view={view} phase={phase} />; break;
    case "DIAGNOSIS": case "DIAGNOSIS_VALIDATED": object = <DiagnosisRecord view={view} phase={phase} />; break;
    case "PLANNING": case "INTERVENTION_VALIDATED": object = <PlanAssembly view={view} phase={phase} />; break;
    case "AWAITING_APPROVAL": object = <ApprovalGate incident={incident} view={view} approve={approve} reject={reject} pending={pending} />; break;
    case "READY": case "EXECUTING": object = <ExecutionRecord view={view} phase={phase} />; break;
    case "OBSERVING": case "VERIFIED": object = <RecoveryMonitor view={view} phase={phase} verified={key === "VERIFIED"} />; break;
    case "CLOSED": object = <OutcomeRecord view={view} state={state} />; break;
    default: object = EXCEPTIONAL.has(key) ? <ExceptionalRecord incident={incident} view={view} /> : <Investigation incident={incident} view={view} phase={phase} />;
  }
  return (
    <section className="col col-op" aria-label="Operation">
      <div className="state">
        <div className="state-main">
          <h1 className="state-phase">{phaseTitle(incident, state)}</h1>
          <p className="state-why">{reasonFor(incident, state, asset)}</p>
        </div>
        <div className="state-side">
          <OwnerChip kind={owner.kind} label={owner.label} />
          {asset ? <span className="state-asset"><ClassIcon cls={asset.equipment_class} size={13} /><span className="truncate">{asset.name}</span><span className="t4">·</span><span className="mono">{asset.equipment_id}</span></span> : null}
        </div>
      </div>
      <div className="col-scroll op-body"><Swap id={key} className="op-swap">{object}</Swap></div>
      <div className="op-invariant" aria-label="Truthfulness invariant">
        {["Prediction", "Diagnosis", "Intervention", "Approval", "Execution", "Outcome"].map((w, i) => <span key={w}>{i ? <i>≠</i> : null}{w}</span>)}
        {incident?.lifecycle?.provenance === "SIMULATED" ? <span className="op-invariant-prov">simulated read model</span> : null}
        {(() => { const r = last(view.execution_receipts); return r && phase !== "CLOSED" ? <span className="op-invariant-note">execution ≠ recovery</span> : null; })()}
      </div>
    </section>
  );
}
