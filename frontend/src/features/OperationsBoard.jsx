// The command view that was the whole dashboard: KPI deck, fleet strip, process line and the
// three-column stage. Now a feature the Dashboard page hosts inside the application shell.
import { useEffect, useMemo, useState } from "react";
import { focusAsset, viewOf, TERMINAL } from "../state/selectors.js";
import { KpiDeck } from "./KpiDeck.jsx";
import { FleetStrip } from "./FleetStrip.jsx";
import { ProcessLine } from "./ProcessLine.jsx";
import { SignalColumn } from "./SignalColumn.jsx";
import { OperationColumn } from "./Operation/OperationColumn.jsx";
import { Record } from "./Record.jsx";
import { Icons } from "../primitives/index.jsx";

const phaseOfAlert = (a) => a.lifecycle?.phase || a.status;

export function OperationsBoard({ state, actions, initialFocus = null, showKpis = true }) {
  const [selected, setSelected] = useState(initialFocus);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [manualMode, setManualMode] = useState(null);
  const [recordOpen, setRecordOpen] = useState(false);

  useEffect(() => { setSelected(null); setSelectedIncident(null); setManualMode(null); }, [state.generation]);
  useEffect(() => { if (initialFocus) setSelected(initialFocus); }, [initialFocus]);

  const focusId = focusAsset(state, selected);
  const machineAlerts = useMemo(() => Object.values(state.alerts || {}).filter((a) => a.equipment_id === focusId), [state.alerts, focusId]);
  const activeAlerts = useMemo(() => machineAlerts.filter((a) => { const p = phaseOfAlert(a); return p && !TERMINAL.has(p); }), [machineAlerts]);
  const pastAlerts = useMemo(() => machineAlerts.filter((a) => { const p = phaseOfAlert(a); return p && TERMINAL.has(p); }), [machineAlerts]);

  // Smart view mode: manual override for this machine, else ACTIVE → PAST → NOMINAL.
  const viewMode = useMemo(() => {
    if (manualMode && manualMode.assetId === focusId) return manualMode.mode;
    if (activeAlerts.length > 0) return "ACTIVE";
    if (pastAlerts.length > 0) return "PAST";
    return "NOMINAL";
  }, [manualMode, focusId, activeAlerts.length, pastAlerts.length]);

  const sameId = (a, b) => (a.id || a.incident_id) === (b.id || b.incident_id);
  let currentIncident = null;
  if (viewMode === "ACTIVE" && activeAlerts.length) currentIncident = selectedIncident && activeAlerts.some((a) => sameId(a, selectedIncident)) ? selectedIncident : activeAlerts[0];
  else if (viewMode === "PAST" && pastAlerts.length) currentIncident = selectedIncident && pastAlerts.some((a) => sameId(a, selectedIncident)) ? selectedIncident : pastAlerts[0];

  const view = viewOf(currentIncident);
  const hasIncident = activeAlerts.length > 0;

  const handleSelectAsset = (id) => { setSelected(id); setSelectedIncident(null); setManualMode(null); };
  const handleSelectMode = (mode) => {
    setManualMode({ assetId: focusId, mode });
    if (mode === "PAST" && pastAlerts.length) setSelectedIncident(pastAlerts[0]);
    else if (mode === "ACTIVE" && activeAlerts.length) setSelectedIncident(activeAlerts[0]);
    else setSelectedIncident(null);
  };

  return (
    <div className="ops">
      {showKpis ? <KpiDeck state={state} /> : null}
      <FleetStrip state={state} focusId={focusId} onSelect={handleSelectAsset} hasIncident={hasIncident} />
      <ProcessLine incident={currentIncident} state={state} tools={
        <button type="button" className={`btn btn-quiet btn-small btn-record ${recordOpen ? "is-active" : ""}`} onClick={() => setRecordOpen((v) => !v)} aria-pressed={recordOpen} title="Toggle the immutable event record">{Icons.record({})}<span>Record</span></button>
      } />
      <main className="stage">
        <SignalColumn state={state} focusId={focusId} incident={currentIncident} />
        <OperationColumn state={state} incident={currentIncident} focusId={focusId} approve={actions.approve} reject={actions.reject} onSelect={handleSelectAsset} viewMode={viewMode} onSelectMode={handleSelectMode} onSelectIncident={setSelectedIncident} links />
        <Record view={view} incident={currentIncident} state={state} />
      </main>
      {recordOpen ? (
        <div className="tray tray-record" role="dialog" aria-label="Record">
          <button type="button" className="tray-close btn btn-quiet btn-icon" onClick={() => setRecordOpen(false)} aria-label="Close record">{Icons.close({})}</button>
          <Record view={view} incident={currentIncident} state={state} className="col-record-tray" />
        </div>
      ) : null}
    </div>
  );
}
