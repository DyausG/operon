# Operon: design mode classification (Phase 0)

Status: Phase 0 only. This document classifies Operon's frontend surfaces and derives design rules
from that classification. It doesn't redesign anything, choose references, fonts, colours or
libraries, or define a design system. The current visual styling is treated as **evidence of
intent, not as the target aesthetic**. The existing *semantic distinctions* (advisory vs.
authoritative vs. trusted vs. simulated vs. human) are treated as **product constraints**, because
they come from the domain invariant, not from styling.

Evidence base: repository reading plus a live run of the committed build (`uv run python run.py`,
deterministic/no-provider mode), inspected with headless Chromium at 1920, 1440, 1024 and 390 px,
idle and through a full Guided Demo (investigation → `AWAITING_APPROVAL` → UI approval →
`OBSERVING` → `CLOSED`).

---

## 1. What Operon is

**Operon is a governed agentic reliability-operations portal for an industrial plant.** An ML
health model trained on UCI AI4I 2020 scores a plant floor of eight machines every tick. When
failure risk crosses the 0.80 action gate, Operon opens a durable incident. The incident then moves
through an enforced lifecycle (`OPEN → INVESTIGATING → AWAITING_EVIDENCE → DIAGNOSIS_VALIDATED →
PLANNING → INTERVENTION_VALIDATED → AWAITING_APPROVAL → READY → EXECUTING → OBSERVING → CLOSED`,
plus `ESCALATED`, `EXECUTION_FAILED` and `CANCELLED`):

- specialist agents (diagnostic, engineering, operations, critic, planner, under a Reliability
  Supervisor) give *advisory* reasoning;
- the application, never the model, promotes a diagnosis and an intervention;
- deterministic governance runs;
- a human approves the **exact** work package by hash and revision;
- execution is claimed and receipted;
- the incident closes only when recovery is verified from post-intervention telemetry.

Sources: `README.md`, `docs/DEMO.md`, `docs/OPERON_ARCHITECTURE.md`, `core/reliability/state.py`.

Governing invariant (`README.md`): **prediction ≠ diagnosis ≠ intervention ≠ approval ≠ execution ≠
outcome. Agents reason; the application owns authority.** Every surface below inherits this.

**Users (repository evidence)**

| User | Evidence | Primary jobs |
|---|---|---|
| Maintenance approver (default role) | `frontend/src/state/session.jsx` `ROLES`; `signIn()` hard-sets `maintenance_approver` | decide on the exact plan at the human hold point; follow dispatch → verification |
| Reliability engineer | `ROLES`; agent workspace, evidence ledger, specialist runs (`pages/AgentPage.jsx`) | investigate cause, inspect evidence and advisory reasoning, steer the agent (PRISM operator instructions) |
| Plant operator | `ROLES`; operations dashboard, fleet strip, signal chart (`features/OperationsBoard.jsx`) | watch the fleet, notice drift toward the gate, see what is in flight |
| Observer | `ROLES` | read-only oversight (the repository says no more than that) |
| **Secondary: evaluators** (hackathon judges, portfolio reviewers) | `docs/DEMO.md` "Recommended reviewer walkthrough"; `docs/PRISM_RUNTIME.md` (Samsung PRISM GenAI Hackathon 2026, Theme 5); `docs/OPERON_ARCHITECTURE.md` §K; `render.yaml` hosted demo | understand the governed agent loop quickly, mostly through the Guided Demo |

Per the product owner's direction, the authenticated product serves the four personas first.
Evaluators are a secondary audience whose needs belong to the **Guided Demo** surface. They must not
turn operational screens into presentation screens.

