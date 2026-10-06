// Representative shared components (07 §18). Every interactive component supports the frozen
// state set: default · hover · active · focus-visible · inactive · disabled · read-only · busy.
import { useId, useState } from "react";
import { IconCopy, IconCheck } from "@tabler/icons-react";
import { ProvenanceMark, SeverityBars, Shape } from "./glyphs.jsx";
import { CONDITION_LABEL, PROVENANCE_LABEL, SEVERITY_LEVEL } from "../model/status.js";
import { FRESHNESS_LABEL } from "../model/freshness.js";
import { age, clock, middle, score, sentence } from "../model/format.js";

/** Tabler icon at a spec size with the matching stroke (07 §10). */
export function Icon({ as: Cmp, size = 16, label, className = "" }) {
  const stroke = size >= 24 ? 2 : size >= 20 ? 1.75 : 1.5;
  return <Cmp size={size} stroke={stroke} className={`wb-icon ${className}`} aria-hidden={label ? undefined : true} aria-label={label} focusable="false" />;
}

/**
 * Button. `inactive` = blocked by state (R-3): stays focusable, aria-disabled, reason linked by
 * `reasonId`, and activation calls `onBlocked` (move focus to the blocker). `busy` keeps the label,
 * adds progress text and aria-busy; never `disabled`.
 */
export function Button({ variant = "secondary", size = "md", inactive = false, reasonId, onBlocked, busy = false, busyLabel,
  disabled = false, icon, children, onClick, type = "button", className = "", ...rest }) {
  const handle = (e) => {
    if (inactive || busy) { e.preventDefault(); if (inactive) onBlocked?.(e); return; }
    onClick?.(e);
  };
  return (
    <button
      type={type}
      className={`wb-btn wb-btn-${variant} wb-btn-${size} ${inactive ? "is-inactive" : ""} ${busy ? "is-busy" : ""} ${className}`}
      aria-disabled={inactive || undefined}
      aria-describedby={inactive && reasonId ? reasonId : rest["aria-describedby"]}
      aria-busy={busy || undefined}
      disabled={disabled}
      onClick={handle}
      {...rest}
    >
      {icon ? <Icon as={icon} size={16} /> : null}
      <span>{children}</span>
      {busy ? <span className="wb-btn-busy">{busyLabel || "Submitting…"}</span> : null}
    </button>
  );
}

export function IconButton({ icon, label, onClick, size = 16, className = "", ...rest }) {
  return (
    <button type="button" className={`wb-iconbtn ${className}`} aria-label={label} title={label} onClick={onClick} {...rest}>
      <Icon as={icon} size={size} />
    </button>
  );
}

/** Mono identifier inside a 2 px-radius hairline frame (instrument tag). */
export function Tag({ children, title }) {
  return <span className="wb-tag" title={title}>{children}</span>;
}

export function SimulatedTag() {
  return <span className="wb-simtag">SIMULATED</span>;
}

