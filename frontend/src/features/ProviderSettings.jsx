// Settings → AI provider. Reads and changes the engine's provider configuration through
// /api/providers. Secrets are typed into a transient field, sent once to the server and
// dropped from component state; nothing provider-related is written to browser storage.
import { useCallback, useEffect, useState } from "react";
import { Section, Field, Input } from "../components/index.jsx";
import { Btn, Icons, Tag, Dot, KV } from "../primitives/index.jsx";
import { PROVIDER_KINDS, capabilityRows, changedFields, fetchProviders, selectProvider, testProvider, updateProvider } from "../state/providers.js";

const Scope = () => <Tag className="scope-tag" tone="auth">engine</Tag>;

function Capabilities({ capabilities, verified }) {
  return (
    <div className="cap-row" aria-label="Model capabilities">
      {capabilityRows(capabilities).map((c) => (
        <span key={c.key} className={`cap cap-${c.state}`} title={c.state === "unknown" ? "Not verified for this model; run Test connection" : c.state === "yes" ? "Supported" : "Not supported"}>
          {c.state === "yes" ? Icons.check({ size: 11 }) : c.state === "no" ? Icons.close({ size: 11 }) : Icons.info({ size: 11 })}{c.label}
        </span>
      ))}
      <span className="t3">{verified ? "verified by connection test" : "from configuration; unverified fields are marked"}</span>
    </div>
  );
}

function TestResult({ result }) {
  if (!result) return null;
  const s = result.status || {};
  const err = s.error;
  return (
    <div className={`note-box ${err ? "note-warn" : "note-brand"}`} role="status">
      {err ? Icons.warn({}) : Icons.check({})}
      <span>
        {err ? <><b className="mono">{err.code}</b> · {err.message}</> : <>{s.detail || "reachable"}</>}
        {s.models?.length ? <><br /><span className="t3">Installed models: {s.models.join(", ")}</span></> : null}
        {s.checked_at ? <><br /><span className="t3 mono">{s.checked_at}</span></> : null}
      </span>
    </div>
  );
}

