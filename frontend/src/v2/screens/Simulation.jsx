// System → Simulation & Demo (08 screen 19), minimal and functional for Phase 4A: the engine and
// Guided Demo controls leave the operational header and live here. Not a review target.
import { useEffect, useRef, useState } from "react";
import { useWb } from "../shell/WbContext.jsx";
import { usePageTitle } from "../shell/WbShell.jsx";
import { Button, EmptyLine, FreshnessIndicator, InlineAlert, Ledger, SectionHeading, TitleBlock } from "../components/ui.jsx";
import { sentence } from "../model/format.js";

function ResetDialog({ onCancel, onConfirm, busy }) {
  const [text, setText] = useState("");
  const input = useRef(null);
  useEffect(() => { input.current?.focus(); }, []);
  return (
    <div className="wb-drawer-layer">
      <div className="wb-scrim" aria-hidden="true" />
      <div className="wb-dialog" role="alertdialog" aria-modal="true" aria-labelledby="reset-title" aria-describedby="reset-desc"
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}>
        <h2 className="wb-pane-title" id="reset-title">Reset the engine?</h2>
        <p id="reset-desc">This clears runtime state (cases, evidence, work orders created in this run) and restarts the simulation. It can’t be undone. Type RESET to confirm.</p>
        <label className="wb-label" htmlFor="reset-confirm">Confirmation</label>
        <input id="reset-confirm" ref={input} className="wb-input" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />
        <div className="wb-dialog-actions">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button variant="danger" inactive={text !== "RESET"} reasonId="reset-desc" onBlocked={() => input.current?.focus()} busy={busy} busyLabel="Resetting…" onClick={onConfirm}>Reset engine</Button>
        </div>
      </div>
    </div>
  );
}

export function Simulation() {
  usePageTitle("Simulation & Demo");
  const { state, engine, fresh, demo } = useWb();
  const [asset, setAsset] = useState("AC-COMP-01");
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const pending = state.action?.pending;
  const assets = state.fleet || [];
  const cells = [
    { label: "Engine", value: state.running ? `Running · tick ${state.tick.toLocaleString("en-GB")}` : `Paused · tick ${state.tick.toLocaleString("en-GB")}` },
    { label: "Guided demo", value: demo?.active ? sentence(demo.status || "active") : "Not active" },
    { label: "Data", value: "Simulated plant" },
  ];
  return (
    <div className="wb-page wb-settings-page">
      <header className="wb-page-head">
        <p className="wb-crumbs">System</p>
        <h1 className="wb-page-title">Simulation & Demo</h1>
        <TitleBlock label="Simulation summary" cells={cells} end={<FreshnessIndicator fresh={fresh} />} />
      </header>
      {state.action?.error ? <InlineAlert tone="critical" title="The engine refused the request">{state.action.error}</InlineAlert> : null}
      <section className="wb-region" aria-labelledby="sim-1">
        <SectionHeading index="01" id="sim-1" title="Simulator" meta="Simulated telemetry for every asset" />
        <div className="wb-row-actions">
          <Button variant="secondary" disabled={!state.running} busy={pending === "/api/stop"} busyLabel="Pausing…" onClick={engine.stop}>Pause simulation</Button>
          <Button variant="secondary" disabled={state.running} busy={pending === "/api/start"} busyLabel="Resuming…" onClick={engine.resume}>Resume</Button>
        </div>
      </section>
      <section className="wb-region" aria-labelledby="sim-2">
        <SectionHeading index="02" id="sim-2" title="Guided demo" meta="Runs the real lifecycle with simulated inputs (inspection, resources)" />
        <div className="wb-row-actions">
          <label className="wb-label" htmlFor="demo-asset">Asset</label>
          <select id="demo-asset" className="wb-select" value={asset} onChange={(e) => setAsset(e.target.value)}>
            {(assets.length ? assets : [{ equipment_id: "AC-COMP-01" }]).map((a) => <option key={a.equipment_id} value={a.equipment_id}>{a.equipment_id}{a.name ? ` · ${a.name}` : ""}</option>)}
          </select>
          <Button variant="primary" busy={pending === "/api/demo/scenario"} busyLabel="Starting…" onClick={() => engine.startDemo(asset)}>Start guided demo</Button>
        </div>
        {demo?.active ? (
          <Ledger rows={[
            { label: "Status", value: sentence(demo.status) },
            { label: "Phase", value: demo.phase || "Not reported" },
            { label: "Approval state", value: demo.approval_state ? sentence(demo.approval_state) : "Not requested" },
            { label: "Elapsed", value: Number.isFinite(demo.elapsed_seconds) ? `${demo.elapsed_seconds} s` : "Not reported" },
            { label: "Reasoning", value: demo.reasoning?.runtime || "Not reported" },
            demo.error ? { label: "Error", value: demo.error } : null,
          ]} />
        ) : <EmptyLine>No guided demo is running. Approvals in a demo are real lifecycle decisions on simulated inputs.</EmptyLine>}
      </section>
      <section className="wb-region" aria-labelledby="sim-3">
        <SectionHeading index="03" id="sim-3" title="Reset" meta="Clears runtime state and restarts the simulation" />
        <Button variant="danger" onClick={() => setConfirming(true)}>Reset engine…</Button>
      </section>
      {confirming ? (
        <ResetDialog busy={resetting} onCancel={() => setConfirming(false)}
          onConfirm={async () => { setResetting(true); await engine.reset(); setResetting(false); setConfirming(false); }} />
      ) : null}
    </div>
  );
}
