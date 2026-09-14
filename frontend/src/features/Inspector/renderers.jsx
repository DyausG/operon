// Typed presentation for artifact payloads. Raw JSON is never the primary view.
import { ArtifactChip, KV, Stamp, Tag, IdToken, Dot } from "../../primitives/index.jsx";
import { clock, dateTime, isIsoDate, looksLikeId, money0, num, title, windowLabel, words } from "../../lib/format.js";

/* ---------- generic structured renderer ---------- */
const HIDE = new Set(["id", "artifact_id", "created_at", "updated_at", "provenance", "runtime", "live_model", "summary", "status", "title"]);
const isPrim = (v) => v == null || ["string", "number", "boolean"].includes(typeof v);

export function Value({ v, k }) {
  if (v == null || v === "") return <span className="t4">—</span>;
  if (typeof v === "boolean") return <span className="mono">{String(v)}</span>;
  if (typeof v === "number") return <span className="mono">{Number.isInteger(v) ? v : num(v, 2)}</span>;
  if (typeof v === "string") {
    if (isIsoDate(v)) return <span className="mono" title={v}>{dateTime(v)}</span>;
    if (looksLikeId(v) && k !== "id") return <ArtifactChip id={v} />;
    if (/^[0-9a-f]{64}$/.test(v)) return <IdToken value={v} hash />;
    return <span>{v}</span>;
  }
  if (Array.isArray(v)) {
    if (!v.length) return <span className="t4">none</span>;
    if (v.every((x) => typeof x === "string" && looksLikeId(x))) return <div className="chips">{v.map((id) => <ArtifactChip key={id} id={id} />)}</div>;
    if (v.every((x) => typeof x === "number")) return <span className="mono series">{v.map((n) => num(n, 1)).join("  ")}</span>;
    if (v.every(isPrim)) return <ul className="plain">{v.map((x, i) => <li key={i}><Value v={x} /></li>)}</ul>;
    if (v.every((x) => x && typeof x === "object" && !Array.isArray(x))) {
      const keys = [...new Set(v.flatMap((o) => Object.keys(o)))].filter((kk) => !HIDE.has(kk) || kk === "status");
      if (keys.length <= 6 && v.every((o) => Object.values(o).every(isPrim))) {
        return <table className="tbl tbl-mini"><thead><tr>{keys.map((kk) => <th key={kk}>{words(kk)}</th>)}</tr></thead><tbody>{v.map((o, i) => <tr key={i}>{keys.map((kk) => <td key={kk}><Value v={o[kk]} k={kk} /></td>)}</tr>)}</tbody></table>;
      }
      return <div className="nested">{v.map((o, i) => <div key={i} className="nested-item"><Structured data={o} /></div>)}</div>;
    }
    return <pre className="raw-inline">{JSON.stringify(v, null, 1)}</pre>;
  }
  if (typeof v === "object") return <div className="nested"><Structured data={v} /></div>;
  return <span>{String(v)}</span>;
}

export function Structured({ data, omit = HIDE }) {
  if (!data || typeof data !== "object") return <Value v={data} />;
  const entries = Object.entries(data).filter(([k]) => !omit.has(k));
  if (!entries.length) return <span className="t4">No structured fields.</span>;
  return (
    <dl className="struct">
      {entries.map(([k, v]) => <div key={k} className={`struct-row ${isPrim(v) || (Array.isArray(v) && v.every(isPrim) && v.length < 4) ? "" : "struct-wide"}`}><dt className="lbl">{words(k)}</dt><dd><Value v={v} k={k} /></dd></div>)}
    </dl>
  );
}

/* ---------- typed renderers ---------- */
const Head = ({ children }) => <div className="r-head">{children}</div>;
const Grid = ({ n = 3, children }) => <div className={`kvgrid kvgrid-${n}`}>{children}</div>;
const Refs = ({ label, ids }) => (ids && ids.length ? <div className="r-refs"><span className="lbl">{label}</span><div className="chips">{ids.map((id) => <ArtifactChip key={id} id={id} />)}</div></div> : null);
const Rest = ({ payload, used }) => { const rest = Object.fromEntries(Object.entries(payload || {}).filter(([k]) => !used.has(k) && !HIDE.has(k))); return Object.keys(rest).length ? <details className="r-rest"><summary className="lbl">Other fields ({Object.keys(rest).length})</summary><Structured data={rest} /></details> : null; };
const used = (...k) => new Set(k);

