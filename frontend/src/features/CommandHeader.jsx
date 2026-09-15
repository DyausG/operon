import { Btn, Icons } from "../primitives/index.jsx";
import { elapsed } from "../lib/format.js";
import { usePulse } from "../motion/index.jsx";

export function CommandHeader({ state, focusId, onDemo, onReset, onStop, onResume, onToggleRecord, recordOpen }) {
  const demo = state.demoScenario || {}, prov = state.reasoningProvenance || {};
  const blink = usePulse(state.frames);
  const clockText = demo.active
    ? elapsed(demo.elapsed_seconds)
    : `+${String(Math.floor((state.plantMin || 0) / 60)).padStart(2, "0")}:${String((state.plantMin || 0) % 60).padStart(2, "0")}`;

  const isBedrockOnline = prov.status === "available" || prov.backend === "agentcore" || prov.model_provider === "bedrock";
  const bedrockLabel = isBedrockOnline ? "Bedrock: Connected" : "Bedrock: Standby (Local)";

  return (
    <header className="hdr">
      <div className="wordmark" title={state.meta.tagline}><span className="mark" />OPERON</div>

      <div className="hdr-badges" aria-label="System operational telemetry markers">
        <span className="hdr-badge badge-gate" title="Human-in-the-loop governance: automated actions require human sign-off">
          {Icons.shield({ size: 12 })}
          <span>Policy Gate: Enforced (HITL)</span>
        </span>
        <span
          className={`hdr-badge badge-bedrock ${isBedrockOnline ? "online" : "standby"}`}
          title={isBedrockOnline ? "AWS Bedrock runtime connected and available" : "AWS Bedrock in local standby; running deterministic benchmark trajectories"}
        >
          <span className={`status-dot ${isBedrockOnline ? "dot-online" : "dot-standby"}`} />
          <span>{bedrockLabel}</span>
        </span>
      </div>

      <div className="hdr-right">
        <span className="hdr-clock" title={demo.active ? "Guided Demo scenario elapsed" : "Plant operating time"}>{clockText}</span>
        <span className={`activity ${!state.connected ? "off" : blink ? "on" : ""}`} title={state.connected ? "Continuous telemetry stream active" : "Reconnecting"} />
        <button
          type="button"
          className={`btn btn-quiet btn-small btn-record ${recordOpen ? "is-active" : ""}`}
          onClick={onToggleRecord}
          aria-pressed={recordOpen}
          title="Toggle immutable event record"
        >
          {Icons.record({})}
          <span>Record</span>
        </button>
        {!demo.active && (
          <Btn quiet small className="btn-icon" onClick={state.running ? onStop : onResume} title={state.running ? "Pause simulator" : "Resume simulator"}>
            {state.running ? Icons.pause({}) : Icons.play({})}
          </Btn>
        )}
        <Btn small onClick={() => onDemo(focusId || "AC-COMP-01")} disabled={!!state.action.pending}>
          {Icons.demo({})}
          {demo.active ? "Restart demo" : "Start demo"}
        </Btn>
        <Btn quiet small onClick={onReset} title="Reset the engine">
          {Icons.reset({})}
          Reset
        </Btn>
      </div>
    </header>
  );
}
