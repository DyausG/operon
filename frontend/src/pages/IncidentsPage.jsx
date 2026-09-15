import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useEngineState } from "../state/engine.jsx";
import { incidentRows } from "../state/portal.js";
import { ROUTES } from "../app/routes.js";
import { PageHeader, DataTable, SearchInput, Segmented, FilterBar, MetricCard, SeverityBadge, StatusBadge, LoadingState } from "../components/index.jsx";
import { OwnerChip, Dot, ProvenanceTag } from "../primitives/index.jsx";
import { risk as fmtRisk, clock } from "../lib/format.js";

export function IncidentsPage() {
  const { state } = useEngineState();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [scope, setScope] = useState("all");
  const rows = useMemo(() => incidentRows(state), [state]);
  const filtered = useMemo(() => rows.filter((r) => {
    if (scope === "active" && !r.active) return false;
    if (scope === "closed" && r.active) return false;
    if (scope === "approval" && r.phase !== "AWAITING_APPROVAL") return false;
    const s = q.trim().toLowerCase();
    return !s || `${r.incidentId} ${r.equipmentId} ${r.machine} ${r.phase} ${r.mode || ""}`.toLowerCase().includes(s);
  }), [rows, q, scope]);
  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  const active = rows.filter((r) => r.active).length, approvals = rows.filter((r) => r.phase === "AWAITING_APPROVAL").length;
  const exceptional = rows.filter((r) => ["ESCALATED", "EXECUTION_FAILED", "CANCELLED"].includes(r.phase)).length;
  const columns = [
    { key: "incidentId", label: "Incident", sort: true, render: (r) => <span className="dt-id"><Dot tone={r.tone} /><span className="mono t1">{r.incidentId}</span></span> },
    { key: "machine", label: "Machine", sort: true, render: (r) => <span className="dt-id"><Link className="dt-link mono" to={ROUTES.machine(r.equipmentId)} onClick={(e) => e.stopPropagation()}>{r.equipmentId}</Link><span className="dt-name truncate">{r.machine}</span></span> },
    { key: "criticality", label: "Severity", sort: (r) => ({ HIGH: 0, MEDIUM: 1, LOW: 2 }[r.criticality] ?? 3), render: (r) => <SeverityBadge criticality={r.criticality} /> },
    { key: "phase", label: "Phase", sort: true, render: (r) => <StatusBadge value={r.phase} /> },
    { key: "owner", label: "Handling", render: (r) => <OwnerChip kind={r.owner.kind} label={r.owner.label} /> },
    { key: "mode", label: "Description", render: (r) => <span className="t2 dt-wrapcell">{r.reason || r.mode || "—"}</span> },
    { key: "risk", label: "Risk", align: "right", sort: true, render: (r) => <span className={`mono tone-${r.tone}`}>{fmtRisk(r.risk)}</span> },
    { key: "openedAt", label: "Detected", sort: true, render: (r) => <span className="mono t3">{clock(r.openedAt) || "—"}</span> },
    { key: "updatedAt", label: "Updated", sort: true, defaultDir: "desc", render: (r) => <span className="mono t3">{clock(r.updatedAt) || "—"}</span> },
    { key: "revision", label: "Rev", align: "right", sort: true, render: (r) => <span className="mono t3">{r.revision ?? "—"}</span> },
    { key: "provenance", label: "Prov.", render: (r) => <ProvenanceTag provenance={r.provenance} compact /> },
  ];
  return (
    <div className="page">
      <div className="page-body page-wide">
        <PageHeader eyebrow="Reliability lifecycle" title="Incidents" meta={<><span>{rows.length} projected by the engine</span><span>Authority path: {state.authorityPath || "lifecycle"}</span></>} />
        <div className="metrics">
          <MetricCard label="Active" value={active} tone={active ? "warn" : "ok"} sub={active ? "In the lifecycle" : "None open"} onClick={() => setScope("active")} compact />
          <MetricCard label="Awaiting approval" value={approvals} tone={approvals ? "warn" : ""} sub="Human hold point" onClick={() => setScope("approval")} compact />
          <MetricCard label="Exceptional" value={exceptional} tone={exceptional ? "crit" : ""} sub="Escalated, failed or cancelled" compact />
          <MetricCard label="Closed" value={rows.length - active} sub="Verified or terminal" onClick={() => setScope("closed")} compact />
        </div>
        <FilterBar>
          <SearchInput value={q} onChange={setQ} placeholder="Search incident, machine, phase" />
          <Segmented ariaLabel="Scope" value={scope} onChange={setScope} options={[{ value: "all", label: "All", count: rows.length }, { value: "active", label: "Active", count: active }, { value: "approval", label: "Needs approval", count: approvals }, { value: "closed", label: "Closed", count: rows.length - active }]} />
        </FilterBar>
        <div className="sec sec-flush"><div className="sec-body">
          <DataTable columns={columns} rows={filtered} rowKey={(r) => r.id} onRowClick={(r) => navigate(ROUTES.incident(r.incidentId))} sort={{ key: "updatedAt", dir: "desc" }} empty={rows.length ? "No incidents match." : "No incidents. A predictive signal at or above the gate opens one; the Guided Demo produces a complete lifecycle."} caption="Incidents" />
        </div></div>
      </div>
    </div>
  );
}
