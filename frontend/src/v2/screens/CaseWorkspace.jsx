// Case workspace, layout D (F0 §14 recommendation, F4.1): a compact identity row with the lifecycle
// position in one line, a left case navigator ("Now" first, then content sections with their state),
// and one section at a time. The decision surface lives in Now when a decision is pending. Section
// selection is the URL hash, so Back / Forward, reload and the existing deep links (#decision,
// #work, #summary) keep working.
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useWb } from "../shell/WbContext.jsx";
import { usePageTitle, useRoleScope } from "../shell/WbShell.jsx";
import { useSession } from "../../state/session.jsx";
import { ConditionMarker, FreshnessIndicator, SeverityMarker, SimulatedTag, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { StageLine } from "../components/StageLine.jsx";
import { openRequests } from "../model/cases.js";
import { SECTIONS, sectionForHash, sectionStates } from "../model/lifecycle.js";
import { postJson } from "../model/refusal.js";
import { duration, score, when, zoneAbbr } from "../model/format.js";
import { WB_ROUTES } from "../shell/routes.js";
import { CaseNow } from "./CaseNow.jsx";
import { EvidenceSection, InvestigationSection, PlanSection, RecordSection, WorkSection } from "./CaseSections.jsx";
import { RecoveryActions } from "./RecoveryActions.jsx";

function NavMarker({ state }) {
  if (state === "action") return <Shape name="decision" size={14} label="Action required" tone="decision" />;
  if (state === "done") {
    return (
      <span className="wb-casenav-done" role="img" aria-label="Done">
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 7.4 5.8 10 11 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
    );
  }
  if (state === "current") return <Shape name="supported" size={14} label="Current" />;
  if (state === "todo") return <Shape name="notStarted" size={14} label="Not started" />;
  return <span className="wb-shape-blank" aria-hidden="true" />;
}

function Deadline({ c, now }) {
  const r = c.requirement;
  if (!r?.expires_at || c.phase !== "AWAITING_APPROVAL" || c.approval?.state === "invalidated") return null;
  if (c.approval?.state === "expired") return <span>Deadline: expired {when(r.expires_at)}</span>;
  const near = c.expiry?.state === "approaching" || c.expiry?.state === "final";
  return (
    <span className={near ? "wb-deadline-near" : ""}>
      {near ? <Shape name="elevated" size={14} label="Deadline approaching" tone="warning" /> : null}
      Deadline {when(r.expires_at)} {zoneAbbr(new Date(r.expires_at))} · in {duration(Date.parse(r.expires_at) - now)}
    </span>
  );
}

export function CaseWorkspace() {
  const { incidentId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { state, cases, now, fresh } = useWb();
  const { session } = useSession();
  const role = useRoleScope();
  const c = cases.find((x) => x.incidentId === incidentId);
  usePageTitle(c ? `${c.assetId} · case` : "Case");
  const headingRef = useRef(null);
  const focusOnChange = useRef(false);
  const decisionPending = c?.approval?.state === "pending";
  const section = sectionForHash(location.hash, { decisionPending });

  useEffect(() => {
    if (!focusOnChange.current) return;
    focusOnChange.current = false;
    headingRef.current?.focus();
    headingRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [section]);

  // Not projected over the stream (e.g. after a reset): ask the case endpoint, show a safe reason.
  const missing = useMissing(c, incidentId, state.frames);

  if (!c) {
    return (
      <div className="wb-page">
        <h1 className="wb-page-title">{state.frames ? "Couldn’t load the case record" : "Loading case record…"}</h1>
        {missing ? <p className="wb-secondary">{missing}</p> : null}
        <p><Link to={WB_ROUTES.cases}>Back to Cases</Link> · <Link to={WB_ROUTES.actions}>My actions</Link></p>
      </div>
    );
  }

  const history = state.histories?.[c.assetId] || [];
  const warn = state.warnThreshold, trigger = state.triggerThreshold;
  const connected = fresh.state !== "disconnected";
  const onDecide = (body) => postJson(`/api/incidents/${encodeURIComponent(c.incidentId)}/approval`, body);
  const requiresPerson = !!c.response && !!c.waiting?.human;
  const sections = sectionStates(c.alert, { openRequestCount: openRequests(c).length, requiresPerson });
  const current = SECTIONS.find((s) => s.id === section) || SECTIONS[0];
  const go = (id) => (e) => {
    e?.preventDefault();
    if (id === section) { headingRef.current?.focus(); return; }
    focusOnChange.current = true;
    navigate({ search: location.search, hash: `#${id}` });
  };

  let content;
  if (section === "evidence") content = <EvidenceSection c={c} history={history} latestTick={state.tick} warn={warn} trigger={trigger} />;
  else if (section === "investigation") content = <InvestigationSection c={c} />;
  else if (section === "decision") content = <PlanSection c={c} trigger={trigger} decisionPending={decisionPending} goNow={go("now")} />;
  else if (section === "work") content = <WorkSection c={c} />;
  else if (section === "record") content = <RecordSection c={c} />;
  else {
    content = <CaseNow c={c} now={now} trigger={trigger}
      decide={{ session, roleId: role.id, roleLabel: role.label, connected, onDecide }}
      actions={<RecoveryActions key={c.incidentId} c={c} session={session} role={role} connected={connected} now={now} decisionPending={decisionPending} />} />;
  }

  return (
    <div className="wb-case is-d">
      <header className="wb-case-id">
        <nav className="wb-crumbs" aria-label="Breadcrumb">
          <Link to={WB_ROUTES.cases}>Cases</Link><span aria-hidden="true"> / </span><span className="wb-mono" aria-current="page">{c.ref}</span>
        </nav>
        <div className="wb-case-titlerow">
          <h1 className="wb-page-title">Model risk above action gate · {c.assetName}</h1>
          <span className="wb-header-fill" />
          <FreshnessIndicator fresh={fresh} />
          {decisionPending && section !== "now" ? <a className="wb-btn wb-btn-primary wb-btn-md" href="#now" onClick={go("now")}><span>Go to decision</span></a> : null}
        </div>
        <p className="wb-case-facts">
          <span className="wb-fact"><ConditionMarker condition={c.condition} /> <span className="wb-num">{score(c.failureProb)}</span></span>
          <span className="wb-fact">{c.severity ? <SeverityMarker value={c.severity} /> : <SeverityMarker value={c.criticality} basis="Asset criticality" />}</span>
          <span className="wb-fact"><WaitingOn role={c.waiting} prefix /></span>
          <span className="wb-fact"><Deadline c={c} now={now} /></span>
          <span className="wb-fact wb-mono-sm">R{c.revision ?? "?"}</span>
          {c.demo ? <span className="wb-fact"><SimulatedTag /></span> : null}
          {c.environment === "SANDBOX" || c.environment === "PRODUCTION" ? <span className="wb-fact wb-envword">{c.environment === "SANDBOX" ? "Sandbox" : "Production"}</span> : null}
        </p>
        <StageLine alert={c.alert} />
      </header>
      <div className="wb-case-main">
        <nav className="wb-casenav" aria-label="Case sections">
          <ol>
            {sections.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className={`wb-casenav-item is-${s.state} ${s.id === section ? "is-selected" : ""}`}
                  aria-current={s.id === section ? "page" : undefined} onClick={go(s.id)}>
                  <NavMarker state={s.state} />
                  <span className="wb-casenav-label">{s.label}</span>
                  {s.meta ? <span className="wb-casenav-meta">{s.meta}</span> : null}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <section className="wb-case-content" aria-labelledby="wb-case-section">
          <h2 className="wb-case-section-title" id="wb-case-section" tabIndex={-1} ref={headingRef}>{current.label}</h2>
          {content}
        </section>
      </div>
    </div>
  );
}

function useMissing(c, incidentId, frames) {
  const [missing, setMissing] = useState(null);
  useEffect(() => {
    if (c || !frames) return undefined;
    let cancelled = false;
    fetch(`/api/incidents/${encodeURIComponent(incidentId)}`).then(async (r) => {
      if (cancelled) return;
      setMissing(r.ok ? "This case exists but isn’t projected over the live stream (latest case per asset, G5)." : `The server answered HTTP ${r.status}: the case isn’t known.`);
    }).catch(() => { if (!cancelled) setMissing("Couldn’t reach the server."); });
    return () => { cancelled = true; };
  }, [c, incidentId, frames]);
  return missing;
}
