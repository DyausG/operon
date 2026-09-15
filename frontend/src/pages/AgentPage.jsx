import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useEngineState } from "../state/engine.jsx";
import { useSettings } from "../state/settings.jsx";
import { deriveAgentRuntime, RUN_STATES } from "../state/agentRuntime.js";
import { alertByIncident, asset as assetOf, incidentRows } from "../state/portal.js";
import { ledgerEntries, ownerOf, phaseOf, phaseTitle, viewOf, verdictFor, isActive, roleName, STAGE_LABEL } from "../state/selectors.js";
import { ROUTES } from "../app/routes.js";
import { PageHeader, Section, EmptyState, LoadingState, StatusBadge, Modal, Tabs } from "../components/index.jsx";
import { Btn, Dot, Icons, Tag, OwnerChip, IdToken, KV, ProvenanceTag, Inspectable, Stamp, When } from "../primitives/index.jsx";
import { OperationColumn } from "../features/Operation/OperationColumn.jsx";
import { EvidenceSlots } from "../features/Operation/EvidenceSlots.jsx";
import { SpecialistChain } from "../features/SpecialistChain.jsx";
import { clock, title, words, risk as fmtRisk } from "../lib/format.js";

export function AgentPage() {
  const { state, approve, reject } = useEngineState();
  const { settings } = useSettings();
  const [params, setParams] = useSearchParams();
  const rows = useMemo(() => incidentRows(state), [state]);
  const wantIncident = params.get("incident"), wantMachine = params.get("machine");
  const selected = useMemo(() => {
    if (wantIncident) return alertByIncident(state, wantIncident);
    if (wantMachine) return rows.find((r) => r.equipmentId === wantMachine && r.active)?.alert || rows.find((r) => r.equipmentId === wantMachine)?.alert || null;
    return rows.find((r) => r.active)?.alert || rows[0]?.alert || null;
  }, [state, rows, wantIncident, wantMachine]);
  const [tab, setTab] = useState("operation");
  const [confirm, setConfirm] = useState(null);
  const runtime = useMemo(() => deriveAgentRuntime(selected, state), [selected, state]);
  const view = viewOf(selected);
  const asset = selected ? assetOf(state, selected.equipment_id) : (wantMachine ? assetOf(state, wantMachine) : null);
  const console_ = useMemo(() => ledgerEntries(view).filter((e) => settings.agent.showAdvisoryLane || e.lane !== "advisory").slice(0, 60), [view, settings.agent.showAdvisoryLane]);
  useEffect(() => { document.title = "Operon Agent · Operon"; }, []);

  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  const decide = (kind) => { if (settings.agent.confirmBeforeApprove) setConfirm(kind); else (kind === "approve" ? approve : reject)(selected); };
  const prov = state.reasoningProvenance || {};
  return (
    <div className="page">
      <div className="page-body page-wide">
        <PageHeader eyebrow="Reasoning" title="Operon Agent workspace" meta={<>
          <span>Backend <span className="mono">{prov.backend || "none"}</span></span>
          <span>{prov.runtime || "runtime not reported"} · {prov.framework || ""}</span>
          <span><Dot tone={runtime.available ? "auth" : "warn"} /> {runtime.available ? "runtime available" : "awaiting runtime"}</span>
          <ProvenanceTag provenance={prov.provenance} runtime={prov.runtime} compact />
        </>} />
        <div className="agent-grid">
          {/* left: context */}
          <div className="agent-col">
            <Section label="Context" meta={`${rows.filter((r) => r.active).length} active`} flush>
              <div className="ctx-list">
                {rows.length ? rows.map((r) => (
                  <button key={r.id} type="button" className={`ctx-row ${selected?.incident_id === r.incidentId ? "is-active" : ""}`} onClick={() => setParams({ incident: r.incidentId })}>
                    <Dot tone={r.tone} />
                    <span className="ctx-row-text"><span className="mono">{r.equipmentId}</span><small className="truncate">{r.phaseLabel} · {r.incidentId}</small></span>
                    {r.phase === "AWAITING_APPROVAL" ? <Tag tone="warn">Approve</Tag> : null}
                  </button>
                )) : <div className="menu-empty t3">No incidents to reason about. Start the guided demo from the Engine menu.</div>}
              </div>
            </Section>
            <Section label="Selected machine">
              {asset ? (
                <div className="stack">
                  <div className="row-wrap"><span className="t1">{asset.name}</span><Link className="inline-link mono" to={ROUTES.machine(asset.equipment_id)}>{asset.equipment_id}</Link></div>
                  <div className="kvgrid kvgrid-2"><KV label="Status" value={<StatusBadge value={asset.status} />} /><KV label="Risk / 24 h" mono value={fmtRisk(asset.failure_prob)} /><KV label="Signature" value={asset.predicted_mode !== "NONE" ? asset.predicted_mode_label : "Nominal"} /><KV label="Criticality" value={title(asset.criticality || "")} /></div>
                </div>
              ) : <span className="t3">No machine selected.</span>}
            </Section>
            <Section label="Runtime state" meta={runtime.state}>
              <RuntimeState runtime={runtime} />
            </Section>
          </div>

          {/* centre: operation + console */}
          <div className="agent-col">
            {selected ? (
              <>
                <div className="row-wrap">
                  <span className="inc-title">{phaseTitle(selected, state)}</span>
                  <StatusBadge value={phaseOf(selected)} />
                  <OwnerChip {...ownerOf(selected, state)} />
                  <Link className="inline-link mono" to={ROUTES.incident(selected.incident_id)}>{selected.incident_id} →</Link>
                </div>
                <Tabs tabs={[{ key: "operation", label: "Operation" }, { key: "runs", label: "Specialist runs", count: runtime.runs.length }, { key: "evidence", label: "Evidence", count: (view.evidence || []).length }, { key: "console", label: "Activity", count: console_.length }]} value={tab} onChange={setTab} ariaLabel="Workspace panels" />
                {tab === "operation" ? <div className="inc-grid" style={{ gridTemplateColumns: "minmax(0,1fr)" }}><OperationColumn state={state} incident={selected} focusId={selected.equipment_id} approve={() => decide("approve")} reject={() => decide("reject")} viewMode="ACTIVE" showSwitcher={false} /></div> : null}
                {tab === "runs" ? (
                  <div className="stack">
                    {runtime.runs.length ? runtime.runs.map((r) => <Section key={r.run_id} label={`${STAGE_LABEL[r.stage] || words(r.stage || "run")}`} meta={`${r.tool_calls ?? 0} structured outputs`}><SpecialistChain run={r} verdict={verdictFor(view, r.stage === "DIAGNOSIS" ? "diagnosis" : "intervention")} stage={r.stage} /></Section>) : <EmptyState title="No specialist runs" body={runtime.available ? "Runs are admitted by the lifecycle service when a stage needs reasoning." : "The reasoning runtime is not connected; durable evidence still accumulates."} />}
                  </div>
                ) : null}
                {tab === "evidence" ? <Section label="Frozen evidence packet" meta={`${(view.evidence || []).length} records`}><EvidenceSlots evidence={view.evidence || []} blocked={phaseOf(selected) === "AWAITING_EVIDENCE"} /></Section> : null}
                {tab === "console" ? <AgentConsole entries={console_} runtime={runtime} /> : null}
              </>
            ) : <EmptyState title="No incident selected" body="Pick an incident in the context list. The workspace shows the frozen evidence, specialist runs, recommendations and the approval hold point for that incident." />}
          </div>

          {/* right: runs, recommendations, transitions */}
          <div className="agent-col">
            <Section label="Specialist runs" meta={`${runtime.runs.length} · ${runtime.toolCalls} structured outputs`} flush>
              {runtime.runs.length ? (
                <div className="ctx-list">
                  {runtime.runs.map((r) => (
                    <Inspectable key={r.run_id} id={r.artifact_id} className="ctx-row" as="div">
                      <Dot tone={String(r.status).toUpperCase() === "RUNNING" ? "warn" : (r.stale_reasons || []).length ? "crit" : "adv"} dashed />
                      <span className="ctx-row-text"><span>{STAGE_LABEL[r.stage] || words(r.stage || "run")}</span><small className="truncate">{words(r.disposition || r.status || "")} · {(r.delegations || []).length} delegations · {r.tool_calls ?? 0} outputs</small></span>
                      <button type="button" className="link-btn" onClick={(e) => { e.stopPropagation(); setTab("runs"); }}>Open</button>
                    </Inspectable>
                  ))}
                </div>
              ) : <div className="menu-empty t3">{runtime.available ? "No runs admitted yet." : "Reasoning runtime not connected."}</div>}
            </Section>
            <Section label="Recommendations">
              {view.diagnosis || view.intervention ? (
                <div className="stack">
                  {view.diagnosis ? <Inspectable id={view.diagnosis.artifact_id || view.diagnosis.id} className="note-box"><Dot tone="auth" /><span><b>Diagnosis.</b> {view.diagnosis.conclusion}</span></Inspectable> : null}
                  {view.intervention ? <Inspectable id={view.intervention.artifact_id || view.intervention.id} className="note-box"><Dot tone="auth" /><span><b>Intervention.</b> {view.intervention.summary}</span></Inspectable> : null}
                  {(view.verdicts || []).slice(-2).map((v) => <Inspectable key={v.id} id={v.artifact_id || v.id} className="note-box"><Stamp tone={v.decision === "ACCEPT" ? "auth" : "crit"}>{title(v.decision)}</Stamp><span>{v.concise_justification || v.validation_summary}</span></Inspectable>)}
                </div>
              ) : <span className="t3">No diagnosis or intervention recorded yet.</span>}
            </Section>
            <Section label="State transitions" meta={`${runtime.transitions.length}`}>
              {runtime.transitions.length ? <div className="transitions">{runtime.transitions.slice(-8).reverse().map((t) => <div key={t.id} className="transition"><span className="mono t4">{clock(t.at)}</span><span><span className="t3">{title(t.from)}</span> → <span className="t1">{title(t.to)}</span>{t.reason ? <span className="t3"> · {t.reason}</span> : null}</span></div>)}</div> : <span className="t3">No transitions recorded.</span>}
            </Section>
          </div>
        </div>
        <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm === "approve" ? "Approve the exact plan?" : "Reject the plan?"} actions={<><Btn onClick={() => setConfirm(null)}>Cancel</Btn><Btn primary onClick={() => { const k = confirm; setConfirm(null); (k === "approve" ? approve : reject)(selected); }}>{confirm === "approve" ? "Approve and dispatch" : "Reject"}</Btn></>}>
          <p className="t2">The decision is bound to intervention hash <span className="mono t1">{String(selected?.lifecycle?.intervention_hash || "").slice(0, 12)}…</span> at revision <span className="mono t1">{selected?.lifecycle?.context_revision ?? "—"}</span>.</p>
        </Modal>
      </div>
    </div>
  );
}