function PredictiveSignal({ a }) {
  const p = a.payload || {}, inner = p.payload || {};
  const attribution = inner.attribution || [];
  const max = Math.max(...attribution.map((x) => Math.abs(x.contribution || 0)), 0.0001);
  return (
    <>
      <Grid n={4}><KV label="Failure probability" mono value={num(inner.failure_probability, 2)} /><KV label="Threshold" mono value={num(inner.threshold, 2)} /><KV label="Source" value={p.source_system} /><KV label="Quality" value={words(p.quality)} /></Grid>
      {attribution.length ? <div className="drivers"><span className="lbl">Attribution</span>{attribution.map((x) => <div key={x.feature} className="driver"><span className="driver-l">{x.label || x.feature}</span><span className="driver-bar"><i style={{ width: `${(Math.abs(x.contribution || 0) / max) * 100}%` }} /></span><span className="driver-v mono">{num(x.value, 1)}</span><span className="driver-c mono">+{num(x.contribution, 2)}</span></div>)}</div> : null}
      <Rest payload={{ ...p, ...inner }} used={used("payload", "attribution", "failure_probability", "threshold", "source_system", "quality", "kind", "source_capability", "live_model")} />
    </>
  );
}
function Evidence({ a }) {
  const p = a.payload || {}, inner = p.payload || {};
  const series = Object.entries(inner).filter(([, v]) => Array.isArray(v) && v.every((n) => typeof n === "number") && v.length > 1);
  return (
    <>
      <Grid n={4}><KV label="Kind" value={words(p.kind)} /><KV label="Source system" value={p.source_system} /><KV label="Capability" mono value={p.source_capability} /><KV label="Quality">{p.quality ? <Tag hatched={String(p.quality).includes("SIMULATED")}>{words(p.quality)}</Tag> : "—"}</KV></Grid>
      {series.length ? <div className="r-series">{series.map(([k, v]) => <MiniSeries key={k} label={words(k)} values={v} />)}</div> : null}
      <Structured data={Object.fromEntries(Object.entries(inner).filter(([k]) => !series.some(([s]) => s === k)))} />
      <Refs label="Supports" ids={a.supporting_ids} />
      <Rest payload={p} used={used("payload", "kind", "source_system", "source_capability", "quality", "actor_id")} />
    </>
  );
}
function MiniSeries({ label, values }) {
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 200},${28 - ((v - min) / span) * 24}`).join(" ");
  return (
    <div className="mini"><span className="lbl">{label}</span><svg viewBox="0 0 200 30" className="mini-svg" preserveAspectRatio="none"><polyline fill="none" stroke="var(--text-2)" strokeWidth="1.5" points={pts} />{values.map((v, i) => <rect key={i} x={(i / (values.length - 1)) * 200 - 2} y={28 - ((v - min) / span) * 24 - 2} width="4" height="4" fill="var(--surface-1)" stroke="var(--text-2)" />)}</svg><span className="mono t3 mini-v">{values.map((v) => num(v, 1)).join(" · ")}</span></div>
  );
}
function Inspection({ a }) {
  const p = a.payload || {}, inner = p.payload || {};
  return (
    <>
      <Grid n={4}><KV label="Actor" mono value={p.actor_id} /><KV label="Result" value={words(inner.inspection_result || a.status)} /><KV label="Quality">{p.quality ? <Tag hatched={String(p.quality).includes("SIMULATED")}>{words(p.quality)}</Tag> : "—"}</KV><KV label="Source" value={p.source_system} /></Grid>
      {inner.finding ? <p className="r-body">{inner.finding}</p> : null}
      <Structured data={inner} omit={new Set(["finding", "inspection_result"])} />
      <Refs label="Corroborates" ids={a.supporting_ids} />
      <Rest payload={p} used={used("payload", "actor_id", "quality", "source_system", "kind", "source_capability")} />
    </>
  );
}
function Advisory({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Head><Tag tone="adv" dashed>Advisory · structured output</Tag><span className="t3">Chain of thought is never shown.</span></Head>
      <Grid n={3}><KV label="Role" value={title(p.specialist_role || p.role)} /><KV label="Stage" value={words(p.stage)} /><KV label="Status"><span className="mono t2"><Dot tone="adv" dashed /> {words(p.status || a.status)}</span></KV></Grid>
      {p.short_conclusion ? <p className="r-body">{p.short_conclusion}</p> : null}
      {(p.structured_findings || []).length ? <div className="r-list"><span className="lbl">Findings</span>{p.structured_findings.map((f, i) => <div key={i} className="r-item"><Tag tone="adv" dashed>{words(f.severity)}</Tag><span>{f.finding}</span></div>)}</div> : null}
      {(p.recommendations || []).length ? <div className="r-list"><span className="lbl">Recommendations</span>{p.recommendations.map((r, i) => <div key={i} className="r-item">{r}</div>)}</div> : null}
      <Refs label="Evidence consumed" ids={p.evidence_references || p.evidence_ids} />
      {p.intervention_id ? <Refs label="Reviews" ids={[p.intervention_id]} /> : null}
      <Rest payload={p} used={used("specialist_role", "role", "stage", "short_conclusion", "structured_findings", "recommendations", "evidence_references", "evidence_ids", "intervention_id", "key", "question", "advisory_id", "incident_id")} />
    </>
  );
}
function Activity({ a }) {
  const p = a.payload || {};
  const rt = p.runtime_identity || {};
  return (
    <>
      <Head><Tag tone="adv" dashed>Advisory run</Tag>{rt.provenance ? <Tag hatched={rt.provenance === "SIMULATED"}>{rt.provenance} · {rt.runtime || rt.backend}</Tag> : null}</Head>
      <Grid n={4}><KV label="Stage" value={words(p.stage)} /><KV label="Disposition" value={words(p.disposition)} /><KV label="Structured outputs" mono value={p.tool_calls} /><KV label="Run" mono value={p.run_id} /></Grid>
      <Refs label="Delegations" ids={(p.delegations || []).map((d) => d.artifact_id).filter(Boolean)} />
      {(p.blockers || []).length ? <div className="r-list"><span className="lbl">Blockers</span>{p.blockers.map((b) => <div key={b} className="r-item t-warn">{b}</div>)}</div> : null}
      <Rest payload={p} used={used("stage", "disposition", "tool_calls", "run_id", "delegations", "blockers", "runtime_identity", "assessments")} />
    </>
  );
}
function Diagnosis({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Grid n={4}><KV label="Likely failure mode" value={p.likely_failure_mode || p.failure_mode_code} /><KV label="Affected component" value={p.affected_component} /><KV label="Confidence" mono value={p.confidence == null ? "not asserted" : num(p.confidence, 2)} /><KV label="Validation" value={words(p.validation_status || a.status)} /></Grid>
      {(p.key_observations || []).length ? <div className="r-list"><span className="lbl">Key observations</span>{p.key_observations.map((o) => <div key={o} className="r-item">{o}</div>)}</div> : null}
      <Refs label="Cited evidence" ids={p.evidence_ids} />
      <Refs label="Advisory inputs" ids={p.specialist_advisory_ids} />
      {p.validator_verdict_id ? <Refs label="Validated by" ids={[p.validator_verdict_id]} /> : null}
      <Rest payload={p} used={used("likely_failure_mode", "failure_mode_code", "affected_component", "confidence", "validation_status", "key_observations", "evidence_ids", "specialist_advisory_ids", "validator_verdict_id", "conclusion")} />
    </>
  );
}
function Verdict({ a }) {
  const p = a.payload || {};
  const ok = (p.decision || p.result) === "ACCEPT";
  return (
    <>
      <Head><Stamp tone={ok ? "auth" : "crit"}>{title(p.decision || p.result)}</Stamp><span className="mono t3">{p.validation_policy_version}</span></Head>
      {p.concise_justification ? <p className="r-body">{p.concise_justification}</p> : null}
      {p.validation_summary && p.validation_summary !== p.concise_justification ? <p className="r-body t3">{p.validation_summary}</p> : null}
      <Grid n={3}><KV label="Target" value={words(p.target_kind)} /><KV label="Blocking issues" value={(p.blocking_issues || []).length ? p.blocking_issues.join(" · ") : "none"} /><KV label="Policy" mono value={p.validation_policy_version} /></Grid>
      <Refs label="Subject" ids={[p.subject_artifact_id || p.target_id].filter(Boolean)} />
      <Rest payload={p} used={used("decision", "result", "concise_justification", "validation_summary", "target_kind", "blocking_issues", "validation_policy_version", "subject_artifact_id", "target_id")} />
    </>
  );
}
function Intervention({ a }) {
  const p = a.payload || {};
  const step = p.steps?.[0];
  return (
    <>
      <Grid n={4}><KV label="Priority" value={title(p.priority)} /><KV label="Risk" value={title(p.risk)} /><KV label="Component" value={p.component} /><KV label="Part" mono value={p.part_id} /><KV label="Window" mono value={windowLabel(p.window_start, p.window_end)} /><KV label="Cost" mono value={p.estimated_cost != null ? money0(p.estimated_cost) : null} /><KV label="Avoided loss" mono value={p.estimated_avoided_loss != null ? money0(p.estimated_avoided_loss) : null} /><KV label="Downtime" mono value={p.estimated_downtime_minutes != null ? `${p.estimated_downtime_minutes} min` : null} /></Grid>
      {step ? <div className="r-list"><span className="lbl">Steps</span>{p.steps.map((s, i) => <div key={i} className="r-item"><span className="mono t3">{words(s.capability)}</span><span>{s.parameters?.description || ""}{s.parameters?.safety ? <span className="t3"> · {s.parameters.safety}</span> : null}</span></div>)}</div> : null}
      {p.required_skill ? <KV label="Required skill" value={p.required_skill} /> : null}
      {p.operational_constraint ? <KV label="Operational constraint" value={p.operational_constraint} /> : null}
      {p.safety_note ? <KV label="Safety" value={p.safety_note} /> : null}
      <Refs label="Diagnosis" ids={[p.diagnosis_id].filter(Boolean)} />
      <Refs label="Reviews" ids={p.review_ids} />
      <Rest payload={p} used={used("priority", "risk", "component", "part_id", "window_start", "window_end", "estimated_cost", "estimated_avoided_loss", "estimated_downtime_minutes", "steps", "required_skill", "operational_constraint", "safety_note", "diagnosis_id", "review_ids")} />
    </>
  );
}
function WorkPackage({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Grid n={3}><KV label="Version" mono value={p.version} /><KV label="Plan hash" ><IdToken value={p.plan_hash} hash /></KV><KV label="Duration" mono value={p.duration_minutes != null ? `${p.duration_minutes} min` : null} /></Grid>
      {(p.instructions || []).length ? <div className="r-list"><span className="lbl">Instructions</span>{p.instructions.map((s, i) => <div key={i} className="r-item"><span className="mono t3">{i + 1}</span><span>{s}</span></div>)}</div> : null}
      {(p.safety_requirements || []).length ? <KV label="Safety requirements" value={p.safety_requirements.join(" · ")} /> : null}
      <Refs label="Intervention" ids={[p.intervention_id].filter(Boolean)} /><Refs label="Diagnosis" ids={[p.diagnosis_id].filter(Boolean)} />
      <Rest payload={p} used={used("version", "plan_hash", "duration_minutes", "instructions", "safety_requirements", "intervention_id", "diagnosis_id")} />
    </>
  );
}
function ApprovalRequest({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Head><Stamp tone={a.status === "PENDING" ? "pending" : "auth"}>{title(a.status)}</Stamp><span className="mono t3">{p.policy_version}</span></Head>
      <div className="bind"><span className="lbl">Intervention</span><IdToken value={p.intervention_id} full /><span className="lbl">Package</span><span className="mono t2">{p.work_package_id}{p.work_package_version ? ` · v${p.work_package_version}` : ""}</span><span className="lbl">Hash</span><IdToken value={p.intervention_hash} hash /><span className="lbl">Approvers</span><span className="mono t2">{p.minimum_distinct_approvers ?? "—"} minimum</span><span className="lbl">Requirement</span><IdToken value={p.requirement_id || a.id} full /><span className="lbl">Mode</span><span className="mono t2">{p.mode || "HUMAN"}</span></div>
      {(p.conditions || []).length ? <ul className="conds">{p.conditions.map((c) => <li key={c}>{c}</li>)}</ul> : null}
      <Rest payload={p} used={used("policy_version", "intervention_id", "work_package_id", "work_package_version", "intervention_hash", "minimum_distinct_approvers", "requirement_id", "mode", "conditions")} />
    </>
  );
}
function ApprovalBinding({ a }) {
  const p = a.payload || {};
  const ok = p.decision === "APPROVE";
  return (
    <>
      <Head><Stamp tone={ok ? "auth" : "crit"}>{ok ? "Approved" : "Rejected"}</Stamp><span className="t2">{p.actor_id} · {words(p.actor_role)}</span><span className="mono t3">{clock(p.approved_at || a.created_at)}</span></Head>
      {p.rationale ? <p className="r-body">{p.rationale}</p> : null}
      <div className="bind"><span className="lbl">Intervention</span><IdToken value={p.intervention_id} full /><span className="lbl">Package</span><span className="mono t2">{p.work_package_id}</span><span className="lbl">Hash</span><IdToken value={p.intervention_hash} hash /><span className="lbl">Plan version</span><span className="mono t2">{p.plan_version || p.context_revision}</span><span className="lbl">Request</span><IdToken value={p.approval_request_id || p.requirement_id} full /><span className="lbl">Decision</span><span className="mono t2">{p.decision}</span></div>
      <Rest payload={p} used={used("decision", "actor_id", "actor_role", "approved_at", "rationale", "intervention_id", "work_package_id", "intervention_hash", "plan_version", "approval_request_id", "requirement_id", "context_revision")} />
    </>
  );
}
function WorkOrder({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Grid n={4}><KV label="Work order" mono value={p.work_order_id} /><KV label="Dispatched" mono value={clock(p.dispatched_at)} /><KV label="Technician assignment" mono value={p.technician_assignment_id} /><KV label="Schedule" mono value={p.schedule_id} /></Grid>
      <Refs label="Approved by" ids={[p.approval_binding_id].filter(Boolean)} /><Refs label="Package" ids={[p.work_package_id].filter(Boolean)} /><Refs label="Intervention" ids={[p.intervention_id].filter(Boolean)} />
      <Rest payload={p} used={used("work_order_id", "dispatched_at", "technician_assignment_id", "schedule_id", "approval_binding_id", "work_package_id", "intervention_id")} />
    </>
  );
}
function Receipt({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Head><Stamp>{title(a.status)}</Stamp><span className="mono t3">{p.adapter}</span></Head>
      {p.performed_action ? <p className="r-body">{p.performed_action}</p> : null}
      <Grid n={4}><KV label="Technician" mono value={p.technician_id} /><KV label="Started" mono value={clock(p.started_at || p.attempted_at)} /><KV label="Completed" mono value={clock(p.completed_at)} /><KV label="Priority" value={title(p.priority)} /></Grid>
      {(p.resources_consumed || []).length ? <KV label="Resources consumed" mono value={p.resources_consumed.map((r) => `${r.part_id} ×${r.quantity}`).join(", ")} /> : null}
      {p.external_ids ? <div className="r-list"><span className="lbl">External identifiers</span>{Object.entries(p.external_ids).map(([k, v]) => <div key={k} className="r-item"><span className="mono t3">{k}</span><span className="mono">{v}</span></div>)}</div> : null}
      <Refs label="Work order" ids={[p.work_order_id].filter(Boolean)} /><Refs label="Approval" ids={[p.approval_binding_id || p.approval_reference].filter(Boolean)} /><Refs label="Intervention" ids={[p.intervention_id].filter(Boolean)} />
      <Rest payload={p} used={used("adapter", "performed_action", "technician_id", "started_at", "attempted_at", "completed_at", "priority", "resources_consumed", "external_ids", "work_order_id", "approval_binding_id", "approval_reference", "intervention_id", "work_package_id", "receipt_id")} />
    </>
  );
}
function ObservationPlan({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Grid n={3}><KV label="Minimum samples" mono value={p.minimum_samples} /><KV label="Accept at or below" mono value={p.recovery_risk_max != null ? `${num(p.recovery_risk_max, 2)} risk` : null} /><KV label="Recorded" mono value={(p.observations || []).length} /></Grid>
      {p.description ? <p className="r-body">{p.description}</p> : null}
      <Refs label="Samples" ids={(p.observations || []).map((o) => o.artifact_id || o.id).filter(Boolean)} />
      <Refs label="Execution receipt" ids={[p.execution_receipt_id].filter(Boolean)} />
      <Rest payload={p} used={used("minimum_samples", "recovery_risk_max", "observations", "description", "execution_receipt_id", "intervention_id")} />
    </>
  );
}
function Observation({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Grid n={4}><KV label="Sequence" mono value={p.sequence} /><KV label="Failure risk" mono value={num(p.failure_risk, 2)} /><KV label="Health" mono value={num(p.health_score, 2)} /><KV label="Vibration" mono value={p.vibration_mm_s != null ? `${num(p.vibration_mm_s, 1)} mm/s` : null} /></Grid>
      {p.telemetry ? <Structured data={p.telemetry} /> : null}
      <Refs label="Execution receipt" ids={[p.execution_receipt_id].filter(Boolean)} />
      <Rest payload={p} used={used("sequence", "failure_risk", "health_score", "vibration_mm_s", "temperature_rise_c", "telemetry", "execution_receipt_id", "intervention_id")} />
    </>
  );
}
function Outcome({ a }) {
  const p = a.payload || {};
  const before = p.before_metrics || {}, after = p.after_metrics || {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  const ok = String(p.result || a.status).includes("VERIFIED");
  return (
    <>
      <Head><Stamp tone={ok ? "ok" : "crit"}>{title(p.result || a.status)}</Stamp><span className="mono t3">{p.verifier || p.verifier_identity}</span><span className="mono t3">{clock(p.verification_timestamp || p.verified_at)}</span></Head>
      {p.reason ? <p className="r-body">{p.reason}</p> : null}
      {keys.length ? <table className="tbl tbl-ba"><thead><tr><th>Metric</th><th className="r">Before</th><th className="r">After</th></tr></thead><tbody>{keys.map((k) => <tr key={k}><td className="t3">{words(k)}</td><td className="r mono">{num(before[k], 2)}</td><td className="r mono t1">{num(after[k], 2)}</td></tr>)}</tbody></table> : null}
      <Refs label="Observations" ids={p.observation_ids || p.verification_evidence_ids} />
      <Refs label="Execution receipt" ids={[p.execution_receipt_id].filter(Boolean)} />
      <Rest payload={p} used={used("result", "verifier", "verifier_identity", "verification_timestamp", "verified_at", "reason", "before_metrics", "after_metrics", "observation_ids", "verification_evidence_ids", "execution_receipt_id", "intervention_id", "work_package_id")} />
    </>
  );
}
function Closure({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Head><Stamp tone="ok">Closed</Stamp><span className="mono t3">{clock(p.closed_at)}</span></Head>
      <Grid n={3}><KV label="Final phase" mono value={p.final_phase} /><KV label="Incident status" value={words(p.final_incident_status)} /><KV label="Closed at" mono value={dateTime(p.closed_at)} /></Grid>
      <Refs label="Outcome" ids={[p.outcome_id].filter(Boolean)} /><Refs label="Execution receipt" ids={[p.execution_receipt_id].filter(Boolean)} />
      <Rest payload={p} used={used("final_phase", "final_incident_status", "closed_at", "outcome_id", "execution_receipt_id")} />
    </>
  );
}
function LifecycleEvent({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Grid n={3}><KV label="Event" value={words(p.event_type)} /><KV label="Revision" mono value={p.revision} /><KV label="Represents" mono value={p.represented_artifact_id} /></Grid>
      {p.payload && Object.keys(p.payload).length ? <Structured data={p.payload} omit={new Set()} /> : null}
      {p.represented_artifact_id ? <Refs label="Linked artifact" ids={[p.represented_artifact_id]} /> : null}
    </>
  );
}
function Resource({ a }) {
  const p = a.payload || {};
  return (
    <>
      <Structured data={p} omit={new Set([...HIDE, "work_package_id", "intervention_id"])} />
      <Refs label="Work package" ids={[p.work_package_id].filter(Boolean)} /><Refs label="Intervention" ids={[p.intervention_id].filter(Boolean)} />
    </>
  );
}

const REGISTRY = {
  predictive_signal: PredictiveSignal, evidence: Evidence, technician_inspection: Inspection,
  specialist_advisory: Advisory, engineering_review: Advisory, operations_review: Advisory, critic_intervention_review: Advisory, specialist_activity: Activity,
  diagnosis: Diagnosis, diagnosis_validation: Verdict, intervention_validation: Verdict,
  intervention: Intervention, work_package: WorkPackage, inventory_reservation: Resource, technician_assignment: Resource, scheduling_record: Resource,
  approval_request: ApprovalRequest, approval_binding: ApprovalBinding, work_order: WorkOrder, execution_receipt: Receipt,
  recovery_observation_plan: ObservationPlan, recovery_observation: Observation, outcome_verification: Outcome, incident_closure: Closure, lifecycle_event: LifecycleEvent,
};
export const ADVISORY_TYPES = new Set(["specialist_advisory", "engineering_review", "operations_review", "critic_intervention_review", "specialist_activity"]);
export const TRUSTED_TYPES = new Set(["technician_inspection"]);

export function Renderer({ artifact }) {
  const R = REGISTRY[artifact.artifact_type];
  if (R) return <div className="r-typed"><R a={artifact} /></div>;
  return <div className="r-typed"><Structured data={artifact.payload || {}} /></div>;
}
