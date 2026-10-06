# OPERON V2: Visual reference study and design validation (Phase 3.1)

Status: research and validation only (historical record). Phase 3 is not redone, and
[`07-product-design-system.md`](07-product-design-system.md) and
[`08-screen-specifications.md`](08-screen-specifications.md) (commit `84b6399`) were **not
edited** by this study. Every proposed change is listed in §19 for review. No frontend, token or
route work was done, and Phase 4 has not started.

> **Post-review note.** The product owner reviewed this study. The accepted decisions are recorded
> in **§22** and are now incorporated into `07` and `08`, which are the governing implementation
> baseline. §1–§21 below are kept unchanged as the original research record, including its access
> limits.

**Evidence labels:**

| Label | Meaning |
|---|---|
| **DIRECT** | Read first-hand: a local clone of a public design-system documentation repo, an npm token package, or a raw public GitHub doc file |
| **SNIPPET** | A search-engine summary of a page that couldn't be opened |
| **RENDER** | Observed in this phase's own scratch render of Phase 3 tokens and components (not committed) |
| **PRIOR** | General product knowledge, used rarely and labelled |

---

## 1. Objectives

1. Test the Phase 3 visual hypotheses (`07 §1–§12`) against mature products and design systems
   **before** they become frontend code.
2. Extract transferable principles for the 14 study areas (shell, dense pages, queues,
   master-detail, case workspace, evidence, approval, timeline, tables, forms, status, charts,
   data states, mobile).
3. Classify every finding as **KEEP**, **REFINE** or **CHALLENGE**. Explicitly *not* a
   reconsideration of the product model, terminology, navigation or governance (brief §12).
4. Avoid design-by-consensus. A pattern counts as evidence only when it solves the same problem
   OPERON has. Usage frequency is not a reason to adopt it.

---

## 2. Resources studied

### 2.1 Requested resources: access outcome

| Resource | Outcome |
|---|---|
| **Refero** (`refero.design`) | **Blocked** by this session's egress proxy. Search-index summaries were reachable: page titles and captions for a few product screens and the Refero *styles* pages (e.g. the Stripe and Linear style analyses). These give **references, not visual evidence**. |
| **Mobbin** (`mobbin.com`) | **Blocked**. Search-index summaries were reachable for about 30 screen and flow URLs (Linear inbox / issue, incident.io, Turo inspection photos, onboarding checklists, bottom-sheet glossary). Captions only. |
| **Component Gallery** (`component.gallery`) | **Blocked**. Its public source repo (`inbn/component-gallery`) was cloned, but component and design-system data are loaded from an external database at build time, so the per-component listings couldn't be reproduced. Its role was filled by reading the design systems it indexes directly (below). |

The blocked hosts can be allowed in the cloud environment's network settings for a future pass:
add `refero.design`, `mobbin.com`, `component.gallery` under Network access → allowed domains.

### 2.2 Primary sources actually read (DIRECT)

| Source | What was read |
|---|---|
| **Siemens Industrial Experience (iX)** docs (`siemens/ix-docs`) and `@siemens/ix` 5.2.1 theme tokens | Colours, status / alarm guidance, grid, HTML table, forms validation, toasts, cards, badges, charts, empty-state language, time-related messages, AI message, application header and menu, classic light and dark themes |
| **IBM Carbon** docs (`carbon-design-system/carbon-website`) and `@carbon/layout`, `@carbon/themes`, `@carbon/styles`, `@carbon/type` | Data table, status-indicator pattern, notification, loading, empty states, disabled and read-only states, forms, modal, tabs, UI shell, data-visualisation guidelines, Carbon for AI |
| **GitHub Primer** docs (`primer/design`) and `@primer/primitives` 11.10 | Data table, button (inactive vs disabled), state label, segmented control, toggle switch, select, radio group, dialog / side sheet, timeline, empty states, loading, degraded experiences, forms, colour, data visualisation |
| **PatternFly** docs (`patternfly/patternfly-org`) and `@patternfly/patternfly` 6.6 | Status & severity, table, primary-detail, empty state, forms, dark theme |
| **Shopify Polaris** docs (`Shopify/polaris`) and `@shopify/polaris-tokens` 9.4 | Index table, badge tones, empty state, card, colour roles (incl. *magic*) |
| **Atlassian** `@atlaskit/tokens` 20.3 | Radius, type, colour role semantics |
| **Microsoft Fluent** `@fluentui/tokens` | Radius, control, table sizes |
| **GitHub docs** (raw) | Reviewing deployments, protected branches, stale-review dismissal, required reviews, PR reviews |
| **Sentry docs** (raw) | Issue details, breadcrumbs |
| **Grafana docs** (raw) | Thresholds, null / disconnect values, graph styles, annotations, alerting No Data / Error / stale instances, theme palette |

### 2.3 Vendor documentation (SNIPPET)

**Products:**
- Linear (Inbox, Triage, Peek, issue view)
- incident.io (incident page, timeline, actions)
- PagerDuty (incidents, mobile)
- Datadog (incident details, Bits AI investigation)
- Jira (issue detail view)
- GitHub notifications inbox
- Terraform Cloud runs
- AWS Change Manager approvals
- ServiceNow approvals community
- Ramp approvals
- Okta Verify
- MaintainX inspection check
- SafetyCulture
- UpKeep
- Vercel
- Grafana Saga navigation

**Colour commentary:**
- Atlassian lozenge and Rovo colour
- PatternFly AI colour guidance
- shapeof.ai colour pattern
- Fluent Copilot

URLs are in §3 and §21.

### 2.4 Own render (RENDER)

- **What:** the Phase 3 tokens and key components (shell, case header and title block, stage track,
  evidence table, decision surface, context rail, queue rows) in Plex at 1440 px, light and dark.
