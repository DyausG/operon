// Server-render the whole portal (every route) for every captured demo frame, plus every
// artifact type through the inspector renderer. Catches runtime exceptions without a browser.
import { renderToString } from "react-dom/server";
import App from "../src/App.jsx";
import { applySnapshot, initialState, reduce } from "../src/state/engineState.js";
import { ArtifactProvider } from "../src/state/artifacts.jsx";
import { focusAsset, incidentFor, viewOf, ledgerEntries, processModel } from "../src/state/selectors.js";
import { Renderer } from "../src/features/Inspector/renderers.jsx";
import { machineRows, incidentRows, maintenanceRows, activityRows, analytics } from "../src/state/portal.js";
import { deriveAgentRuntime } from "../src/state/agentRuntime.js";

const noop = () => Promise.resolve({ ok: true });
const actions = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };
const SESSION = { email: "smoke@plant.example", name: "Smoke Operator", role: "maintenance_approver", remember: true, signedInAt: "2026-01-15T09:00:00Z", mode: "demo" };

function routesFor(state) {
  const focus = focusAsset(state, null);
  const incident = incidentFor(state, focus);
  const machine = focus || "AC-COMP-01";
  const inc = incident?.incident_id || "DEMO-INCIDENT-01";
  return [
    "/legacy/dashboard", "/legacy/machines", `/legacy/machines/${machine}`, "/legacy/incidents", `/legacy/incidents/${inc}`, `/legacy/incidents/UNKNOWN-1`,
    `/legacy/agent?incident=${inc}`, "/legacy/maintenance", "/legacy/analytics", "/legacy/activity", "/legacy/notifications", "/legacy/profile", "/legacy/settings",
  ];
}

