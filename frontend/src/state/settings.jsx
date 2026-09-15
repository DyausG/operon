// Operator preferences. Every field here is frontend-only and stored in this browser;
// the engine has no preference store yet. Keep the list explicit so a later backend can adopt it.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { readJSON, writeJSON } from "../lib/storage.js";
import { setTimeMode } from "../lib/format.js";

const KEY = "operon.settings";
const Ctx = createContext(null);

export const DEFAULT_SETTINGS = {
  general: { timeMode: "utc", density: "comfortable", landing: "/app/dashboard" },
  notifications: { critical: true, approvals: true, maintenance: true, agent: true, connection: true, sound: false },
  agent: { showAdvisoryLane: true, confirmBeforeApprove: true, autoOpenDeepLink: true, defaultIncidentView: "auto" },
  plant: { showEconomics: true, sparklineWindow: 26 },
};

function merge(saved) {
  const out = {};
  for (const [k, v] of Object.entries(DEFAULT_SETTINGS)) out[k] = { ...v, ...(saved?.[k] || {}) };
  return out;
}

export function SettingsProvider({ children, initialSettings }) {
  const [settings, setSettings] = useState(() => merge(initialSettings ?? readJSON(KEY, null)));

  useEffect(() => {
    setTimeMode(settings.general.timeMode);
    if (typeof document !== "undefined") document.documentElement.setAttribute("data-density", settings.general.density);
  }, [settings.general.timeMode, settings.general.density]);

  const set = useCallback((section, patch) => {
    setSettings((prev) => {
      const next = { ...prev, [section]: { ...prev[section], ...patch } };
      writeJSON(KEY, next);
      return next;
    });
  }, []);
  const reset = useCallback(() => { const next = merge(null); writeJSON(KEY, next); setSettings(next); }, []);

  const value = useMemo(() => ({ settings, set, reset }), [settings, set, reset]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSettings() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSettings outside SettingsProvider");
  return ctx;
}
