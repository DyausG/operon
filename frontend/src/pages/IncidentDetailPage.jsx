import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useEngineState } from "../state/engine.jsx";
import { useSettings } from "../state/settings.jsx";
import { alertByIncident, asset as assetOf, openedAt, updatedAt } from "../state/portal.js";
import { hasInspection, ledgerEntries, ownerOf, phaseOf, phaseTitle, viewOf, last, STEPS, processModel } from "../state/selectors.js";
import { ROUTES } from "../app/routes.js";
import { Breadcrumbs, EmptyState, LoadingState, Section, SeverityBadge, StatusBadge, Tabs, Modal } from "../components/index.jsx";
import { OwnerChip, Btn, Icons, IdToken, Inspectable, KV, Dot, Stamp, ProvenanceTag, When, Tag } from "../primitives/index.jsx";
import { ProcessLine } from "../features/ProcessLine.jsx";
import { OperationColumn } from "../features/Operation/OperationColumn.jsx";
import { Record } from "../features/Record.jsx";
import { SignalColumn } from "../features/SignalColumn.jsx";
import { risk as fmtRisk, clock, dateTime, num, title, words } from "../lib/format.js";

export function IncidentDetailPage() {
  const { id } = useParams();
  const { state, approve, reject } = useEngineState();
  const { settings } = useSettings();
  const navigate = useNavigate();
  const [tab, setTab] = useState("operation");
  const [confirm, setConfirm] = useState(null);
  const alert = alertByIncident(state, id);
  const view = viewOf(alert);
  const asset = alert ? assetOf(state, alert.equipment_id) : null;

  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  if (!alert) {
    return <div className="page"><div className="page-body"><Breadcrumbs items={[{ label: "Incidents", to: ROUTES.incidents }, { label: id }]} /><EmptyState title={`Incident ${id} is not in the current projection`} body="The engine only projects incidents of the current generation. A reset or a new Guided Demo starts a new generation." action={<Btn onClick={() => navigate(ROUTES.incidents)}>Back to incidents</Btn>} /></div></div>;
  }
  const phase = phaseOf(alert), owner = ownerOf(alert, state), lc = alert.lifecycle || {};
  const decide = (kind) => {
    if (settings.agent.confirmBeforeApprove) setConfirm(kind);
    else (kind === "approve" ? approve : reject)(alert);
  };
  const guardedApprove = (a) => decide("approve"), guardedReject = (a) => decide("reject");
  const tabs = [{ key: "operation", label: "Operation" }, { key: "timeline", label: "Timeline" }, { key: "record", label: "Record", count: ledgerEntries(view).length }, { key: "telemetry", label: "Telemetry" }];
  return (
    <div className="page">
      <div className="page-body page-wide">
        <Breadcrumbs items={[{ label: "Incidents", to: ROUTES.incidents }, { label: alert.incident_id }]} />
        <div className="inc-head">
          <div className="inc-title-row">
            <h1 className="inc-title">{phaseTitle(alert, state)}</h1>
            <StatusBadge value={phase} />
            <OwnerChip kind={owner.kind} label={owner.label} />
            <SeverityBadge criticality={alert.criticality} />
            <ProvenanceTag provenance={alert.provenance || lc.provenance} runtime={alert.runtime || lc.runtime} compact />
          </div>
          <div className="page-meta">
            <span className="mono">{alert.incident_id}</span>
            <Link className="inline-link" to={ROUTES.machine(alert.equipment_id)}>{alert.equipment_name || asset?.name || alert.equipment_id} · {alert.equipment_id}</Link>
            <span>Risk <span className="mono">{fmtRisk(alert.failure_prob)}</span></span>
            {alert.predicted_mode_label ? <span>{alert.predicted_mode_label}</span> : null}
            <span>rev <span className="mono">{lc.revision ?? "—"}</span></span>
            <Link className="inline-link" to={`${ROUTES.agent}?incident=${encodeURIComponent(alert.incident_id)}`}>Open in agent workspace →</Link>
          </div>
          {lc.last_reason ? <p className="t2">{lc.last_reason}</p> : null}
        </div>
        <div className="sec sec-flush"><div className="sec-body"><ProcessLine incident={alert} state={state} /></div></div>
        <Tabs tabs={tabs} value={tab} onChange={setTab} ariaLabel="Incident sections" />
        {tab === "operation" ? (
          <div className="inc-grid">
            <OperationColumn state={state} incident={alert} focusId={alert.equipment_id} approve={guardedApprove} reject={guardedReject} viewMode="ACTIVE" showSwitcher={false} />
            <div className="stack">
              <Section label="Lifecycle identifiers" flush>
                <div className="kvgrid kvgrid-2">
                  <KV label="Phase" value={title(phase)} /><KV label="Context revision" mono value={lc.context_revision ?? lc.revision} />
                  <KV label="Diagnosis"><IdToken value={lc.diagnosis_id} /></KV><KV label="Intervention"><IdToken value={lc.intervention_id} /></KV>
                  <KV label="Intervention hash"><IdToken value={lc.intervention_hash} hash /></KV><KV label="Approval requirement"><IdToken value={lc.requirement_id} /></KV>
                  <KV label="Authority valid" value={lc.authority_valid == null ? null : String(lc.authority_valid)} mono /><KV label="Reconciliation" value={lc.reconciliation_required == null ? null : lc.reconciliation_required ? "required" : "not required"} />
                  <KV label="Opened" mono value={dateTime(openedAt(alert))} /><KV label="Updated" mono value={dateTime(updatedAt(alert))} />
                </div>
              </Section>
              <Section label="Trust boundary">
                <div className="note-box">{Icons.shield({})}<span>Advisory output is dashed; authoritative application records are solid. Approval binds the exact intervention hash at the revision shown and never executes anything by itself.</span></div>
              </Section>
            </div>
          </div>
        ) : null}
        {tab === "timeline" ? <Section label="Operational timeline" meta={`${(view.events || []).length} events`} flush><IncidentTimeline alert={alert} state={state} /></Section> : null}
        {tab === "record" ? <div className="inc-grid"><Record view={view} incident={alert} state={state} /><Section label="About the record"><p className="t3">Every entry is an authoritative lifecycle event, a trusted input or an advisory specialist output, in the order the application committed them. Click a row to inspect the artifact.</p></Section></div> : null}
        {tab === "telemetry" ? <div className="inc-grid"><SignalColumn state={state} focusId={alert.equipment_id} incident={alert} /><Section label="Telemetry context"><p className="t3">The predictive signal that opened the incident, the planned window, execution and the recovery observation samples are annotated on the trace. Observation samples are clickable artifacts.</p></Section></div> : null}
        <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm === "approve" ? "Approve the exact plan?" : "Reject the plan?"} actions={<><Btn onClick={() => setConfirm(null)}>Cancel</Btn><Btn primary onClick={() => { const k = confirm; setConfirm(null); (k === "approve" ? approve : reject)(alert); }}>{confirm === "approve" ? "Approve and dispatch" : "Reject"}</Btn></>}>
          <p className="t2">{confirm === "approve" ? "Approval binds intervention hash" : "Rejection records a decision against intervention hash"} <span className="mono t1">{String(lc.intervention_hash || "").slice(0, 12)}…</span> at revision <span className="mono t1">{lc.context_revision ?? lc.revision}</span>. The lifecycle service refuses stale or mismatched intent.</p>
          <p className="t3">You can turn this confirmation off in Settings → Agent preferences.</p>
        </Modal>
      </div>
    </div>
  );
}

