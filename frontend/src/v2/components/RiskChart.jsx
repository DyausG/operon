// Risk trajectory chart (07 §16). Model risk score 0–1 against the backend thresholds only.
// X-axis in ticks until X8 (the stream has no server timestamps); the axis ends at the latest tick
// received ("now"), a stale region follows an asset's last sample, missing ticks break the line.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { segmentsOf } from "../model/freshness.js";
import { score } from "../model/format.js";
import { Provenance, Segmented } from "./ui.jsx";

function useWidth(ref, fallback = 560) {
  const [w, setW] = useState(fallback);
  useEffect(() => {
    if (!ref.current || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

const fmtTick = (t) => Number(t).toLocaleString("en-GB");

export function RiskChart({ points = [], latestTick, warn, trigger, title = "Risk trajectory", compact = false, assetId }) {
  const box = useRef(null);
  const width = useWidth(box, compact ? 280 : 560);
  const [view, setView] = useState("chart");
  const [cursor, setCursor] = useState(null);
  const summaryId = useId();
  const pts = useMemo(() => points.filter((p) => Number.isFinite(p?.t) && Number.isFinite(p?.prob)), [points]);

  if (!pts.length) {
    return (
      <figure className="wb-chart" aria-label={title}>
        <figcaption className="wb-chart-head"><span className="wb-chart-title">{title}</span></figcaption>
        <p className="wb-empty-line">No samples in this window.</p>
      </figure>
    );
  }

  const first = pts[0], last = pts[pts.length - 1];
  const end = Number.isFinite(latestTick) ? Math.max(latestTick, last.t) : last.t;
  const start = Math.min(first.t, end - 1);
  const height = compact ? 96 : 188;
  const pad = compact ? { l: 4, r: 4, t: 8, b: 6 } : { l: 36, r: 132, t: 12, b: 26 };
  const iw = Math.max(40, width - pad.l - pad.r), ih = height - pad.t - pad.b;
  const x = (t) => pad.l + ((t - start) / Math.max(1, end - start)) * iw;
  const y = (v) => pad.t + (1 - v) * ih;
  const { segments, gaps } = segmentsOf(pts);
  const behind = end - last.t;
  const stale = behind > 5;
  const crossed = Number.isFinite(trigger) ? pts.find((p) => p.prob >= trigger) : null;
  const summary = `Model risk score ${pts.length > 1 ? `moved from ${score(first.prob)} to ${score(last.prob)} between tick ${fmtTick(first.t)} and tick ${fmtTick(last.t)}` : `was ${score(last.prob)} at tick ${fmtTick(last.t)}`}`
    + (crossed ? `; at or above the action gate since tick ${fmtTick(crossed.t)}.` : ".")
    + (stale ? ` No data since tick ${fmtTick(last.t)}.` : "");
  const active = cursor != null ? pts[Math.min(cursor, pts.length - 1)] : null;

  const onKey = (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); setCursor((c) => Math.min(pts.length - 1, (c ?? pts.length - 1) + 1)); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); setCursor((c) => Math.max(0, (c ?? pts.length - 1) - 1)); }
    else if (e.key === "Escape") setCursor(null);
  };

  const thresholds = [
    Number.isFinite(warn) ? { v: warn, cls: "warn", label: `Warning band ${score(warn)}` } : null,
    Number.isFinite(trigger) ? { v: trigger, cls: "crit", label: `Action gate ${score(trigger)}` } : null,
  ].filter(Boolean);

  return (
    <figure className={`wb-chart ${compact ? "is-compact" : ""}`} aria-label={`${title}${assetId ? ` · ${assetId}` : ""}`}>
      <figcaption className="wb-chart-head">
        <span className="wb-chart-title">{title}</span>
        <span className="wb-chart-scope">
          Last {pts.length} samples · this run · x-axis in ticks (no server timestamps yet, X8)
        </span>
        {!compact ? (
          <Segmented label="Chart view" value={view} onChange={setView}
            options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]} />
        ) : null}
      </figcaption>
      <p className="wb-sr" id={summaryId}>{summary}</p>
      {view === "table" && !compact ? (
        <div className="wb-chart-table">
          <table className="wb-table">
            <caption className="wb-sr">{summary}</caption>
            <thead><tr><th scope="col">Tick</th><th scope="col" className="is-num">Model risk score</th><th scope="col">Provenance</th></tr></thead>
            <tbody>
              {pts.slice().reverse().map((p) => (
                <tr key={p.t}><td className="wb-num">{fmtTick(p.t)}</td><td className="wb-num is-num">{score(p.prob)}</td>
                  <td><span className="wb-marker"><Provenance kind="model" /> <span>Model-generated</span></span></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="wb-chart-plot" ref={box}>
          <svg width={width} height={height} role="img" aria-describedby={summaryId} tabIndex={compact ? -1 : 0}
            onKeyDown={compact ? undefined : onKey} onBlur={() => setCursor(null)} className="wb-chart-svg">
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <line key={v} x1={pad.l} x2={pad.l + iw} y1={y(v)} y2={y(v)} className="wb-viz-grid" />
            ))}
            {stale ? (
              <g>
                <rect x={x(last.t)} y={pad.t} width={Math.max(0, x(end) - x(last.t))} height={ih} className="wb-viz-stale" />
                {!compact ? <text x={x(last.t) + 6} y={pad.t + 14} className="wb-viz-label">No data since tick {fmtTick(last.t)}</text> : null}
              </g>
            ) : null}
            {gaps.map((g) => (
              !compact ? <text key={`${g.from}-${g.to}`} x={(x(g.from) + x(g.to)) / 2} y={pad.t + ih - 4} textAnchor="middle" className="wb-viz-label">
                No data ticks {fmtTick(g.from + 1)}–{fmtTick(g.to - 1)}
              </text> : null
            ))}
            {thresholds.map((th) => (
              <g key={th.cls}>
                <line x1={pad.l} x2={pad.l + iw} y1={y(th.v)} y2={y(th.v)} className={`wb-viz-th wb-viz-th-${th.cls}`} />
                {!compact ? <text x={pad.l + iw + 8} y={y(th.v) + 4} className="wb-viz-label">{th.label}</text> : null}
              </g>
            ))}
            {segments.map((seg, i) => (
              seg.length > 1
                ? <polyline key={i} points={seg.map((p) => `${x(p.t)},${y(p.prob)}`).join(" ")} className="wb-viz-series" />
                : <circle key={i} cx={x(seg[0].t)} cy={y(seg[0].prob)} r="2" className="wb-viz-point" />
            ))}
            <circle cx={x(last.t)} cy={y(last.prob)} r="3" className="wb-viz-last" />
            {!compact ? <text x={Math.min(x(last.t) + 6, pad.l + iw + 8)} y={y(last.prob) - 6} className="wb-viz-value">{score(last.prob)}</text> : null}
            {!compact ? (
              <g>
                <line x1={pad.l} x2={pad.l + iw} y1={pad.t + ih} y2={pad.t + ih} className="wb-viz-axis" />
                <text x={pad.l} y={height - 6} className="wb-viz-label">tick {fmtTick(start)}</text>
                <text x={pad.l + iw} y={height - 6} textAnchor="end" className="wb-viz-label">tick {fmtTick(end)} · latest received</text>
                {[0, 0.5, 1].map((v) => <text key={v} x={pad.l - 6} y={y(v) + 4} textAnchor="end" className="wb-viz-label">{v.toFixed(1)}</text>)}
              </g>
            ) : null}
            {active ? <line x1={x(active.t)} x2={x(active.t)} y1={pad.t} y2={pad.t + ih} className="wb-viz-cursor" /> : null}
          </svg>
          {!compact ? (
            <p className="wb-chart-foot">
              {active
                ? <>Tick {fmtTick(active.t)} · model risk score <span className="wb-num">{score(active.prob)}</span> · Model-generated (not a probability)</>
                : <>Model risk score (not a probability). Thresholds from the backend. Focus the chart and use ← → to read samples.</>}
            </p>
          ) : null}
        </div>
      )}
    </figure>
  );
}
