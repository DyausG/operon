// Agent runtime contract for the workspace. This is the seam the Samsung PRISM
// interruptible-agent runtime will fill. Today it only *reports* what the backend already
// exposes (supervisor runs, dispositions, stale reasons); every capability the backend lacks
// is declared false so the UI never pretends.
import { last, phaseOf, viewOf } from "./selectors.js";

/** Vocabulary reserved for the interruptible runtime. Values not derivable today stay null. */
export const RUN_STATES = ["idle", "fast_path", "slow_path", "tool_executing", "interrupted", "cancelled", "superseded", "recovering", "replanning", "completed", "failed"];

export const CAPABILITIES = {
  operatorInstructions: { supported: false, note: "No operator-message endpoint exists; instructions cannot reach a runtime yet." },
  interrupt: { supported: false, note: "Runs are not cancellable from the portal; the lifecycle service owns run admission." },
  cancel: { supported: false, note: "Reserved for the PRISM runtime." },
  replan: { supported: false, note: "Re-planning is triggered by the application, never by the portal." },
  fastSlowPath: { supported: false, note: "The runtime reports one run per stage; fast/slow path split is not modelled." },
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

/** Derive the workspace's runtime view for one incident. Pure; reads the read model only. */
export function deriveAgentRuntime(incident, state) {
  const view = viewOf(incident);
  const runs = view.agent_runs || [];
  const current = last(runs);
  const prov = state.reasoningProvenance || {};
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
    available: state.supervisorAvailable !== false && prov.status !== "awaiting_runtime",
    status: prov.status || "unknown",
    phase,
    state: runState(current),
    path: null,            // fast | slow — reserved
    interruption: null,    // reserved
    supersededBy: null,    // reserved
    recovery: null,        // reserved
    runs,
    current,
    toolCalls: runs.reduce((n, r) => n + (r.tool_calls || 0), 0),
    delegations: runs.reduce((n, r) => n + (r.delegations || []).length, 0),
    transitions,
    capabilities: CAPABILITIES,
  };
}
