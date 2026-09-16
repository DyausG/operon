// Agent runtime contract for the workspace. This is the seam the Samsung PRISM
// interruptible-agent runtime will fill. Today it only *reports* what the backend already
// exposes (supervisor runs, dispositions, stale reasons); every capability the backend lacks
// is declared false so the UI never pretends.
import { last, phaseOf, viewOf } from "./selectors.js";

/** Vocabulary reserved for the interruptible runtime. Values not derivable today stay null. */
export const RUN_STATES = ["idle", "fast_path", "slow_path", "tool_executing", "interrupted", "cancelled", "superseded", "recovering", "replanning", "completed", "failed"];

export const CAPABILITIES = {
  operatorInstructions: { supported: true, note: "Messages go to POST /api/prism/sessions/{id}/messages; each accepted message is a new revision." },
  interrupt: { supported: true, note: "A new message supersedes the active revision: its Slow Path is cancelled where possible and fenced otherwise." },
  cancel: { supported: "partial", note: "Cooperative cancellation only; non-cancellable work completes in isolation and is recorded stale." },
  replan: { supported: false, note: "Re-planning is triggered by the application, never by the portal." },
  fastSlowPath: { supported: true, note: "Fast Path acknowledges immediately (deterministic); the Slow Path runs per revision and commits through the fence." },
  toolTrace: { supported: "partial", note: "Structured tool-call counts and delegations are recorded per run; no live step stream." },
  approvals: { supported: true, note: "Exact-plan approval/rejection is wired to /api/approve and /api/reject." },
};

function runState(run) {
  if (!run) return "idle";
  const status = String(run.status || "").toUpperCase();
  if (status === "RUNNING" || status === "STARTED" || status === "CLAIMED") return "tool_executing";
  if ((run.stale_reasons || []).length) return "superseded";
  if (status === "FAILED" || status === "ERROR") return "failed";
  if (String(run.disposition || "").toUpperCase().includes("DEFER")) return "recovering";
  return "completed";
}

/** The PRISM session bound to this incident (durable view mirrored from the server), if any. */
export function prismSessionFor(incident, state) {
  const sessions = Object.values(state.prism?.sessions || {});
  if (!incident?.incident_id) return sessions.find((s) => !s.incident_id) || null;
  return sessions.find((s) => s.incident_id === incident.incident_id) || null;
}

function prismState(session) {
  if (!session) return null;
  const map = { idle: "idle", fast_path: "fast_path", slow_path: "slow_path", superseding: "superseded", completed: "completed", failed: "failed", cancelled: "cancelled", recovering: "recovering" };
  return map[session.runtime_state] || null;
}

/** Derive the workspace's runtime view for one incident. Pure; reads the read model only. */
export function deriveAgentRuntime(incident, state) {
  const prism = prismSessionFor(incident, state);
  const view = viewOf(incident);
  const runs = view.agent_runs || [];
  const current = last(runs);
  const demo = state.demoScenario || {};
  // A Guided Demo incident reasons through the scenario's backend (the configured provider,
  // or the labelled deterministic advisory); report that, never the scenario id.
  const prov = demo.active && demo.reasoning && demo.incident_id && incident?.incident_id === demo.incident_id ? demo.reasoning : (state.reasoningProvenance || {});
  const phase = phaseOf(incident);
  const transitions = (view.events || []).filter((e) => e.event_type === "PHASE_CHANGED").map((e) => ({
    at: e.created_at, from: e.payload?.from, to: e.payload?.to, reason: e.payload?.reason, revision: e.revision, id: e.id,
  }));
  return {
    backend: prov.backend || "none",
    runtime: prov.runtime || null,
    provenance: prov.provenance || null,
    liveModel: prov.live_model ?? false,
    provider: prov.provider || "none",
    modelProvider: prov.model_provider || null,
    model: prov.model || null,
    available: prov.backend === "deterministic" ? true : state.supervisorAvailable !== false && prov.status !== "awaiting_runtime",
    status: prov.status || "unknown",
    phase,
    state: prismState(prism) || runState(current),
    path: prism ? (prism.active_run ? "slow" : prism.fast_path ? "fast" : null) : null,
    interruption: prism?.interruption ? `revision ${prism.interruption.superseded_revision} superseded by ${prism.interruption.superseded_by}${prism.interruption.still_running?.length ? " · old worker still running (fenced)" : ""}` : null,
    supersededBy: prism?.interruption ? `revision ${prism.interruption.superseded_by}` : null,
    recovery: prism?.recovery?.description || null,
    prism,
    runs,
    current,
    toolCalls: runs.reduce((n, r) => n + (r.tool_calls || 0), 0),
    delegations: runs.reduce((n, r) => n + (r.delegations || []).length, 0),
    transitions,
    capabilities: CAPABILITIES,
  };
}
