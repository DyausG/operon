import { useEffect, useMemo, useState } from "react";
import { useReducedMotion } from "framer-motion";
import { AnimatePresence, motion, DUR, EASE } from "../../motion/index.jsx";
import { useInspector } from "../../state/artifacts.jsx";
import { ArtifactChip, Btn, Icons, IdToken, Stamp, Tag, Dot, KV, ProvenanceTag } from "../../primitives/index.jsx";
import { Renderer, ADVISORY_TYPES, TRUSTED_TYPES } from "./renderers.jsx";
import { rowIndex, statusTone } from "../../state/selectors.js";
import { dateTime, title, words } from "../../lib/format.js";

function authorityOf(artifact) {
  if (ADVISORY_TYPES.has(artifact.artifact_type)) return { kind: "advisory", label: "Advisory · AI reasoning" };
  if (TRUSTED_TYPES.has(artifact.artifact_type)) return { kind: "trusted", label: "Trusted input" };
  if (artifact.artifact_type === "approval_binding") return { kind: "human", label: "Human decision" };
  return { kind: "application", label: "Application record" };
}

export function InspectorTray({ view }) {
  const insp = useInspector();
  const reduce = useReducedMotion();
  const open = !!insp.current;
  const knownIds = useMemo(() => [...rowIndex(view).keys()], [view]);
  useEffect(() => { if (open) insp.prefetch(knownIds); }, [open, knownIds, insp]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
      if (e.key === "Escape") insp.close();
      else if (e.key === "Backspace") insp.back();
      else if (e.key === "ArrowLeft" || e.key === "ArrowRight") window.dispatchEvent(new CustomEvent("operon:sibling", { detail: e.key === "ArrowLeft" ? -1 : 1 }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, insp]);
  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.div key="backdrop" className="tray-backdrop" onClick={insp.close} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: DUR.std }} />
          <motion.aside key="tray" className="tray" role="dialog" aria-label="Artifact inspector" initial={reduce ? false : { x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={reduce ? { opacity: 0 } : { x: 40, opacity: 0 }} transition={{ duration: DUR.deliberate, ease: EASE }}>
            <Tray id={insp.current} />
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}

export function Tray({ id }) {
  const insp = useInspector();
  const { status, artifact } = insp.get(id);
  const [raw, setRaw] = useState(false);
  const [dir, setDir] = useState(1);
  const depth = insp.stack.length;
  const sibs = artifact ? insp.siblings(artifact.artifact_type) : [];
  const si = artifact ? sibs.findIndex((s) => s.id === artifact.id) : -1;
  const go = (nid, d = 1) => { setDir(d); insp.replace(nid); };
  useEffect(() => {
    const onSib = (e) => { const d = e.detail; const target = sibs[si + d]; if (target) go(target.id, d); };
    window.addEventListener("operon:sibling", onSib);
    return () => window.removeEventListener("operon:sibling", onSib);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="tray-inner">
      <div className="tray-nav">
        <Btn quiet small className="btn-icon" onClick={insp.back} disabled={depth < 2} aria-label="Back">{Icons.back({})}</Btn>
        <span className="tray-crumbs mono">{insp.stack.map((s, i) => <span key={`${s.id}-${i}`} className={i === depth - 1 ? "t1" : "t4"}>{i ? " / " : ""}{s.id}</span>)}</span>
        <span className="tray-sibs">
          <Btn quiet small className="btn-icon" disabled={si <= 0} onClick={() => go(sibs[si - 1].id, -1)} aria-label="Previous of same type">{Icons.prev({})}</Btn>
          <span className="mono t3">{si >= 0 ? `${si + 1}/${sibs.length}` : ""}</span>
          <Btn quiet small className="btn-icon" disabled={si < 0 || si >= sibs.length - 1} onClick={() => go(sibs[si + 1].id, 1)} aria-label="Next of same type">{Icons.next({})}</Btn>
        </span>
        <Btn quiet small className="btn-icon" onClick={insp.close} aria-label="Close inspector">{Icons.close({})}</Btn>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={id} className="tray-scroll" initial={{ opacity: 0, x: 12 * dir }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 * dir }} transition={{ duration: DUR.std, ease: EASE }}>
          {status === "loading" ? <div className="tray-loading"><Dot /><span className="t3">Reading artifact {id}…</span></div> : null}
          {status === "missing" ? <div className="tray-loading"><Tag tone="warn">Not resolvable</Tag><span className="t3">No detail record exists for {id} in the active read model.</span></div> : null}
          {artifact ? <Body artifact={artifact} raw={raw} setRaw={setRaw} /> : null}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

function Body({ artifact, raw, setRaw }) {
  const insp = useInspector();
  const auth = authorityOf(artifact);
  const tone = statusTone(artifact.status);
  const refs = insp.referencedBy(artifact.id);
  const isAdv = auth.kind === "advisory";
  return (
    <div className={`art art-${auth.kind}`}>
      <div className="art-pinned">
        <header className="art-head">
          <div className="art-kind">
            <Tag tone={isAdv ? "adv" : undefined} dashed={isAdv}>{title(artifact.artifact_type)}</Tag>
            <span className={`owner owner-${auth.kind}`}>{auth.label}</span>
            {artifact.synthesized ? <Tag tone="warn">Compact row · no detail endpoint</Tag> : null}
          </div>
          <h2 className="art-title">{artifact.title}</h2>
          <div className="art-status">
            {artifact.status ? (isAdv ? <Tag tone="adv" dashed><Dot tone="adv" dashed />{words(artifact.status)}</Tag> : <Stamp tone={tone === "ok" ? "ok" : tone === "crit" ? "crit" : tone === "warn" ? "pending" : "auth"}>{words(artifact.status)}</Stamp>) : null}
          </div>
        </header>
        <div className="kvgrid kvgrid-3 art-meta">
          <KV label="Artifact"><IdToken value={artifact.id} full /></KV>
          <KV label="Created" mono value={dateTime(artifact.created_at)} />
          <KV label="Source" mono value={artifact.source} />
          <KV label="Incident"><IdToken value={artifact.incident_id} full /></KV>
          <KV label="Equipment" mono value={artifact.equipment_id} />
          <KV label="Runtime" mono value={artifact.runtime || "Operon application"} />
          {artifact.reasoning ? <KV label="Reasoning"><ProvenanceTag reasoning={artifact.reasoning} compact /></KV> : null}
        </div>
        {artifact.summary ? <p className="art-summary">{artifact.summary}</p> : null}
      </div>

      <div className="art-scroll-body">
        <Renderer artifact={artifact} />
        <section className="lineage">
          <span className="lbl">Lineage</span>
          <div className="lineage-grid">
            <Lane label="Derived from" ids={artifact.parent_ids} empty="No parents" />
            <Lane label="Supported by" ids={artifact.supporting_ids} empty="No supporting artifacts" />
            <Lane label="Related" ids={artifact.related_ids} empty="No related artifacts" />
            <Lane label="Referenced by" ids={refs.map((r) => r.id)} empty="Nothing loaded references this yet" />
          </div>
        </section>
        <section className="rawjson">
          <button type="button" className="btn btn-quiet btn-small" onClick={() => setRaw((v) => !v)} aria-expanded={raw}>
            {Icons.json({})}
            {raw ? "Hide raw JSON" : "Raw JSON"}
          </button>
          {raw ? <pre className="raw">{JSON.stringify(artifact, null, 2)}</pre> : null}
        </section>
      </div>
    </div>
  );
}

function Lane({ label, ids = [], empty }) {
  return (
    <div className="lane">
      <span className="lane-l">{label}</span>
      {ids.length ? <div className="chips">{ids.map((id) => <ArtifactChip key={id} id={id} />)}</div> : <span className="t4 lane-empty">{empty}</span>}
    </div>
  );
}
