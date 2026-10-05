# OPERON V2: Naming due diligence

Status: research and naming strategy only. Nothing has been renamed. No logos or assets were made,
and no repository settings were changed.

**This is not legal advice.** It records facts and practical branding risk. Matters needing a
trademark professional are listed in §9.

Foundation: Phase 2.5 brand strategy (`03-brand-strategy-and-identity.md`, commit `a55a64b`),
which flagged the collision (§0, decision D-N1).

**Method:**
- 8 research passes on 2026-10-05: competitor + trademark; discoverability + namespaces; four
  candidate-screening batches covering 36 names; repository audit by `git grep`.
- Evidence levels:
  - **DIRECT**: queried or read first-hand (npm / PyPI registries, DNS, GitHub search via the
    session's GitHub tool, repository files).
  - **SNIPPET**: a search-engine summary of a page.
  - **SECONDARY**: third-party aggregator.
- Most primary sites were blocked by the session's egress proxy, including ycombinator.com,
  operonsolutions.com, the USPTO TSDR API, uspto.report, EUIPO / TMview, IP India and UKIPO. Many
  facts are therefore SNIPPET and must be re-verified by a person with normal web access.

---

## Executive summary

- **Collision severity: VERY HIGH.** A Y Combinator S26 company called **Operon** sells into
  process and manufacturing plants. It has a **predictive-maintenance product** that predicts
  failures for pumps, compressors and valves and does **"automatic work order generation in your
  CMMS"**, alongside an "agentic data layer". That is the same buyer, the same plant users, and
  overlapping functions under an identical name. It already supplies the top answer for "Operon
  predictive maintenance" and ranks #1 for "Operon manufacturing AI".
- **Discoverability: very poor.**
  - "Operon" is a textbook genetics term.
  - "Operon AI" is fragmented across 6+ active projects, plus Anthropic's reported "Claude Operon"
    biology mode.
  - npm `operon`, the npm `@operon` scope, PyPI `operon` and PyPI `operon-ai` are taken, as are all
    the obvious domains.
  - The one query we can realistically own is **"Operon reliability"**, where our repository
    already ranks #2.
- **Trademarks:**
  - A **pending** US application for **OPERON** in **class 42** (SaaS advisory) by Operon LLC,
    Hampton VA (serial 99703517; SNIPPET).
  - A **registered** OPERON for synthetic DNA (Eurofins).
  - No OPERON software or industrial marks found in India, EU or UK, but the official databases
    were unreachable.
- **Renaming cost: low at the presentation level, high if done deep.** User-visible text lives in
  about 20 files. The deep identifiers (policy versions, provenance boundaries, protocol IDs,
  migration names, 35 environment variables) are persisted and hash-bound and should **never** be
  renamed. Keep `operon` as the internal codename, as Chromium does for Chrome.
- **The alternatives are not clean either.** 36 candidates were screened. Dictionary words and
  "hold / govern / verify" metaphors are being claimed in 2025–26 by AI-agent governance startups
  (Holdpoint, Governor, Trunnion, Bollard, Stanchion, Countersign, Proofline, Keel). The best
  candidates are **MODERATE** risk, not LOW.
- **Recommendation: KEEP TEMPORARILY, PLAN RENAME.**
  - Keep "Operon" as the working name and internal codename now. The submitted generation on
    `main` keeps it permanently.
  - Do **not** produce final identity assets, a public README rebrand, or launch materials under
    "Operon".
  - Choose the V2 product name (from the finalists below or a focused coined-name round) and obtain
    a professional knockout search **before** Phase 4 (shipping visible identity).
  - Phase 3 can proceed name-agnostic.

---

## 1. The competing Operon

### 1.1 Facts

| Item | Finding | Evidence |
|---|---|---|
| Name | **Operon**; also "Operon Solutions" on GitHub, LinkedIn and Caplight. Legal entity name **unverified** | SNIPPET (YC, site, LinkedIn) |
| Website | operonsolutions.com ("Operon — The Context Layer for Process & Manufacturing") | SNIPPET |
| Y Combinator | **Summer 2026 (S26)**, status Active, San Francisco; YC tagline "Agentic data layer for manufacturing & process industries" | SNIPPET (ycombinator.com/companies/operon) |
| Age | Founded 2026; job post (~mid-2026) says "four months old and YC-backed" | SNIPPET |
| Founder(s) | Anderson Chen (Founder / CEO), from Taiwan. GitHub bio: "Co-Founder @ Operon Solutions, AI for Chemical Engineering". Team includes an ML Ops engineer (Eddie Wang, "Operon (YC S26)") | DIRECT (github.com/anderson120912091209); SNIPPET |
| Funding | Caplight: accelerator round 2026-05-29, **$530k** total, est. valuation $1.79M (SECONDARY). Another summary states "$700k pre-seed" (SNIPPET). Taiwanese press: NT$1M grant (Jamie Lin gap-year programme) and investment by Nova Studio (SNIPPET). **Amounts unverified / conflicting** | SECONDARY / SNIPPET |
| Activity | Active: hiring a Founding FDE ($100–150k + 0.2–1.0 % equity, US); blog posts (e.g. "From 2,400 Legacy P&IDs to Structured Data in a Weekend"); press claims of 300+ trial requests in 72 h after a LinkedIn demo | SNIPPET |
| Positioning (quotes) | <ul><li>"reads the documents your plant runs on — P&IDs, isometrics, line lists, compliance records — and turns them into one live, queryable context layer for search, compliance, and AI agents".</li><li>"data intelligence layer for heavy industry… engineers query their plant in natural language and build agentic workflows for safety, compliance, and design".</li></ul> | SNIPPET |
| Industrial focus | Refineries, chemical plants, power facilities; process and manufacturing plant engineers; on-site forward-deployed engineers | SNIPPET |
| **Predictive maintenance** | Docs page: "Operon's Predictive Maintenance uses machine learning models trained on your actual equipment data to predict failures days or weeks before they occur."<ul><li>Data sources: PI, IP.21, DeltaV, Honeywell PHD, CSI, Bently Nevada, SKF, DCS / SCADA and CMMS history.</li><li>Per-asset models for pumps, compressors, turbines, fans, heat exchangers, vessels and valves.</li><li>Anomaly detection and RUL.</li><li>**"automatic work order generation in your CMMS"**.</li><li>Claimed: >92 % accuracy, 14-day lead time, <5 % false positives.</li></ul> | SNIPPET (operonsolutions.com/en/docs/predictive-maintenance) |
| Agent claims | "Agentic data layer", "context layer for AI agents", CAD / P&ID AI agent | SNIPPET |
| Customers | No named customers or logos found; one blog references an unnamed petrochemical refinery | SNIPPET |
| Markets | US go-to-market; Taiwan / Singapore roots | SNIPPET |
| Open source / social | No product repository found; founder GitHub has 16 followers; LinkedIn company page exists; no Launch HN or Product Hunt found | DIRECT / SNIPPET |
| Search visibility | #1 for "Operon manufacturing AI" (YC page); supplies the answer for "Operon predictive maintenance"; not yet visible for "Operon AI" or "Operon industrial AI" | SNIPPET |

### 1.2 Their Operon vs our Operon

| Dimension | THEIR Operon (YC S26) | OUR Operon (DyausG/operon) |
|---|---|---|
| Category | Industrial data / context layer + agentic workflows + predictive-maintenance module | Governed reliability-operations workflow |
| Buyer | Plant owner-operators (refining, chemicals, power); engineering leadership | Plant reliability and maintenance leadership |
| User | Process / plant engineers; maintenance via the PdM module | Reliability engineers, maintenance approvers, technicians, operators |
| Industry | Process and manufacturing (heavy industry) | Industrial plants (manufacturing / process) |
| Problem | Knowledge trapped in P&IDs and documents; compliance; unplanned failures | Turning failure-risk signals into decided, executed, verified maintenance |
| AI / agent positioning | "Agentic data layer", natural-language plant queries, P&ID agent | Advisory multi-agent investigation (supervisor, specialists, critic) |
| Predictive maintenance | **Yes**: ML on historian, vibration and DCS data; RUL | **Yes**: ML failure-risk scoring |
| Reliability | Downtime-reduction claims | Core purpose |
| Workflows | Search, compliance, design, MOC, PdM → CMMS work orders | Evidence → diagnosis → plan → approval → execution → verification |
| Human approval | Not stated | Explicit, hash-bound approval of the exact work package |
| Execution | "Automatic work order generation in your CMMS" | Governed execution via CMMS adapters |
| Verification | Not found | Verified recovery from post-intervention data |
| Deployment | Cloud and on-prem, APIs / SDK, on-site engineers | Open-source, self-hosted / container |
| Business model | VC-backed enterprise SaaS + services | Open-source portfolio / hackathon project (pre-commercial) |

### 1.3 Collision severity: **VERY HIGH**

Reasons:
- An identical word, used in the **same vertical**, for **overlapping buyers and users**.
- **Overlapping functions:** ML predictive maintenance, agentic AI, and CMMS work-order creation.
- The competitor is **funded, active, and already ranks** for the exact queries we would need.

Operon's real differentiators (governed approval, verified recovery, open source) are invisible at
the level of a name. A plant engineer hearing "Operon, the industrial AI that predicts failures and
raises work orders" cannot tell the two apart.

### 1.4 Other "Operon" entities (context)

| Entity | Relevance | Evidence |
|---|---|---|
| operonos.com: "Operon OS — The Operating System for Agentic AI Governance" (deny-by-default, human-in-the-loop approval, signed audit) | **Conceptually very close to our governance pitch** | SNIPPET |
| operonhq.ai / useoperon.com: "AI Workforce Operating System" (DLB Technologies LLC, Norfolk VA); approval flows | AI agents | SNIPPET |
| operonhq.com: "Operon – AI Built Like Biology" (consultancy) | AI | SNIPPET |
| PyPI `operon-ai`: "Biomimetic wiring diagrams for robust agentic systems" (active 2026-07) | AI agents, package namespace | DIRECT |
| Anthropic "Claude Operon": reported biology-research mode (leaked March 2026); Claude Science launched 2026-06-30 | Would dominate "Operon AI" search if the name is used publicly | SNIPPET |
| Operon Group Oy (Finland): water / wastewater operator with the OperonWay data / AI platform | Industrial-adjacent | SNIPPET |
| Operon E2I LLC (California, AI / web); operon-app.com (home services OS); operon-solutions.com (government contracting) | Software | SNIPPET |
| Eurofins Genomics (operon.com, ex-Operon Biotechnologies); Operon S.A. (Spain, diagnostics, since 1973); Polish educational publisher Operon; GATC Health Operon™ | Life science / other | SNIPPET |
| Industrial hardware, PLC or robotics "Operon" | None found | SNIPPET |

---

## 2. Trademark findings (facts only)

| Mark | Owner / applicant | Serial (Reg. no.) | Filed | Status | Class | Goods / services | Jurisdiction | Evidence |
|---|---|---|---|---|---|---|---|---|
| **OPERON** (standard characters) | Operon LLC, Hampton, Virginia | **99703517** | 2026-03-15 | **PENDING**: intent-to-use; "new application awaiting assignment to an examining attorney" at last snippet | **42** | "information and advisory services relating to software as a service (SAAS)" | US | SNIPPET (uspto.report) |
| OPERON (logo) | Operon LLC (same) | 99703518 | ~2026-03-15 | PENDING (per snippet) | 42 (per snippet) | Same wording | US | SNIPPET (trademarkelite) |
| OPERON | Eurofins Genomics, LLC | 78564911 (Reg. 3076207) | 2005-02-10 | **REGISTERED** (renewed 2016) | Chemical / research | Synthetic DNA for research | US | SNIPPET (justia) |
| OPERON | Eurofins Genomics, LLC | 78564908 | 2005-02-10 | **UNVERIFIED** | — | Synthetic DNA | US | SNIPPET |
| OPERON MOLECULES FOR LIFE | Operon Biotechnologies, Inc. | 78564901 (Reg. 3079122) | 2005 | **ABANDONED / DEAD** (cancelled §8, 2012) | Chemical | — | US | SNIPPET |
| EUROFINS MWG OPERON | Eurofins Scientific Ireland Ltd | 79128743 (Reg. 4718489) | — | **DEAD** (cancelled 2022) | incl. computer / scientific | — | US | SNIPPET |
| OPERON | Operon Ventures LLC | 86450362 | 2014-11-11 | **ABANDONED** (no Statement of Use, 2017) | 36 | Venture capital | US | SNIPPET |
| OPERON | (medical furniture owner) | 76258222 (Reg. 2703771) | 2001 | Registered and renewed 2013; **current status UNVERIFIED** | 10 | Medical procedure furniture | US | SNIPPET |
| (any OPERON in software / industrial classes) | — | — | — | **None found** (official databases unreachable, so "none found" ≠ "none exists") | 7, 9, 37, 42 | — | India, EU, UK | SNIPPET |

Additional observations:
- **No trademark filing by the YC company was found.** That does not mean it has no rights:
  **use-based (common-law) rights** may exist from commercial use.
- Operon LLC (Hampton VA) and DLB Technologies (Norfolk VA, operonhq.ai) are geographically close;
  any connection is **unverified**.

**Practical branding risk (not a legal conclusion):**
- A **pending class 42 SaaS filing**, plus an **active, funded company using the identical name in
  our vertical**, means any future commercial use, trademark filing, domain purchase or fundraising
  under "Operon" would need professional clearance first.
- There is a non-trivial chance of having to rename later, at a higher cost (after public launch,
  assets and accumulated recognition).

---

## 3. Search / discoverability audit

| Surface | Findings | Evidence |
|---|---|---|
| Web: "Operon" | Genetics dominates (8 of the top 9: ScienceDirect, PMC, bioRxiv, MCAT, IDT…) | SNIPPET |
| Web: "Operon AI" | Fragmented: swaruplab/operon (bioinformatics IDE), PyPI operon-ai, operonhq.ai, GATC Health Operon™, Claude Operon coverage | SNIPPET |
| Web: "Operon industrial AI" | No single owner; Operon Solutions and Operon OS adjacent | SNIPPET |
| Web: "Operon predictive maintenance" | **Operon Solutions' PdM docs page is the answer source** | SNIPPET |
| Web: "Operon reliability" | Biology papers, but **DyausG/operon ranks #2** | SNIPPET |
| Web: "Operon manufacturing AI" | **YC Operon page #1**; operonsolutions.com twice in the top 9 | SNIPPET |
| GitHub | **432** repos with "operon" in the name; 94 user / org logins contain it; `github.com/operon` and `operon-io` taken. Top repos: hasanyilmaz/operon (245★), heal-research/operon (222★), swaruplab/operon (99★), coredipper/operon (bio-inspired agent control, topics include "reliability"). Ours: 1★, no description or topics set | DIRECT |
| npm | `operon` taken (dormant); **`@operon` scope taken** (ad-network SDK, 2026); `operon-ai`, `operon-reliability`, `operon-ops` free; other Operon AI-agent packages exist (`@operon-sdk/*`, `operon-agents*`, `operon-mcp`) | DIRECT |
| PyPI | `operon` taken (dormant 2018); `pyoperon` taken; **`operon-ai` taken (active AI-agent package)**; `operon-reliability`, `operon-ops` free | DIRECT |
| Social | No @operon / @operon_ai found on X via search (unconfirmed); LinkedIn has several Operon companies (labs, medical devices, Finnish utility operator); YouTube dominated by a Polish publisher and Claude Operon videos | SNIPPET |
| Domains | operon.com, .ai, .io, .dev, .tech, .app, .co, .systems, operonhq.*, operon-ai.com, getoperon.com, useoperon.com all **resolve** (registered / in use). `operon.industries` and `operonreliability.com` did not resolve (availability unconfirmed) | DIRECT (DNS) |

**Difficulty of owning each query:**

| Query | Difficulty | Reason |
|---|---|---|
| Operon | **Very hard** | Textbook genetics plus legacy biotech brands |
| Operon AI | **Very hard** | 6+ active "Operon AI" projects; Claude Operon coverage |
| Operon industrial AI | **Hard** | No owner yet, but the YC company and Operon OS are adjacent |
| Operon predictive maintenance | **Hard, and a direct conflict** | Competitor already owns the answer |
| Operon reliability | **Feasible** | Already #2; no commercial rival |
| Operon manufacturing AI | **Very hard** | YC company #1 |

---

## 4. Cost of keeping the name

| Cost | Assessment |
|---|---|
| Search confusion | Severe for every query except "Operon reliability" |
| Recruiter / employer confusion | High: "Operon, industrial AI, YC" will be read as the YC company; portfolio attribution blurred |
| Hackathon / project confusion | Moderate: judges searching "Operon AI" find others; the repo has no description or topics yet |
| GitHub discoverability | Poor: 432 same-name repos |
| Package naming | Bare names and the `@operon` scope are taken; qualified names (`operon-reliability`) still free |
| Domains | All primary domains taken |
| Future commercialisation | **Blocked pending professional clearance** (pending class 42 mark; same-vertical common-law user) |
| Open-source recognition | Diluted by bio-inspired and agent projects with the same name |
| Word of mouth | "Operon, the industrial AI startup" → wrong company |
| Trademark / legal review burden | High and recurring |
| Visual differentiation burden | High: must look unlike two "agent governance" Operons and an industrial-AI Operon at once |

| Benefit of keeping | Assessment |
|---|---|
| Existing repository and history | Real but small (created 2026-09-09; 1★ / 1 fork) |
| Recognition accumulated | Limited to hackathon submissions and reviewers; tied to the submitted generation, which keeps the name regardless |
| Relevance of the word | Good: "a coordinated unit under an operator's control" (Phase 2.5 §5) |
| Screenshots / submissions / docs | Submissions are frozen (immutable, on `main`); V2 has no public assets yet |
| Migration cost | Low now at the presentation level (§5); grows after Phase 4 assets and any public launch |

---

## 5. Cost of renaming now (audit; nothing changed)

Repository totals:

| Measure | Value |
|---|---|
| Tracked files | 296 |
| Files containing "operon" (excluding lockfiles and `frontend/dist`) | **137** |
| Occurrences | ≈ **1,833** (`operon` 1,064; `Operon` 401; `OPERON` 368) |
| Occurrences in `frontend/dist` | 45 (regenerated by the build) |
| Paths containing the name | `core/migrations/001_operon.sql`, `core/prism/operon.py`, `docs/OPERON_ARCHITECTURE.md` |

| Category | What exists | Rename? |
|---|---|---|
| **Repository name** | `DyausG/operon` | Optional (GitHub redirects renamed repos; local remotes, Render service and links need updating). Not required for a product rename |
| **Application-visible strings** | <ul><li>Backend `APP_NAME = "Operon"` and `APP_TAGLINE` (`core/config.py:23-24`).</li><li>~15 frontend files: wordmark (`AppShell.jsx:92`), document titles, LoginPage, `routes.js` "Operon Agent", AgentPage, Settings, Profile, Inspector "Operon application", ConnectionBanner, ProviderSettings copy.</li><li>`frontend/index.html` title.</li></ul> | **Yes**: the presentation layer, ≈ 20 files |
| **Package / module names** | <ul><li>`pyproject.toml` `name = "operon"`; `frontend/package.json` `operon-frontend`.</li><li>Python module `core/prism/operon.py`; identifiers such as `OperonSlowPathAdapter`, `operon_run_id`, `InvokeAndStopOperonRuntime` (~30 identifiers).</li></ul> | Keep (internal codename); optionally rename the distribution name only |
| **Environment variables** | **35** `OPERON_*` variables (e.g. `OPERON_AI_PROVIDER`, `OPERON_REASONING_BACKEND`, `OPERON_TRUSTED_SUBMISSIONS`) | Keep; optionally add new-prefix aliases later |
| **Database / schema identifiers** | <ul><li>Migration `001_operon.sql`: the ledger keys on the filename stem, so renaming would re-run it.</li><li>Persisted provenance and boundary strings in hash-bound artifacts: `operon.application.promotion` (164 occurrences), `operon.application.outcome`, `operon.application.lifecycle`, `operon.confirm_mechanism`, `operon.investigation`, source system `operon.sqlite`.</li><li>Policy versions `operon-promotion-1`, `operon-lifecycle-1`, `operon-outcome-1`, `operon-freshness-1`, `operon-evidence-v1`.</li></ul> | **Never**: changing them breaks hashes, audit continuity and migrations |
| **APIs** | No REST path contains the name (verified). Remote reasoning protocol `operon-reasoning-1` and session prefix `operon-run-` (AgentCore wire contract) | Keep protocol IDs |
| **Docs** | README + 9 docs files (≈ 154 occurrences); design docs (≈ 206, historical record) | Update product-facing docs; leave design history |
| **Screenshots / images** | Only `docs/banner.svg` (text "Operon") | Replace with new identity later (already planned for retirement) |
| **Tests** | 25 files, 151 occurrences (mostly internal identifiers and persisted strings) | Mostly unaffected; a few UI-string assertions in the frontend smoke test |
| **URLs** | No hard-coded repository or domain URLs in tracked files (verified) | — |
| **Configuration** | `.env.example` (`OPERON_*`), `demo.sh` / `run.bat` text, `render.yaml` service name `agentic-predictive-maintenance` (doesn't use the name) | Text only |
| **Browser storage keys** | `operon.theme`, `operon.session`, `operon.settings`, `operon.sidebar`, `operon.notifications.read` | Keep (a rename would reset users' local preferences) |
| **GitHub metadata** | No description, topics, homepage or social preview currently set | Free to set for any name |

**Conclusion:** the name is **deeply embedded technically**, but in identifiers that are not
user-facing and must stay stable anyway. A **presentation-level rename** is straightforward, with
`operon` retained as the internal codename (as Chromium is for Chrome, or many products'
repository names):
- ≈ 20 product files;
- product docs and README;
- the wordmark;
- an optional repository / distribution rename.

Estimated effort: about a day of focused work plus a docs pass. It should happen **once**, with the
Phase 4 identity, not twice.

---

## 6. Alternative names

### 6.1 Longlist (60+ candidates, by strategy)

Elimination marks:
- **‡** screened in this phase (results §7);
- **×** eliminated at longlist stage for a known collision or meaning problem (general knowledge,
  not researched further);
- **·** not screened.

| Strategy | Candidates |
|---|---|
| Real words: structure / stability | Keel‡, Keelson‡, Holdfast‡, Staunch‡, Lintel‡, Stanchion‡, Corbel‡, Bollard‡, Mooring‡, Cleat‡, Plinth×, Bulwark×, Keystone×, Linchpin× |
| Adapted technical / mechanical terms | Escapement‡, Detent‡, Collet‡, Tenon‡, Trunnion‡, Clevis‡, Sprag‡, Capstan‡, Interlock‡, Governor‡, Pawl·, Windlass·, Gimbal×, Spindle×, Gantry×, Trestle×, Truss×, Arbor×, Fulcrum×, Torque× |
| Proof / verification | Witness‡, Holdpoint‡, Countersign‡, Proofline‡, Plumb‡, Plumbline‡, Assay× (biology / lab), Attest·, Verity×, Hallmark×, Signoff×, Proofmark× (firearms proofing), Checkpoint× (security), Ratify· |
| Continuity / operation | Throughline‡, Holdline‡, Sureline‡, Mainspring× (Mainspring Energy), Flywheel×, Cadence× (EDA), Perennial×, Uptime×, Durance× |
| Signal / action | Telltale‡, Semaphore× (CI product), Relay×, Beacon×, Actuate× (BI), Tripwire× (security), Sightline× (monitoring vendor), Lodestar× |
| Reliability / guardianship | Vigil‡, Datum‡, Cairn‡, Forthright‡, Truebearing‡, Closeout‡, Sentinel× (overused; this project's own legacy env prefix), Steward×, Warden×, Bedrock× (AWS Bedrock, used by this product), Upkeep× (CMMS), Corrigo× (JLL CMMS), Fathom×, Kestrel× (instruments), Meridian×, Tenable×, Ledger×, Arbiter×, Verdict× |
| Invented / adapted | Operant× (psychology term), Operix× (X-suffix), Provenor· (suffix-generated feel), Recova· (generic), Truset· |

### 6.2 Systemic finding

Across 36 screened names, **every dictionary word that expresses holding, governing, verifying or
supporting** is already used by 2025–26 **AI-agent governance or approval tools**, or by industrial
companies. Examples:
- Holdpoint (inspection sign-off apps; agent approval queues)
- Governor (Credo AI Agent Governor; "AI proposes. Humans approve.")
- Trunnion AI (governed multi-agent, human-in-the-loop, manufacturing)
- Bollard AI, Stanchion AI, Countersign, Proofline, Keel (control plane for "approval of the exact
  agent action")

OPERON's thesis is now a crowded naming territory. A truly clean name will most likely be a
**coined, ownable word** (developed in a dedicated naming round with professional clearance),
rather than another metaphor from this vocabulary.

---

## 7. Screening results

All preliminary (not trademark clearance). npm / PyPI / DNS / GitHub DIRECT; companies SNIPPET.

| Name | Key collisions found | npm | PyPI | .com / .ai / .io | Pronunciation | Undesirable | Risk |
|---|---|---|---|---|---|---|---|
| **Truebearing** | mercator-hq/truebearing (tiny "permissions and guardrails for agentic products", holds PyPI); Bearing AI (maritime AI, different name); small non-software "True Bearing" firms | **free** | taken | .com, .ai registered; .io no DNS | Clear; one word vs "True Bearing" | May read as bearing-specific monitoring | **MODERATE** |
| **Detent** | detent.ai "Proof-Carrying AI"; PyPI `detent` (AI-agent verification runtime); small agent-orchestration project; no industrial / maintenance company | **free** | taken | all registered | de-TENT / DEE-tent; "détente" confusion | Spanish "¡detente!" = "stop!" (apt); Portuguese "detento" (inmate) close | **MODERATE** |
| **Holdfast** | HoldFast AI (contractor dispatch, small); archived observability project; Australian maintenance service firms; PyPI `holdfast` "governed evolution for prompts"; *Holdfast* video game dominates GitHub | taken | taken | all registered | Clear | Positive ("hold fast") | **MODERATE** |
| **Keelson** | RISE-Maritime/keelson (open maritime SDK, holds PyPI); marine inspection / resin firms; small agent-governance repos | stub (unpublished) | taken | all registered | KEEL-sun vs KEL-sun; obscure | Reads as a surname | **MODERATE** |
| **Holdline** | No software company; Holdline Ltd (UK machinery wholesale); small 2026 agent "approval gate" repos | **free** | **free** | all registered | Clear | Telephone "on hold" | **MODERATE** |
| Lintel | uselintel.com (construction-drawing AI); Indian IT firm; "lint" (linter) association | taken | taken | .com / .io no DNS; .ai registered | LIN-tl; "lentil" | Developer "lint" reading | MODERATE |
| Staunch | Small dev shop and industrial firms; common adjective | taken | free | all registered | stawnch / stahnch | Hard to own; "stench" mishearing | MODERATE |
| Escapement | AI-safety "escapements" project; agent orchestration npm | taken | taken | all registered | Misspelled often | **"Escape"** contradicts governance | MODERATE |
| Collet | Sound-alike "Collate" (funded AI data governance); machining-tool results | taken | taken | all registered | Poor (collate / Colette) | French "collet" = snare | MODERATE |
| Forthright | Forthright Technology Partners owns .com (IT services to manufacturers, "AI operationalisation") | free | taken | all registered | "th" hard internationally | Generic adjective | MODERATE |
| Clevis, Sprag, Tenon, Plumb, Closeout, Plumbline, Throughline, Telltale, Countersign, Cleat, Mooring, Sureline | Various established software marks or AI-agent tools (see notes) | — | — | — | — | — | HIGH |
| Holdpoint, Witness, Governor, Interlock, Keel, Vigil, Cairn, Datum, Trunnion, Capstan, Bollard, Stanchion, Corbel, Proofline | Direct AI-governance or industrial collisions (WitnessAI $85.5M; Interlock ransomware targeting manufacturing; Trunnion AI; Keel control plane; Corbel industrial AI; …) | — | — | — | — | — | VERY HIGH |

### Top 10

Truebearing · Detent · Holdfast · Keelson · Holdline · Lintel · Staunch · Escapement · Collet ·
Forthright

### Top 5

Truebearing · Detent · Holdfast · Keelson · Holdline

### Top 3 with scoring (1–5; for collision risk, 5 = least risk), compared with Operon

| Criterion | **Truebearing** | **Detent** | **Holdfast** | *Operon (baseline)* |
|---|---|---|---|---|
| Distinctiveness | 4 | 4 | 3 | 2 |
| Industrial credibility | 4 (bearings, true running, navigation) | 4 (mechanical detent) | 4 (workholding clamp) | 3 |
| Product fit | 4: reliability + direction; risk of sounding bearing-only | **5**: "held until deliberately released" = human decision before action | 4: holds securely; steadfast operation | 4: coordinated unit under an operator |
| Memorability | 4 | 4 | 4 | 4 |
| Pronunciation / spelling | 4 (compound split) | 3 (stress; "détente") | 5 | 4 |
| Searchability | 3 | 3 (SwiftUI "detents") | 2 (video game) | **1** |
| Expandability (beyond PdM) | 3 | 4 | 4 | 4 |
| Visual identity potential | **5** (compass needle × bearing ring) | 4 (notch / click) | 4 (clamp / anchor) | 3 |
| Collision risk | 3 | 3 (AI-verification cluster: detent.ai) | 3 (Australian maintenance firms; PyPI governed-AI package) | **1** |
| **Total (/45)** | **34** | **34** | **33** | **26** |

**Reading the scores:**
- All three finalists are materially better than Operon on collision and searchability (the two
  criteria that triggered this review).
- **None is clean**. Each has small same-concept projects, and none has had a trademark search.
- Detent has the best conceptual fit for the governed loop.
- Truebearing has the strongest visual potential and the fewest industrial collisions.
- Holdfast is the easiest to say and spell, but the hardest to find in search.

---

## 8. Recommendation: **KEEP TEMPORARILY, PLAN RENAME**

Decision rationale:

1. **Keeping Operon long-term is not sensible.** The collision is VERY HIGH:
   - an identical name in the same vertical;
   - an active, funded competitor that already owns the predictive-maintenance and manufacturing
     queries;
   - a pending class 42 OPERON application;
   - two "Operon" products pitching agent governance with human approval.

   Every month of public V2 identity built on it increases the cost of the inevitable change.
2. **Renaming *now* to one of these finalists would be premature.** The best alternatives are
   MODERATE risk and unscreened by a professional. Switching immediately could trade one collision
   for another and force a second rename.
3. **The rename is cheap at the presentation level** (§5) and can be done once, later, without
   touching hash-bound internals.
4. **Phase 3 doesn't need the final name.** The design system (tokens, components, semantics,
   density) is name-agnostic. Only the wordmark, logo and brand assets depend on it, and Phase 2.5
   already deferred those.

Concrete plan:

| Step | When | Scope |
|---|---|---|
| A | Now | Treat "Operon" as the **V2 working name and permanent internal codename**. The submitted generation (`main`) keeps "Operon" forever |
| B | Now | Do **not** produce final logos, public README rebrand, domains, social handles or launch materials under "Operon" |
| C | Before Phase 4 | Product owner shortlists 2–3 names: the finalists above and/or a focused **coined-name round**, given §6.2. Obtain a **professional knockout search** (US classes 9, 42, 37, 7; India; EU / UK) and check domain / handle availability with a registrar |
| D | With Phase 4 identity | Execute the presentation-level rename in one change: user-visible strings, docs, README, wordmark, optional repository / distribution rename. Internal `operon` identifiers, environment variables, policy / provenance strings and protocol IDs stay |
| E | Interim | If public visibility is needed before D, use the qualified descriptor "Operon Reliability" and set GitHub topics. Avoid "Operon AI" and "Operon industrial AI" phrasing |

Phase 2.5 visual exploration: run the name-independent concept families (Governed Loop, Step-signal
Path, Governed Unit) and pause the Instrument-O family (name-dependent) until the name is decided.

---

## 9. Facts still requiring professional or legal verification

1. Current TSDR status of US **99703517** / **99703518** (examiner assignment, office actions,
   publication, abandonment), full identification of services, and any added classes.
2. Identity of **Operon LLC** (Hampton VA) and any relationship to DLB Technologies (operonhq.ai).
3. The YC company's legal entity, any trademark filings (US, Taiwan or elsewhere), and the extent of
   its **use-based rights**.
4. Full knockout searches for OPERON **and each finalist** in US classes 7, 9, 37, 42; **India**
   (IP India, classes 9 and 42); EUIPO / TMview; UKIPO.
5. Questions requiring a trademark attorney:
   - likelihood of confusion;
   - priority (intent-to-use vs prior use);
   - whether open-source, non-commercial use constitutes use in commerce;
   - filing strategy if commercialisation is planned.
6. Domain and social-handle availability at registrars and platforms; DNS non-resolution here is not
   proof of availability.
7. Competitor funding amounts ($530k vs $700k: conflicting secondary sources), named customers,
   team size.
8. Whether Anthropic's "Claude Operon" naming is public product branding (it affects "Operon AI"
   discoverability, not trademark analysis for our classes).

---

## 10. Sources

All accessed 2026-10-05. Evidence: D = DIRECT, S = SNIPPET, SEC = SECONDARY.

### Competitor

| Source | Evidence |
|---|---|
| ycombinator.com/companies/operon (+ /jobs/w7qf3HJ-founding-fde) | S |
| operonsolutions.com/en, /en/about, /en/blog, /en/docs/predictive-maintenance, /en/docs/pid-agent | S |
| caplight.com/company/operonsolutions; sota2.com/companies/operon-solutions | SEC |
| github.com/anderson120912091209 | D |
| medium.com/@andersonchen_2095 | S |
| bnext.com.tw/article/90932/…; udn.com/news/story/6841/9653594; cw.com.tw/article/5142005; cryptocity.tw/news/taiwan-genz-ai-startup-operon-enters-yc | S |
| vibecrowd.ai/launches/operon | S |

### Other Operon entities

| Source | Evidence |
|---|---|
| operonos.com; operonhq.ai/about; useoperon.com; operonhq.com; getoperon.com; operon.so/developers; operonapp.dev; operone2i.com; operon-app.com; operongroup.fi/en; operondx.com; gatchealth.com/operon-platform; eurofins.com/media-centre/press-releases-2014/2014-04-02 | S |
| testingcatalog.com/anthropic-tests-claude-operon-for-scientific-research-in-biology/; news.northeastern.edu/2026/06/30/anthropic-claude-science-launch/ | S |

### Trademarks

| Source | Evidence |
|---|---|
| uspto.report/TM/99703517; trademarkelite.com/trademark/trademark-detail/99703518/logo; trademark.justia.com/785/64/operon-78564911.html; trademarks.justia.com/864/50/operon-86450362.html; trademarkia.com/operon-molecules-for-life-78564901; trademarkia.com/eurofins-mwg-operon-79128743 | S |

### Discoverability

| Source | Evidence |
|---|---|
| WebSearch result orderings for the six queries in §3 | S |
| GitHub repository and user search (432 repos; 94 logins); github.com/DyausG/operon; npm registry (`operon`, `@operon/*`, `operon-ai`, `operon-reliability`, `operon-ops`); PyPI JSON (`operon`, `pyoperon`, `operon-ai`, `operon-reliability`, `operon-ops`); DNS lookups for 15 domains | D |
| en.wikipedia.org/wiki/Operon; khanacademy.org lac operon; sciencedirect.com operon topics | S |

### Candidate screening

| Source | Evidence |
|---|---|
| npm / PyPI / DNS / GitHub queries for all 36 candidates | D |
| Company and product evidence (selected): witness.ai; Lanner WITNESS; holdpoint.co; ELAS Holdpoint; Credo AI Agent Governor; Governor Technologies; Interlock ransomware reporting; interlock-us.com; trunnion.ai; bollardai.com; stanchionai.com; capstan.so; Corbel (Axios / PR Newswire seed coverage); Corbel Systems; keelapi.com; Keel Solution; detent.ai; holdfastai.com; Tenon (tenonhq); Tenon Group FM; uselintel.com; cleat.ai; SMW Autoblok Proofline®; peerpush.com/p/proofline; Sunhillo SureLine®; Sureline Systems; Thruline; ThroughLine Care; Telltale Games; countersign.com; countersign.network; Bearing AI; mercator-hq/truebearing; Forthright Technology Partners; Collate; SDT Vigilant; datum.co; Autodesk Datum; Cairn Oil & Gas | S |

### Repository audit

| Source | Evidence |
|---|---|
| `git grep` over `overhaul/v2` at `a55a64b` (counts, categories, file paths cited in §5) | D |
