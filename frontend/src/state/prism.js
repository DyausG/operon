// Operator-message client for the PRISM runtime (Stage 1). Holds no authority: it posts to
// /api/prism and mirrors what the server accepts. Session views arrive over the websocket.
import { useCallback, useMemo, useRef, useState } from "react";
import { prismSessionFor } from "./agentRuntime.js";

const requestId = () => (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `req-${Date.now()}-${Math.random().toString(16).slice(2)}`);

async function postJSON(path, body) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const result = await response.json().catch(() => ({ ok: false, error: `HTTP ${response.status}` }));
  return { status: response.status, ...result };
}

/** { session, send(text), pending, error, last } for the PRISM session bound to the selected incident. */
export function usePrismSession(incident, state) {
  const session = useMemo(() => prismSessionFor(incident, state), [incident, state]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [last, setLast] = useState(null);
  const creating = useRef(null);
  const incidentId = incident?.incident_id || null;

  const ensureSession = useCallback(async () => {
    if (session?.session_id) return session.session_id;
    if (!creating.current) {
      creating.current = postJSON("/api/prism/sessions", incidentId ? { incident_id: incidentId } : {})
        .then((r) => { creating.current = null; if (!r.ok) throw new Error(r.error || "session refused"); return r.session.session_id; })
        .catch((err) => { creating.current = null; throw err; });
    }
    return creating.current;
  }, [session?.session_id, incidentId]);

  const send = useCallback(async (content) => {
    setPending(true); setError(null);
    try {
      const id = await ensureSession();
      const rid = requestId();
      const r = await postJSON(`/api/prism/sessions/${id}/messages`, { content, content_type: "text", request_id: rid, idempotency_key: rid });
      if (!r.ok) throw new Error(r.error || `message refused (${r.status})`);
      setLast(r);
      return r;
    } catch (err) {
      setError(err.message);
      return { ok: false, error: err.message };
    } finally {
      setPending(false);
    }
  }, [ensureSession]);

  return { session, send, pending, error, last };
}
