// Operon-owned status shapes (07 §10): simple geometry on a 16-unit grid, drawn at 14 px in cells
// and inline and 16 px in the plant band and title block (R-4). Never below 14 px. Provenance marks
// are separate 10 px squares and never carry severity (07 §14).

const SW = 1.5;

const SHAPES = {
  // asset condition
  normal: <circle cx="8" cy="8" r="5" fill="none" stroke="currentColor" strokeWidth={SW} />,
  elevated: <path d="M8 2.1 14.4 13.6H1.6Z" fill="currentColor" />,
  // Filled octagon with a knocked-out "!" so it never reads as a dot at 14–16 px (R-4).
  critical: <path fillRule="evenodd" fill="currentColor" d="M5.1.8h5.8l4.3 4.3v5.8l-4.3 4.3H5.1L.8 10.9V5.1ZM7.1 3.9h1.8l-.25 5.2H7.35ZM8 10.4a1.05 1.05 0 1 0 0 2.1 1.05 1.05 0 0 0 0-2.1Z" />,
  unknown: (
    <g>
      <rect x="2" y="2" width="12" height="12" rx="1" fill="none" stroke="currentColor" strokeWidth={SW} strokeDasharray="2.2 1.8" />
      <path d="M6.4 6.3a1.7 1.7 0 1 1 2.4 1.5c-.5.3-.8.7-.8 1.2v.4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="11.2" r=".85" fill="currentColor" />
    </g>
  ),
  stale: (
    <g fill="none" stroke="currentColor" strokeWidth={SW} strokeLinecap="round">
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.6V8l2.3 1.5" />
    </g>
  ),
  offline: (
    <g fill="none" stroke="currentColor" strokeWidth={SW} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 1.8v2.6M10 1.8v2.6M4.4 4.6h7.2v2.3a3.6 3.6 0 0 1-7.2 0Z M8 10.5v3.7" />
      <path d="M1.8 1.8l12.4 12.4" />
    </g>
  ),
  // watch / verification
  watch: <path d="M8 1.9 14.1 8 8 14.1 1.9 8Z" fill="none" stroke="currentColor" strokeWidth={SW} strokeLinejoin="round" />,
  inconclusive: (
    <g fill="none" stroke="currentColor" strokeWidth={SW} strokeLinejoin="round" strokeLinecap="round">
      <path d="M8 1.9 14.1 8 8 14.1 1.9 8Z" />
      <path d="M5.6 8.4c.8-1 1.6-1 2.4-.4s1.6.6 2.4-.4" strokeWidth="1.3" />
    </g>
  ),
  notStarted: <circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" strokeWidth={SW} strokeDasharray="2.4 2" />,
  verified: (
    <g fill="none" stroke="currentColor" strokeWidth={SW} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="6" />
      <path d="M5.3 8.2 7.2 10l3.6-3.8" />
    </g>
  ),
  notRecovered: (
    <g fill="none" stroke="currentColor" strokeWidth={SW} strokeLinecap="round">
      <circle cx="8" cy="8" r="6" />
      <path d="M5.9 5.9l4.2 4.2M10.1 5.9l-4.2 4.2" />
    </g>
  ),
  // a person must act (CH-1): person in a square
  decision: (
    <g>
      <rect x="1.75" y="1.75" width="12.5" height="12.5" rx="1" fill="none" stroke="currentColor" strokeWidth={SW} />
      <circle cx="8" cy="6.1" r="1.9" fill="currentColor" />
      <path d="M4.5 12.4c.5-2 1.8-3.1 3.5-3.1s3 1.1 3.5 3.1Z" fill="currentColor" />
    </g>
  ),
  // in progress (neutral): half-filled circle
  active: (
    <g>
      <circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" strokeWidth={SW} />
      <path d="M8 2.4a5.6 5.6 0 0 1 0 11.2Z" fill="currentColor" />
    </g>
  ),
  // work state
  planned: <path d="M4 1.8h5.4L12 4.4v9.8H4Z M9.2 1.8v2.8H12" fill="none" stroke="currentColor" strokeWidth={SW} strokeLinejoin="round" />,
  approved: (
    <g fill="none" stroke="currentColor" strokeWidth={SW} strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="12" height="12" rx="1" />
      <path d="M5.2 8.1 7.2 10l3.6-3.9" />
    </g>
  ),
  committed: (
    <g fill="none" stroke="currentColor" strokeWidth={SW} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 1.8h5.4L12 4.4v9.8H4Z" />
      <path d="M6 9.2 7.5 10.6 10 7.9" />
    </g>
  ),
  // hypothesis outcome
  supported: <circle cx="8" cy="8" r="4.6" fill="currentColor" />,
  refuted: (
    <g fill="none" stroke="currentColor" strokeWidth={SW}>
      <circle cx="8" cy="8" r="5.2" />
      <path d="M4.4 11.6l7.2-7.2" />
    </g>
  ),
  unresolved: <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth={SW} strokeDasharray="2.2 1.9" />,
  open: <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth={SW} />,
  // system actor (gear) for system waiting-on roles
  system: (
    <g fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round">
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1.6v2M8 12.4v2M1.6 8h2M12.4 8h2M3.5 3.5l1.4 1.4M11.1 11.1l1.4 1.4M3.5 12.5l1.4-1.4M11.1 4.9l1.4-1.4" strokeLinecap="round" />
      <circle cx="8" cy="8" r="4.3" />
    </g>
  ),
  // attention rank (neutral ink, weight-coded)
  rankAction: <rect x="3" y="3" width="10" height="10" fill="currentColor" />,
  rankRisk: (
    <g>
      <rect x="3.75" y="3.75" width="8.5" height="8.5" fill="none" stroke="currentColor" strokeWidth={SW} />
      <path d="M3 3h5v10H3Z" fill="currentColor" />
    </g>
  ),
  rankWatch: <rect x="3.75" y="3.75" width="8.5" height="8.5" fill="none" stroke="currentColor" strokeWidth={SW} />,
};

