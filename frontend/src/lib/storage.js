// Guarded browser storage. Every accessor tolerates SSR, private windows and blocked site data.
const memory = new Map();

function area(kind) {
  try {
    if (typeof window === "undefined") return null;
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

export function readJSON(key, fallback = null, kind = "local") {
  const store = area(kind);
  try {
    const raw = store ? store.getItem(key) : memory.get(`${kind}:${key}`);
    if (raw == null) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function writeJSON(key, value, kind = "local") {
  const store = area(kind);
  try {
    const raw = JSON.stringify(value);
    if (store) store.setItem(key, raw); else memory.set(`${kind}:${key}`, raw);
    return true;
  } catch {
    return false;
  }
}

export function remove(key, kind = "local") {
  const store = area(kind);
  try {
    if (store) store.removeItem(key); else memory.delete(`${kind}:${key}`);
  } catch { /* ignore */ }
}

/** Remove every Operon key from both storage areas (Settings → "Clear local data"). */
export function clearOperonKeys() {
  for (const kind of ["local", "session"]) {
    const store = area(kind);
    if (!store) continue;
    try {
      const keys = [];
      for (let i = 0; i < store.length; i += 1) { const k = store.key(i); if (k && k.startsWith("operon.")) keys.push(k); }
      keys.forEach((k) => store.removeItem(k));
    } catch { /* ignore */ }
  }
  memory.clear();
}