Roles are currently *presentation only* (`pages/ProfilePage.jsx`: "The engine records approvals
under the dashboard operator identity until authentication exists"). Sign-in is a browser-local demo
session (`state/session.jsx`, `docs/DEMO.md`).

**Stack and shell.** React 18 + Vite. `frontend/src/app/routes.js` and `App.jsx` define `/login` as
the only public route, with everything else under `/app/*`. `app/AppShell.jsx` provides:

- a sidebar grouped Operate / Plan / Review / Account;
- a top bar with page title, plant or Guided Demo status, global search, the "Policy gate · HITL"
  badge, the reasoning-provider chip, the plant clock, the Engine menu, theme, notifications and the
  user menu;
- an artifact inspector tray reachable from every page (`features/Inspector/Tray.jsx`).

---

## 2. Surface inventory and routes

| ID | Surface | Routes / entry points | Primary user | Usage context |
|---|---|---|---|---|
| **A** | Entry / sign-in | `/login` | anyone reaching the host | once per device/session; the only public page |
| **B** | Operations command view | `/app/dashboard` (default landing; `OperationsBoard`: KPI deck, fleet strip, process line, Signal / Operation / Record columns) | plant operator, approver | continuous monitoring and triage during a shift |
| **C** | Incident lifecycle & approval | `/app/incidents`, `/app/incidents/:id` (Operation / Timeline / Record / Telemetry tabs). **The approval gate object** (`features/Operation/ApprovalGate.jsx`) also renders inside B and D. | maintenance approver, reliability engineer | per incident; the consequential decision |
| **D** | Agent workspace (PRISM) | `/app/agent`, `?incident=`, `?machine=` | reliability engineer | per incident when reasoning needs inspecting or steering |
| **E** | Fleet & assets | `/app/machines`, `/app/machines/:id` (Overview / Telemetry / Incidents / Maintenance / Operon actions / Activity) | operator, reliability engineer | status scan and drill-in on one asset |
| **F** | Records & review | `/app/maintenance`, `/app/activity`, `/app/notifications`, notification menu | approver, engineer, observer | follow-up, audit, "what happened" |
| **G** | Analytics & impact | `/app/analytics` | reliability engineer, plant management | periodic review of risk trends and economic impact |
| **H** | Configuration & account | `/app/settings` (General, Appearance, Notifications, Agent preferences, AI provider, Plant & system, Account), `/app/profile`, Engine menu (top bar) | engineer or administrator setting up; every user for preferences | set-and-forget; diagnostics when something is wrong |
| **I** | Guided Demo (presentation mode) | **not a route**: a cross-cutting engine state started from Engine menu → *Start Guided Demo*, Settings → Plant & system, or Machine detail → *Run Guided Demo here*. It is experienced through B, C and D. | evaluator (secondary audience); presenter | one-off ~1-minute run of the real lifecycle on a deterministic scenario |

Grouping decisions:

- **Shell and inspector** are shared infrastructure, not a surface. They follow B's rules because B
  is their heaviest use.
- **Maintenance, Activity and Notifications are one surface.** In Operon they are all read-only
  ledgers projected from the incident lifecycle. `MaintenancePage.jsx` says "Creating ad-hoc work
  orders from the portal is intentionally not offered". `NotificationsPage.jsx` notes that items are
  browser-only. All three share the same job: find and trust a record.
- **Incidents and the approval gate are one surface, even where the gate renders elsewhere.** The live
  run shows the identical gate (exact plan, bound-to hash, revision, policy, Approve / Reject) on
  `/app/dashboard`, `/app/incidents/:id` and `/app/agent`. The decision's rules must not vary by
  host page.
- **Guided Demo is separated** because its purpose (an evaluator understanding the loop in about a
  minute) differs materially from the operational purpose of the screens it runs on.
- **Out of scope:** `README.md` and `docs/banner.svg` are a public-facing repository surface, not
  part of the app. There is **no public landing or marketing page** in the frontend.

---

## 3. Nine-axis classification

Axes, where 1 = first pole and 5 = second pole:

1. Operational ↔ Exploratory
2. Repeated-use ↔ Occasional-use
3. Information-heavy ↔ Experience-heavy
4. Task-oriented ↔ Narrative-oriented
5. Brand-subordinate ↔ Brand-dominant
6. Conventional ↔ Experimental interaction
7. Utility ↔ Expression
8. Desktop-heavy ↔ Mobile-heavy
9. Authenticated product ↔ Public-facing

| Surface | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | Track |
|---|---|---|---|---|---|---|---|---|---|---|
| A Entry / sign-in | 1 | 4 | 3 | 3 | 3 | 1 | 3 | 2 | 5 | **HYBRID** |
| B Operations command view | 1 | 1 | 1 | 2 | 1 | 2 | 1 | 1 | 1 | **PRODUCT** |
| C Incident lifecycle & approval | 2 | 2 | 1 | 2 | 1 | 1 | 1 | 2 | 1 | **PRODUCT** |
| D Agent workspace (PRISM) | 3 | 3 | 1 | 2 | 1 | 3 | 2 | 1 | 1 | **PRODUCT** |
| E Fleet & assets | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | **PRODUCT** |
| F Records & review | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | **PRODUCT** |
| G Analytics & impact | 3 | 3 | 2 | 3 | 1 | 1 | 2 | 2 | 2 | **PRODUCT** |
| H Configuration & account | 2 | 5 | 2 | 1 | 1 | 1 | 1 | 2 | 1 | **PRODUCT** |
| I Guided Demo | 3 | 5 | 3 | 5 | 3 | 2 | 3 | 1 | 4 | **HYBRID** |

### 3.1 Scores changed after the runtime inspection or the audience clarification

| Surface · axis | Preliminary → final | Why |
|---|---|---|
| G · 1 Op↔Exp | 4 → **3** | **Runtime.** Analytics is computed from the current engine *generation* only (`state/portal.js` `analytics(state)`; the live page shows "720 telemetry samples in this generation" and charts spanning 90 ticks ≈ 22 plant-hours). It is a shift/session review, not open-ended long-horizon exploration. |
| G · 2 Repeat↔Occ | 4 → **3** | **Runtime.** For the same reason, a generation-scoped summary suits a per-shift or daily check rather than a monthly report. |
| I · 6 Conv↔Exp | 3 → **2** | **Runtime.** The live Guided Demo has **no presentation layer**. The only cues are the top-bar subtitle ("Guided Demo · Instrument Air Compressor 01 · awaiting human approval") and the provenance chip; everything else is the ordinary product (`README.md`: "Everything else is the real product"). It reached `AWAITING_APPROVAL` about 18 s after start, faster than the ~42 s the README documents, and closed about 25 s after approval. The loop is too fast for time-based choreography. Whatever helps an evaluator must be a conventional, persistent layer over real state, not an experimental scripted interaction. |
| A · 5 Brand | 4 → **3** | **Audience clarification.** Sign-in is still the only public page, but brand serves *entering the plant's tool honestly*, not impressing judges. The live UI already drops the brand panel below 900 px (`styles/login.css`). |
| D · 5 Brand | 2 → **1** | **Audience clarification.** The preliminary 2 came from D being the Theme 5 showcase. That is an evaluator need and must not shape the operational workspace. |
| G · 5 Brand | 2 → **1** | **Audience clarification.** Same reasoning: impact numbers serve plant stakeholders; judges are secondary. |

**Boundary change after runtime.** The approval gate renders on B, C and D. It is classified once,
under C, and C's rules govern it wherever it appears.

**Runtime observations that confirmed scores (not changed):**

- **Live mode is multi-incident.** In the first run the live simulator opened four concurrent
  incidents within about 40 plant-minutes. All four escalated, because the container's invalid AWS
  credentials made Operon auto-select Bedrock and every supervisor run failed authentication. The
  record surfaced those errors verbatim. This confirms B as a triage surface across concurrent and
  exceptional incidents.
- **At 390 px, nothing overflows the page horizontally,** but it isn't a designed phone experience:
  - tables scroll inside their containers (Incidents at 390 shows only two columns);
  - the dashboard becomes one long column with the approval gate far below the signal chart;
  - the exact-plan grid wraps to one word per line;
  - the Bound-to / Package / Hash row overlaps and is illegible. It overlaps at 1440 and 1920 px as
    well.
- **Density is real.** One Guided-Demo incident produced 70 record entries and 61 timeline events.
- **Agent workspace in no-model mode is mostly reserved content.** Much of it is hatched "reserved"
  runtime cells, a run-state vocabulary and capability notes that quote an API path (`POST
  /api/prism/sessions/{id}/messages`). The operator-instruction console sits inside a tab labelled
  "Activity". The content currently leans toward explaining the runtime to a developer or evaluator.
  That is a tension to resolve in later phases, not a reason to reclassify D.

### 3.2 Reasons for every score

#### A · Entry / sign-in (`/login`)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 1 | One job: get in. There is nothing to explore (`pages/LoginPage.jsx`: email, password, remember, forgot). |
| 2 Repeat↔Occ | 4 | "Remember me on this device" persists the session (`state/session.jsx`), so a plant user sees this rarely. An evaluator sees it once. |
| 3 Info↔Exp | 3 | Half form (utility), half a three-point statement of the trust model (signal ≠ execution, advisory agents, human hold point) in `login-side`. |
| 4 Task↔Narr | 3 | The task is sign-in, but the side panel narrates what Operon promises, which matters because this is the first thing anyone sees. |
| 5 Brand | 3 | The only screen where wordmark and tagline lead. The brand panel is dispensable (hidden < 900 px) and the form and honesty note are the point. |
| 6 Conv↔Exp | 1 | Authentication must behave conventionally: `autocomplete="username"` and `current-password`, password managers, show/hide, error text. |
| 7 Util↔Expr | 3 | The form is pure utility; the side panel is the one sanctioned place for expression of what Operon is. |
| 8 Desk↔Mob | 2 | People may open the link on any device and the page collapses to a single column at 900 px. The product behind it is desktop-heavy, so sign-in usually happens on desktop. |
| 9 Auth↔Pub | 5 | The only unauthenticated route (`App.jsx`); on the hosted Render demo it is the public face. |

#### B · Operations command view (`/app/dashboard`)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 1 | Live WebSocket state (`state/useEngine.js`), an action gate at 0.80, and a hold point you can act on directly on this page (the approval gate renders here). |
| 2 Repeat↔Occ | 1 | The default landing page (`App.jsx` index → dashboard; Settings "Landing page" defaults to Dashboard); built for a whole shift. |
| 3 Info↔Exp | 1 | KPI deck, 8-tile fleet strip with risk and sparkline, an 11-segment process line, and signal, operation and record columns all on one screen (1920 px screenshot). |
| 4 Task↔Narr | 2 | Triage is the task, but the process line (SENSE → CLOSE) gives each incident an inherent sequence the operator reads. |
| 5 Brand | 1 | The wordmark is a small sidebar item; nothing on the board exists for brand. |
| 6 Conv↔Exp | 2 | Mostly conventional (tables, tabs, charts). The domain grammar is specific but must stay learnable: hold-point hatching on APPROVE, dashed advisory vs. solid authority, SIMULATED hatch. |
| 7 Util↔Expr | 1 | Every element answers "is anything wrong, and what is Operon doing about it". |
| 8 Desk↔Mob | 1 | The three-column stage; breakpoints at 1680/1440/1200 px progressively drop the record column (`styles/shell.css`, `tokens.css`). At 390 px it becomes an unordered long scroll. |
| 9 Auth↔Pub | 1 | Behind `RequireAuth`; the operational heart of the product. |

#### C · Incident lifecycle & approval (`/app/incidents`, `/app/incidents/:id`, approval gate on B and D)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 2 | The decision is operational. Reading evidence, verdicts and the timeline before deciding adds some investigation. |
| 2 Repeat↔Occ | 2 | Every incident passes through here. The approver's primary route is sidebar-badged (Incidents count, Operon Agent approvals). |
| 3 Info↔Exp | 1 | Lifecycle identifiers (diagnosis, intervention, hash, requirement, revision, authority valid, reconciliation), the exact-plan grid, 70-entry record. |
| 4 Task↔Narr | 2 | The Timeline tab tells the incident's story (Detection → Evidence → Reasoning → Diagnosis → Recommended action → Approval → Execution → Resolution), but only to support a decision. |
| 5 Brand | 1 | No brand role; trust comes from correctness, not identity. |
| 6 Conv↔Exp | 1 | A consequential, hash-bound approval must be unmistakable and conventional. A confirm modal restating the hash and revision is on by default (`state/settings.jsx` `confirmBeforeApprove: true`). |
| 7 Util↔Expr | 1 | Pure utility; expression here would lower trust in the decision. |
| 8 Desk↔Mob | 2 | An approver might be away from the desk, and the gate is technically usable at 390 px. But the binding row that proves *which* plan you approve is illegible there, so the surface is effectively desktop. |
| 9 Auth↔Pub | 1 | Authenticated; it records a human decision. |

#### D · Agent workspace (`/app/agent`)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 3 | Inspecting specialist runs, delegations, the evidence packet, PRISM revisions and stale candidates is investigative. Sending an instruction that supersedes a revision is operational. |
| 2 Repeat↔Occ | 3 | Used per incident when reasoning needs attention, not continuously. The operator console is a tab, not the default view. |
| 3 Info↔Exp | 1 | Three columns: context list, runtime state grid and PRISM KV grid; operation tabs; runs, recommendations and transitions. |
| 4 Task↔Narr | 2 | Delegation chains and progress have sequence. The repository explicitly wants "concise findings and evidence references … not an unrestricted stream of model reasoning" (`docs/OPERON_ARCHITECTURE.md` §K). |
| 5 Brand | 1 | Operational workspace (changed from 2, see §3.1). |
| 6 Conv↔Exp | 3 | Interruptible agents with revision fencing, supersession and discarded stale candidates (`docs/PRISM_RUNTIME.md`) have no established UI convention. Some new interaction is unavoidable. |
| 7 Util↔Expr | 2 | Utility first. Conveying *agent state* (running, superseded, fenced) needs some distinct expression, but only enough to be read accurately. |
| 8 Desk↔Mob | 1 | The three-column grid collapses at 1440/1000 px (`styles/pages.css`); dense inspection is a desk task. |
| 9 Auth↔Pub | 1 | Authenticated; it can change what the agent reasons about. |

#### E · Fleet & assets (`/app/machines`, `/app/machines/:id`)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 2 | Status scan (sortable by risk) plus drill-in to one asset's telemetry envelopes and failure-mode surveillance. |
| 2 Repeat↔Occ | 2 | Regular checks on assets that are drifting; also reached from global search and incident links. |
| 3 Info↔Exp | 1 | A 10-column table (id, class, criticality, status, risk, health, trend, signature, incidents, last sample); the detail page has 6 tabs, channel envelopes and failure-mode cells. |
| 4 Task↔Narr | 1 | Look up, compare, drill in. |
| 5 Brand | 1 | None. |
| 6 Conv↔Exp | 1 | Sortable table, filters, segmented status, tabs: standard patterns suit comparison. |
| 7 Util↔Expr | 1 | Utility. |
| 8 Desk↔Mob | 2 | Table-centric and desktop-first. A technician checking one machine on a tablet near the asset is plausible but has no repository evidence. |
| 9 Auth↔Pub | 1 | Authenticated. |

#### F · Records & review (`/app/maintenance`, `/app/activity`, `/app/notifications`)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 2 | Follow-up and audit: filter by lane, machine or kind, then open an artifact in the inspector. |
| 2 Repeat↔Occ | 2 | Notifications and pending approvals are checked often; the full audit trail less often. |
| 3 Info↔Exp | 1 | Chronological ledgers with lane, revision, time and context columns; the maintenance table has 11 columns. |
| 4 Task↔Narr | 1 | Find a record and verify it. |
| 5 Brand | 1 | None. |
| 6 Conv↔Exp | 1 | Tables, lists, filters and inbox patterns. |
| 7 Util↔Expr | 1 | Utility. |
| 8 Desk↔Mob | 2 | Notifications are the most plausibly mobile content in Operon. Everything else is tabular (maintenance rows wrap to 5 lines at 1440 px). |
| 9 Auth↔Pub | 1 | Authenticated. |

#### G · Analytics & impact (`/app/analytics`)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 3 | Trend and distribution reading (Fleet vs. per-asset risk toggle, table views), bounded to the current generation (changed from 4). |
| 2 Repeat↔Occ | 3 | A shift or daily review, not continuous (changed from 4). |
| 3 Info↔Exp | 2 | Chart-led, with five KPI cells and six distributions. Still information, but read more at a glance than row by row. |
| 4 Task↔Narr | 3 | Carries the business case: recovered value, net impact, OEE baseline vs. target, downtime cost. The README says "every number a stakeholder might challenge … is surfaced in the UI". |
| 5 Brand | 1 | Changed from 2 (§3.1). |
| 6 Conv↔Exp | 1 | Standard line, bar and horizontal-bar charts; honesty over novelty. |
| 7 Util↔Expr | 2 | Mostly utility; the economic framing adds a small persuasive element. |
| 8 Desk↔Mob | 2 | Charts need width; a manager might glance on a tablet. |
| 9 Auth↔Pub | 2 | Authenticated, but its audience reaches beyond operators to plant stakeholders who consume the numbers. |

#### H · Configuration & account (`/app/settings`, `/app/profile`, Engine menu)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 2 | Set values; the provider "Test connection" is a diagnostic action. |
| 2 Repeat↔Occ | 5 | Set once. Revisited on a provider failure, a reset, or a preference change. |
| 3 Info↔Exp | 2 | Status grids (active provider, selection, backend, supervisor, thresholds) plus substantial explanatory prose about scope and truthfulness. |
| 4 Task↔Narr | 1 | Configure and verify. |
| 5 Brand | 1 | None. |
| 6 Conv↔Exp | 1 | Toggles, selects, radio cards, anchored section nav. |
| 7 Util↔Expr | 1 | Utility. |
| 8 Desk↔Mob | 2 | Stacks cleanly below 900 px; configuration is a desk task. |
| 9 Auth↔Pub | 1 | Authenticated; the provider section talks to engine-side configuration (`server/providers_api.py`). |

#### I · Guided Demo (presentation mode over B/C/D)

| Axis | Score | Reason |
|---|---|---|
| 1 Op↔Exp | 3 | The evaluator isn't running a plant; they watch the real loop and probe it (inspector, tabs), then take one operational act: approve or reject. |
| 2 Repeat↔Occ | 5 | Once per evaluator (`docs/DEMO.md` walkthrough); a presenter repeats it, but for a new audience each time. |
| 3 Info↔Exp | 3 | Runs on the same dense screens, but its success is whether a newcomer *experiences* the loop in about a minute. |
| 4 Task↔Narr | 5 | A fixed story documented in five steps (`README.md` "The 90-second Guided Demo": Signal → Investigate → Plan and validate → Human-in-the-loop → Execute, observe, verify). |
| 5 Brand | 3 | The first sustained impression for an outsider, so identity matters. It is bounded by honesty: SIMULATED, deterministic advisory and no-model labels must stay visible. |
| 6 Conv↔Exp | 2 | Changed from 3 (§3.1): it must remain the real product, and the pace (~18 s to the hold point) rules out time-scripted choreography. |
| 7 Util↔Expr | 3 | Must be useful (the real decision) and communicative (make the invariant visible). |
| 8 Desk↔Mob | 1 | Run from a laptop via `./demo.sh` or shown on a shared screen; at 390 px the story's spine (process line → gate) is split across a long scroll. |
| 9 Auth↔Pub | 4 | The audience is outsiders; the hosted demo accepts any email (`docs/DEMO.md`). Technically it still sits behind the demo sign-in. |

---

## 4. Shared product constraints (from the invariant, not from styling)

These apply to every PRODUCT surface and to the product screens the Guided Demo runs on.

1. **Record kinds stay visibly distinct.** The invariant (prediction ≠ diagnosis ≠ intervention ≠
   approval ≠ execution ≠ outcome) and the lanes the code already models (`authority`, `advisory`,
   `trusted`, `human`, `application`, `stream` in `pages/ActivityPage.jsx`; `ProvenanceTag`,
   `OwnerChip` in `primitives/`) require every surface to distinguish:
   - advisory output (agent/model),
   - authoritative application records,
   - trusted inputs (inspection, executor receipts),
   - human decisions,
   - SIMULATED or deterministic provenance.

   *How* they are encoded is a later decision; that they differ is fixed.
2. **Grey-is-normal is a semantic requirement.** It follows from 8 machines × continuous scoring
   with only a few in exception. It doesn't dictate any particular grey.
3. **Truthful state over optimistic state.** "Operon never substitutes a fabricated reasoning
   result" (`docs/DEMO.md`). Standby, unavailable, escalated, stale and reserved states must be as
   legible as success.
4. **Identifiers are first-class data.** Hash, revision, requirement id and incident id are what
   approval binds to (`ApprovalGate.jsx`). They must be copyable, legible and never truncated so far
   that equality can't be checked.

---

## 5. Derived design rules per surface

Format: *classification / user need → design consequence.*

### A · Entry / sign-in: HYBRID

| Dimension | Rule |
|---|---|
| Information density | Occasional-use (4) + single task (1) → the minimum fields plus **one** honesty statement (browser-local session, no host authentication). Nothing else competes with the form. |
| Typography | Public (5) + brand 3 → one display moment (the tagline) is allowed. Conventional auth (1) → labels, errors and hints use the product's normal UI type so the form feels like the product it opens. |
| Navigation | Single task → no navigation other than theme and "Forgot password?". After sign-in, return to the requested deep link (the current `location.state.from` behaviour is correct). |
| Layout | Info/Exp 3 → a split is justified: the form is primary, the thesis secondary. Desktop-first but device-agnostic (2) → the thesis panel is the first thing to collapse. |
| Motion | Occasional + conventional → none beyond focus and submit feedback. Nothing should delay reaching the form. |
| Colour | Brand 3 → brand colour may appear here more than anywhere else, but status colours keep their product meanings (the thesis points already use the advisory / authority / verified distinctions). |
| Imagery | Public + narrative 3 → imagery is allowed only if it *states the thesis* (signal → advice → human hold → verified outcome). No stock industrial photos or 3D machines, which would imply capabilities (digital twin, physical control) the repository explicitly excludes (`OPERON_ARCHITECTURE.md` "DO NOT BUILD": digital twin, PLC control). |
| Interaction patterns | Conventional (1) → native autofill, show/hide, inline validation, Enter submits. Never add fake SSO or IdP buttons: none exist. |
| Component reuse | Reuse product form fields and buttons, so the first touch predicts the product. |
| Visual metaphor | Thesis → a metaphor, if any, is the *governed loop*, not a machine or a brain. |
| Storytelling | Narrative 3 → at most three statements. The story is "what Operon will and won't do", not a feature list. |
| Responsive | Desktop 2 → single column under the collapse point; the honesty note must survive every width. |

### B · Operations command view: PRODUCT

| Dimension | Rule |
|---|---|
| Information density | Repeated (1) + information-heavy (1) → high density is correct: every asset, the pipeline state and the current incident at once. Density is earned by suppressing *normal*: nominal assets and inactive segments recede so the few exceptions carry the eye. |
| Typography | Readouts are compared across tiles every tick → tabular/monospaced numerals for risk, health, revision and ids. A small number of type roles (label, value, heading), because operators scan structure, not prose. |
| Navigation | Continuous use (1) → persistent navigation with live counts (active incidents, pending approvals, unread). Every object on the board links to its home (machine → E, incident → C, run → D). No modal detours from the primary view. |
| Layout | Triage across **concurrent** incidents (observed: 4 at once) → the layout must answer "which incidents need a human now" before "what is the state of the focused one". Stable positions over time (repeated use builds spatial memory); nothing reflows on every tick. |
| Motion | Live stream + repeated use → motion only signals a *state change* (phase transition, new record, crossing the gate) and must never loop decoratively. Respect reduced motion (already honoured in `styles/base.css`). |
| Colour | Grey-is-normal + exception-driven attention → colour is spent only on warning, critical, verified, advisory and human-action states. Brand colour must not collide with a status meaning. |
| Imagery | Utility (1) → no photographs or illustrations. Equipment-class icons are allowed as identification aids. |
| Interaction patterns | Operational → one-click drill-ins, hover or focus for detail, keyboard-reachable search. The consequential approve/reject action follows C's rules even when it appears here. |
| Component reuse | The Signal, Operation and Record components are shared with C, D and E → they are defined once and must read identically on every host page. |
| Visual metaphor | The **process line** (lifecycle as an 11-segment track with a hold point) is the domain's own metaphor and earns its place. No control-room skeuomorphism (dials, gauges) that would imply physical control. |
| Storytelling | Task 2 → only the lifecycle position of each incident; no editorial copy on the board. |
| Responsive | Desktop 1 → optimise for ≥1440 px. Below that, preserve *priority order* (exceptions → hold points → focused incident → record) rather than squeezing columns. The phone layout is a degraded read-only view unless Phase 1 evidence says otherwise. |

### C · Incident lifecycle & approval: PRODUCT

| Dimension | Rule |
|---|---|
| Information density | Info-heavy (1) + consequential decision → full identifiers and evidence are available, but the **decision block** (exact plan, bound hash, revision, conditions, Approve / Reject) is compact and self-contained. Everything needed to decide sits in it without scrolling. |
| Typography | The approver checks *equality* of hash and revision → ids in monospace, with enough visible characters to compare. Truncation must be deliberate and expandable, never overlapping (the live binding row overlaps today). |
| Navigation | Per incident, repeated → list → detail with breadcrumbs; the list filters by "Needs approval". Deep links to incident, artifact (`#artifact=`) and agent workspace (`?incident=`) are part of the job. |
| Layout | The decision governs → the incident page is organised around *where the incident is in the lifecycle* and *what can happen next* ("What can happen next" is already modelled for escalated incidents). Supporting evidence sits beside or behind the decision, never between the approver and the buttons. |
| Motion | Conventional (1) → the decision block must not animate in a way that moves buttons while the approver is reading. Transitions only confirm that a decision was recorded. |
| Colour | Human hold point → the hold state has a distinct, non-alarm colour meaning ("human required" is neither warning nor success). Rejection and escalation use exception colours; advisory stays visually subordinate to authority. |
| Imagery | None. Evidence *data* (the telemetry trace annotated with gate, planned window and observation samples) is the only imagery. |
| Interaction patterns | Consequential + conventional (1) → Approve is explicit, labelled with its consequence ("Approve exact plan and dispatch"), paired with an equally reachable Reject, and optionally confirmed. No hold-to-confirm, swipe or gesture: they hide the binding. |
| Component reuse | **One approval gate component, rendered identically on B, C and D.** Its rules can't depend on the host page. |
| Visual metaphor | Lifecycle timeline and process line. The Timeline tab's Detection → Resolution structure is the domain story and is reused. |
| Storytelling | Task 2 → the timeline narrates *what happened and why* to justify the decision. No prose beyond recorded reasons and justifications. |
| Responsive | Desktop 2 → until mobile approval is confirmed as a need (open question), narrow widths must at least keep the decision block's identifiers legible, or refuse to present an approve action that can't be verified. |

### D · Agent workspace (PRISM): PRODUCT

| Dimension | Rule |
|---|---|
| Information density | Info-heavy (1) + investigative (3) → dense, but organised by *revision*: current instruction, current canonical result, then history (superseded or stale). Reserved or unavailable capabilities are visible in *one* place, not scattered across the page. |
| Typography | Revision numbers, run ids and model and provider labels are decision-relevant → monospace for ids. Advisory prose from agents is typographically distinct from application records. |
| Navigation | Per incident → context list (incidents) → workspace; deep-linkable by incident and machine. The operator-instruction console must be reachable without guessing (today it hides under an "Activity" tab). |
| Layout | Governing question "which revision is canonical and is anything still running" → the current revision's state and the input to supersede it are primary. Runs, evidence and transitions are secondary panels. |
| Motion | Experimental 3 → motion *may* represent agent lifecycle (queued → running → superseded → fenced/stale → canonical), since that is new information. It must never suggest thinking or intelligence (no typing indicators, sparkles or pulsing "AI" glows). |
| Colour | Advisory vs. authoritative is the core distinction → agent output is never styled as authority. Stale and superseded results get their own non-success treatment; live model vs. deterministic advisory are distinguishable at a glance. |
| Imagery | None. No agent avatars or personas: "Agents reason; the application owns authority." |
| Interaction patterns | New pattern needed (6 = 3): *instruct → immediate fast-path acknowledgement → slow-path result per revision*, where a new instruction supersedes the old. This is **not** a chat. Messages are revisions with provenance, and a result that arrives late is shown as discarded, not merged. |
| Component reuse | Reuse the approval gate (C), evidence slots, specialist chain and provenance tag. Don't fork variants for the workspace. |
| Visual metaphor | Revision ledger or supersession chain, not a conversation thread. |
| Storytelling | Concise findings and evidence references, never an unbounded reasoning stream (`OPERON_ARCHITECTURE.md` §K). |
| Responsive | Desktop 1 → three regions at wide widths. Below that the order is: current revision and instruction → result → runs and evidence → context. |

### E · Fleet & assets: PRODUCT

| Dimension | Rule |
|---|---|
| Information density | Comparison across 8 assets (or more, see §8) → tabular density with sort by risk as the default (already the default). |
| Typography | Numeric comparison → tabular numerals and right-aligned numbers; the asset id is the primary identifier, the name secondary. |
| Navigation | Table → detail → the incident or agent for that asset. Global search reaches assets directly. |
| Layout | Scan then drill → the list is a table, not a card gallery. Detail puts current status, risk and health and any active alert first; history lives in tabs. |
| Motion | Minimal; sparklines update in place without animated redraw churn. |
| Colour | Grey-is-normal; only warning or critical assets are coloured. The per-asset chart already recedes nominal assets, and that principle applies here too. |
| Imagery | Equipment-class icons only. No machine photos or renders: the data is simulated, and pictures would imply specific real equipment. |
| Interaction patterns | Sort, filter, segmented status, row click to detail; conventional (1). |
| Component reuse | Signal column and telemetry envelopes come from B; maintenance and activity tables from F. |
| Visual metaphor | Operating envelope (value against a nominal band) for telemetry, the domain's own framing ("Physical SCADA telemetry envelopes"). |
| Storytelling | None beyond "why is this asset in this state" (status source, signature). |
| Responsive | Desktop 2 → on narrow widths, collapse table rows to id, status and risk and keep sort. Whether tablet-at-the-asset is a real mode is an open question. |

### F · Records & review: PRODUCT

| Dimension | Rule |
|---|---|
| Information density | Audit (info 1) → one row per record, many rows per screen, lane and revision always visible. |
| Typography | Time, revision and id in monospace; titles in UI type; detail secondary. |
| Navigation | Filter by lane, machine and kind; every row opens its artifact in the inspector or links to its incident or machine. |
| Layout | Chronological with day separators; filters above, never in a side panel that hides rows. |
| Motion | New rows appear without shifting the row being read. |
| Colour | Lane identity (authority, advisory, trusted, human, engine) must survive in the list; exception states are coloured, routine ones aren't. |
| Imagery | None. |
| Interaction patterns | Inbox semantics for notifications (read/unread, needs action). Ledger semantics for activity and maintenance (read-only; the repository deliberately offers no ad-hoc work-order creation). |
| Component reuse | One activity-list component (already shared with the machine detail page) and one maintenance table. |
| Visual metaphor | A ledger, not a social feed. |
| Storytelling | None. Records speak through their recorded reasons. |
| Responsive | Desktop 2 → notifications must be readable on a phone (most plausible mobile content). Tables collapse to key columns. |

### G · Analytics & impact: PRODUCT

| Dimension | Rule |
|---|---|
| Information density | Info 2 → fewer, larger visualisations than B; each chart answers one question. |
| Typography | Headline figures (recovered value, OEE) may be larger than elsewhere (narrative 3), always with unit, scope and provenance adjacent. |
| Navigation | Single page; a chart or distribution should link to the incidents or assets it counts. |
| Layout | Business case first (value, OEE, downtime cost), then risk and health trends, then distributions. |
| Motion | None beyond hover and tooltip; charts don't animate on load (repeated reading, honest numbers). |
| Colour | Thresholds (gate, warn) keep their product colours; categorical series follow the same exception-first rule (per-asset view already recedes nominal assets). |
| Imagery | Charts only. |
| Interaction patterns | Fleet vs. per-asset toggles, table views for every chart (already present), hover values. |
| Component reuse | Shared chart primitives with B and E. |
| Visual metaphor | None beyond standard charts. |
| Storytelling | Narrative 3 → each number carries its provenance: simulated economics, generation scope ("this generation"), configured economics from `core/config.py`. The story is *traceable value*, not a sales claim. |
| Responsive | Desktop 2 → charts reflow to one column; KPI cells stay legible. |

### H · Configuration & account: PRODUCT

| Dimension | Rule |
|---|---|
| Information density | Occasional (5) → moderate density; plain-language explanation is justified because users arrive rarely and often because something is wrong. |
| Typography | Config keys, model ids and env names in monospace; explanations in body text. |
| Navigation | Anchored sections (`#provider`, `#plant` deep links are used by the Engine menu). |
| Layout | Scope is the organising principle → every setting says where it lives (**browser-local** vs. **engine**, already tagged). Engine configuration and personal preferences are visually separated. |
| Motion | None beyond save and test feedback. |
| Colour | Provider status (configured, unverified, reachable, failed) uses the same truthful-state colours as elsewhere; "not configured" is a normal state, not an error. |
| Imagery | Provider identification at most; no decorative imagery. |
| Interaction patterns | Conventional (1): toggles, selects, radio cards, explicit Save and Test connection. Disabled controls say why (for example, the "Sound" toggle). Don't add controls that have no effect. |
| Component reuse | Product form components (shared with A and D). |
| Visual metaphor | None. |
| Storytelling | None, except short truthful explanations of mode (deterministic vs. model-backed). |
| Responsive | Section nav becomes a horizontal wrap under 900 px (already present); forms become single column. |

### I · Guided Demo: HYBRID

| Dimension | Rule |
|---|---|
| Information density | Runs on dense product screens (B/C/D), but the newcomer needs one thread → any demo aid shows **one** current step at a time on top of unchanged product density. It doesn't simplify the product screens themselves. |
| Typography | Shared-screen presentation (desktop 1, outsiders) → any demo-specific text must be legible at a distance. Product typography is not enlarged globally, which would distort B. |
| Navigation | The loop crosses B → C → D → back to B. A demo aid may *point* to where the next thing is happening, but must never auto-navigate the viewer away from what they are reading. |
| Layout | Demo aids live outside the operational layout (the top-bar demo status is the current seam) and never cover the process line, the approval gate or provenance labels. |
| Motion | Pace is fast (~18 s to the hold point) → rely on persistent state (step reached, what just happened) rather than transient animations a viewer can miss. Motion may *mark* a transition but must not be the only record of it. |
| Colour | SIMULATED and deterministic provenance labels stay at full visibility; the demo can't recolour anything to look "more live". |
| Imagery | None added. The real telemetry trace (degradation ramp crossing the gate, recovery samples) is the demo's imagery. |
| Interaction patterns | Conventional (6 = 2). Start, restart, reset (with confirm) and the real Approve/Reject. The human decision can't be automated or pre-clicked: the README guarantees no timer or callback can approve. |
| Component reuse | Zero demo-only forks of product components. The demo is the product plus a thin, removable narrative layer. |
| Visual metaphor | The five documented steps (Signal → Investigate → Plan & validate → Human-in-the-loop → Execute/observe/verify) mapped onto the existing process line, not a new metaphor. |
| Storytelling | Narrative 5 → the one surface where explicit storytelling is required: *prediction, not cause*; advisory vs. authority; exact-hash approval; verified recovery. Each claim is tied to a real on-screen record, never to scripted copy that could diverge from state. |
| Responsive | Desktop 1 → designed for laptop and projector widths (1280–1920 px). No phone presentation target. |

---

## 6. Governing idea per surface

| Surface | Governing idea |
|---|---|
| A Entry / sign-in | **Enter the plant's reliability tool knowing exactly what kind of session this is.** |
| B Operations command view | **What needs a human right now, across every asset and every open incident?** |
| C Incident lifecycle & approval | **Decide on the exact plan, able to see what is evidence, what is advice and what is authority.** |
| D Agent workspace | **See which revision the agent is working on, what it concluded, and steer it without ever granting it authority.** |
| E Fleet & assets | **Which asset is drifting toward the gate, and why?** |
| F Records & review | **Find the record and trust what it says.** |
| G Analytics & impact | **Is the value real, and can every number be traced?** |
| H Configuration & account | **Know and change what the engine is running on, truthfully.** |
| I Guided Demo | **Make the governed loop understandable to a newcomer in about a minute, without faking any part of it.** |

---

## 7. Failure modes to guard against (Operon-specific)

| Surface | Most likely way an AI-generated redesign makes it worse |
|---|---|
| A | A marketing hero: gradient backdrop, 3D factory or robot-arm art, "Sign in with Google/Okta" buttons, while the demo-session disclosure disappears. That implies authentication and capabilities Operon explicitly doesn't have. |
| B | A generic SaaS KPI dashboard: every metric in its own colourful card with an icon, green/red everywhere, decorative area charts, "AI insights" panels. This breaks grey-is-normal, so four concurrent critical incidents look no different from routine noise, and the hold point is lost among cards. |
| C | Advisory and authoritative records flattened into one uniform card style, and Approve turned into a cheerful primary CTA without the hash, revision and bound plan beside it. The approver can then no longer tell *what* they are approving, or whether the agent or the application said it. |
| D | A ChatGPT-style chat UI: message bubbles, agent avatars, streaming "thinking…" sparkles. That hides revisions, supersession and discarded stale candidates, implies the model has authority, and presents deterministic advisory as live AI. |
| E | A card gallery of machine photos or 3D renders with radial gauges, replacing a sortable comparison. It is slower to scan and implies real equipment and physical control. |
| F | Activity reskinned as a social or news feed (avatars, relative-time bubbles, reactions), with lanes flattened and browser-local notifications presented as a durable inbox. |
| G | A vanity dashboard: huge "$101,150 saved!" hero numbers without scope or provenance, simulated economics presented as real, chart animation and junk. |
| H | A settings page padded with plausible-looking toggles that do nothing, where the browser-local vs. engine scope blurs and "deterministic / no provider" is rendered as a connected success state. |
| I | A scripted marketing walkthrough: coach marks, spotlight overlays, auto-advancing slides and confetti on CLOSED. It covers the process line or approval gate, hides SIMULATED labels to look more impressive, or auto-approves, turning a real governed product into a video. |

---

## 8. Track selection

| Surface | Track | Why |
|---|---|---|
| A Entry / sign-in | **HYBRID** | Public-facing (9 = 5) with a sanctioned narrative panel (3/3), but interaction must be fully conventional (6 = 1) and the brand stays subordinate to honesty (5 = 3). Expression is allowed in the thesis panel only. |
| B Operations command view | **PRODUCT** | Every axis sits at the operational, repeated, information, utility, desktop and authenticated pole. |
| C Incident lifecycle & approval | **PRODUCT** | Consequential, hash-bound decision; conventional (1) and utility (1). Any expression lowers trust. |
| D Agent workspace | **PRODUCT** | Experimental interaction (6 = 3) is *functional* novelty for interruptible agents, not expression (7 = 2, brand 1). New patterns are allowed; expressive treatment isn't. |
| E Fleet & assets | **PRODUCT** | Comparison and drill-in; all axes at or near the product pole. |
| F Records & review | **PRODUCT** | Ledgers and inbox; all axes at or near the product pole. |
| G Analytics & impact | **PRODUCT** | Narrative 3 is about *traceable* numbers; charts must be honest and conventional (6 = 1). The narrative is carried by provenance, not by expressive design. |
| H Configuration & account | **PRODUCT** | Occasional but purely utility. |
| I Guided Demo | **HYBRID** | Narrative (5), outsider audience (9 = 4) and one-off use (5) pull toward expression, but it *is* the real product (6 = 2, zero component forks). It may carry a thin, removable storytelling layer and nothing more. |

No surface is EXPRESSIVE. The only candidate would be a public landing or marketing page, which
doesn't exist in the repository (see §9).

---

## 9. Uncertainties and questions the repository can't answer

1. **PRISM Theme 5, Stage 3.** `docs/PRISM_RUNTIME.md` and `README.md` say multimodal grounding, a
   model-backed Fast Path and the "final interruption UX" are unfinished. The modality (voice,
   camera, image upload from a technician on the floor) is not specified. If Stage 3 adds
   floor-side or mobile input, D (axes 6 and 8) and possibly C would move.
2. **Mobile or remote approval.** Is the maintenance approver expected to approve from a phone or
   tablet away from the desk? The UI currently permits it but can't show the binding legibly at
   390 px. The answer decides C's responsive rules.
3. **Control-room or wall display.** Is B shown on a large shared display (read-only, viewed from a
   distance)? No evidence either way. It would change B's typography and density rules.
4. **Real fleet scale.** The demo has 8 assets (`core/seed_data.py`). A real plant may have tens or
   hundreds; the fleet strip on B and the navigation of E depend on scale.
5. **Concurrency.** How many simultaneous incidents does one approver handle? The live simulator
   staged four at once; B's triage rules depend on the realistic number.
6. **Role differentiation.** Roles are presentation only. Will Observer lose Approve/Reject, and will
   the operator and engineer get different landing pages or densities?
7. **Analytics horizon.** Analytics is generation-scoped today. Is persistent, long-horizon history
   planned? That would move G back toward exploratory and occasional (axes 1 and 2).
8. **Public landing page.** Is a public page for the hosted demo intended, or is `/login` the only
   public face? A landing page would be the only EXPRESSIVE candidate.
9. **Guided Demo affordances.** May the Guided Demo gain presentation-only aids (step captions,
   "what just happened" annotations) inside the product, as §5-I permits in principle? Or must it
   stay the unmodified product with only the top-bar status?
10. **Demo pacing.** The live run reached the hold point in about 18 s, but the README documents
    about 42 s. Is the faster pacing intended? It affects how much the demo can rely on a viewer
    catching transitions.
11. **Brand constraints.** Must the current wordmark, `docs/banner.svg`, the "Autonomous Reliability
    Operations for Industrial Systems" tagline (required by `OPERON_ARCHITECTURE.md` "Operon
    branding and exact tagline") or dark-as-default survive into later phases?
12. **Working conditions.** Nothing in the repository covers gloves or touch-only use, bright
    shop-floor light, colour-vision requirements, localisation or units. All would affect later
    rules.
13. **Notifications durability.** Notifications are browser-only today. If they become server-side
    and pushed (for example, to phones), F's mobile score changes.
