import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useEngineState } from "../state/engine.jsx";
import { maintenanceRows } from "../state/portal.js";
import { ROUTES } from "../app/routes.js";
import { PageHeader, DataTable, SearchInput, Segmented, FilterBar, MetricCard, StatusBadge, LoadingState, Section, EmptyState } from "../components/index.jsx";
import { Inspectable, Tag, Dot } from "../primitives/index.jsx";
import { clock, money0, title, windowLabel, words } from "../lib/format.js";
import { useInspector } from "../state/artifacts.jsx";

const KIND_LABEL = { intervention: "Intervention", approval: "Approval", work_order: "Work order", receipt: "Receipt" };
const ORIGIN_TONE = { advisory: "adv", application: "auth", trusted: "normal" };

export function MaintenanceTable({ rows, empty }) {
  const insp = useInspector();
  const columns = [
    { key: "kind", label: "Item", sort: true, render: (r) => <span className="dt-id"><Tag className="mt-kind">{KIND_LABEL[r.kind] || title(r.kind)}</Tag><span className="mono t3">{r.id}</span></span> },
    { key: "machine", label: "Machine", sort: true, render: (r) => <Link className="dt-link mono" to={ROUTES.machine(r.equipmentId)} onClick={(e) => e.stopPropagation()}>{r.equipmentId}</Link> },
    { key: "task", label: "Task", render: (r) => <span className="mt-task t2">{r.task}</span> },
    { key: "priority", label: "Priority", sort: true, render: (r) => r.priority ? <Tag tone={String(r.priority).toUpperCase() === "HIGH" || String(r.priority).toUpperCase() === "URGENT" ? "crit" : "normal"}>{title(r.priority)}</Tag> : <span className="t4">—</span> },
    { key: "status", label: "Status", sort: true, render: (r) => <StatusBadge value={r.status} /> },
    { key: "origin", label: "Origin", sort: true, render: (r) => <Tag tone={ORIGIN_TONE[r.origin]} dashed={r.origin === "advisory"}>{r.origin}</Tag> },
    { key: "technician", label: "Technician", render: (r) => <span className="mono t3">{r.technician || "—"}</span> },
    { key: "part", label: "Part", render: (r) => <span className="mono t3">{r.part || "—"}</span> },
    { key: "window", label: "Window / due", render: (r) => <span className="mono t3">{windowLabel(r.windowStart, r.windowEnd) || "—"}</span> },
    { key: "createdAt", label: "Created", sort: true, defaultDir: "desc", render: (r) => <span className="mono t3">{clock(r.createdAt) || "—"}</span> },
    { key: "incidentId", label: "Incident", render: (r) => r.incidentId ? <Link className="dt-link mono" to={ROUTES.incident(r.incidentId)} onClick={(e) => e.stopPropagation()}>{r.incidentId}</Link> : <span className="t4">—</span> },
  ];
  return (
    <div className="sec sec-flush"><div className="sec-body">
      <DataTable dense columns={columns} rows={rows} rowKey={(r) => `${r.kind}:${r.id}`} onRowClick={(r) => r.artifactId && insp.open(r.artifactId)} sort={{ key: "createdAt", dir: "desc" }} empty={empty} caption="Maintenance work items" />
    </div></div>
  );
}

