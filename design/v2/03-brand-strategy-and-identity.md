# OPERON V2: Brand strategy & identity (Phase 2.5)

Status: Phase 2.5 brand strategy. No frontend, CSS, README or asset changes. **No final logo is
declared.** §22 contains visual exploration briefs for review before any selection.

Accepted foundations:

| Phase | Document | Notes |
|---|---|---|
| 0 | [`design/mode.md`](../mode.md) | |
| 1 | [`01-product-model-and-information-architecture.md`](01-product-model-and-information-architecture.md) | |
| 2 | [`02-product-ux-reference-research.md`](02-product-ux-reference-research.md) | Commit `023b54a`; Governed Operations Workbench accepted as the interaction foundation |

Carried-forward product decisions (from the product owner):
- **Case** (not Incident) in user-facing V2 terminology; backend stays `incident`.
- Navigation: My actions · Cases · Assets · Work orders · Reliability · Audit log · System.
- Technicians are direct users.
- Mobile approval only where the full binding, consequences and evidence are legible.
- Reject is never an opaque dead end.
- Photo / evidence attachments desired (backend capability required).
- Deliberate friction is acceptable for consequential approvals.
- A wall display is not the primary surface.
- Gaps G1–G12 preserved, none implemented.

Evidence levels used for external claims: **DIRECT** (source read), **SNIPPET** (search summary of a
source), **SECONDARY** (third party). Computed values (contrast, colour distance, CVD) were produced in
this phase with a scratch tool (WCAG 2.x contrast; OKLab ΔE ×100; Machado–Oliveira–Fernandes 2009 CVD
simulation) and the categorical-palette validator of the data-visualisation method used in Phase 2.

---

## 0. Headline findings that shape everything below

1. **The name needs a decision before final identity assets are produced.** A Y Combinator–backed
   company called **Operon** (`operonsolutions.com`) sells an *"agentic data layer for manufacturing
   & process industries"*, with predictive maintenance as a stated use case (SNIPPET). That is the
   same buyers and the same agent narrative. A **pending US trademark application for OPERON**
   (serial 99703517, class 42 SaaS, filed 2026-03-15) also exists (SNIPPET). Separately:
   - search results for "operon" are dominated by biology;
   - ≈ 432 GitHub repositories contain "operon" (DIRECT count);
   - npm `operon` and PyPI `Operon` are taken (DIRECT).

   This is **not legal advice**. It is a serious branding and discoverability issue worth counsel
   review. The strategy below is written so that most of it survives a rename (§5, §23).
2. **OPERON's current brand colours collide with its own status semantics:**
   - The app's teal `#2FA39A` sits ΔE 8 from the "verified" green.
   - The README banner's amber `#F5A524` is essentially the warning amber.

   **Both are retired** by this strategy.
3. **Blue / teal is the industrial-software category colour:** Siemens Petrol, GE Vernova "Blue
   Stone" `#015E60`, Cognite, IBM, MaintainX navy. A deep petrol candidate tested here measured
   **ΔE 3** from GE Vernova's teal, effectively identical. Every chromatic hue not occupied by
   OPERON's status semantics is either claimed by a competitor or collapses into a status hue for
   colour-vision-deficient users.
4. **Therefore: OPERON's brand is ink and paper. Colour belongs to the plant's operational state.**
   This is the ISA-101 principle (grey is normal; colour means abnormal) extended from the product
   into the brand. It is also open white space in the category.

---

## 1. Brand foundation

| Element | Definition |
|---|---|
| **Category** | **Reliability operations software for industrial plants.** It sits between condition monitoring / APM (which stops at a prediction) and CMMS (which starts at a work order). Avoid "Industrial AI platform", the most overused phrase in the category (§4). |
| **Target users** | Plant reliability and maintenance teams: control-room operators, reliability engineers, maintenance supervisors / approvers, technicians, reliability managers, system administrators (Phase 1 §5). Evaluators are secondary. |
| **Primary value proposition** | Operon turns an early warning into a **verified recovery**: it collects the evidence, investigates with advisory agents, asks a person to decide on the exact work, and proves the fix worked. |
| **Product promise** | **Nothing executes without an explicit human decision. Nothing closes without evidence that it worked.** |
| **Differentiators** | <ol><li>**Carries through:** the loop continues past prediction to execution and verification (most products stop at an alert or a recommendation).</li><li>**Governed autonomy:** agents advise, the application owns authority, a person approves the exact, hash-bound work package.</li><li>**Evidence and provenance:** every conclusion cites evidence; advisory, authoritative, trusted, human and simulated records stay distinguishable.</li><li>**Honest uncertainty:** "inconclusive" is a legitimate answer; no fabricated reasoning, no fake live metrics.</li><li>**Built for plant roles, technicians included.**</li></ol> |
| **Personality** | Precise · calm · accountable · candid · quietly capable. A good instrument or an experienced reliability engineer: says what it knows, shows how it knows, and doesn't raise its voice unless something is wrong. |
| **Emotional qualities** | Control (I know what's happening and what's waiting on me) · trust (I can check why) · composure (normal stays quiet) · closure (the loop is finished, and proven). |
| **Must NOT project** | <ul><li>AI hype or omniscience.</li><li>Sci-fi / cyberpunk futurism.</li><li>"Autonomous" in the sense of *replacing* people.</li><li>Militaristic or defence-tech coldness.</li><li>Playfulness or cuteness.</li><li>Alarmism.</li><li>Opacity.</li><li>Biotech (accidental, given the name).</li><li>Hackathon-demo energy.</li></ul> |

**Brand idea, in one line: *carried through, and proven.*** Operon takes intelligence all the way
from a machine signal to a verified operational result, under human authority, with a record.

---

## 2. Positioning

**Positioning statement.** *For plant reliability and maintenance teams who must act on predictive
signals safely, Operon is reliability operations software that carries each early warning through
evidence, investigation and an explicit human decision to a verified recovery. Monitoring tools
and AI assistants stop at a prediction or a suggestion.*

**Where Operon sits:**

| Category | Typically ends at | Operon |
|---|---|---|
| Condition monitoring / APM (Augury, SmartSignal, Senseye) | Alert, health score, recommendation | Continues to decision, execution, verification |
| CMMS (Maximo Manage, MaintainX, Fiix) | Work order executed / closed | Starts earlier (signal + investigation) and closes only on verified recovery |
| AI copilots (Industrial Copilot, chat assistants) | An answer | Produces evidence-bound artifacts; never executes without approval |

---

## 3. Messaging

| Use | Copy |
|---|---|
| **One-line positioning** | Operon carries an early warning through to a verified recovery: evidence, investigation, a human decision, and proof the fix worked. |
| **Short description** (≈ 25 words) | Reliability operations software for industrial plants. Operon investigates predictive signals with advisory agents, asks a person to approve the exact work, and verifies recovery. |
| **Medium description** (≈ 70 words) | Operon watches plant assets for early signs of failure. When risk crosses the action gate it opens a case, gathers evidence, and runs specialist agents that propose and challenge hypotheses, all advisory. The application, not the model, promotes a diagnosis and a plan. A maintenance approver decides on the exact work package; execution is receipted, and the case closes only when post-repair data proves the asset recovered. Every step is on the record. |
| **GitHub repository description** (≤ 350 characters; limit SNIPPET) | `Reliability operations for industrial plants: predictive signals → evidence → advisory agent investigation → human approval of the exact work package → execution → verified recovery. Runs offline in a deterministic mode; Gemini, Ollama or Bedrock optional.` (≈ 255 characters) |
| **Website / README hero** | **From early warning to verified recovery.** Operon investigates equipment risk with advisory agents, puts the decision in human hands, and closes a case only when the data proves the fix worked. |
| **Concise pitch** (≈ 45 s) | Predictive maintenance tells you a machine might fail. Then what? Someone has to work out why, plan the work, decide whether to commit people, parts and downtime, and check afterwards that it actually helped. Operon carries that whole loop. Agents investigate and challenge each other's conclusions, but they only advise. A person approves the exact work package. Operon verifies recovery from post-repair data before it closes the case. |
| **Technical descriptor** (optional) | Governed agentic reliability operations: ML risk detection, Strands specialist agents (advisory), hash-bound human approval, receipted execution and outcome verification over a journaled lifecycle. |
| **Manifesto line** (internal / presentations) | Agents investigate. People decide. Nothing closes without proof. |

