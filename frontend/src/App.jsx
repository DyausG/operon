import { useEffect, useMemo, useState } from "react";
import { useEngine } from "./state/useEngine.js";
import { focusAsset, incidentFor, rowIndex, viewOf } from "./state/selectors.js";
import { ArtifactProvider, useInspector } from "./state/artifacts.jsx";
import { CommandHeader } from "./features/CommandHeader.jsx";
import { FleetStrip } from "./features/FleetStrip.jsx";
import { ProcessLine } from "./features/ProcessLine.jsx";
import { SignalColumn } from "./features/SignalColumn.jsx";
import { OperationColumn } from "./features/Operation/OperationColumn.jsx";
import { Record } from "./features/Record.jsx";
import { ProvenanceFooter } from "./features/ProvenanceFooter.jsx";
import { InspectorTray } from "./features/Inspector/Tray.jsx";
import { Icons } from "./primitives/index.jsx";

export default function App({ engine }) {
  const live = useEngine();
  const { state, approve, reject, reset, stop, resume, startDemo, clearError } = engine || live;
  return <Shell state={state} actions={{ approve, reject, reset, stop, resume, startDemo, clearError }} />;
}

/** Deep link: open the inspector on load for #artifact=<id> (handy for recording and sharing). */
function DeepLink({ ready }) {
  const insp = useInspector();
  useEffect(() => {
    if (!ready || typeof location === "undefined") return;
    const m = /#artifact=([^&]+)/.exec(location.hash || "");
    if (m) insp.open(decodeURIComponent(m[1]));
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function Shell({ state, actions }) {
  const [selected, setSelected] = useState(null);
  const [recordOpen, setRecordOpen] = useState(false);
  useEffect(() => { setSelected(null); }, [state.generation]);
  const focusId = focusAsset(state, selected);
  const incident = incidentFor(state, focusId);
  const view = viewOf(incident);
  const index = useMemo(() => rowIndex(view), [view]);
  const hasIncident = Object.keys(state.alerts).length > 0;
  return (
    <ArtifactProvider generation={state.generation} rowIndex={index}>
      <DeepLink ready={state.frames > 0} />
      <div className="app">
        <CommandHeader state={state} focusId={focusId} onDemo={(id) => { setSelected(id); actions.startDemo(id); }}
          onReset={() => { setSelected(null); actions.reset(); }} onStop={actions.stop} onResume={actions.resume}
          onToggleRecord={() => setRecordOpen((v) => !v)} recordOpen={recordOpen} />
        <FleetStrip state={state} focusId={focusId} onSelect={setSelected} hasIncident={hasIncident} />
        <ProcessLine incident={incident} state={state} />
        <main className="stage">
          <SignalColumn state={state} focusId={focusId} incident={incident} />
          <OperationColumn state={state} incident={incident} focusId={focusId} approve={actions.approve} reject={actions.reject} onSelect={setSelected} />
          <Record view={view} incident={incident} state={state} />
        </main>
        <ProvenanceFooter state={state} />
        <InspectorTray view={view} incident={incident} />
        {recordOpen ? (
          <div className="tray tray-record" role="dialog" aria-label="Record">
            <button type="button" className="tray-close btn btn-quiet btn-icon" onClick={() => setRecordOpen(false)} aria-label="Close record">{Icons.close({})}</button>
            <Record view={view} incident={incident} state={state} className="col-record-tray" />
          </div>
        ) : null}
        {state.action.error ? (
          <div className="hdr-error" role="alert">{Icons.warn({})}<span>Action refused: {state.action.error}</span><button type="button" className="btn btn-quiet btn-small" onClick={actions.clearError}>Dismiss</button></div>
        ) : null}
      </div>
    </ArtifactProvider>
  );
}
