import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useEngineState } from "../state/engine.jsx";
import { activityRows } from "../state/portal.js";
import { ROUTES } from "../app/routes.js";
import { PageHeader, SearchInput, Segmented, FilterBar, Select, LoadingState, Section, EmptyState } from "../components/index.jsx";
import { Inspectable, When } from "../primitives/index.jsx";
import { dateTime } from "../lib/format.js";

const LANES = [{ value: "all", label: "All" }, { value: "authority", label: "Authoritative" }, { value: "advisory", label: "Advisory" }, { value: "trusted", label: "Trusted input" }, { value: "human", label: "Operator" }, { value: "application", label: "Engine" }];

export function ActivityList({ rows, showContext = true }) {
  if (!rows.length) return <EmptyState compact title="No activity" body="Lifecycle events, specialist outputs, operator decisions and engine control events appear here in order." />;
  let lastDay = null;
  return (
    <div className="lg-list">
      {rows.map((e) => {
        const day = (e.at || "").slice(0, 10);
        const header = day && day !== lastDay ? <div key={`d:${day}`} className="act-day">{day}</div> : null;
        lastDay = day || lastDay;
        return (
          <div key={e.key}>
            {header}
            <Inspectable id={e.artifactId} className={`act-row lg-lane-${e.lane} act-lane-${e.lane}`}>
              <span className="lg-ln" />
              {showContext ? <span className="act-ctx">{e.equipmentId ? <Link to={ROUTES.machine(e.equipmentId)} onClick={(ev) => ev.stopPropagation()}>{e.equipmentId}</Link> : <span className="t4">engine</span>}{e.incidentId ? <Link to={ROUTES.incident(e.incidentId)} onClick={(ev) => ev.stopPropagation()} className="truncate">{e.incidentId}</Link> : null}</span> : null}
              <span className="act-body"><span className="act-title">{e.title}</span>{e.detail ? <span className="act-detail">{e.detail}</span> : null}</span>
              <span className="act-meta">{e.lane === "advisory" ? <span className="lg-adv">adv</span> : e.revision != null ? <span className="lg-rev">rev {e.revision}</span> : <span className="lg-rev">{e.source === "stream" ? "stream" : e.lane}</span>}<When iso={e.at} /></span>
            </Inspectable>
          </div>
        );
      })}
    </div>
  );
}

export function ActivityPage() {
  const { state } = useEngineState();
  const [q, setQ] = useState("");
  const [lane, setLane] = useState("all");
  const [machine, setMachine] = useState("all");
  const rows = useMemo(() => activityRows(state), [state]);
  const filtered = useMemo(() => rows.filter((e) => {
    if (lane === "authority" && e.lane !== "authority") return false;
    if (lane !== "all" && lane !== "authority" && e.lane !== lane) return false;
    if (machine !== "all" && e.equipmentId !== machine) return false;
    const s = q.trim().toLowerCase();
    return !s || `${e.title} ${e.detail} ${e.equipmentId || ""} ${e.incidentId || ""}`.toLowerCase().includes(s);
  }), [rows, q, lane, machine]);
  if (!state.frames && !state.fleet.length) return <div className="page"><div className="page-body"><LoadingState /></div></div>;
  const count = (l) => rows.filter((e) => (l === "all" ? true : e.lane === l)).length;
  return (
    <div className="page">
      <div className="page-body page-wide">
        <PageHeader eyebrow="Review" title="Activity" meta={<><span>{rows.length} entries · lifecycle records of every projected incident plus engine stream events</span>{rows[0]?.at ? <span>latest {dateTime(rows[0].at)}</span> : null}</>} />
        <FilterBar>
          <SearchInput value={q} onChange={setQ} placeholder="Search events, machines, incidents" />
          <Segmented ariaLabel="Lane" value={lane} onChange={setLane} options={LANES.map((l) => ({ ...l, count: count(l.value) }))} />
          <div className="filters-end"><Select label="Machine" value={machine} onChange={setMachine} options={[{ value: "all", label: "All machines" }, ...state.fleet.map((a) => ({ value: a.equipment_id, label: a.equipment_id }))]} /></div>
        </FilterBar>
        <Section label="Chronological record" meta={`${filtered.length} shown`} flush><ActivityList rows={filtered} /></Section>
      </div>
    </div>
  );
}
