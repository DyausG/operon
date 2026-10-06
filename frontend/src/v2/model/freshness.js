// Stream freshness (07 §15.1) with the X8 fallback: the stream carries tick indices and simulated
// plant minutes but no server wall-clock time. Until X8, ages come from the browser's *receipt*
// time and the expected interval is the median gap between recent arrivals (never hard-coded).

export const ARRIVAL_WINDOW = 10; // gaps measured over the last 10 ticks

/** Median of consecutive gaps over the last `window` arrivals (ms). Null until two arrivals. */
export function expectedInterval(arrivals, window = ARRIVAL_WINDOW) {
  const recent = arrivals.slice(-(window + 1));
  if (recent.length < 2) return null;
  const gaps = [];
  for (let i = 1; i < recent.length; i += 1) gaps.push(recent[i] - recent[i - 1]);
  gaps.sort((a, b) => a - b);
  const mid = Math.floor(gaps.length / 2);
  return gaps.length % 2 ? gaps[mid] : (gaps[mid - 1] + gaps[mid]) / 2;
}

/**
 * Classify the stream. States: live · delayed · stale · disconnected (07 §15.1), plus
 * `paused` (engine running = false; 08 screen 23) and `measuring` (connected, but too few
 * arrivals to know the expected interval, so "Live" can't be proven yet).
 */
export function classifyStream({ connected, running, lastReceipt, interval, now }) {
  if (!connected) return { state: "disconnected", ageMs: lastReceipt ? now - lastReceipt : null };
  if (running === false) return { state: "paused", ageMs: lastReceipt ? now - lastReceipt : null };
  if (!lastReceipt) return { state: "waiting", ageMs: null };
  const ageMs = now - lastReceipt;
  if (!interval) return { state: "measuring", ageMs };
  if (ageMs <= 2 * interval) return { state: "live", ageMs };
  if (ageMs <= 5 * interval) return { state: "delayed", ageMs };
  return { state: "stale", ageMs };
}

export const FRESHNESS_LABEL = {
  live: "Live", delayed: "Delayed", stale: "Stale", disconnected: "Disconnected",
  paused: "Simulation paused", measuring: "Connected", waiting: "Waiting for plant data",
};

/** Per-asset staleness: ticks behind the latest tick (until X8). Stale beyond 5 expected ticks. */
export function assetLag(history, latestTick) {
  const last = history?.length ? history[history.length - 1].t : null;
  if (last == null || !Number.isFinite(latestTick)) return { lastTick: last, behind: null, stale: last == null };
  const behind = Math.max(0, latestTick - last);
  return { lastTick: last, behind, stale: behind > 5 };
}

/** Gap rule (07 §16): break the series where tick indices are missing; never interpolate. */
export function segmentsOf(points) {
  const segments = [];
  const gaps = [];
  let current = [];
  for (const p of points) {
    const prev = current[current.length - 1];
    if (prev && p.t - prev.t > 1) {
      segments.push(current);
      gaps.push({ from: prev.t, to: p.t });
      current = [];
    }
    current.push(p);
  }
  if (current.length) segments.push(current);
  return { segments, gaps };
}
