import { useEffect, useMemo, useState } from "react";
import { useEngine } from "./state/useEngine.js";
import { focusAsset, rowIndex, viewOf, TERMINAL } from "./state/selectors.js";
import { ArtifactProvider, useInspector } from "./state/artifacts.jsx";
import { CommandHeader } from "./features/CommandHeader.jsx";
import { KpiDeck } from "./features/KpiDeck.jsx";
import { FleetStrip } from "./features/FleetStrip.jsx";
import { ProcessLine } from "./features/ProcessLine.jsx";
import { SignalColumn } from "./features/SignalColumn.jsx";
import { OperationColumn } from "./features/Operation/OperationColumn.jsx";
import { Record } from "./features/Record.jsx";
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
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [manualMode, setManualMode] = useState(null);
  const [recordOpen, setRecordOpen] = useState(false);

  useEffect(() => {
    setSelected(null);
    setSelectedIncident(null);
    setManualMode(null);
  }, [state.generation]);

  const focusId = focusAsset(state, selected);

  // Filter alerts for the currently focused machine
  const machineAlerts = useMemo(() => {
    return Object.values(state.alerts || {}).filter((a) => a.equipment_id === focusId);
  }, [state.alerts, focusId]);

  const activeAlerts = useMemo(() => {
    return machineAlerts.filter((a) => {
      const p = a.lifecycle?.phase || a.status;
      return p && !TERMINAL.has(p);
    });
  }, [machineAlerts]);

  const pastAlerts = useMemo(() => {
    return machineAlerts.filter((a) => {
      const p = a.lifecycle?.phase || a.status;
      return p && TERMINAL.has(p);
    });
  }, [machineAlerts]);

  // Smart view mode:
  // - If operator manually clicked a tab for this machine, respect it
  // - Otherwise:
  //   1. If active incident exists -> "ACTIVE"
  //   2. If no active incident, but closed/past incident exists -> "PAST"
  //   3. If no incidents exist at all -> "NOMINAL"
  const viewMode = useMemo(() => {
    if (manualMode && manualMode.assetId === focusId) {
      return manualMode.mode;
    }
    if (activeAlerts.length > 0) return "ACTIVE";
    if (pastAlerts.length > 0) return "PAST";
    return "NOMINAL";
  }, [manualMode, focusId, activeAlerts.length, pastAlerts.length]);

  // Derive target incident based strictly on the effective view mode
  let currentIncident = null;
  if (viewMode === "ACTIVE") {
    if (activeAlerts.length > 0) {
      currentIncident = (selectedIncident && activeAlerts.some((a) => (a.id || a.incident_id) === (selectedIncident.id || selectedIncident.incident_id)))
        ? selectedIncident
        : activeAlerts[0];
    }
  } else if (viewMode === "PAST") {
    if (pastAlerts.length > 0) {
      currentIncident = (selectedIncident && pastAlerts.some((a) => (a.id || a.incident_id) === (selectedIncident.id || selectedIncident.incident_id)))
        ? selectedIncident
        : pastAlerts[0];
    }
  } else {
    // viewMode === "NOMINAL"
    currentIncident = null;
  }

  const view = viewOf(currentIncident);
  const index = useMemo(() => rowIndex(view), [view]);
  const hasIncident = activeAlerts.length > 0;

  const handleSelectAsset = (id) => {
    setSelected(id);
    setSelectedIncident(null);
    setManualMode(null); // trigger smart mode derivation for the newly selected machine
  };

  const handleSelectMode = (mode) => {
    setManualMode({ assetId: focusId, mode });
    if (mode === "PAST" && pastAlerts.length > 0) {
      setSelectedIncident(pastAlerts[0]);
    } else if (mode === "ACTIVE" && activeAlerts.length > 0) {
      setSelectedIncident(activeAlerts[0]);
    } else {
      setSelectedIncident(null);
    }
  };

  const handleSelectIncident = (inc) => {
    setSelectedIncident(inc);
  };

  const handleStartDemo = (id) => {
    setSelected(id);
    setSelectedIncident(null);
    setManualMode({ assetId: id, mode: "ACTIVE" });
    actions.startDemo(id);
  };

  const handleReset = () => {
    setSelected(null);
    setSelectedIncident(null);
    setManualMode(null);
    actions.reset();
  };

  return (
    <ArtifactProvider generation={state.generation} rowIndex={index}>
      <DeepLink ready={state.frames > 0} />
      <div className="app">
        <CommandHeader
          state={state}
          focusId={focusId}
          onDemo={handleStartDemo}
          onReset={handleReset}
          onStop={actions.stop}
          onResume={actions.resume}
          onToggleRecord={() => setRecordOpen((v) => !v)}
          recordOpen={recordOpen}
        />
        <KpiDeck state={state} />
        <FleetStrip state={state} focusId={focusId} onSelect={handleSelectAsset} hasIncident={hasIncident} />
        <ProcessLine incident={currentIncident} state={state} />
        <main className="stage">
          <SignalColumn state={state} focusId={focusId} incident={currentIncident} />
          <OperationColumn
            state={state}
            incident={currentIncident}
            focusId={focusId}
            approve={actions.approve}
            reject={actions.reject}
            onSelect={handleSelectAsset}
            viewMode={viewMode}
            onSelectMode={handleSelectMode}
            onSelectIncident={handleSelectIncident}
          />
          <Record view={view} incident={currentIncident} state={state} />
        </main>
        <InspectorTray view={view} incident={currentIncident} />
        {recordOpen ? (
          <div className="tray tray-record" role="dialog" aria-label="Record">
            <button
              type="button"
              className="tray-close btn btn-quiet btn-icon"
              onClick={() => setRecordOpen(false)}
              aria-label="Close record"
            >
              {Icons.close({})}
            </button>
            <Record view={view} incident={currentIncident} state={state} className="col-record-tray" />
          </div>
        ) : null}
        {state.action.error ? (
          <div className="hdr-error" role="alert">
            {Icons.warn({})}
            <span>Action refused: {state.action.error}</span>
            <button type="button" className="btn btn-quiet btn-small" onClick={actions.clearError}>
              Dismiss
            </button>
          </div>
        ) : null}
      </div>
    </ArtifactProvider>
  );
}