- **Comparison:** the Phase 3 values were compared with the refined values proposed in §19.
- **Storage:** scratch only (not committed, per the brief's no-decorative-binaries rule).

---

## 3. Reference matrix

Each line compares approaches, not votes. The **Principle** column is what transfers to OPERON.

| Problem | Reference A | Reference B | Reference C | Principle for OPERON |
|---|---|---|---|---|
| **Shell** | Siemens iX application header and menu (DIRECT): lean header; right slot for top-level context (site, time); menu bottom for settings | Carbon UI shell (DIRECT): left rail beyond 5 items; never three navigation tiers; tabs for level 4 | Grafana Saga navigation (SNIPPET, [grafana.com/developers/saga/patterns/navigation](https://grafana.com/developers/saga/patterns/navigation/)): levels 1–3 in the menu, 4 as tabs, 5 as headings | Two-tier IA with in-page sections is correct. The header carries context and status only. |
| **Dense page** | Refero Stripe style analysis (SNIPPET, [styles.refero.design/…48e5de76](https://styles.refero.design/style/48e5de76-05d5-4c4e-a269-c7c245b291ec)): ledger rules, generous section spacing, colour only for action, depth from tint, not shadow | Carbon status indicators (DIRECT): no indicator when no action is needed | Sentry issue-details redesign (SNIPPET, [sentry.io/changelog/new-issue-details-ui-now-available](https://sentry.io/changelog/new-issue-details-ui-now-available/)): actions grouped apart from information | Rules plus space plus tint, with colour rationed. This confirms the Phase 3 thesis. Spacing must carry hierarchy, not more rules (§16). |
| **Queue** | GitHub inbox by *reason*, e.g. `reason:review-requested` (DIRECT-raw, [docs.github.com … inbox-filters](https://docs.github.com/en/subscriptions-and-notifications/reference/inbox-filters)) | Linear Inbox / Triage, personal vs team (SNIPPET, [linear.app/docs/inbox](https://linear.app/docs/inbox), [triage](https://linear.app/docs/triage); Mobbin [ecd4b63c](https://mobbin.com/explore/screens/ecd4b63c-7956-4fa3-9573-bf6d78c4bca4)) | incident.io "you lead / participate vs all" (SNIPPET; Mobbin [e187fff5](https://mobbin.com/screens/e187fff5-d4a3-4765-8170-7502e59ef299)) · ServiceNow list-view reject skips the mandatory comment (SNIPPET, [community thread](https://www.servicenow.com/community/itsm-forum/making-rejection-comments-mandatory-on-approval-record-on/td-p/509910)) | Group by *required response for me* versus others. **Never decide from the list** (the ServiceNow failure is exactly what OPERON forbids). |
| **Master-detail** | PatternFly primary-detail (DIRECT): inline drawer with divider, required selected state, explicit close, one pane on mobile | Linear Peek (SNIPPET, [linear.app/docs/peek](https://linear.app/docs/peek)): ↑ / ↓ moves the preview | Primer side sheets (DIRECT): side sheets are dialogs; *"avoid side sheets that allow interactions with the rest of the page"* | A preview is either **docked** (inline, non-modal) or **modal**. Phase 3's mid-width "overlay without scrim" is neither (§6, CHALLENGE). |
| **Case workspace** | Sentry Issue Details (DIRECT-raw): header with counts and actions, one long column of sections, activity sidebar, scope labels | Datadog incident: tabbed Overview / Timeline / Remediation (SNIPPET, [docs.datadoghq.com … incident_details](https://docs.datadoghq.com/monitors/incident_management/incident_details/)) | Jira / Linear: properties in a right column with "hide when empty" (SNIPPET, [Jira issue view](https://support.atlassian.com/jira-software-cloud/docs/configure-the-issue-detail-view/); Mobbin Linear [4f007bec](https://mobbin.com/explore/screens/4f007bec-a13b-4f86-a102-43b9adcfde53)) | One document with an index (Sentry) beats tabs when users must compare evidence, investigation and plan. Carbon (DIRECT): *"Tabs should not be used if the user needs to compare information in different groups."* Long metadata belongs in the rail, not the header. |
| **Evidence** | Datadog Bits AI hypotheses validated / invalidated / inconclusive, agent trace kept in a separate view (SNIPPET, [docs.datadoghq.com/bits_ai/…](https://docs.datadoghq.com/bits_ai/bits_ai_sre/investigate_issues/)) | Sentry breadcrumbs: absolute or relative time; search, filter and sort in a drawer (DIRECT-raw) | Grafana annotations (DIRECT-raw) | Outcome vocabulary on hypotheses, trace on demand (validates `07 §18.6`). Long evidence goes to a filterable drawer. |
| **Approval** | GitHub deployment review: **"Approve and deploy"** / **"Reject"**; self-review blocking; bypass needs a comment plus "I understand the consequences" (DIRECT-raw, [reviewing deployments](https://docs.github.com/actions/managing-workflow-runs/reviewing-deployments)) | GitHub stale-approval dismissal: an approval records the diff state and is dismissed when it changes (DIRECT-raw, [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)) | Terraform Confirm & Apply / Discard locks the workspace (SNIPPET, [developer.hashicorp.com …/run/manage](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/run/manage)) · AWS Change Manager single-rejection veto (SNIPPET, [docs.aws.amazon.com …](https://docs.aws.amazon.com/systems-manager/latest/userguide/cm-approvals-templates.html)) · Okta number match (SNIPPET) | An exact-snapshot binding plus a verb that names the consequence is mature practice. Okta adds a principle Phase 3 lacks: a **short binding token next to the control** (§19 R-10). |
| **Timeline** | incident.io: curated default (status and severity changes plus pinned items), full log searchable (SNIPPET, [docs.incident.io/post-incident/timeline](https://docs.incident.io/post-incident/timeline)) | Primer Timeline (DIRECT); PagerDuty event-type filters (SNIPPET) | Linear groups consecutive similar events (SNIPPET, [collapsed history](https://linear.app/changelog/2025-04-03-collapsed-issue-history)) | Curated default plus full filterable record, already in `08 §8`. Add date separators, a zone statement and a filter drawer. |
| **Tables** | Carbon data table (DIRECT): rows 24 / 32 / 40 / 48 / 64; sticky header; batch actions | Primer data table (DIRECT): show the sort on load; never two data points in one column; no "–" filler | PatternFly table (DIRECT); Polaris IndexTable (DIRECT): paginate above 50; *row tone* tints whole rows (**don't copy**) · iX HTML grid (DIRECT) | Carbon density plus Primer column discipline plus OPERON styling. No row tinting for status. |
| **Forms** | Primer: avoid disabled buttons and use *inactive* (`aria-disabled`, focusable, explains itself); validate on blur after change or on submit; no live regions for validation (DIRECT) | Carbon disabled vs **read-only** (read-only stays perceivable; a disabled primary needs an inline re-enable message) (DIRECT) | iX forms validation: error / **warning** / info / valid levels (DIRECT) · Primer: segmented control applies immediately, so use a radio group inside submitted forms (DIRECT) | Phase 3 under-specifies disabled, read-only, validation timing and busy states (§11). |
| **Status** | Carbon status-indicator pattern: at least 3 of 4 channels (symbol, shape, colour, text); a combined indicator takes the colour of its most serious member; more than 5–6 indicators overwhelm (DIRECT, [carbondesignsystem.com/patterns/status-indicator-pattern](https://carbondesignsystem.com/patterns/status-indicator-pattern/)) | PatternFly: *"severity icons and status icons are not interchangeable"*; "undefined" is a named severity value (DIRECT, [patternfly.org/patterns/status-and-severity](https://www.patternfly.org/patterns/status-and-severity)) | iX: status colour on icons and indicators, not on text; alarm › critical › warning ladder (DIRECT, [ix.siemens.io/docs/styles/colors](https://ix.siemens.io/docs/styles/colors)) | OPERON's 8-dimension grammar meets or exceeds these. It lacks a **combination rule** and a **glyph budget** (§12). |
| **Charts** | Grafana: thresholds, connect-null and disconnect-values thresholds, No Data and stale alert states (DIRECT-raw) | Datadog: anomaly band as neutral grey, forecasts as bands (SNIPPET) | Carbon data-viz axes and legends (DIRECT); iX charts (DIRECT; its start-at-zero advice is rejected for telemetry) | Staleness must be visible **on the time axis**, gaps need a rule, and predictions are bands first (§13). |
| **Data states** | Primer degraded experiences: never show an empty state for data that exists but can't load; cap outage messages per page (DIRECT) | Grafana "Normal (MissingSeries)" and CloudWatch `notBreaching` treat missing data as normal (DIRECT-raw / SNIPPET): the **anti-reference** | iX time-related messages: state the time zone when the viewer's differs (DIRECT) | "Stale never becomes Normal" is a deliberate OPERON departure and should be written as a principle (§14). |
| **Mobile task** | MaintainX Inspection Check: exactly **Pass / Flag / Fail**; Fail if any check fails, Flag if any flag and no fail; a Fail auto-creates a work order (SNIPPET, [help.getmaintainx.com …](https://help.getmaintainx.com/completed-with-inspection-check-report)) | SafetyCulture: required questions marked; flagged answers reviewed at completion (SNIPPET, [help.safetyculture.com/000009](https://help.safetyculture.com/000009)) | Carbon progress indicator suits 3 or more steps and not logic-branching paths (DIRECT) · Mobbin bottom-sheet guidance: no sheets for primary or complex tasks (SNIPPET, [mobbin.com/glossary/bottom-sheet](https://mobbin.com/glossary/bottom-sheet)) | Strong validation of screen 21. Adopt the roll-up rule into G13. |
| **Mobile approval** | GitHub Mobile deployment review (SNIPPET, [github.blog changelog](https://github.blog/changelog/2021-04-01-reviewing-deployments-on-github-mobile/)) | Ramp mobile approvals (SNIPPET, [support.ramp.com](https://support.ramp.com/ramp-mobile-app)) | PagerDuty mobile swipe, **only for reversible acknowledge** (SNIPPET, [support.pagerduty.com …/mobile-app](https://support.pagerduty.com/main/docs/mobile-app)) | Phone approval exists in mature products. OPERON's stricter render-everything-or-hand-off rule is justified because approval dispatches physical work. No swipe for consequential acts. |

---

## 4. Shell findings

| Finding | Evidence | Verdict |
|---|---|---|
| Lean header carrying context (plant, time, status) and account; navigation in a left rail | iX application header (DIRECT); Carbon UI shell (DIRECT) | **KEEP** (`08 §3`) |
| Two navigation tiers; in-page sections, not a third tier | Carbon ("never three tiers"); Grafana Saga levels | **KEEP** (rail plus case section index) |
| iX keeps the menu bottom for settings and about, not navigation to an admin area | iX (DIRECT) | **REFINE (minor):** System at the rail foot is a documented, justified deviation. Keep it, separated by a rule. |
| A single system-status indicator in the header (stream, analysis, demo) | No direct equivalent; iX puts top-level context in the header's right slot | **KEEP** |
| Uppercase group eyebrows in the rail plus uppercase title-block labels plus uppercase section labels compound into a "form" texture | RENDER (Phase 3 specimen) | **REFINE:** uppercase budget (§16) |

---

## 5. Queue findings (My actions)

| Finding | Evidence | Verdict |
|---|---|---|
| Group by the *reason it needs me* (review requested, approval) versus everyone else | GitHub inbox reasons; Linear personal vs team; incident.io | **KEEP** "Requires you (role)" / "Waiting on other roles" |
| Leaving out snooze, read state and "Done" is correct without per-user storage (G7, G8) | Linear and GitHub rely on per-user state | **KEEP** |
| No approve or reject from the list | ServiceNow list-view rejection bypasses the mandatory comment (cautionary) | **KEEP**, now evidenced |
| The group header should name the reason ("Requires you · Maintenance approver: approvals and dispatch failures") | GitHub reason filters | **REFINE** |
| Other-role items carry no verb buttons (read-only rows, so they don't look actionable) | Linear team vs personal | **REFINE** |
| `J` / `K` as aliases of `↑` / `↓` | Linear, Gmail convention (SNIPPET) | **REFINE (small)** |

---

## 6. Master-detail findings

| Finding | Evidence | Verdict |
|---|---|---|
| Docked preview at ≥ 1440 with the selected row kept and an explicit close | PatternFly primary-detail; Linear Peek | **KEEP**, plus an explicit close control |
| **1024–1439: "overlays the right of the sheet; queue visible; no scrim"** | Primer: a side sheet is a dialog, so avoid side sheets that allow interaction with the rest of the page. PatternFly: primary-detail is an *inline* drawer. | **CHALLENGE.** It is neither docked (non-modal, inline) nor modal. Keyboard and focus behaviour and occlusion of the selected row are undefined. **Recommended:** dock down to **1280** with a **380 px** preview (the queue keeps ≥ 900 px); below 1280 use a **modal drawer** (scrim, focus trap, `Esc` returns to the row). Fallback: specify it formally as a non-modal peek (`role="complementary"`, no focus trap, never covering the selected row). |
| Long lists inside a preview open a "view all" drawer | Sentry (DIRECT-raw) | **REFINE:** evidence over 10 rows and the full record open in the inspector drawer |

---

## 7. Case workspace findings

| Finding | Evidence | Verdict |
|---|---|---|
| One scrolling document with a section index, not tabs | Sentry single column; Carbon tabs rule; PatternFly jump links | **KEEP**, now evidenced |
| Timeline as its own tab (Datadog, PagerDuty, incident.io) | SNIPPET | Not adopted. Keep the Record **curated inline** (about 10 authoritative entries) and open the full record in the inspector drawer (Sentry-style). **REFINE** |
| Title block with 8–9 cells | RENDER: 8 cells read as a table header and duplicate the rail's identifiers. Mature tools keep headers short and move long metadata into a right column (Jira, Linear, Sentry sidebar; iX header "only … a status or a counter"). | **REFINE:** at most 6 cells at 1440 (Asset condition, Severity, Stage, Waiting on, Deadline, Revision). Case reference, analysis run and incident UUID move to the context rail's *Identifiers*. Drop cells that don't apply rather than showing "—". |
| Next-step block framed in the context rail | RENDER: the frame competed with the decision surface, so two framed objects were in view | **REFINE:** next-step block rendered as **tint plus 2 px ink left rule** (not a frame). Limit to one framed object per viewport region. |
| Two ink-primary buttons visible at once (header "Go to decision" plus decision surface "Approve and dispatch") | Primer: one primary per page (DIRECT). RENDER confirmed the competition. | **REFINE (must-fix):** the header CTA is secondary whenever the decision surface is on screen, and becomes primary only when it isn't |
| The stage track could be mistaken for a step-by-step wizard | Carbon progress indicator is for linear tasks (DIRECT) | **REFINE:** state in the spec that the track is a lifecycle position display, never a stepper, and not clickable to advance |
| Hold-point bar | RENDER: legible and distinctive at 2 × 18 px | **KEEP** |

---

## 8. Evidence findings

| Finding | Evidence | Verdict |
|---|---|---|
| Hypotheses with validated / invalidated / inconclusive outcomes; trace on demand | Datadog Bits AI (SNIPPET) | **KEEP** (`07 §18.6`) |
| Evidence as table rows with source and time, not cards | Sentry, Grafana, Primer table discipline | **KEEP** |
| Mono identifiers wrap inside narrow columns (`model.gbm v3` broke onto two lines) | RENDER | **REFINE:** identifier cells `nowrap` with middle truncation (`a046ef…39ab`) and full value on hover / copy |
| Time shown absolute, with optional relative-to-detection ("+00:11") | Sentry breadcrumbs (DIRECT-raw) | **REFINE (optional)** for evidence and record |
| An empty cell rendered as "—" | Primer: no "–" filler (DIRECT) | **REFINE:** use words ("Not projected", "No observation") |

---

## 9. Approval findings

| Finding | Evidence | Verdict |
|---|---|---|
| In-page decision surface, not a modal | Carbon: no modal when information outside it must be consulted; Primer: never a page in a dialog (DIRECT) | **KEEP** |
| "Approve and dispatch" wording | GitHub "Approve and deploy" (DIRECT-raw) | **KEEP**, with direct precedent |
| Any change voids the approval | GitHub stale-approval dismissal (DIRECT-raw) | **KEEP**. **Add** a visible "changed since you opened this (R33 → R34): what changed" state before submission (REFINE). |
| Short binding token adjacent to the controls | Okta number match (SNIPPET) | **REFINE:** a "a046ef · R33" token directly above the buttons, desktop and phone |
| Reject styled as danger red | Carbon: danger means destructive. In OPERON the *irreversible* act is Approve, but Reject is today an unrecoverable stop (G2). Red there also reuses the critical status hue. | **REFINE:** keep danger emphasis while Reject ends in an unresolvable escalation, but through an **`action.danger` token** (aliasing red) so the status token isn't reused (`07 §3` one-meaning rule). Re-evaluate when G4 / G2 exist. |
| Violet 2 px rule framing the decision surface | Polaris: don't style a whole container in the AI "magic" colour (DIRECT). The surface contains model-generated recommendations. | **CHALLENGE**, folded into the violet decision (§16.1) |
| Disabled Approve (acknowledgement not checked, disconnected) | Primer *inactive* button; Carbon disabled-primary guidance (DIRECT) | **REFINE (must-fix):** Approve stays focusable (`aria-disabled`); activating it moves focus to the blocker (checkbox, connection banner) with the reason linked |

---

## 10. Timeline findings

| Finding | Evidence | Verdict |
|---|---|---|
| Engineering record styling: square nodes, typed events, no avatars or bubbles | Primer Timeline; incident.io; GitHub PR timeline (PRIOR) | **KEEP** |
| Curated default plus full log | incident.io (SNIPPET) | **KEEP** (`08 §8`) |
| Date separators when events span days; time zone stated once at the top | iX time messages (DIRECT) | **REFINE** |
| Event-type filters in the full-record drawer | PagerDuty (SNIPPET) | **REFINE** |
| Dashed advisory nodes need a text equivalent | Carbon 3-of-4 channels (DIRECT) | **REFINE:** the word "Advisory" in the row's accessible name and on hover |

---

## 11. Tables and forms findings

### 11.1 Hard numbers (DIRECT, token packages)

| System | Radius scale | Control heights | Table rows | Body |
|---|---|---|---|---|
| **OPERON (Phase 3)** | **0 / 2 / 4** | 28 / 32 / 40 / 48 | 32 / 40 / ≥ 56 | 14 / 20; table 13 / 18 |
| Siemens iX 5.2.1 | 0 / 2 (controls) / 4 (cards, menus, toasts) | 24 / 32 / 40 | ≈ 37 | 14 / 20 |
| Carbon v11 | 0 / 2 / 4 / 8 …; v12 flag moves inputs and tags to 4 (no pills) | 24 / 32 / 40 / 48 | 24 / 32 / 40 / 48 / 64 | 14 / 18–20 |
| Primer 11.10 | 3 / 6 / 12 | 24 / 28 / 32 / 40 / 48 (44 coarse minimum) | condensed / normal / spacious | 14 / 1.5 |
| PatternFly 6.6 | 4 / 6 / 16 / 24 / pill | ≈ 37 | ≈ 37 compact / ≈ 53 | 14 / 1.5 |
| Polaris 9.4 | 2 … 30 | — | — | **13 / 20** |
| Fluent 2 | 0 / 2 / 4 … (controls 4) | 24 / 32 / 40 | 24 / 34 / 44 | 14 / 20 |

**Conclusions:**
- OPERON's numbers sit inside mature practice. Its radius and density are **identical to Siemens
  iX**, the closest industrial reference.
- OPERON's 13 px compact table text is below most systems' 14 px but matches Polaris. Keep it,
  with Comfortable (14 px) as a user preference.

### 11.2 Table principles adopted

**Carbon density plus Primer column discipline plus OPERON styling:**
- show the active sort on load, including the default multi-key sort ("Sorted by attention, then
  deadline");
- one data point per column (the Case column's interim reference and asset name need a declared
  sort key: the asset tag);
- no "–" filler;
- sticky header;
- no row tinting for status (Polaris row *tone* rejected);
- paginate or virtualise above about 50–200 rows.

### 11.3 Forms gaps in Phase 3 (REFINE)

1. **Inactive vs disabled:** consequential buttons blocked by state are *inactive*
   (`aria-disabled`, focusable, reason linked); plain `disabled` only for irrelevant controls.
2. **Read-only** state added to the state set (readable, copyable, not editable): bound
   identifiers, past decisions.
3. **Validation timing:** on blur after the user changes a field, and on submit; never on each
   keystroke; no live-region announcements for field errors.
4. **Validation levels:** error and **warning** (iX). A warning lets the user continue (e.g.
   "rationale is short").
5. **Busy state:** a submitting button shows its label plus progress text, stays `aria-busy` and is
   never set `disabled`.
6. **Pass / Flag / Fail** is a **radio group** semantically (styled as a segmented control), because
   it sits inside a submitted form (Primer).
7. **Toasts** pause on hover / focus and are announced politely.

---

## 12. Status-system findings

| Finding | Evidence | Verdict |
|---|---|---|
| Multi-channel status (glyph plus shape plus text, colour supplementary) | Carbon 3-of-4 rule; iX; PatternFly | **KEEP**: OPERON exceeds the rule |
| Condition separated from severity | PatternFly "not interchangeable" | **KEEP** |
| "In progress" neutral, not coloured | Most systems colour it blue; OPERON's neutral choice is supported by CVD evidence (`07 §4.3`) and iX's ISA-style rationing | **KEEP** |
| Green only for verified | Primer uses green for open or success; OPERON's narrower meaning is stricter and consistent | **KEEP** |
| No **combination rule** for aggregates (plant band group, line roll-up, collapsed flood group) | Carbon: a group takes the colour and shape of its most serious member, plus a count | **REFINE:** aggregates show worst member plus count ("⬣ 1 · ▲ 2 · 5 normal") |
| Case rows carry about 5 glyphs, at Carbon's 5–6 ceiling | Carbon (DIRECT) | **REFINE:** inside groups that already have an attention header, drop the per-row attention glyph. Show the stage as a word plus n/8 (no node glyph) in rows. |
| Small status shapes are indistinguishable at 10–12 px: the critical octagon reads as a dot | RENDER (both themes) | **REFINE (must-fix):** status shapes in cells ≥ 14 px (octagon, triangle, diamond, person-square); 10–12 px marks are reserved for provenance only, which never carries severity. Plant-band cells use 16 px. |
| "Unknown" as a first-class value | PatternFly "undefined" severity | **KEEP** (OPERON already has it) |

---

## 13. Visualisation findings

| Finding | Evidence | Verdict |
|---|---|---|
| Neutral series, labelled dashed thresholds, table alternative, no gauges or gradients | Grafana, Carbon, Primer data-viz (DIRECT) | **KEEP**: stricter than all references |
| **A "last 90 samples" window hides staleness**: a stale chart looks identical to a live one | Grafana stale and no-data handling (DIRECT-raw) | **REFINE (must-fix):** the time axis ends at *server now*; after the last sample a labelled region "No data since 14:18" is drawn. Sparklines likewise. |
| **No gap rule** | Grafana disconnect-values threshold (DIRECT-raw); Carbon labelled gaps | **REFINE (must-fix):** break the line when consecutive samples are more than 2 × the expected interval apart. Label the gap with start and end. Distinguish *sensor gap* from *connection lost*. |
| Sample quality not drawn | Ignition break-line (SNIPPET) | **REFINE:** suspect samples as hollow markers excluded from the line |
| No chart-level states | iX problem → cause → remedy messages (DIRECT) | **REFINE:** loading / empty / error / partial states for every chart container |
| Too many dash patterns (threshold, prediction, model-generated provenance, baseline) | RENDER and Datadog bands (SNIPPET) | **REFINE:** thresholds dashed; baseline dotted; predictions as **bands** (no dashed line); provenance shown in tooltip and legend, not as a line style on telemetry |
| Event labels inside the plot collide | Grafana annotation lane (DIRECT-raw) | **REFINE:** event glyphs in a lane under the x-axis, labels in the tooltip |
| Y-axis | Carbon: telemetry may start above zero (DIRECT); iX start-at-zero advice is not suitable for telemetry | **REFINE:** a minimum visible span per channel so noise doesn't look like a trend. Thresholds in view are always included in the domain. |
| Small multiples | Grafana shared crosshair (PRIOR / SNIPPET) | **REFINE:** synchronised crosshair across the five channels |
| Thresholds only from backend values with source | Grafana's default "green base, red at 80" is the anti-pattern (DIRECT-raw) | **KEEP and state explicitly**: never draw a default threshold |

---

## 14. Empty / error / stale findings

| Finding | Evidence | Verdict |
|---|---|---|
| "Clear" empty states must cite evidence, and none are shown while stale | Primer degraded experiences: never an empty state for data that can't load (DIRECT) | **KEEP** |
| **§15 defines Live as < 10 s and Stale as > 3 × expected interval.** These overlap or leave an undefined zone depending on the interval. The asset "threshold" is unnumbered. | Spec defect (found by this study) | **REFINE (must-fix):** one per-source freshness table: **Live** (≤ 2 × expected interval) · **Delayed** (2–5 ×, value shown with age) · **Stale** (> 5 ×, condition becomes Stale) · **Disconnected** (stream closed). Ages computed from server time. Phase 4 takes the expected interval from the engine tick cadence. |
| Message hierarchy on disconnect (Phase 3 put a stale glyph on every value) | Primer caps outage messages per page (DIRECT) | **REFINE:** banner for the cause, "as of" in each title block, value glyphs only where a value's freshness differs from its region |
| Mixed staleness on Overview | — | **REFINE:** "7 of 8 assets current · CNC-MILL-07 stale since 14:18" |
| "Stale never becomes Normal" as an explicit principle | Departs from Grafana `Normal (MissingSeries)` and CloudWatch `notBreaching` | **KEEP and state it** |
| Empty-state wording | iX: no "yet" in headings; PatternFly: say what is needed ("Access permissions needed", not "Access denied"); grey icons; Primer: error codes in secondary text (DIRECT) | **REFINE** copy in `08 §6` (e.g. "No cases yet" → heading "No open cases", body "A case opens when…") |
| Skeleton timing | Primer: no indicator under 1 s; Carbon loading (DIRECT) | **REFINE:** skeleton after about 300–750 ms, then elapsed time ("Waiting for plant data · 12 s"). Replaces `07 §11`'s 2 s rule. |
| Reconnect backfill | — | **REFINE:** a backfilled gap is marked on charts and noted in the case record |
| "Not configured" missing from `07 §15` (present in `08 §6`) | Internal consistency | **REFINE** |
| Polite vs assertive announcements | — | **REFINE:** Live → Stale polite; Disconnected assertive; once each |

---

## 15. Mobile findings

| Finding | Evidence | Verdict |
|---|---|---|
| Pass / Flag / Fail inspection | MaintainX uses exactly this vocabulary (SNIPPET) | **KEEP**, strongly validated |
| Roll-up rule | MaintainX: Fail if any fail; Flag if any flag and no fail | **REFINE:** add to the proposed G13 definition (backend gap) |
| Review step | SafetyCulture: flagged items reviewed at completion | **REFINE:** list Flag and Fail answers first on "Review & submit" |
| A result that can't be recorded yet (G13) | — | **REFINE:** offer "Copy result" (plain text) so the technician can hand it on. No silent loss. |
| Step-based flow with progress | Carbon progress indicator: ≥ 3 steps, not for logic-branching paths (DIRECT) | **KEEP** (4 fixed steps) |
| No bottom sheets for the inspection or decision | Mobbin glossary (SNIPPET) | **KEEP** (full screens) |
| Phone approval exists in mature products (GitHub Mobile, Ramp); swipe only for reversible acts (PagerDuty) | SNIPPET | **KEEP** OPERON's stricter rule (approval dispatches physical work) |
| Binding token above the controls on phone | Okta number match | **REFINE** (same as §9) |

---

## 16. Visual and aesthetic findings (the specific challenges)

### 16.1 Violet for "a person must act"

**Evidence:**
- **No mature system found uses violet for human-required action.**
- Competing meanings in 2024–26 systems (DIRECT unless marked):

  | Meaning | Source |
  |---|---|
  | **AI / automation** | Polaris *magic* `#8051FF`, documented as "artificial intelligence or any other type of automation"; Atlassian Rovo (SNIPPET) |
  | **Done / merged** | Primer `done` `#8250df` |
  | **Undefined status** | Carbon |
  | **Non-status** | PatternFly |
  | **Suppressed alarm** | Vendor ISA-101 tables (SNIPPET) |

- AI is not universally purple: Carbon's AI colour is **blue** (`#4589ff`), and PatternFly advises
  giving AI no colour (SNIPPET).
- OPERON's light violet `#6B47CC` sits at OKLCH hue 290, **ΔE 8.8 from Polaris *magic*** (measured).
- Polaris explicitly says not to style whole containers in the magic colour. OPERON's 2 px violet
  rule frames a surface that *contains model-generated recommendations*: the strongest possible
  "AI suggestion box" reading.

**RENDER:**
- At glyph-and-word scale, violet looks professional and calm; it doesn't read as AI.
- As a container rule on the decision surface, it starts to.
- With an ink rule, the decision surface remained unmistakable (heading, glyph, deadline, Approve).

**Conclusion:** CHALLENGE (partial). The *semantic* separation ("a person must act" as its own
role) is right. The current *expression* (high-chroma violet, container framing) risks the AI
reading. Recommended resolution:

| Option | What it is | Recommendation |
|---|---|---|
| **A** | Keep the hue, lower its chroma and confine it. Light `#674EB0` (6.10:1 on sheet, OKLCH C 0.15, ΔE 12.8 from Polaris magic), dark `#AA95E8` (6.82:1). Used **only** on the person glyph and the short role word ("Approver"). The decision-surface top rule becomes **ink**. Violet is banned adjacent to model output, loading, onboarding and empty states. The existing sparkle / gradient / glow ban stays. | **Recommended** |
| **B** | Neutral ink person glyph plus the rank glyph, no hue. Consistent with OPERON's own "attention is not a colour". Loses a fast scan cue in mixed lists. | **Fallback** |
| *Rejected* | Indigo / blue-violet (hue 268–280): lands on the "default AI indigo", near Carbon's AI blue, and reintroduces the blue / violet CVD collision Phase 3 removed. Magenta (≈ 320): collides with iX's critical and HMI alarm palettes. | Not adopted |

- **Verification gate (Phase 4):** a 5-second recognition test with plant users. If ≥ 20 % read the
  violet glyph as "AI" or "done", switch to B.
- **CVD (measured):** option A keeps ≥ 14.5 ΔE from every other status hue and from secondary
  text under protan and deutan simulation.

### 16.2 Engineering title blocks

**Conclusion: KEEP as a signature, REFINE the size.**
- In RENDER, 6 cells read as a deliberate engineering header and 8–9 cells read as a duplicated
  table header.
- Mature tools keep headers status-sized and put long metadata in a right column.
- Rules:
  - at most 6 cells;
  - no empty cells;
  - identifiers go to the context rail;
  - sentence-case values, with only the cell labels as eyebrows.

  The title block then remains distinctive (vertical hairline cells are rare in SaaS) without being
  literal or gimmicky.

### 16.3 0 / 2 / 4 px radius

**Conclusion: KEEP.**
- The scale is identical to Siemens iX, and Carbon v12 and Fluent controls are converging on 4 px
  with no pills.
- RENDER: 4 px buttons and inputs read crisp, not harsh.
- Harshness came from **uppercase density and rule density**, not radius.
- Keep "no pills" and "max 4".

### 16.4 Ruled surfaces vs cards

**Conclusion: KEEP with a precise exception list (REFINE).**
- Validated by Stripe-style ledgers (SNIPPET), Linear and iX borderless panes, and Primer and
  Carbon guidance.
- Bounded surfaces genuinely help comprehension for:

  | Bounded surface | Treatment |
  |---|---|
  | Objects acted on as a unit (decision surface, technician task) | Already framed |
  | Context rail | Tint plus hairline or left rule, **not** a frame |
  | Pinned open evidence request | Left rule |
  | Identifier / hash wells | Sunken tint |
  | Chart plot areas | Sunken tint |
  | Exception banner | Rule plus glyph |

- At most **one framed object per viewport region**.
- Long scrolls need sticky section headings so region boundaries never get lost.

### 16.5 Information density

**Conclusion: KEEP the numbers; REFINE the texture.**
- 32 / 40 rows and 28 / 32 / 40 / 48 controls equal Carbon and Primer, and the compact table at
  13 px matches Polaris.
- RENDER at Comfortable felt professional, not cramped.
- The risk is **visual noise, not density**: too many rules plus uppercase labels plus glyphs.
  Fix it with the rule budget (§16.6) and the glyph budget (§12), not by hiding information.

### 16.6 Light theme ("Drawing Sheet")

**Conclusion: REFINE (values and rule budget).**
- **Measured:** the shell-to-sheet step is **1.056**, lower than Carbon g10 (1.10), iX classic-light
  (1.10) and Primer (1.065). It merges on tablets and projectors.
- "Warm Paper" is effectively neutral: chroma 0.004, so hue barely registers.

**Refinements:**

| Change | Detail |
|---|---|
| Light `surface.base` | `#F1F0EC` (step **1.09**, warmer, OKLCH C 0.0054). Measured: ink 16.31:1, tertiary 5.13:1, control border 3.38:1 (still ≥ 3:1). Cap warmth at about C 0.006; beyond that it drifts toward the "archival case file" Phase 2.5 rejected. |
| Rule budget | No vertical rules outside title blocks. Tables use **either** the sunken header band **or** a header rule, not both. Hierarchy comes from spacing and type before adding rules. |
| Uppercase budget | Eyebrows only in title-block cell labels and the rail group labels. Decision-surface keys, rail headings and section metadata become sentence-case 12 px weight 500. RENDER: this removed the "government form" texture. |
| Brand Paper `#F3F4F1` | Remains the **brand** colour (`03`). Only the product's light shell surface moves. Product-owner confirmation needed (it changes Phase 3 decision R3's "uses the brand Paper exactly"). |

### 16.7 Dark theme ("Instrument")

**Conclusion: KEEP the direction; REFINE the values.**

**Measured:**

| | OPERON | Grafana | Carbon g100 | iX classic-dark |
|---|---|---|---|---|
| Base → sheet step | **1.06** (lowest of every system compared) | 1.08 | 1.20 | 1.33 |
| Primary text | **14.7:1** | about 10.9:1 | — | — |

The surfaces are numerically close to Grafana's, so the look must come from OPERON's structure
(title blocks, stage track, ink controls), not the surfaces.

**Refinements:**

| Token | Change | Measured contrast |
|---|---|---|
| Dark `surface.sheet` | `#1A1F21` (step **1.12**) | Tertiary 4.93:1, critical 4.86:1, control border 3.40:1 |
| `text.primary` | `#DDE2E4` (13.4:1 on the old sheet, 12.7:1 on the new) | Supports the "low glare" goal |
| Hover and selected | Re-derive from the new sheet, keeping tertiary text ≥ 4.5:1 on selected rows or using secondary text there (as Phase 3 already requires) | — |

**RENDER:** the refined dark theme is softer and more clearly layered. It never approached
terminal, neon or cyberpunk: no black, no saturated accents, no glow.

---

## 17. Phase 3 hypotheses validated

| Hypothesis | Validated by |
|---|---|
| Instrument & Record, Ink / Paper / Graphite, no brand hue | Rationed colour in Stripe-style ledgers, iX, Carbon status guidance; RENDER |
| IBM Plex Sans + Mono; mono identifiers | iX / Carbon parity (14 / 20); RENDER legibility |
| Ruled sections over card soup | Linear / iX borderless panes, Stripe ledger, Polaris / Carbon card guidance |
| One principal working sheet | Sentry single column; RENDER |
| 0 / 2 / 4 px radii, no pills | iX identical; Carbon v12; Fluent |
| Shadows only for overlays | Stripe / Refero "depth from tint, not shadow" (SNIPPET); Carbon |
| Restrained semantic colour; neutral in-progress; green verified-only | Carbon 3-of-4 channels; iX status on icons, not text; CVD measurements |
| Separate status dimensions (condition ≠ severity ≠ stage) | PatternFly "not interchangeable" |
| Title blocks (reduced to ≤ 6 cells) | RENDER; status-sized headers in mature tools |
| Nameplate identifiers | RENDER; Sentry / GitHub mono IDs |
| Stage track with hold point | RENDER (legible, distinctive); stepper caveat added |
| Compact provenance marks | No reference has an equivalent; RENDER legible as marks (never as severity) |
| Instrument-style readouts | Carbon / iX tabular figures |
| One in-page decision surface; "Approve and dispatch"; exact binding; no approval from lists | GitHub deployments and stale reviews; Terraform; AWS; ServiceNow cautionary case; Carbon / Primer modal rules |
| One document plus section index for the case | Sentry; Carbon tabs rule |
| Queue grouped by required response | GitHub reasons; Linear |
| Task-shaped mobile inspection Pass / Flag / Fail | MaintainX; SafetyCulture |
| Stale ≠ Normal; clear empty states cite evidence | Primer degraded experiences (and contrast with Grafana / CloudWatch defaults) |
| No categorical palette; neutral telemetry; table alternatives | Carbon / Primer data-viz; Grafana defaults as anti-pattern |

---

## 18. Phase 3 hypotheses challenged

Only two items meet the brief's CHALLENGE bar: strong evidence that a Phase 3 decision should be
reconsidered before Phase 4. Neither reopens the product model, terminology or navigation.

| # | Phase 3 decision | Evidence | Proposed resolution | Needs product owner? |
|---|---|---|---|---|
| **CH-1** | Violet `status.decision` at current chroma, including the violet top rule framing the decision surface (`07 §4.3`, `08` screen 8) | No system uses violet for human action; Polaris *magic* (AI) is ΔE 8.8 away, and Polaris forbids framing containers in it; the decision surface contains model output | **Option A** (§16.1): lower chroma, glyph-plus-word only, ink decision rule, adjacency ban, recognition test with option B as fallback | **Yes** |
| **CH-2** | Preview at 1024–1439 "overlays the sheet, queue visible, no scrim" (`08 §4`) | Primer: overlay side sheets are dialogs; PatternFly primary-detail is inline. The behaviour is undefined for focus and occlusion. | Dock at ≥ 1280 (380 px); modal drawer below 1280 | **Yes** (affects laptop users' workflow) |

No usability contradiction was found in the product model, Case terminology, navigation
architecture, governed approval, evidence-first investigation, or the work-vs-verification
separation.

---

## 19. Recommended refinements before implementation

To be applied to `07` and `08` after review. Not applied here.

**Must-fix before Phase 4** (spec defects or accessibility):

| ID | Refinement | Target |
|---|---|---|
| R-1 | Freshness table: Live ≤ 2× interval · Delayed 2–5× · Stale > 5× · Disconnected; ages from server time; expected interval from the engine tick cadence; remove the "< 10 s" rule | `07 §15`, `08` screen 23 |
| R-2 | Charts: time axis ends at server *now*, with a "No data since …" region; gap rule (> 2× interval breaks the line, labelled start–end, sensor vs connection gap); sparklines show staleness | `07 §16` |
| R-3 | Inactive (`aria-disabled`, focusable, reason linked, focus moves to the blocker) replaces `disabled` for Approve, Submit inspection and decision controls while disconnected | `07 §17`, `§18.1`; `08` screens 8, 21, 22 |
| R-4 | Status shapes ≥ 14 px in cells (16 px in the plant band); 10–12 px reserved for provenance marks | `07 §10`, `§12` |
| R-5 | One primary per view: the case-header CTA is secondary while the decision surface is visible | `08` case template, screen 8 |

**Refine** (direction kept, guidance changes):

| ID | Refinement | Target |
|---|---|---|
| R-6 | Title block ≤ 6 cells; no empty cells; case reference, analysis run and UUID move to the context rail Identifiers | `07 §9.4`, `08` case template |
| R-7 | Uppercase budget: eyebrows only in title-block labels and rail group labels; everything else sentence case | `07 §6.2` |
| R-8 | Rule budget: no vertical rules outside title blocks; header band *or* header rule; hierarchy via space and type first | `07 §9`, `§5.2` |
| R-9 | Light `surface.base` → `#F1F0EC` (brand Paper unchanged); re-verify all light pairs (done here: ink 16.31, tertiary 5.13, control 3.38) | `07 §4.2` |
| R-10 | Short binding token ("a046ef · R33") directly above the decision controls, desktop and phone; a "changed since you opened this (R33 → R34)" state before submit | `08` screens 8, 22 |
| R-11 | Next-step block and context rail: tint plus 2 px ink left rule, not a frame; one framed object per viewport region; exception list from §16.4 | `07 §9.3` |
| R-12 | Record: curated inline (about 10 authoritative entries); full record in the inspector drawer with event-type filters; date separators; time zone stated once; "Advisory" in accessible names | `08 §8` |
| R-13 | Evidence over 10 rows → "View all" in the inspector drawer; identifier cells `nowrap` with middle truncation | `08` case template, `07 §18.6` |
| R-14 | Status combination rule (worst member plus count) for every aggregate; drop the per-row attention glyph inside attention-grouped lists; stage as word plus n/8 in rows | `07 §12` |
| R-15 | Words instead of "—" for unknown values ("Not projected", "No observation") | `07 §12.4`, `08` |
| R-16 | Forms: read-only state; validation on blur-after-change and on submit; warning level; busy state never `disabled`; Pass / Flag / Fail as a radio group; toasts pause on hover / focus | `07 §18.1`, `§18.3` |
| R-17 | Charts: predictions as bands (no dashed forecast line); event lane under the axis; suspect samples as hollow markers; chart loading / empty / error / partial states; minimum visible y-span; synchronised crosshair in small multiples | `07 §16` |
| R-18 | Data-state message hierarchy (banner → "as of" per title block → value glyphs only where freshness differs); mixed-staleness wording; backfill marking; "Not configured" added to `07 §15`; announcements polite for stale, assertive for disconnect | `07 §15` |
| R-19 | Skeleton after about 300–750 ms then elapsed time, replacing the 2 s rule | `07 §11`, `§15` |
| R-20 | Empty-state copy: no "yet" in headings; say what is needed; error codes in secondary text | `08 §6` |
| R-21 | Queue: group headers name the reason; other-role rows have no verbs; `J` / `K` aliases | `08` screen 3, `§4` |
| R-22 | Stage track declared a lifecycle position display (not a stepper, not clickable) | `07 §13.2` |
| R-23 | Inspection: MaintainX-style roll-up rule added to the G13 definition; Flag / Fail listed first on review; "Copy result" when the result can't be recorded | `08 §1.2`, screen 21 |
| R-24 | `action.danger` token (alias of red) for Reject and destructive admin, so the status token isn't reused; revisit Reject's danger emphasis when G4 / G2 exist | `07 §3`, `§18.1` |
| R-25 | Dark `surface.sheet` → `#1A1F21`; `text.primary` → `#DDE2E4`; re-derive hover and selected (measured: tertiary 4.93, critical 4.86, control 3.40) | `07 §4.2` |

**Challenge resolutions** (after product-owner decision): CH-1 → violet option A (or B); CH-2 →
dock ≥ 1280 / modal below.

---

## 20. Phase 3 decisions that should remain unchanged

**Product model and IA:**
- Case terminology (backend `incident`).
- Navigation hierarchy and groups.
- System at the rail foot.
- No global search.

**Theme and colour:**
- Instrument & Record.
- Ink / Paper / Graphite with no brand hue.
- OS-driven theme default.
- Four status hues with one meaning each; blue removed; in-work neutral; green only for verified.
- Attention, severity and provenance neutral (not colour).
- No categorical chart palette.

**Typography and form:**
- IBM Plex Sans + Mono from IBM's official files; type scale and minimums; mono for identifiers.
- 0 / 2 / 4 px radius, no pills.
- Shadows only for overlays.
- Ruled sections; the five framed-object types (with R-11 refinements).
- Density modes Compact / Comfortable / Touch and their numbers.

**Status and lifecycle:**
- The eight-dimension status grammar and slots.
- Stage names and the stage track with its hold point.
- The provenance pattern (dashed = advisory, solid = authoritative, hatched = simulated).
- Model scores never labelled as probability.

**Case workspace and approval:**
- Queue → preview → workspace, and the docked preview at ≥ 1440.
- One scrolling case document with a section index; section order.
- The single in-page decision surface; "Approve and dispatch"; "Reject and escalate" with a
  required reason; Request changes not rendered until G4.
- No decisions from lists or notifications.
- Approval expiry states (`08 §7`).
- Work vs verification vocabularies; "field completion not reported (G10)".

**Mobile and data states:**
- Task-shaped mobile: the technician inspection flow, Pass / Flag / Fail, phone approval with
  hand-off, no swipe or bottom-sheet decisions.
- Stale ≠ Normal; clear empty states that cite evidence.

**Process:**
- Phase 4 slice order (`08 §9`). R-1 to R-5 fold into slices 1–4 without reordering.
- All G1–G14 and X1–X7 definitions.

---

## 21. Source index (for audit)

**DIRECT: local clones (public repos, read-only, shallow sparse) and packages:**
- `siemens/ix-docs@47de577` docs (components / styles / guidelines) → https://ix.siemens.io/docs/… ;
  `@siemens/ix` 5.2.1 `scss/theme/classic/{light,dark}`
- `carbon-design-system/carbon-website@5e9cd1d` `src/pages/…`:
  - [data table](https://carbondesignsystem.com/components/data-table/usage/)
  - [status indicators](https://carbondesignsystem.com/patterns/status-indicator-pattern/)
  - [disabled states](https://carbondesignsystem.com/patterns/disabled-states/)
  - tabs, UI shell, loading, notification, data visualisation, Carbon for AI

  Packages: `@carbon/layout`, `@carbon/themes` 11.82.0, `@carbon/styles`, `@carbon/type`.
- `primer/design@87f799f` `content/…`:
  - [data table](https://primer.style/product/components/data-table/)
  - [button](https://primer.style/product/components/button)
  - [forms](https://primer.style/product/ui-patterns/forms/overview)
  - dialog / side sheet, timeline, degraded experiences, data visualisation

  Package: `@primer/primitives` 11.10.0.
- `patternfly/patternfly-org@2452272`:
  - [status and severity](https://www.patternfly.org/patterns/status-and-severity)
  - [table](https://www.patternfly.org/components/table/design-guidelines)
  - [empty state](https://www.patternfly.org/components/empty-state/design-guidelines)
  - [form](https://www.patternfly.org/components/forms/form/design-guidelines)
  - primary-detail

  Package: `@patternfly/patternfly` 6.6.1.
- `Shopify/polaris@3f7954a`:
  - [index table](https://polaris.shopify.com/components/tables/index-table)
  - colour roles (*magic*: `polaris.shopify.com/content/design/colors/palettes-and-roles.mdx`)

  Package: `@shopify/polaris-tokens` 9.4.2.
- `@atlaskit/tokens` 20.3.0; `@fluentui/tokens`.
- Raw GitHub docs:
  - [reviewing deployments](https://docs.github.com/actions/managing-workflow-runs/reviewing-deployments)
  - [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
  - [inbox filters](https://docs.github.com/en/subscriptions-and-notifications/reference/inbox-filters)
  - PR review docs
- Raw Sentry docs: [issue details](https://docs.sentry.io/product/issues/issue-details/),
  breadcrumbs.
- Raw Grafana docs (`grafana/grafana` `docs/sources/…`): thresholds, connect-null / disconnect
  values, graph styles, annotations, alerting No Data / Error / stale instances.

**SNIPPET** (search summaries; pages blocked):

*Mobbin:*
- Linear issue [4f007bec](https://mobbin.com/explore/screens/4f007bec-a13b-4f86-a102-43b9adcfde53)
- Linear inbox [ecd4b63c](https://mobbin.com/explore/screens/ecd4b63c-7956-4fa3-9573-bf6d78c4bca4)
- [db497da7](https://mobbin.com/explore/screens/db497da7-0b3c-4f6b-bf78-f355b2147dec)
- incident.io [e187fff5](https://mobbin.com/screens/e187fff5-d4a3-4765-8170-7502e59ef299)
- [bottom-sheet glossary](https://mobbin.com/glossary/bottom-sheet)

*Refero:*
- [Vercel dashboard](https://refero.design/pages/961ad1cd-9ab6-4506-a557-44800f2f15ba)
- [Stripe style](https://styles.refero.design/style/48e5de76-05d5-4c4e-a269-c7c245b291ec)
- [Linear style](https://styles.refero.design/style/90ce5883-bb24-4466-93f7-801cd617b0d1)

*Vendor documentation:*
- Linear: [inbox](https://linear.app/docs/inbox), [triage](https://linear.app/docs/triage),
  [peek](https://linear.app/docs/peek)
- [incident.io timeline](https://docs.incident.io/post-incident/timeline)
- [PagerDuty incidents](https://support.pagerduty.com/main/docs/incidents) and
  [mobile](https://support.pagerduty.com/main/docs/mobile-app)
- Datadog: [incident details](https://docs.datadoghq.com/monitors/incident_management/incident_details/),
  [Bits AI investigate](https://docs.datadoghq.com/bits_ai/bits_ai_sre/investigate_issues/)
- [Jira issue view](https://support.atlassian.com/jira-software-cloud/docs/configure-the-issue-detail-view/)
- [Terraform runs](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/run/manage)
- [AWS Change Manager approvals](https://docs.aws.amazon.com/systems-manager/latest/userguide/cm-approvals-templates.html)
- [ServiceNow rejection comments](https://www.servicenow.com/community/itsm-forum/making-rejection-comments-mandatory-on-approval-record-on/td-p/509910)
- [Ramp mobile](https://support.ramp.com/ramp-mobile-app)
- [Okta Verify](https://help.okta.com/oie/en-us/content/topics/identity-engine/authenticators/configure-okta-verify-options.htm)
- [MaintainX inspection check](https://help.getmaintainx.com/completed-with-inspection-check-report)
- [SafetyCulture](https://help.safetyculture.com/000009)
- [Sentry issue-details changelog](https://sentry.io/changelog/new-issue-details-ui-now-available/)
- [Grafana Saga navigation](https://grafana.com/developers/saga/patterns/navigation/)
- [GitHub Mobile deployments](https://github.blog/changelog/2021-04-01-reviewing-deployments-on-github-mobile/)

*Colour commentary:* atlassian.design lozenge / Rovo colour; PatternFly AI colour; shapeof.ai;
Fluent Copilot.

**RENDER:** scratch specimen of the Phase 3 tokens and the §19 refinements at 1440 px, light and
dark (not committed).

---

## 22. Product-owner resolution (post-review addendum)

Added after review. This section does **not** alter the research above; it records what was
decided and where it now lives.

**Accepted and incorporated into `07` / `08`:**

| Item | Resolution | Now specified in |
|---|---|---|
| R-1 – R-8 | Approved as written | `07 §15`, `§16`, `§17`, `§10`, `§9`, `§6.2`, `§5.2`; `08` case template, screens 8, 21–23 |
| R-9 | Light `surface.base` `#F1F0EC` as the **Phase 4A starting value**, subject to the screenshot gate. Brand Paper `#F3F4F1` is unchanged. | `07 §4.2`, `§5.2` |
| R-10 – R-23 | Approved as written | `07 §9`, `§12`, `§13`, `§16`, `§17`, `§18`; `08 §4`, `§6`, `§8`, screens 3, 8, 21, 22 |
| R-24 | Separate `action.danger` token approved. Danger-red is **not** established as Reject's permanent treatment; it is re-evaluated once Request changes and escalation resolution exist (G4, G2). | `07 §4.2`, `§4.3` rule 5, `§18.1` |
| R-25 | Dark `surface.sheet` `#1A1F21` and `text.primary` `#DDE2E4` as **Phase 4A starting values**; hover / selected / raised / overlay re-derived and re-measured | `07 §4.2` |
| CH-1 | **Option A** for Phase 4A. Decision violet `#674EB0` / `#AA95E8`; only the person / action glyph and the short role word; the decision-surface rule is Ink; never framing model output; never for AI, automation, loading, onboarding or empty states; no gradients or glow. Prototype decision with a recognition test; fallback is neutral Ink. | `07 §4.3`, `§9.2–9.3`; `08` screen 8, §11.3 |
| CH-2 | **Phase 4A prototype hypothesis:** docked preview of about 380 px at ≥ 1280; modal drawer below 1280; one pane on mobile. No ambiguous non-modal overlay state. To be confirmed after the rendered review. | `07 §8`, `§18.3`; `08 §4`, §11.3 |

**Additional product-owner corrections:**

| Correction | Resolution | Now specified in |
|---|---|---|
| A. Uncalibrated model confidence | Never displayed in V2, including the inspector and raw payload views; no replacement percentage | `07 §2`, `§18.6`; `08 §4`, screen 5 |
| B. Burst / flood grouping | Presentation-only, always expandable, never hides asset, timestamp, severity, evidence, state or record; not implemented where safe expansion isn't possible (today: not in Phase 4A) | `07 §12.5`; `08` screen 2, §8, §9 |
| C. Backend truth | AVAILABLE / X / G distinctions preserved; no illustrative value becomes application data | `08 §1`, §11.3 |

**Found during reconciliation:**
- R-1 and R-2 assumed server timestamps. The stream carries only tick indices and simulated plant
  minutes.
- This is recorded as projection exposure **X8**, with an honest fallback: receipt-time freshness,
  tick-based axes, and no post-start sample count (`07 §15.1`, `§16`; `08 §1.2`, screen 10).
- No other G / X definition changed, except that G13 gained the approved roll-up rule (R-23).

**Supplementary reference pack (received after this study).** `OPERON-V2-Phase3-reference-pack`
(6 October 2026) uses its own evidence labels: VIEWED, PAGE, DOC, INDEX. Only the VIEWED items are
first-hand visual evidence:
- Refero Cycle dashboard (R01);
- Refero Vercel usage (R02);
- Mobbin Linear inbox (R05);
- Mobbin Linear issue detail (R09).

They corroborate decisions already in the baseline:

| Principle | Reference | Baseline it supports |
|---|---|---|
| Stable left rail with a central work area | R01 | Shell (`08 §3`) |
| Scope and time-range controls next to unit-labelled charts | R02 | `07 §16` "scope and time range sit next to the chart title" |
| Compact list, filter at the list head, readable timestamps | R05 | My actions (`08` screen 3), **without** read / unread state (G7 / G8) |
| A central document with a narrow properties rail | R09 | Case workspace with context rail (`08` case template) |

Its PAGE, DOC and INDEX entries are references, not visual evidence. Nothing in the pack reopens a
decision, and no reference's visual brand was imported (no blue charts, gradient illustrations,
activity avatars, command overlays or indigo actions).
