// Case inspector (F4.1, layout D): detail on demand beside the case, in the CH-2 containers (docked
// ≥ 1280, modal drawer below). Views: the asset, the case identifiers, the full record, all evidence
// and one artifact (GET /api/demo/artifacts/{id}). Everything shown is a backend record; confidence
// values are removed, and an artifact the server can't return falls back to the case's own row.
import { useEffect, useMemo, useState } from "react";
import { CopyId, EmptyLine, Ledger, Muted, Provenance, Segmented, SimulatedTag } from "../components/ui.jsx";
import { ConditionMarker } from "../components/ui.jsx";
import { RiskChart } from "../components/RiskChart.jsx";
import { PROVENANCE_LABEL, provenanceOf, withoutConfidence } from "../model/status.js";
import { clock, score, sentence, when, zoneAbbr } from "../model/format.js";
import { INSPECT_VIEWS } from "../model/inspect.js";
import { eventCopy } from "./caseCopy.js";

const MAX_PAYLOAD = 20000;

export function inspectorTitle(target, c) {
  if (!target) return "";
  if (target.kind === "asset") return `Asset · ${c.assetId}`;
  if (target.kind === "artifact") return "Record detail";
  return INSPECT_VIEWS[target.kind];
}

function AssetView({ c, history, latestTick, warn, trigger }) {
  return (
    <>
      <Ledger rows={[
        { label: "Asset", value: <><span className="wb-mono">{c.assetId}</span>{c.assetName ? ` · ${c.assetName}` : ""}</> },
        c.assetClass ? { label: "Class", value: sentence(c.assetClass) } : null,
        { label: "Criticality", value: c.criticality ? sentence(c.criticality) : <Muted>Not recorded</Muted> },
        { label: "Condition", value: <><ConditionMarker condition={c.condition} /> · model risk score <span className="wb-num">{score(c.failureProb)}</span></> },
        { label: "Thresholds", value: <>watch <span className="wb-num">{score(warn)}</span> · action gate <span className="wb-num">{score(trigger)}</span> (engine configuration)</> },
        { label: "Cases", value: "This case only. The live stream carries the latest case per asset (G5); earlier cases on this asset aren’t listed here." },
      ]} />
      <RiskChart points={history} latestTick={latestTick} warn={warn} trigger={trigger} title="Risk trajectory" assetId={c.assetId} />
      {c.demo ? <p className="wb-caption">Simulated plant data <SimulatedTag /></p> : null}
    </>
  );
}

function IdentifiersView({ c }) {
  const lc = c.alert?.lifecycle || {};
  const id = (value, label) => <CopyId value={value} label={label} head={8} tail={6} />;
  return (
    <>
      <Ledger className="wb-identifiers" rows={[
        { label: "Case", value: id(c.incidentId, "case id") },
        { label: "Revision", value: <span className="wb-mono-sm">R{lc.revision ?? "?"}</span> },
        { label: "Diagnosis", value: id(lc.diagnosis_id, "diagnosis id") },
        { label: "Work package", value: id(lc.intervention_id, "intervention id") },
        { label: "Package hash", value: id(lc.intervention_hash, "intervention hash") },
        { label: "Approval requirement", value: id(lc.requirement_id || c.requirement?.id, "requirement id") },
        { label: "Observation plan", value: id(lc.plan_id, "observation plan id") },
        { label: "Outcome", value: id(lc.outcome_id, "outcome id") },
      ]} />
      <p className="wb-caption">Identifiers as the backend projects them. A missing value is not recorded on this case yet{lc.requirement_id ? "" : "; the requirement shown is the latest one, which the backend no longer treats as pending"}.</p>
    </>
  );
}

function RecordView({ c }) {
  const [scope, setScope] = useState("acts");
  const [query, setQuery] = useState("");
  const all = useMemo(() => (c.rm?.events || []).map(eventCopy).filter(Boolean).reverse(), [c.rm]);
  const q = query.trim().toLowerCase();
  const rows = all.filter((e) => (scope === "all" || (e.authoritative && e.group !== "evidence"))
    && (!q || `${e.text} ${e.reason || ""} ${e.type}`.toLowerCase().includes(q)));
  return (
    <>
      <div className="wb-inspector-tools">
        <Segmented label="Events shown" value={scope} onChange={setScope}
          options={[{ value: "acts", label: "Transitions and human acts" }, { value: "all", label: "All events" }]} />
        <label className="wb-inspector-filter">
          <span className="wb-sr">Filter the record</span>
          <input className="wb-input" type="search" placeholder="Filter" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
      </div>
      <p className="wb-caption">{rows.length} of {all.length} events · newest first · times in {zoneAbbr() || "browser time"}{all.length >= 80 ? " · earlier events aren’t loaded in this build (X5)" : ""}</p>
      {rows.length ? (
        <ol className="wb-inspector-list">
          {rows.map((e) => (
            <li key={e.id} className={e.authoritative ? "is-auth" : "is-adv"}>
              <span className="wb-num wb-secondary">{clock(e.at, { seconds: true })}</span>
              <span>{e.text}{e.reason ? <span className="wb-secondary"> · {e.reason}</span> : null}</span>
              <span className="wb-mono-sm wb-secondary">R{e.revision}</span>
            </li>
          ))}
        </ol>
      ) : <EmptyLine>No events match.</EmptyLine>}
    </>
  );
}