/** The colour role of each shape (07 §4.3 / §12.2). */
const TONE = {
  normal: "nominal", elevated: "warning", critical: "critical", unknown: "unknown", stale: "stale", offline: "offline",
  watch: "warning", inconclusive: "warning", notStarted: "nominal", verified: "verified", notRecovered: "critical",
  decision: "decision", active: "active", planned: "nominal", approved: "nominal", committed: "nominal",
  supported: "ink", refuted: "nominal", unresolved: "nominal", open: "ink", system: "nominal",
  rankAction: "ink", rankRisk: "ink", rankWatch: "ink",
};

/**
 * One status shape. `label` is the accessible meaning ("Asset condition: Critical"); when the
 * shape sits next to its own visible word, pass `decorative` and let the word carry it.
 */
export function Shape({ name, size = 14, label, decorative = false, tone, className = "" }) {
  const body = SHAPES[name];
  if (!body) return null;
  const px = Math.max(14, size); // R-4: never below 14 px
  return (
    <svg
      className={`wb-shape wb-tone-${tone || TONE[name] || "ink"} ${className}`}
      width={px} height={px} viewBox="0 0 16 16"
      role={decorative ? undefined : "img"} aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : label} focusable="false"
    >
      {body}
    </svg>
  );
}

export const SHAPE_NAMES = Object.keys(SHAPES);

/** 10 px provenance marks (07 §14). Never coloured; never a status. */
export function ProvenanceMark({ kind, label }) {
  const common = { x: 0.75, y: 0.75, width: 8.5, height: 8.5 };
  let body;
  if (kind === "measured") body = <rect {...common} fill="currentColor" stroke="currentColor" strokeWidth="1" />;
  else if (kind === "derived") body = (
    <g><rect {...common} fill="none" stroke="currentColor" strokeWidth="1" /><path d="M.75 9.25 9.25 .75v8.5Z" fill="currentColor" /></g>
  );
  else if (kind === "model") body = <rect {...common} fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="1.6 1.2" />;
  else if (kind === "human") body = (
    <g><rect {...common} fill="none" stroke="currentColor" strokeWidth="1" /><circle cx="5" cy="5" r="1.7" fill="currentColor" /></g>
  );
  else body = (
    <g>
      <rect {...common} fill="none" stroke="currentColor" strokeWidth="1" />
      <path d="M.75 4.5 4.5.75M.75 9.25 9.25.75M4.5 9.25 9.25 4.5" stroke="currentColor" strokeWidth=".9" />
    </g>
  );
  return (
    <svg className="wb-prov" width="10" height="10" viewBox="0 0 10 10" role="img" aria-label={label} focusable="false">
      <title>{label}</title>
      {body}
    </svg>
  );
}

/** Four ascending bars; filled count = level. Neutral ink: severity is consequence, not state. */
export function SeverityBars({ level = 0 }) {
  return (
    <svg className="wb-sev" width="18" height="14" viewBox="0 0 18 14" aria-hidden="true" focusable="false">
      {[0, 1, 2, 3].map((i) => {
        const h = 5 + i * 3;
        return <rect key={i} x={i * 4.5 + 0.5} y={13.5 - h} width="3" height={h} rx=".5"
          className={i < level ? "wb-sev-on" : "wb-sev-off"} />;
      })}
    </svg>
  );
}
