// Time and value formatting. Times render in the browser's zone with its abbreviation until the
// plant time zone is projected (X3). Browser receipt times are always labelled "received" (X8).

const pad = (n) => String(n).padStart(2, "0");

export function toDate(value) {
  if (value == null || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "14:32" or "14:32:05". */
export function clock(value, { seconds = false } = {}) {
  const d = toDate(value);
  if (!d) return null;
  return `${pad(d.getHours())}:${pad(d.getMinutes())}${seconds ? `:${pad(d.getSeconds())}` : ""}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** HH:MM(:SS) when the moment is today in the browser zone, otherwise "18 Aug 14:00". Never a bare
 *  time for another day (a time without its date would misdate older evidence). */
export function when(value, { seconds = false, now = new Date() } = {}) {
  const d = toDate(value);
  if (!d) return null;
  const today = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  return today ? clock(d, { seconds }) : dayClock(d);
}

/** "05 Oct 13:02" (interim case reference format, G6). */
export function dayClock(value) {
  const d = toDate(value);
  if (!d) return null;
  return `${pad(d.getDate())} ${MONTHS[d.getMonth()]} ${clock(d)}`;
}

/** Short zone abbreviation of the browser zone, e.g. "UTC", "CDT". */
export function zoneAbbr(at = new Date()) {
  try {
    const part = new Intl.DateTimeFormat("en-GB", { timeZoneName: "short" }).formatToParts(at)
      .find((p) => p.type === "timeZoneName");
    return part?.value || "";
  } catch {
    return "";
  }
}

/** Full ISO date-time with zone, for hover titles. */
export function isoTitle(value) {
  const d = toDate(value);
  return d ? d.toISOString() : "";
}

/** "2 h 41 min", "42 min", "under 1 min". Minutes only: never ticking seconds (08 §7). */
export function duration(ms) {
  if (ms == null || !Number.isFinite(ms)) return null;
  const total = Math.max(0, Math.floor(ms / 60000));
  if (total < 1) return "under 1 min";
  const h = Math.floor(total / 60), m = total % 60;
  if (h >= 48) return `${Math.floor(h / 24)} d ${h % 24} h`;
  return h ? `${h} h ${m} min` : `${m} min`;
}

/** Age for freshness lines: seconds below two minutes, then minutes. */
export function age(ms) {
  if (ms == null || !Number.isFinite(ms)) return null;
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 120) return `${s} s`;
  return duration(ms);
}

/** Model risk score: three decimals, never a percentage (07 §2). */
export function score(value) {
  return Number.isFinite(value) ? value.toFixed(value >= 0.995 || value < 0.01 ? 3 : 2) : null;
}

/** Thousands separator, true minus sign (U+2212). */
export function number(value, digits = 0) {
  if (!Number.isFinite(value)) return null;
  const s = Math.abs(value).toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return value < 0 ? `−${s}` : s;
}

/** Middle truncation for identifiers: "619e0c…46e4". */
export function middle(id, head = 6, tail = 4) {
  if (!id) return "";
  const s = String(id);
  return s.length <= head + tail + 1 ? s : `${s.slice(0, head)}…${s.slice(-tail)}`;
}

export function shortId(id, n = 8) {
  return id ? String(id).slice(0, n) : "";
}

export function sentence(s) {
  if (!s) return "";
  const t = String(s).replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}
