// AI provider configuration client. Talks only to /api/providers; the browser never sees a
// credential (the API returns configured/masked status) and nothing here touches storage.
export const PROVIDER_KINDS = [
  { id: "none", label: "None / deterministic", hint: "Telemetry, health scoring, incidents and the Guided Demo keep running; model-backed reasoning is off." },
  { id: "gemini", label: "Google Gemini", hint: "Cloud model. The API key stays on the server (environment or this session)." },
  { id: "ollama", label: "Ollama / local", hint: "Open-source models served by a local Ollama process. No credential." },
  { id: "bedrock", label: "AWS Bedrock", hint: "Cloud model. AWS credentials come from the server's AWS configuration." },
];

/** Non-secret Ollama tunables the engine accepts on PUT /api/providers/ollama (see OllamaSettings). */
export const OLLAMA_TUNABLES = ["num_ctx", "timeout_seconds", "connect_timeout_seconds", "invocation_timeout_seconds",
  "run_timeout_seconds", "peer_timeout_seconds"];

export const CAPABILITY_LABELS = [
  ["text_generation", "Text"], ["structured_output", "Structured output"], ["tool_calling", "Tool calling"],
  ["streaming", "Streaming"], ["image_input", "Image input"],
];

function json(body) {
  return { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

async function call(path, init = {}) {
  if (typeof fetch === "undefined") throw new Error("engine API unavailable in this environment");
  const response = await fetch(path, init);
  let body = {};
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok || body.ok === false) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

export const fetchProviders = () => call("/api/providers");
export const selectProvider = (provider, model) => call("/api/providers/select", { method: "POST", ...json(model ? { provider, model } : { provider }) });
export const updateProvider = (kind, fields) => call(`/api/providers/${kind}`, { method: "PUT", ...json(fields) });

/** A failed connection test is a valid answer (the status carries the normalized error), not an exception. */
export async function testProvider(kind) {
  if (typeof fetch === "undefined") throw new Error("engine API unavailable in this environment");
  const response = await fetch(`/api/providers/${kind}/test`, { method: "POST" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok && !body.status) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

/** Capability rows for display: true = supported, false = not supported, null = unverified. */
export function capabilityRows(capabilities) {
  const caps = capabilities || {};
  return CAPABILITY_LABELS.map(([key, label]) => ({ key, label, state: caps[key] === true ? "yes" : caps[key] === false ? "no" : "unknown" }));
}

/** Only the fields a provider accepts, and only the ones the operator changed. */
export function changedFields(kind, draft, status) {
  const out = {};
  const d = draft || {};
  if (kind === "gemini") {
    if (d.model != null && d.model !== (status?.model || "")) out.model = d.model;
    if (d.api_key) out.api_key = d.api_key;
  } else if (kind === "ollama") {
    if (d.model != null && d.model !== (status?.model || "")) out.model = d.model;
    if (d.base_url != null && d.base_url !== (status?.endpoint || "")) out.base_url = d.base_url;
    const current = status?.settings || {};
    for (const key of OLLAMA_TUNABLES) {
      if (d[key] == null || d[key] === "") continue;
      const value = Number(d[key]);
      if (!Number.isFinite(value) || value === Number(current[key])) continue;
      out[key] = value;
    }
  } else if (kind === "bedrock") {
    if (d.model_id != null && d.model_id !== (status?.model || "")) out.model_id = d.model_id;
    if (d.region != null && d.region !== (status?.region || "")) out.region = d.region;
  }
  return out;
}
