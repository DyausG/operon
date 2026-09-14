import { Btn, Icons, ProvenanceTag } from "../primitives/index.jsx";
import { elapsed } from "../lib/format.js";
import { usePulse } from "../motion/index.jsx";

export function CommandHeader({ state, focusId, onDemo, onReset, onStop, onResume, onToggleRecord, recordOpen }) {
  const demo = state.demoScenario || {}, prov = state.reasoningProvenance || {};
  const blink = usePulse(state.frames);
  const clockText = demo.active ? elapsed(demo.elapsed_seconds) : `+${String(Math.floor((state.plantMin || 0) / 60)).padStart(2, "0")}:${String((state.plantMin || 0) % 60).padStart(2, "0")}`;
  const runtimeLabel = demo.active ? null : prov.backend === "agentcore" ? "AgentCore · Bedrock" : prov.backend === "demo" ? "Typed advisory fixture" : prov.runtime || "Local runtime";
  return (
    <header className="hdr">
      <div className="wordmark" title={state.meta.tagline}><span className="mark" />OPERON</div>
      <span className="hdr-site truncate">{state.meta.plant || "—"}</span>
      <div className="ribbon" aria-label="Agents reason; the application owns authority"><span className="ribbon-a">Agents reason</span><i /><span className="ribbon-b">Application owns authority</span></div>
      <div className="hdr-right">
        {demo.active
          ? <ProvenanceTag provenance="SIMULATED" runtime={demo.runtime} live={false} />
          : <span className="tag" title={`reasoning backend ${prov.backend || "none"} · ${prov.status || ""}`}><span className={`dot ${prov.status === "available" ? "dot-auth" : ""}`} />{runtimeLabel}{prov.provenance ? <span className="prov-rt"> · {prov.provenance}</span> : null}</span>}
        <span className="hdr-clock" title={demo.active ? "scripted demo elapsed" : "plant time"}>{clockText}</span>
        <span className={`activity ${!state.connected ? "off" : blink ? "on" : ""}`} title={state.connected ? "stream connected" : "reconnecting"} />
        <button type="button" className="btn btn-quiet btn-small btn-record" onClick={onToggleRecord} aria-pressed={recordOpen} title="Record">{Icons.record({})}</button>
        {!demo.active && <Btn quiet small className="btn-icon" onClick={state.running ? onStop : onResume} title={state.running ? "Pause simulator" : "Resume simulator"}>{state.running ? Icons.pause({}) : Icons.play({})}</Btn>}
        <Btn small onClick={() => onDemo(focusId || "AC-COMP-01")} disabled={!!state.action.pending}>{Icons.demo({})}{demo.active ? "Restart guided demo" : "Start guided demo"}</Btn>
        <Btn quiet small onClick={onReset} title="Reset the engine">{Icons.reset({})}Reset</Btn>
      </div>
    </header>
  );
}