Vocabulary to own (unclaimed in the category per research): **verified recovery, evidence, exact
work package, decision, on the record, carried through.**

Vocabulary to avoid (overused; research §4): Industrial AI, AI-powered, unlock, unleash, empower,
transform, reinvent, smart factory, frontline, autonomous (contradicts human authority), "operate
smarter" (Samsara), platform (as the headline).

---

## 4. Tagline exploration

Scores 1–5 on seven criteria:

| Code | Criterion |
|---|---|
| D | Distinctiveness |
| M | Memorability |
| Cr | Credibility |
| R | Relation to Operon's loop |
| I | Industrial relevance |
| L | Longevity |
| A | Avoidance of AI clichés |

| # | Candidate | D | M | Cr | R | I | L | A | Σ | Note |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **From early warning to verified recovery.** | 4 | 4 | 5 | 5 | 5 | 5 | 5 | **33** | Plant language at both ends; "verified recovery" is Operon's literal closure rule and unclaimed |
| 2 | **Nothing closes without proof.** | 5 | 5 | 4 | 4 | 3 | 5 | 5 | **31** | Strong as a secondary line or manifesto; needs context alone |
| 3 | From machine signal to verified action. | 3 | 3 | 4 | 5 | 4 | 4 | 5 | 28 | Accurate; "action" is abstract |
| 4 | Evidence first. Human decision. Verified result. | 4 | 3 | 5 | 5 | 4 | 4 | 5 | 30 | Explains the model; three-beat structure is common |
| 5 | **Reliability, carried through.** | 4 | 4 | 4 | 4 | 4 | 5 | 5 | **30** | Elegant; borrows from "carried through" without "intelligence" |
| 6 | Industrial intelligence, carried through. | 3 | 3 | 3 | 4 | 4 | 4 | 2 | 23 | "Industrial intelligence" is AVEVA / Seeq territory |
| 7 | Intelligence that keeps industry moving. | 1 | 2 | 2 | 2 | 3 | 3 | 2 | 15 | Generic |
| 8 | Close the loop on every failure. | 3 | 4 | 3 | 4 | 4 | 4 | 4 | 26 | Control-engineering resonance; "close the loop" is a business cliché |
| 9 | Predict. Decide. Verify. | 2 | 4 | 3 | 4 | 3 | 4 | 4 | 24 | Clear but generic triad |
| 10 | Every fix, verified. | 4 | 4 | 3 | 4 | 4 | 4 | 5 | 28 | Short; "fix" narrows scope (inspections, non-repairs) |
| 11 | Autonomy you can sign off. | 4 | 4 | 3 | 4 | 2 | 3 | 3 | 23 | Clever; leans on "autonomy" |
| 12 | Signals in. Verified fixes out. | 4 | 4 | 3 | 4 | 3 | 3 | 5 | 26 | Mechanical; slightly glib |
| 13 | Where predictions become proven repairs. | 3 | 3 | 4 | 4 | 4 | 4 | 5 | 27 | Clear; soft verb |
| 14 | Machine intelligence. Human authority. Verified outcomes. | 3 | 2 | 4 | 5 | 3 | 4 | 3 | 24 | Long |
| 15 | Reliability with a record. | 4 | 3 | 4 | 3 | 3 | 5 | 5 | 27 | Accountability angle; undersells action |
| 16 | Find it early. Fix it right. Prove it worked. | 3 | 4 | 4 | 5 | 5 | 4 | 5 | 30 | Very plant-native; long for a lock-up |
| 17 | Governed autonomy for industrial reliability. | 3 | 2 | 4 | 4 | 4 | 4 | 3 | 24 | Better as descriptor than tagline |
| 18 | The decision stays human. | 4 | 4 | 4 | 3 | 2 | 5 | 5 | 27 | Values line; omits detection and verification |
| 19 | Early warning, carried to proof. | 4 | 3 | 4 | 5 | 4 | 4 | 5 | 29 | Compact variant of #1 |

**Top five:**
1. *From early warning to verified recovery.*
2. *Nothing closes without proof.*
3. *Reliability, carried through.*
4. *Find it early. Fix it right. Prove it worked.*
5. *Evidence first. Human decision. Verified result.*

**Recommendation:**

| Role | Line |
|---|---|
| **Primary tagline** | **From early warning to verified recovery.** |
| **Secondary descriptor** (lock-ups, GitHub, slides) | **Governed reliability operations for industrial plants.** |
| **Supporting line** (manifesto, README section header, closing slide) | *Nothing closes without proof.* |

---

## 5. Naming rules

**Meaning (research):** *operon* was coined by Jacob & Monod (1960–61). The French *opéron* comes
from *opérer*, "to bring about, effect". It names a group of genes whose expression is
**coordinated by an operator** (a regulatory switch) and transcribed from one promoter
(DIRECT / SNIPPET: Merriam-Webster, Wikidata, ScienceDirect).

The metaphor is apt and can be used **verbally**:

| Operon (biology) | OPERON (product) |
|---|---|
| A coordinated unit of action | A case |
| Held "off" by default | No execution without approval |
| Switched on by evidence (the inducer) | Evidence lifts the block |

**Visually, biology is off-limits:**
- no DNA helices;
- no gene maps (a horizontal row of boxes with a start arrow, which also resembles workflow
  diagrams, so pipeline graphics must not look like that);
- no plasmid circles;
- no molecular blobs.

At least one AI-agent project already uses the same biology metaphor (`coredipper/operon`; arXiv
2607.04240; SNIPPET / DIRECT), another reason to keep it out of the visuals.

**Case and form:**

| Context | Treatment | Rationale |
|---|---|---|
| Logotype / wordmark | **OPERON**, capitals, custom-tuned spacing | Industrial nameplate character; distinct from prose |
| Prose, docs, UI copy, README text | **Operon** (title case) | It is a word, not an acronym; capitals in running text read as an acronym or as shouting |
| Application chrome (window title, nav) | Logo in the shell; textual references "Operon" | Product name, not a heading |
| Pronunciation | /ˈɒp-ə-rɒn/ ("OP-er-on") (Merriam-Webster, SNIPPET) | |
| GitHub repository | `operon` (current); see decision D-N3 | Renaming a repo keeps redirects but breaks clones' remotes |
| Packages / modules | Qualified names, e.g. `operon-reliability`, `@operon-reliability/*` | npm `operon` and PyPI `Operon` are taken (DIRECT) |
| Discoverability lock-up | **OPERON** + descriptor "Reliability Operations" | Biology dominates search; a fixed qualifier helps |
| Never | "Operon AI", "Operon OS" (both in use by others, SNIPPET); "OPERON" in running prose; "Operon-powered" | |

**Name risk:** as stated in §0, flagged for product-owner and counsel decision (D-N1). Logo families
1, 3 and 4 below are name-independent; family 2 (Instrument O) depends on the letter O.

---

## 6. Identity territories

Three required territories plus one considered and set aside.

### A. Industrial Precision: "the instrument and the drawing sheet"

| Aspect | Description |
|---|---|
| Central idea | Operon behaves like a precision instrument and documents like an engineering drawing: exact, calibrated, legible, nothing decorative. |
| Mood | Calm, exact, trustworthy, quiet until something matters |
| Logo families | Governed loop with hold point; Instrument O (ISA-5.1-inspired bubble); stepped signal path |
| Typography | A rational grotesk with technical detail (IBM Plex Sans family; width axis for nameplate-style headings) + monospace for tags and identifiers |
| Colour | Ink + paper + graphite neutrals; **no brand hue**; colour only from operational state and real photography |
| Graphic language | Drawing-sheet grids, title blocks, tag numbers (`AC-COMP-01`), revision marks, 1 px hairlines, 90° / 45° geometry, dimension-line motifs |
| Imagery | Real maintenance detail photography (hands, tools, bearings, probes, lock-out tags), technical diagrams, product UI |
| Strengths | Credible to engineers; unmistakably not "AI glow"; perfectly aligned with ISA-101 and with the product's colour discipline; ages slowly |
| Weaknesses | Can feel austere or cold; monochrome risks reading as defence tech (Anduril / Palantir) |
| Generic risk | Low for colour; medium for grotesk typography (needs a distinctive mark and graphic system) |
| Workbench fit | Excellent: the product *is* this territory (quiet band, typed record, precise binding) |