/** Read-only identifier with copy (R-13: middle truncation, full value on hover and copy). */
export function CopyId({ value, head = 6, tail = 4, label }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="wb-muted">Not recorded</span>;
  const copy = async () => {
    try { await navigator.clipboard.writeText(String(value)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard unavailable */ }
  };
  return (
    <span className="wb-copyid">
      <span className="wb-mono-sm" title={String(value)}>{middle(value, head, tail)}</span>
      <button type="button" className="wb-iconbtn wb-iconbtn-sm" onClick={copy} aria-label={`Copy ${label || "identifier"}`} title={copied ? "Copied" : `Copy ${label || "identifier"}`}>
        <Icon as={copied ? IconCheck : IconCopy} size={16} />
      </button>
    </span>
  );
}

/** Asset condition: glyph plus word (plus score when expanded). Stale replaces the dot, never Normal. */
export function ConditionMarker({ condition, value, size = 14, showWord = true, showScore = false, stale = false }) {
  const c = stale ? "stale" : condition || "unknown";
  const shape = c === "critical" ? "critical" : c === "elevated" ? "elevated" : c === "normal" ? "normal" : c === "stale" ? "stale" : "unknown";
  const word = CONDITION_LABEL[c];
  return (
    <span className={`wb-marker wb-cond-${c}`}>
      <Shape name={shape} size={size} label={`Asset condition: ${word}`} decorative={showWord} />
      {showWord ? <span className="wb-marker-word">{word}</span> : null}
      {showScore && Number.isFinite(value) ? <span className="wb-num">{score(value)}</span> : null}
    </span>
  );
}

/** Waiting on: person-in-square (decision violet) for human roles, gear for system roles (CH-1). */
export function WaitingOn({ role, size = 14, prefix = false, quiet = false }) {
  if (!role) return <span className="wb-muted">Not reported</span>;
  if (role.key === "none") return <span className="wb-marker"><span className="wb-marker-word wb-secondary">No one</span></span>;
  return (
    <span className="wb-marker">
      <Shape name={role.human ? "decision" : "system"} size={size} decorative tone={role.human && !quiet ? "decision" : "nominal"} />
      <span className="wb-marker-word">
        {prefix ? <span className="wb-secondary">Waiting on </span> : null}
        <span className={role.human && !quiet ? "wb-role-word" : ""}>{role.label}</span>
      </span>
    </span>
  );
}

export function SeverityMarker({ value, basis = "Severity" }) {
  if (!value) return <span className="wb-muted">Not projected</span>;
  return (
    <span className="wb-marker" aria-label={`${basis}: ${sentence(value)}`}>
      <SeverityBars level={SEVERITY_LEVEL[value] || 0} />
      <span className="wb-marker-word" aria-hidden="true">{sentence(value)}</span>
    </span>
  );
}

export function AttentionGlyph({ level }) {
  const name = level === "action" ? "rankAction" : level === "risk" ? "rankRisk" : level === "watch" ? "rankWatch" : null;
  const label = level === "action" ? "Action required" : level === "risk" ? "At risk" : level === "watch" ? "Watch" : "";
  return name ? <Shape name={name} size={14} label={label} /> : <span className="wb-shape-blank" aria-hidden="true" />;
}

export function Provenance({ kind, detail }) {
  const word = PROVENANCE_LABEL[kind] || "Derived";
  return <ProvenanceMark kind={kind} label={detail ? `${word} · ${detail}` : word} />;
}

/**
 * Freshness indicator (07 §15.3): clock glyph + state word + receipt time. Receipt times come
 * from the browser clock until X8 and say "received", never implying server or plant time.
 */
export function FreshnessIndicator({ fresh, compact = false }) {
  if (!fresh) return null;
  const { state, ageMs, lastReceipt } = fresh;
  const word = FRESHNESS_LABEL[state];
  const at = lastReceipt ? clock(lastReceipt, { seconds: true }) : null;
  const title = "Time basis: browser receipt time (the stream has no server timestamps yet, X8). Expected interval measured from recent arrivals.";
  let detail = null;
  if (state === "live") detail = at ? `received ${at}` : null;
  else if (state === "delayed") detail = `${age(ageMs)} since last update`;
  else if (state === "stale") detail = at ? `since received ${at}` : null;
  else if (state === "disconnected") detail = at ? `last received ${at}` : "no data received";
  else if (state === "paused") detail = fresh.tick != null ? `at tick ${fresh.tick.toLocaleString("en-GB")}` : null;
  else if (state === "measuring") detail = "measuring update interval";
  const shape = state === "disconnected" ? "offline" : state === "live" || state === "measuring" ? null : "stale";
  return (
    <span className={`wb-fresh is-${state}`} title={title}>
      {shape ? <Shape name={shape} size={14} decorative /> : null}
      <span className="wb-fresh-word">{word}</span>
      {detail && !compact ? <span className="wb-fresh-detail">· {detail}</span> : null}
    </span>
  );
}

/** Title block (07 §9.4): at most six labelled cells. Cells that don't apply are dropped. */
export function TitleBlock({ cells, end, label }) {
  const visible = cells.filter(Boolean).slice(0, 6);
  return (
    <dl className="wb-titleblock" aria-label={label}>
      {visible.map((c) => (
        <div className="wb-tb-cell" key={c.label}>
          <dt className="wb-eyebrow">{c.label}</dt>
          <dd className="wb-tb-value">{c.value}</dd>
        </div>
      ))}
      {end ? <div className="wb-tb-end">{end}</div> : null}
    </dl>
  );
}

/** Section heading: mono index · title · right-aligned meta · rule (07 §18.4). */
export function SectionHeading({ index, title, meta, id, level = 2, sticky = false, action }) {
  const H = `h${level}`;
  return (
    <div className={`wb-section-head ${sticky ? "is-sticky" : ""}`}>
      {index ? <span className="wb-section-index" aria-hidden="true">{index}</span> : null}
      <H className="wb-section-title" id={id}>{title}</H>
      {meta ? <span className="wb-section-meta">{meta}</span> : null}
      {action ? <span className="wb-section-action">{action}</span> : null}
    </div>
  );
}

/** Inline alert: left 2 px rule plus glyph (info · warning · critical · decision). */
export function InlineAlert({ tone = "info", title, children, id, role }) {
  const shape = tone === "critical" ? "critical" : tone === "warning" ? "elevated" : tone === "decision" ? "decision" : tone === "stale" ? "stale" : tone === "offline" ? "offline" : null;
  return (
    <div className={`wb-alert wb-alert-${tone}`} id={id} role={role}>
      {shape ? <Shape name={shape} size={14} decorative /> : <span className="wb-alert-dot" aria-hidden="true" />}
      <div className="wb-alert-body">
        {title ? <p className="wb-alert-title">{title}</p> : null}
        {children ? <div className="wb-alert-text">{children}</div> : null}
      </div>
    </div>
  );
}

export function EmptyLine({ children }) {
  return <p className="wb-empty-line">{children}</p>;
}

export function Checkbox({ checked, onChange, children, id, describedBy, invalid }) {
  const auto = useId();
  const cid = id || auto;
  return (
    <label className="wb-check" htmlFor={cid}>
      <input type="checkbox" id={cid} checked={checked} onChange={(e) => onChange(e.target.checked)} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
      <span className="wb-check-box" aria-hidden="true" />
      <span className="wb-check-label">{children}</span>
    </label>
  );
}

/** Textarea with validation timing (R-16): on blur after a change, and on submit. */
export function TextArea({ label, hint, value, onChange, message, level, id, rows = 3, onBlur }) {
  const auto = useId();
  const tid = id || auto;
  const msgId = `${tid}-msg`;
  const hintId = `${tid}-hint`;
  return (
    <div className="wb-field">
      <label className="wb-label" htmlFor={tid}>{label}</label>
      {hint ? <p className="wb-hint" id={hintId}>{hint}</p> : null}
      <textarea
        id={tid} rows={rows} className={`wb-textarea ${level ? `is-${level}` : ""}`} value={value}
        onChange={(e) => onChange(e.target.value)} onBlur={onBlur}
        aria-invalid={level === "error" || undefined}
        aria-describedby={[hint ? hintId : null, message ? msgId : null].filter(Boolean).join(" ") || undefined}
      />
      {message ? <p className={`wb-field-msg is-${level}`} id={msgId}>
        <Shape name={level === "error" ? "critical" : "elevated"} size={14} decorative tone={level === "error" ? "critical" : "warning"} />
        <span>{message}</span>
      </p> : null}
    </div>
  );
}

/** Segmented control: choices that apply immediately (07 §18.1). */
export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="wb-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          className={`wb-seg-opt ${value === o.value ? "is-on" : ""}`} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Label / value rows (sentence-case keys, `type.label`; R-7). */
export function Ledger({ rows, className = "" }) {
  return (
    <dl className={`wb-ledger ${className}`}>
      {rows.filter(Boolean).map((r) => (
        <div className="wb-ledger-row" key={r.key || r.label}>
          <dt className="wb-ledger-key">{r.label}</dt>
          <dd className="wb-ledger-val">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Muted({ children }) {
  return <span className="wb-muted">{children}</span>;
}
