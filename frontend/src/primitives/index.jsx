import { useState } from "react";
import { clock, shortHash, shortId, title } from "../lib/format.js";
import { statusTone } from "../state/selectors.js";
import { useAnimatedNumber } from "../motion/index.jsx";
import { useInspector } from "../state/artifacts.jsx";

/* ---------- status vocabulary ---------- */
export function Dot({ tone = "normal", dashed = false, className = "" }) {
  return <i className={`dot dot-${tone} ${dashed ? "dot-dashed" : ""} ${className}`} aria-hidden="true" />;
}
export function Tag({ tone, children, dashed = false, hatched = false, className = "", title: t }) {
  const cls = `tag ${tone ? `tag-${tone}` : ""} ${dashed ? "tag-dashed" : ""} ${hatched ? "tag-hatched" : ""} ${className}`;
  return <span className={cls} title={t}>{children}</span>;
}
export function StatusTag({ value, dashed = false }) {
  if (!value) return null;
  const tone = statusTone(value);
  return <Tag tone={tone} dashed={dashed}><Dot tone={tone} dashed={dashed} />{title(value)}</Tag>;
}
/** Application-only mark. Never used for advisory output. */
export function Stamp({ tone = "auth", children, className = "" }) {
  return <span className={`stamp stamp-${tone} ${className}`}>{children}</span>;
}
/** Reasoning provenance chip. `reasoning` is the engine's normalized descriptor
 * ({ backend, provider, model, live_model, provenance }); legacy props still work. */
export function ProvenanceTag({ provenance, runtime, live, reasoning = null, compact = false }) {
  if (reasoning) {
    const label = reasoning.live_model ? `Model · ${reasoning.model_provider || reasoning.provider}${reasoning.model ? ` · ${reasoning.model}` : ""}`
      : reasoning.backend === "deterministic" ? "No model · deterministic advisory"
      : reasoning.provenance === "INJECTED" ? "No live model · injected double" : "No model provider";
    return <Tag className={`prov ${reasoning.live_model ? "prov-live" : "prov-none"}`} dashed={!reasoning.live_model} title={`backend ${reasoning.backend || "none"} · provider ${reasoning.provider || "none"} · model ${reasoning.model || "none"} · provenance ${reasoning.provenance || "none"}`}>{label}</Tag>;
  }
  if (!provenance || provenance === "SIMULATED") return null;
  const rt = runtime ? String(runtime).replace("operon.demo.", "") : null;
  return (
    <Tag className="prov" title={`provenance ${provenance} · runtime ${runtime || "unknown"}`}>
      {provenance}{!compact && rt ? <span className="prov-rt"> · {rt}</span> : null}
    </Tag>
  );
}
export function OwnerChip({ kind, label }) {
  return <span className={`owner owner-${kind}`}>{label}</span>;
}

