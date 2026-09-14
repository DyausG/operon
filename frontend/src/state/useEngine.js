import { useCallback, useEffect, useRef, useState } from "react";
import { initialState, reduce } from "./engineState.js";

function wsURL() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

/** One WebSocket to the Operon engine plus the human-in-the-loop actions. Contracts unchanged. */
export function useEngine() {
  const [state, setState] = useState(initialState);
  const wsRef = useRef(null);

  useEffect(() => {
    let stop = false, ws;
    const connect = () => {
      ws = new WebSocket(wsURL());
      wsRef.current = ws;
      ws.onopen = () => setState((p) => ({ ...p, connected: true }));
      ws.onclose = () => { setState((p) => ({ ...p, connected: false })); if (!stop) setTimeout(connect, 1200); };
      ws.onmessage = (ev) => { const msg = JSON.parse(ev.data); setState((prev) => reduce(prev, msg)); };
    };
    connect();
    return () => { stop = true; if (ws) ws.close(); };
  }, []);

  const post = useCallback(async (path, body) => {
    setState((p) => ({ ...p, action: { pending: path, error: null } }));
    try {
      const response = await fetch(path, { method: "POST", ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
      const result = await response.json();
      setState((p) => ({ ...p, action: { pending: null, error: result.ok === false ? result.error : null } }));
      return result;
    } catch (error) {
      setState((p) => ({ ...p, action: { pending: null, error: error.message } }));
      return { ok: false, error: error.message };
    }
  }, []);

  // Approval intent must name the exact requirement/intervention/hash/revision the operator saw.
  const intent = (a) => a?.lifecycle?.requirement_id ? {
    requirement_id: a.lifecycle.requirement_id, intervention_id: a.lifecycle.intervention_id,
    intervention_hash: a.lifecycle.intervention_hash, context_revision: a.lifecycle.context_revision,
  } : undefined;
  const approve = useCallback((a) => post(`/api/approve/${a?.equipment_id ?? a}`, intent(a)), [post]);
  const reject = useCallback((a) => post(`/api/reject/${a?.equipment_id ?? a}`, intent(a)), [post]);
  const reset = useCallback(() => post("/api/reset"), [post]);
  const stop = useCallback(() => post("/api/stop"), [post]);
  const resume = useCallback(() => post("/api/start"), [post]);
  const startDemo = useCallback((equipmentId) => post("/api/demo/scenario", { equipment_id: equipmentId }), [post]);
  const clearError = useCallback(() => setState((p) => ({ ...p, action: { ...p.action, error: null } })), []);

  return { state, approve, reject, reset, stop, resume, startDemo, clearError };
}
