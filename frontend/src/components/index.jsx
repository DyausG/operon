// Shared composite UI for the portal: page chrome, tables, tabs, menus, dialogs, states.
// Built on the primitives; every colour comes from tokens.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Icons, Tag, Dot } from "../primitives/index.jsx";
import { statusTone } from "../state/selectors.js";
import { title } from "../lib/format.js";

/* ---------- page chrome ---------- */
export function PageHeader({ eyebrow, title: t, meta, children, actions, className = "" }) {
  return (
    <div className={`page-head ${className}`}>
      <div className="page-head-main">
        {eyebrow ? <span className="lbl page-eyebrow">{eyebrow}</span> : null}
        <h1 className="page-title">{t}</h1>
        {meta ? <div className="page-meta">{meta}</div> : null}
        {children}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </div>
  );
}

export function Breadcrumbs({ items = [] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {items.map((c, i) => (
        <span key={`${c.label}-${i}`} className="crumb">
          {i ? <span className="crumb-sep" aria-hidden="true">{Icons.chevronRight({ size: 12 })}</span> : null}
          {c.to && i < items.length - 1 ? <Link to={c.to} className="crumb-link">{c.label}</Link> : <span className={i === items.length - 1 ? "crumb-cur" : "crumb-link"}>{c.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function Section({ label, meta, children, className = "", actions, flush = false }) {
  return (
    <section className={`sec ${flush ? "sec-flush" : ""} ${className}`}>
      {label ? (
        <div className="sec-head">
          <span className="lbl sec-label">{label}</span>
          {actions}
          {meta != null ? <span className="sec-meta mono">{meta}</span> : null}
        </div>
      ) : null}
      <div className="sec-body">{children}</div>
    </section>
  );
}

/* ---------- metrics ---------- */
export function MetricCard({ label, value, unit, sub, tone = "", to, onClick, icon, compact = false }) {
  const body = (
    <>
      <div className="mc-meta"><span className="mc-lbl">{label}</span>{tone && tone !== "normal" ? <Dot tone={tone} /> : null}</div>
      <div className="mc-body">
        <span className={`mc-val mono ${tone ? `tone-${tone}` : ""}`}>{value}{unit ? <span className="mc-unit">{unit}</span> : null}</span>
        {sub ? <span className="mc-sub truncate">{sub}</span> : null}
      </div>
    </>
  );
  const cls = `mc ${compact ? "mc-compact" : ""} ${tone ? `mc-${tone}` : ""} ${to || onClick ? "mc-link" : ""}`;
  if (to) return <Link to={to} className={cls}>{body}</Link>;
  if (onClick) return <button type="button" className={cls} onClick={onClick}>{body}</button>;
  return <div className={cls}>{body}</div>;
}

export function SeverityBadge({ criticality }) {
  if (!criticality) return <span className="t4">—</span>;
  const c = String(criticality).toUpperCase();
  const tone = c === "HIGH" ? "crit" : c === "MEDIUM" ? "warn" : "normal";
  return <Tag tone={tone} className="sev">{c === "HIGH" ? "High" : c === "MEDIUM" ? "Medium" : title(c)}</Tag>;
}

export function StatusBadge({ value }) {
  if (!value) return <span className="t4">—</span>;
  const tone = statusTone(value);
  return <Tag tone={tone}><Dot tone={tone} />{title(value)}</Tag>;
}

export function Sparkline({ points = [], accessor = (p) => p.prob ?? 0, width = 72, height = 18, tone = "normal", max = 1 }) {
  if (!points || points.length < 2) return <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true"><line x1="0" y1={height - 2} x2={width} y2={height - 2} stroke="var(--text-4)" strokeWidth="1" strokeDasharray="2 2" /></svg>;
  const p = points.slice(-40);
  const vals = p.map(accessor);
  const hi = max ?? Math.max(...vals), lo = max != null ? 0 : Math.min(...vals), span = hi - lo || 1;
  const pts = p.map((_, i) => `${((i / (p.length - 1)) * width).toFixed(1)},${(height - 1 - ((vals[i] - lo) / span) * (height - 2)).toFixed(1)}`).join(" ");
  return <svg className={`spark tone-${tone}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true"><polyline points={pts} fill="none" strokeWidth="1.3" /></svg>;
}

/* ---------- data table ---------- */
export function DataTable({ columns, rows, rowKey, onRowClick, sort: initialSort, empty, dense = false, className = "", rowClass, caption }) {
  const [sort, setSort] = useState(initialSort || null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col || !col.sort) return rows;
    const get = typeof col.sort === "function" ? col.sort : (r) => r[col.key];
    const out = [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") return va - vb;
      return String(va).localeCompare(String(vb));
    });
    return sort.dir === "desc" ? out.reverse() : out;
  }, [rows, sort, columns]);
  const toggle = (c) => {
    if (!c.sort) return;
    setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: c.defaultDir || "asc" }));
  };
  return (
    <div className={`dt-wrap ${className}`}>
      <table className={`tbl dt ${dense ? "dt-dense" : ""}`}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={`${c.align === "right" ? "r" : ""} ${c.sort ? "dt-sortable" : ""} ${sort?.key === c.key ? "dt-sorted" : ""}`} style={c.width ? { width: c.width } : undefined} aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
                {c.sort ? <button type="button" className="dt-sort" onClick={() => toggle(c)}>{c.label}{sort?.key === c.key ? (sort.dir === "asc" ? Icons.sortAsc({ size: 12 }) : Icons.sortDesc({ size: 12 })) : null}</button> : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length ? sorted.map((r) => {
            const k = rowKey(r);
            const clickable = !!onRowClick;
            return (
              <tr key={k} className={`${clickable ? "tbl-select" : ""} ${rowClass ? rowClass(r) : ""}`} onClick={clickable ? () => onRowClick(r) : undefined} tabIndex={clickable ? 0 : undefined} onKeyDown={clickable ? (e) => { if (e.key === "Enter") onRowClick(r); } : undefined}>
                {columns.map((c) => <td key={c.key} className={c.align === "right" ? "r" : ""}>{c.render ? c.render(r) : r[c.key]}</td>)}
              </tr>
            );
          }) : (
            <tr><td colSpan={columns.length} className="dt-empty">{empty || "Nothing to show."}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- filters ---------- */
export function SearchInput({ value, onChange, placeholder = "Search", className = "", autoFocus = false, ...rest }) {
  return (
    <label className={`search ${className}`}>
      {Icons.search({ size: 14 })}
      <input type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} autoFocus={autoFocus} {...rest} />
    </label>
  );
}
export function Select({ value, onChange, options, label, className = "" }) {
  const id = useId();
  return (
    <label className={`sel ${className}`} htmlFor={id}>
      {label ? <span className="lbl">{label}</span> : null}
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}
export function Segmented({ value, onChange, options, ariaLabel }) {
  return (
    <div className="seg-ctl" role="tablist" aria-label={ariaLabel}>
      {options.map((o) => (
        <button key={o.value} type="button" role="tab" aria-selected={value === o.value} className={`seg-btn ${value === o.value ? "is-active" : ""}`} onClick={() => onChange(o.value)}>
          {o.label}{o.count != null ? <span className="seg-count mono">{o.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
export function FilterBar({ children }) { return <div className="filters">{children}</div>; }

/* ---------- tabs ---------- */
export function Tabs({ tabs, value, onChange, ariaLabel }) {
  return (
    <div className="tabs" role="tablist" aria-label={ariaLabel}>
      {tabs.map((t) => (
        <button key={t.key} type="button" role="tab" aria-selected={value === t.key} className={`tab ${value === t.key ? "is-active" : ""}`} onClick={() => onChange(t.key)}>
          {t.label}{t.count != null ? <span className="tab-count mono">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

/* ---------- toggles & fields ---------- */
export function Toggle({ checked, onChange, label, hint, disabled = false }) {
  const id = useId();
  return (
    <div className={`toggle-row ${disabled ? "is-disabled" : ""}`}>
      <div className="toggle-text"><label htmlFor={id} className="toggle-label">{label}</label>{hint ? <span className="toggle-hint">{hint}</span> : null}</div>
      <button id={id} type="button" role="switch" aria-checked={checked} className={`toggle ${checked ? "on" : ""}`} onClick={() => !disabled && onChange(!checked)} disabled={disabled}><span className="toggle-knob" /></button>
    </div>
  );
}
export function Field({ label, hint, error, children, className = "" }) {
  return (
    <div className={`field ${error ? "has-error" : ""} ${className}`}>
      <span className="lbl field-label">{label}</span>
      {children}
      {error ? <span className="field-error" role="alert">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}
export function Input({ className = "", ...rest }) { return <input className={`input ${className}`} {...rest} />; }

/* ---------- menus & dialogs ---------- */
export function useOutsideClose(open, onClose) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, onClose]);
  return ref;
}

export function Menu({ button, children, align = "right", open, onOpenChange, className = "", width }) {
  const ref = useOutsideClose(open, () => onOpenChange(false));
  return (
    <div className={`menu ${className}`} ref={ref}>
      {button}
      {open ? <div className={`menu-pop menu-${align}`} role="menu" style={width ? { width } : undefined}>{children}</div> : null}
    </div>
  );
}
export function MenuItem({ children, onClick, to, icon, danger = false, active = false }) {
  const cls = `menu-item ${danger ? "is-danger" : ""} ${active ? "is-active" : ""}`;
  const inner = <>{icon ? <span className="menu-ico">{icon}</span> : null}<span className="menu-text">{children}</span></>;
  if (to) return <Link to={to} className={cls} role="menuitem" onClick={onClick}>{inner}</Link>;
  return <button type="button" className={cls} role="menuitem" onClick={onClick}>{inner}</button>;
}
export function MenuRule() { return <div className="menu-rule" />; }

export function Modal({ open, onClose, title: t, children, actions, width = 480 }) {
  const ref = useOutsideClose(open, onClose);
  useEffect(() => { if (open) ref.current?.querySelector("button, input, [tabindex]")?.focus(); }, [open, ref]);
  if (!open) return null;
  return (
    <div className="modal-backdrop">
      <div className="modal" role="dialog" aria-modal="true" aria-label={t} ref={ref} style={{ width }}>
        <div className="modal-head"><h2 className="modal-title">{t}</h2><button type="button" className="btn btn-quiet btn-icon" onClick={onClose} aria-label="Close">{Icons.close({})}</button></div>
        <div className="modal-body">{children}</div>
        {actions ? <div className="modal-actions">{actions}</div> : null}
      </div>
    </div>
  );
}

/* ---------- states ---------- */
export function EmptyState({ title: t, body, action, icon, compact = false }) {
  return (
    <div className={`empty ${compact ? "empty-compact" : ""}`}>
      {icon ? <span className="empty-ico">{icon}</span> : null}
      <span className="empty-title">{t}</span>
      {body ? <p className="empty-body">{body}</p> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}
export function LoadingState({ label = "Connecting to the Operon engine…", compact = false }) {
  return <div className={`loading ${compact ? "loading-compact" : ""}`} role="status"><span className="loading-bar" /><span className="t3">{label}</span></div>;
}
export function ErrorState({ title: t = "Something went wrong", body, action }) {
  return <div className="errstate" role="alert">{Icons.warn({})}<div><span className="errstate-title">{t}</span>{body ? <p className="t3">{body}</p> : null}</div>{action}</div>;
}
export function ConnectionBanner({ connected, frames }) {
  if (connected) return null;
  return <div className="conn-banner" role="status">{Icons.warn({ size: 14 })}<span>{frames ? "Engine stream disconnected. Showing the last mirrored state; reconnecting…" : "Waiting for the Operon engine on /ws. Start the backend with `uv run python run.py`."}</span></div>;
}
