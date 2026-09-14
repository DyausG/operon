import { money0, pct } from "../lib/format.js";
import { Dot } from "../primitives/index.jsx";

export function KpiDeck({ state }) {
  const fleet = state.fleet || [];
  const biz = state.business || {};
  const alerts = Object.values(state.alerts || {});

  const crit = fleet.filter((a) => a.status === "CRITICAL");
  const warn = fleet.filter((a) => a.status === "WARNING");
  const nominal = fleet.filter((a) => !["CRITICAL", "WARNING"].includes(a.status));
  const hasCrit = crit.length > 0;
  const hasWarn = warn.length > 0;

  // 1. Fleet status
  let fleetVal = `${fleet.length}/${fleet.length}`;
  let fleetSub = "All nominal";
  let fleetTone = "ok";
  if (hasCrit) {
    fleetVal = `${crit.length} Critical`;
    fleetSub = `${warn.length ? `${warn.length} warn · ` : ""}${nominal.length} nominal`;
    fleetTone = "crit";
  } else if (hasWarn) {
    fleetVal = `${warn.length} Warning`;
    fleetSub = `${nominal.length} nominal`;
    fleetTone = "warn";
  }

  // 2. Operational pipeline
  const activeAlerts = alerts.filter(
    (a) => !["CLOSED", "FAILED", "CANCELLED"].includes(a.lifecycle?.phase || a.status)
  );
  const activeAlert = activeAlerts[0];
  let pipeVal = `${activeAlerts.length} Active`;
  let pipeSub = "Surveillance nominal";
  let pipeTone = "normal";
  if (activeAlert) {
    const phase = activeAlert.lifecycle?.phase || activeAlert.status || "OPEN";
    pipeTone = phase === "AWAITING_APPROVAL" ? "warn" : "auth";
    pipeVal = phase.replaceAll("_", " ");
    pipeSub = activeAlert.equipment_id ? `Target: ${activeAlert.equipment_id}` : "Active";
  }

  // 3. Line OEE
  const oeeBase = biz.oee_baseline ?? 0.71;
  const oeeTarget = biz.oee_target ?? 0.85;
  const oeeVal = pct(oeeBase);
  let oeeSub = `Target: ${pct(oeeTarget)}`;
  if (hasCrit) {
    oeeSub = `Bottleneck: ${crit[0].equipment_id}`;
  } else if (hasWarn) {
    oeeSub = `Impacted: ${warn[0].equipment_id}`;
  }

  // 4. Averted Downtime
  const recovered = biz.recovered_value || 0;
  const prevented = biz.events_prevented || 0;
  const avertedVal = recovered > 0 ? `+${money0(recovered)}` : "$0";
  const avertedSub = `${prevented} event${prevented === 1 ? "" : "s"} mitigated`;

  // 5. Value at Risk
  const dtCost = biz.downtime_cost_per_hour || 25000;
  let varVal = "$0";
  let varTone = "normal";
  let varSub = `Base: ${money0(dtCost)} / hr`;
  if (hasCrit) {
    varVal = `${money0(dtCost * 2)}`;
    varTone = "crit";
    varSub = "Active risk exposure";
  } else if (hasWarn || activeAlerts.length > 0) {
    varVal = `${money0(dtCost)}`;
    varTone = "warn";
    varSub = "Potential downtime exposure";
  }

  return (
    <div className="kpi-deck" role="region" aria-label="Fleet operational and economic KPIs">
      <div className={`kpi-cell tone-${fleetTone}`}>
        <div className="kpi-meta">
          <span className="kpi-lbl">Fleet Status</span>
          <Dot tone={fleetTone} />
        </div>
        <div className="kpi-body">
          <span className="kpi-val mono">{fleetVal}</span>
          <span className="kpi-sub truncate">{fleetSub}</span>
        </div>
      </div>

      <div className={`kpi-cell tone-${pipeTone}`}>
        <div className="kpi-meta">
          <span className="kpi-lbl">Operations Pipeline</span>
          {activeAlerts.length > 0 ? <Dot tone={pipeTone} /> : null}
        </div>
        <div className="kpi-body">
          <span className="kpi-val mono truncate">{pipeVal}</span>
          <span className="kpi-sub truncate">{pipeSub}</span>
        </div>
      </div>

      <div className="kpi-cell">
        <div className="kpi-meta">
          <span className="kpi-lbl">Line OEE</span>
          <span className="kpi-target mono">tgt {pct(oeeTarget)}</span>
        </div>
        <div className="kpi-body">
          <span className="kpi-val mono">{oeeVal}</span>
          <span className="kpi-sub truncate">{oeeSub}</span>
        </div>
      </div>

      <div className="kpi-cell tone-ok">
        <div className="kpi-meta">
          <span className="kpi-lbl">Averted Downtime</span>
        </div>
        <div className="kpi-body">
          <span className="kpi-val mono">{avertedVal}</span>
          <span className="kpi-sub truncate">{avertedSub}</span>
        </div>
      </div>

      <div className={`kpi-cell tone-${varTone}`}>
        <div className="kpi-meta">
          <span className="kpi-lbl">Value at Risk</span>
        </div>
        <div className="kpi-body">
          <span className="kpi-val mono">{varVal}</span>
          <span className="kpi-sub truncate">{varSub}</span>
        </div>
      </div>
    </div>
  );
}