function RuntimeState({ runtime }) {
  const cap = runtime.capabilities;
  return (
    <div className="stack">
      <div className="rt-state">
        <div className="rt-cell"><span className="lbl">Run state</span><span className="kv-v mono">{runtime.state}</span></div>
        <div className="rt-cell"><span className="lbl">Backend</span><span className="kv-v mono">{runtime.backend} · {runtime.status}</span></div>
        <div className="rt-cell is-reserved"><span className="lbl">Path</span><span className="kv-v t3">{runtime.path || "not modelled"}</span></div>
        <div className="rt-cell is-reserved"><span className="lbl">Interruption</span><span className="kv-v t3">{runtime.interruption || "none reported"}</span></div>
        <div className="rt-cell is-reserved"><span className="lbl">Superseded by</span><span className="kv-v t3">{runtime.supersededBy || "—"}</span></div>
        <div className="rt-cell is-reserved"><span className="lbl">Recovery</span><span className="kv-v t3">{runtime.recovery || "—"}</span></div>
      </div>
      <div className="rt-vocab" aria-label="Runtime state vocabulary">{RUN_STATES.map((s) => <Tag key={s} className={s === runtime.state ? "is-current" : ""} dashed={s !== runtime.state}>{s}</Tag>)}</div>
      <div className="cap-list">
        {Object.entries(cap).map(([k, c]) => (
          <div key={k} className="cap">{c.supported === true ? Icons.check({ size: 14 }) : c.supported === "partial" ? Icons.info({ size: 14 }) : Icons.lock({ size: 14 })}<span><span className="cap-name">{words(k.replace(/([A-Z])/g, " $1"))}</span>{c.supported === true ? "" : c.supported === "partial" ? " · partial" : " · not available"}<span className="cap-note">{c.note}</span></span></div>
        ))}
      </div>
      <p className="t4" style={{ fontSize: 11 }}>Hatched cells are reserved for the interruptible-agent runtime (fast/slow path, interruption, supersession, recovery, re-planning). They render only what the engine reports.</p>
    </div>
  );
}

