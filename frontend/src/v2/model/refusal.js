// Backend refusals, shown safely (F4.1). A refusal keeps its HTTP status and an actionable reason,
// but the server body is never rendered as-is: only a string `error` / `detail` (or the first
// FastAPI validation message) is taken, control characters are removed and the text is bounded.
const MAX_DETAIL = 300;

/** A single plain-text line from an untrusted value, or null. */
export function cleanServerText(value) {
  if (typeof value !== "string") return null;
  // eslint-disable-next-line no-control-regex
  const text = value.replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ").replace(/\s+/g, " ").trim();
  if (!text) return null;
  return text.length > MAX_DETAIL ? `${text.slice(0, MAX_DETAIL - 1)}…` : text;
}

/** The server's own reason, if it gave a usable one. */
export function serverReason(body) {
  if (!body || typeof body !== "object") return null;
  const direct = cleanServerText(body.error) || cleanServerText(body.detail);
  if (direct) return direct;
  if (Array.isArray(body.detail) && body.detail.length) {
    const first = body.detail[0] || {};
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body").join(".") : "";
    const msg = cleanServerText(first.msg);
    return msg ? cleanServerText(field ? `${field}: ${msg}` : msg) : null;
  }
  return null;
}

const LEAD = {
  0: "Couldn’t reach the server. Nothing was recorded.",
  400: "The server refused the request as invalid.",
  403: "Not permitted here. The server refused this action.",
  404: "The server doesn’t know this case.",
  409: "Refused: not valid in the case’s current state, or the case changed.",
  422: "The server rejected the request as invalid.",
};

/** { status, lead, detail } for display; `status` 0 means the request never reached the server. */
export function refusalFrom(status, body) {
  const lead = LEAD[status] || (status >= 500 ? "The server failed to process the request. Nothing is assumed recorded." : "The server refused the request.");
  return { status, lead, detail: serverReason(body) };
}

/** POST JSON and classify the answer. Never throws. */
export async function postJson(url, body) {
  let res;
  try {
    res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    return { ok: false, status: 0, data: null, refusal: refusalFrom(0, null) };
  }
  const data = await res.json().catch(() => null);
  if (res.ok && (!data || data.ok !== false)) return { ok: true, status: res.status, data, refusal: null };
  return { ok: false, status: res.status, data, refusal: refusalFrom(res.status, data) };
}