### B. Autonomous Operations: "the orchestrated flow"

| Aspect | Description |
|---|---|
| Central idea | Operon orchestrates a continuous flow from signal to action; motion and paths are the identity. |
| Mood | Dynamic, modern, confident, forward |
| Logo families | Continuous path / orbit; flowing signal ribbon; node-to-node route |
| Typography | Geometric sans (e.g. Geist / Space Grotesk character) |
| Colour | Deep night field + one electric signal hue (cobalt / ultramarine) + white |
| Graphic language | Curved paths, gradients along routes, animated flow lines, rounded geometry |
| Imagery | Abstract flow graphics, product UI, light trails |
| Strengths | Communicates "agentic" activity; attractive in presentations and social previews |
| Weaknesses | **Category-blue** (≈ Cognite / IBM); cobalt sits in the "active / executing" status hue; "autonomous" contradicts human authority; flow lines easily become the generic network-node cliché |
| Generic risk | **High** |
| Workbench fit | Poor: encourages motion and colour in operational surfaces that must stay quiet |

### C. Industrial Intelligence: "the evidence and the record"

| Aspect | Description |
|---|---|
| Central idea | Operon is the trustworthy record of how a reliability decision was reached: evidence, reasoning artifacts, decision, proof. |
| Mood | Considered, accountable, thorough, editorial |
| Logo families | Governed unit (brackets / regulated unit); verification seal or stamp; case-file mark |
| Typography | Editorial pairing: a humanist sans or restrained serif display + sans text + mono for references |
| Colour | Warm paper, ink, and a material accent (bronze / umber) |
| Graphic language | Stamps, seals, revision tables, annotated photographs, margin notes, citation markers |
| Imagery | Evidence close-ups, annotated inspection photos, documents |
| Strengths | Owns *evidence* and *accountability* (unclaimed in the category); strong for approvers and managers |
| Weaknesses | Can feel archival, legal or slow; less "operational"; the bronze accent collapses into status hues for CVD users at any useful lightness (§10) |
| Generic risk | Medium (editorial-tech is a recognisable style) |
| Workbench fit | Good inside the case (evidence, record); weak for the live plant band |

### (Considered) D. Field & Material: "the worksite"

High-visibility colour, rugged materials, frontline photography. **Set aside:** Samsara's July 2026
rebrand claims this (high-vis yellow, "built with operators"; SNIPPET), and high-vis colours collide
with warning amber.

---

## 7. Recommended territory

**A deliberate hybrid: "Instrument & Record."** Territory A is the base; territory C supplies the
evidence and verification vocabulary; territory B contributes only its *signal path* as a line
motif, never its colour or gradients.

| From | Take | Leave |
|---|---|---|
| **A: Industrial Precision** | Ink / paper / graphite colour; rational grotesk + mono; drawing-sheet grid, tags, hairlines; mark families 1–3 | — |
| **C: Industrial Intelligence** | Evidence marks, revision and verification motifs (as *graphic language*, e.g. "verified" seal in brand materials only), annotated photography, accountable voice | Bronze accent in the product; serif display |
| **B: Autonomous Operations** | The continuous *signal path* as a single-weight line connecting stages in diagrams and covers | Electric colour, gradients, glow, curved flow cliché |

**Why:**
- It is the only direction whose colour behaviour matches the product's safety semantics.
- It occupies category white space.
- It speaks directly to Operon's differentiator: carried through (path), governed (hold point),
  proven (record).

The cold / defence-tech risk is mitigated by:
- warm paper rather than stark white;
- real, human maintenance photography with natural colour;
- a calm, plain voice.

---

## 8. Logo strategy

### 8.1 Concept families

Feasibility of core geometry was checked with throwaway sketches rendered at 16 / 24 / 32 / 64 /
128 px on light and dark (scratch only, not committed, not proposals).

| # | Family | Idea | 16 px feasibility (sketch) | Risks | Keep? |
|---|---|---|---|---|---|
| 1 | **Governed Loop** | A loop path (rounded-square, instrument-like) carrying the signal around; the loop is completed only through a **hold point** (a gate bar or break) and terminates in a verified state | Readable; crude version read as an abstract "G" | "G" reading; generic-O ring if circular | **Yes** (primary candidate) |
| 2 | **Instrument O** | Built on the ISA-5.1 instrument bubble (a circle, with a division line for location); the line becomes the signal that stops at a decision point | Very readable | Can read as a one-eyed face, a power/toggle symbol or Ø; depends on the name's O | **Yes** (with caution) |
| 3 | **Step-signal Path** | The signal as a *step function* (state transitions), not a heartbeat spike, ending in a square terminal = committed, verified action | Readable | The ECG/heartbeat version reads as medical: must use orthogonal steps | **Yes** |
| 4 | **Governed Unit** | Brackets (the operator / governance) enclosing a solid unit (the case / action); the word "operon" means a regulated unit | Very readable | Reads as code / selection / "stop" button; generic dev-tool risk | **Exploratory** |
| 5 | Isolation / spectacle blind | P&ID symbol of positive isolation (open + closed discs): "safe to work" | Not sketched | Reads as glasses / infinity; niche | Optional only |
| ✗ | State-step bars | Ascending blocks to a terminal | Read as phone signal strength | Cliché | **Rejected** |
| ✗ | Clichés per brief | Robot heads, brains, circuit brains, hexagons, network nodes, gears, factory silhouettes, generic O rings, infinity, lightning; **plus** DNA / gene-map shapes | — | — | **Rejected** |

The **current app mark** (a ring with one coloured arc, `frontend/src/styles/shell.css:6`) is a
generic O ring and is retired.

### 8.2 System to produce after selection (not now)

| Element | Specification |
|---|---|
| Symbol | Solid / geometric, own corner logic, built on a 48-unit grid; minimum 16 px (with a dedicated simplified favicon drawing) |
| Wordmark | **OPERON** capitals, derived from the chosen type family but **custom-adjusted** (spacing, the O, R leg, N diagonals) so it isn't simply typed IBM Plex |
| Horizontal lockup | Symbol + wordmark; optional descriptor line "Reliability Operations" |
| Stacked lockup | Only if the symbol is roughly square and used on covers / app splash |
| Variants | Ink on paper (light), paper on ink (dark), single-colour monochrome (black, white), knockout |
| Favicon | Symbol only, hand-hinted at 16 / 32; SVG + PNG |
| Application icon | Symbol on a solid ink square (dark) or paper square (light), no gradient |
| Clear space | ≥ the width of the wordmark's "O" stroke × 4 around the lockup; ≥ 25 % of symbol width around the symbol |
| Distinctness from UI icons | Never drawn as a 24 px / 2 px-stroke outline glyph; never uses status shapes (octagon, triangle, diamond) or status colours; never placed in icon slots |

---

## 9. Typography candidates

Verified from font files (OpenType tables, cmap, licence files), rendered specimens at 11 / 13 / 16 px
on dark and light, and package metadata. All candidates are licensed under the SIL OFL 1.1.

**Reserved Font Names (RFN) matter for shipping.** A self-made subset is a modified version and must
not carry an RFN. For RFN families, ship vendor or fontsource files unchanged.

| RFN status | Families |
|---|---|
| RFN | **Plex**, **Source**, **Fira**, **Mona**, **Hubot** |
| Ambiguous | **Red Hat** (repo `LICENSE` vs `OFL.txt` conflict) |
| No RFN | Inter, Geist, JetBrains Mono, Atkinson, Public Sans, Archivo, Space Grotesk, Instrument, Barlow, Roboto, Noto |

**A packaging finding with real consequences:** fontsource / Google Fonts builds **strip most
OpenType features**:
- Inter's fontsource build lacks `zero`, `ss02` and the `cv*` sets.
- IBM's own `@ibm/plex-*` split WOFF2 files keep `zero` and `ss01–ss05`.
- Inter's official variable subset keeps everything.

