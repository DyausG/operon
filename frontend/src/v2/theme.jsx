// V2 theme (07 §5.3): follows the OS by default; override System / Light / Dark per browser.
// Independent of the legacy shell's theme so legacy pages stay unchanged during Phase 4.
// `?theme=light|dark|system` is a bootstrap override (shared links, screenshots), stored like a choice.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { readJSON, writeJSON } from "../lib/storage.js";

const KEY = "operon.v2.theme";
export const MODES = ["system", "light", "dark"];
const Ctx = createContext(null);

function prefersDark() {
  try { return window.matchMedia("(prefers-color-scheme: dark)").matches; } catch { return false; }
}

export function resolveTheme(mode, systemDark) {
  if (mode === "light" || mode === "dark") return mode;
  return systemDark ? "dark" : "light";
}

function initialMode(forced) {
  if (MODES.includes(forced)) return forced;
  try {
    const q = new URLSearchParams(window.location.search).get("theme");
    if (MODES.includes(q)) { writeJSON(KEY, q); return q; }
  } catch { /* SSR */ }
  const saved = readJSON(KEY, null);
  return MODES.includes(saved) ? saved : "system";
}

export function WbThemeProvider({ children, mode: forced }) {
  const [mode, setModeState] = useState(() => initialMode(forced));
  const [systemDark, setSystemDark] = useState(() => (typeof window === "undefined" ? false : prefersDark()));
  useEffect(() => {
    let mq;
    try { mq = window.matchMedia("(prefers-color-scheme: dark)"); } catch { return undefined; }
    const on = () => setSystemDark(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  const setMode = useCallback((next) => { if (MODES.includes(next)) { setModeState(next); writeJSON(KEY, next); } }, []);
  const resolved = resolveTheme(mode, systemDark);
  const value = useMemo(() => ({ mode, resolved, setMode }), [mode, resolved, setMode]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWbTheme() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useWbTheme outside WbThemeProvider");
  return ctx;
}
