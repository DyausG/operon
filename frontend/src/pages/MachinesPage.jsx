import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useEngineState } from "../state/engine.jsx";
import { machineRows } from "../state/portal.js";
import { ROUTES } from "../app/routes.js";
import { PageHeader, DataTable, SearchInput, Select, Segmented, FilterBar, MetricCard, SeverityBadge, StatusBadge, Sparkline, LoadingState } from "../components/index.jsx";
import { ClassIcon, Dot } from "../primitives/index.jsx";
import { risk as fmtRisk, num, title } from "../lib/format.js";

export function MachinesPage() {
  const { state } = useEngineState();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [cls, setCls] = useState("all");
  const rows = useMemo(() => machineRows(state), [state]);
  const classes = useMemo(() => [...new Set(rows.map((r) => r.cls).filter(Boolean))].sort(), [rows]);
  const filtered = useMemo(() => rows.filter((r) => {
    if (status === "attention" && !["CRITICAL", "WARNING"].includes(r.status) && !r.activeIncidents) return false;
    if (status === "critical" && r.status !== "CRITICAL") return false;
    if (status === "healthy" && r.status !== "HEALTHY") return false;
    if (cls !== "all" && r.cls !== cls) return false;
    const s = q.trim().toLowerCase();
    if (s && !`${r.id} ${r.name} ${r.cls} ${r.mode || ""}`.toLowerCase().includes(s)) return false;
    return true;
  }), [rows, q, status, cls]);
  if (!state.frames && !rows.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;

  const crit = rows.filter((r) => r.status === "CRITICAL").length, warn = rows.filter((r) => r.status === "WARNING").length;
  const attention = rows.filter((r) => r.activeIncidents || r.status !== "HEALTHY").length;
  const meanHealth = rows.length ? rows.reduce((s, r) => s + (r.health ?? 0), 0) / rows.length : null;
  const columns = [
    { key: "id", label: "Machine", sort: true, render: (r) => <span className="dt-id"><Dot tone={r.tone} /><span className="mono t1">{r.id}</span><span className="dt-name truncate">{r.name}</span></span> },
    { key: "cls", label: "Class", sort: true, render: (r) => <span className="tbl-cls"><ClassIcon cls={r.cls} size={13} />{String(r.cls || "").replaceAll("_", " ").toLowerCase()}</span> },
    { key: "criticality", label: "Criticality", sort: (r) => ({ HIGH: 0, MEDIUM: 1, LOW: 2 }[r.criticality] ?? 3), render: (r) => <SeverityBadge criticality={r.criticality} /> },
    { key: "status", label: "Status", sort: true, render: (r) => <StatusBadge value={r.status} /> },
    { key: "risk", label: "Risk / 24 h", align: "right", sort: true, defaultDir: "desc", render: (r) => <span className={`mono tone-${r.tone}`}>{fmtRisk(r.risk)}</span> },
    { key: "health", label: "Health", align: "right", sort: true, render: (r) => <span className="mono t2">{num(r.health, 2)}</span> },
    { key: "trend", label: "Trend", render: (r) => <Sparkline points={r.history} tone={r.tone} /> },
    { key: "mode", label: "Signature", sort: true, render: (r) => <span className="t3">{r.mode || "Nominal signature"}</span> },
    { key: "activeIncidents", label: "Incidents", align: "right", sort: true, render: (r) => <span className="mono">{r.activeIncidents ? <span className="tone-warn">{r.activeIncidents} active</span> : r.incidents ? `${r.incidents} closed` : "—"}</span> },
    { key: "lastTick", label: "Last sample", align: "right", sort: true, render: (r) => <span className="mono t3">{r.lastTick != null ? `t${r.lastTick}` : "—"}</span> },
  ];
  return (
    <div className="page">
      <div className="page-body page-wide">
        <PageHeader eyebrow="Fleet" title="Machines" meta={<><span>{rows.length} assets · {state.meta.plant}</span><span>warn band {fmtRisk(state.warnThreshold)} · incident gate {fmtRisk(state.triggerThreshold)}</span></>} />
        <div className="metrics">
          <MetricCard label="Assets monitored" value={rows.length} sub={`${classes.length} equipment classes`} compact />
          <MetricCard label="Need attention" value={attention} tone={attention ? "warn" : "ok"} sub={attention ? `${crit} critical · ${warn} warning` : "All nominal"} onClick={() => setStatus(status === "attention" ? "all" : "attention")} compact />
          <MetricCard label="Critical" value={crit} tone={crit ? "crit" : ""} sub={crit ? "Active incident or risk above gate" : "None"} compact />
          <MetricCard label="Mean health" value={meanHealth == null ? "—" : num(meanHealth, 2)} sub="Model health score, fleet average" compact />
        </div>
        <FilterBar>
          <SearchInput value={q} onChange={setQ} placeholder="Search id, name, class, signature" />
          <Segmented ariaLabel="Status filter" value={status} onChange={setStatus} options={[{ value: "all", label: "All", count: rows.length }, { value: "attention", label: "Attention", count: attention }, { value: "critical", label: "Critical", count: crit }, { value: "healthy", label: "Healthy", count: rows.length - attention }]} />
          <div className="filters-end"><Select label="Class" value={cls} onChange={setCls} options={[{ value: "all", label: "All classes" }, ...classes.map((c) => ({ value: c, label: title(c) }))]} /></div>
        </FilterBar>
        <div className="sec sec-flush"><div className="sec-body">
          <DataTable columns={columns} rows={filtered} rowKey={(r) => r.id} onRowClick={(r) => navigate(ROUTES.machine(r.id))} sort={{ key: "risk", dir: "desc" }} empty={rows.length ? "No machines match these filters." : "The engine has not reported a fleet yet."} caption="Fleet machines" />
        </div></div>
      </div>
    </div>
  );
}
