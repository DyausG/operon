import { Inspectable, Stamp, Dot, Tag, IdToken, ProvenanceTag } from "../primitives/index.jsx";
import { roleName, STAGE_LABEL, inferRole } from "../state/selectors.js";
import { title, words } from "../lib/format.js";

const ABBR = { supervisor: "SUP", diagnostic: "DIAG", engineering: "ENG", operations: "OPS", critic: "CRIT", planner: "PLAN", system: "APP" };

/** Review chain: supervisor → delegations (advisory, dashed) → application validation (solid). Structured outputs only. */
export function SpecialistChain({ run, verdict, stage, compact = false, pendingLabel = "Application validation" }) {
  if (!run) return null;
  const nodes = (run.delegations || []).map((d) => ({
    key: d.key || d.role, role: d.role, status: d.status, text: d.summary || d.short_conclusion || d.question || "Structured report recorded",
    evidence: (d.evidence_references || d.evidence_ids || []).length, artifactId: d.artifact_id || null,
  }));
  for (const a of run.assessments || []) {
    if (nodes.some((n) => n.key === a.key)) continue;
    const role = inferRole(a.assessment);
    nodes.push({ key: a.key, role, status: "SUCCEEDED", text: a.assessment?.reasoning_summary || "Structured assessment recorded", evidence: (a.assessment?.evidence_reviewed || []).length, artifactId: null });
  }
  const running = run.status === "RUNNING";
  const identity = run.runtime_identity || {};
  return (
    <div className={`chain ${compact ? "chain-compact" : ""}`}>
      <div className="chain-head">
        <span className="lbl">Specialist chain · {STAGE_LABEL[run.stage || stage] || words(run.stage || stage)}</span>
        <Tag tone="adv" dashed>Advisory</Tag>
        {identity.provenance || run.provenance ? <ProvenanceTag provenance={identity.provenance || run.provenance} runtime={identity.runtime || run.runtime} live={identity.live_model ?? run.live_model} compact /> : null}
        <span className="chain-meta mono">{run.run_id ? <IdToken value={run.run_id} /> : null}{run.tool_calls != null ? ` · ${run.tool_calls} structured outputs` : ""}</span>
      </div>
      <Inspectable id={run.artifact_id} className="chain-sup" as="div">
        <span className="node-abbr">SUP</span>
        <span className="chain-sup-role">{roleName("supervisor")}</span>
        <span className="node-status"><Dot tone="adv" dashed />{running ? "running" : words(run.disposition || run.status || "")}</span>
        <span className="chain-sup-text truncate">{run.summary || "Delegates to specialists over the frozen evidence packet."}</span>
      </Inspectable>
      <div className="chain-row">
        {nodes.map((n, i) => (
          <div key={n.key} className="chain-link">
            {i ? <span className="edge edge-adv" /> : null}
            <Inspectable id={n.artifactId} className={`node ${n.status === "RUNNING" || (running && !n.status) ? "node-running" : ""}`}>
              <span className="node-abbr">{ABBR[n.role] || "SPC"}</span>
              <span className="node-role">{roleName(n.role)}</span>
              <span className="node-status"><Dot tone="adv" dashed />{words(n.status || (running ? "running" : "succeeded"))}{n.evidence ? ` · ${n.evidence} evidence` : ""}</span>
              <span className="node-text">{n.text}</span>
            </Inspectable>
          </div>
        ))}
        <div className="chain-link">
          <span className="edge edge-auth" />
          {verdict ? (
            <Inspectable id={verdict.artifact_id || verdict.id} className="node node-auth">
              <span className="node-abbr">APP</span>
              <span className="node-role">Application validation</span>
              <span className="node-status"><Stamp tone={verdict.decision === "ACCEPT" ? "auth" : "crit"}>{title(verdict.decision)}</Stamp></span>
              <span className="node-text">{verdict.concise_justification || verdict.validation_summary || (verdict.blocking_issues || []).join(" · ") || "Validated against policy."}{verdict.validation_policy_version ? <span className="node-policy mono"> · {verdict.validation_policy_version}</span> : null}</span>
            </Inspectable>
          ) : (
            <div className="node node-auth node-pending">
              <span className="node-abbr">APP</span>
              <span className="node-role">{pendingLabel}</span>
              <span className="node-status"><Stamp tone="pending">Pending</Stamp></span>
              <span className="node-text">Advisory output cannot transition the lifecycle. The application validates before anything is promoted.</span>
            </div>
          )}
        </div>
      </div>
      {(run.blockers || []).length ? <ul className="chain-blockers">{run.blockers.map((b) => <li key={b}>{b}</li>)}</ul> : null}
    </div>
  );
}
