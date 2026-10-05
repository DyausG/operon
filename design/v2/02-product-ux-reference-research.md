# OPERON V2: Product UX reference research & design direction (Phase 2)

Status: Phase 2 (research, interaction-architecture validation, design direction). No application,
frontend, CSS, route or backend change.

Builds on (accepted, not revised):
- [`design/mode.md`](../mode.md) (Phase 0)
- [`01-product-model-and-information-architecture.md`](01-product-model-and-information-architecture.md)
  (Phase 1, commit `478b4ae`)

Where research conflicts with a Phase 1 decision, the conflict is recorded in §18 with an explicit
recommendation. Phase 1 itself is unchanged.

Marker used throughout: **`REQUIRES BACKEND CAPABILITY (Gn)`**. The interaction is desirable but
depends on a backend capability that doesn't exist yet. It must not be faked in the UI.

---

## 1. Executive summary

Across industrial, incident-management, enterprise and AI products, the systems that handle
consequential work well agree on five things:

1. **Normal recedes; exceptions are rationed.** ISA-101 high-performance HMI treats grey as normal
   and colour as "something wrong". ISA-18.2 / EEMUA 191 keep the top alarm priority at roughly
   5 % and treat floods as a design failure.
2. **Every item that demands attention names a required response and an owner.** Examples:
   - the ISA alarm definition, "requiring a response";
   - PagerDuty's "an alert requires a human to perform an action";
   - Maximo's "waiting on approval" and "waiting for material" statuses.
3. **Lifecycles separate "done" from "verified".** Examples:
   - Splunk ITSI: Resolved ≠ Closed;
   - Rootly's maintenance `verifying` status;
   - Datadog Bits: "applied" and "resolved" checked separately;
   - permit-to-work hand-back.

   OPERON's verified-recovery closure is a genuine strength.
4. **Approvals bind to an exact snapshot, expire, fail closed and are audited.** Examples:
   - GitHub stale-approval dismissal;
   - Terraform "Needs Confirmation → Confirm & Apply / Discard";
   - permit-to-work limited validity;
   - AWS Change Manager single-rejection veto.

   OPERON's hash + revision binding is already best-practice. Its **presentation** (expiry,
   consequences, reject path) is not.
5. **AI earns trust through evidence, alternatives and an honest "inconclusive", not through
   narrative or confidence percentages.** Datadog Bits shows hypotheses as validated, invalidated or
   inconclusive in a tree. The over-reliance literature finds that explanations and accuracy claims
   increase acceptance *even when the AI is wrong*. Chain-of-thought is unfaithful (Anthropic: hints
   mentioned in only 25–39 % of cases).

**Recommended direction:** a deliberate hybrid called the **Governed Operations Workbench** (§12–13):
- a *case-workbench* backbone (queue + list/detail + contextual inspector, keyboard-capable);
- an ISA-101-disciplined *plant condition band* that is always present but quiet;
- an *evidence-first investigation view* (hypothesis outcomes, not transcripts) inside each case.

**Terminology:** keep most Phase 1 terms. Practitioner usage raises **one real conflict**:
"Incident" is rare in maintenance and reads as a *safety* incident in many plants. The analytics
industry's word for the evidence-backed escalation container is **"case"** (Senseye, SmartSignal,
AVEVA). This needs product-owner validation (§9, §18).

**Backend:** the G1–G10 matrix (§15) shows that Phase 3 can design all surfaces honestly today,
but four interactions can't be *offered* until the backend supports them:
- technician inspection (G1);
- exception resolution (G2/G3);
- reject-with-route (G4);
- asset history (G5).

The research also exposed two additional gaps, proposed as **G11** and **G12**:
- **G11:** an expired approval requirement can never be renewed.
- **G12:** incidents have no human owner and no acknowledgement.

---

## 2. Research methodology

- **Access date:** 2026-10-05 for all sources.
- **Environment constraint:** the session's egress proxy blocked direct access to most vendor sites
  (PagerDuty, incident.io, Linear, Stripe, IBM, Siemens developer site, MaintainX, Limble, Fiix,
  Augury, ISA, Microsoft Learn, AWS docs, Google PAIR and others).
- **What was reachable:**
  - `docs.datadoghq.com`;
  - public Git repositories cloned read-only outside the OPERON repo (`/home/user/siemens/ix`,
    `/home/user/research/...`). These contain *official* product documentation or design-system
    guidance from Siemens iX, IBM Maximo labs, IBM Carbon, GitHub Docs, Primer, Grafana, Sentry,
    PagerDuty, HashiCorp, Linear (SDK schema), incident.io and Rootly (Terraform providers);
  - web-search summaries of official pages.
- **Evidence levels** (shown for every reference):
  - **DIRECT**: official documentation or repository text read in full.
  - **SNIPPET**: a search-engine summary of an official page; the page itself wasn't read.
  - **SECONDARY**: third-party analysis, reviews or articles.
- **No product screenshots or live UIs were inspected.** Statements about visual layout come only
  from documentation text. Where a conclusion is inferred rather than observed, it is labelled
  *Inference*.
- **Method:** three parallel research passes (industrial / CMMS; incident, observability and
  enterprise UX; AI-agent and approval UX), then synthesis against Phase 0 and Phase 1 by mapping
  each finding onto an OPERON surface, persona, job or gap. A reference is included only if it
  changes or confirms an OPERON decision.
- **OPERON evidence:** backend facts were re-verified in code for this phase (approval expiry
  behaviour, projection contents; see §15).

---

## 3. Industrial product references

| Reference (evidence) | Observed | Conclusion for OPERON |
|---|---|---|
| **Siemens iX design system and guidelines** (DIRECT: `siemens/ix` components, `siemens/ix-docs`) | <ul><li>Status vocabulary Alarm › Critical › Warning › Info / Neutral / Success, each with contrast variants. "Don't use status colors for texts."</li><li>`ix-event-list` with a left colour-indicator stripe.</li><li>`ix-workflow-steps` (open / success / done / warning / error; vertical).</li><li>Non-dismissable `persistent` message bar.</li><li>`ix-kpi` neutral / warning / alarm.</li><li>Alarm-message anatomy: reason + criticality, "Immediate action required" vs "No action required", value / threshold / deviation / duration / location / time, then "What you need to do". Warning copy avoids "may/might".</li><li>AI messages show provenance next to content. Consequential requests are "confirmed once, with consequences".</li><li>The only AI components are chat primitives (`chat-ai-message` with sources/actions slots; "Stop processing").</li></ul> | **Borrow** the status ladder (with a separate text colour), the stripe-indicated event row, the vertical stage tracker, the alarm-message anatomy for attention items, and confirm-once-with-consequences. **Reject** the chat-first AI pattern; OPERON's AI surfaces are evidence and decision surfaces. |
| **IBM Maximo Health / Predict / Monitor** (DIRECT: `IBM/maximo-labs`) | <ul><li>Persona: reliability engineer.</li><li>Asset views: Table (saved views, sort by health / criticality / risk / "days to failure"), Map, Charts, Matrix (Criticality × Health / Risk, "High Need For Action").</li><li>"Work queues": high probability of failure, poor health, **missing data**.</li><li>Predictions per failure mode over a horizon ("20 % probability … next 2 months due to overheating"), days-to-failure with ±, contributing factors with weights, probability history.</li><li>An asset timeline showing predicted failure *next to the next PM* and past work orders.</li><li>Alerts: New → Validated / Acknowledged / Resolved; severity Critical / High / Medium / Low. Alerts become service requests with hierarchy fields inherited.</li></ul> | **Borrow:** prediction stated as mode + probability + horizon; contributing factors (OPERON already has model attribution); a "missing data" queue; the asset timeline; alert → request handoff. **Avoid** Maximo's proliferation of score types and its tile-stacked asset page (see critique). |
| **IBM Maximo Manage / Mobile** (SECONDARY / SNIPPET) | <ul><li>Work-order statuses WAPPR (waiting on approval) → APPR → WMATL (waiting material) → INPRG → COMP → CLOSE.</li><li>Close-out coding Failure class → Problem → Cause → Remedy.</li><li>"Incident"/"Problem" tickets exist only in the HSE and Control Desk (ITIL) modules.</li><li>Maximo Mobile is offline-first with camera, barcode and voice.</li></ul> | **Adapt** "waiting on…" statuses (validates Phase 1 *waiting-on*) and structured close-out coding. Note that "incident" carries an ITIL/HSE meaning in the market leader (§9). |
| **Siemens Senseye PdM** (SNIPPET / SECONDARY) | <ul><li>"Attention Index" ranks assets needing attention.</li><li>A **case** opens at Medium/High; **one open case per asset**; cases hold "insights" as evidence.</li><li>Closing a case requires feedback (useful / not useful), which trains prioritisation.</li></ul> | Strongly validates OPERON's one-active-incident-per-asset rule and evidence container. **Borrow** mandatory close-out feedback (as a future capability, not today) and "attention" framing for triage. |
| **GE Vernova APM SmartSignal** (SNIPPET / SECONDARY) | <ul><li>Alerts ranked by severity; "create a case directly from the alert".</li><li>Prescriptive recommendations grounded in "the library of closed cases".</li><li>ARC analysis: false alarms and sensor failures are the main trust barrier; sensor-health monitoring is the remedy.</li></ul> | **Borrow** data/sensor health shown next to every prediction. Recommendations should cite prior cases (G5 dependency). |
| **AVEVA (Predictive Analytics, InTouch Situational Awareness)** (SNIPPET) | <ul><li>Anomaly → fault diagnostics → time-to-failure → case management.</li><li>Alarms are "triple coded… colour, shape and text".</li></ul> | **Borrow** triple coding: severity never depends on colour alone (also accessibility). |
| **ABB Ability Genix APM** (SNIPPET) | <ul><li>Condition in NAMUR NE107 terms or a severity score.</li><li>A "maintenance workplace" of condition notifications and recommendations across areas, sites and fleets.</li><li>MTBF / MTTR reliability matrix.</li></ul> | **Adapt** the area/line grouping and the "workplace" framing. The term "recommendation" is industry-standard. |
| **Honeywell Forge APM / Inspection Rounds** (SNIPPET) | <ul><li>Fault models with "causes, consequences and corrective actions"; "predict time to fail".</li><li>Inspection Rounds runs on tablets, phones, wearables and rugged devices, offline, with an ATEX Zone 1 variant.</li></ul> | **Borrow** cause → consequence → corrective-action structure for the Plan. Technician input happens on mobile/rugged devices. |
| **Augury** (SNIPPET) | <ul><li>Health levels Acceptable / Monitor / Alarm / Danger, each with diagnosis + recommendation + urgency.</li><li>Alarm/Danger auto-creates MaintainX work orders.</li><li>Augury's own writing: alert fatigue is "an accuracy problem"; "once trust starts to erode, it's very hard to get back."</li></ul> | **Borrow** urgency paired with recommendation. Trust is the product. False positives cost more than they appear to. |
| **MaintainX** (SNIPPET) | <ul><li>Work orders Open / On Hold / In Progress / Done.</li><li>Requests are Pending until approved; approval converts and locks the request.</li><li>Procedure fields include **Inspection Check (Pass / Flag / Fail, where Flag/Fail prompts follow-up)**, photo / file, **signature**, meter reading, **location check-in**.</li><li>The AI "work order brief" has three sections: Context, On This Asset, On Similar Assets.</li></ul> | **Borrow** the technician inspection pattern (Pass / Flag / Fail + evidence + signature) for G1 and the three-part brief structure for incident summaries. |
| **Fiix, Limble, UpKeep** (SNIPPET) | <ul><li>Fiix: configurable statuses inside fixed control groups; closed-as-done ≠ closed-as-not-needed.</li><li>Limble: offline mode, but **request approval cannot be done offline**; per-asset QR codes open request portals.</li><li>UpKeep: offline checklists and photos; asset / location / component hierarchy; QR requests.</li></ul> | **Borrow** fixed lifecycle categories with honest terminal reasons, "authoritative actions require connectivity", and QR asset lookup. |
| **ISA-101** (SNIPPET / SECONDARY) | <ul><li>Display hierarchy: L1 span-of-control overview (no control actions) → L2 unit → L3 detail → L4 diagnostics.</li><li>Grey normal; colour reserved for abnormal.</li></ul> | **Adopt** as OPERON's display hierarchy: L1 Overview, L2 line / queue, L3 asset / case, L4 evidence / inspector. |
| **ISA-18.2 / IEC 62682 / EEMUA 191** (SNIPPET / SECONDARY) | <ul><li>An alarm requires a response.</li><li>States: Normal / Unacknowledged / Acknowledged / RTN-unacknowledged / Shelved (time-bounded) / Suppressed / Out-of-service (needs approval).</li><li>Priority ≈ 80 / 15 / 5.</li><li>A flood is > 10 alarms in 10 minutes. Steady-state target < 1 per 10 minutes.</li></ul> | Every OPERON attention item must name its required response. Ration "Act now". Acknowledge ≠ resolve. Shelving is time-bounded. |

