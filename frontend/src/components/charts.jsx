// Inline SVG charts for analytics. Thin marks, recessive grid, hover crosshair + tooltip,
// legend for >= 2 series, table view behind a disclosure. Colours only through --chart-* tokens.
import { useMemo, useState } from "react";
import { num } from "../lib/format.js";

const PAD = { l: 36, r: 12, t: 10, b: 22 };

function niceTicks(min, max, n = 4, integer = false) {
  if (!(max > min)) return [min];
  const span = max - min, raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
  let step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n + 1) || mag;
  if (integer) step = Math.max(1, Math.round(step));
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

/** series: [{ id, label, points: [{t, v}], className }] — className carries s-1, s-2, tone-x or is-muted. */
export function LineChart({ series = [], width = 640, height = 220, yMin = 0, yMax = null, yLabel, xLabel = "tick", thresholds = [], formatValue = (v) => num(v, 2), emphasis = null, showLegend = true, ariaLabel }) {
  const [hover, setHover] = useState(null);
  const [hidden, setHidden] = useState(() => new Set());
  const visible = series.filter((s) => !hidden.has(s.id));
  const xs = useMemo(() => { const set = new Set(); for (const s of series) for (const p of s.points) if (p.t != null) set.add(p.t); return [...set].sort((a, b) => a - b); }, [series]);
  const ys = visible.flatMap((s) => s.points.map((p) => p.v)).filter((v) => v != null);
  const lo = yMin ?? Math.min(...ys), hi = yMax ?? (ys.length ? Math.max(...ys) * 1.05 : 1);
  const xmin = xs[0] ?? 0, xmax = xs[xs.length - 1] ?? 1;
  const x = (t) => PAD.l + ((t - xmin) / Math.max(1e-9, xmax - xmin)) * (width - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - lo) / Math.max(1e-9, hi - lo)) * (height - PAD.t - PAD.b);
  const ticks = niceTicks(lo, hi, 4);
  if (!xs.length) return <div className="chart-empty">No samples yet. Telemetry accumulates while the engine runs.</div>;
  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * width;
    let best = xs[0], bd = Infinity;
    for (const t of xs) { const d = Math.abs(x(t) - px); if (d < bd) { bd = d; best = t; } }
    setHover(best);
  };
  const tipRows = hover != null ? visible.map((s) => ({ s, v: s.points.find((p) => p.t === hover)?.v })).filter((r) => r.v != null) : [];
  const tipLeft = hover != null ? (x(hover) / width) * 100 : 0;
  return (
    <div className="chart">
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          <g className="chart-grid">{ticks.map((v) => <line key={v} x1={PAD.l} x2={width - PAD.r} y1={y(v)} y2={y(v)} />)}</g>
          {ticks.map((v) => <text key={`t${v}`} x={PAD.l - 6} y={y(v) + 3} textAnchor="end" className="chart-t">{formatValue(v)}</text>)}
          {thresholds.map((th) => <g key={th.label}><line x1={PAD.l} x2={width - PAD.r} y1={y(th.value)} y2={y(th.value)} className={`chart-thresh ${th.tone}`} /><text x={PAD.l + 4} y={y(th.value) - 4} className="chart-t">{th.label}</text></g>)}
          <line x1={PAD.l} x2={width - PAD.r} y1={y(lo)} y2={y(lo)} className="chart-axis" />
          {visible.map((s) => {
            const pts = s.points.filter((p) => p.v != null);
            if (pts.length < 2) return null;
            const muted = emphasis && emphasis !== s.id && !s.className?.includes("tone-");
            return <polyline key={s.id} className={`chart-line ${s.className || ""} ${muted ? "is-muted" : ""}`} points={pts.map((p) => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ")} />;
          })}
          {hover != null ? <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={height - PAD.b} className="chart-cross" /> : null}
          {hover != null ? tipRows.map(({ s, v }) => <circle key={s.id} cx={x(hover)} cy={y(v)} r="4" className={`chart-marker ${s.className || ""}`} />) : null}
          <text x={PAD.l} y={height - 6} className="chart-t">{xLabel} {xmin}</text>
          <text x={width - PAD.r} y={height - 6} textAnchor="end" className="chart-t">{xLabel} {xmax}</text>
          {yLabel ? <text x={PAD.l} y={PAD.t - 1} className="chart-l">{yLabel}</text> : null}
          <rect x={PAD.l} y={PAD.t} width={width - PAD.l - PAD.r} height={height - PAD.t - PAD.b} className="chart-hit" />
        </svg>
        {hover != null && tipRows.length ? (
          <div className="chart-tip" style={{ left: `${tipLeft}%`, top: `${(PAD.t / height) * 100 + 8}%` }}>
            <b>{xLabel} {hover}</b>
            {tipRows.slice(0, 8).map(({ s, v }) => <div key={s.id} className="tip-row"><span><span className={`swatch swatch-line ${s.className || ""}`} /> {s.label}</span><span className="mono">{formatValue(v)}</span></div>)}
          </div>
        ) : null}
      </div>
      {showLegend && series.length > 1 ? (
        <ul className="chart-legend">
          {series.map((s) => <li key={s.id} className={hidden.has(s.id) ? "is-hidden" : ""}><button type="button" onClick={() => setHidden((h) => { const n = new Set(h); n.has(s.id) ? n.delete(s.id) : n.add(s.id); return n; })} aria-pressed={!hidden.has(s.id)}><span className={`swatch swatch-line ${s.className || ""}`} />{s.label}</button></li>)}
        </ul>
      ) : null}
      <details className="chart-table"><summary>Table view</summary>
        <div className="dt-wrap"><table className="tbl tbl-mini"><thead><tr><th>{xLabel}</th>{series.map((s) => <th key={s.id} className="r">{s.label}</th>)}</tr></thead>
          <tbody>{xs.slice(-12).map((t) => <tr key={t}><td className="mono">{t}</td>{series.map((s) => <td key={s.id} className="r mono">{formatValue(s.points.find((p) => p.t === t)?.v ?? null)}</td>)}</tr>)}</tbody></table></div>
      </details>
    </div>
  );
}

/** Single-series categorical bars. items: [{ key, label, n, tone }] */
export function BarChart({ items = [], height = 180, width = 420, formatValue = (v) => String(v), ariaLabel, emptyLabel = "No data" }) {
  const [hover, setHover] = useState(null);
  if (!items.length || items.every((i) => !i.n)) return <div className="chart-empty">{emptyLabel}</div>;
  const max = Math.max(...items.map((i) => i.n), 1);
  const integer = items.every((i) => Number.isInteger(i.n));
  const ticks = niceTicks(0, max, 3, integer);
  const bw = (width - PAD.l - PAD.r) / items.length;
  const maxChars = Math.max(6, Math.floor(bw / 6.5));
  const y = (v) => PAD.t + (1 - v / (ticks[ticks.length - 1] || max)) * (height - PAD.t - PAD.b);
  return (
    <div className="chart">
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
          <g className="chart-grid">{ticks.map((v) => <line key={v} x1={PAD.l} x2={width - PAD.r} y1={y(v)} y2={y(v)} />)}</g>
          {ticks.map((v) => <text key={`t${v}`} x={PAD.l - 6} y={y(v) + 3} textAnchor="end" className="chart-t">{formatValue(v)}</text>)}
          <line x1={PAD.l} x2={width - PAD.r} y1={y(0)} y2={y(0)} className="chart-axis" />
          {items.map((it, i) => {
            const bx = PAD.l + i * bw + bw * 0.18, w = bw * 0.64, top = y(it.n), h = Math.max(0, y(0) - top);
            return (
              <g key={it.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={bx} y={top} width={w} height={h} className={`chart-bar ${it.tone ? `tone-${it.tone}` : "s-1"}`} rx="2" />
                <rect x={PAD.l + i * bw} y={PAD.t} width={bw} height={height - PAD.t - PAD.b} className="chart-hit" />
                <text x={bx + w / 2} y={height - 6} textAnchor="middle" className="chart-t">{it.label.length > maxChars ? `${it.label.slice(0, maxChars - 1)}…` : it.label}</text>
                {it.n ? <text x={bx + w / 2} y={top - 4} textAnchor="middle" className="chart-t">{formatValue(it.n)}</text> : null}
              </g>
            );
          })}
        </svg>
        {hover != null ? <div className="chart-tip" style={{ left: `${((PAD.l + hover * bw + bw / 2) / width) * 100}%`, top: `${(y(items[hover].n) / height) * 100}%` }}><b>{items[hover].label}</b><div className="tip-row"><span>count</span><span className="mono">{formatValue(items[hover].n)}</span></div></div> : null}
      </div>
    </div>
  );
}

/** Horizontal bar list for short categorical breakdowns. */
export function HBarList({ items = [], formatValue = (v) => String(v), emptyLabel = "No data" }) {
  if (!items.length) return <div className="chart-empty">{emptyLabel}</div>;
  const max = Math.max(...items.map((i) => i.n), 1);
  return (
    <div className="hbar-list">
      {items.map((it) => (
        <div key={it.key} className="hbar" title={`${it.label}: ${formatValue(it.n)}`}>
          <span className="hbar-l">{it.tone ? <span className={`swatch tone-${it.tone}`} /> : null}{it.label}</span>
          <span className="hbar-track"><span className={`hbar-fill ${it.tone ? `tone-${it.tone}` : ""}`} style={{ width: `${(it.n / max) * 100}%` }} /></span>
          <span className="hbar-v mono">{formatValue(it.n)}</span>
        </div>
      ))}
    </div>
  );
}
