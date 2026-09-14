import { EmptySlot, Inspectable, Tag } from "../../primitives/index.jsx";
import { words } from "../../lib/format.js";

const EXPECTED = [
  ["model_signal", "Predictive signal"], ["telemetry", "Telemetry trend"], ["operational_context", "Operating context"],
  ["maintenance_history", "Maintenance history"], ["inspection", "Technician inspection"],
];

export function EvidenceSlots({ evidence = [], blocked = false }) {
  const byKind = new Map();
  for (const e of evidence) byKind.set(e.kind, [...(byKind.get(e.kind) || []), e]);
  const kinds = [...EXPECTED];
  for (const k of byKind.keys()) if (!kinds.some(([kk]) => kk === k)) kinds.push([k, words(k)]);
  return (
    <div className="ev">
      <div className="ev-head"><span className="lbl">Evidence</span><span className="ph-meta mono">{evidence.length} record{evidence.length === 1 ? "" : "s"}</span></div>
      <div className="ev-grid">
        {kinds.map(([kind, label]) => {
          const items = byKind.get(kind) || [];
          if (!items.length) {
            const req = kind === "inspection" && blocked;
            return <EmptySlot key={kind} label={label} tone={req ? "warn" : ""} hint={req ? "Required before diagnosis validation · trusted input" : "Not yet acquired"} />;
          }
          const e = items[items.length - 1];
          const trusted = kind === "inspection";
          return (
            <Inspectable key={kind} id={e.artifact_id || e.id} className={`slot ev-slot ${trusted ? "ev-trusted" : ""}`}>
              <span className="lbl">{label}</span>
              <span className="ev-summary">{e.summary}</span>
              <span className="ev-meta" title={e.source_system || e.source || ""}>{e.quality ? <Tag hatched={String(e.quality).includes("SIMULATED")} className="ev-q">{words(e.quality)}</Tag> : null}{trusted && e.actor_id ? <span className="mono t3">{e.actor_id}</span> : null}</span>
            </Inspectable>
          );
        })}
      </div>
    </div>
  );
}