| System | UI sans | Display | Mono | Verified strengths | Verified weaknesses |
|---|---|---|---|---|---|
| **1. IBM Plex (consolidated)** | IBM Plex Sans **variable** (wght 100–700, **wdth 75–100**; width 75 reproduces Plex Condensed exactly) | Same family at narrower width / heavier weight | IBM Plex Mono | <ul><li>**Clearest default 1 / l / I** among neutral sans faces (specimen).</li><li>0 visibly narrower than O.</li><li>**Tabular figures by default** (all digit advances equal).</li><li>Full Latin / Ext / Greek / Cyrillic / Vietnamese; complete technical symbols.</li><li>IBM-maintained (published 2026-09-29).</li><li>One 64 KB variable file replaces five static files (current ≈ 140 KB total).</li><li>Continuity with today's app.</li></ul> | <ul><li>RFN "Plex" (ship IBM / fontsource files unmodified).</li><li>No `tnum` feature (not needed).</li><li>**Association with IBM / Maximo (Carbon)**, mitigated by a custom wordmark and Operon's own graphic system.</li></ul> |
| 2. Inter + JetBrains Mono | Inter 4.1 variable (wght, opsz) | Inter Display (opsz 32) | JetBrains Mono | <ul><li>No RFN.</li><li>Huge glyph set.</li><li>`ss02` disambiguation exists in the official build.</li><li>JetBrains Mono most legible mono at 11 px.</li></ul> | <ul><li>**l = I by default** (needs `ss02` and the official 97 KB build).</li><li>Proportional figures by default.</li><li>Inter Display merges "rn" → "m" at 11 px (display only).</li><li>Ubiquitous SaaS look.</li></ul> |
| 3. Geist + Geist Mono | Geist variable | Geist | Geist Mono | <ul><li>Contemporary.</li><li>Slashed zero in mono by default.</li><li>No RFN.</li></ul> | <ul><li>l / I ambiguous by default.</li><li>No Greek / Vietnamese.</li><li>Strong Vercel / dev-tool association.</li></ul> |
| 4. Atkinson Hyperlegible Next + Mono | Atkinson Next | — | Atkinson Mono | <ul><li>Best out-of-box disambiguation (slashed 0, distinct 1 l I).</li><li>No RFN.</li></ul> | <ul><li>Latin only.</li><li>Missing → ↑ ↓ µ.</li><li>Humanist / accessibility character, least industrial.</li><li>Uneven spacing.</li></ul> |
| 5. Archivo + Plex / JetBrains Mono | Archivo (wght, **wdth 62–125**) | Archivo extended / condensed | Plex Mono or JetBrains Mono | <ul><li>Single family spans condensed to extended for display.</li><li>No RFN.</li></ul> | <ul><li>l / I ambiguous.</li><li>Not tabular by default.</li><li>Condensed widths cramp "rn" at 11 px.</li></ul> |

**Recommendation: System 1 (IBM Plex, consolidated)** for UI, brand display and mono. Use the width
axis for nameplate-style display and condensed headers. For data surfaces needing a slashed zero,
self-host IBM's own split WOFF2 files, which keep the features.

**Alternative:** System 2 (Inter official build + JetBrains Mono) if the IBM association is judged
too strong (decision D-T1).

Fallback stacks (System 1; family names verified in fontsource CSS):

```css
--font-ui:   "IBM Plex Sans Variable", "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
--font-cond: "IBM Plex Sans Variable", "IBM Plex Sans Condensed", "Roboto Condensed", "Arial Narrow", system-ui, sans-serif; /* with font-stretch: 75% */
--font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, "Liberation Mono", monospace;
```

Rules carried to Phase 3:
- Use U+2212 (−) for minus in numeric contexts.
- Numeric cells use `tabular-nums` (harmless where figures are already tabular).
- Identifiers and hashes are always mono.
- Never set running text in condensed widths below 13 px.

---

## 10. Colour architecture

**Brand colour and operational colour are separate systems.** Brand colour never carries operational
meaning; operational colour is never used decoratively.

### 10.1 Candidates tested and rejected

| Candidate | Result | Why rejected |
|---|---|---|
| Current app teal `#2FA39A` | ΔE 8.1 from verified green; CVD ΔE 7.8 | Reads as "verified" |
| README banner amber `#F5A524` | ≈ warning amber | Functional colour used as decoration |
| Deep petrol `#255A6B` | **ΔE 3 from GE Vernova Blue Stone**; Siemens' brand colour is "Petrol" | Not distinctive; category blue-green |
| Cobalt `#3D5AFE` | ΔE 17 from active blue; CVD 13 from decision violet | Category blue; status adjacency |
| Bronze ramp (`#4A3418` … `#D6C3A3`) | Only the darkest step stays clear of status hues under CVD (ΔE 12); mid steps collapse with critical / verified (CVD ΔE 1–3) | Unusable in product; optional for print only |
| Signal orange, lime, magenta | Collide with critical, warning or watch, or with AVEVA purple | Status or competitor collision |

A full search of OKLCH space for colours far from both the status set and competitor brand colours
found only very dark oxide, umber and olive regions:
- oxide reads as "red / danger";
- olive reads as military;
- umber is the bronze above.

### 10.2 Brand palette (proposed)

| Role | Name | HEX | RGB | HSL | OKLCH | Usage |
|---|---|---|---|---|---|---|
| Primary | **Ink** | `#0C1418` | rgb(12, 20, 24) | hsl(200, 33 %, 7 %) | oklch(0.19 0.015 230) | Wordmark and mark on light; dark brand fields; print text |
| Primary | **Paper** | `#F3F4F1` | rgb(243, 244, 241) | hsl(80, 12 %, 95 %) | oklch(0.97 0.004 122) | Light brand fields; mark and wordmark on dark; README / social backgrounds |
| Secondary (neutral family) | **Graphite** ramp | see §11 | | | oklch(L 0.008 222) | Lines, grids, secondary text, diagram strokes |
| Supporting neutral | **Steel** | `#81878A` | rgb(129, 135, 138) | hsl(200, 4 %, 52 %) | oklch(0.62 0.008 229) | Diagram secondary strokes, captions on dark |
| Accent | **None chromatic.** The accent is *form*: the signal-path line (Paper on Ink, Ink on Paper) | — | — | — | — | — |
| Optional (print / marketing only; decision D-C2) | **Bronze 700** | `#4A3418` | rgb(74, 52, 24) | hsl(34, 51 %, 19 %) | oklch(0.34 0.053 71) | Never in product UI; never adjacent to status colours |

Key contrast pairs (WCAG 2.x):

| Pair | Ratio |
|---|---|
| Ink on Paper | **16.85:1** |
| Paper on Ink | **16.85:1** |
| Bronze 700 on Paper | 10.59:1 |

Brand-to-status distance: Ink and Paper sit ≥ 24 ΔE (normal) and ≥ 22 ΔE (CVD) from every
status colour in both themes, so they can never be confused with a state.

---

## 11. Dark / light theme philosophy

Phase 3 converts this into tokens. Values below are proposals validated for contrast.

**Dark theme: "the instrument."** Low-glare graphite (never pure black). Elevation is lighter
surfaces, not shadows. Normal recedes into graphite; status uses bright steps. The brand appears
only as the Paper-coloured mark. Intended for control rooms and long shifts.

**Light theme: "the drawing sheet."** Paper page, white working panels, ink text. Elevation comes
from white-on-paper plus hairline borders (minimal shadow). Status uses darker, text-safe steps.
The brand appears as the Ink-coloured mark. Intended for offices, approvals, reading and printing.

**Not an inversion:** different surface logic (lighter-is-higher vs white-on-paper), different
status steps per theme, different border strengths, a warm paper page vs cool graphite page.