/* ---------- identifiers & numbers ---------- */
export function IdToken({ value, hash = false, full = false, className = "" }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="t4">—</span>;
  const shown = full ? value : hash ? shortHash(value) : shortId(value, 9);
  const copy = (e) => {
    e.stopPropagation();
    try { navigator.clipboard?.writeText(String(value)); } catch { /* clipboard unavailable */ }
    setCopied(true); setTimeout(() => setCopied(false), 1200);
  };
  return <button type="button" className={`id ${className}`} title={String(value)} onClick={copy}>{copied ? "copied" : shown}</button>;
}
export function Readout({ value, decimals = 2, size = "m", tone = "", unit, delta, className = "" }) {
  const v = useAnimatedNumber(value, { decimals });
  return (
    <span className={`readout readout-${size} ${tone ? `tone-${tone}` : ""} ${className}`}>
      <span className="readout-v">{value == null ? "—" : v}</span>
      {unit ? <span className="readout-u">{unit}</span> : null}
      {delta != null && Math.abs(delta) > 0.0001 ? <span className={`readout-d ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(decimals)}</span> : null}
    </span>
  );
}
export function Count({ value }) { const v = useAnimatedNumber(value, { decimals: 0, duration: 320 }); return <span className="num">{v}</span>; }

/* ---------- layout ---------- */
export function PanelHeader({ label, meta, children, className = "" }) {
  return (
    <div className={`ph ${className}`}>
      <span className="lbl ph-label">{label}</span>
      {children}
      {meta != null ? <span className="ph-meta mono">{meta}</span> : null}
    </div>
  );
}
export function Btn({ children, primary = false, quiet = false, small = false, className = "", ...rest }) {
  return <button type="button" className={`btn ${primary ? "btn-primary" : ""} ${quiet ? "btn-quiet" : ""} ${small ? "btn-small" : ""} ${className}`} {...rest}>{children}</button>;
}
export function EmptySlot({ label, hint, tone = "", className = "" }) {
  return <div className={`slot slot-empty ${tone ? `slot-${tone}` : ""} ${className}`}><span className="lbl">{label}</span>{hint ? <span className="slot-hint">{hint}</span> : null}</div>;
}
export function KV({ label, value, mono = false, children, span = 1, className = "" }) {
  return (
    <div className={`kv ${className}`} style={span > 1 ? { gridColumn: `span ${span}` } : undefined}>
      <span className="lbl kv-l">{label}</span>
      <span className={`kv-v ${mono ? "mono" : ""}`}>{children ?? (value == null || value === "" ? <span className="t4">Not recorded</span> : value)}</span>
    </div>
  );
}
export function Rule({ className = "" }) { return <div className={`hair ${className}`} />; }
export function When({ iso }) { return iso ? <span className="mono t3 when" title={iso}>{clock(iso)}</span> : null; }

/** Clickable wrapper that opens the inspector for an artifact id. */
export function Inspectable({ id, children, className = "", as: As = "div", disabled = false, ...rest }) {
  const insp = useInspector();
  const active = insp.current && insp.current === id;
  if (!id || disabled) return <As className={className} {...rest}>{children}</As>;
  const onKey = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); insp.open(id); } };
  return <As role="button" tabIndex={0} className={`inspectable ${active ? "is-inspected" : ""} ${className}`} onClick={(e) => { e.stopPropagation(); insp.open(id); }} onKeyDown={onKey} title={`Inspect ${id}`} {...rest}>{children}</As>;
}
/** Small linked chip to another artifact (used in lineage, evidence references). */
export function ArtifactChip({ id, label, type, tone = "", push = true }) {
  const insp = useInspector();
  if (!id) return null;
  const { artifact } = insp.get(id);
  const text = label || artifact?.title || id;
  const kind = type || artifact?.artifact_type;
  return (
    <button type="button" className={`chip ${tone ? `chip-${tone}` : ""} ${insp.current === id ? "is-inspected" : ""}`} title={id}
      onClick={(e) => { e.stopPropagation(); push ? insp.push(id) : insp.open(id); }}>
      {kind ? <span className="chip-type">{title(kind)}</span> : null}<span className="chip-text">{text}</span>
    </button>
  );
}

/* ---------- icons: 16px, 1.5px stroke ---------- */
const I = ({ children, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
export function ClassIcon({ cls, size = 16 }) {
  switch (cls) {
    case "COMPRESSOR": return <I size={size}><circle cx="8" cy="8" r="5.5" /><path d="M8 2.5v3M8 10.5v3M2.5 8h3M10.5 8h3" /></I>;
    case "CNC_MACHINE": return <I size={size}><rect x="2.5" y="3" width="11" height="7.5" rx=".5" /><path d="M5 13.5h6M8 10.5v3M5.5 6l2 1.5-2 1.5" /></I>;
    case "PUMP": return <I size={size}><circle cx="6.5" cy="8.5" r="4" /><path d="M10.5 8.5h3M6.5 4.5V2M12 5l1.5-1.5" /></I>;
    case "ROBOT": return <I size={size}><rect x="4.5" y="6" width="7" height="6" rx="1" /><path d="M8 6V3M6 2h4M6.5 9h.01M9.5 9h.01" /></I>;
    case "CONVEYOR": return <I size={size}><circle cx="4" cy="10" r="1.8" /><circle cx="12" cy="10" r="1.8" /><path d="M4 8.2h8M2.5 12.5h11" /></I>;
    case "GRINDER": return <I size={size}><circle cx="8" cy="8" r="5" /><circle cx="8" cy="8" r="1.8" /></I>;
    case "PRESS": return <I size={size}><path d="M3 2.5h10M5.5 2.5v4l2.5 2.5 2.5-2.5v-4M8 9v4M5.5 13.5h5" /></I>;
    default: return <I size={size}><rect x="2.5" y="2.5" width="11" height="11" rx="1" /></I>;
  }
}
export const Icons = {
  close: (p) => <I {...p}><path d="M4 4l8 8M12 4l-8 8" /></I>,
  back: (p) => <I {...p}><path d="M10 3L5 8l5 5" /></I>,
  prev: (p) => <I {...p}><path d="M10 3L5 8l5 5" /></I>,
  next: (p) => <I {...p}><path d="M6 3l5 5-5 5" /></I>,
  pause: (p) => <I {...p}><path d="M5.5 3.5v9M10.5 3.5v9" /></I>,
  play: (p) => <I {...p}><path d="M5 3.5l7 4.5-7 4.5z" /></I>,
  reset: (p) => <I {...p}><path d="M3 8a5 5 0 1 0 1.5-3.6" /><path d="M3 3v3h3" /></I>,
  demo: (p) => <I {...p}><circle cx="8" cy="8" r="5.5" /><path d="M6.5 5.8l3.5 2.2-3.5 2.2z" fill="currentColor" stroke="none" /></I>,
  record: (p) => <I {...p}><path d="M3 4h10M3 8h10M3 12h7" /></I>,
  json: (p) => <I {...p}><path d="M5.5 2.5C4 2.5 4 3.5 4 4.5v2C4 7.5 3 8 2.5 8 3 8 4 8.5 4 9.5v2c0 1 0 2 1.5 2M10.5 2.5c1.5 0 1.5 1 1.5 2v2c0 1 1 1.5 1.5 1.5-.5 0-1.5.5-1.5 1.5v2c0 1 0 2-1.5 2" /></I>,
  link: (p) => <I {...p}><path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1a2.5 2.5 0 0 1-3.5-3.5l1-1" /></I>,
  check: (p) => <I {...p}><path d="M3.5 8.5l3 3 6-7" /></I>,
  warn: (p) => <I {...p}><path d="M8 2.5l6 11H2z" /><path d="M8 6.5v3M8 11.5h.01" /></I>,
  shield: (p) => <I {...p}><path d="M8 2l5 2v4c0 3.5-2.5 6-5 7-2.5-1-5-3.5-5-7V4z" /></I>,
  cpu: (p) => <I {...p}><rect x="4" y="4" width="8" height="8" rx="1" /><path d="M6 1v3M10 1v3M6 12v3M10 12v3M1 6h3M1 10h3M12 6h3M12 10h3" /></I>,
  grid: (p) => <I {...p}><rect x="2.5" y="2.5" width="4.5" height="4.5" /><rect x="9" y="2.5" width="4.5" height="4.5" /><rect x="2.5" y="9" width="4.5" height="4.5" /><rect x="9" y="9" width="4.5" height="4.5" /></I>,
  chevronDown: (p) => <I {...p}><path d="M4 6l4 4 4-4" /></I>,
  chevronRight: (p) => <I {...p}><path d="M6 4l4 4-4 4" /></I>,
  menu: (p) => <I {...p}><path d="M3 4.5h10M3 8h10M3 11.5h10" /></I>,
  search: (p) => <I {...p}><circle cx="7" cy="7" r="4" /><path d="M10 10l3.5 3.5" /></I>,
  bell: (p) => <I {...p}><path d="M4 11.5V7a4 4 0 0 1 8 0v4.5l1 1.5H3z" /><path d="M6.5 14a1.5 1.5 0 0 0 3 0" /></I>,
  sun: (p) => <I {...p}><circle cx="8" cy="8" r="3" /><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" /></I>,
  moon: (p) => <I {...p}><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z" /></I>,
  monitor: (p) => <I {...p}><rect x="2" y="3" width="12" height="8" rx="1" /><path d="M6 13.5h4M8 11v2.5" /></I>,
  dashboard: (p) => <I {...p}><rect x="2.5" y="2.5" width="4.5" height="6" /><rect x="9" y="2.5" width="4.5" height="3.5" /><rect x="9" y="8" width="4.5" height="5.5" /><rect x="2.5" y="10.5" width="4.5" height="3" /></I>,
  machines: (p) => <I {...p}><rect x="2.5" y="4" width="11" height="8" rx="1" /><path d="M5.5 12v2M10.5 12v2M2.5 8h11M6 4V2.5M10 4V2.5" /></I>,
  incidents: (p) => <I {...p}><path d="M8 2.5l6 11H2z" /><path d="M8 6.5v3M8 11.5h.01" /></I>,
  agent: (p) => <I {...p}><rect x="3" y="5" width="10" height="8" rx="1.5" /><path d="M8 5V2.5M5.5 2.5h5M6 9h.01M10 9h.01M6.5 11.5h3" /></I>,
  wrench: (p) => <I {...p}><path d="M9.5 2.5a3.5 3.5 0 0 0-3.2 4.9L2.5 11.2l2.3 2.3 3.8-3.8a3.5 3.5 0 0 0 4.9-3.2l-2 2-1.8-.5-.5-1.8z" /></I>,
  analytics: (p) => <I {...p}><path d="M2.5 13.5h11M4 10.5l3-3 2.5 2.5 3.5-4.5" /></I>,
  activity: (p) => <I {...p}><path d="M2 8h2.5l2-4.5 3 9 2-4.5H14" /></I>,
  user: (p) => <I {...p}><circle cx="8" cy="5.5" r="2.75" /><path d="M2.75 13.5a5.25 5.25 0 0 1 10.5 0" /></I>,
  settings: (p) => <I {...p}><circle cx="8" cy="8" r="2.2" /><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" /></I>,
  logout: (p) => <I {...p}><path d="M6 2.5H3v11h3M10 11l3-3-3-3M13 8H6.5" /></I>,
  external: (p) => <I {...p}><path d="M9 2.5h4.5V7M13.5 2.5L7.5 8.5M12 9.5v4H2.5V4h4" /></I>,
  eye: (p) => <I {...p}><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" /><circle cx="8" cy="8" r="2" /></I>,
  eyeOff: (p) => <I {...p}><path d="M2 2l12 12M6.3 6.4A2 2 0 0 0 9.6 9.7M4.2 4.3C2.6 5.5 1.5 8 1.5 8s2.5 4.5 6.5 4.5c1.2 0 2.3-.4 3.2-.9M7 3.6c.3 0 .7-.1 1-.1 4 0 6.5 4.5 6.5 4.5s-.7 1.3-1.9 2.5" /></I>,
  lock: (p) => <I {...p}><rect x="3.5" y="7" width="9" height="6.5" rx="1" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></I>,
  filter: (p) => <I {...p}><path d="M2.5 3.5h11L9.5 8.5v4l-3 1v-5z" /></I>,
  sortAsc: (p) => <I {...p}><path d="M8 3v10M4.5 6.5L8 3l3.5 3.5" /></I>,
  sortDesc: (p) => <I {...p}><path d="M8 3v10M4.5 9.5L8 13l3.5-3.5" /></I>,
  clock: (p) => <I {...p}><circle cx="8" cy="8" r="5.5" /><path d="M8 4.5V8l2.5 1.5" /></I>,
  bolt: (p) => <I {...p}><path d="M9 2L3.5 9h4l-.5 5L12.5 7h-4z" /></I>,
  stop: (p) => <I {...p}><rect x="4" y="4" width="8" height="8" rx="1" /></I>,
  plus: (p) => <I {...p}><path d="M8 3.5v9M3.5 8h9" /></I>,
  info: (p) => <I {...p}><circle cx="8" cy="8" r="5.5" /><path d="M8 7.5v3.5M8 5.2h.01" /></I>,
  collapse: (p) => <I {...p}><path d="M9.5 3L5 8l4.5 5M13 3v10" /></I>,
  expand: (p) => <I {...p}><path d="M6.5 3L11 8l-4.5 5M3 3v10" /></I>,
};
