import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

export const DUR = { instant: 0.08, quick: 0.12, std: 0.2, deliberate: 0.32, slow: 0.48 };
export const EASE = [0.2, 0.7, 0.2, 1];

/** Fade + 4px rise on mount; used for stage objects and rows. */
export function Reveal({ children, delay = 0, y = 4, className, as = "div", layout = false, ...rest }) {
  const reduce = useReducedMotion();
  const M = motion[as] || motion.div;
  return (
    <M className={className} layout={layout ? "position" : undefined}
      initial={reduce ? false : { opacity: 0, y }} animate={{ opacity: 1, y: 0 }} exit={reduce ? undefined : { opacity: 0, y: -y }}
      transition={{ duration: DUR.std, ease: EASE, delay }} {...rest}>{children}</M>
  );
}

/** Stage swap: crossfade the phase object keyed by phase. */
export function Swap({ id, children, className }) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={id} className={className} initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
        exit={reduce ? undefined : { opacity: 0, y: -4, transition: { duration: DUR.quick } }} transition={{ duration: DUR.deliberate, ease: EASE }}>{children}</motion.div>
    </AnimatePresence>
  );
}

export { AnimatePresence, motion };

/** Interpolate a number toward its target with tabular figures (readouts, counts). */
export function useAnimatedNumber(target, { duration = 480, decimals = 2 } = {}) {
  const reduce = useReducedMotion();
  const [value, setValue] = useState(target ?? 0);
  const fromRef = useRef(target == null ? null : Number(target));
  useEffect(() => {
    if (target == null || Number.isNaN(Number(target))) return;
    const from = fromRef.current, to = Number(target);
    // First real value shows immediately; only later changes interpolate.
    if (reduce || from == null || from === to) { fromRef.current = to; setValue(to); return; }
    let raf, start;
    const step = (ts) => {
      if (start == null) start = ts;
      const t = Math.min(1, (ts - start) / duration);
      const v = from + (to - from) * t;
      setValue(v);
      if (t < 1) raf = requestAnimationFrame(step); else fromRef.current = to;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, duration, reduce]);
  return Number(value).toFixed(decimals);
}

/** Flash a class briefly when `dep` changes (activity blink). */
export function usePulse(dep, ms = 160) {
  const [on, setOn] = useState(false);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    setOn(true);
    const t = setTimeout(() => setOn(false), ms);
    return () => clearTimeout(t);
  }, [dep, ms]);
  return on;
}