| Dark token (proposal) | HEX | Contrast | Light token (proposal) | HEX | Contrast |
|---|---|---|---|---|---|
| page | `#0F1415` | — | page | `#F4F5F4` | — |
| panel | `#161A1C` | — | panel | `#FFFFFF` | — |
| raised | `#1C2123` | — | sunken | `#ECEFF0` | — |
| border (decorative) | `#272C2E` | 1.24:1 vs panel | border (decorative) | `#D3D9DB` | 1.43:1 vs panel |
| border-strong | `#34393B` | 1.50:1 | border-strong | `#B5BCBE` | 1.93:1 |
| text-1 | `#E8ECEE` | **14.74:1** on panel | text-1 | `#11181B` | **17.94:1** |
| text-2 | `#B5BCBE` | **9.09:1** | text-2 | `#4E5456` | **7.70:1** |
| text-3 | `#868D90` | **5.19:1** panel / 5.50 page | text-3 | `#646B6E` | **5.43:1** panel / 4.96 page |

Phase 3 obligations:
- **Interactive control boundaries need ≥ 3:1** (WCAG 1.4.11), so form-control borders need a step
  stronger than the decorative borders above.
- The light-theme warning text step must be darkened for use on the page background (§12).

---

## 12. Semantic colour relationship

**Principle:** normal recedes; abnormal earns prominence. Severity is always **colour + shape/icon +
text**. **Five hues only**, because the research (ISA-18.2 rationing) and CVD testing both argue for
fewer hues: several pairs collapse for CVD users regardless of tuning.

| State | Hue | Shape / icon | Text | Dark step | Light step |
|---|---|---|---|---|---|
| Nominal | none (graphite text) | none / hollow dot | "Normal" | text-2 | text-2 |
| Informational | none | info-circle | "Info" | text-2 | text-2 |
| Watch | amber | **outlined** diamond | "Watch" | `#F0A23B` (outline) | `#B36200` (outline) |
| Warning | amber | **filled** triangle | "Warning" | `#F0A23B` · 8.29:1 | `#B36200` · 4.50:1 panel (darken for page) |
| Critical | red | filled octagon | "Critical" | `#F0564B` · 5.12:1 | `#C8302B` · 5.37:1 |
| Approval / decision required | violet | person-check / hand icon in a square | "Decision required" | `#A98BF5` · 6.42:1 | `#6B47CC` · 6.18:1 |
| Executing / in work | blue | progress / play icon | "In work" | `#5B9BF0` · 6.17:1 | `#2662C8` · 5.73:1 |
| Verified | green | check-circle | "Verified" | `#4CB782` · 7.01:1 | `#1F7F50` · 4.99:1 |
| Offline | none | cloud-off / plug-off | "Offline" | text-3 | text-3 |
| Stale | none, reduced emphasis | clock-history | "Stale · 14 min" | text-3 | text-3 |
| Unknown | none | question-circle, dashed outline | "Unknown" | text-3 | text-3 |

**CVD findings driving the mandatory shape + text rule** (ΔE under the worse of protan / deutan):
- active blue ↔ decision violet: 1.9 (dark) / 0.6 (light);
- warning ↔ watch as separate hues: 3.7 (hence the shared hue, distinguished by fill and shape);
- critical ↔ verified: 7.2 (dark).

**Conceptual token separation** (Phase 3 implements):

| Family | Carries | Rules |
|---|---|---|
| **Brand** | Identity (Ink, Paper, optional Bronze 700) | Logo and brand channels only; never status |
| **Neutral** | Surfaces, text, borders, normal data | The default for everything; normal = neutral |
| **Operational status** | Condition and lifecycle state (the five hues + neutral states) | Always with shape and text; never decorative |
| **Attention** | Urgency ordering (Action required › At risk › Watch › Info) | Expressed by **position, weight, grouping and the status of the underlying item**, not by new hues |
| **Provenance** | Authoritative / advisory / trusted input / human / simulated | **Line style and labels** (solid, dashed, hatched, tags), not hues; hatching reserved for simulated |
| **Data visualisation** | Series, thresholds, bands, markers | Neutral series by default; thresholds borrow status colours with labels; categorical slots only in status-free charts (§15) |

---

## 13. Graphic language

**Character: instrument-like and architectural, controlled.** Not mechanical-skeuomorphic; not
computational-neon.

| Element | Rule |
|---|---|
| Geometry | Orthogonal; 45° only where a direction change needs it; circles only for instrument / status semantics |
| Line weight | Brand graphics: one primary line weight (signal path) + one hairline (grids, dimensions). Product: 1 px hairlines |
| Corners / radii | Small and consistent (product 2–4 px; brand frames 0–2 px). No pill-shaped containers except tags |
| Borders | Hairlines define structure; shadows only for overlays (light theme) |
| Grid | 8-unit base with 4-unit subdivisions; brand layouts on a visible or implied drawing-sheet grid |
| Spacing character | Generous around decisions and headlines, tight inside tables. Calm, not airy |
| Panels | Flat surfaces separated by hairlines or value steps, not floating cards |
| Technical diagrams | Engineering-drawing style: monochrome strokes, tag labels in mono, a title block (name, revision, date), state nodes as small squares, transitions as straight segments |
| Signal / path motif | One continuous line passing through the lifecycle stages (signal → case → evidence → investigation → decision → work → verification), with a **hold point** (gap or bar) at the decision. Never glowing, never gradient |
| Patterns / textures | Brand: fine dot-grid or drawing grid on covers only. Product: **hatching is reserved for SIMULATED provenance** and must not be used decoratively anywhere |
| Illustration | No characters, robots or isometric factories. Diagrams instead |
| Photography / machine imagery | §18 |
| Data graphics | §15 |

Explicitly avoid:
- cyberpunk / HUD overlays;
- scanning beams;
- particle networks;
- glows;
- glassmorphism;
- gradient meshes;
- DNA or gene-map shapes;
- workflow diagrams drawn as a horizontal row of boxes with a start arrow.

---

## 14. Iconography

Verified from package tarballs.

| Library | Licence (from file) | Icons | Grid / style | Industrial coverage | Verdict |
|---|---|---|---|---|---|
| **Tabler** (`@tabler/icons@3.49.0`) | MIT | 5,184 outline + 1,054 filled | 24 px, 2 px round stroke | Best among stroke sets: engine, circuit-motor, gauge, temperature, pipeline, tank, cylinder, windmill, radar, building-factory, robot, signature, clipboard-check; full outline and filled status shapes (circle, triangle, octagon, diamond, square, hexagon) | **Primary** |
| Lucide (`lucide-static@1.52.0`) | ISC | 2,130 | 24 px, 2 px round stroke (same geometry) | robot-arm, factory, inspection-panel, fan | **Supplement** (drop-in compatible) |
| Material Symbols | Apache-2.0 | 3,927 × 3 | Fill-based, 960 grid | valve, water_pump, conveyor_belt, precision_manufacturing, sensors | Reference / restyle only (keep NOTICE) |
| Carbon | Apache-2.0 | ~2,766 | Fill, 32 px | Good semantic set | Not primary (IBM look; fill style) |
| Siemens iX icons | MIT | 1,097 | Fill, mostly 512 | Plant / PLC / maintenance shapes | Reference only (Siemens visual identity) |
| Phosphor / Iconoir / Heroicons / Fluent | MIT | — | — | Weaker industrial coverage or stale | Not selected |
| **Remix Icon ≥ 4.9.0** | **Remix Icon License v1.0** (changed 2026-01-27; forbids use in logos and competing icon sets; not OSI) | — | — | — | **Avoid** (≤ 4.8.0 was Apache-2.0) |

**System rules:**

| Topic | Rule |
|---|---|
| Stroke / fill | **Outline (2 px) by default**; **filled** variants only for status shapes and selected-state navigation |
| Default size | 16 px in dense UI, 20 px in navigation, 24 px for primary actions and mobile; strokes scale with the icon (no hairline icons below 16 px) |
| Status overlays | A small filled status shape (8–10 px) at the bottom-right of an asset or case icon, always paired with a text label nearby |
| Asset icons | Equipment class icons from Tabler / Lucide where they exist. **Custom glyphs required** for **pump, valve, compressor, conveyor, bearing** (absent from all stroke sets), drawn on Tabler's 24 / 2 px round grid under Operon's licence |
| Action icons | Verb-specific (approve = check-square, reject = x-square, request changes = message-edit, inspect = clipboard-check, attach = camera); never an icon alone for consequential actions |
| Navigation icons | One per area; outline; filled when active |
| Semantic icons | Per §12 shapes (octagon = critical, triangle = warning, diamond = watch, check-circle = verified, person / hand = decision, progress = in work, cloud-off = offline, clock-history = stale, question = unknown) |
| Licensing | Keep MIT / ISC notices in THIRD_PARTY_NOTICES |
| Logo vs icons | The logo is never built from library glyphs, never drawn as a 24 px outline icon, never uses status shapes or colours |

