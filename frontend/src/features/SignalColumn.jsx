import { useMemo, useState } from "react";
import { PanelHeader, Readout } from "../primitives/index.jsx";
import { num, risk as fmtRisk } from "../lib/format.js";
import { availableSeries, last, statusTone, viewOf } from "../state/selectors.js";
import { useInspector } from "../state/artifacts.jsx";

const W = 460, H = 210, PAD = { l: 34, r: 14, t: 12, b: 18 };

function scales(points, minSlots = 10) {
  const ts = points.map((p) => p.t ?? 0);
  const tmin = ts.length ? Math.min(...ts) : 0;
  const tmax = Math.max(ts.length ? Math.max(...ts) : 0, tmin + minSlots - 1);
  const x = (t) => PAD.l + ((t - tmin) / Math.max(1, tmax - tmin)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - Math.max(0, Math.min(1, v))) * (H - PAD.t - PAD.b);
  return { x, y, tmin, tmax };
}

export function SignalColumn({ state, focusId, incident }) {
  const insp = useInspector();
  const [hover, setHover] = useState(null);
  const points = state.histories?.[focusId] || [];
  const asset = state.fleet.find((a) => a.equipment_id === focusId);
  const view = viewOf(incident);
  const phase = incident?.lifecycle?.phase;
  const tone = statusTone(asset?.status);
  const cur = last(points), prev = points.length > 1 ? points[points.length - 2] : null;
  const series = useMemo(() => availableSeries(points), [points]);
  const plan = last(view.observation_plans);
  const observations = plan?.observations || [];
  const obsStart = observations.length ? points.length - observations.length : null; // index of first observation sample
  const outcome = last(view.outcomes);
  const signalEvidence = (view.evidence || []).find((e) => e.kind === "model_signal");
  const showMarkers = points.length <= 24;
  const { x, y, tmin, tmax } = scales(points);
  const trigger = state.triggerThreshold ?? 0.8, warn = state.warnThreshold ?? 0.45;
  const incidentT = incident ? (incident.created_tick ?? points.find((p) => (p.prob ?? 0) >= trigger)?.t) : null;
  const fleetTraces = !incident ? state.fleet.filter((a) => a.equipment_id !== focusId).map((a) => ({ id: a.equipment_id, pts: state.histories?.[a.equipment_id] || [] })).filter((s) => s.pts.length > 1) : [];
  const hovered = hover != null ? points[hover] : null;
  const shown = hovered || cur;
  const path = points.map((p) => `${x(p.t ?? 0).toFixed(1)},${y(p.prob ?? 0).toFixed(1)}`).join(" ");
  const onMove = (e) => {
    if (!points.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0, bd = Infinity;
    points.forEach((p, i) => { const d = Math.abs(x(p.t ?? 0) - px); if (d < bd) { bd = d; best = i; } });
    setHover(best);
  };
  const openPoint = (i) => {
    if (obsStart != null && i >= obsStart) { const ob = observations[i - obsStart]; if (ob?.artifact_id) insp.open(ob.artifact_id); }
    else if (incident && points[i]?.t === incidentT && signalEvidence?.artifact_id) insp.open(signalEvidence.artifact_id);
  };
  return (
    <section className="col col-signal" aria-label="Telemetry">
      <PanelHeader label={`Signal · ${focusId || "—"}`} meta={`${points.length} sample${points.length === 1 ? "" : "s"} · gate ${fmtRisk(trigger)}`} />
      <div className="col-scroll">
        <div className="sig-readout">
          <Readout value={shown?.prob} decimals={2} size="l" tone={hover != null ? "normal" : tone} delta={hover == null && prev && cur ? (cur.prob ?? 0) - (prev.prob ?? 0) : null} />
          <span className="sig-readout-l"><span className="lbl">Failure risk / 24 h</span><span className="t3">{hover != null ? `sample t${shown?.t}` : asset?.predicted_mode_label || "—"}</span></span>
        </div>
        <div className="sig-band well" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Failure risk over time">
            <defs><pattern id="sig-grid" width="8" height="8" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="var(--grid-dot)" /></pattern></defs>
            <rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={H - PAD.t - PAD.b} fill="url(#sig-grid)" />
            <rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={y(trigger) - PAD.t} fill="var(--crit)" opacity=".06" />
            <rect x={PAD.l} y={y(trigger)} width={W - PAD.l - PAD.r} height={y(warn) - y(trigger)} fill="var(--warn)" opacity=".05" />
            {obsStart != null && obsStart > 0 ? <rect x={(x(points[obsStart - 1].t) + x(points[obsStart].t)) / 2} y={PAD.t} width={x(tmax) - (x(points[obsStart - 1].t) + x(points[obsStart].t)) / 2} height={H - PAD.t - PAD.b} fill="var(--text-1)" opacity=".035" /> : null}
            <line x1={PAD.l} x2={W - PAD.r} y1={y(trigger)} y2={y(trigger)} stroke="var(--crit)" strokeDasharray="3 3" /><text x={4} y={y(trigger) + 3} className="sig-t">{fmtRisk(trigger)}</text>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(warn)} y2={y(warn)} stroke="var(--warn)" strokeDasharray="3 3" /><text x={4} y={y(warn) + 3} className="sig-t">{fmtRisk(warn)}</text>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)} stroke="var(--edge)" /><text x={4} y={y(0) + 3} className="sig-t">0.00</text>
            <text x={4} y={PAD.t + 3} className="sig-t">1.00</text>
            {fleetTraces.map((s) => <polyline key={s.id} fill="none" stroke="var(--text-4)" strokeWidth="1" points={s.pts.map((p) => `${x(p.t ?? 0)},${y(p.prob ?? 0)}`).join(" ")} />)}
            {incidentT != null ? <g><line x1={x(incidentT)} x2={x(incidentT)} y1={PAD.t} y2={H - PAD.b} stroke="var(--text-3)" /><text x={x(incidentT) + 4} y={PAD.t + 10} className="sig-a">incident</text></g> : null}
            {obsStart != null && obsStart > 0 ? <g><line x1={(x(points[obsStart - 1].t) + x(points[obsStart].t)) / 2} x2={(x(points[obsStart - 1].t) + x(points[obsStart].t)) / 2} y1={PAD.t} y2={H - PAD.b} stroke="var(--text-2)" /><text x={(x(points[obsStart - 1].t) + x(points[obsStart].t)) / 2 + 4} y={H - PAD.b - 6} className="sig-a">executed · observing</text></g> : null}
            {incident && view.intervention && !observations.length && ["PLANNING", "INTERVENTION_VALIDATED", "AWAITING_APPROVAL", "READY", "EXECUTING"].includes(phase) ? <g><line x1={x(tmax) - 26} x2={x(tmax) - 26} y1={PAD.t} y2={H - PAD.b} stroke="var(--brand)" strokeDasharray="2 3" /><text x={x(tmax) - 30} y={H - PAD.b - 6} textAnchor="end" className="sig-a sig-brand">{phase === "EXECUTING" ? "executing" : phase === "READY" ? "dispatching" : "planned window"}</text></g> : null}
            {points.length > 1 ? <polyline fill="none" stroke="var(--text-2)" strokeWidth="1.5" points={path} /> : null}
            {showMarkers ? points.map((p, i) => {
              const isLast = i === points.length - 1, inObs = obsStart != null && i >= obsStart, isIncident = incidentT != null && p.t === incidentT;
              const fill = isLast ? `var(--${tone === "normal" ? "text-2" : tone})` : isIncident ? "var(--crit)" : "var(--surface-1)";
              const stroke = inObs ? "var(--ok)" : "var(--text-2)";
              return (
                <g key={i} className={inObs || isIncident ? "sig-pt clickable" : "sig-pt"} onClick={() => openPoint(i)}>
                  <rect x={x(p.t ?? 0) - 3} y={y(p.prob ?? 0) - 3} width="6" height="6" fill={fill} stroke={stroke} strokeWidth="1.5" />
                  {inObs ? <text x={x(p.t ?? 0)} y={y(p.prob ?? 0) - 7} textAnchor="middle" className="sig-n">{i - obsStart + 1}</text> : null}
                </g>
              );
            }) : cur ? <circle cx={x(cur.t ?? 0)} cy={y(cur.prob ?? 0)} r="3" fill={`var(--${tone === "normal" ? "text-2" : tone})`} /> : null}
            {hovered ? <line x1={x(hovered.t ?? 0)} x2={x(hovered.t ?? 0)} y1={PAD.t} y2={H - PAD.b} stroke="var(--text-3)" strokeDasharray="1 2" /> : null}
            <text x={PAD.l} y={H - 4} className="sig-t">t{tmin}</text><text x={W - PAD.r} y={H - 4} textAnchor="end" className="sig-t">t{tmax}</text>
          </svg>
        </div>
        {outcome ? (
          <div className="sig-ba">
            <span className="lbl">Before → after</span>
            {Object.entries(outcome.before_metrics || {}).map(([k, v]) => (
              <span key={k} className="sig-ba-row"><span className="t3">{k.replaceAll("_", " ")}</span><span className="mono">{num(v, 2)}</span><span className="t4">→</span><span className="mono t1">{num(outcome.after_metrics?.[k], 2)}</span></span>
            ))}
          </div>
        ) : null}
        <div className="sig-strips">
          {series.map((s) => <Strip key={s.key} spec={s} points={points} hover={hover} />)}
          {!series.length ? <div className="sig-empty t3">No supporting telemetry in this snapshot.</div> : null}
        </div>
      </div>
    </section>
  );
}

function Strip({ spec, points, hover }) {
  const vals = points.map((p) => p[spec.key]).filter((v) => v != null);
  const shown = hover != null ? points[hover]?.[spec.key] : last(vals);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const pts = points.map((p, i) => `${(i / Math.max(1, points.length - 1)) * 120},${17 - ((p[spec.key] - min) / span) * 14}`).join(" ");
  const hx = hover != null ? (hover / Math.max(1, points.length - 1)) * 120 : null;
  return (
    <div className="strip">
      <span className="strip-n">{spec.label}</span>
      <svg viewBox="0 0 120 18" preserveAspectRatio="none" className="strip-svg" aria-hidden="true">
        {points.length > 1 ? <polyline fill="none" stroke="var(--text-3)" strokeWidth="1.2" points={pts} /> : null}
        {hx != null ? <line x1={hx} x2={hx} y1="0" y2="18" stroke="var(--text-3)" strokeWidth=".8" /> : null}
      </svg>
      <span className="strip-v mono">{num(shown, spec.d)}<small>{spec.unit}</small></span>
    </div>
  );
}
