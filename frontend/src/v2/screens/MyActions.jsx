// My actions (08 screen 3) with the queue → preview pattern (08 §4, CH-2 prototype):
//  ≥ 1280 docked preview (≈380 px, pushes content, non-modal) · 768–1279 modal drawer · phone: one pane.
// No decisions from the list. No read / unread state (G7). No burst grouping (G5; 07 §12.5).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { useWb } from "../shell/WbContext.jsx";
import { usePageTitle, useRoleScope } from "../shell/WbShell.jsx";
import { WB_ROUTES } from "../shell/routes.js";
import { ConditionMarker, EmptyLine, FreshnessIndicator, Icon, Muted, Segmented, TitleBlock, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { DockedPane, ModalDrawer, usePreviewMode } from "../components/Overlay.jsx";
import { ROLES, ROLE_QUEUE, stageCompact } from "../model/status.js";
import { reasonLine } from "../model/cases.js";
import { clock, when, duration } from "../model/format.js";
import { CasePreview } from "./CasePreview.jsx";

function roleKeyFor(sessionRoleId) {
  return Object.values(ROLES).find((r) => r.sessionRole === sessionRoleId)?.key || null;
}

function DeadlineCell({ c, now }) {
  const r = c.requirement;
  if (!r?.expires_at) return <Muted>No deadline</Muted>;
  if (c.expiry?.state === "expired") return <span>Expired {when(r.expires_at)}</span>;
  const near = c.expiry?.state === "approaching" || c.expiry?.state === "final";
  return (
    <span className={`wb-q-deadline ${near ? "wb-deadline-near" : ""}`}>
      {near ? <Shape name="elevated" size={14} label="Deadline approaching" tone="warning" /> : null}
      by {when(r.expires_at)} · {duration(Date.parse(r.expires_at) - now)}
    </span>
  );
}

function QueueRow({ c, now, trigger, selected, onOpen, onKey, readOnly }) {
  return (
    <li className={`wb-q-item ${selected ? "is-selected" : ""}`}>
      <button type="button" className="wb-q-row" data-row={c.incidentId} aria-current={selected ? "true" : undefined}
        onClick={() => onOpen(c.incidentId)} onKeyDown={(e) => onKey(e, c.incidentId)}>
        <span className="wb-q-line1">
          {readOnly ? (
            <span className="wb-q-title is-readonly"><span className="wb-mono">{c.assetId}</span> · {c.stage?.label}</span>
          ) : (
            <span className="wb-q-title">
              <Shape name="decision" size={14} decorative tone="decision" />
              {c.response?.verb}
            </span>
          )}
          {readOnly ? <WaitingOn role={c.waiting} prefix /> : <DeadlineCell c={c} now={now} />}
        </span>
        <span className="wb-q-line2">
          <span className="wb-mono">{c.assetId}</span>
          <span className="wb-dot-sep" aria-hidden="true">·</span>
          <span>{c.assetName}</span>
          <span className="wb-dot-sep" aria-hidden="true">·</span>
          <span>{stageCompact(c.phase)}</span>
          <span className="wb-dot-sep" aria-hidden="true">·</span>
          <ConditionMarker condition={c.condition} />
        </span>
        <span className="wb-q-line3">{reasonLine(c, { trigger })}</span>
      </button>
    </li>
  );
}

export function MyActions() {
  usePageTitle("My actions");
  const { state, cases, now, fresh } = useWb();
  const role = useRoleScope();
  const myRoleKey = roleKeyFor(role.id);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const mode = usePreviewMode();
  const scope = params.get("scope") === "all" ? "all" : "mine";
  const previewId = params.get("preview");
  const [othersOpen, setOthersOpen] = useState(false);
  const lastRow = useRef(null);
  const listRef = useRef(null);

  const actionable = cases.filter((c) => c.attention === "action" && c.waiting?.human);
  const mine = actionable.filter((c) => c.waiting.key === myRoleKey);
  const others = actionable.filter((c) => c.waiting.key !== myRoleKey);
  const automated = cases.filter((c) => c.waiting && !c.waiting.human && c.waiting.key !== "none").length;
  const primary = scope === "all" ? actionable : mine;
  const secondary = scope === "all" ? [] : others;
  const visible = useMemo(() => [...primary, ...(othersOpen ? secondary : [])], [primary, secondary, othersOpen]);
  const selected = cases.find((c) => c.incidentId === previewId) || null;

  const open = useCallback((id) => {
    lastRow.current = id;
    const next = new URLSearchParams(params);
    next.set("preview", id);
    // Opening pushes a history entry so Back closes the preview; changing it while open replaces.
    navigate({ search: `?${next}` }, { replace: !!previewId, state: { previewPushed: previewId ? location.state?.previewPushed : true } });
  }, [params, previewId, navigate, location.state]);

  const close = useCallback(() => {
    lastRow.current = previewId || lastRow.current;
    if (location.state?.previewPushed) navigate(-1);
    else { const next = new URLSearchParams(params); next.delete("preview"); setParams(next, { replace: true }); }
  }, [previewId, location.state, navigate, params, setParams]);

  // Return focus to the originating row once the preview has actually closed (08 §4); Back and
  // Close both land here, after the drawer and its inert background are gone.
  const wasOpen = useRef(previewId);
  useEffect(() => {
    if (wasOpen.current && !previewId && lastRow.current) {
      listRef.current?.querySelector(`[data-row="${CSS.escape(lastRow.current)}"]`)?.focus();
    }
    wasOpen.current = previewId;
  }, [previewId]);

  const onKey = (e, id) => {
    const ids = visible.map((c) => c.incidentId);
    const i = ids.indexOf(id);
    const move = (j) => {
      if (j < 0 || j >= ids.length) return;
      e.preventDefault();
      listRef.current?.querySelector(`[data-row="${CSS.escape(ids[j])}"]`)?.focus();
      if (previewId && mode === "docked") open(ids[j]);
    };
    if (e.key === "ArrowDown" || e.key === "j" || e.key === "J") move(i + 1);
    else if (e.key === "ArrowUp" || e.key === "k" || e.key === "K") move(i - 1);
    else if (e.key === "Enter" && e.shiftKey) { e.preventDefault(); navigate(WB_ROUTES.case(id)); }
    else if ((e.key === "o" || e.key === "O") && previewId) { e.preventDefault(); navigate(WB_ROUTES.case(previewId)); }
    else if (e.key === "Escape" && previewId) { e.preventDefault(); close(); }
  };

  // Phone: one pane at a time; a tap opens the workspace directly (no preview).
  useEffect(() => {
    if (mode === "phone" && previewId) navigate(WB_ROUTES.case(previewId), { replace: true });
  }, [mode, previewId, navigate]);

  const setScope = (v) => { const next = new URLSearchParams(params); if (v === "all") next.set("scope", "all"); else next.delete("scope"); setParams(next, { replace: true }); };

  const cells = [
    { label: "Role", value: <>{role.label} <span className="wb-secondary">(declared · G8)</span></> },
    { label: "Requires you", value: `${mine.length}` },
    { label: "Other roles", value: `${others.length}` },
  ];

  const docked = mode === "docked" && selected;
  return (
    <div className={`wb-page wb-queue-page ${docked ? "has-preview" : ""}`}>
      <div className="wb-queue-main">
        <header className="wb-page-head">
          <h1 className="wb-page-title">My actions</h1>
          <TitleBlock label="Queue summary" cells={cells} end={<FreshnessIndicator fresh={fresh} />} />
        </header>
        <div className="wb-filters">
          <Segmented label="Scope" value={scope} onChange={setScope} options={[{ value: "mine", label: "Mine" }, { value: "all", label: "All roles" }]} />
          <span className="wb-filters-meta">Sorted by attention, then deadline · decisions are made in the case, never from this list</span>
        </div>

        <div className="wb-queue" ref={listRef}>
          <section aria-labelledby="q-mine">
            <h2 className="wb-group-head" id="q-mine">
              {scope === "all" ? `Requires a person · ${primary.length}` : `Requires you · ${role.label} · ${primary.length}`}
              {scope === "mine" && ROLE_QUEUE[myRoleKey] ? <span className="wb-group-reason"> · {ROLE_QUEUE[myRoleKey]}</span> : null}
            </h2>
            {primary.length ? (
              <ul className="wb-q-list">
                {primary.map((c) => <QueueRow key={c.incidentId} c={c} now={now} trigger={state.triggerThreshold} selected={c.incidentId === previewId} onOpen={open} onKey={onKey} readOnly={scope === "all" && c.waiting.key !== myRoleKey} />)}
              </ul>
            ) : (
              <EmptyLine>
                {fresh.state === "disconnected" || fresh.state === "stale"
                  ? "Can’t confirm that nothing is waiting on you: data isn’t current."
                  : `Nothing is waiting on ${role.label}. ${automated} ${automated === 1 ? "case is" : "cases are"} in automated stages; ${others.length} waiting on other roles.`}
              </EmptyLine>
            )}
          </section>
          {scope === "mine" ? (
            <section aria-labelledby="q-others" className="wb-q-others">
              <h2 className="wb-group-head" id="q-others">
                <button type="button" className="wb-disclosure" aria-expanded={othersOpen} onClick={() => setOthersOpen((o) => !o)}>
                  <Icon as={othersOpen ? IconChevronDown : IconChevronRight} size={16} />
                  Waiting on other roles · {others.length}
                </button>
              </h2>
              {othersOpen ? (
                others.length ? (
                  <ul className="wb-q-list">
                    {others.map((c) => <QueueRow key={c.incidentId} c={c} now={now} trigger={state.triggerThreshold} selected={c.incidentId === previewId} onOpen={open} onKey={onKey} readOnly />)}
                  </ul>
                ) : <EmptyLine>No items are waiting on other roles.</EmptyLine>
              ) : null}
            </section>
          ) : null}
        </div>
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
