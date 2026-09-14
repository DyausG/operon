// Formatting helpers. Numbers are shown as the application reports them (risk 0.86, not 86%).
export const risk = (v) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(2));
export const num = (v, d = 1) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d));
export const money0 = (v) => (v == null ? "—" : "$" + Math.round(Number(v)).toLocaleString("en-US"));
export const pct = (v) => (v == null ? "—" : `${Math.round(Number(v) * 100)}%`);

export function clock(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toISOString().slice(11, 19);
}
export function dateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
}
export function windowLabel(start, end) {
  if (!start) return null;
  const a = new Date(start), b = end ? new Date(end) : null;
  if (Number.isNaN(a.getTime())) return String(start);
  const hm = (d) => d.toISOString().slice(11, 16);
  const mins = b ? Math.round((b - a) / 60000) : null;
  return `${hm(a)}${b ? ` – ${hm(b)}` : ""}${mins ? ` · ${mins} min` : ""}`;
}
export function elapsed(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60), r = s % 60;
  return `+${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}
export function shortId(id, keep = 6) {
  if (!id) return "—";
  const s = String(id);
  if (s.length <= keep * 2 + 1) return s;
  return `${s.slice(0, keep)}…${s.slice(-keep + 2)}`;
}
export function shortHash(h) {
  if (!h) return "—";
  const s = String(h);
  return s.length > 14 ? `${s.slice(0, 6)}…${s.slice(-4)}` : s;
}
export const words = (v) => (v == null ? "" : String(v).replaceAll("_", " ").toLowerCase());
export const title = (v) => { const w = words(v); return w ? w[0].toUpperCase() + w.slice(1) : ""; };
export const isIsoDate = (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v);
export const looksLikeId = (v) => typeof v === "string" && /^[A-Z][A-Z0-9]+(-[A-Z0-9]+){1,}$/.test(v) && v.length < 40;
