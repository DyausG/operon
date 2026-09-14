import { useMemo, useState } from "react";
import { Inspectable, PanelHeader, When, Count, Tag } from "../primitives/index.jsx";
import { ledgerEntries } from "../state/selectors.js";
import { AnimatePresence, motion, DUR, EASE } from "../motion/index.jsx";
import { useReducedMotion } from "framer-motion";

const LANES = [["all", "All"], ["authority", "Authoritative"], ["advisory", "Advisory"]];

export function Record({ view, incident, state, className = "" }) {
  const [lane, setLane] = useState("all");
  const reduce = useReducedMotion();
  const entries = useMemo(() => ledgerEntries(view), [view]);
  const shown = lane === "all" ? entries : entries.filter((e) => (lane === "authority" ? e.lane !== "advisory" : e.lane === "advisory"));
  return (
    <section className={`col col-record ${className}`} aria-label="Record">
      <PanelHeader label="Record" meta={<><Count value={entries.length} /> entries</>}>
        <div className="lanes" role="tablist">
          {LANES.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={lane === k} className={`lane-btn ${lane === k ? "on" : ""}`} onClick={() => setLane(k)}>{l}</button>)}
        </div>
      </PanelHeader>
      <div className="col-scroll lg-list">
        {!incident ? (
          <div className="lg-empty">
            <span className="lbl">No incident record</span>
            <p className="t3">Monitoring {state.fleet.length || "—"} assets. A predictive signal at or above {Number(state.triggerThreshold ?? 0.8).toFixed(2)} opens a durable incident; every entry after that is evidence-bound.</p>
          </div>
        ) : null}
        <AnimatePresence initial={false}>
          {shown.map((e) => (
            <motion.div key={e.id} layout="position" initial={reduce ? false : { opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: DUR.std, ease: EASE }}>
              <Inspectable id={e.artifactId} className={`lg-row lg-lane-${e.lane}`}>
                <span className="lg-ln" />
                <span className="lg-body">
                  <span className="lg-title">{e.title}</span>
                  {e.detail ? <span className="lg-detail">{e.detail}</span> : null}
                </span>
                <span className="lg-meta">
                  {e.lane === "advisory" ? <span className="lg-adv">adv</span> : e.revision != null ? <span className="lg-rev">rev {e.revision}</span> : null}
                  <When iso={e.at} />
                </span>
              </Inspectable>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
}
