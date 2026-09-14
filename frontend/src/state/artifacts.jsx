// Artifact detail access and the inspector navigation stack.
// Reads GET /api/demo/artifacts/{id}; falls back to the compact read-model row when the
// endpoint has no record (live mode, unknown id). Cache is scoped to a demo generation.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

const Ctx = createContext(null);

export function ArtifactProvider({ generation, rowIndex, children, fetcher }) {
  const cache = useRef(new Map());
  const inflight = useRef(new Map());
  const [tick, setTick] = useState(0);
  const [stack, setStack] = useState([]);
  const bump = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => { cache.current.clear(); inflight.current.clear(); setStack([]); bump(); }, [generation, bump]);

  const synthesize = useCallback((id) => {
    const row = rowIndex?.get(id);
    if (!row) return null;
    return {
      id, artifact_type: row.artifact_type || row.kind || row.event_type || "record", title: row.title || row.summary || id,
      status: row.status || null, created_at: row.created_at || null, incident_id: row.incident_id || null,
      equipment_id: row.equipment_id || row.asset_id || null, source: row.source_system || row.source || null,
      provenance: row.provenance || null, runtime: row.runtime || null, live_model: row.live_model ?? null,
      parent_ids: [], supporting_ids: [], related_ids: [], summary: row.summary || "", payload: row, synthesized: true,
    };
  }, [rowIndex]);

  const load = useCallback((id) => {
    if (!id || cache.current.has(id) || inflight.current.has(id)) return;
    const run = (fetcher || defaultFetcher)(id).then((art) => {
      cache.current.set(id, art || synthesize(id) || { id, missing: true });
    }).catch(() => { cache.current.set(id, synthesize(id) || { id, missing: true }); })
      .finally(() => { inflight.current.delete(id); bump(); });
    inflight.current.set(id, run);
  }, [fetcher, synthesize, bump]);

  const get = useCallback((id) => {
    if (!id) return { status: "missing", artifact: null };
    const hit = cache.current.get(id);
    if (hit) return hit.missing ? { status: "missing", artifact: null } : { status: "ready", artifact: hit };
    load(id);
    return { status: "loading", artifact: null };
  }, [load]);

  // Reverse references from everything loaded so far.
  const referencedBy = useCallback((id) => {
    const out = [];
    for (const art of cache.current.values()) {
      if (art.missing) continue;
      for (const field of ["parent_ids", "supporting_ids", "related_ids"]) {
        if ((art[field] || []).includes(id)) out.push({ id: art.id, via: field });
      }
    }
    return out;
  }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const siblings = useCallback((type) => {
    return [...cache.current.values()].filter((a) => !a.missing && a.artifact_type === type)
      .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)) || a.id.localeCompare(b.id));
  }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const prefetch = useCallback((ids) => { for (const id of ids || []) load(id); }, [load]);

  const open = useCallback((id) => { if (id) setStack([{ id }]); }, []);
  const push = useCallback((id) => { if (id) setStack((s) => (s[s.length - 1]?.id === id ? s : [...s, { id }])); }, []);
  const replace = useCallback((id) => { if (id) setStack((s) => (s.length ? [...s.slice(0, -1), { id }] : [{ id }])); }, []);
  const back = useCallback(() => setStack((s) => s.slice(0, -1)), []);
  const close = useCallback(() => setStack([]), []);

  const value = useMemo(() => ({ get, load, prefetch, referencedBy, siblings, stack, open, push, replace, back, close, tick, current: stack[stack.length - 1]?.id || null }),
    [get, load, prefetch, referencedBy, siblings, stack, open, push, replace, back, close, tick]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useInspector() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useInspector outside ArtifactProvider");
  return ctx;
}

async function defaultFetcher(id) {
  const res = await fetch(`/api/demo/artifacts/${encodeURIComponent(id)}`);
  if (!res.ok) return null;
  const data = await res.json();
  return data && data.ok !== false && data.id ? data : null;
}