---

## 15. Data-visualisation identity

Principle: **telemetry is quiet; deviations and decisions are loud, but only with labels.**

| Element | Rule |
|---|---|
| Telemetry series | Neutral (text-2 / graphite); 1.5–2 px lines; the focal series in text-1. **No categorical colour on telemetry** |
| Historical trends | Same neutral treatment; recessive gridlines and axes; one y-axis only |
| Anomaly windows | Low-opacity band in the relevant status colour, **with a text label** ("Above warning band 02:10–03:40"); never a colour-only band |
| Prediction intervals | Neutral translucent band around a dashed forecast line; labelled with the horizon and basis ("80 % interval, 7 days") |
| Thresholds | Dashed horizontal lines in the status colour (warning band, action gate), labelled at the line end with value and name |
| Baselines | Dotted neutral line labelled "Baseline (pre-intervention)" |
| Comparison series | **Focus + context:** one highlighted series, others neutral; or small multiples. When distinct identities are unavoidable (Reliability page, status-free charts only), use a *validated* categorical palette. The reference instance validated on Operon's surfaces is slots 1–3 (blue / orange / aqua): dark `#3987e5`, `#d95926`, `#199e70` pass all-pairs; light `#2a78d6`, `#eb6834`, `#1baf7a` pass with one sub-3:1 slot requiring direct labels. **These hues mean status elsewhere, so they never share a chart with status colour.** Phase 3 validates Operon's final set |
| Event markers | Vertical hairlines with a small glyph + short label: detection (signal), decision (person-check), work (wrench), observation start (eye) |
| Maintenance events | Spans for the work window; executed work in the in-work hue at low opacity with label |
| Verification | Post-intervention samples as discrete markers; outcome label ("Verified recovery: last 3 scores < 0.45") at the end of the series |
| Always | Legend for ≥ 2 series; direct labels for ≤ 4; table view available; no rainbow; no dual axes; no decorative charts |

---

## 16. Motion

**Philosophy: motion confirms change; it never performs.** Stable machinery must look stable.

| Use | Motion |
|---|---|
| State transition | Quick crossfade + 2–4 px settle (≈ 120–200 ms); the new state is fully legible at rest |
| Investigation progress | Discrete step updates (stage x of y, delegation count). No spinners for > 1 s processes; no pulsing |
| New evidence | Brief background highlight (≈ 1 s) on the new row, then rest; nothing else moves |
| Approval completion | Immediate state change + plain confirmation text; **no celebration** |
| Action execution | Progress tied to real receipts (claimed → confirmed); never an indeterminate animation implying work that isn't happening |
| Verification | Sample counter increments ("2 / 3 samples"); the outcome appears without fanfare |
| Navigation | ≤ 200 ms panel / peek transitions; no page-level flourishes |
| Brand materials | Signal-path line may draw on once (≤ 800 ms) on covers or video; never looping |

Never:
- constantly pulsing dashboards or "live" dots that pulse when nothing changes;
- scanning or sweeping effects;
- glowing AI animations;
- motion that moves the Approve button or the binding;
- auto-playing loops.

**Reduced motion** (`prefers-reduced-motion`):
- no translation or scaling;
- state changes are instant;
- highlights become a static marker ("new") that clears on interaction;
- every motion cue has a non-motion equivalent (text, icon, position).

---

## 17. Voice

**Principles:**
- **Plain:** say what happened, then what to do.
- **Technical when it helps:** values, units, thresholds, times.
- **Calm:** no exclamation marks, no alarm words without cause.
- **Honest about certainty:** "likely", "not confirmed", "inconclusive", with the basis.
- **No hype.**
- **No anthropomorphising:** agents "found", "proposed", "flagged"; they don't "think", "feel" or
  "want".
- Siemens iX's guidance holds: lead with the reason, avoid "may / might" in warnings, say what to do.

| Situation | Example |
|---|---|
| Alert | **Failure risk above action gate · AC-COMP-01.** Risk 0.86 (gate 0.80), rising for 40 min. Likely mode: power failure. A case has been opened. *Action required: none yet. Investigation is running.* |
| Recommendation | **Recommended: replace drive-end bearing (PRT-BRG ×1).** Basis: torque and power deviation since 02:10, technician inspection confirms bearing wear. Critic: accepted. Window 13:12–15:12, 50 min planned downtime, est. avoided loss $101,150. |
| Approval request | **Decision required by 15:12.** Approve the exact work package for AC-COMP-01: 1 bearing, TECH-201, 13:12–15:12. Approving commits a work order, reserves parts and notifies the technician. Package a046ef…39ab, revision 33. |
| Failed action | **Work order not confirmed.** The CMMS did not acknowledge the claim within 30 s. Nothing was dispatched. The case is waiting on a maintenance supervisor to retry or reinvestigate. |
| Verification | **Recovery verified.** The last 3 risk scores after the work (0.001, 0.001, 0.001) are below the 0.45 warning band; baseline was 0.97. Case closed. |
| Missing data | **No data from HYD-PUMP-03 for 14 min.** Condition can't be assessed; shown as Unknown, not Normal. Check the sensor link. |
| Agent investigation | **Investigation · revision 3.** Diagnostic and critic reviews complete. Leading hypothesis: bearing wear (supported by 3 evidence items, contradicted by 0). Waiting on technician inspection to confirm. |
| Escalation | **Escalated: engineering decision required.** The investigation could not reach a supported diagnosis within its limits. No work has been planned. Resolving escalations isn't available in this version (this asset can't open a new case until it is resolved). |

Avoid:
- "AI-powered insight";
- "Our AI thinks…";
- "Smart";
- "Oops";
- "Something went wrong";
- exclamation marks;
- emoji in product copy;
- capitals for emphasis.

---

## 18. Imagery

| Channel | Balance | Notes |
|---|---|---|
| GitHub social preview | Abstract brand graphic: lockup + tagline + signal-path line on Ink or Paper | Solid background (GitHub recommends solid for dark mode; DIRECT) |
| README | Product UI (real, in-context screenshot of the Case workspace) + one engineering-style architecture diagram | No stock photography |
| Website | Product UI first; real maintenance photography second; diagrams for "how it works" | — |
| Presentations | Diagrams (signal path, lifecycle), product UI, sparing photography for context | Engineering-drawing title blocks on technical slides |
| Login / marketing surfaces | Plain Ink / Paper with the lockup and one line of thesis; optional single real photograph (desaturated, not tinted) | Never a hero image that delays sign-in |

**Photography direction:**
- Real maintenance work at human scale: hands, tools, bearings, vibration probes, lock-out tags,
  inspection sheets, machine detail.
- Natural colour, neutral grading.
- Shallow depth used sparingly.
- Real wear and grime acceptable.

**Never:**
- stock wide-angle factories with blue overlays;
- HUD graphics;
- robots posing;
- glowing data streams;
- people pointing at screens;
- AI-generated "factory" images.

Photography requires licensed or original sources (decision D-I1).

---

## 19. Asset requirements (to produce after visual selection; none created now)

Location: `docs/assets/brand/`.

| Asset | Format / size | Notes |
|---|---|---|
| `operon-mark.svg` | SVG, 48-unit grid, `currentColor` | Master symbol |
| `operon-mark-light.svg` / `operon-mark-dark.svg` | SVG | Ink on light / Paper on dark |
| `operon-mark-mono-black.svg` / `-mono-white.svg` | SVG | Single colour |
| `operon-wordmark.svg` (+ light / dark / mono) | SVG | Custom-spaced OPERON |
| `operon-lockup.svg` (+ light / dark / mono) | SVG | Horizontal; optional descriptor variant `operon-lockup-descriptor.svg` |
| `operon-lockup-stacked.svg` | SVG | Only if justified by the selected mark |
| `favicon.svg` | SVG, simplified 16 px drawing | Separately drawn, not just scaled |
| `favicon.png` / `favicon.ico` | 16, 32, 48 px | Hinted |
| `apple-touch-icon.png` | 180 × 180 | Solid background |
| `app-icon.png` | 512 × 512 and 1024 × 1024; maskable variant with content inside the central 80 % safe zone | PWA / app stores |
| `operon-social-preview.png` | **1280 × 640**, < 1 MB, solid background | GitHub social preview (DIRECT) |
| `operon-readme-hero-light.png` / `-dark.png` | 1600 × 400 (2×: 3200 × 800) | Served via `<picture>` for theme |
| `operon-cover.png` | 1920 × 1080 | Presentations |
| `operon-diagram-lifecycle.svg` | SVG | Engineering-style lifecycle / signal path |
| `brand-guidelines.md` | — | Clear space, minimum sizes, misuse examples |

