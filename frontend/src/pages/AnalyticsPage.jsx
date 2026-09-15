import { useMemo, useState } from "react";
import { useEngineState } from "../state/engine.jsx";
import { analytics } from "../state/portal.js";
import { PageHeader, Section, MetricCard, LoadingState, Segmented } from "../components/index.jsx";
import { LineChart, BarChart, HBarList } from "../components/charts.jsx";
import { money0, num, pct, risk as fmtRisk, title, words } from "../lib/format.js";

export function AnalyticsPage() {
  const { state } = useEngineState();
  const a = useMemo(() => analytics(state), [state]);
  const [riskView, setRiskView] = useState("fleet");
  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  const biz = a.business;
  const fleetRisk = [{ id: "mean", label: "Fleet mean risk", className: "s-1", points: a.meanRisk.map((p) => ({ t: p.t, v: p.mean })) }, { id: "max", label: "Highest asset risk", className: "s-2", points: a.meanRisk.map((p) => ({ t: p.t, v: p.max })) }];
  // Per-asset view: status colour is the identity here (critical/warning assets are the story), the rest recede.
  const perAsset = a.riskSeries.map((s) => ({ id: s.id, label: s.id, className: s.tone === "normal" ? "is-muted" : `tone-${s.tone}`, points: s.points }));
  const health = [{ id: "health", label: "Fleet mean health", className: "s-1", points: a.meanHealth.map((p) => ({ t: p.t, v: p.mean })) }];
  const thresholds = [{ value: state.triggerThreshold, label: `gate ${fmtRisk(state.triggerThreshold)}`, tone: "crit" }, { value: state.warnThreshold, label: `warn ${fmtRisk(state.warnThreshold)}`, tone: "warn" }];
  const outcomes = a.outcomes.length ? Object.entries(a.outcomes.reduce((m, o) => ({ ...m, [o.result]: (m[o.result] || 0) + 1 }), {})).map(([k, n]) => ({ key: k, label: title(k), n, tone: k === "VERIFIED_RECOVERY" ? "ok" : "warn" })) : [];
  const verdicts = a.verdicts.length ? Object.entries(a.verdicts.reduce((m, v) => ({ ...m, [`${v.target_kind}:${v.decision}`]: (m[`${v.target_kind}:${v.decision}`] || 0) + 1 }), {})).map(([k, n]) => ({ key: k, label: `${words(k.split(":")[0])} · ${words(k.split(":")[1])}`, n, tone: k.endsWith("ACCEPT") ? "auth" : "crit" })) : [];
  return (
    <div className="page">
      <div className="page-body page-wide">
        <PageHeader eyebrow="Plan" title="Analytics" meta={<><span>{a.sampleCount} telemetry samples in this generation</span><span>{a.alerts.length} incidents · {a.runs.length} reasoning runs</span>{state.demoScenario?.active ? <span className="tag tag-hatched">simulated scenario</span> : null}</>} />
        <div className="metrics">
          <MetricCard label="Recovered value" value={money0(biz.recovered_value || 0)} tone={biz.recovered_value ? "ok" : ""} sub={`${biz.events_prevented || 0} events mitigated`} compact />
          <MetricCard label="Net impact" value={money0(biz.net_value ?? 0)} sub={biz.loss_incurred ? `${money0(biz.loss_incurred)} lost` : "no losses recorded"} compact />
          <MetricCard label="OEE baseline" value={biz.oee_baseline != null ? pct(biz.oee_baseline) : "—"} sub={biz.oee_target != null ? `target ${pct(biz.oee_target)}` : ""} compact />
          <MetricCard label="Downtime cost" value={biz.downtime_cost_per_hour ? money0(biz.downtime_cost_per_hour) : "—"} unit="/ h" sub="unplanned line downtime" compact />
          <MetricCard label="Mean fleet risk" value={a.meanRisk.length ? fmtRisk(a.meanRisk[a.meanRisk.length - 1].mean) : "—"} sub="latest tick" compact />
        </div>
        <div className="grid-2">
          <Section label="Failure risk over time" meta={`${a.axis.length} ticks`} actions={<Segmented ariaLabel="Risk view" value={riskView} onChange={setRiskView} options={[{ value: "fleet", label: "Fleet" }, { value: "assets", label: "Per asset" }]} />}>
            <LineChart series={riskView === "fleet" ? fleetRisk : perAsset} yMin={0} yMax={1} yLabel="risk / 24 h" thresholds={thresholds} ariaLabel="Failure risk over time" showLegend={riskView === "fleet"} />
            {riskView === "assets" ? <p className="t3" style={{ fontSize: 11.5 }}>Assets in warning or critical status are drawn in their status colour; nominal assets recede. Hover for values.</p> : null}
          </Section>
          <Section label="Fleet health over time" meta="model health score"><LineChart series={health} yMin={0} yMax={1} yLabel="health" ariaLabel="Fleet mean health over time" /></Section>
        </div>
        <div className="grid-3">
          <Section label="Machines by status"><BarChart items={a.statusDist} ariaLabel="Machines by status" /></Section>
          <Section label="Incidents by phase"><BarChart items={a.phaseDist} ariaLabel="Incidents by phase" emptyLabel="No incidents in this generation." /></Section>
          <Section label="Criticality"><HBarList items={a.critDist.map((c) => ({ key: c.key, label: `${c.label} · ${c.incidents} incident${c.incidents === 1 ? "" : "s"}`, n: c.n }))} formatValue={(v) => `${v} assets`} /></Section>
        </div>
        <div className="grid-3">
          <Section label="Predicted failure signatures"><HBarList items={a.modeDist} emptyLabel="Every asset is on a nominal signature." /></Section>
          <Section label="Reasoning run dispositions" meta={`${a.runs.length} runs`}><HBarList items={a.runDist} emptyLabel="No specialist runs recorded." /></Section>
          <Section label="Validation verdicts & outcomes"><HBarList items={[...verdicts, ...outcomes]} emptyLabel="No verdicts or outcomes yet." /></Section>
        </div>
      </div>
    </div>
  );
}