export function MaintenancePage() {
  const { state } = useEngineState();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const rows = useMemo(() => maintenanceRows(state), [state]);
  const filtered = useMemo(() => rows.filter((r) => (kind === "all" || r.kind === kind) && (!q.trim() || `${r.id} ${r.machine} ${r.equipmentId} ${r.task} ${r.status} ${r.technician || ""} ${r.part || ""}`.toLowerCase().includes(q.trim().toLowerCase()))), [rows, q, kind]);
  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  const count = (k) => rows.filter((r) => r.kind === k).length;
  const pending = rows.filter((r) => r.kind === "approval" && r.status === "PENDING").length;
  const open = rows.filter((r) => r.kind === "work_order" && !["COMPLETED", "CLOSED", "CONFIRMED"].includes(String(r.status).toUpperCase())).length;
  const interventions = rows.filter((r) => r.kind === "intervention");
  const cost = interventions.reduce((s, r) => s + (r.cost || 0), 0);
  const bindings = Object.values(state.alerts || {}).map((a) => ({ a, b: a.lifecycle?.read_model?.binding })).filter((x) => x.b);
  return (
    <div className="page">
      <div className="page-body page-wide">
        <PageHeader eyebrow="Plan" title="Maintenance" meta={<><span>Interventions, approvals, work orders and receipts from the incident read models</span></>} />
        <div className="metrics">
          <MetricCard label="Interventions" value={count("intervention")} sub={`${interventions.filter((r) => r.origin === "application").length} validated`} compact onClick={() => setKind("intervention")} />
          <MetricCard label="Pending approvals" value={pending} tone={pending ? "warn" : ""} sub="Human hold point" compact onClick={() => setKind("approval")} />
          <MetricCard label="Work orders" value={count("work_order")} tone={open ? "auth" : ""} sub={open ? `${open} dispatched, no receipt` : "All confirmed"} compact onClick={() => setKind("work_order")} />
          <MetricCard label="Execution receipts" value={count("receipt")} sub="Trusted executor confirmations" compact onClick={() => setKind("receipt")} />
          <MetricCard label="Planned cost" value={cost ? money0(cost) : "—"} sub={state.demoScenario?.active ? "economics simulated" : "from validated interventions"} compact />
        </div>
        <FilterBar>
          <SearchInput value={q} onChange={setQ} placeholder="Search task, machine, technician, part" />
          <Segmented ariaLabel="Item kind" value={kind} onChange={setKind} options={[{ value: "all", label: "All", count: rows.length }, { value: "intervention", label: "Interventions", count: count("intervention") }, { value: "approval", label: "Approvals", count: count("approval") }, { value: "work_order", label: "Work orders", count: count("work_order") }, { value: "receipt", label: "Receipts", count: count("receipt") }]} />
        </FilterBar>
        <MaintenanceTable rows={filtered} empty={rows.length ? "No work items match." : "No maintenance items yet. Interventions appear once an incident reaches planning; the Guided Demo produces a complete work package."} />
        <div className="grid-2">
          <Section label="Bound resources" meta={`${bindings.length} binding${bindings.length === 1 ? "" : "s"}`}>
            {bindings.length ? bindings.map(({ a, b }) => (
              <Inspectable key={a.incident_id || a.equipment_id} id={b.artifact_id || b.id} className="stack" style={{ padding: "8px 10px", background: "var(--surface-2)" }}>
                <div className="row-wrap"><span className="mono t1">{a.equipment_id}</span><Link className="inline-link mono" to={ROUTES.incident(a.incident_id)} onClick={(e) => e.stopPropagation()}>{a.incident_id}</Link><StatusBadge value={b.status || b.inventory_status} /></div>
                <dl className="kvlist">
                  <dt>Technician</dt><dd className="mono">{b.technician_id || "—"}{b.technician_availability ? ` · ${words(b.technician_availability)}` : ""}</dd>
                  <dt>Parts</dt><dd className="mono">{(b.parts || []).map((p) => `${p.part_id} ×${p.quantity ?? 1}`).join(", ") || "—"}</dd>
                  <dt>Window</dt><dd className="mono">{windowLabel(b.schedule, b.window_end) || "—"}</dd>
                  <dt>Work package</dt><dd className="mono">{b.work_package_id || "—"}{b.work_package_version ? ` · v${b.work_package_version}` : ""}</dd>
                </dl>
              </Inspectable>
            )) : <EmptyState compact title="No resource bindings" body="Technician, part and schedule bindings are recorded by the application when an intervention is assembled." />}
          </Section>
          <Section label="How maintenance items are produced">
            <div className="stack">
              <div className="note-box"><Dot tone="adv" dashed /><span><b>Advisory drafts</b> come from the planner specialist and carry no authority.</span></div>
              <div className="note-box"><Dot tone="auth" /><span><b>Validated interventions, approval requirements and work orders</b> are application records bound to an exact intervention hash.</span></div>
              <div className="note-box"><Dot tone="trusted" /><span><b>Execution receipts</b> are trusted executor confirmations; only they move an incident to observation.</span></div>
              <p className="t3">There is no separate work-order system in Operon today; everything here is read from the incident lifecycle. Creating ad-hoc work orders from the portal is intentionally not offered.</p>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
