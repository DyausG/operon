import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useEngineState } from "../state/engine.jsx";
import { activityRows, alertsFor, asset as assetOf, incidentRows, maintenanceRows } from "../state/portal.js";
import { availableSeries, isActive, last, statusTone, viewOf } from "../state/selectors.js";
import { ROUTES } from "../app/routes.js";
import { Breadcrumbs, DataTable, EmptyState, LoadingState, Section, SeverityBadge, StatusBadge, Tabs, MetricCard } from "../components/index.jsx";
import { ClassIcon, Readout, Btn, Icons, Inspectable, When } from "../primitives/index.jsx";
import { SignalColumn } from "../features/SignalColumn.jsx";
import { AssetNominalBoard } from "../features/Operation/AssetNominalBoard.jsx";
import { SpecialistChain } from "../features/SpecialistChain.jsx";
import { ActivityList } from "./ActivityPage.jsx";
import { MaintenanceTable } from "./MaintenancePage.jsx";
import { risk as fmtRisk, num, title, words, clock } from "../lib/format.js";

export function MachineDetailPage() {
  const { id } = useParams();
  const { state, startDemo } = useEngineState();
  const navigate = useNavigate();
  const [tab, setTab] = useState("overview");
  const asset = assetOf(state, id);
  const alerts = useMemo(() => alertsFor(state, id), [state, id]);
  const active = alerts.find(isActive) || null;
  const incidents = useMemo(() => incidentRows(state).filter((r) => r.equipmentId === id), [state, id]);
  const work = useMemo(() => maintenanceRows(state).filter((r) => r.equipmentId === id), [state, id]);
  const activity = useMemo(() => activityRows(state, { equipmentId: id }), [state, id]);
  const points = state.histories?.[id] || [];
  const cur = last(points);
  const runs = useMemo(() => alerts.flatMap((a) => (viewOf(a).agent_runs || []).map((r) => ({ ...r, incidentId: a.incident_id, verdicts: viewOf(a).verdicts || [] }))), [alerts]);

  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  if (!asset) {
    return <div className="page"><div className="page-body"><Breadcrumbs items={[{ label: "Machines", to: ROUTES.machines }, { label: id }]} /><EmptyState title={`No machine ${id}`} body="The engine has not reported an asset with this id. It may have been removed on reset." action={<Btn onClick={() => navigate(ROUTES.machines)}>Back to machines</Btn>} /></div></div>;
  }
  const tone = statusTone(asset.status);
  const series = availableSeries(points);
  const tabs = [
    { key: "overview", label: "Overview" }, { key: "telemetry", label: "Telemetry", count: points.length },
    { key: "incidents", label: "Incidents", count: incidents.length }, { key: "maintenance", label: "Maintenance", count: work.length },
    { key: "agent", label: "Operon actions", count: runs.length }, { key: "activity", label: "Activity", count: activity.length },
  ];
  return (
    <div className="page">
      <div className="page-body page-wide">
        <Breadcrumbs items={[{ label: "Machines", to: ROUTES.machines }, { label: asset.equipment_id }]} />
        <div className="mh">
          <div className="page-head-main">
            <span className="lbl">{words(asset.equipment_class)} · {asset.criticality ? `${title(asset.criticality)} criticality` : ""}</span>
            <h1 className="page-title"><ClassIcon cls={asset.equipment_class} size={18} /><span>{asset.name}</span><span className="mono t3">{asset.equipment_id}</span><StatusBadge value={asset.status} /></h1>
            <div className="page-meta">
              <span>{asset.status_reason || "Current model risk thresholds"}</span>
              {asset.predicted_mode && asset.predicted_mode !== "NONE" ? <span>Signature: {asset.predicted_mode_label}</span> : <span>Nominal signature</span>}
              {cur ? <span className="mono">last sample t{cur.t}</span> : null}
            </div>
            <div className="page-actions">
              {active ? <Link className="btn btn-small btn-primary" to={ROUTES.incident(active.incident_id)}>{Icons.incidents({})} Open active incident</Link> : null}
              <Link className="btn btn-small" to={`${ROUTES.agent}?machine=${encodeURIComponent(asset.equipment_id)}`}>{Icons.agent({})} Agent workspace</Link>
              {!state.demoScenario?.active ? <Btn small quiet onClick={() => startDemo(asset.equipment_id)}>{Icons.demo({})} Run Guided Demo here</Btn> : null}
            </div>
          </div>
          <div className="mh-readouts">
            <div className="mh-ro"><span className="lbl">Failure risk / 24 h</span><Readout value={asset.failure_prob} decimals={2} size="s" tone={tone} /></div>
            <div className="mh-ro"><span className="lbl">Health score</span><Readout value={asset.health_score} decimals={2} size="s" /></div>
            <div className="mh-ro"><span className="lbl">Active incidents</span><Readout value={alerts.filter(isActive).length} decimals={0} size="s" tone={alerts.some(isActive) ? "warn" : ""} /></div>
          </div>
        </div>
        <Tabs tabs={tabs} value={tab} onChange={setTab} ariaLabel="Machine sections" />
        {tab === "overview" ? (
          <div className="detail-grid">
            <div className="stack">
              <Section label="Operational baseline" meta={`${series.length} telemetry channels`}><AssetNominalBoard state={state} focusId={asset.equipment_id} /></Section>
            </div>
            <div className="stack">
              <Section label="Status" flush>
                <div className="kvgrid kvgrid-2">
                  <KV label="Status" value={<StatusBadge value={asset.status} />} /><KV label="Criticality" value={<SeverityBadge criticality={asset.criticality} />} />
                  <KV label="Status source" value={words(asset.status_source)} /><KV label="Warn / gate" value={<span className="mono">{fmtRisk(state.warnThreshold)} / {fmtRisk(state.triggerThreshold)}</span>} />
                  <KV label="Incidents" value={`${alerts.filter(isActive).length} active · ${alerts.length - alerts.filter(isActive).length} closed`} /><KV label="Samples" value={<span className="mono">{points.length}</span>} />
                </div>
              </Section>
              <Section label="Current alert">
                {active ? (
                  <Inspectable id={active.lifecycle?.read_model?.diagnosis?.artifact_id || null} className="stack">
                    <div className="row-wrap"><StatusBadge value={active.lifecycle?.phase || active.status} /><span className="mono t3">{active.incident_id}</span></div>
                    <p className="t2">{active.lifecycle?.last_reason || active.predicted_mode_label || "Incident in progress."}</p>
                    <Link className="inline-link" to={ROUTES.incident(active.incident_id)}>Open incident →</Link>
                  </Inspectable>
                ) : <EmptyState compact title="No active alert" body="Telemetry is scored every tick. A signal at or above the incident gate opens a durable incident." />}
              </Section>
            </div>
          </div>
        ) : null}
        {tab === "telemetry" ? (
          <div className="detail-grid">
            <SignalColumn state={state} focusId={asset.equipment_id} incident={active} />
            <Section label="Latest sample" meta={cur ? `t${cur.t}` : "—"}>
              {cur ? <div className="channels">{series.map((s) => <div key={s.key} className="channel"><span className="lbl">{s.label}</span><span className="channel-v mono">{num(cur[s.key], s.d)}<small>{s.unit}</small></span></div>)}</div> : <EmptyState compact title="No samples yet" body="The engine has not streamed telemetry for this machine in this generation." />}
            </Section>
          </div>
        ) : null}
        {tab === "incidents" ? (
          <Section label="Incidents on this machine" flush>
            <DataTable dense columns={[
              { key: "id", label: "Incident", sort: true, render: (r) => <Link className="dt-link mono" to={ROUTES.incident(r.incidentId)}>{r.incidentId}</Link> },
              { key: "phase", label: "Phase", sort: true, render: (r) => <StatusBadge value={r.phase} /> },
              { key: "owner", label: "Owner", render: (r) => <span className="t2">{r.owner.label}</span> },
              { key: "mode", label: "Signature", render: (r) => <span className="t3">{r.mode || "—"}</span> },
              { key: "risk", label: "Risk", align: "right", sort: true, render: (r) => <span className="mono">{fmtRisk(r.risk)}</span> },
              { key: "openedAt", label: "Opened", sort: true, render: (r) => <span className="mono t3">{clock(r.openedAt) || "—"}</span> },
              { key: "revision", label: "Rev", align: "right", render: (r) => <span className="mono t3">{r.revision ?? "—"}</span> },
            ]} rows={incidents} rowKey={(r) => r.id} onRowClick={(r) => navigate(ROUTES.incident(r.incidentId))} empty="No incidents have been opened on this machine." />
          </Section>
        ) : null}
        {tab === "maintenance" ? <MaintenanceTable rows={work} empty="No interventions, work orders or receipts exist for this machine." /> : null}
        {tab === "agent" ? (
          <div className="stack">
            {runs.length ? runs.map((r) => <Section key={r.run_id} label={`Run · ${words(r.stage || "")}`} meta={r.incidentId}><SpecialistChain run={r} verdict={[...r.verdicts].reverse().find((v) => v.target_kind === (r.stage === "DIAGNOSIS" ? "diagnosis" : "intervention")) || null} stage={r.stage} /></Section>) : <EmptyState title="No Operon reasoning runs" body="Specialist runs are recorded per incident stage. None have been admitted for this machine yet." />}
          </div>
        ) : null}
        {tab === "activity" ? <Section label="Machine activity" meta={`${activity.length} entries`} flush><ActivityList rows={activity} showContext={false} /></Section> : null}
      </div>
    </div>
  );
}

function KV({ label, value }) { return <div className="kv"><span className="lbl kv-l">{label}</span><span className="kv-v">{value ?? <span className="t4">—</span>}</span></div>; }
