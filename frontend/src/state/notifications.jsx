// Notifications derive from engine state the client has actually observed (the stream event log
// plus current incident phases). Read state is browser-local. No event is invented here.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { readJSON, writeJSON } from "../lib/storage.js";
import { useEngineState } from "./engine.jsx";
import { useSettings } from "./settings.jsx";
import { title } from "../lib/format.js";

const KEY = "operon.notifications.read";
const Ctx = createContext(null);

const PHASE_NOTES = {
  OPEN: { category: "critical", tone: "crit", title: "Incident opened" },
  AWAITING_EVIDENCE: { category: "agent", tone: "warn", title: "Trusted evidence required" },
  AWAITING_APPROVAL: { category: "approvals", tone: "warn", title: "Approval required", action: true },
  READY: { category: "maintenance", tone: "auth", title: "Work package dispatching" },
  EXECUTING: { category: "maintenance", tone: "auth", title: "Work order executing" },
  OBSERVING: { category: "agent", tone: "auth", title: "Observing recovery" },
  CLOSED: { category: "maintenance", tone: "ok", title: "Incident closed" },
  ESCALATED: { category: "critical", tone: "crit", title: "Incident escalated" },
  EXECUTION_FAILED: { category: "critical", tone: "crit", title: "Execution failed" },
  CANCELLED: { category: "critical", tone: "crit", title: "Incident cancelled" },
};

/** Turn one stream-log entry into a notification, or null when it is not operator-facing. */
export function notificationFor(entry, state) {
  const machine = entry.id ? state.fleet.find((a) => a.equipment_id === entry.id) : null;
  const name = machine?.name || entry.id || "";
  const base = { id: `n:${entry.seq}`, at: entry.at, machineId: entry.id || null, incidentId: entry.incidentId || null, seq: entry.seq };
  switch (entry.kind) {
    case "alert": {
      const note = PHASE_NOTES[entry.phase];
      if (!note) return null;
      return { ...base, ...note, body: entry.reason || `${name} · ${title(entry.phase)}` };
    }
    case "outcome":
      return { ...base, category: "agent", tone: entry.result === "VERIFIED_RECOVERY" ? "ok" : "warn", title: entry.result ? title(entry.result) : "Outcome recorded", body: `${name} · ${title(entry.phase || "")}` };
    case "resolved":
      return { ...base, category: "maintenance", tone: "ok", title: "Intervention dispatched", body: `${name}${entry.outcome ? ` · ${title(entry.outcome)}` : ""}` };
    case "rejected":
      return { ...base, category: "approvals", tone: "crit", title: "Plan rejected", body: `${name} · operator rejected the exact plan` };
    case "failure":
      return { ...base, category: "critical", tone: "crit", title: "Unplanned failure", body: `${name} failed without intervention` };
    case "error":
      return { ...base, category: "agent", tone: "crit", title: "Action refused", body: entry.error || "" };
    case "control":
      return { ...base, category: "connection", tone: "normal", title: entry.running ? "Simulator resumed" : "Simulator paused", body: "Engine control" };
    case "reset":
      return { ...base, category: "connection", tone: "normal", title: "Engine reset", body: "All incidents and telemetry cleared" };
    case "demo":
      if (!entry.status || !["factory_healthy", "awaiting_human_approval", "complete", "cancelled", "failed"].includes(entry.status)) return null;
      return { ...base, category: "agent", tone: entry.status === "awaiting_human_approval" ? "warn" : entry.status === "failed" ? "crit" : "normal", title: entry.status === "factory_healthy" ? "Guided Demo started" : entry.status === "failed" ? "Guided Demo failed" : title(entry.status), body: `Guided Demo scenario · ${entry.id || ""}` };
    default:
      return null;
  }
}

export function NotificationsProvider({ children }) {
  const { state } = useEngineState();
  const { settings } = useSettings();
  const [read, setRead] = useState(() => new Set(readJSON(KEY, [])));

  const items = useMemo(() => {
    const enabled = settings.notifications;
    const out = [];
    for (const entry of state.eventLog || []) {
      const n = notificationFor(entry, state);
      if (!n || enabled[n.category] === false) continue;
      out.push({ ...n, read: read.has(n.id) });
    }
    return out;
  }, [state, settings.notifications, read]);

  const unread = useMemo(() => items.filter((n) => !n.read).length, [items]);
  const needsAction = useMemo(() => Object.values(state.alerts || {}).filter((a) => (a.lifecycle?.phase || a.status) === "AWAITING_APPROVAL").length, [state.alerts]);

  const persist = useCallback((next) => { setRead(next); writeJSON(KEY, [...next].slice(-500)); }, []);
  const markRead = useCallback((id) => setRead((prev) => { if (prev.has(id)) return prev; const next = new Set(prev); next.add(id); writeJSON(KEY, [...next].slice(-500)); return next; }), []);
  const markAllRead = useCallback(() => persist(new Set([...read, ...items.map((n) => n.id)])), [items, read, persist]);
  const markUnread = useCallback((id) => setRead((prev) => { const next = new Set(prev); next.delete(id); writeJSON(KEY, [...next]); return next; }), []);

  useEffect(() => { if (state.generation) { /* generation change keeps read ids; ids are per-seq so nothing collides */ } }, [state.generation]);

  const value = useMemo(() => ({ items, unread, needsAction, markRead, markAllRead, markUnread }), [items, unread, needsAction, markRead, markAllRead, markUnread]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useNotifications() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useNotifications outside NotificationsProvider");
  return ctx;
}