function EvidenceView({ c, link }) {
  const rows = (c.rm?.evidence || []).slice().sort((a, b) => String(b.observed_at || "").localeCompare(String(a.observed_at || "")));
  if (!rows.length) return <EmptyLine>No evidence recorded yet.</EmptyLine>;
  return (
    <ol className="wb-inspector-list">
      {rows.map((e) => {
        const prov = provenanceOf(e);
        return (
          <li key={e.id}>
            <Provenance kind={prov} detail={e.source_capability || "source not recorded"} />
            <span>{link({ kind: "artifact", id: e.id }, e.summary || sentence(e.kind))}<span className="wb-secondary"> · {sentence(e.kind)} · {PROVENANCE_LABEL[prov]}</span></span>
            <span className="wb-num wb-secondary">{e.observed_at ? when(e.observed_at) : "—"}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Artifact detail from the server, with the case's own row as the fallback. */
function useArtifact(id) {
  const [result, setResult] = useState({ id, status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setResult({ id, status: "loading" });
    fetch(`/api/demo/artifacts/${encodeURIComponent(id)}`).then(async (r) => {
      const data = await r.json().catch(() => null);
      if (cancelled) return;
      if (r.ok && data && data.ok !== false && data.id) setResult({ id, status: "ready", artifact: data });
      else setResult({ id, status: "missing", http: r.status });
    }).catch(() => { if (!cancelled) setResult({ id, status: "missing", http: 0 }); });
    return () => { cancelled = true; };
  }, [id]);
  return result.id === id ? result : { id, status: "loading" };
}

function rowFor(rm, id) {
  for (const key of ["evidence", "hypotheses", "requirements", "execution_receipts", "observation_plans", "outcomes", "approval_decisions", "agent_runs", "events"]) {
    const hit = (rm?.[key] || []).find((x) => x.id === id || x.run_id === id);
    if (hit) return { collection: key, row: hit };
  }
  if (rm?.intervention?.id === id) return { collection: "intervention", row: rm.intervention };
  if (rm?.diagnosis?.id === id) return { collection: "diagnosis", row: rm.diagnosis };
  return null;
}

function Payload({ value }) {
  const text = JSON.stringify(withoutConfidence(value), null, 2) || "";
  return (
    <details className="wb-details">
      <summary>Recorded content</summary>
      <pre className="wb-pre">{text.length > MAX_PAYLOAD ? `${text.slice(0, MAX_PAYLOAD)}\n… (truncated)` : text}</pre>
    </details>
  );
}

function ArtifactView({ c, id, link }) {
  const res = useArtifact(id);
  if (res.status === "loading") return <p className="wb-secondary" role="status">Loading the record…</p>;
  if (res.status === "missing") {
    const local = rowFor(c.rm, id);
    return (
      <>
        <p className="wb-secondary">The server has no detail for this record{res.http ? ` (HTTP ${res.http})` : " (couldn’t reach the server)"}.{local ? " Showing the case’s own copy." : ""}</p>
        {local ? <><Ledger rows={[{ label: "Kind", value: sentence(local.collection) }, { label: "Identifier", value: <CopyId value={id} label="record id" head={8} tail={6} /> }]} /><Payload value={local.row} /></> : null}
      </>
    );
  }
  const a = res.artifact;
  const links = [["Parents", a.parent_ids], ["Supporting", a.supporting_ids], ["Related", a.related_ids]].filter(([, ids]) => (ids || []).length);
  return (
    <>
      <p className="wb-inspector-kind">{sentence(a.artifact_type || "record")}</p>
      {a.summary ? <p>{a.summary}</p> : null}
      <Ledger rows={[
        { label: "Identifier", value: <CopyId value={a.id} label="record id" head={8} tail={6} /> },
        a.status ? { label: "Status", value: sentence(a.status) } : null,
        a.created_at ? { label: "Recorded", value: when(a.created_at, { seconds: true }) } : null,
        { label: "Source", value: <>{a.runtime || a.source || "not recorded"}{a.provenance ? <span className="wb-secondary"> · {sentence(a.provenance)}</span> : null}{a.live_model === false ? <span className="wb-secondary"> · no live model</span> : null}</> },
        ...links.map(([label, ids]) => ({ label, value: <ul className="wb-mini-list">{ids.map((x) => <li key={x}>{link({ kind: "artifact", id: x }, <span className="wb-mono-sm">{String(x).slice(0, 8)}</span>)}</li>)}</ul> })),
      ]} />
      <Payload value={a.payload ?? a} />
    </>
  );
}

export function CaseInspector({ c, target, link, history, latestTick, warn, trigger }) {
  if (target.kind === "asset") return <AssetView c={c} history={history} latestTick={latestTick} warn={warn} trigger={trigger} />;
  if (target.kind === "identifiers") return <IdentifiersView c={c} />;
  if (target.kind === "record") return <RecordView c={c} />;
  if (target.kind === "evidence") return <EvidenceView c={c} link={link} />;
  return <ArtifactView key={target.id} c={c} id={target.id} link={link} />;
}