**Critique of industrial references (evidence-based):**
- Maximo's own labs show five or more score types and an asset page of stacked tiles, including a
  "Predictions" tile to "double click to expand" and a demo asset "projected to fail in 0 days"
  alongside a "low probability". That is contradictory signalling (DIRECT). User reviews call it
  clunky with hidden menus (SECONDARY).
- Legacy HMI saturates colour, which ISA-101 exists to correct. Most consoles miss EEMUA upset
  targets (2 of 37 in the ASM benchmark; SNIPPET).
- Vocabulary collides across products: "acknowledge" means *receipt* in ISA-18.2 but *action
  taken* in Siemens Insights Hub (SNIPPET). Statuses are tenant-configurable in Fiix and UpKeep.
- Siemens is deprecating its own status pill (iX v7). Even leaders are still settling status-chip
  patterns.

**Conclusion:** industrial products are strongest on asset hierarchy, prediction semantics and
technician mobility. They are weakest on concurrency, ownership and approval presentation. Those
come from the incident-management family below.

---

## 4. Incident / observability references

| Reference (evidence) | Observed | Conclusion for OPERON |
|---|---|---|
| **PagerDuty** (DIRECT: `PagerDuty/api-schema`, `incident-response-docs`; SNIPPET: support docs) | <ul><li>Incident triggered / acknowledged / resolved; urgency (high / low) separate from priority.</li><li>`pending_actions` (escalate / unacknowledge / resolve at time *t*).</li><li>Acknowledgement timeout re-triggers.</li><li>A typed log of ~16 entry types.</li><li>Process guide: "an alert requires a human to perform an action"; "assume the worst" on severity; handover of unresolved issues at shift end.</li></ul> | **Borrow:**<ul><li>acknowledgement as an *ownership claim with expiry*;</li><li>visible scheduled automatic actions ("Approval expires 14:20");</li><li>typed timeline entries;</li><li>urgency ≠ severity;</li><li>shift handover.</li></ul>**Reject** the 3-state lifecycle as the whole model, and on-call paging as the primary mode (plants run staffed shifts). |
| **Datadog Incidents, Monitors, Bits** (DIRECT) | <ul><li>Incidents Active / **Stable** / Resolved / Completed; SEV-1…5 + Unknown, with an explanatory side panel.</li><li>**Transition forms** require fields at status changes.</li><li>Typed timeline cells; graphs **freeze** after 24 h as evidence.</li><li>Monitors OK / Warn / Alert / **No Data**. "Resolve is not meant for acknowledging." Downtimes silence notifications but not state.</li><li>Approvals: Requested / Approved / Declined, immutable once anyone responds.</li><li>Bits: hypotheses validated / invalidated / **inconclusive**; Hypothesis Tree; "Verify Resolution".</li></ul> | **Borrow:**<ul><li>required evidence at gates;</li><li>frozen evidence snapshots at decision time;</li><li>No Data as a first-class state;</li><li>immutable decision records;</li><li>inconclusive outcomes;</li><li>separate "applied" vs "resolved" verification.</li></ul> |
| **Grafana Alerting** (DIRECT: `grafana/grafana` docs) | <ul><li>Normal / Pending / Alerting / **Recovering** / **No Data** / **Error**, each with a state reason.</li><li>A pending period debounces.</li><li>Silences require a comment and preview affected instances.</li><li>**Inhibition**: a parent alert suppresses dependent alerts.</li><li>Grouping intervals.</li></ul> | **Borrow:**<ul><li>a reason string on every state;</li><li>Recovering ≈ Verifying;</li><li>No Data / Error ≠ Normal (stale sensors);</li><li>a preview of what a suppression affects;</li><li>(future) inhibition along the plant → line → asset hierarchy.</li></ul> |
| **Sentry** (DIRECT: `getsentry/sentry-docs`) | <ul><li>New / Ongoing / Escalating / **Regressed** / Archived / Resolved.</li><li>Archive "until escalating" or until N events.</li><li>A manual priority override freezes auto-adjustment.</li><li>Two-pane inbox ordered by progress (Assigned → Diagnosed → Fix Proposed → Fix Applied).</li><li>Seer agent stop-points ("stop after root cause / plan").</li><li>Humans can edit agent plan steps.</li></ul> | **Borrow:**<ul><li>Regressed (OPERON already has REGRESSED; link to the prior work order);</li><li>progress-ordered personal queue;</li><li>visible override-freezes-automation;</li><li>agent stop-points (OPERON's agents already stop at advice, so say so).</li></ul> |
| **incident.io** (DIRECT: Terraform provider data model; SNIPPET: docs) | <ul><li>Fixed status categories (triage / live / learning / paused / closed / **declined** / **merged** / canceled) with custom sub-statuses inside.</li><li>Policies with deadlines and a named person to chase.</li><li>Investigations with hypothesis + confidence + linked evidence, and an adversarial agent (SNIPPET).</li></ul> | **Borrow:** fixed categories with sub-statuses (OPERON's 8 stages + internal phases), honest terminal reasons, deadline + chase person. |
| **Rootly** (DIRECT: provider data model) | <ul><li>in_triage / started / **mitigated** / resolved / closed / cancelled.</li><li>Scheduled maintenance: planning / scheduled / in_progress / **verifying** / completed.</li></ul> | The maintenance lifecycle with `verifying` maps almost exactly to OPERON's In work → Verifying → Closed. |
| **Splunk ITSI / On-Call** (SNIPPET) | <ul><li>New / In Progress / **Pending** (responsibility temporarily elsewhere) / Resolved ("waiting for verification") / Closed (verified, often by someone else).</li><li>Pop-out-of-Ack.</li></ul> | Closest software analogue to verified recovery. "Pending" validates *waiting on*. |
| **AWS Incident Manager / Health** (SNIPPET) | <ul><li>Overview shows **the current runbook step**.</li><li>Engagements show who responded and who is next.</li><li>Health categories issue / scheduledChange.</li></ul> | **Borrow** "current step + who is next" on the case summary. |
| **Google Cloud Service Health** (SNIPPET) | <ul><li>Emerging / Confirmed / Resolved / Merged.</li><li>Relevance Impacted / Related.</li></ul> | Separate *confidence of a problem* from *relevance to me*. |

**Pattern translation to physical operations:**

| Pattern | Translates? | OPERON adaptation |
|---|---|---|
| Acknowledge = claim ownership; ack timeout re-surfaces | Partly | Claim with *shift-scaled* expiry; re-surface on no progress. **REQUIRES BACKEND CAPABILITY (G12)** |
| Escalation policies / paging | Partly | Show "next escalation / expiry" times; route by shift role, not by pager |
| Urgency ≠ severity | Yes | Time-to-act (expiry, window, risk trend) ≠ consequence (criticality, severity) |
| "Assume the worst" severity | Yes | Physical safety raises the cost of under-classifying |
| Pending period / Recovering / No Data | Yes | Debounce risk; Verifying; stale-data state |
| Silence / shelve | Yes, time-bounded | Shelve with reason + expiry; out-of-service needs approval (future) |
| Instant rollback | **No** | Physical work is irreversible; the plan carries a contingency instead |
| Resolved ≠ Closed (verification) | **Yes, strongly** | Already OPERON's model; make it visible |
| Approval bound to exact diff, stale on change | **Yes, critical** | Already implemented (hash + revision); expose it |
| Chat channel per incident | Partly | The timeline/record is the system of record; no chat dependency |
| Public status page | No | Internal digest only |

---

## 5. Enterprise UX references

| Reference (evidence) | Transferable principle | Not transferable |
|---|---|---|
| **GitHub** (DIRECT: `github/docs`) | <ul><li>Inbox triage by *reason* (assigned, review requested, state change), with Done / Save / Unread.</li><li>Ctrl/Cmd+K command palette scoped to location, with prefix sigils.</li><li>PR review: Comment / Approve / **Request changes**.</li><li>Approval dismissed when the diff changes.</li><li>Environment reviewers, prevent self-review, wait timer.</li><li>Bypass needs a comment + "I understand the consequences…".</li></ul> | Code-centric diff UI |
| **Primer** (DIRECT: `primer/design`) | <ul><li>Data tables only for flat, comparable data; otherwise lists.</li><li>Progressive disclosure used sparingly, preserving context.</li><li>Empty ≠ unavailable: "never show empty when data exists but is unavailable".</li><li>≤ 5 error messages per page.</li><li>Success messaging sparingly.</li><li>No loading indicator < 1 s; skeletons for large areas.</li><li>Explicit save for consequential forms.</li></ul> | GitHub brand styling |
| **Linear** (DIRECT: SDK schema; SNIPPET: docs, design essays) | <ul><li>Triage verbs (Accept / Decline / Duplicate / Snooze), single-key.</li><li>Snooze until a time *or* new activity.</li><li>Graded SLA risk timestamps.</li><li>Space-to-peek.</li><li>Cmd+K.</li><li>"Navigation should recede"; dimmer sidebar, softer contrast.</li></ul> | Its look and its software-team vocabulary (cycles, backlog) |
| **Stripe** (SNIPPET) | <ul><li>Per-object event timeline with typed event names.</li><li>Field-scoped search.</li></ul> | Payments-specific detail layouts |
| **Vercel** (SNIPPET) | Staged ≠ promoted (≈ executed ≠ verified) | Instant rollback |
| **Ramp** (SNIPPET) | <ul><li>Conditional multi-step approval chains (all / any).</li><li>**Request changes** ≠ Reject.</li><li>Delegation recorded "on behalf of".</li><li>Policy changes themselves need approval.</li></ul> | Finance semantics |
| **Retool / Notion** (SNIPPET) | <ul><li>Selection stable by primary key across sort and filter.</li><li>Side peek for lists, full page for deep work.</li></ul> | General-purpose builder chrome |
| **AWS / Datadog consoles** (above) | <ul><li>Detail-page anatomy: header (status, metadata, primary actions) + sidebar (ownership, first / last seen) + tabs.</li><li>Facet filters + saved views.</li></ul> | Cloud-resource density everywhere |

**Synthesis (transferable, not aesthetic):**
1. Navigation recedes; the work area dominates.
2. List + preview (peek) for triage, full page for deep work.
3. One consistent filter syntax and saved views.
4. Keyboard verbs for high-frequency triage, always with visible equivalents.
5. Typed, immutable timelines.
6. Explicit save and confirm for consequential actions.
7. Honest degraded states.
8. Restraint in success and decorative feedback.

---

## 6. Agent / AI interaction references

| Reference (evidence) | Observed | Conclusion for OPERON |
|---|---|---|
| **Datadog Bits Investigation / Remediation** (DIRECT) | <ul><li>Hypotheses tested against telemetry and labelled validated / invalidated / inconclusive (status labels SNIPPET).</li><li>"Investigation Steps" (live) and a "Hypothesis Tree" (after) showing rejected paths.</li><li>"inconclusive when the available data is insufficient".</li><li>Remediation guardrails: **Ask** (named approvers) / **Deny** (recommend only).</li><li>"Verify Resolution" checks applied *and* resolved.</li><li>No numeric confidence documented.</li></ul> | **Closest analogue to OPERON's Investigation.** Use a hypothesis outcome list (supported / refuted / unresolved; OPERON's `Hypothesis` status already has OPEN / SUPPORTED / REFUTED / UNRESOLVED), keep rejected alternatives visible, and treat inconclusive as a valid result. |
| **GitHub Copilot cloud agent** (DIRECT) | <ul><li>Rationale recorded per action ("audit trail of what changed and why").</li><li>Confidence only High / Medium / Low, used to *route* to review.</li><li>"Approvals are a workflow convenience, not a security control" unless enforced server-side.</li><li>Steering applies after the current tool call.</li><li>The initiator's approval doesn't count.</li></ul> | Coarse confidence used for routing; server-side approval enforcement (OPERON has it); supersession takes effect at a declared boundary (PRISM revision fencing); separation of duties (**REQUIRES BACKEND CAPABILITY (G8)**). |
| **IBM Carbon for AI** (DIRECT: `carbon-website`) | <ul><li>"Transparency of AI presence is key", marked at every level.</li><li>Explanations "only when needed or requested". The AI label opens a layered explainability popover (Overview / Supporting details / Artifacts / Actions).</li><li>Overridden AI content loses AI styling and offers "revert".</li></ul> | Label AI-origin content consistently. Use layered, on-demand explanation. Distinguish human-edited from AI-proposed fields. |
| **Siemens iX AI** (DIRECT) | Chat primitives only, with a sources slot and the disclaimer "AI-generated. Always verify." | Not sufficient for decisions; OPERON needs bespoke evidence and decision surfaces. |
| **Microsoft HAX guidelines** (DIRECT, Amershi et al. CHI 2019) | <ul><li>G2: make clear how well the system can do what it does.</li><li>G9: support efficient correction.</li><li>G10: scope services when in doubt.</li><li>G11: make clear why the system did what it did.</li><li>G15: granular feedback.</li><li>G17: global controls.</li><li>G18: notify about changes.</li></ul> | Basis for honest capability statements (deterministic vs live model), inconclusive results and on-demand "why". |
| **Microsoft Aether over-reliance review** (DIRECT, 2022) | <ul><li>Explanations increase reliance *on incorrect* recommendations.</li><li>Stated accuracy raised trust even at 50 %.</li><li>Cognitive forcing functions (checklists, ruling out alternatives, on-demand explanations) reduce over-reliance but are disliked.</li><li>Confidence scores "can backfire".</li><li>Prefer "informative, not just convincing" explanations; dense explanations backfire.</li></ul> | Design the decision surface with **proportionate forcing functions**, short evidence-linked explanations, and no persuasive narrative. |
| **Academic** (SNIPPET: Zhang 2020; Bansal 2021; Buçinca 2021; Parasuraman & Manzey 2010; Xiong ICLR 2024) | <ul><li>Confidence alone doesn't improve decisions.</li><li>Explanations raise acceptance regardless of correctness.</li><li>Automation bias affects experts and teams and isn't fixed by training.</li><li>LLM verbalised confidence is overconfident.</li></ul> | Never display model self-reported confidence as a precise percentage. Derive categorical confidence from evidence. |
| **Anthropic** (DIRECT: "Reasoning models don't always say what they think"; "Building effective agents") | <ul><li>Chain-of-thought faithfulness is low.</li><li>Show *planning steps*, pause for human feedback at checkpoints, use stopping conditions.</li></ul> | Show actions, plans, evidence and checkpoints, **not** reasoning text. |
| **incident.io / PagerDuty SRE agent / ChatGPT agent / Security Copilot** (SNIPPET) | <ul><li>Hypotheses with confidence + linked evidence; an adversarial agent.</li><li>Actions run "upon approval"; "validate service recovery".</li><li>Asks permission before consequential actions; takeover mode.</li><li>Feedback "Looks right / Needs improvement".</li></ul> | Confirms the industry direction: approval-gated actions, recovery validation, adversarial review (OPERON's critic). |
| **Augury patent** (DIRECT patent text, SNIPPET product) | Multiple candidate diagnoses with confidence; advice on when to escalate. | *Inference:* N-best alternatives are more honest than a single score; the product UI is unverified. |

**Answer to the core question.** OPERON shows that agents did meaningful work through **artifacts,
not narration**:

| User needs to see | OPERON source | Presentation |
|---|---|---|
| WHAT the system concluded | `SupervisorReport` disposition, promoted `Diagnosis` | One-line conclusion with status: diagnosed / needs inspection / inconclusive / blocked |
| WHY, at evidence level | `HypothesisSuggestion` supporting / contradicting evidence ids, falsification tests; critic `evidence_gaps` / `contradictions` | Hypothesis outcome list: each hypothesis with supporting and contradicting evidence chips, outcome and critic challenge. Alternatives stay visible. |
| WHAT evidence it used | `Evidence` artifacts (kind, quality, provenance), `evidence_reviewed` | Evidence list with quality and provenance, and freshness at decision time |
| WHAT it recommends | `Intervention` + `MaintenancePlanAssessment` + reviews | Plan as cause → consequence → corrective action; reviewers' findings |
| WHAT it wants permission to do | `ApprovalRequirement` (hash, revision, conditions, expiry) | The decision surface (§7) |
| WHAT happened after execution | `ExecutionReceipt`, `ObservationPlan`, `Outcome` | "Applied?" and "Resolved?" as two results, with recovery evidence |
| WHAT the agent is doing now | run status, PRISM revision | Status line: running / waiting on inspection / superseded by instruction rev N / stopped |

Excluded by default: delegation transcripts, raw model text, token-level progress. These are
available in the artifact inspector for engineers, labelled as advisory model output.

**Confidence rule:**
- Display a **categorical** confidence (High / Medium / Low / Inconclusive).
- State its **basis**: count and quality of supporting vs contradicting evidence, critic verdict,
  data coverage.
- Show N-best alternatives when hypotheses are close.
- Model-reported numeric confidence (`HypothesisSuggestion.confidence`) appears only in the
  inspector, labelled "model-reported".
- Confidence never changes whether approval is required. In OPERON approval is always required,
  and that must stay visible.

---

## 7. Human-approval research → the V2 decision surface

Findings:
- Approval must bind to the exact package (GitHub stale dismissal; Terraform "View Plan" before
  Confirm & Apply).
- Approval expires and fails closed (GitHub 30-day auto-fail; permit-to-work "limited time").
- Separation of duties (GitHub prevent self-review; Copilot initiator rule).
- Three verbs (GitHub Comment / Approve / Request changes; Ramp request changes).
- A single rejection vetoes (AWS Change Manager).
- Reject is a named terminal state for that package, not a deletion (Terraform "Discarded").
- Conflicts and windows are checked at approval *and* at execution (ServiceNow conflict detection;
  AWS change calendar).
- Bypass requires a written reason and an explicit consequence statement (GitHub).
- Confirm once, with consequences (iX).

**What a credible OPERON decision surface communicates** (Phase 3 designs it; Phase 1 D5 makes it
the only approval surface):

| # | Element | OPERON data today | Status |
|---|---|---|---|
| 1 | **The exact action**: asset, steps, parts, technician, window, cost, downtime, avoided loss | `Intervention`, `WorkPackageBinding` | Available |
| 2 | **What it binds to**: intervention hash, context revision, requirement id, plus the statement "any change voids this approval" | `lifecycle` projection | Available |
| 3 | **Why**: diagnosis, key evidence, critic verdict, open evidence gaps, rejected alternatives | Read model | Available |
| 4 | **Reviews of this exact plan**: engineering feasibility, operations resources, critic, planner flags (reversible / safety-relevant / external commitment) | Assessments | Available |
| 5 | **Consequences**: what executing commits (work order, part reservation, labour booking, technician notification); production downtime; what happens if nothing is done (risk trajectory, window) | Local CMMS adapter behaviour, plan | Available (worded from known adapter behaviour) |
| 6 | **Conditions** from governance | `requirement.conditions` | Available |
| 7 | **Deadline**: absolute expiry time, countdown, and the rule ("24 h or window start, whichever is first") | `expires_at` in `GET /api/incidents/{id}` (not in the WebSocket projection) | Available via existing endpoint |
| 8 | **Who may decide**: required role; who requested | `required_roles`; requester = application | Role available; **identity REQUIRES BACKEND CAPABILITY (G8)** |
| 9 | **Verbs**: *Approve and dispatch* · *Reject* (reason required) · *Request changes* (returns to planning with comments) | Approve / Reject exist | Reject reason and route: **REQUIRES BACKEND CAPABILITY (G4)**. Request changes: **REQUIRES BACKEND CAPABILITY (G4)**. |
| 10 | **Forcing function** proportionate to risk: explicit acknowledgement of contradicting evidence or open critic items before Approve | Read model | Design-only (no backend change needed) |
| 11 | **After expiry**: the surface states the requirement expired, that nothing executed, and what renews it | Expiry computed; no renewal path | **REQUIRES BACKEND CAPABILITY (G11)** |
| 12 | **Audit**: decision record (actor, role, time, hash, revision, rationale) linked from the record | `approval_decision` | Available (actor identity G8) |
| 13 | **Re-check at execution**: window and revision re-validated before claim | Execution claim checks | Available; surface the result |

**Recommendation on Reject** (refines Phase 1 G4, doesn't change it):
- Reject should be terminal *for that package* and require a reason.
- It should route to Planning (replan) or Investigating (reinvestigate), chosen by the approver. The
  state graph already permits AWAITING_APPROVAL → PLANNING and → INVESTIGATING.
- Escalation stays a separate, explicit act.
- Until G4 exists, the V2 surface must state plainly: "Rejecting escalates this incident. No
  further automated progress until resolved (G2)."

---

## 8. Information-density principles

**Philosophy: dense where comparison happens, quiet where nothing is wrong, explicit where a human
must act.** This follows from ISA-101 (grey normal, L1–L4) and EEMUA (ration salience), applied to
Phase 0's density rules.

| Scenario | What dominates | What recedes |
|---|---|---|
| Mostly nominal plant | Condition band (all quiet), "Nothing needs you", recent changes | Telemetry, analytics |
| Several elevated assets, no incidents | Watch list (asset, trend, time above band) | Normal assets (counts only) |
| One critical incident | Its case row: stage, waiting on, next step, deadline | Everything else stays put; no layout shift |
| Many concurrent incidents | Grouped queue: waiting on a human first, then by severity and deadline; flood collapse (> N new in 10 min → grouped) | Per-incident detail |
| Pending approvals | Approval items with deadline and asset | Investigation detail |
| Investigation in progress | Case stage + agent status line | Delegation detail (inspector) |
| Failed action | Act-now item with what failed and what is still true (claims, receipts) | — |
| Historical review | Tables, timelines, filters, outcomes | Live status |

**Where information belongs:**

| Container | Use for | Never for |
|---|---|---|
| **Persistent screen space** | System status (stream, reasoning mode, data freshness); action-required count; plant condition band (L1) | KPIs that don't change decisions; demo or engine controls |
| **Visible without scrolling** (case) | Stage, waiting on, next action, deadline, the one-line conclusion | Full evidence, logs |
| **On demand** (inspector, expanders) | Artifact bodies, delegation detail, identifiers in full, model-reported scores | The decision's bound identifiers (always visible on the decision surface) |
| **Tables** | Comparable flat records: assets, cases, work orders, audit entries | Heterogeneous records that need explanation |
| **Lists / queues** | Heterogeneous action items with a required response | — |
| **Cards** | Rarely: a self-contained object summary that is *acted on as a unit* (the decision surface; a work-order summary on mobile) | Metrics, list rows, fleet tiles, evidence items, timeline entries: **never cards just because cards are easy** |
| **Timelines** | Lifecycle history, typed events, the record | Current state (show state, not history, first) |
| **Charts** | Telemetry vs envelope; risk trajectory vs thresholds with annotations (detection, window, execution, observation); performance trends | Decoration, single numbers, categorical counts better shown as text |
| **Contextual side panel** | Artifact inspector, peek of a case or asset from a queue | Primary decisions (approval happens in the case, full width) |

---

## 9. Terminology validation

Practitioner sources:
- standards: EN 13306, ISO 14224, ISA-18.2;
- vendor documentation: Maximo, MaintainX, Fiix, Limble, SAP PM, Senseye, Augury, Siemens iX.

Classification: **KEEP** · **CHANGE** · **CONTEXT DEPENDENT** · **NEEDS USER VALIDATION**.

| Term (Phase 1) | Evidence | Classification | Recommendation |
|---|---|---|---|
| **Asset** | Standard in CMMS / APM (Maximo, MaintainX, Augury); "equipment" in SAP PM / ISO 14224 | **KEEP** | "Asset" in navigation; "equipment" acceptable in labels |
| **Incident** | Rare in maintenance; in Maximo it's an HSE / Control Desk (ITIL) ticket. "Case" is the analytics escalation container in Senseye, SmartSignal and AVEVA, with one per asset and evidence attached (exactly OPERON's object). Risk: plant users read "incident" as a safety event. | **NEEDS USER VALIDATION** | Recommend **"Case"** in the UI (backend keeps `incident`). See §18 conflict C1. |
| **Needs you** | Informal. Industry uses "work queues" (Maximo), "inbox" (Sentry, GitHub), "Immediate action required" (iX) | **CHANGE** (wording) | **"My actions"** (personal queue), with items labelled by required response ("Approve plan", "Inspect", "Resolve escalation"). Final wording: user validation. |
| **Work** | CMMS standard is "work order(s)" | **CHANGE** | **"Work orders"** |
| **Performance** | Reliability teams use MTBF / MTTR / "reliability" (Genix) and "asset health"; "performance" collides with OEE / process performance | **CONTEXT DEPENDENT** | **"Reliability"** if it shows outcomes and failure trends; keep "Performance" only if it becomes OEE-centric |
| **Investigation** | Datadog "Bits Investigation", incident.io "Investigations"; RCA language in plants | **KEEP** | |
| **Evidence** | Senseye "insights as evidence"; Datadog, incident.io | **KEEP** | |
| **Recommendation** | Genix, Honeywell, GE, Augury | **KEEP** | Structure: cause → consequence → corrective action |
| **Approval** | Maximo WAPPR, MaintainX request approval; permit to work for hazardous work | **KEEP** | Verbs: "Approve and dispatch" / "Reject" / "Request changes" |
| **Verification** | "Close-out", "post-maintenance test", "return to service", "hand-back" | **KEEP** (with context) | "Verifying recovery" / "Verified recovery". Avoid "Validation" (collides with internal `VALIDATED` promotion). |
| **Escalated** | PagerDuty: escalation = route to the next responder; plants: escalate to supervisor | **CONTEXT DEPENDENT** | Always show with its required response: "Escalated: engineering decision required" |
| **Waiting on** | Maximo "waiting on approval / material"; Splunk "Pending" | **KEEP** | |
| **Act now** | iX "Immediate action required"; ISA-18.2 top priority is rationed | **CHANGE** | **"Action required"** (top attention) |
| **At risk** | Augury "Alarm / Danger", iX "critical" | **KEEP** | |
| **Watch** | Augury "Monitor"; iX "warning" | **KEEP** | Avoid "Monitor" (collides with monitoring) |
| **Info** | iX "info" | **KEEP** | |
| *(new)* **Alert** | APM detections (Maximo Monitor, SmartSignal). "Alarm" is reserved for process control (ISA-18.2). | **KEEP** (add) | Use "alert" for model detections; never "alarm" |
| *(new)* **Acknowledge** | ISA-18.2: receipt; Insights Hub: action taken; ambiguous across products | **NEEDS USER VALIDATION** | If adopted, define as *"I have seen this and own it"* (ownership claim) and never as resolution. **REQUIRES BACKEND CAPABILITY (G12)** |

---

## 10. Persona task walkthroughs

Notation: **ENTRY → INFORMATION → DECISION → ACTION → FEEDBACK → NEXT STATE.** Each walkthrough
compares current OPERON with the Phase 1 information architecture plus the recommended direction.

### 10.1 Control-room operator: "I just opened OPERON at the start of my shift. What needs attention?"

| Step | Current OPERON | V2 |
|---|---|---|
| ENTRY | `/app/dashboard`; focus is auto-selected (`focusAsset`) | Overview |
| INFORMATION | <ul><li>KPI deck: one pipeline phase shown, invented Value at risk.</li><li>Fleet tiles with risk.</li><li>One focused incident.</li><li>Other incidents only via tiles or the switcher.</li></ul> | <ul><li>Condition band: 8 assets; normal ones quiet.</li><li>"Action required" group: each item's required response, owner, deadline.</li><li>"At risk" and "Watch" groups.</li><li>"Since your last visit" changes.</li><li>System status (reasoning mode, data freshness).</li></ul> |
| DECISION | Which tile to click | Which item to open or hand over |
| ACTION | Click tile → board refocuses | Open case (peek or full); **acknowledge / claim: REQUIRES BACKEND CAPABILITY (G12)** |
| FEEDBACK | Board re-renders | Item shows owner and claim time |
| NEXT STATE | Same page | Case or asset; shift handover digest (future; G7 / G12) |

**Unnecessary navigation today:** cycling through tiles to discover concurrent incidents.
**Missing information:** who owns each incident; what changed since the last shift (notifications
are lost on reload, G7).

### 10.2 Maintenance technician: "I was sent to inspect a machine. What do I inspect, and how do I report it?"

| Step | Current OPERON | V2 |
|---|---|---|
| ENTRY | None. Technicians have no UI. Inspections arrive via the flag-gated API, or as SIMULATED in the Guided Demo. | My actions → "Inspect HYD-PUMP-03" (or QR scan on the asset → asset page → open request) |
| INFORMATION | — | <ul><li>Asset, location (line), safety notes.</li><li>What to check: the evidence request question, the suspected failure mode, falsification tests from hypotheses.</li><li>Due time.</li></ul> |
| DECISION | — | Mechanism confirmed / not confirmed / other finding |
| ACTION | — | Pass / Flag / Fail-style result + notes (+ photo, meter reading, signature in future). **REQUIRES BACKEND CAPABILITY (G1, G8; attachments are a further new capability)** |
| FEEDBACK | — | "Inspection recorded. Diagnosis can now be validated" (`AWAITING_EVIDENCE → INVESTIGATING`) |
| NEXT STATE | — | Case moves on; technician's task closes |

**This is the largest functional gap:** the lifecycle depends on this persona, and the product
offers them nothing. Phase 3 should design it; Phase 6 must deliver G1.

### 10.3 Reliability engineer: "Why does OPERON believe this machine is failing?"

| Step | Current OPERON | V2 |
|---|---|---|
| ENTRY | Machine detail or Agent page | Case (from queue, asset or search) → Investigation |
| INFORMATION | <ul><li>Detection attribution buried in the Timeline tab.</li><li>Evidence slots.</li><li>Specialist chain.</li><li>The Agent page mixes reserved runtime content.</li></ul> | <ul><li>Detection: risk trajectory vs gate, contributing factors (model attribution), data quality.</li><li>Hypothesis outcomes with supporting / contradicting evidence.</li><li>Critic challenges.</li><li>Open evidence requests.</li><li>Categorical confidence with its basis.</li><li>Provenance: live model / deterministic.</li></ul> |
| DECISION | Is the reasoning sound? | Accept direction, request evidence, or redirect |
| ACTION | Send instruction (hidden in the Agent "Activity" tab) | "Direct the investigation" (PRISM revision) inside Investigation |
| FEEDBACK | PRISM panel (revision, fast path) | Acknowledged in < 1 s; status line "Investigating (rev 3, superseded rev 2)"; result replaces the canonical one |
| NEXT STATE | — | Diagnosed or Needs inspection |

**Unnecessary navigation:** Machine ↔ Incident ↔ Agent hopping.
**Missing:** prior cases on this asset (G5); similar assets.

### 10.4 Maintenance supervisor / approver: "OPERON wants to perform an action. Should I allow it?"

| Step | Current OPERON | V2 |
|---|---|---|
| ENTRY | Sidebar badge → dashboard, incident or agent page (three gates) | My actions → "Approve plan for AC-COMP-01 · expires 15:12" → Case → Plan & decision |
| INFORMATION | <ul><li>Exact plan grid.</li><li>Binding row (illegible, overlapping).</li><li>"3 structured reviews" + Validated stamp.</li><li>No expiry or consequences.</li></ul> | All 13 elements of §7: action, binding, why, reviews, consequences, conditions, deadline, eligibility, audit |
| DECISION | Approve / Reject | Approve / Reject / Request changes |
| ACTION | Confirm modal with hash + revision | Confirm once with consequences; forcing function if contradictions or open critic items exist. **Reject reason / route and Request changes: REQUIRES BACKEND CAPABILITY (G4).** |
| FEEDBACK | Optimistic status; phase changes | "Approved at 13:12 by …; work order created; technician notified"; refusal messages if stale |
| NEXT STATE | READY → EXECUTING → OBSERVING | In work → Verifying; the task leaves My actions |

**Missing:** expiry (available through the existing endpoint); "what happens if I do nothing";
approver identity (G8).

### 10.5 Reliability / maintenance manager: "What's unresolved, what's underway, what keeps recurring?"

| Step | Current OPERON | V2 |
|---|---|---|
| ENTRY | Analytics / Incidents | Reliability (Performance) + Cases list |
| INFORMATION | <ul><li>Generation-scoped charts.</li><li>Distributions.</li><li>Economics partly simulated.</li></ul> | <ul><li>Open cases by stage and waiting-on (aging).</li><li>Work orders underway.</li><li>Outcomes (verified / not recovered / regressed).</li><li>Recurrence per asset and failure mode.</li><li>Value with provenance.</li></ul> |
| DECISION | — | Where to intervene (stuck cases, repeat failures) |
| ACTION | — | Drill into a case or asset; (future) reassign (G12) |
| FEEDBACK | — | — |
| NEXT STATE | — | Case / asset |

**Missing:** recurrence and history beyond the current generation. **REQUIRES BACKEND CAPABILITY
(G5, G9).** Escalated cases are stuck with no resolution (G2).

### 10.6 Administrator: "Is OPERON itself healthy and correctly configured?"

| Step | Current OPERON | V2 |
|---|---|---|
| ENTRY | Settings → AI provider / Plant & system; header chip | System status indicator → System |
| INFORMATION | <ul><li>Provider cards, capability chips, test connection.</li><li>Thresholds (read-only).</li><li>Stream state.</li></ul> | <ul><li>Reasoning runtime (provider, model, recent run failures across cases, bounds).</li><li>Data freshness per asset.</li><li>Policies (versions, thresholds).</li><li>Integrations / adapters.</li><li>Simulation & Demo mode.</li></ul> |
| DECISION | Change provider? | Change provider; investigate failing runs |
| ACTION | Select, configure, test | Same (existing `/api/providers`) |
| FEEDBACK | Test result note | Same, plus effect statement ("applies to next run") |
| NEXT STATE | — | — |

**Mostly well supported today.** The V2 change is moving engine and demo controls here and adding
the cross-case runtime view.

---

## 11. Responsive / device strategy

**Evidence:**
- Technicians use offline-first phone and tablet apps (Maximo Mobile, Limble, UpKeep, MaintainX;
  SNIPPET). Hazardous areas use ATEX / intrinsically safe devices (Honeywell Inspection Rounds
  ATEX Zone 1; SNIPPET / SECONDARY).
- Operators work at multi-monitor control-room consoles (EEMUA 201 via IChemE; SNIPPET).
- Reliability engineers use desktop web apps with table, map, matrix and charts (Maximo labs;
  DIRECT).
- Authoritative actions often require connectivity (Limble: no offline request approval; SNIPPET).
- Usage statistics found (44 % tablet / 34 % smartphone among technicians) have no primary
  attribution: indicative only.
- No primary evidence was found for glove-friendly sizes; larger touch targets are an inference.

| Persona | Primary device | Secondary | OPERON should work on |
|---|---|---|---|
| Control-room operator | Control-room workstation (multi-monitor) | Wall display (unconfirmed) | Desktop ≥ 1440 |
| Technician | Phone / tablet (possibly rugged / ATEX), sometimes offline | Shared workstation | **Phone and tablet first** for their tasks |
| Reliability engineer | Desktop / laptop | Tablet for reading | Desktop / laptop |
| Supervisor / approver | Desktop | Tablet / phone away from desk | Desktop full; tablet full; phone limited (below) |
| Manager | Laptop | Tablet | Laptop; tablet read |
| Administrator | Desktop | — | Desktop |

**Workflows that genuinely need mobile (and their honesty status):**

| Workflow | Mobile? | Status |
|---|---|---|
| Inspection submission | **Yes, primary** | **REQUIRES BACKEND CAPABILITY (G1, G8)** |
| Photo / evidence attachment | Yes, eventually | **REQUIRES BACKEND CAPABILITY** (no attachment store; new, beyond G1–G10) |
| Approval | Tablet: yes. Phone: only if the full binding (action, window, cost, hash / revision, expiry) is legible on one screen, and only online. Otherwise show the item and defer. | UI-only constraint plus product-owner decision (Q2 in §19) |
| Acknowledgement / claim | Yes | **REQUIRES BACKEND CAPABILITY (G12)** |
| Notifications | Yes (push, eventually) | **REQUIRES BACKEND CAPABILITY (G7)** |
| Work status (my work orders) | Yes | Read available; status updates **REQUIRE BACKEND CAPABILITY (G10)** |
| Asset lookup (search, QR to asset URL) | Yes | Available: QR codes can encode existing asset URLs; no backend change |
| Investigation detail, analytics, audit, system | No (read-only at best) | — |

**Strategy:**
- **Task-based adaptive layouts, not squeezed desktop.** The phone experience is "My actions + case
  summary + inspection + asset lookup".
- Desktop is the full workbench.
- Tablet is the full workbench minus multi-pane density.
- Authoritative actions require connectivity and state so.

---

## 12. Three OPERON V2 design directions

These are philosophies, not themes.

### Direction A: "Control Room" (monitoring-first)

| Aspect | Description |
|---|---|
| Philosophy | OPERON as a high-performance HMI. The plant is always on screen (ISA-101 L1); everything is reached from the asset. |
| Density | Very high and persistent: all assets with live trends, alert list docked |
| Navigation | Shallow: L1 plant → L2 line → L3 asset → L4 diagnostics; cases open as overlays |
| Workspace model | A fixed multi-region console (overview canvas + alert list + detail pane) |
| Incident presentation | Alert-list rows (stripe-indicated) expanding into a case pane |
| Machine presentation | Dominant: live tiles or trends with envelopes, always visible |
| Agent presentation | Minimal: a status line and conclusion per case |
| Strengths | Unmatched situational awareness; familiar to operators; strong on concurrency at a glance |
| Weaknesses | Weak for approvals, technicians and deep investigation; fixed regions waste space on laptops; mobile is impossible |
| Best personas | Operator |
| Risks | Becomes the "dated HMI imitation" to avoid; telemetry theatre (8 simulated assets streaming persistently); agent value invisible |
| Daily feel | A control-room screen left open all shift |

### Direction B: "Case Workbench" (workflow-first)

| Aspect | Description |
|---|---|
| Philosophy | OPERON as a queue of work that humans and agents move forward (incident.io / Linear / Sentry inbox) |
| Density | Medium-high in lists, calm in detail; telemetry on demand |
| Navigation | My actions / Cases / Assets / Work orders; list + peek + full page; command palette; keyboard verbs |
| Workspace model | Queue → case workspace with sections; side inspector |
| Incident presentation | Primary: stage tracker, waiting-on, next action, decision surface |
| Machine presentation | Secondary pages; condition in rows |
| Agent presentation | Embedded Investigation section with evidence-linked conclusions |
| Strengths | Best for approvers, engineers and accountability; maps cleanly to the Phase 1 information architecture; scales to mobile tasks |
| Weaknesses | Plant awareness only through lists; can feel like generic SaaS; operators lose the "whole plant at a glance" |
| Best personas | Approver, engineer, technician (mobile tasks), manager |
| Risks | "Linear for factories" look-alike; the physical plant becomes abstract |
| Daily feel | A disciplined inbox that empties as work gets done |

### Direction C: "Asset Record & Investigation Studio" (evidence-first)

| Aspect | Description |
|---|---|
| Philosophy | OPERON as the living reliability record of each asset; investigation is the centrepiece (Maximo Health asset timeline + Datadog hypothesis tree) |
| Density | High in the investigation; timelines everywhere |
| Navigation | Asset-first: asset → timeline (condition, cases, work, outcomes) → investigation studio |
| Workspace model | A wide canvas: evidence board, hypothesis outcomes, telemetry annotations side by side |
| Incident presentation | A chapter in the asset's timeline |
| Machine presentation | Primary: a rich asset record |
| Agent presentation | Prominent: hypothesis tree, critic challenges and evidence links are the main canvas |
| Strengths | Showcases OPERON's agentic depth honestly; best for root-cause work and learning from history |
| Weaknesses | Slow for triage and approvals; depends on history the backend doesn't provide (G5, G9); heavy for operators and technicians |
| Best personas | Reliability engineer |
| Risks | Over-exposes agent output and invites automation bias; the analytics surface outgrows the operational one |
| Daily feel | An analyst's workbench opened when something is wrong |

---

## 13. Recommended direction

**A deliberate hybrid, the "Governed Operations Workbench": B as the backbone, with A's discipline
at the top and C's evidence view inside the case.**

| Taken from | What | Why |
|---|---|---|
| **B (backbone)** | My actions, case queue, list + peek + full-page case workspace, single decision surface, command palette, keyboard verbs, mobile task views | Phase 1's central claim is that humans are the blockers and the case is the unit of work. B is the only direction that serves approver, technician and engineer jobs (J2, J7, J8, J9). |
| **A (top band only)** | An always-present, quiet L1 plant condition band (assets by line, grey when normal, triple-coded when abnormal, stale-data visible) and the ISA-101 L1–L4 hierarchy | Keeps the plant physical and gives operators situational awareness without turning the product into an HMI. Phase 0 surface B ("what needs a human now, across every asset"). |
| **C (inside the case and asset)** | The Investigation section as hypothesis outcomes with evidence and critic challenges; the asset page as a timeline of condition, cases, work and outcomes | Shows agent value through artifacts, not chat. The asset timeline is the honest home for history once G5 exists. |

**Why not a pure direction:**
- **A** fails the approver and technician and drifts toward HMI imitation.
- **B alone** loses the plant.
- **C** puts analysis ahead of operations and depends on missing history.

**How it feels in daily use:**
- An operator sees a quiet band and an empty action list on a good day.
- On a bad day the band shows which assets, and the list shows who must do what by when.
- The engineer opens a case and sees *why* in one screen.
- The approver sees exactly what they're committing to and until when.
- The technician sees only their task on a phone.

---

## 14. Conceptual pattern library (for Phase 3)

Purpose only; no styling. "Depends on" lists backend gaps; a pattern can be designed now but not
fully *offered* until its gap is closed.

| Pattern | Purpose | Notes / depends on |
|---|---|---|
| Application shell | Persistent frame: navigation that recedes, system status, action-required count, search, account | Demo and engine controls excluded (System) |
| Global navigation | Move between the six areas; show counts only where they demand action | — |
| Plant / line selector | Scope views to plant → line; single plant today | Line data exists in the schema, not in the snapshot (small backend exposure) |
| Plant condition band (L1) | One-glance condition of every asset; normal recedes | Stale-data state required |
| Attention queue | Ordered list of items requiring a response (who, what, by when) | Inspection / exception items: G1 / G2 / G3 |
| Asset row | Compare assets: id, line, condition, trend, open case, data freshness | — |
| Case (incident) row | Compare cases: reference, asset, stage, waiting on, severity, age / deadline | Human reference G6 |
| Status indicator (condition) | Normal / Elevated / Critical / No data; triple-coded | Never derived from case existence |
| Severity marker | Consequence class, distinct from condition and urgency | `incident.severity` exists, not projected |
| Waiting-on indicator | Who must act next (system / agent / technician / approver / engineer / executor) | Derived from phase |
| Stage tracker | Where a case is in 8 stages + exceptions; loops shown honestly | Internal phase on demand |
| Deadline / expiry indicator | Absolute time + countdown + rule; fails closed | `expires_at` via the case endpoint; renewal G11 |
| Evidence item | One piece of evidence: kind, summary, quality, provenance, freshness, link to artifact | — |
| Hypothesis outcome | A candidate cause with supporting / contradicting evidence and outcome (supported / refuted / unresolved) | Data exists |
| Investigation event | A meaningful agent action (delegation, evidence request, critic verdict, completion), not reasoning text | — |
| Agent status line | What the agent is doing now, on which revision; superseded / stopped | PRISM |
| Instruction composer | Direct the investigation; a revision, not a chat | PRISM |
| Recommendation block | Cause → consequence → corrective action, with reviewers' findings | — |
| Decision surface | The single approval surface (§7) | G4, G8, G11 for full behaviour |
| Inspection form (technician) | Structured result + notes (+ attachments later) | **G1, G8** |
| Work item | A committed work order: technician, parts, window, receipt | Status updates G10 |
| Verification result | Applied? Resolved? Before / after evidence; outcome | — |
| Event timeline | Typed, immutable history of a case / asset / system | — |
| Provenance marker | Authoritative / advisory / trusted input / human decision / simulated / deterministic | Phase 0 constraint |
| Confidence marker | Categorical confidence + basis; "inconclusive" | §6 rule |
| Update (notification) | Pointer to what changed, with read state | Durable G7 |
| Acknowledge / claim control | Take ownership of an item | **G12** |
| Empty state | First use / nothing to do / filtered-empty, each worded differently | Primer distinctions |
| Degraded-data state | Data exists but is stale or unavailable; never shown as empty or normal | — |
| Loading state | No indicator < 1 s; skeleton for large regions | — |
| Error / refusal state | Why an action was refused (stale revision, expired requirement) and what to do | Lifecycle refusal messages exist |
| Confirmation | Confirm once, stating consequences | — |
| Filter / search controls | Consistent `key:value` filters, saved views, command palette | — |
| Artifact inspector | Layered, on-demand detail and provenance of any record | Existing `#artifact=` |
| Demo-mode frame | Clearly bounded presentation layer over the real product | Phase 0 surface I |

---

## 15. G1–G10 dependency matrix (+ proposed G11, G12)

Backend facts re-verified for this phase:
- `lifecycle.py:293-307` (`_approval_state` incl. EXPIRED), `:590` (only caller of
  `request_approval`), `:622-625` (re-issue only if expired), `:680-681` (decision requires
  PENDING), `:1003` (`expires_at` in the incident projection);
- `server/main.py:202-238` (flag-gated trusted endpoints);
- `selectors.js:22` (triage rank used for sort only).

| Gap | Backend today | Current UI implies | V2 ideally needs | Phase 3 depends on it? | Representable honestly before implementation? | Phase 6 priority |
|---|---|---|---|---|---|---|
| **G1** Trusted inspection & resource confirmation | Endpoints exist; disabled unless `OPERON_TRUSTED_SUBMISSIONS=1`; unauthenticated; free-form actor | "Physical inspection is required… cannot supply it"; nothing to do | Technician inspection form; approver resource confirmation | Yes (inspection form, technician mobile) | Yes: show "Waiting on technician inspection", who / what is needed, and that submission isn't available in this deployment | **P1** |
| **G2** Escalation resolution (resume / cancel) | No endpoint; CANCELLED unreachable; escalation blocks new admission for the asset | "Remains active… explicit decision resumes or cancels" (no control) | Resume investigation / cancel with reason | Yes (exception surfaces) | Yes: "Escalated: engineering decision required. Resolution isn't available yet; this asset can't open a new case until resolved." | **P1** |
| **G3** Retry failed execution | `retry_execution` exists, no caller or endpoint | ExceptionalRecord only | Retry / reinvestigate / cancel | Yes | Yes: show failed step, receipts, "retry not available" | P2 |
| **G4** Reject → replan / reinvestigate with reason; request changes | REJECT → ESCALATED | Reject button without consequence statement | Reject (reason, route) + Request changes | Yes (decision surface) | Yes: state "Rejecting escalates this case" until G4 | **P1** |
| **G5** Incident history per asset | Only latest incident per asset projected (`self.alerts[eid]`; reducer keyed by `equipment_id`); DB keeps all | "Past" shows one, labelled "Closed / Verified" even when cancelled | Full case history per asset; recurrence | Yes (asset timeline, manager walkthrough) | Partly: show "latest case only in this build" | **P1** |
| **G6** Human-readable case reference | UUID only | UUID / short hash shown | `CASE-0042`-style reference | Yes (rows, deep links) | Yes: asset + opened time as interim label | P2 |
| **G7** Durable per-user updates | Browser-only event log; backend `notification` table unexposed | Notifications lost on reload | Server-side updates, read state, push | Partly (Updates, handover) | Yes: label "this session only" (already done) | P2 |
| **G8** Authentication / identity / roles | Caller-declared `actor_id` / `actor_role`; no users | Demo sign-in; roles presentation-only | Real identity, role-gated actions, separation of duties | Partly (role-aware defaults, approver eligibility) | Yes: "Demo session; approvals recorded as dashboard operator" (already stated) | **P1** (prerequisite for G1 and G12 trust) |
| **G9** Long-horizon performance data | Generation-scoped analytics (≈ 90 ticks) | Charts as if historical | Persistent trends, MTBF / recurrence | Partly (Reliability) | Yes: scope labels ("this run") | P3 |
| **G10** Work-order status lifecycle | Written once (OPEN / RESERVED / BOOKED / READY), never updated | Maintenance table shows static statuses | In progress / on hold / done / closed-not-needed | Partly (Work orders) | Yes: "status as committed; field updates not connected" | P2 |
| **G11 (new)** Approval renewal after expiry | Requirement EXPIRED → decisions refused; no caller re-issues; case stuck in AWAITING_APPROVAL | Nothing (expiry not shown) | Re-request / replan on expiry; visible countdown | Yes (deadline indicator, decision surface) | Yes: show expiry; after expiry show "Expired: nothing executed; renewal not available yet" | **P1** |
| **G12 (new)** Ownership & acknowledgement | No human owner or assignee on `incident`; backend `alert.ACKNOWLEDGED` unused | "Handling" column shows phase-derived owner kind | Claim / acknowledge (ownership with expiry), assignee, handover | Partly (queue, walkthrough 10.1) | Yes: show waiting-on role only; no fake assignee | P2 |

**Specific examinations requested:**

| Topic | Finding |
|---|---|
| Technician inspection / resource confirmation | G1; design now, label unavailable |
| Escalation resolution / cancellation | G2 + unreachable CANCELLED; highest operational risk, because cases dead-end and block assets |
| Retry / resume | G3 (retry) and G2 (resume) |
| Historical incidents | G5 |
| Approval behaviour / expiry | Always required (by design); expiry available via the existing incident endpoint and displayable now; renewal is G11 |
| Notification delivery / history | G7; backend `notification` rows (technician SMS recorded as SENT) can be shown as "dispatch notification recorded" from the work-package commit without implying real delivery |
| Plant / line hierarchy | In the schema (`plant`, `assembly_line`), not projected; small backend exposure needed for the line selector |
| Severity / triage exposure | `incident.severity`, `triage_score` and `triage_rank` exist; rank used only for sort; severity not projected per alert (small backend exposure) |

---

## 16. OPERON anti-patterns ("OPERON must not become")

| Anti-pattern | Evidence | OPERON-specific form |
|---|---|---|
| Dashboard of interchangeable cards | Primer: tables only for comparable data; Maximo's tile-stacked asset page (DIRECT) | KPI tiles for fleet, pipeline, OEE and value as the first thing on screen |
| Excessive gradients / glows / colour | ISA-101 grey-normal; iX "don't use status colours for text"; AVEVA triple coding | Glowing "AI" accents, coloured rows for normal assets |
| AI chatbot as the main interface | Carbon (explanations on demand, in context); iX AI = chat primitives only; HAX G11; a chat transcript can't bind an approval | Turning PRISM instructions into a chat thread with avatars |
| Fake live metrics | OPERON KpiDeck fallbacks (OEE 0.71, Value at risk formula); Augury on trust erosion | Any number without source and scope; simulated values unlabelled |
| Decorative charts | Primer; Phase 0 | Sparklines everywhere regardless of decision value |
| Excessive status colours | ISA-18.2 rationing; Siemens deprecating pills | Every phase coloured; status chips on every row |
| Hidden approval consequences | GitHub "I understand the consequences"; ServiceNow conflicts; iX confirm-with-consequences | Approve button without what it commits, until when, and what it voids |
| Unexplained agent confidence | Aether ("confidence can backfire"); Xiong (LLM overconfidence); Zhang | "92 % confident" badges from model self-report |
| Walls of agent logs | Aether ("dense explanations backfire"); Anthropic | The current delegation and console stream as the main investigation view |
| Exposing chain-of-thought | Anthropic faithfulness (25–39 %) | Raw model text presented as justification |
| Treating every event as equally important | EEMUA floods; PagerDuty "alert requires action" | Notifications for every phase change; unread count as urgency |
| Demo controls in operations | Phase 0 / 1 | Engine menu, "Run Guided Demo here", static HITL badge in the operational chrome |
| Desktop squeezed onto mobile | Limble / Maximo mobile task apps; Phase 0 at 390 px | The 3-column board stacked into a long scroll; an illegible binding on a phone |
| Animations obscuring state | Phase 0 motion rules | Animated stage transitions that hide the current phase or move the Approve button |
| **Resolve that isn't resolved** | Datadog ("resolve is not meant for acknowledging"); Splunk Resolved ≠ Closed | Showing "Closed / Verified" for cancelled or failed cases (current IncidentSwitcher bug) |
| **Empty when unavailable** | Primer degraded-experience guidance; Grafana No Data | A stale sensor rendered as a calm normal asset |
| **Condition from case existence** | Phase 1 | "CRITICAL" at 0.00 risk via status override |
| **Approval that outlives its basis** | GitHub stale approvals; permit-to-work validity | Hiding expiry; allowing a decision UI after expiry |
| **Self-approval** | GitHub prevent self-review; Copilot rule | Same identity requesting and approving (once G8 exists) |
| **Silent dead ends** | Phase 1 G2 / G4 / G11 | Cases that can't progress, shown as "active" without saying who can unblock them, or that nobody can |
| **Persuasive AI copy** | Aether, Bansal 2021 | "OPERON is confident this will fix…"; narrative in place of evidence |

---

## 17. Design principles for Phase 3

1. **Name the response.** Every attention item states the required response, who owns it, and by
   when (ISA-18.2, PagerDuty, iX alarm anatomy).
2. **Normal recedes; exceptions are rationed and triple-coded** (ISA-101, EEMUA, AVEVA).
3. **One decision, one place, fully bound.** The decision surface shows action, binding,
   consequences, deadline and eligibility, and fails closed (GitHub, Terraform, permit-to-work).
4. **Artifacts over narration.** Show conclusions, hypotheses, evidence, reviews and outcomes,
   never reasoning text by default (Datadog Bits, Carbon, Anthropic).
5. **Honest uncertainty.** Categorical confidence with its basis; "inconclusive" is a valid result;
   no model-reported percentages up front (Aether, Xiong, Datadog).
6. **Done ≠ verified.** "Applied" and "resolved" are separate, visible results (Splunk, Datadog,
   Rootly).
7. **Degraded ≠ empty ≠ normal.** Stale or unavailable data has its own state (Primer, Grafana).
8. **Queue → peek → workspace.** Triage in lists, deep work in full pages, provenance in the side
   inspector (Sentry, Linear, Notion).
9. **Tables for comparison, timelines for history, charts for trajectories against thresholds,
   cards almost never.**
10. **Task-shaped mobile.** Technicians and approvers get purpose-built small-screen flows; dense
    surfaces don't shrink, they are omitted.
11. **Never fake capability.** Unsupported actions are absent, with a plain statement of why, and
    are marked `REQUIRES BACKEND CAPABILITY` in design artifacts.
12. **Typed, immutable record.** Every authoritative act appears in a typed timeline with actor,
    revision and reason.
13. **Demo is a frame, not a feature.** Presentation aids live only in Demo mode.

---

## 18. Decisions proposed

| # | Proposal | Relation to Phase 1 |
|---|---|---|
| P1 | Adopt the **Governed Operations Workbench** hybrid (§13) as the Phase 3 direction | Implements Phase 1 information architecture |
| P2 | Adopt ISA-101 display levels as the information hierarchy (L1 Overview, L2 line / queue, L3 asset / case, L4 evidence / inspector) | Consistent |
| P3 | Adopt the §7 decision-surface content as the Phase 3 specification for D5 | Extends D5 |
| P4 | Confidence rule (§6): categorical + basis + alternatives; numeric only in the inspector | Refines §13 of Phase 1 |
| P5 | Add proposed gaps **G11** (approval renewal) and **G12** (ownership / acknowledgement) to the Phase 6 backlog | Adds to G1–G10 (unchanged) |
| P6 | Phase 6 priority order: **G2, G4, G11, G1 + G8, G5**, then G3, G6, G7, G10, G12, then G9 | New |
| P7 | Terminology changes: Work → Work orders; Needs you → My actions; Act now → Action required; add Alert; Performance → Reliability (conditional) | **Conflict C2** (D11 wording; Phase 1 allowed revisiting in Phase 3) |
| P8 | **Conflict C1: "Incident" vs "Case."** Evidence suggests "Case" is the industry term for OPERON's object and avoids the safety-incident reading. Recommendation: use **"Case"** in the UI and keep `incident` in backend and API. Phase 1 D11 kept "Incident". **Product-owner decision required.** | **Conflicts with Phase 1 D11** |
| P9 | Treat expiry as displayable now via `GET /api/incidents/{id}`; no fake countdown from WebSocket data | Consistent |
| P10 | **Conflict C3: Overview composition.** Phase 1 put "Needs you" both in the global header and as a nav item. Research (Sentry / GitHub inboxes) supports **one** personal queue as a primary destination, with the header showing its count only. | Refines Phase 1 §9 (no structural change) |

---

## 19. Questions requiring product-owner input

1. **Case vs Incident** (P8 / C1): which term should plant users see?
2. **Mobile approval:** may approvals happen on a phone (with the full-binding-on-one-screen rule),
   or tablet and desktop only?
3. **Technician channel:** will technicians use OPERON directly (phone / tablet), or will
   inspections arrive via a CMMS integration? This decides the priority of the inspection form.
4. **Acknowledgement / ownership (G12):** do you want explicit claim / acknowledge with shift-scaled
   expiry, or is waiting-on-role enough for V2?
5. **Reject routing (G4):** should the approver choose replan vs reinvestigate, or should OPERON
   decide?
6. **Phase 6 order (P6):** confirm or reorder.
7. **Navigation labels (P7):** "My actions", "Work orders", "Reliability": acceptable?
8. **Wall display:** is an always-on control-room display (Direction A's strength) a real
   requirement? If yes, Phase 3 adds an L1 display mode.
9. **Attachments (photos)** for inspections: in V2 scope (new backend capability) or later?
10. **Forcing functions:** are you comfortable with deliberate friction on Approve when contradicting
    evidence or open critic items exist?

---

## 20. Sources

All accessed **2026-10-05**.

### Industrial / CMMS

| Source | Evidence |
|---|---|
| Siemens iX components: `github.com/siemens/ix` (`packages/core/src/components`, HEAD `3bb92a7`) | DIRECT |
| Siemens iX guidelines: `github.com/siemens/ix-docs` (`docs/styles/colors.md`; `components/pill/guide.md`; `components/ai-message/guide.md`; `guidelines/mobile/mobile-ux.md`; `guidelines/language/messaging/*`; `guidelines/language/operational-emails/operative-alarms-and-events/*`; `guidelines/conversational-design/designing-conversations/confirming-request.md`; `guidelines/language/menu-functions-and-ui-labels/ui-terminology.md`) | DIRECT |
| IBM Maximo labs: `github.com/IBM/maximo-labs` (`MkDocs/apm_9.0/docs/{demo_script,health_scoring_intro,default_score_setup}.md`; `monitor_alerts_9.1/docs/{servicerequest,view_alert,hierarchyAlerts}.md`; `monitor_smart_alerts_9.2/docs/*`) | DIRECT |
| maximoinsideout.blogspot.com/2015/09/work-order-status-flow.html; facilities.berkeley.edu/faq/maximo/what-do-different-statuses-work-order-mean; maximosecrets.com/glossary/failure-hierarchy/; maximosecrets.com/2021/11/19/incidents-and-problems/; themaximoguys.ai/blog/mas-manage-maximo-mobile | SECONDARY |
| apps.apple.com/us/app/ibm-maximo-mobile-for-eam/id1547495854 | SNIPPET |
| capterra.com/p/240578/IBM-Maximo/reviews/; g2.com/products/ibm-maximo-application-suite/reviews | SECONDARY |
| developer.siemens.com/senseye/introduction/terminology.html | SNIPPET |
| machinebuilding.net/senseyes-attention-index-ai-improves-predictive-maintenance | SECONDARY |
| blog.siemens.com/en/2025/12/predictive-maintenance-with-generative-ai-senseye-anticipates-when-there-will-be-trouble-at-the-factory/ | SNIPPET |
| automation.com/article/siemens-industrial-copilot-generative-ai | SECONDARY |
| developer.siemens.com/insights-hub/docs/apis/advanced-eventmanagement/api-eventmanagement-overview.html; documentation.mindsphere.io/MindSphere/apps/insights-hub-monitor/assets.html | SNIPPET |
| gevernova.com/software/documentation/cloud-apm/usw/pdf/SmartSignal.pdf; gevernova.com/software/blog/intelligence-at-work-alert-that-knows-the-next-step | SNIPPET |
| arcweb.com/blog/ge-vernovas-smartsignal-roadmap-targets-trust-predictive-maintenance | SECONDARY |
| aveva.com/en/solutions/operations/asset-analytics/; aveva.com/en/solutions/operations/situational-awareness/ | SNIPPET |
| library.e.abb.com/public/2d016171d5d14734bd601f30fdc4cdcb/ABB_Ability_Genix_APM_Brochure_V3.pdf; new.abb.com/process-automation/genix/genix-apm | SNIPPET |
| process.honeywell.com/content/dam/forge/en/documents/brochures/hon-asset-performance-management-brochure.pdf; process.honeywell.com/us/en/solutions/honeywell-forge/honeywell-forge-inspection-rounds | SNIPPET |
| augury.com/blog/customers-partners/from-alert-to-action-5-things-to-know-about-the-augury-maintainx-integration/; augury.com/blog/machine-health/why-your-team-has-stopped-trusting-their-predictive-maintenance-alerts/ | SNIPPET |
| help.getmaintainx.com/{about-work-orders, view-and-filter-work-requests, procedure-fields, complete-a-work-order-with-maintainx-assist, ai-basics} | SNIPPET |
| helpdesk.fiixsoftware.com/hc/en-us/articles/{17578832400020, 360046681792, 4413562238740} | SNIPPET |
| arcweb.com/blog/rockwell-automation-added-genai-prescriptive-work-orders-fiix-asset-risk-predictor-software | SECONDARY |
| help.limblecmms.com/en/articles/{8857152-offline-mode, 2982723-work-requests-overview}; upkeep.com/product/mobile-cmms/ | SNIPPET |
| help.sap.com (Notification Type); sap-plant-maintenance.com/sap-pm-notification-or-work-order/ | SNIPPET / SECONDARY |
| ISA-101: ww2.isa.org/standards-publications/isa-publications/intech-magazine/2012/december/system-integration-the-high-performance-hmi/; automation.com/en-us/articles/2015-1/isa-101-toward-a-more-effective-hmi-strategy | SNIPPET |
| ISA-101: docs.tatsoft.com/display/FX/ISA-101+HMI+Compliance+How-to+Guide; ladx.ai/resources/isa-101-hmi-design | SECONDARY |
| ISA-18.2 / EEMUA: isa.org PAS "Understanding ISA-18.2" PDF; exida.com Alarm Management PDF and blog; Honeywell ASM / EEMUA benchmarking paper | SNIPPET |
| ISA-18.2 / EEMUA: processonline.com.au improving-alarm-management-with-isa-18-2-part-2 | SECONDARY |
| ISA-18.2 / EEMUA: icheme.org/media/19390/hazards-29-paper-10.pdf | SNIPPET |
| Standards & practice: ISO 14224 / EN 13306 summaries (standard.no presentation; intechopen.com/chapters/67580); namur.net NE107; instrumentationtools.com NE107 | SNIPPET |
| Standards & practice: reliabilityweb.com work-order completion; f7i.ai repair verification; intellipermit.com LOTO / permit to work | SECONDARY |
| Devices: bartec.com intrinsically safe phones; oxmaint.com; mpulsesoftware.com; getmaintainx.com State of Industrial Maintenance 2024 | SECONDARY / SNIPPET |

### Incident / observability / enterprise

| Source | Evidence |
|---|---|
| Datadog: docs.datadoghq.com/incident_response/incident_management/ (+ investigate/declare, describe, timeline; setup_and_configuration, information, transition_forms, responder_roles; post_incident, follow-ups) | DIRECT |
| Datadog: docs.datadoghq.com/incident_response/work_management/approvals/ | DIRECT |
| Datadog: docs.datadoghq.com/monitors/{downtimes, manage, status/status_page, status/events}/ | DIRECT |
| Datadog: docs.datadoghq.com/watchdog/alerts/ | DIRECT |
| Datadog: docs.datadoghq.com/bits_ai/{bits_investigation, bits_investigation/investigate_issues, bits_investigation/improve_accuracy, bits_remediation}/; datadoghq.com/blog/building-bits-ai-sre/ | DIRECT |
| Datadog: datadoghq.com/blog/bits-ai-sre/ | SNIPPET |
| Repositories: github.com/grafana/grafana (`docs/sources/alerting`); github.com/getsentry/sentry-docs (`docs/product/issues`, `ai-in-sentry/seer/autofix`); github.com/github/docs; github.com/primer/design | DIRECT |
| Repositories: github.com/PagerDuty/api-schema; github.com/PagerDuty/incident-response-docs; github.com/incident-io/terraform-provider-incident; github.com/rootlyhq/terraform-provider-rootly; github.com/linear/linear (SDK schema) | DIRECT |
| support.pagerduty.com/main/docs/incidents; support.pagerduty.com/main/docs/escalation-policies | SNIPPET |
| docs.incident.io/incidents/lifecycle; help.incident.io/articles/9326198278-follow-ups | SNIPPET |
| linear.app/docs/{triage, peek, display-options}; linear.app/now/how-we-redesigned-the-linear-ui; linear.app/now/behind-the-latest-design-refresh | SNIPPET |
| docs.stripe.com/dashboard/search; docs.stripe.com/development/dashboard/events | SNIPPET |
| vercel.com/docs/instant-rollback; vercel.com/docs/deployments/promoting-a-deployment | SNIPPET |
| support.ramp.com (spend-request approvals; delegate approvers); ramp.com/blog/multistep-approvals-for-corporate-cards-reimbursements | SNIPPET |
| help.splunk.com (ITSI episode statuses; On-Call incidents, auto-resolve / pop-out-of-ack) | SNIPPET |
| docs.aws.amazon.com/incident-manager/latest/userguide/{tracking-details, response-plans}.html; docs.aws.amazon.com/health/latest/APIReference/API_Event.html | SNIPPET |
| docs.cloud.google.com/service-health/docs/concepts | SNIPPET |
| grafana.com IRM incident-response-settings | SNIPPET |
| docs.retool.com/apps/guides/data/table/rows; notion.com/help/views-filters-and-sorts | SNIPPET |
| ISA-18.2 context: merobix.com/blog/what-is-isa-18-2 | SECONDARY |

### AI / agent / approval

| Source | Evidence |
|---|---|
| GitHub Docs (`github.com/github/docs`, = docs.github.com): Copilot cloud agent (`about-automation-rationale-and-approvals`, `about-automations`, `agent-management`, `manage-rationale-confidence-approvals`, `manage-and-track-agents`, `review-copilot-output`) | DIRECT |
| GitHub Docs: deployments and environments; reviewing deployments; protected branches; reviewing pull requests | DIRECT |
| HashiCorp `web-unified-docs` (HCP Terraform run states / UI) | DIRECT |
| IBM Carbon (`github.com/carbon-design-system/carbon-website`): `guidelines/carbon-for-ai`, `components/ai-label/usage` | DIRECT |
| Microsoft HAX: microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/ (camera-ready PDF) | DIRECT |
| Microsoft HAX: microsoft.com/en-us/haxtoolkit/ai-guidelines/ | SNIPPET |
| Microsoft Aether over-reliance review: microsoft.com/en-us/research/wp-content/uploads/2022/06/Aether-Overreliance-on-AI-Review-Final-6.21.22.pdf | DIRECT |
| Google PAIR: pair.withgoogle.com/chapter/explainability-trust/ | SNIPPET |
| Academic: Zhang, Liao & Bellamy FAT* 2020 (semanticscholar); Bansal et al. CHI 2021 (idl.cs.washington.edu); Buçinca et al. CSCW 2021 (eecs.harvard.edu); Parasuraman & Manzey Human Factors 2010 (journals.sagepub.com); Xiong et al. ICLR 2024 (proceedings.iclr.cc) | SNIPPET |
| Anthropic: anthropic.com/research/reasoning-models-dont-say-think; anthropic.com/engineering/building-effective-agents | DIRECT |
| AWS Systems Manager Change Manager userguide (approvals templates, change-requests-review) | SNIPPET |
| ServiceNow change-management data sheet and community article | SECONDARY / SNIPPET |
| HSE HSG250 permit to work (books.hse.gov.uk/gempdf/hsg250.pdf); permitpad.co.uk HSG250 guide | SNIPPET |
| openai.com/index/introducing-chatgpt-agent/; incident.io/solution/ai-sre and /investigations; pagerduty.com SRE-agent blog; learn.microsoft.com Security Copilot promptbooks; augury.com/machine-health/ | SNIPPET |
| Augury patent (USPTO 10533920) | DIRECT (patent text) |
