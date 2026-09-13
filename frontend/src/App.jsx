import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useEngine } from "./useEngine.js";
import { ClassIcon, ShieldMark, money0, pct, STATUS_ORDER } from "./lib.jsx";

const FLOW = ["OPEN", "INVESTIGATING", "AWAITING_EVIDENCE", "DIAGNOSIS_VALIDATED", "PLANNING", "INTERVENTION_VALIDATED", "AWAITING_APPROVAL", "READY", "EXECUTING", "OBSERVING", "CLOSED"];
const FLOW_LABELS = { OPEN: "Signal", INVESTIGATING: "Investigate", AWAITING_EVIDENCE: "Evidence", DIAGNOSIS_VALIDATED: "Diagnosis", PLANNING: "Plan", INTERVENTION_VALIDATED: "Validated", AWAITING_APPROVAL: "Approval", READY: "Ready", EXECUTING: "Execute", OBSERVING: "Observe", CLOSED: "Recovered" };
const SERIES = ["#ff5d73", "#f6b94a", "#748ffc", "#30c7d2", "#31d6a0", "#b478f2"];

export default function App() {
  const { state, approve, reject, reset, stop, resume, startDemo } = useEngine();
  const alerts = useMemo(() => Object.values(state.alerts).sort((a, b) => (a.triage_rank || 99) - (b.triage_rank || 99)), [state.alerts]);
  const [selected, setSelected] = useState(null);
  const active = alerts.filter((a) => !["CLOSED", "FAILED", "CANCELLED"].includes(a.lifecycle?.phase || a.status));
  const focusId = selected || active[0]?.equipment_id || alerts[0]?.equipment_id || state.fleet[0]?.equipment_id;
  const incident = alerts.find((a) => a.equipment_id === focusId) || null;
  return <div className="app-shell">
    <Header state={state} onReset={() => { setSelected(null); reset(); }} onStop={stop} onResume={resume}
      onDemo={() => { const target = focusId || "AC-COMP-01"; setSelected(target); startDemo(target); }} />
    <ImpactBar state={state} alerts={alerts} />
    {state.action.error && <div className="action-error">Action refused: {state.action.error}</div>}
    <main className="workspace">
      <aside className="overview-stack"><FleetPanel fleet={state.fleet} selected={focusId} onSelect={setSelected} /><RiskChart state={state} focusId={focusId} /></aside>
      <section className="command-stack"><IncidentQueue alerts={alerts} selected={focusId} onSelect={setSelected} />
        {incident ? <IncidentCommand incident={incident} state={state} approve={approve} reject={reject} /> : <EmptyCommand threshold={state.triggerThreshold} />}
      </section>
    </main>
  </div>;
}

function Header({ state, onReset, onStop, onResume, onDemo }) {
  const mins = state.plantMin % 60, hours = Math.floor(state.plantMin / 60);
  const provenance = state.reasoningProvenance || {}, agentcore = provenance.backend === "agentcore";
  return <header className="topbar">
    <div className="brand"><span className="brand-mark"><ShieldMark /></span><span><b>{state.meta.appName || "Operon"}</b><small>Industrial reliability command</small></span></div>
    <div className="authority-banner"><span className="agent-side">AGENTS REASON</span><i /><span className="authority-side">APPLICATION OWNS AUTHORITY</span></div><div className="top-spacer" />
    {state.demoScenario.active ? <div className="provenance"><span className="hot">Guided demo</span><i>·</i><span>typed advisory</span><i>·</i><span>simulated plant</span><em className="standby">{state.demoScenario.status?.replaceAll("_", " ")}</em></div>
      : <div className="provenance"><span>Operon</span><i>→</i><span className={agentcore ? "hot" : "muted"}>AgentCore</span><i>→</i><span>Strands</span><i>→</i><span className={provenance.model_provider ? "hot" : "muted"}>Bedrock</span><em className={provenance.status === "available" ? "online" : "standby"}>{provenance.status === "available" ? "connected" : "local ready"}</em></div>}
    <span className={`stream ${state.connected && state.running ? "online" : "standby"}`}><i />{!state.connected ? "reconnecting" : state.running ? "live" : "paused"}</span>
    <span className="plant-clock">+{String(hours).padStart(2, "0")}:{String(mins).padStart(2, "0")}</span>
    <button className="icon-btn" onClick={state.running ? onStop : onResume}>{state.running ? "Ⅱ" : "▶"}</button>
    <button className="text-btn" disabled={!!state.action.pending} onClick={onDemo}>{state.demoScenario.active ? "Restart guided demo" : "Start guided demo"}</button>
    <button className="text-btn" onClick={onReset}>Reset</button>
  </header>;
}

