// DEVELOPMENT-ONLY design specimen (08 §11.2 "status-primitives sheet"). Registered only when
// import.meta.env.DEV is true; never part of the production route table. Every value on this page
// is a labelled SPECIMEN placeholder for visual review, not plant or application data.
import { useMemo, useState } from "react";
import { IconSquareCheck, IconSquareX } from "@tabler/icons-react";
import { usePageTitle } from "../shell/WbShell.jsx";
import { AttentionGlyph, Button, Checkbox, ConditionMarker, FreshnessIndicator, InlineAlert, Provenance, SectionHeading, SeverityMarker, SimulatedTag, Tag, TextArea, TitleBlock, WaitingOn } from "../components/ui.jsx";
import { Shape } from "../components/glyphs.jsx";
import { StageTrack } from "../components/StageTrack.jsx";
import { ROLES } from "../model/status.js";
import { DecisionSurface } from "./DecisionSurface.jsx";

function Swatch({ children, label }) {
  return <div className="spec-swatch"><div className="spec-swatch-body">{children}</div><p className="spec-swatch-label">{label}</p></div>;
}

function useSpecimenCase(revision) {
  return useMemo(() => {
    const expires = new Date(Date.now() + 42 * 60000).toISOString();
    return {
      incidentId: "specimen", assetId: "SPECIMEN-01", assetName: "Specimen asset (not plant data)", failureProb: null,
      phase: "AWAITING_APPROVAL", expiry: { state: "approaching" },
      requirement: { id: "req-specimen", expires_at: expires, required_roles: ["maintenance_approver"], status: "PENDING", conditions: ["Specimen condition: exact human approval of this work package is required."] },
      alert: { lifecycle: { requirement_id: "req-specimen-0001", intervention_id: "iv-specimen-0001", intervention_hash: `00000000specimen0000000000000${revision}`, context_revision: revision }, proposal: { governance: { conditions: [] } } },
      rm: {
        intervention: { steps: [{ capability: "create_work_package", parameters: { equipment_id: "SPECIMEN-01", parts: [{ part_id: "PART-SPECIMEN", qty: 1 }], technician_id: "TECH-SPECIMEN" } }] },
        diagnosis: { id: "dx", conclusion: "Specimen diagnosis (placeholder text)", evidence_ids: ["e1", "e2"], hypothesis_ids: ["h1"], alternative_hypothesis_ids: [] },
        hypotheses: [{ id: "h1", mechanism: "Specimen diagnosis (placeholder text)", status: "SUPPORTED", contradicting_evidence_ids: ["e2"] }],
        agent_runs: [],
      },
    };
  }, [revision]);
}

