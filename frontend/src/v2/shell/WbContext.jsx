// Shared V2 view model over the existing engine connection (no new transport, no backend change):
// receipt-time freshness (X8 fallback), derived cases, and a minute-resolution clock for deadlines.
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useEngineState } from "../../state/engine.jsx";
import { classifyStream, expectedInterval } from "../model/freshness.js";
import { compareCases, deriveCase } from "../model/cases.js";

const Ctx = createContext(null);

/** Records the browser receipt time of every new tick (the stream carries no server time, X8). */
function useArrivals(tick, frames) {
  const arrivals = useRef([]);
  const lastTick = useRef(null);
  if (tick !== lastTick.current && frames > 0) {
    lastTick.current = tick;
    arrivals.current = arrivals.current.concat(Date.now()).slice(-11);
  }
  return arrivals.current;
}

function useNow(stepMs) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), stepMs);
    return () => clearInterval(id);
  }, [stepMs]);
  return now;
}

export function WbProvider({ children }) {
  const engine = useEngineState();
  const { state } = engine;
  const arrivals = useArrivals(state.tick, state.frames);
  const now = useNow(1000);
  const interval = expectedInterval(arrivals);
  const lastReceipt = arrivals[arrivals.length - 1] ?? null;
  const fresh = { ...classifyStream({ connected: state.connected, running: state.running, lastReceipt, interval, now }), lastReceipt, interval, tick: state.tick };

  const value = useMemo(() => {
    const fleetById = Object.fromEntries((state.fleet || []).map((a) => [a.equipment_id, a]));
    const demo = state.demoScenario || {};
    const analysisPaused = state.reasoningProvenance?.status === "awaiting_runtime";
    const cases = Object.values(state.alerts || {})
      .map((a) => deriveCase(a, { fleetById, warn: state.warnThreshold, trigger: state.triggerThreshold, now, demoIncidentId: demo.active ? demo.incident_id : null, analysisPaused }))
      .filter(Boolean)
      .sort(compareCases);
    return { engine, state, fleetById, cases, now, analysisPaused, demo };
    // `now` advances once a second; derived deadlines re-evaluate with it (minute display only).
  }, [engine, state, now]);

  return <Ctx.Provider value={{ ...value, fresh }}>{children}</Ctx.Provider>;
}

export function useWb() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useWb outside WbProvider");
  return ctx;
}