**Safe areas:**
- Lockup clear space ≥ 4× the wordmark stroke width on all sides.
- Symbol clear space ≥ 25 % of its width.
- Minimum symbol size 16 px (favicon drawing) / 20 px (UI).
- Minimum lockup width 96 px.
- Social preview: keep text within the central 1120 × 520 area.

---

## 20. GitHub / README identity

| Element | Direction |
|---|---|
| Repository description | §3 (≤ 350 characters) |
| Topics (≤ 20) | `reliability-engineering`, `predictive-maintenance`, `asset-performance-management`, `cmms`, `human-in-the-loop`, `ai-agents`, `industrial`, `maintenance`, `fastapi`, `react` |
| Social preview | Ink background, Paper lockup, tagline, single signal-path line; 1280 × 640 |
| README hero | Theme-aware lockup (`<picture>` light / dark), tagline, one-sentence description. **No pill row of tech logos, no gradient banner** |
| First screen | What Operon is (2 lines) · one real screenshot of the Case workspace · "Run it" (one command) · "How it works" (4-stage summary) · links to docs |
| Badges | At most 3: licence, CI status, Python version. No vanity badges |
| Logo placement | Hero only; not repeated in sections |
| Screenshot treatment | Real UI at 1440 px width, light and dark pair, neutral frame (no device mock-ups, no tilt / shadow theatre); captions state what the screen shows; simulated data labelled as such |
| Architecture diagram | Engineering-drawing style (monochrome, mono tags, title block), replacing the current Mermaid-only view for the hero (Mermaid can remain in docs) |
| Tone | Product documentation, not a hackathon write-up. Hackathon history moves to a "Project history" section with dates and submission tags (once established) |

**Retire:**
- the amber gradient banner (`docs/banner.svg`: glow, amber outline, tech-logo pills, "Segoe UI");
- the title-case "Operon" logotype in it.

---

## 21. Brand / product-system boundary

| Brand decides | Product design system decides |
|---|---|
| Name treatment, logo, lockups | Information density and layout grids |
| Type *families* (Plex) and display usage | Type *scale*, sizes, line heights for UI |
| Brand colours (Ink, Paper, Graphite character) | Semantic, status, attention and provenance colours and their steps |
| Graphic language for brand channels | Component behaviour, states, tables, controls, forms |
| Imagery and photography | Case workflows, decision surface, responsive behaviour |
| Voice principles | Product microcopy patterns per component |
| Motion philosophy | Motion tokens and component transitions |

**Where brand must yield to operational usability or safety:**
1. **Status colours always win.** No brand colour in operational content; the logo never sits inside
   a status context.
2. **Legibility wins over character.** Dense UI uses regular widths and the disambiguating features,
   not display widths.
3. **Contrast minimums win.** WCAG AA for text, 3:1 for control boundaries, in both themes.
4. **Motion restraint wins.** Product motion follows §16 even where brand materials animate.
5. **Hatching belongs to provenance.** Brand textures never use it.
6. **Plain language wins.** Taglines never appear inside the product's operational screens.

---

## 22. Visual exploration briefs (for concept boards; no selection yet)

Each brief produces one board:
- the mark at 16, 32, 128 px and hero size;
- light and dark versions;
- a wordmark and horizontal lockup;
- a favicon in a browser tab mock;
- a GitHub social preview (1280 × 640);
- a README hero;
- one product chrome crop (sidebar with mark) beside a status-heavy table, to prove no conflict.

### Brief 1: "Governed Loop" (Instrument & Record)

| Aspect | Specification |
|---|---|
| Concept | The loop is completed only through a hold point: signal → investigation → **decision gate** → verified |
| Mark geometry | Rounded-square loop (instrument bezel proportion), single uniform stroke ≈ 1/8 of mark width; the path enters at top-left, travels clockwise, and closes through a short **gate bar** set across the gap; terminal is a small solid square (committed / verified). Must not read as "G", "C", a document or a generic O ring |
| Wordmark | OPERON capitals from Plex Sans at width ~85–90, weight ~550; tracking +4 %; O optically matched to the loop's corner radius |
| Typography | IBM Plex Sans (variable) for descriptor and examples; Plex Mono for tags |
| Palette | Ink `#0C1418`, Paper `#F3F4F1`, Graphite neutrals; no hue |
| Background | Paper (light); Ink (dark); fine drawing grid only on the cover / social preview |
| Composition | Lockup left-aligned on an 8-unit grid; signal-path line runs from the mark into the layout as a single hairline |
| Must NOT appear | Gradients, glow, colour accent, infinity shapes, circular rings, DNA, arrows on the loop, status colours |

### Brief 2: "Instrument O"

| Aspect | Specification |
|---|---|
| Concept | The O of Operon as an industrial instrument bubble (ISA-5.1): the horizontal division becomes the signal, which **stops short** at a decision point |
| Mark geometry | Circle, stroke ≈ 1/9 diameter; a horizontal bar from the left edge to ~55 % of the diameter; a small square (not a dot, to avoid the "eye") at the bar's end. Test asymmetric bar heights to avoid Θ / Ø / power-symbol readings |
| Wordmark | OPERON with the first O replaced by **nothing**; the mark stands alone next to the full wordmark (no letter substitution) |
| Typography | Plex Sans width 100, weight 500; descriptor in Plex Mono uppercase small |
| Palette | Ink / Paper; optional Bronze 700 on a print cover only (for evaluation of D-C2) |
| Background | Ink and Paper variants; one variant on a P&ID-style hairline drawing (not real plant drawings) |
| Composition | Centred mark on the social preview; lockup bottom-left |
| Must NOT appear | Face / eye readings, power-button connotations, Ø diameter-symbol readings, gauges with needles, gears |

### Brief 3: "Step-signal Path"

| Aspect | Specification |
|---|---|
| Concept | A machine signal rendered as **discrete state transitions** (a step function) that resolves into a solid, committed block: signal carried through to action |
| Mark geometry | Orthogonal polyline with 3 steps of decreasing amplitude (noise → resolution), single stroke ≈ 1/10 width, ending in a solid square terminal; 90° corners only |
| Wordmark | OPERON at Plex Sans width 75–80 (nameplate feel), weight 600, tracking +8 % |
| Typography | Plex Sans condensed widths for display, regular width for text |
| Palette | Ink / Paper; the path in Paper on Ink for the hero |
| Background | Ink field with a faint drawing grid |
| Composition | The path extends horizontally across the social preview, passing a hold-point gap, ending at the lockup |
| Must NOT appear | ECG / heartbeat spikes, sine waves, signal-strength bars, arrows, lightning, gradients |

### Brief 4: "Governed Unit" (exploratory)

| Aspect | Specification |
|---|---|
| Concept | Operon as a *regulated unit*: governance (brackets / operator) enclosing a solid action unit |
| Mark geometry | Two orthogonal brackets with unequal arms (asymmetry to avoid "[ ]" code reading), enclosing a solid square offset toward the exit side; stroke ≈ 1/8 width |
| Wordmark | OPERON at Plex Sans width 100, weight 500, tracking +2 % |
| Typography | Plex Sans + Plex Mono |
| Palette | Ink / Paper |
| Background | Paper with a revision-table detail (territory C reference) |
| Composition | Mark used as a seal on a "verified" record motif in one frame (brand materials only) |
| Must NOT appear | Code / terminal connotations (`[ ]`, `{ }`, `</>`), stop-button squares alone, checkboxes |

