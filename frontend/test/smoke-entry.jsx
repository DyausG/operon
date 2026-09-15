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
    "/app/dashboard", "/app/machines", `/app/machines/${machine}`, "/app/incidents", `/app/incidents/${inc}`, `/app/incidents/UNKNOWN-1`,
    `/app/agent?incident=${inc}`, "/app/maintenance", "/app/analytics", "/app/activity", "/app/notifications", "/app/profile", "/app/settings",
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
  // <Navigate> commits on the client, so a signed-out render of /app must simply not expose the shell.
  try { const html = render("/app/dashboard", state, null); if (html.includes('class="app')) throw new Error("shell rendered without a session"); lines.push("ok   signed-out /app renders no shell (redirect is client-side)"); }
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
        if (path === "/app/dashboard") lastHtml = html;
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
    if (s.eventLog.length < 4) throw new Error("event log not populated");
    const html = render("/app/notifications", s);
    if (!html.includes("ntf-row")) throw new Error("notifications not rendered");
    render("/app/activity", s);
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