function ImpactBar({ state, alerts }) {
  const biz = state.business || {}, critical = state.fleet.filter((a) => a.status === "CRITICAL").length;
  const investigating = alerts.filter((a) => ["OPEN", "INVESTIGATING", "AWAITING_EVIDENCE"].includes(a.lifecycle?.phase)).length;
  const observing = alerts.filter((a) => a.lifecycle?.phase === "OBSERVING").length;
  return <div className="impact-bar">
    <div><small>Factory</small><b>{state.fleet.length || "—"} assets</b><span>{critical} critical</span></div>
    <div><small>Active response</small><b>{investigating} investigating</b><span>{observing} observing</span></div>
    <div><small>Value verified</small><b>{money0(biz.recovered_value || 0)}</b><span>{biz.events_prevented || 0} recovered events</span></div>
    <div><small>Net impact</small><b className={(biz.net_value || 0) < 0 ? "negative" : "positive"}>{money0(biz.net_value || 0)}</b><span>configured economics</span></div>
    <div><small>Line OEE</small><b>{pct(biz.oee_baseline || 0)}</b><div className="microbar"><i style={{ width: `${(biz.oee_baseline || 0) * 100}%` }} /></div></div>
  </div>;
}

function FleetPanel({ fleet, selected, onSelect }) {
  const sorted = [...fleet].sort((a, b) => (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || b.failure_prob - a.failure_prob);
  return <Panel title="Factory overview" meta="8-machine simulated floor"><div className="fleet-grid">{sorted.map((asset) => <AssetCard key={asset.equipment_id} asset={asset} selected={selected === asset.equipment_id} onClick={() => onSelect(asset.equipment_id)} />)}</div></Panel>;
}

function AssetCard({ asset, selected, onClick }) {
  return <button className={`asset-card ${asset.status.toLowerCase()} ${selected ? "selected" : ""}`} onClick={onClick}>
    <div className="asset-top"><span className="asset-icon"><ClassIcon cls={asset.equipment_class} /></span><span className="asset-name"><b>{asset.equipment_id}</b><small>{asset.name}</small></span><Status value={asset.status}>{asset.status}</Status></div>
    <div className="risk-row"><b>{pct(asset.failure_prob)}</b><span>24h risk</span></div><div className="asset-mode">{asset.predicted_mode && asset.predicted_mode !== "NONE" ? asset.predicted_mode_label : "Nominal signature"}</div><Spark point={asset.point} status={asset.status} />
  </button>;
}

function Spark({ point, status }) {
  const history = useRef([]); if (point) history.current = [...history.current, point.prob].slice(-26);
  const color = { CRITICAL: "#ff5d73", WARNING: "#f6b94a", SCHEDULED: "#67a5ff", HEALTHY: "#31d6a0", DOWN: "#7b849a" }[status];
  return <div className="spark"><ResponsiveContainer><AreaChart data={history.current.map((p, i) => ({ i, p }))}><YAxis hide domain={[0, 1]} /><Area dataKey="p" type="monotone" stroke={color} fill={color} fillOpacity={0.08} strokeWidth={1.5} dot={false} isAnimationActive={false} /></AreaChart></ResponsiveContainer></div>;
}

function RiskChart({ state, focusId }) {
  const ids = useMemo(() => { const value = new Set(state.fleet.filter((a) => a.status !== "HEALTHY").map((a) => a.equipment_id)); if (focusId) value.add(focusId); return [...value].slice(0, 6); }, [state.fleet, focusId]);
  const data = useMemo(() => { const times = new Map(); ids.forEach((id) => (state.histories[id] || []).forEach((point) => { if (!times.has(point.t)) times.set(point.t, { t: point.t }); times.get(point.t)[id] = point.prob; })); return [...times.values()].sort((a, b) => a.t - b.t).slice(-70); }, [ids, state.histories]);
  return <Panel title="Predictive signal" meta={`action gate ${pct(state.triggerThreshold)}`}><div className="risk-chart"><ResponsiveContainer><LineChart data={data} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}><CartesianGrid vertical={false} stroke="rgba(139,158,191,.09)" /><ReferenceArea y1={state.triggerThreshold} y2={1} fill="rgba(255,93,115,.06)" /><XAxis dataKey="t" tick={{ fill: "#67748b", fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={28} /><YAxis domain={[0, 1]} tickFormatter={(v) => Math.round(v * 100)} tick={{ fill: "#67748b", fontSize: 10 }} axisLine={false} tickLine={false} /><ReferenceLine y={state.triggerThreshold} stroke="#ff5d73" strokeDasharray="4 4" /><Tooltip formatter={(value) => pct(value)} contentStyle={{ background: "#101722", border: "1px solid #2a3547", borderRadius: 8 }} />{ids.map((id, i) => <Line key={id} dataKey={id} type="monotone" stroke={SERIES[i]} strokeWidth={focusId === id ? 2.4 : 1.4} strokeOpacity={focusId && focusId !== id ? .3 : 1} dot={false} connectNulls isAnimationActive={false} />)}</LineChart></ResponsiveContainer></div><div className="chart-legend">{ids.map((id, i) => <span key={id}><i style={{ background: SERIES[i] }} />{id}</span>)}</div></Panel>;
}

function IncidentQueue({ alerts, selected, onSelect }) {
  if (!alerts.length) return null;
  return <div className="incident-queue">{alerts.map((item) => <button key={item.incident_id} className={selected === item.equipment_id ? "selected" : ""} onClick={() => onSelect(item.equipment_id)}><span className={`phase-dot ${tone(item.lifecycle?.phase)}`} /><span><b>{item.equipment_id}</b><small>{item.lifecycle?.phase || item.status}</small></span><em>{pct(item.failure_prob)}</em></button>)}</div>;
}

function IncidentCommand({ incident, state, approve, reject }) {
  const lifecycle = incident.lifecycle || {}, view = lifecycle.read_model || {}, phase = lifecycle.phase || "OPEN";
  return <motion.div key={incident.incident_id} className="incident-command" initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}>
    <div className="incident-hero"><div><span className="eyebrow">Incident command center</span><h1>{incident.equipment_name}</h1><p><CopyId value={incident.incident_id} /> · {incident.equipment_id} · revision {lifecycle.revision}</p></div><div className="hero-risk"><small>24h failure risk</small><b>{pct(incident.failure_prob)}</b><span>{incident.predicted_mode_label || "Predictive anomaly"}</span></div><Status value={phase}>{phase.replaceAll("_", " ")}</Status></div>
    <Lifecycle phase={phase} events={view.events || []} /><Invariant />
    <div className="command-grid"><div className="command-column"><DiagnosisCard incident={incident} view={view} /><EvidenceCard evidence={view.evidence || []} /><AgentCard view={view} lifecycle={lifecycle} provenance={state.reasoningProvenance} /></div><div className="command-column"><InterventionCard incident={incident} view={view} /><ApprovalCard incident={incident} view={view} approve={approve} reject={reject} pending={state.action.pending} /><OutcomeCard incident={incident} view={view} /><EventCard events={view.events || []} /></div></div>
  </motion.div>;
}

function Lifecycle({ phase, events }) {
  const reached = new Set(events.filter((event) => event.event_type === "PHASE_CHANGED").map((event) => event.payload?.to).filter(Boolean)); reached.add("OPEN"); reached.add(phase);
  const currentIndex = FLOW.indexOf(phase), exceptional = ["ESCALATED", "EXECUTION_FAILED", "CANCELLED"].includes(phase);
  return <section className="lifecycle-block"><div className="section-title"><span>Authoritative lifecycle</span><small>committed application state</small></div><div className="lifecycle-flow">{FLOW.map((step, i) => { const done = reached.has(step) || (!exceptional && currentIndex >= 0 && i < currentIndex); return <div key={step} className={`${done ? "done" : ""} ${phase === step ? "current" : ""}`}><i>{done ? "✓" : i + 1}</i><span>{FLOW_LABELS[step]}</span></div>; })}{exceptional && <div className="exception current"><i>!</i><span>{phase.replaceAll("_", " ")}</span></div>}</div></section>;
}

function Invariant() { return <div className="invariant"><span>Prediction</span><i>≠</i><span>Diagnosis</span><i>≠</i><span>Intervention</span><i>≠</i><span>Approval</span><i>≠</i><span>Execution</span><i>≠</i><span>Outcome</span></div>; }

function DiagnosisCard({ incident, view }) {
  const diagnosis = view.diagnosis, verdict = [...(view.verdicts || [])].reverse().find((item) => item.target_kind === "diagnosis"), signal = (view.evidence || []).find((item) => item.kind === "model_signal");
  return <Card title="Evidence → diagnosis" icon="◎" meta={diagnosis ? "application validated" : "investigation active"}><div className="signal-box"><div><small>Predictive signal</small><b>{incident.predicted_mode_label || "Elevated failure risk"}</b></div><Status value="signal">prediction, not cause</Status></div>
    {signal?.payload?.attribution?.length > 0 && <div className="drivers">{signal.payload.attribution.slice(0, 3).map((item) => <span key={item.feature}><b>{item.label || item.feature}</b> {Number(item.value).toFixed(1)} <em>+{Number(item.contribution).toFixed(2)}</em></span>)}</div>}
    {diagnosis ? <div className="diagnosis"><span className="validated-mark">✓</span><div><small>Validated diagnosis</small><h3>{diagnosis.conclusion}</h3><p>{diagnosis.evidence_ids.length} cited evidence records · confidence {diagnosis.confidence == null ? "not asserted" : pct(diagnosis.confidence)}</p></div></div> : <EmptyLine text="No diagnosis has crossed the application validation boundary." />}{verdict && <Verdict item={verdict} />}</Card>;
}

function EvidenceCard({ evidence }) {
  const [expanded, setExpanded] = useState(false), items = [...evidence].reverse();
  return <Card title="Evidence ledger" icon="▤" meta={`${evidence.length} durable records`}><div className="evidence-list">{items.slice(0, expanded ? 12 : 5).map((item) => <div key={item.id} className="evidence-row"><span className={`source-mark ${item.provenance?.toLowerCase()}`}>{item.kind === "model_signal" ? "◆" : "●"}</span><div><b>{item.kind.replaceAll("_", " ")}</b><p>{item.summary}</p><small>{item.source_system} · {item.provenance} · {item.quality}</small></div><CopyId value={item.id} short /></div>)}</div>{items.length > 5 && <button className="inline-btn" onClick={() => setExpanded(!expanded)}>{expanded ? "Show less" : `Show ${items.length - 5} more`}</button>}</Card>;
}

function AgentCard({ view, lifecycle, provenance }) {
  const runs = view.agent_runs || [], run = runs[runs.length - 1], assessments = run?.assessments || [], delegations = run?.delegations || [], baseline = (view.agent_actions || []).filter((item) => item.actor === "operon.investigation");
  return <Card title="Strands agent activity" icon="✦" meta={run ? `${run.status} · ${run.tool_calls} tool calls` : "awaiting reasoning runtime"}><div className="agent-boundary"><span>Advisory reasoning</span><i>cannot transition lifecycle</i></div>{run ? <><div className="run-strip"><span><small>Run ID</small><CopyId value={run.run_id} /></span><span><small>Stage</small><b>{run.stage}</b></span><span><small>Backend</small><b>{run.runtime_identity?.backend || provenance?.backend || "local"}</b></span></div>{run.summary && <p className="run-summary">{run.summary}</p>}<div className="agent-list"><AgentLine name="Reliability Supervisor" role="supervisor" status={run.status} text={run.disposition} />{delegations.map((item) => <AgentLine key={item.key} name={roleName(item.role)} role={item.role} status={item.status} text={item.question} />)}{assessments.filter((item) => !delegations.some((d) => d.key === item.key)).map((item) => <AgentLine key={item.key} name={roleName(inferRole(item.assessment))} role={inferRole(item.assessment)} status="SUCCEEDED" text={item.assessment.reasoning_summary} />)}</div>{run.blockers?.length > 0 && <ul className="blockers">{run.blockers.map((item) => <li key={item}>{item}</li>)}</ul>}</> : <>{baseline.map((item) => <AgentLine key={item.id} name="Application Investigator" role="system" status={item.status} text={item.summary} />)}<EmptyLine text={lifecycle.supervisor_available ? "Supervisor run will appear here." : "Durable evidence is ready; reasoning runtime is not connected."} /></>}</Card>;
}

function AgentLine({ name, role, status, text }) { return <div className="agent-line"><span className={`agent-avatar ${role}`}>{role === "supervisor" ? "S" : role?.[0]?.toUpperCase() || "A"}</span><div><b>{name}</b><p>{text || "Structured report recorded"}</p></div><Status value={status}>{status}</Status></div>; }

function InterventionCard({ incident, view }) {
  const item = view.intervention, binding = view.binding, verdict = [...(view.verdicts || [])].reverse().find((entry) => entry.target_kind === "intervention");
  return <Card title="Proposed intervention" icon="⌁" meta={item?.status || "not proposed"}>{item ? <><div className="plan-head"><div><small>Typed maintenance action</small><h3>{item.steps[0]?.parameters?.description || item.steps[0]?.capability?.replaceAll("_", " ")}</h3></div><Status value={item.risk}>{item.risk} risk</Status></div><div className="plan-grid"><KV label="Capability" value={item.steps[0]?.capability} /><KV label="Technician" value={binding?.technician_id} /><KV label="Estimated cost" value={money0(item.estimated_cost)} /><KV label="Downtime" value={`${item.estimated_downtime_minutes} min`} /><KV label="Window" value={formatWindow(item.window_start, item.window_end)} /><KV label="Avoided loss" value={money0(item.estimated_avoided_loss)} /></div>{binding?.parts?.length > 0 && <div className="parts"><small>Reserved parts</small>{binding.parts.map((part) => <span key={part.part_id}>{part.quantity}× {part.part_id}</span>)}</div>}{verdict && <Verdict item={verdict} />}</> : <EmptyLine text={incident.lifecycle?.phase === "DIAGNOSIS_VALIDATED" ? "Diagnosis accepted. Maintenance planning is next." : "No intervention has been promoted."} />}</Card>;
}

function ApprovalCard({ incident, view, approve, reject, pending }) {
  const phase = incident.lifecycle?.phase, current = [...(view.requirements || [])].reverse()[0], decision = [...(view.approval_decisions || [])].reverse()[0], canApprove = phase === "AWAITING_APPROVAL" && incident.lifecycle?.requirement_id;
  if (!current && !canApprove) return <Card title="Governance & approval" icon="◇" meta="application gate"><EmptyLine text="No approval requirement has been issued." /></Card>;
  return <Card title="Governance & approval" icon="◇" meta={current?.policy_version || "policy evaluated"} accent={canApprove ? "approval" : ""}><div className="governance-result"><span className="shield-small">◆</span><div><small>Application policy result</small><b>{canApprove ? "Human approval required" : current?.status || "Evaluated"}</b><p>{(current?.conditions || []).join(" · ") || "Exact promoted work package binding enforced."}</p></div></div>{current && <div className="binding-strip"><span>Bound to</span><CopyId value={current.intervention_id} short /><span>hash</span><CopyId value={current.intervention_hash} short /></div>}{canApprove && <div className="approval-actions"><button disabled={!!pending} onClick={() => approve(incident)}>Approve exact plan & dispatch</button><button disabled={!!pending} className="reject" onClick={() => reject(incident)}>Reject</button></div>}{decision && <div className={`decision ${decision.decision.toLowerCase()}`}><b>{decision.decision}</b><span>{decision.actor_role} · {decision.actor_id}</span><small>bound to the viewed intervention hash</small></div>}</Card>;
}

function OutcomeCard({ incident, view }) {
  const receipts = view.execution_receipts || [], receipt = receipts[receipts.length - 1], plans = view.observation_plans || [], plan = plans[plans.length - 1], outcomes = view.outcomes || [], outcome = outcomes[outcomes.length - 1], phase = incident.lifecycle?.phase;
  return <Card title="Execution & outcome" icon="◉" meta="deterministic verification"><div className="outcome-flow"><div className={receipt ? "done" : ""}><i>{receipt ? "✓" : "1"}</i><span><b>Execution</b><small>{receipt?.status || "not dispatched"}</small></span></div><em>→</em><div className={plan ? "active" : ""}><i>{plan ? "◌" : "2"}</i><span><b>Observe</b><small>{plan ? "post-maintenance telemetry" : "not started"}</small></span></div><em>→</em><div className={outcome ? "done" : ""}><i>{outcome ? "✓" : "3"}</i><span><b>Verify</b><small>{outcome?.result || "not established"}</small></span></div></div>{receipt && <div className="receipt"><span><small>Execution receipt</small><CopyId value={receipt.id} /></span><Status value={receipt.status}>{receipt.status}</Status><p>{Object.entries(receipt.external_ids || {}).map(([key, value]) => `${key}: ${value}`).join(" · ") || receipt.adapter}</p></div>}{phase === "OBSERVING" && !outcome && <div className="observing-callout"><span className="pulse-ring" /><div><b>Execution confirmed — recovery not yet established</b><p>Operon is evaluating telemetry after the frozen observation boundary.</p></div></div>}{outcome && <div className={`outcome-result ${tone(outcome.result)}`}><b>{outcome.result.replaceAll("_", " ")}</b><p>{outcome.reason}</p><div>{Object.entries(outcome.before_metrics || {}).slice(0, 3).map(([key, value]) => <span key={`b-${key}`}>{key}: {Number(value).toFixed(2)} before</span>)}{Object.entries(outcome.after_metrics || {}).slice(0, 3).map(([key, value]) => <span key={`a-${key}`}>{key}: {Number(value).toFixed(2)} after</span>)}</div></div>}{!receipt && <EmptyLine text="No governed execution receipt exists." />}</Card>;
}

function EventCard({ events }) { return <Card title="Application activity" icon="⋮" meta={`${events.length} committed events`}><div className="event-list">{[...events].reverse().slice(0, 8).map((event) => <div key={event.id}><i className={tone(event.event_type)} /><span><b>{event.event_type.replaceAll("_", " ")}</b><small>revision {event.revision} · {relativeTime(event.created_at)}</small></span></div>)}</div></Card>; }
function EmptyCommand({ threshold }) { return <div className="empty-command"><ShieldMark /><h2>Operon is monitoring the factory</h2><p>A predictive signal at {pct(threshold)} opens a durable incident. Every step after that is evidence-bound and independently governed.</p><Invariant /><div className="empty-pipeline">Telemetry → predictive signal → incident → investigation → human-governed action → observed outcome</div></div>; }
function Panel({ title, meta, children }) { return <section className="panel"><div className="panel-title"><h2>{title}</h2><span>{meta}</span></div>{children}</section>; }
function Card({ title, icon, meta, accent = "", children }) { return <section className={`detail-card ${accent}`}><div className="card-title"><span>{icon}</span><h2>{title}</h2><small>{meta}</small></div>{children}</section>; }
function Status({ value, children }) { return <span className={`status ${tone(value)}`}>{children}</span>; }
function KV({ label, value }) { return <div className="kv"><small>{label}</small><b>{value || "Not recorded"}</b></div>; }
function EmptyLine({ text }) { return <div className="empty-line"><i />{text}</div>; }
function CopyId({ value, short = false }) { if (!value) return <span>—</span>; return <code title={value}>{short ? `${value.slice(0, 7)}…` : value.length > 22 ? `${value.slice(0, 12)}…${value.slice(-5)}` : value}</code>; }
function Verdict({ item }) { return <div className={`verdict ${tone(item.decision)}`}><b>{item.decision === "ACCEPT" ? "✓ Critic + application validation passed" : item.decision}</b>{(item.blocking_issues || []).length > 0 && <p>{item.blocking_issues.join(" · ")}</p>}<small>{item.validation_policy_version || "validation policy"}</small></div>; }
function tone(value = "") { const v = String(value).toUpperCase(); if (["HEALTHY", "CLOSED", "CONFIRMED", "ACCEPT", "APPROVE", "APPROVED", "SUCCEEDED", "VERIFIED_RECOVERY", "READY"].includes(v)) return "good"; if (["WARNING", "AWAITING_APPROVAL", "AWAITING_EVIDENCE", "OBSERVING", "PENDING", "CONDITIONS", "SIGNAL"].includes(v)) return "warn"; if (["CRITICAL", "ESCALATED", "EXECUTION_FAILED", "FAILED", "REJECT", "REJECTED", "REGRESSED", "NOT_RECOVERED", "ERROR"].includes(v)) return "bad"; if (v.includes("CLOSED") || v.includes("OUTCOME_RECORDED")) return "good"; if (v.includes("EXECUTION") || v.includes("APPROVAL")) return "warn"; return "info"; }
function roleName(role) { return ({ diagnostic: "Diagnostic Specialist", engineering: "Engineering Specialist", operations: "Operations Specialist", critic: "Critic / Validator", planner: "Maintenance Planner", supervisor: "Reliability Supervisor" })[role] || "Specialist"; }
function inferRole(value = {}) { if ("competing_hypotheses" in value) return "diagnostic"; if ("intervention_feasibility" in value) return "engineering"; if ("resource_feasibility" in value) return "operations"; if ("recommendation" in value) return "critic"; if ("proposed_steps" in value) return "planner"; return "agent"; }
function formatWindow(start, end) { if (!start) return null; const fmt = (v) => new Date(v).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); return `${fmt(start)} – ${fmt(end)}`; }
function relativeTime(value) { return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""; }
