import { useMemo } from "react";
import { Dot } from "../primitives/index.jsx";
import { shortId } from "../lib/format.js";
import { phaseTitle, TERMINAL } from "../state/selectors.js";

export function IncidentSwitcher({
  state,
  focusId,
  incident,
  selectedMode = "ACTIVE",
  onSelectMode,
  onSelectIncident,
}) {
  const alerts = useMemo(() => {
    return Object.values(state.alerts || {});
  }, [state.alerts]);

  const machineAlerts = useMemo(() => {
    return alerts.filter((a) => a.equipment_id === focusId);
  }, [alerts, focusId]);

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

  const currentId = incident?.id || incident?.incident_id;

  return (
    <div className="incident-switcher" role="region" aria-label="Machine incident switcher">
      <div className="switcher-nav">
        <span className="switcher-lbl">INCIDENTS · {focusId || "—"}</span>
        <div className="switcher-segments" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={selectedMode === "ACTIVE"}
            className={`switcher-tab ${selectedMode === "ACTIVE" ? "is-active" : ""}`}
            onClick={() => onSelectMode && onSelectMode("ACTIVE")}
          >
            <span>Active</span>
            <span className="switcher-badge">{activeAlerts.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={selectedMode === "PAST"}
            className={`switcher-tab ${selectedMode === "PAST" ? "is-active" : ""}`}
            onClick={() => onSelectMode && onSelectMode("PAST")}
          >
            <span>Past</span>
            <span className="switcher-badge">{pastAlerts.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={selectedMode === "NOMINAL"}
            className={`switcher-tab ${selectedMode === "NOMINAL" ? "is-active" : ""}`}
            onClick={() => onSelectMode && onSelectMode("NOMINAL")}
          >
            <span>Nominal</span>
          </button>
        </div>
      </div>

      <div className="switcher-tray">
        {selectedMode === "ACTIVE" && (
          <div className="switcher-chips">
            {activeAlerts.map((a) => {
              const p = a.lifecycle?.phase || a.status || "OPEN";
              const id = a.id || a.incident_id || a.equipment_id;
              const isSelected = currentId === id;
              const isApproval = p === "AWAITING_APPROVAL";
              const tone = isApproval ? "warn" : "auth";
              return (
                <button
                  key={id}
                  type="button"
                  className={`session-chip ${isSelected ? "is-selected" : ""} tone-${tone}`}
                  onClick={() => onSelectIncident && onSelectIncident(a)}
                  title={`Incident ${id} · ${phaseTitle(a, state)}`}
                >
                  <Dot tone={tone} />
                  <span className="chip-id mono">{shortId(id)}</span>
                  <span className="chip-sep">·</span>
                  <span className="chip-phase">{phaseTitle(a, state)}</span>
                </button>
              );
            })}
            {activeAlerts.length === 0 && (
              <span className="switcher-empty">Continuous surveillance · Zero active incidents for {focusId}</span>
            )}
          </div>
        )}

        {selectedMode === "PAST" && (
          <div className="switcher-chips">
            {pastAlerts.map((a) => {
              const id = a.id || a.incident_id || a.equipment_id;
              const isSelected = currentId === id;
              return (
                <button
                  key={id}
                  type="button"
                  className={`session-chip resolved ${isSelected ? "is-selected" : ""}`}
                  onClick={() => onSelectIncident && onSelectIncident(a)}
                  title={`Resolved Incident ${id} · Closed`}
                >
                  <Dot tone="ok" />
                  <span className="chip-id mono">{shortId(id)}</span>
                  <span className="chip-sep">·</span>
                  <span className="chip-phase">Closed / Verified</span>
                </button>
              );
            })}
            {pastAlerts.length === 0 && (
              <span className="switcher-empty">No archived incident records for {focusId}</span>
            )}
          </div>
        )}

        {selectedMode === "NOMINAL" && (
          <div className="switcher-nominal-info">
            <span className="nominal-dot" />
            <span className="nominal-msg">Continuous sensor surveillance · Asset operating within nominal tolerance</span>
          </div>
        )}
      </div>
    </div>
  );
}
