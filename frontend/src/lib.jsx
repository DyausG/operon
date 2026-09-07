// Small shared helpers: number formatting + inline SVG icons.

export const pct = (v) => `${Math.round((v ?? 0) * 100)}%`;
export const money = (v) =>
  (v ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const money0 = (v) =>
  "$" + Math.round(v ?? 0).toLocaleString("en-US");

export const STATUS_ORDER = { CRITICAL: 0, WARNING: 1, SCHEDULED: 2, DOWN: 3, HEALTHY: 4 };

const I = (p) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{p}</svg>
);

export function ClassIcon({ cls }) {
  switch (cls) {
    case "COMPRESSOR": return I(<><circle cx="12" cy="12" r="8" /><path d="M12 4v4M12 16v4M4 12h4M16 12h4" /></>);
    case "CNC_MACHINE": return I(<><rect x="4" y="5" width="16" height="11" rx="1" /><path d="M8 20h8M12 16v4M8 9l3 3-3 3" /></>);
    case "PUMP": return I(<><circle cx="10" cy="12" r="6" /><path d="M16 12h5M10 6V3M18 9l2-2" /></>);
    case "ROBOT": return I(<><rect x="7" y="9" width="10" height="8" rx="1.5" /><path d="M12 9V5M9 3h6M9.5 13h.01M14.5 13h.01" /></>);
    case "CONVEYOR": return I(<><circle cx="6" cy="15" r="2.5" /><circle cx="18" cy="15" r="2.5" /><path d="M6 12.5h12M4 18h16" /></>);
    case "GRINDER": return I(<><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2.5" /></>);
    case "PRESS": return I(<><path d="M5 4h14M8 4v6l4 4 4-4V4M12 14v6M8 20h8" /></>);
    default: return I(<><rect x="4" y="4" width="16" height="16" rx="2" /></>);
  }
}

export function ShieldMark() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#a9b6ff" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2.5l7 3v5.5c0 4.6-3 8.2-7 10.5-4-2.3-7-5.9-7-10.5V5.5l7-3z" />
      <path d="M8.5 12l2.5 2.5 4.5-5" stroke="#34e2b0" />
    </svg>
  );
}

export const actorGlyph = { model: "◆", agent: "✦", tool: "▸" };