export function ProviderSettings() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [draft, setDraft] = useState({});
  const [tests, setTests] = useState({});
  const [saved, setSaved] = useState(null);

  const load = useCallback(async () => {
    setBusy("load");
    try { setData(await fetchProviders()); setError(null); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const active = data?.active || "none";
  const selection = data?.selection || "auto";
  const statuses = data?.providers || {};
  const status = statuses[active] || {};
  const prov = data?.reasoning_provenance || {};
  const d = draft[active] || {};
  const patch = (fields) => setDraft((prev) => ({ ...prev, [active]: { ...(prev[active] || {}), ...fields } }));

  const choose = async (kind) => {
    if (busy) return;
    setBusy("select"); setSaved(null);
    try { setData(await selectProvider(kind)); setError(null); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };
  const save = async () => {
    const fields = changedFields(active, d, status);
    if (!Object.keys(fields).length) { setSaved("Nothing changed."); return; }
    setBusy("save");
    try {
      const next = await updateProvider(active, fields);
      setData(next); setError(null);
      setDraft((prev) => ({ ...prev, [active]: { ...(prev[active] || {}), api_key: "" } }));
      setSaved(fields.api_key ? "Saved. The key is held in server memory for this session only." : "Saved.");
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };
  const runTest = async () => {
    setBusy("test");
    try { const result = await testProvider(active); setTests((prev) => ({ ...prev, [active]: result })); setError(null); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };

  const test = tests[active];
  const shownCaps = test?.status?.capabilities || status.capabilities;

  return (
    <Section label="AI provider" actions={<Scope />}>
      <div id="s-provider" />
      {!data && !error ? <p className="t3">Loading provider status from the engine…</p> : null}
      {error ? <div className="note-box note-warn" role="alert">{Icons.warn({})}<span>{error}</span></div> : null}
      {data ? (
        <>
          <div className="choice-row" role="radiogroup" aria-label="Model provider">
            {PROVIDER_KINDS.map((k) => {
              const s = statuses[k.id] || {};
              const on = active === k.id;
              return (
                <button key={k.id} type="button" role="radio" aria-checked={on} className={`choice prov-choice ${on ? "is-active" : ""}`} onClick={() => choose(k.id)} disabled={busy === "select"}>
                  <span className="choice-title"><Dot tone={k.id === "none" ? "normal" : s.configured ? "ok" : "warn"} />{k.label}</span>
                  <span className="choice-hint">{k.hint}</span>
                  {k.id !== "none" ? <span className="choice-hint mono">{s.configured ? "configured" : "not configured"}{s.model ? ` · ${s.model}` : ""}</span> : null}
                </button>
              );
            })}
          </div>
          <div className="kvgrid kvgrid-4">
            <KV label="Active provider" value={data.active_display_name || null} />
            <KV label="Selection" mono value={selection === "auto" ? `auto → ${active}` : selection} />
            <KV label="Reasoning backend" mono value={data.reasoning_backend || null} />
            <KV label="Supervisor" value={<span className="row-wrap"><Dot tone={data.supervisor_available ? "auth" : "warn"} />{data.supervisor_available ? "runtime available" : "awaiting runtime"}</span>} />
          </div>
          {data.locked ? <div className="note-box note-warn" role="status">{Icons.lock({})}<span>{data.lock_reason}</span></div> : null}
          {!data.supervisor_available && prov.unavailable_reason ? <p className="t3">{prov.unavailable_reason}</p> : null}
          <p className="t3">Changing the provider here takes effect for the next incident and the next Guided Demo without a restart; a run already in progress finishes on the backend it started with.</p>

          {active === "none" ? (
            <div className="note-box">{Icons.info({})}<span>Deterministic mode. Telemetry, ML health scoring, incident admission, baseline evidence, governance policy and the Guided Demo all run. Model-backed reasoning (supervisor and specialists) is disabled and reports itself as unavailable; incidents wait in INVESTIGATING. Operon never substitutes fabricated reasoning.</span></div>
          ) : null}

          {active === "gemini" ? (
            <div className="form-grid">
              <Field label="API key" hint={status.credential?.configured ? `Configured · source: ${status.credential.source}. Never shown or stored in the browser.` : "Not configured. Set GEMINI_API_KEY on the server, or provide a session key below (held in server memory only)."}>
                <Input type="password" autoComplete="off" placeholder={status.credential?.configured ? "•••••••• (replace for this session)" : "Session API key"} value={d.api_key || ""} onChange={(e) => patch({ api_key: e.target.value })} />
              </Field>
              <Field label="Model" hint="Any Gemini model id, e.g. gemini-flash-latest or gemini-2.5-pro.">
                <Input value={d.model ?? status.model ?? ""} onChange={(e) => patch({ model: e.target.value })} />
              </Field>
            </div>
          ) : null}

          {active === "ollama" ? (
            <div className="form-grid">
              <Field label="Base URL" hint="Where Ollama listens; default http://127.0.0.1:11434.">
                <Input value={d.base_url ?? status.endpoint ?? ""} onChange={(e) => patch({ base_url: e.target.value })} />
              </Field>
              <Field label="Model" hint="A model already pulled into Ollama (run `ollama list`). Operon never pulls models.">
                <Input value={d.model ?? status.model ?? ""} onChange={(e) => patch({ model: e.target.value })} />
              </Field>
              {test?.status?.models?.length ? (
                <div className="model-chips" aria-label="Installed models">
                  {test.status.models.map((m) => <button key={m} type="button" className={`chip ${(d.model ?? status.model) === m ? "is-active" : ""}`} onClick={() => patch({ model: m })}>{m}</button>)}
                </div>
              ) : null}
            </div>
          ) : null}

          {active === "bedrock" ? (
            <div className="form-grid">
              <Field label="Credentials" hint="Resolved on the server from AWS_PROFILE, access keys, a role or the shared credentials file. Not editable here.">
                <span className="row-wrap"><Dot tone={status.credential?.configured ? "ok" : "warn"} />{status.credential?.detail || "unknown"}</span>
              </Field>
              <Field label="Region" hint="AWS region with Bedrock model access.">
                <Input value={d.region ?? status.region ?? ""} onChange={(e) => patch({ region: e.target.value })} />
              </Field>
              <Field label="Model id" hint="Foundation model or cross-region inference profile id enabled in your account.">
                <Input value={d.model_id ?? status.model ?? ""} onChange={(e) => patch({ model_id: e.target.value })} />
              </Field>
            </div>
          ) : null}

          {active !== "none" ? (
            <>
              <Capabilities capabilities={shownCaps} verified={!!test?.status && !test.status.error} />
              <div className="row-wrap">
                <Btn small primary onClick={save} disabled={!!busy}>{busy === "save" ? "Saving…" : "Save"}</Btn>
                <Btn small onClick={runTest} disabled={!!busy}>{Icons.bolt({})} {busy === "test" ? "Testing…" : "Test connection"}</Btn>
                <Btn small quiet onClick={load} disabled={!!busy}>{Icons.reset({})} Refresh</Btn>
                {saved ? <span className="t3">{saved}</span> : null}
              </div>
              <TestResult result={test} />
            </>
          ) : null}
          <p className="t3">Provider choice is independent from Operon's reliability logic: the same lifecycle, governance and approval gates apply whatever model reasons. Secrets never leave the server; the API reports configured status only. Environment variables are documented in <span className="mono">.env.example</span> and <span className="mono">docs/DEMO.md</span>.</p>
        </>
      ) : null}
    </Section>
  );
}