### Brief 5: Territory comparison board (A vs B vs C, same content)

| Aspect | Specification |
|---|---|
| Purpose | Confirm the territory choice visually before a mark is picked |
| Content per territory | The same tagline, lockup placeholder (neutral text "OPERON"), one product crop, one photograph slot, one diagram |
| A | Ink / Paper / Graphite, Plex, drawing grid, real maintenance photograph |
| B | Night field + cobalt signal, geometric sans, flow lines (to make its genericness and status-colour conflict visible) |
| C | Warm paper, ink, Bronze 700, editorial pairing, annotated evidence photograph |
| Must NOT appear | Final marks (this board is about territory, not logo) |

---

## 23. Decisions requiring product-owner approval

| # | Decision | Recommendation |
|---|---|---|
| **D-N1** | **Name risk:** proceed with "Operon" (counsel review of USPTO 99703517 and the YC "Operon" in industrial agentic AI) or consider renaming before producing final assets | Commission counsel review **before** final asset production; visual exploration can proceed with name-independent marks (Briefs 1, 3, 4) |
| D-N2 | Prose casing: "Operon" in text, "OPERON" only as logotype | Approve |
| D-N3 | Repository / package naming (`operon` repo; qualified package names; descriptor lock-up "Reliability Operations") | Keep repo name; qualify packages; adopt descriptor |
| **D-B1** | Territory: **Instrument & Record** hybrid (A base + C evidence language + B signal-path line only) | Approve |
| **D-C1** | **Brand = Ink + Paper + Graphite, no chromatic brand hue**; retire teal `#2FA39A` and banner amber `#F5A524` | Approve |
| D-C2 | Optional Bronze 700 for print / marketing only | Defer until Brief 5 board is seen |
| D-C3 | Five-hue operational status model with mandatory shape + text (§12) | Approve as Phase 3 input |
| **D-T1** | Typography: IBM Plex (variable Sans + Mono) vs Inter + JetBrains Mono (if the IBM association is a concern) | Plex |
| D-I1 | Icon system: Tabler (primary) + Lucide (supplement) + 5–8 custom industrial glyphs; avoid Remix ≥ 4.9 | Approve |
| D-I2 | Photography: commission / license real maintenance photography (no stock, no AI-generated) | Approve the direction; source TBD |
| **D-L1** | Logo families to take into visual exploration: 1 Governed Loop, 2 Instrument O, 3 Step-signal Path, 4 Governed Unit (exploratory) | Approve briefs 1–5 |
| **D-TG1** | Primary tagline "From early warning to verified recovery."; descriptor "Governed reliability operations for industrial plants."; supporting line "Nothing closes without proof." | Approve |
| D-R1 | README / GitHub direction (§20), including retiring `docs/banner.svg` when the README is rewritten | Approve for a later phase |
| D-P1 | Who produces final artwork: in-house from the briefs vs a commissioned designer | Product-owner choice |

---

## 24. Sources

All accessed 2026-10-05. Evidence levels: DIRECT / SNIPPET / SECONDARY.

### Name, trademark, discoverability

| Source | Evidence |
|---|---|
| merriam-webster.com/dictionary/operon | SNIPPET |
| wikidata.org/wiki/Q33988416 | SNIPPET |
| sciencedirect.com/topics/biochemistry-genetics-and-molecular-biology/operon | SNIPPET |
| encyclopedia.pub/entry/43702 | SNIPPET |
| open.maricopa.edu/microbialgenetics/chapter/gene-regulation-in-bacteria-the-operon-model/ | SNIPPET |
| lmu.pressbooks.pub/conceptsinbiology/chapter/transcriptional-regulation-of-the-lac-operon/ | SNIPPET |
| ycombinator.com/companies/operon; operonsolutions.com/en; operonsolutions.com/en/docs/pid-agent; vibecrowd.ai/launches/operon | SNIPPET |
| uspto.report/TM/99703517; trademarkelite.com/trademark/trademark-detail/99703518/logo; trademark.justia.com/785/64/operon-78564911.html; trademarkia.com/eurofins-mwg-operon-79128743 | SNIPPET |
| eurofins.com/media-centre/press-releases-2014/2014-04-02; operondx.com/about-us/ | SNIPPET |
| operonhq.ai; operonhq.com; operonos.com; operone2i.com | SNIPPET |
| GitHub search count; github.com/{heal-research, swaruplab, coredipper, hasanyilmaz}/operon | DIRECT |
| arxiv.org/abs/2607.04240 | SNIPPET |
| pypi.org/pypi/operon/json; registry.npmjs.org/operon | DIRECT |

### Brand landscape and taglines

| Source | Evidence |
|---|---|
| element.siemens.io/fundamentals/typography/; Siemens brand guidelines 2013 (joomag) | SNIPPET |
| ibm.com MAS 9.2 announcement; themaximoguys.ai Carbon UI | SNIPPET / SECONDARY |
| brandfetch.com (aveva.com, cognitedata.com, getmaintainx.com, gevernova.com) | SECONDARY |
| fastcompany.com/91596360/samsara-rebrand-base-design; samsara.com brand-refresh and builtwithoperators | SNIPPET |
| fontsinuse.com/uses/32662/anduril-industries; summaryjudgement.substack.com; designrush.com Palantir; milkandcookies.studio | SECONDARY |
| cognite.com; seeq.com; augury.com (+ "predicting a better future" post); tulip.co/platform; uptake.com; weforum.org Sight Machine; getmaintainx.com; fiixsoftware.com/about-us; rockwellautomation.com Fiix; honeywell.com Forge; tomorrow.city; hexagon.com; octave.com newsroom 2026; siemens.com Insights Hub; litmus.io; inductiveautomation.com; tractian.com | SNIPPET |
| ssustudio.com; tentackles.com; studio204.ca | SECONDARY |

### GitHub presentation

| Source | Evidence |
|---|---|
| github/docs (raw): customizing-your-repositorys-social-media-preview.md; about-readmes.md; classifying-your-repository-with-topics.md | DIRECT |
| github.com/desktop/desktop/issues/19465 (description length) | SNIPPET |

### Typography (verified from files)

| Source | Evidence |
|---|---|
| npm: @fontsource(-variable)/{ibm-plex-sans, ibm-plex-sans-condensed, ibm-plex-mono, inter, geist(-mono), source-sans-3, source-code-pro, public-sans, atkinson-hyperlegible-next, atkinson-hyperlegible-mono, red-hat-text, red-hat-display, red-hat-mono, instrument-sans, archivo, barlow, barlow-condensed, space-grotesk, mona-sans, hubot-sans, jetbrains-mono, fira-sans, fira-code, roboto-flex, roboto-mono, noto-sans-mono} | DIRECT |
| npm: @ibm/plex-sans@1.1.0, @ibm/plex-mono; inter-ui@4.1.1; geist@1.7.2 | DIRECT |
| Upstream repos cloned (14) | DIRECT |
| openfontlicense.org/ofl-faq/; lwn.net/Articles/552178/ | SNIPPET |

### Icons (verified from package tarballs)

| Source | Evidence |
|---|---|
| @tabler/icons@3.49.0; lucide-static@1.52.0; @phosphor-icons/core@2.1.1; @carbon/icons@11.89.0; @material-symbols/svg-400@0.47.6; iconoir@7.12.1; heroicons@2.2.0; @fluentui/svg-icons@1.1.343; remixicon@4.9.1 (and 4.8.0 licence); @siemens/ix-icons@3.5.0 | DIRECT |
| github.com/Remix-Design/RemixIcon/issues/1069; github.com/elixir-lang/ex_doc/issues/2262; github.com/saga-soft/novelWriter/issues/3051 | SNIPPET |

### Colour and accessibility

| Source | Evidence |
|---|---|
| WCAG 2.x contrast formula; OKLab (Ottosson); Machado, Oliveira & Fernandes (2009) CVD matrices | Computed in this phase |
| Data-visualisation method's categorical validator (reference palette slots 1–3) | Run on Operon's surfaces |
| Phase 2 sources for ISA-101, ISA-18.2, Siemens iX status and voice guidance, AVEVA triple coding | See `02-product-ux-reference-research.md` §20 |
