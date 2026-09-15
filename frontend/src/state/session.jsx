// Demo sign-in session. The Operon host has no authentication layer (see server/main.py);
// this session exists only in the operator's browser and never reaches the backend.
// It is labelled as such in the UI. Nothing here grants authority: approvals still carry the
// exact requirement/intervention/hash/revision the lifecycle service demands.
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { readJSON, remove, writeJSON } from "../lib/storage.js";

const KEY = "operon.session";
const Ctx = createContext(null);

export const ROLES = [
  { id: "maintenance_approver", label: "Maintenance approver" },
  { id: "reliability_engineer", label: "Reliability engineer" },
  { id: "plant_operator", label: "Plant operator" },
  { id: "observer", label: "Observer" },
];

export function initialsOf(name = "") {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "OP";
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

function displayNameFrom(email) {
  const local = String(email).split("@")[0] || "operator";
  return local.split(/[._-]+/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ") || "Operator";
}

export function validateCredentials({ email, password }) {
  const errors = {};
  const e = String(email || "").trim();
  if (!e) errors.email = "Enter your work email.";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) errors.email = "That does not look like an email address.";
  const p = String(password || "");
  if (!p) errors.password = "Enter your password.";
  else if (p.length < 8) errors.password = "Passwords are at least 8 characters.";
  return errors;
}

function readSaved() {
  return readJSON(KEY, null, "local") || readJSON(KEY, null, "session");
}

export function SessionProvider({ children, initialSession = undefined }) {
  const [session, setSession] = useState(() => (initialSession !== undefined ? initialSession : readSaved()));

  const persist = useCallback((next) => {
    remove(KEY, "local"); remove(KEY, "session");
    if (next) writeJSON(KEY, next, next.remember ? "local" : "session");
    setSession(next);
  }, []);

  const signIn = useCallback(async ({ email, password, remember = false }) => {
    const errors = validateCredentials({ email, password });
    if (Object.keys(errors).length) return { ok: false, errors };
    // Simulated latency keeps the loading state honest without pretending a server answered.
    await new Promise((r) => setTimeout(r, 350));
    const next = {
      email: String(email).trim().toLowerCase(),
      name: displayNameFrom(email),
      role: "maintenance_approver",
      remember: !!remember,
      signedInAt: new Date().toISOString(),
      mode: "demo",
    };
    persist(next);
    return { ok: true, session: next };
  }, [persist]);

  const signOut = useCallback(() => persist(null), [persist]);
  const update = useCallback((patch) => setSession((prev) => { if (!prev) return prev; const next = { ...prev, ...patch }; persist(next); return next; }), [persist]);

  const value = useMemo(() => ({ session, signedIn: !!session, signIn, signOut, update }), [session, signIn, signOut, update]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
