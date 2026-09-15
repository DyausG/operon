// Theme mode: light | dark | system. Persisted in this browser; resolved to an explicit
// data-theme attribute on <html> so every token has one source of truth.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { readJSON, writeJSON } from "../lib/storage.js";

const KEY = "operon.theme";
export const THEME_MODES = ["light", "dark", "system"];
const Ctx = createContext(null);

function systemPrefersDark() {
  try { return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches; } catch { return true; }
}
function resolve(mode) { return mode === "system" ? (systemPrefersDark() ? "dark" : "light") : mode; }

function readInitialMode() {
  // ?theme=light|dark is a bootstrap override (useful for screenshots and shared links); it is persisted like a choice.
  try {
    const q = typeof location !== "undefined" ? new URLSearchParams(location.search).get("theme") : null;
    if (q && THEME_MODES.includes(q)) { writeJSON(KEY, q); return q; }
  } catch { /* ignore */ }
  const saved = readJSON(KEY, null);
  return THEME_MODES.includes(saved) ? saved : "dark";
}

export function applyTheme(resolved) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.style.colorScheme = resolved;
}

export function ThemeProvider({ children, initialMode }) {
  const [mode, setModeState] = useState(() => initialMode || readInitialMode());
  const [resolved, setResolved] = useState(() => resolve(initialMode || readInitialMode()));

  useEffect(() => {
    const r = resolve(mode);
    setResolved(r);
    applyTheme(r);
    if (mode !== "system" || typeof window === "undefined") return undefined;
    let mq;
    try { mq = window.matchMedia("(prefers-color-scheme: dark)"); } catch { return undefined; }
    const onChange = () => { const next = resolve("system"); setResolved(next); applyTheme(next); };
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, [mode]);

  const setMode = useCallback((next) => {
    if (!THEME_MODES.includes(next)) return;
    setModeState(next);
    writeJSON(KEY, next);
  }, []);
  const toggle = useCallback(() => setMode(resolved === "dark" ? "light" : "dark"), [resolved, setMode]);

  const value = useMemo(() => ({ mode, resolved, setMode, toggle }), [mode, resolved, setMode, toggle]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme outside ThemeProvider");
  return ctx;
}
