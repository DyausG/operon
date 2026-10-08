// Cases (08 screen 4, today's variant). The list is what the live stream carries: the latest case
// per asset (G5), labelled as limited history. Status segments, stage, waiting-on and asset filters
// and the sort live in the URL; a row opens the CH-2 preview (docked ≥ 1280, modal drawer 768–1279,
// phone opens the case). Decisions are never made from the list.
import { useCallback, useEffect, useRef } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useWb } from "../shell/WbContext.jsx";
import { usePageTitle } from "../shell/WbShell.jsx";
import { WB_ROUTES } from "../shell/routes.js";
import { Button, ConditionMarker, EmptyLine, FreshnessIndicator, Muted, Segmented, TitleBlock, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { DockedPane, ModalDrawer, usePreviewMode } from "../components/Overlay.jsx";
import { stageCompact, stageOf } from "../model/status.js";
import { SORTS, STAGE_OPTIONS, STATUS_SEGMENTS, WAITING_OPTIONS, exceptionWords, filterCases, listState, sortCases, statusCounts } from "../model/caseList.js";
import { score, when } from "../model/format.js";
import { CasePreview } from "./CasePreview.jsx";

const EMPTY_FOR = {
  active: "No open cases on the live stream.",
  exceptions: "No case needs recovery.",
  resolved: "No closed or cancelled cases on the live stream.",
  all: "No cases on the live stream. A case opens when an asset’s model risk score crosses the action gate.",
};

function CaseRow({ c, selected, onOpen, onKey }) {
  const exception = stageOf(c.phase)?.exception;
  const why = exceptionWords(c);
  return (
    <tr className={selected ? "is-selected" : undefined} aria-selected={selected || undefined}>
      <th scope="row">
        <button type="button" className="wb-cl-row" data-row={c.incidentId} aria-current={selected ? "true" : undefined}
          onClick={() => onOpen(c.incidentId)} onKeyDown={(e) => onKey(e, c.incidentId)}>
          <span className="wb-cl-asset"><span className="wb-mono">{c.assetId}</span>{c.assetName ? ` · ${c.assetName}` : ""}</span>
          <span className="wb-cl-ref wb-mono-sm">{c.ref}</span>
        </button>
      </th>
      <td>
        <span className="wb-cl-stage">{exception ? <Shape name="critical" size={14} decorative tone="critical" /> : null}{stageCompact(c.phase)}</span>
        {why ? <span className="wb-cl-sub">{why}</span> : null}
      </td>
      <td>
        <WaitingOn role={c.waiting} />
        {c.response && c.waiting?.human ? <span className="wb-cl-sub">{c.response.verb}</span> : null}
      </td>
      <td className="is-nowrap"><ConditionMarker condition={c.condition} /> <span className="wb-num">{score(c.failureProb)}</span></td>
      <td className="is-nowrap wb-num">{c.openedAt ? when(c.openedAt) : <Muted>Not recorded</Muted>}</td>
      <td className="is-nowrap wb-num">{c.updatedAt ? when(c.updatedAt) : <Muted>Not recorded</Muted>}</td>
      <td className="is-nowrap"><Link to={WB_ROUTES.case(c.incidentId)}>Open<span className="wb-sr"> case {c.ref}</span></Link></td>
    </tr>
  );
}

export function CasesList() {
  usePageTitle("Cases");
  const { cases, now, fresh } = useWb();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const mode = usePreviewMode();
  const list = listState(params);
  const previewId = params.get("preview");
  const lastRow = useRef(null);
  const tableRef = useRef(null);

  const counts = statusCounts(cases);
  const rows = sortCases(filterCases(cases, list), list.sort);
  const selected = cases.find((c) => c.incidentId === previewId) || null;
  const filtered = !!(list.stage || list.waiting || list.q);

  const set = (key, value, fallback = "") => {
    const next = new URLSearchParams(params);
    if (!value || value === fallback) next.delete(key); else next.set(key, value);
    setParams(next, { replace: true, state: location.state });
  };
  const clearFilters = () => {
    const next = new URLSearchParams(params);
    for (const k of ["stage", "waiting", "q"]) next.delete(k);
    setParams(next, { replace: true, state: location.state });
  };

  const open = useCallback((id) => {
    lastRow.current = id;
    const next = new URLSearchParams(params);
    next.set("preview", id);
    navigate({ search: `?${next}` }, { replace: !!previewId, state: { previewPushed: previewId ? location.state?.previewPushed : true } });
  }, [params, previewId, navigate, location.state]);

  const close = useCallback(() => {
    lastRow.current = previewId || lastRow.current;
    if (location.state?.previewPushed) navigate(-1);
    else { const next = new URLSearchParams(params); next.delete("preview"); setParams(next, { replace: true }); }
  }, [previewId, location.state, navigate, params, setParams]);

  const wasOpen = useRef(previewId);
  useEffect(() => {
    if (wasOpen.current && !previewId && lastRow.current) {
      tableRef.current?.querySelector(`[data-row="${CSS.escape(lastRow.current)}"]`)?.focus();
    }
    wasOpen.current = previewId;
  }, [previewId]);

  useEffect(() => {
    if (mode === "phone" && previewId) navigate(WB_ROUTES.case(previewId), { replace: true });
  }, [mode, previewId, navigate]);

  const onKey = (e, id) => {
    const ids = rows.map((c) => c.incidentId);
    const i = ids.indexOf(id);
    const move = (j) => {
      if (j < 0 || j >= ids.length) return;
      e.preventDefault();
      tableRef.current?.querySelector(`[data-row="${CSS.escape(ids[j])}"]`)?.focus();
      if (previewId && mode === "docked") open(ids[j]);
    };
    if (e.key === "ArrowDown" || e.key === "j" || e.key === "J") move(i + 1);
    else if (e.key === "ArrowUp" || e.key === "k" || e.key === "K") move(i - 1);
    else if (e.key === "Enter" && e.shiftKey) { e.preventDefault(); navigate(WB_ROUTES.case(id)); }
    else if (e.key === "Escape" && previewId) { e.preventDefault(); close(); }
  };

  const unsure = fresh.state === "disconnected" || fresh.state === "stale";
  const docked = mode === "docked" && selected;
  return (
    <div className={`wb-page wb-queue-page ${docked ? "has-preview" : ""}`}>
      <div className="wb-queue-main">
        <header className="wb-page-head">
          <h1 className="wb-page-title">Cases</h1>
          <TitleBlock label="Case counts" cells={[
            { label: "Scope", value: "Latest case per asset" },
            { label: "Active", value: `${counts.active}` },
            { label: "Exceptions", value: `${counts.exceptions}` },
            { label: "Resolved", value: `${counts.resolved}` },
          ]} end={<FreshnessIndicator fresh={fresh} />} />
          <p className="wb-scope-note">Limited history: the live stream carries only the latest case for each asset (G5). Earlier cases on the same asset aren’t listed here.</p>
        </header>

        <div className="wb-filters wb-cl-filters">
          <Segmented label="Status" value={list.status} onChange={(v) => set("status", v, "active")}
            options={STATUS_SEGMENTS.map((s) => ({ value: s.value, label: `${s.label} · ${counts[s.value]}` }))} />
          <label className="wb-cl-filter">
            <span className="wb-label">Stage</span>
            <select className="wb-select" value={list.stage} onChange={(e) => set("stage", e.target.value)}>
              <option value="">Any stage</option>
              {STAGE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="wb-cl-filter">
            <span className="wb-label">Waiting on</span>
            <select className="wb-select" value={list.waiting} onChange={(e) => set("waiting", e.target.value)}>
              <option value="">Anyone</option>
              {WAITING_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="wb-cl-filter">
            <span className="wb-label">Asset</span>
            <input className="wb-input" type="search" value={list.q} placeholder="ID or name" onChange={(e) => set("q", e.target.value)} />
          </label>
          <label className="wb-cl-filter">
            <span className="wb-label">Sort</span>
            <select className="wb-select" value={list.sort} onChange={(e) => set("sort", e.target.value, "attention")}>
              {SORTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </div>

        {rows.length ? (
          <div className="wb-table-wrap" ref={tableRef}>
            <table className="wb-table is-compact wb-cl-table">
              <caption className="wb-table-caption">{rows.length} of {counts.all} {counts.all === 1 ? "case" : "cases"} · select a row to preview; decisions are made in the case, never from this list</caption>
              <thead><tr>
                <th scope="col">Case</th><th scope="col">Stage</th><th scope="col">Waiting on</th><th scope="col">Asset condition</th>
                <th scope="col">Opened</th><th scope="col">Updated</th><th scope="col"><span className="wb-sr">Open</span></th>
              </tr></thead>
              <tbody>
                {rows.map((c) => <CaseRow key={c.incidentId} c={c} selected={c.incidentId === previewId} onOpen={open} onKey={onKey} />)}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="wb-cl-empty">
            <EmptyLine>{unsure ? "Can’t confirm the list is complete: data isn’t current." : filtered ? "No cases match these filters." : EMPTY_FOR[list.status]}</EmptyLine>
            {filtered ? <Button variant="secondary" size="sm" onClick={clearFilters}>Clear filters</Button> : null}
          </div>
        )}
      </div>

      {selected && mode === "docked" ? (
        <DockedPane title="Case preview" titleId="wb-preview-title" onClose={close}>
          <CasePreview c={selected} now={now} />
        </DockedPane>
      ) : null}
      {selected && mode === "modal" ? (
        <ModalDrawer title="Case preview" titleId="wb-preview-title" onClose={close}>
          <CasePreview c={selected} now={now} />
        </ModalDrawer>
      ) : null}
    </div>
  );
}