export function Specimen() {
  usePageTitle("Design specimen");
  const [revision, setRevision] = useState(1);
  const [ack, setAck] = useState(false);
  const [text, setText] = useState("short");
  const spec = useSpecimenCase(revision);
  const conds = ["normal", "elevated", "critical", "unknown", "stale"];
  return (
    <div className="wb-page spec">
      <header className="wb-page-head">
        <h1 className="wb-page-title">Design specimen</h1>
        <InlineAlert tone="info" title="Specimen · development-only route · not plant data">
          Component and status states for the Phase 4A visual gate. Values are placeholders; nothing here comes from or reaches the engine.
        </InlineAlert>
      </header>

      <section className="wb-region">
        <SectionHeading index="01" title="Asset condition" meta="16 px (band, title block) · 14 px (cells, inline)" />
        <div className="spec-grid">
          {conds.map((c) => <Swatch key={c} label={`${c} · 16 / 14`}><ConditionMarker condition={c} size={16} /><ConditionMarker condition={c} /></Swatch>)}
        </div>
      </section>

      <section className="wb-region">
        <SectionHeading index="02" title="Data freshness" meta="receipt-time basis until X8" />
        <div className="spec-grid">
          {[
            { state: "live" }, { state: "delayed", ageMs: 25000 }, { state: "stale" }, { state: "disconnected" }, { state: "paused", tick: 1204 }, { state: "measuring" },
          ].map((f) => <Swatch key={f.state} label={f.state}><FreshnessIndicator fresh={f} /></Swatch>)}
        </div>
      </section>

      <section className="wb-region">
        <SectionHeading index="03" title="Waiting on" meta="violet only on the person glyph and role word (CH-1)" />
        <div className="spec-grid">
          {Object.values(ROLES).map((r) => <Swatch key={r.key} label={r.human ? "human (decision cue)" : "system"}><WaitingOn role={r} /></Swatch>)}
          <Swatch label="Ink fallback (CH-1 if recognition fails)"><WaitingOn role={ROLES.approver} quiet /></Swatch>
        </div>
      </section>

      <section className="wb-region">
        <SectionHeading index="04" title="Case stage" meta="position display, not a stepper (R-22)" />
        {["INVESTIGATING", "AWAITING_EVIDENCE", "AWAITING_APPROVAL", "OBSERVING", "ESCALATED"].map((p) => <div key={p} className="spec-track"><StageTrack phase={p} /></div>)}
      </section>

      <section className="wb-region">
        <SectionHeading index="05" title="Severity · attention · provenance" />
        <div className="spec-grid">
          {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <Swatch key={s} label="severity (neutral ink)"><SeverityMarker value={s} /></Swatch>)}
          {["action", "risk", "watch"].map((a) => <Swatch key={a} label={`attention: ${a}`}><AttentionGlyph level={a} /></Swatch>)}
          {["measured", "derived", "model", "human", "simulated"].map((k) => <Swatch key={k} label={`provenance: ${k} (10 px)`}><Provenance kind={k} /></Swatch>)}
          <Swatch label="simulated, consequential"><SimulatedTag /></Swatch>
          <Swatch label="instrument tag"><Tag>SPECIMEN-01</Tag></Swatch>
        </div>
      </section>

      <section className="wb-region">
        <SectionHeading index="06" title="Work, verification and hypothesis states" meta="verified is the only green" />
        <div className="spec-grid">
          {[["planned", "Planned"], ["decision", "Awaiting decision"], ["approved", "Approved"], ["active", "Dispatching"], ["committed", "Work order committed"], ["critical", "Dispatch failed"],
            ["notStarted", "Not started"], ["watch", "Observing"], ["inconclusive", "Inconclusive"], ["verified", "Verified recovery"], ["notRecovered", "Not recovered"],
            ["supported", "Supported"], ["open", "Open"], ["unresolved", "Unresolved"], ["refuted", "Refuted"], ["offline", "Offline"]].map(([s, w]) => (
            <Swatch key={w} label={s}><span className="wb-marker"><Shape name={s} size={14} decorative /> <span className="wb-marker-word">{w}</span></span></Swatch>
          ))}
        </div>
      </section>

      <section className="wb-region">
        <SectionHeading index="07" title="Combination (07 §12.3) and aggregate" meta="two hued glyphs per row at most" />
        <div className="spec-combo">
          <AttentionGlyph level="action" /><ConditionMarker condition="critical" /><span className="wb-mono">SPECIMEN-01</span>
          <span>Awaiting decision · 5/8</span><WaitingOn role={ROLES.approver} prefix /><SeverityMarker value="HIGH" /><span>by 15:12 · in 2 h 41 min</span>
        </div>
        <p className="spec-combo"><ConditionMarker condition="critical" showWord={false} /> 1 critical · <ConditionMarker condition="elevated" showWord={false} /> 2 elevated · 5 normal <span className="wb-secondary">(worst member first, R-14; specimen counts)</span></p>
        <TitleBlock label="Specimen title block" cells={[
          { label: "Asset condition", value: <ConditionMarker condition="critical" size={16} /> },
          { label: "Severity", value: <SeverityMarker value="HIGH" /> },
          { label: "Stage", value: "Awaiting decision · 5/8" },
          { label: "Waiting on", value: <WaitingOn role={ROLES.approver} size={16} /> },
          { label: "Deadline", value: "15:12 · in 2 h 41 min" },
          { label: "Revision", value: <span className="wb-mono">R33</span> },
        ]} />
      </section>

      <section className="wb-region">
        <SectionHeading index="08" title="Controls" meta="inactive = focusable, aria-disabled, reason linked (R-3)" />
        <p className="wb-sr" id="spec-reason">Specimen reason: a blocker must be cleared first.</p>
        {["primary", "secondary", "ghost", "danger"].map((v) => (
          <div key={v} className="spec-row">
            <span className="spec-row-label">{v}</span>
            <Button variant={v} icon={v === "primary" ? IconSquareCheck : v === "danger" ? IconSquareX : undefined}>Default</Button>
            <Button variant={v} inactive reasonId="spec-reason">Inactive</Button>
            <Button variant={v} busy busyLabel="Submitting…">Busy</Button>
            <Button variant={v} disabled>Disabled (irrelevant)</Button>
          </div>
        ))}
        <div className="spec-row">
          <Checkbox checked={ack} onChange={setAck}>Acknowledgement checkbox (specimen)</Checkbox>
        </div>
        <div className="spec-form">
          <TextArea label="Reason (warning level)" hint="Validated on blur after change and on submit" value={text} onChange={setText} message="This reason is short. It will be recorded as written." level="warning" rows={2} />
          <TextArea label="Reason (error level)" value="" onChange={() => {}} message="A reason is required to reject." level="error" rows={2} />
        </div>
        <div className="spec-stack">
          {["info", "warning", "critical", "stale", "offline"].map((t) => <InlineAlert key={t} tone={t} title={`Inline alert · ${t}`}>Specimen message text.</InlineAlert>)}
        </div>
      </section>

      <section className="wb-region">
        <SectionHeading index="09" title="Decision surface states (specimen)" meta="forcing function · approaching deadline · changed since opened" />
        <p className="wb-caption">Placeholder identifiers. The real surface renders only on a case awaiting decision. <Button variant="ghost" size="sm" onClick={() => setRevision((r) => r + 1)}>Specimen: change the bound revision</Button></p>
        <DecisionSurface c={spec} session={{ name: "Specimen decider", role: "maintenance_approver" }} roleLabel="Maintenance approver"
          connected now={Date.now()} trigger={null} onDecide={async () => ({ ok: false, error: "Specimen: nothing is sent to the engine from this page." })} />
      </section>
    </div>
  );
}
