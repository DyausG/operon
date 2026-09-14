import { renderToString } from "react-dom/server";
import { Shell } from "../src/App.jsx";
import { applySnapshot, initialState } from "../src/state/engineState.js";
import { ArtifactProvider } from "../src/state/artifacts.jsx";
import { rowIndex, viewOf, incidentFor, focusAsset, ledgerEntries, processModel } from "../src/state/selectors.js";
import { Tray } from "../src/features/Inspector/Tray.jsx";
import { Renderer } from "../src/features/Inspector/renderers.jsx";

const noop = () => Promise.resolve({ ok: true });
const actions = { approve: noop, reject: noop, reset: noop, stop: noop, resume: noop, startDemo: noop, clearError: () => {} };

export function run(frames, artifacts) {
  const lines = []; let failures = 0, lastHtml = "";
  let state = initialState;
  for (const frame of frames) {
    state = applySnapshot(state, frame);
    const label = `${frame.demo_scenario?.status} / ${frame.alerts?.[0]?.lifecycle?.phase || "no-incident"}`;
    try {
      const html = renderToString(<Shell state={state} actions={actions} />);
      const focus = focusAsset(state, null), incident = incidentFor(state, focus), view = viewOf(incident);
      const entries = ledgerEntries(view), pm = processModel(incident, state);
      if (!html.includes("class=\"app\"")) throw new Error("shell missing");
      lines.push(`ok   ${label.padEnd(44)} html ${String(html.length).padStart(6)}  entries ${String(entries.length).padStart(2)}  step ${pm.current?.key || pm.branch?.key}`);
      lastHtml = html;
    } catch (err) { failures++; lines.push(`FAIL ${label}: ${err.stack}`); }
  }
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
