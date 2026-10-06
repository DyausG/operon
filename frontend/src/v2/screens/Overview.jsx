// Overview (08 screens 1–2): "does anything need a person, and is the plant normal?"
// Board template: title block, quiet plant band, then an 8 + 4 region grid. Regions keep their
// positions between nominal and active states (no layout shift). Every value is a backend field.
import { Link } from "react-router-dom";
import { useWb } from "../shell/WbContext.jsx";
import { usePageTitle } from "../shell/WbShell.jsx";
import { WB_ROUTES } from "../shell/routes.js";
import { AttentionGlyph, ConditionMarker, EmptyLine, FreshnessIndicator, InlineAlert, Muted, SectionHeading, SeverityMarker, TitleBlock, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { assetLag } from "../model/freshness.js";
import { aggregateConditions, conditionOf, CONDITION_LABEL, stageCompact } from "../model/status.js";
import { clock, when, duration, score } from "../model/format.js";
import { reasonLine } from "../model/cases.js";
import { OUTCOME } from "../model/status.js";

function DeadlineCell({ c, now }) {
  const r = c.requirement;
  if (!r?.expires_at) return <Muted>No deadline</Muted>;
  if (c.expiry?.state === "expired") return <span>Expired {when(r.expires_at)}</span>;
  const near = c.expiry?.state === "approaching" || c.expiry?.state === "final";
  return (
    <span className={near ? "wb-deadline-near" : ""}>
      {near ? <Shape name="elevated" size={14} label="Deadline approaching" tone="warning" /> : null}
      {when(r.expires_at)}
      <span className="wb-cell-sub">in {duration(Date.parse(r.expires_at) - now)}</span>
    </span>
  );
}

function Deadline({ c, now }) {
  const r = c.requirement;
  if (!r?.expires_at) return <Muted>No deadline</Muted>;
  const near = c.expiry?.state === "approaching" || c.expiry?.state === "final";
  if (c.expiry?.state === "expired") return <span>Expired {when(r.expires_at)}</span>;
  return (
    <span className={near ? "wb-deadline-near" : ""}>
      {near ? <Shape name="elevated" size={14} label="Deadline approaching" tone="warning" /> : null}
      {when(r.expires_at)} · in {duration(Date.parse(r.expires_at) - now)}
    </span>
  );
}

function PlantBand({ assets, warn, trigger, latestTick, histories, live }) {
  const items = assets.map((a) => {
    const lag = assetLag(histories[a.equipment_id], latestTick);
    const cond = lag.stale && live ? "stale" : conditionOf(a.failure_prob, { warn, trigger });
    return { a, cond, lag };
  });
  const { counts } = aggregateConditions(items.map((i) => i.cond));
  const order = ["critical", "stale", "unknown", "elevated", "normal"];
  const summary = order.filter((k) => counts[k]).map((k) => `${counts[k]} ${CONDITION_LABEL[k].toLowerCase()}`).join(" · ");
  return (
    <section className="wb-band" aria-labelledby="wb-band-title">
      <div className="wb-band-head">
        <h2 className="wb-band-title" id="wb-band-title">Plant condition</h2>
        <span className="wb-band-summary">{summary}</span>
        <span className="wb-band-scope">Line (single, unnamed; X3) · condition from model risk score only</span>
      </div>
      <ul className="wb-band-list">
        {items.map(({ a, cond, lag }) => {
          const abnormal = cond !== "normal";
          return (
            <li key={a.equipment_id} className={`wb-band-cell ${abnormal ? "is-abnormal" : ""}`}>
              <ConditionMarker condition={cond} size={16} showWord={false} />
              <span className="wb-band-tag">{a.equipment_id}</span>
              {abnormal ? (
                <span className="wb-band-detail">
                  <span className="wb-marker-word">{CONDITION_LABEL[cond]}</span>
                  {cond === "stale"
                    ? <span className="wb-secondary"> since tick {lag.lastTick?.toLocaleString("en-GB")}</span>
                    : <span className="wb-num"> {score(a.failure_prob)}</span>}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function AttentionItem({ c, now, trigger }) {
  const isDecision = c.phase === "AWAITING_APPROVAL";
  return (
    <li className="wb-attn-item">
      <div className="wb-attn-line1">
        {c.response
          ? <Link className="wb-attn-verb" to={WB_ROUTES.case(c.incidentId, c.response.section)}>{c.response.verb} · <span className="wb-mono">{c.assetId}</span></Link>
          : <Link className="wb-attn-verb is-plain" to={WB_ROUTES.case(c.incidentId)}><span className="wb-mono">{c.assetId}</span> · {c.stage?.label}{c.waiting?.key === "analysis" ? " (automated)" : ""}</Link>}
        <span className="wb-attn-deadline">{isDecision ? <Deadline c={c} now={now} /> : null}</span>
      </div>
      <p className="wb-attn-line2">
        <ConditionMarker condition={c.condition} />
        <span className="wb-dot-sep" aria-hidden="true">·</span>
        <span>{c.assetName}</span>
        <span className="wb-dot-sep" aria-hidden="true">·</span>
        <WaitingOn role={c.waiting} prefix />
      </p>
      <p className="wb-attn-line3">{reasonLine(c, { trigger })}</p>
    </li>
  );
}

function ActiveCasesTable({ cases, now }) {
  return (
    <div className="wb-table-wrap">
      <table className="wb-table is-compact">
        <caption className="wb-table-caption">Sorted by attention, then deadline · latest case per asset (G5)</caption>
        <thead>
          <tr>
            <th scope="col" className="wb-col-glyph"><span className="wb-sr">Attention</span></th>
            <th scope="col">Case</th>
            <th scope="col">Stage</th>
            <th scope="col">Waiting on</th>
            <th scope="col">{cases.every((c) => c.severity) ? "Severity" : "Severity or asset criticality"}</th>
            <th scope="col">Deadline</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.incidentId}>
              <td className="wb-col-glyph"><AttentionGlyph level={c.attention} /></td>
              <th scope="row" className="wb-cell-case">
                <Link to={WB_ROUTES.case(c.incidentId)} className="wb-mono">{c.ref}</Link>
                <span className="wb-cell-sub">{c.assetName}</span>
              </th>
              <td className="is-nowrap">{stageCompact(c.phase)}</td>
              <td className="is-nowrap"><WaitingOn role={c.waiting} /></td>
              <td className="is-nowrap">{c.severity ? <SeverityMarker value={c.severity} /> : <SeverityMarker value={c.criticality} basis="Asset criticality" />}</td>
              <td className="is-nowrap"><DeadlineCell c={c} now={now} /></td>
              <td className="wb-num">{c.updatedAt ? clock(c.updatedAt) : <Muted>Not projected</Muted>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Overview() {
  usePageTitle("Overview");
  const { state, cases, now, fresh, analysisPaused, demo } = useWb();
  const warn = state.warnThreshold, trigger = state.triggerThreshold;
  const assets = state.fleet || [];
  const live = fresh.state === "live" || fresh.state === "measuring";
  const dataOk = live || fresh.state === "delayed";
  const action = cases.filter((c) => c.attention === "action");
  const risk = cases.filter((c) => c.attention === "risk");
  const active = cases.filter((c) => !["CLOSED", "CANCELLED"].includes(c.phase));
  const caseAssets = new Set(active.map((c) => c.assetId));
  const watchAssets = assets.filter((a) => !caseAssets.has(a.equipment_id) && conditionOf(a.failure_prob, { warn, trigger }) === "elevated");
  const verifying = cases.filter((c) => c.phase === "OBSERVING");
  const working = cases.filter((c) => (c.rm?.execution_receipts || []).length > 0 && !["CLOSED", "CANCELLED"].includes(c.phase));
  const outcomes = cases.filter((c) => c.outcomeResult);
  const lags = assets.map((a) => assetLag(state.histories?.[a.equipment_id], state.tick));
  const stale = lags.filter((l) => l.stale).length;
  const reporting = assets.length - stale;
  const rp = state.reasoningProvenance || {};
  const attentionCount = action.length + risk.length;

  let statement;
  if (fresh.state === "disconnected") {
    statement = <>Live data lost{fresh.lastReceipt ? ` (last received ${clock(fresh.lastReceipt, { seconds: true })}, browser time)` : ""}. Condition below is as of that time.</>;
  } else if (fresh.state === "stale" || fresh.state === "paused") {
    statement = <>Can’t confirm that nothing needs attention: {fresh.state === "paused" ? `the simulation is paused at tick ${state.tick.toLocaleString("en-GB")}` : "data is stale"}.</>;
  } else if (!assets.length) {
    statement = <>Waiting for plant data. No readings received since the page opened.</>;
  } else if (attentionCount === 0) {
    statement = <>No case needs a person right now.</>;
  } else {
    statement = <>{action.length ? `${action.length} ${action.length === 1 ? "item requires" : "items require"} a person` : "Nothing requires a person"}{risk.length ? ` · ${risk.length} at risk` : ""}.</>;
  }

  const blockCells = [
    { label: "Plant", value: state.meta?.plant || "Not reported" },
    { label: "Assets", value: assets.length ? `${reporting} of ${assets.length} reporting` : "No data" },
    { label: "Active cases", value: `${active.length}` },
    { label: "Thresholds", value: `Warning ${score(warn)} · gate ${score(trigger)}` },
  ];

  return (
    <div className="wb-page wb-overview">
      <header className="wb-page-head">
        <h1 className="wb-page-title">Overview</h1>
        <TitleBlock label="Plant summary" cells={blockCells} end={<FreshnessIndicator fresh={fresh} />} />
      </header>

      <PlantBand assets={assets} warn={warn} trigger={trigger} latestTick={state.tick} histories={state.histories || {}} live={dataOk} />

      {rp.status === "awaiting_runtime" ? (
        <InlineAlert tone="info" title={demo?.active ? "Analysis provider not configured · Guided Demo uses the labelled deterministic advisory" : "Analysis unavailable: no model provider is configured"}>
          {rp.unavailable_reason}
        </InlineAlert>
      ) : null}

      <div className="wb-board">
        <div className="wb-board-main">
          <section className="wb-region" aria-labelledby="ov-attn">
            <SectionHeading index="01" id="ov-attn" title="Requires attention" meta={dataOk ? `${attentionCount}` : "as of last received data"} />
            <p className="wb-statement">{statement}</p>
            {dataOk && attentionCount === 0 && assets.length ? (
              <p className="wb-statement-facts">
                {assets.length} of {assets.length} assets below the action gate ({score(trigger)}) · last data received {fresh.lastReceipt ? clock(fresh.lastReceipt, { seconds: true }) : "not yet"} · {analysisPaused ? "analysis not configured" : "analysis available"}.
              </p>
            ) : null}
            {action.length ? (
              <div className="wb-attn-group">
                <h3 className="wb-group-head">Action required · {action.length}</h3>
                <ul className="wb-attn-list">{action.map((c) => <AttentionItem key={c.incidentId} c={c} now={now} trigger={trigger} />)}</ul>
              </div>
            ) : null}
            {risk.length ? (
              <div className="wb-attn-group">
                <h3 className="wb-group-head">At risk · {risk.length}</h3>
                <ul className="wb-attn-list">{risk.map((c) => <AttentionItem key={c.incidentId} c={c} now={now} trigger={trigger} />)}</ul>
              </div>
            ) : null}
          </section>

          <section className="wb-region" aria-labelledby="ov-cases">
            <SectionHeading index="02" id="ov-cases" title="Active cases" meta={`${active.length}`} />
            {active.length ? <ActiveCasesTable cases={active} now={now} /> : <EmptyLine>No open cases. A case opens when an asset’s model risk score reaches the action gate ({score(trigger)}).</EmptyLine>}
          </section>
        </div>

        <div className="wb-board-side">
          <section className="wb-region" aria-labelledby="ov-watch">
            <SectionHeading index="03" id="ov-watch" title="Watch" meta={`${watchAssets.length + verifying.length}`} />
            {watchAssets.length + verifying.length === 0 ? <EmptyLine>No asset is in the warning band without a case. No case is verifying.</EmptyLine> : (
              <ul className="wb-list">
                {watchAssets.map((a) => (
                  <li key={a.equipment_id} className="wb-list-row">
                    <ConditionMarker condition="elevated" />
                    <span className="wb-mono">{a.equipment_id}</span>
                    <span className="wb-num">{score(a.failure_prob)}</span>
                    <span className="wb-secondary">no case (below gate)</span>
                  </li>
                ))}
                {verifying.map((c) => (
                  <li key={c.incidentId} className="wb-list-row">
                    <Shape name="watch" size={14} decorative />
                    <Link className="wb-mono" to={WB_ROUTES.case(c.incidentId, "work")}>{c.assetId}</Link>
                    <span className="wb-secondary">Verifying</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="wb-region" aria-labelledby="ov-work">
            <SectionHeading index="04" id="ov-work" title="Work in progress" meta={`${working.length}`} />
            {working.length === 0 ? <EmptyLine>No committed work orders.</EmptyLine> : (
              <ul className="wb-list">
                {working.map((c) => {
                  const rec = (c.rm.execution_receipts || [])[0];
                  const wo = rec?.external_ids?.wo_number || rec?.external_ids?.wo_id;
                  return (
                    <li key={c.incidentId} className="wb-list-row">
                      <Shape name="committed" size={14} decorative />
                      <span className="wb-mono">{wo || "Work order"}</span>
                      <span className="wb-mono">{c.assetId}</span>
                      <span className="wb-secondary">committed {rec?.completed_at ? clock(rec.completed_at) : ""} · field completion not reported (G10)</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          <section className="wb-region" aria-labelledby="ov-outcomes">
            <SectionHeading index="05" id="ov-outcomes" title="Recent outcomes" meta="this run · G5" />
            {outcomes.length === 0 ? <EmptyLine>No outcomes recorded in this run.</EmptyLine> : (
              <ul className="wb-list">
                {outcomes.map((c) => (
                  <li key={c.incidentId} className="wb-list-row">
                    <Shape name={OUTCOME[c.outcomeResult]?.shape || "unknown"} size={14} decorative />
                    <span className="wb-mono">{c.assetId}</span>
                    <span>{OUTCOME[c.outcomeResult]?.label || "Outcome not recognised"}{(c.rm?.outcomes || []).some((o) => o.basis === "SIMULATED") ? " (simulated)" : ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