/** Structured timeline over the read model: one section per lifecycle stage, in the spec's vocabulary. */
export function IncidentTimeline({ alert, state }) {
  const view = viewOf(alert);
  const model = processModel(alert, state);
  const events = view.events || [];
  const find = (type) => events.filter((e) => e.event_type === type);
  const signal = (view.evidence || []).find((e) => e.kind === "model_signal");
  const decision = last(view.approval_decisions), wo = last(view.work_orders), receipt = last(view.execution_receipts);
  const plan = last(view.observation_plans), outcome = last(view.outcomes), closure = last(view.closures);
  const runs = view.agent_runs || [];
  const sections = [
    { key: "detect", title: "Detection", at: find("INCIDENT_OPENED")[0]?.created_at || openedAt(alert), done: true, artifact: signal?.artifact_id || signal?.id,
      text: signal ? `${signal.summary}` : `Predictive risk ${fmtRisk(alert.failure_prob)} crossed the gate ${fmtRisk(state.triggerThreshold)}.`, items: signal?.payload?.attribution?.slice(0, 3).map((a) => ({ l: a.label || a.feature, v: `${num(a.value, 1)} · +${num(a.contribution, 2)}` })) },
    { key: "evidence", title: "Evidence", at: last(find("EVIDENCE_ACQUIRED"))?.created_at, done: (view.evidence || []).length > 0, blocked: phaseOf(alert) === "AWAITING_EVIDENCE" && !hasInspection(view),
      text: (view.evidence || []).length ? `${(view.evidence || []).length} evidence records acquired${hasInspection(view) ? ", including a trusted technician inspection" : ""}.` : "No evidence acquired yet.",
      items: (view.evidence || []).map((e) => ({ l: words(e.kind), v: e.summary, id: e.artifact_id || e.id })) },
    { key: "reasoning", title: "Reasoning", at: runs[0]?.created_at || last(find("SPECIALIST_ACTIVITY_RECORDED"))?.created_at, done: runs.length > 0,
      text: runs.length ? `${runs.length} supervisor run${runs.length === 1 ? "" : "s"} · ${runs.reduce((n, r) => n + (r.delegations || []).length, 0)} specialist delegations · advisory only.` : "No specialist run has been admitted for this incident.",
      items: runs.map((r) => ({ l: words(r.stage || "run"), v: r.summary || words(r.disposition || r.status || ""), id: r.artifact_id })) },
    { key: "diagnosis", title: "Diagnosis", at: find("DIAGNOSIS_VALIDATED")[0]?.created_at || find("DIAGNOSIS_CREATED")[0]?.created_at, done: !!view.diagnosis, artifact: view.diagnosis?.artifact_id || view.diagnosis?.id,
      text: view.diagnosis ? `${view.diagnosis.conclusion}${view.diagnosis.confidence != null ? ` · confidence ${num(view.diagnosis.confidence, 2)}` : ""}` : "No diagnosis recorded.",
      items: (view.verdicts || []).filter((v) => v.target_kind === "diagnosis").map((v) => ({ l: `Verdict · ${words(v.decision)}`, v: v.concise_justification || v.validation_summary || "", id: v.artifact_id || v.id })) },
    { key: "plan", title: "Recommended action", at: find("INTERVENTION_VALIDATED")[0]?.created_at || find("INTERVENTION_CREATED")[0]?.created_at, done: !!view.intervention, artifact: view.intervention?.artifact_id || view.intervention?.id,
      text: view.intervention ? `${view.intervention.summary}${view.intervention.priority ? ` · ${title(view.intervention.priority)} priority` : ""}` : "No intervention drafted.",
      items: view.binding ? [{ l: "Technician", v: view.binding.technician_id }, { l: "Part", v: (view.binding.parts || []).map((p) => `${p.part_id} ×${p.quantity ?? 1}`).join(", ") }, { l: "Package", v: view.binding.work_package_id }].filter((i) => i.v) : [] },
    { key: "approval", title: decision ? (decision.decision === "APPROVE" ? "Approval" : "Rejection") : "Approval", at: decision?.approved_at || decision?.created_at || find("APPROVAL_REQUESTED")[0]?.created_at, done: !!decision, hold: !decision && phaseOf(alert) === "AWAITING_APPROVAL", artifact: decision?.artifact_id || decision?.id,
      text: decision ? `${decision.actor_id} (${words(decision.actor_role)}) ${decision.decision === "APPROVE" ? "approved" : "rejected"} the exact plan bound to hash ${String(decision.intervention_hash || "").slice(0, 10)}….` : phaseOf(alert) === "AWAITING_APPROVAL" ? "Awaiting an explicit human decision on the exact plan. Nothing executes before it." : "No approval requested yet." },
    { key: "execution", title: "Execution", at: receipt?.completed_at || wo?.dispatched_at, done: !!receipt, artifact: receipt?.artifact_id || receipt?.id || wo?.artifact_id || wo?.id,
      text: receipt ? `${receipt.performed_action || "Execution confirmed"} · ${words(receipt.status)}` : wo ? `Work order ${wo.id} dispatched; awaiting the execution receipt.` : "Nothing dispatched." },
    { key: "resolution", title: "Resolution", at: closure?.closed_at || outcome?.created_at, done: !!closure, artifact: closure?.artifact_id || closure?.id || outcome?.artifact_id || outcome?.id,
      text: closure ? closure.summary : outcome ? `${title(outcome.result)} · ${outcome.reason || ""}` : plan ? `Observing recovery · ${(plan.observations || []).length}/${plan.minimum_samples ?? 3} samples` : "Recovery not yet observed.",
      items: (plan?.observations || []).map((o) => ({ l: `Sample ${o.sequence}`, v: `risk ${num(o.failure_risk, 2)} · ${words(o.status || "")}`, id: o.artifact_id || o.id })) },
  ];
  return (
    <div className="timeline">
      {sections.map((s, i) => (
        <div key={s.key} className="tl-step">
          <div className="tl-rail"><Dot tone={s.blocked ? "warn" : s.hold ? "warn" : s.done ? "auth" : "normal"} className={s.done || s.hold || s.blocked ? "" : "dot-future"} />{i < sections.length - 1 ? <span className="tl-line" /> : null}</div>
          <Inspectable id={s.artifact} className="tl-body" disabled={!s.artifact}>
            <div className="tl-head">
              <span className={`tl-title ${s.done ? "" : "is-future"}`}>{s.title}</span>
              {s.hold ? <Stamp tone="pending">Hold point</Stamp> : null}
              {s.blocked ? <Tag tone="warn">Blocked · trusted input</Tag> : null}
              {s.at ? <span className="tl-when mono">{clock(s.at)}</span> : null}
            </div>
            <p className="tl-text">{s.text}</p>
            {(s.items || []).length ? <div className="tl-items">{s.items.map((it, j) => <Inspectable key={j} id={it.id} className="tl-item" disabled={!it.id}><span className="lbl">{it.l}</span><span>{it.v}</span></Inspectable>)}</div> : null}
          </Inspectable>
        </div>
      ))}
      {model.branch ? <div className="tl-step"><div className="tl-rail"><Dot tone="crit" /></div><div className="tl-body"><div className="tl-head"><span className="tl-title">{model.branch.label}</span></div><p className="tl-text">{model.branch.reason}</p></div></div> : null}
    </div>
  );
}