export function run(frames, artifacts) {
  const lines = []; let failures = 0, lastHtml = "";
  let state = initialState;
  const render = (path, st, session = SESSION, theme = "dark") => renderToString(<App engine={{ state: st, ...actions }} session={session} settings={null} theme={theme} router="memory" initialEntries={[path]} />);

  // Login (signed out) in both themes, and the auth redirect.
  for (const theme of ["dark", "light"]) {
    try { const html = render("/login", state, null, theme); if (!html.includes("login-card")) throw new Error("login card missing"); lines.push(`ok   login (${theme})`.padEnd(50) + ` html ${String(html.length).padStart(6)}`); }
    catch (err) { failures++; lines.push(`FAIL login ${theme}: ${err.stack}`); }
  }
  // <Navigate> commits on the client, so a signed-out render must simply not expose either shell.
  try { for (const p of ["/legacy/dashboard", "/app/overview"]) { const html = render(p, state, null); if (html.includes('class="app') || html.includes('class="wb-root"')) throw new Error(`shell rendered without a session on ${p}`); } lines.push("ok   signed-out /legacy and /app render no shell (redirect is client-side)"); }
  catch (err) { failures++; lines.push(`FAIL auth guard: ${err.stack}`); }

  for (const frame of frames) {
    state = applySnapshot(state, frame);
    const label = `${frame.demo_scenario?.status} / ${frame.alerts?.[0]?.lifecycle?.phase || "no-incident"}`;
    try {
      const focus = focusAsset(state, null), incident = incidentFor(state, focus), view = viewOf(incident);
      const entries = ledgerEntries(view), pm = processModel(incident, state);
      // Pure derivations every page relies on.
      machineRows(state); incidentRows(state); maintenanceRows(state); activityRows(state); analytics(state); deriveAgentRuntime(incident, state);
      let total = 0;
      for (const path of routesFor(state)) {
        const html = render(path, state);
        if (!html.includes('class="app')) throw new Error(`shell missing on ${path}`);
        total += html.length;
        if (path === "/legacy/dashboard") lastHtml = html;
      }
      lines.push(`ok   ${label.padEnd(44)} routes ${routesFor(state).length}  html ${String(total).padStart(7)}  entries ${String(entries.length).padStart(2)}  step ${pm.current?.key || pm.branch?.key}`);
    } catch (err) { failures++; lines.push(`FAIL ${label}: ${err.stack}`); }
  }
  // Light theme + compact density over the final state.
  try { for (const path of routesFor(state)) render(path, state, SESSION, "light"); lines.push("ok   light theme over every route (final frame)"); }
  catch (err) { failures++; lines.push(`FAIL light theme: ${err.stack}`); }
  // Stream events feed the event log / notifications.
  try {
    let s = state;
    s = reduce(s, { type: "control", running: false });
    s = reduce(s, { type: "alert", alert: { ...Object.values(s.alerts)[0], lifecycle: { ...Object.values(s.alerts)[0].lifecycle, phase: "ESCALATED" } }, phase: "ESCALATED" });
    s = reduce(s, { type: "failure", equipment_id: "PRESS-08", result: { loss: 1 } });
    s = reduce(s, { type: "error", equipment_id: "AC-COMP-01", error: "stale intent" });
    // PRISM (Stage 1) versioned envelope: durable session view + event; the Agent page renders the panel.
    const inc = Object.values(s.alerts)[0]?.incident_id || null;
    const prismSession = { session_id: "11111111-2222-3333-4444-555555555555", incident_id: inc, status: "ACTIVE", current_revision: 2, canonical_revision: 1, canonical_current: false,
      fast_path: { status: "accepted_superseding", message: "Acknowledged as revision 2", latency_ms: 3.2, revision: 2, superseded_revision: 1, deeper_reasoning: "scheduled" },
      slow_path: { run_id: "aaaaaaaa-0000-0000-0000-000000000002", revision: 2, attempt: 1, status: "RUNNING", stale: false },
      active_run: { run_id: "aaaaaaaa-0000-0000-0000-000000000002", revision: 2, attempt: 1, status: "RUNNING", stale: false },
      runtime_state: "superseding", interruption: { superseded_revision: 1, superseded_by: 2, run_ids: ["aaaaaaaa-0000-0000-0000-000000000001"], at: "2026-09-16T09:00:00Z", still_running: ["aaaaaaaa-0000-0000-0000-000000000001"] },
      stale_results: 1, stale_run_ids: ["aaaaaaaa-0000-0000-0000-000000000001"], superseded_runs: 1, cancelled_runs: 0, last_failure: null,
      recovery: { policy: "retry_current_revision", description: "policy retry_current_revision; revision retried as attempt 2" },
      provenance: { adapter: "deterministic", provider: "none", model: null, live_model: false, provenance: "DETERMINISTIC" }, turn_count: 2, run_count: 2 };
    s = reduce(s, { type: "prism", prism_version: 1, session: prismSession, event: { event_id: 9, session_id: prismSession.session_id, revision: 1, run_id: "aaaaaaaa-0000-0000-0000-000000000001", event_type: "stale_result_discarded", payload: { reason: "stale_revision" }, created_at: "2026-09-16T09:00:01Z" } });
    if (!s.prism.sessions[prismSession.session_id] || s.prism.events[0].event_type !== "stale_result_discarded") throw new Error("prism reducer did not mirror the session");
    if (!deriveAgentRuntime(incidentFor(s, focusAsset(s, null)), s).prism) throw new Error("agent runtime did not pick up the prism session");
    const agentHtml = render(`/legacy/agent?incident=${inc}`, s);
    if (!agentHtml.includes("PRISM session") || !agentHtml.includes("stale result")) throw new Error("PRISM panel not rendered");
    if (s.eventLog.length < 5) throw new Error("event log not populated");
    const html = render("/legacy/notifications", s);
    if (!html.includes("ntf-row")) throw new Error("notifications not rendered");
    render("/legacy/activity", s);
    lines.push(`ok   stream event log → notifications (${s.eventLog.length} entries)`);
  } catch (err) { failures++; lines.push(`FAIL event log: ${err.stack}`); }

  // Every artifact type renders through the inspector renderer.
  const types = new Map();
  for (const art of Object.values(artifacts)) {
    try {
      const html = renderToString(<ArtifactProvider generation={0} rowIndex={new Map()} fetcher={async (id) => artifacts[id] || null}><Renderer artifact={art} /></ArtifactProvider>);
      if (html.length < 40) throw new Error("empty render");
      types.set(art.artifact_type, (types.get(art.artifact_type) || 0) + 1);
    } catch (err) { failures++; lines.push(`FAIL artifact ${art.id} (${art.artifact_type}): ${err.stack}`); }
  }
  lines.push(`artifact renderers: ${[...types.entries()].map(([t, n]) => `${t}×${n}`).join(", ")}`);
  return { report: lines.join("\n"), failures, lastHtml };
}