function AgentConsole({ entries, runtime }) {
  const [draft, setDraft] = useState("");
  const supported = runtime.capabilities.operatorInstructions.supported;
  return (
    <Section label="Activity & operator console" meta={`${entries.length} entries`}>
      <div className="console">
        <div className="console-log">
          {entries.length ? entries.map((e) => (
            <Inspectable key={e.id} id={e.artifactId} className={`console-line ${e.lane === "advisory" ? "is-advisory" : e.lane === "trusted" ? "is-human" : ""}`}>
              <time className="mono">{clock(e.at)}</time>
              <span><span className="t1">{e.title}</span>{e.detail ? <span className="t3"> — {e.detail}</span> : null}</span>
            </Inspectable>
          )) : <span className="t3">No activity recorded for this incident yet.</span>}
        </div>
        <form className="console-form" onSubmit={(e) => e.preventDefault()}>
          <textarea className="input" rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={supported ? "Instruct the agent…" : "Operator instructions are not connected to a runtime yet."} disabled={!supported} aria-label="Operator instruction" />
          <Btn primary type="submit" disabled={!supported || !draft.trim()}>{Icons.next({})} Send</Btn>
        </form>
        {!supported ? <div className="note-box note-warn">{Icons.info({})}<span>{runtime.capabilities.operatorInstructions.note} This composer is the boundary the Samsung PRISM interruptible-agent runtime will connect to; it never fabricates a response.</span></div> : null}
      </div>
    </Section>
  );
}
