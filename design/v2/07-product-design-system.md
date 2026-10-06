# OPERON V2: Product design system (Phase 3)

Status: Phase 3 specification, **reconciled with the reviewed Phase 3.1 findings** (see
[`09-visual-reference-validation.md`](09-visual-reference-validation.md) §22 for the product-owner
resolution). This document plus `08` is the **implementation baseline for Phase 4A**. Values marked
*Phase 4A starting value* remain subject to the Phase 4A screenshot gate (`08 §11`). Documentation
only. No application code, CSS, routes or backend behaviour changed. No logo or wordmark is created
or selected. Companion document:
[`08-screen-specifications.md`](08-screen-specifications.md) (screens, backend reality, Phase 4
plan). Text diagrams live in [`diagrams/`](diagrams/).

Inputs, accepted as research (not reopened):

| Phase | Document | Used for |
|---|---|---|
| 0 | [`../mode.md`](../mode.md) | Surface tracks (operational surfaces PRODUCT; sign-in and Guided Demo HYBRID), failure modes |
| 1 | [`01-product-model-and-information-architecture.md`](01-product-model-and-information-architecture.md) | Product nouns, 8 stages + exceptions, six-dimension status model, gaps G1–G10 |
| 2 | [`02-product-ux-reference-research.md`](02-product-ux-reference-research.md) | Governed Operations Workbench, decision-surface content, terminology, G11–G12, anti-patterns |
| 2.5 | [`03-brand-strategy-and-identity.md`](03-brand-strategy-and-identity.md) | Instrument & Record, Ink / Paper / Graphite, Plex, Tabler, status hues, voice, motion |
| 2.6–2.8 | `04`–`06` | Public name **unresolved**; OPERON stays the working name and internal codename |

Resolved items carried as facts:
- **Deployment:** OPERON has never been publicly deployed and has **zero** Render services. Nothing
  about deployment is open in this phase.
- **Naming:** unresolved by design. This system never depends on the word OPERON (§1.4).
- **`overhaul/v2` GitHub ruleset:** infrastructure housekeeping only (may still need manual
  creation in the GitHub UI). It does not affect design work.

Terminology used in this document: **Case** is the user-facing name for the backend `incident`
(product-owner decision recorded in Phase 2.5). Backend names are unchanged.

---

## 1. Visual direction

### 1.1 The decision

**"Instrument & Record", expressed in the product as a drawing sheet with an instrument's
discipline.**

- The workbench reads like a well-made engineering document: ruled regions, labelled title
  blocks, tag numbers, revision marks.
- Data reads like a calibrated instrument: tabular figures, units, thresholds and time, and
  nothing drawn that isn't measured.
- Colour is almost absent until the plant gives it a reason.

Why this, and not an alternative:

| Alternative considered | Why not |
|---|---|
| "Control room" dark console as the default | Phase 2 rejected Direction A as primary. Dark-by-default reads as "technical" for aesthetic reasons, which the brief rules out. A dark console also tends toward sci-fi under pressure (glows, neon status). |
| Neutral component-library dashboard (cards, pills, rounded panels) | Generic ("dashboard #482"). Cards fragment comparison. Pills overuse colour. Nothing in it is recognisably ours without a logo. |
| Editorial "case file" (serif display, warm paper, stamps) | Phase 2.5 kept territory C's *vocabulary* (evidence, revision, verification) but rejected its serif and bronze for the product. It reads archival during a live event. |
| Brand-colour accent UI (one hue for buttons, links, focus) | Phase 2.5 showed every free hue is either a competitor's or collides with a status hue under colour-vision deficiency (CVD). An accent hue would teach users that colour doesn't mean state. |

The chosen direction is the only one in which aesthetic character and operational semantics come
from the same source. Ruled structure carries hierarchy, ink carries authority, and colour carries
state. Each element does exactly one job.

### 1.2 What makes it recognisable without a logo (signature elements)

These are deliberate, specified in later sections, and the product's identity. Phase 4 must
implement all of them.

1. **Title-block headers.** Page and case headers are a single row of **at most six** labelled cells
   separated by vertical hairlines: 11 px eyebrow label above a 14 px value, like an engineering
   drawing's title block (§9.4). This replaces stat cards.
2. **Ruled document sections, not cards.** Content regions are separated by 1 px rules and spacing.
   Section headings carry a mono index (`02`), a title and right-aligned metadata on one line, with
   a rule beneath. Panels are flat. The only framed objects are those acted on as a unit (§9.3).
3. **The stage track.** Lifecycle position is a single 1 px line through eight square nodes, with a
   **hold-point bar** before *Awaiting decision* (the governed gate). Exceptions drop below the line
   (§13). The track is the product's most distinctive mark. It is a **position display, never a
   stepper**: it is not clickable and never advances anything.
4. **Instrument tags.** Asset tags, case references, revisions and hashes are set in Plex Mono inside
   2 px-radius hairline frames (`AC-COMP-01`, `R33`, `a046ef…39ab`), like nameplate tags on
   equipment.
5. **Ink controls.** Primary actions are ink on paper (light) and paper on ink (dark). There is no
   brand-coloured button anywhere. Focus and selection are ink too.
6. **Provenance marks.** 10 px square swatches (solid, diagonal, dashed, person, hatched) beside
   values and records (§14). Hatching appears **only** for simulated data, anywhere in the product.
7. **The quiet plant band.** An ISA-101 L1 strip of every asset. Normal assets are grey tags with
   hollow dots. Abnormal assets gain shape, colour and a label (§12, screens 1–2).
8. **Readouts.** Values in tabular Plex at weight 500, units in tertiary text, the true minus (U+2212),
   timestamps with seconds and zone where they matter, right-aligned in tables.

### 1.3 What the product must not look like

The Phase 2 §16 anti-patterns plus this brief's §51 are binding. Visual consequences:

- **No dark sci-fi:** no glow, neon, scanlines, HUD frames, gradients, glass or blur.
- **No KPI-card gallery, everything-in-cards layout or pill rows.**
- **No AI motif:** no orb, sparkle, avatar or "thinking" animation.
- **No decorative industrial motif:** no gauges, rivets or hazard stripes. Hatching is reserved for
  simulation.
- **Corners are at most 4 px.** Circles are used only for status dots, never for containers.

### 1.4 Name independence

- The product chrome shows the working name in exactly one place: a text label in the shell header
  (`config.APP_NAME`, plain Plex Sans 600, no custom lettering).
- No component, token, illustration or empty state contains the name.
- The favicon and app icon are out of scope (logo decision pending). Phase 4 uses a neutral
  placeholder: an Ink square with no letterform.
- Copy patterns refer to the system as "the application" when attribution matters ("Verified by
  the application's outcome policy"), not by name.
- A public rename is therefore one string and one asset swap.

---

## 2. Principles carried into the system

| Principle (brief §3) | System mechanism |
|---|---|
| Attention before analytics | Overview and My actions lead with the attention queue. Analytics live on Reliability only. No metric appears above the attention list. |
| Evidence before recommendation | In the case document, Evidence and Investigation precede Plan & decision. Every recommendation and hypothesis row links its supporting and contradicting evidence counts. |
| Human authority explicit | One decision surface (`08` screens 8, 22), bound identifiers always visible, the *decision* cue (violet person glyph plus role word, §4.3) used only where a person must act |
| Done ≠ verified | Separate work-state and verification-state vocabularies and glyphs (§12). "Work order committed" never uses the verified hue or check-circle. |
| Unknown ≠ healthy | `unknown` / `stale` / `offline` have their own glyphs (dashed, clock, plug-off) and are never rendered as hollow-dot normal (§12, §15) |
| Normal recedes | Normal uses secondary text and hollow glyphs. Colour budget: ≤ 4 hues, none of them for normal. |
| No invented certainty | Numbers come only from backend fields (`08` §1). Model scores are labelled as model output and never as probability or confidence. **Model self-reported confidence values are never displayed** (§18.6). Estimates carry their assumption set. |
| AI is workflow, not metaphor | Analysis appears as typed records: runs, hypotheses, reviews, requests. Waiting-on uses "Analysis (automated)", never "Agent". |

---

## 3. Token architecture

Three layers. Components consume **semantic** tokens only.

```text
primitive            semantic                         component
graphite.900  ──►    color.surface.base           ──► shell.background
ink, paper           color.text.primary           ──► table.cell.text
red.dark.500  ──►    color.status.critical.fg     ──► statusMarker.critical.icon
space.4       ──►    space.inline.md              ──► button.md.paddingX
```

**Naming:**
- `category.role.variant`, kebab-cased as CSS custom properties in Phase 4 (for example
  `--color-surface-sheet`).
- Each theme defines every semantic colour token; there are no theme-conditional component tokens.
- **A token has one meaning.** For example, `color.status.warning.fg` is never used for a deadline,
  link or chart series. Deadline emphasis has its own token that *aliases* warning, so its meaning
  can be changed independently.

Categories: colour, typography, space, size (control / row / icon / hit), radius, border, elevation,
motion, z-index, breakpoint, density.

---

## 4. Colour

### 4.1 Primitives

| Primitive | Value | Notes |
|---|---|---|
| `ink` | `#0C1418` | Brand Ink. Light-theme primary text and ink controls. |
| `paper` | `#F3F4F1` | Brand Paper (unchanged brand colour, `03`). Inverse text on ink controls. The product's light shell surface is a separate token (§4.2). |
| `graphite.*` | ramp at oklch hue ≈ 222, chroma ≈ 0.008 | Neutral family. Values listed in §4.2 per use. |
| `red.dark` / `red.light` | `#F0564B` / `#C42B3A` | Critical |
| `amber.dark` / `amber.light` | `#EBAA3C` / `#7F5C00` | Warning and watch |
| `violet.dark` / `violet.light` | `#AA95E8` / `#674EB0` | A person must act (lowered chroma, Phase 3.1 CH-1) |
| `green.dark` / `green.light` | `#4CB782` / `#1D7A4C` | Verified |

### 4.2 Semantic neutrals (both themes)

All ratios are WCAG 2.x, computed in Phase 3 with the Phase 2.5 colour tool.

| Token | Dark: "The Instrument" | Light: "The Drawing Sheet" | Use |
|---|---|---|---|
| `color.surface.base` | `#0F1415` | `#F1F0EC` (*Phase 4A starting value*, R-9; brand Paper `#F3F4F1` unchanged) | Shell background and nav rail |
| `color.surface.sheet` | `#1A1F21` (*Phase 4A starting value*, R-25) | `#FAFAF8` | The working area: full-bleed content region, tables, the case document |
| `color.surface.sunken` | `#121719` | `#EBEDE9` | Table header band, identifier wells, code-like blocks |
| `color.surface.raised` | `#1F2426` | `#FFFFFF` | Inputs (light), inspector rail, sticky headers over scrolled content |
| `color.surface.overlay` | `#202527` | `#FFFFFF` | Menus, popovers, dialogs, drawers (with elevation and `border.strong`, §9.5) |
| `color.surface.hover` | `#202527` | `#F0F1EF` | Row and option hover |
| `color.surface.selected` | `#282D2F` | `#E7E8E6` | Selected row (plus a 2 px ink left bar) |
| `color.border.subtle` | `#272C2E` | `#D6DAD8` | Decorative rules between rows and regions (structure only) |
| `color.border.strong` | `#34393B` | `#B9BFBF` | Region boundaries, title-block dividers, table header rule |
| `color.border.control` | `#6B7275` | `#7C8386` | **Interactive boundaries** (inputs, checkboxes, segmented control, secondary buttons) |
| `color.border.focus` | `#DDE2E4` | `#0C1418` | Focus ring (2 px + 2 px offset) |
| `color.text.primary` | `#DDE2E4` (*Phase 4A starting value*, R-25) | `#0C1418` (Ink) | Primary text, values, focal series |
| `color.text.secondary` | `#B5BCBE` | `#4A5154` | Secondary text, normal-state labels |
| `color.text.tertiary` | `#868D90` | `#5F6669` | Metadata, units, timestamps, eyebrow labels |
| `color.text.disabled` | `#5C6366` | `#9AA0A2` | Disabled only (exempt from contrast; never for information) |
| `color.text.inverse` | `#0C1418` | `#F3F4F1` | Text on ink controls |
| `color.action.primary.bg` | `#DDE2E4` | `#0C1418` | Primary button (ink control) |
| `color.action.primary.bg-hover` | `#FFFFFF` | `#22303A` | |
| `color.action.primary.fg` | `#0C1418` | `#F3F4F1` | |
| `color.action.danger.fg` | `#F0564B` | `#C42B3A` | Danger / consequential-stop actions: text and border of the `danger` button (R-24). **Its own token**: it currently shares the red value with `status.critical` but must never be implemented as a reference to the status token. |

Measured contrast:

Re-measured for the reconciled values (Phase 3.1, WCAG 2.x):

| Pair | Dark (base / sheet / raised) | Light (base / sheet / raised) |
|---|---|---|
| text.primary | 14.21 / 12.74 / 12.01 | 16.31 / 17.80 / 18.60 |
| text.secondary | 9.64 / 8.64 / 8.14 | 7.09 / 7.74 / 8.09 |
| text.tertiary | 5.50 / 4.93 / 4.65 | 5.13 / 5.60 / 5.85 |
| border.control (non-text, needs ≥ 3:1) | 3.79 / 3.40 / 3.20 | 3.38 / 3.69 / 3.85 |
| ink control vs its surface | 14.21 (dark base) | 16.31 (light base) |
| tertiary on hover | 4.59 (`#202527`) | ≥ 5.3 |

**Phase 2.5 obligations resolved:**
- **Form-control borders ≥ 3:1:** `color.border.control` passes on every surface in both themes.
  The decorative `border.subtle` and `border.strong` are never used as the only boundary of an
  interactive control.
- **Light warning text on the page:** the Phase 2.5 light warning `#B36200` (4.50:1 on white
  only) is replaced by **`#7F5C00`**:
  - 5.36:1 on the light shell (`#F1F0EC`), 5.85 on sheet, 6.12 on white;
  - it also separates better from critical under deuteranopia (ΔE 5.2 vs 1.9 for `#B36200`'s
    darkened variants).

**Selected rows in dark:** tertiary text on `surface.selected` (`#282D2F`) measures 4.13:1, below
AA. Selected rows render secondary metadata in `text.secondary` (7.24:1).

### 4.3 Operational status roles (the colour budget)

**Four hues, each with exactly one meaning.** Everything else is neutral and carried by shape and
text.

| Role token | Meaning (one only) | Dark fg | Light fg | Dark tint | Light tint | Contrast (dark sheet / light sheet) |
|---|---|---|---|---|---|---|
| `status.critical` | Condition or outcome at the action threshold; failure | `#F0564B` | `#C42B3A` | `#352223` | `#F5E5E5` | 4.86 / 5.35 |
| `status.warning` | Abnormal but below the action threshold (Elevated); watch items use this hue in outline form | `#EBAA3C` | `#7F5C00` | `#342E20` | `#EEEADF` | 8.20 / 5.85 |
| `status.decision` | **A person must act** (approve, inspect, confirm, resolve) | `#AA95E8` | `#674EB0` | *none: no decision tint in V2* | *none* | 6.48 / 6.10 |
| `status.verified` | Recovery verified by the outcome policy | `#4CB782` | `#1D7A4C` | `#1E302A` | `#E4EDE7` | 6.66 / 5.10 |

**Decision cue (CH-1, resolved for Phase 4A as option A):**
- Violet appears **only** on the person / action glyph and, where useful, the short human-role word
  ("Approver", "Technician"). It never colours sentences, headings, buttons, rules, borders or
  containers.
- The decision surface's top rule is **Ink** (§9.3), not violet.
- **Never** violet adjacent to or framing model-generated content, and never for AI, automation,
  loading, onboarding or empty states. No violet gradients, glow or decoration.
- **Phase 4A gate:** a recognition test must show the cue reads as "a person must act", not "AI",
  "automation" or "done". If it fails, the fallback is a neutral **Ink** person glyph plus the role
  word (no hue). This is a prototype decision, not permanent policy.
- **CVD (measured):** ≥ 14.5 ΔE from every other status hue and from secondary text under protan and
  deutan simulation; ΔE 12.8 from Polaris' AI "magic" violet (was 8.8).

Neutral states (no hue):

| State | Token | Rendering |
|---|---|---|
| Nominal | `status.nominal` → `text.secondary` | Hollow dot. "Normal" in text only where a label is needed. |
| Information | `status.info` → `text.secondary` | info-circle |
| Active / executing | `status.active` → `text.primary` | Half-filled circle (progress) plus a verb ("Dispatching", "In work") |
| Offline | `status.offline` → `text.tertiary` | plug-off |
| Stale | `status.stale` → `text.tertiary` | clock plus age ("Stale · 14 min") |
| Unknown / no data | `status.unknown` → `text.tertiary` | Dashed-outline square with "?" plus "No data" |

Rules:

1. **Tints are supplementary.** A tint never carries state alone. On a tint, the label uses
   `text.primary` and only the icon uses the status fg.
   - Measured: critical fg on its dark tint is 4.37:1 and verified fg on its light tint is 4.46:1,
     so status-coloured *text* on tints is not allowed.
2. **Status fg colour is for icons, shapes, threshold lines, tag borders and the short status word.**
   Never for sentences, links or headings.
3. **CVD.** Worst remaining pairs:
   - critical–verified ΔE 6.1 (light, deutan);
   - critical–warning ΔE 5.2 (light, deutan).

   Both are always distinguished by shape and word (octagon vs check-circle vs triangle).
4. **Colour budget per view.** On a typical operational screen, status colour should appear on no
   more than the abnormal items and the decision cues. If more than ~20 % of rows on a screen carry
   a hue, the grouping is wrong (rationing, ISA-18.2).
5. **Actions never reuse status tokens.** Destructive or consequential-stop buttons use
   `color.action.danger.*` (§4.2). Reject's danger emphasis is **provisional**: it reflects that
   rejection currently ends in an unresolvable escalation (G2, G4). Re-evaluate it once Request
   changes and escalation resolution exist.

**Decision recorded (changes Phase 2.5 §12, D-C3):** the fifth hue, **"executing / in work" blue,
is removed.**
- **Why:** the Phase 2.5 measurements show blue and decision violet collapse under CVD (ΔE 0.6
  deutan in light, 1.9 protan in dark). "Awaiting decision" and "In work" appear side by side in
  every case list.
- **What replaces it:** work in progress is a *process* state, not an alarm, so it renders neutral
  (`text.primary` plus the progress glyph plus a verb).
- **What it buys:** frees the colour budget, and with it the only CVD collision that shape alone
  couldn't fix in dense lists.

### 4.4 Attention: not a colour

Attention (Action required › At risk › Watch › Info) is expressed by **position, grouping, weight
and a neutral rank glyph**, never by a new hue (Phase 2.5 §12). See §12.5. The item's own status
glyph supplies colour when the underlying state has one.

### 4.5 Provenance: not a colour

Provenance uses line style, a square mark and words (§14). It has no hue. Hatching is reserved for
simulated data.

### 4.6 Data-visualisation tokens

| Token | Dark | Light | Use |
|---|---|---|---|
| `viz.series` | `text.secondary` | `text.secondary` | Default telemetry and risk series, 1.5 px |
| `viz.series.focus` | `text.primary` | `text.primary` | The one series under discussion, 2 px |
| `viz.series.context` | `text.tertiary` at 60 % | `text.tertiary` at 60 % | Other assets in focus + context |
| `viz.grid` | `border.subtle` | `border.subtle` | Horizontal gridlines only |
| `viz.axis` | `border.strong` | `border.strong` | Axis line, tick marks |
| `viz.baseline` | `text.tertiary`, dotted 1/3 | same | Labelled baseline |
| `viz.threshold.warning` | `status.warning.fg`, dashed 4/3 | same | Warning band line (0.45) with label |
| `viz.threshold.critical` | `status.critical.fg`, dashed 4/3 | same | Action gate (0.80) with label |
| `viz.band.abnormal` | status tint, 100 % | status tint | Time span above a threshold, with text label |
| `viz.prediction.band` | `text.secondary` at 12 % | at 10 % | Prediction interval, drawn as a **band only** (no dashed forecast line, R-17). None exists in the backend today (§16). |
| `viz.event` | `text.tertiary` 1 px vertical | same | Event marker: glyph in the **event lane** under the x-axis; label in the tooltip (R-17) |
| `viz.work.span` | `text.primary` at 8 % | at 6 % | Work window, labelled |
| `viz.simulated` | 45° hatch, `text.tertiary` at 35 %, 1 px / 4 px | same | Simulated spans and points |
| `viz.missing` | No mark. A gap plus a labelled start–end ("No data 14:18–14:26"). | same | Missing samples are never interpolated (gap rule, §16). |
| `viz.stale` | `surface.sunken` region from the last sample to server *now*, labelled "No data since 14:18" | same | Staleness made visible on the time axis (R-2) |
| `viz.sample.suspect` | Hollow marker in `viz.series` colour, excluded from the line | same | Samples with quality SUSPECT (R-17) |

**No categorical palette ships in V2.**
- Comparisons use focus + context or small multiples.
- The Phase 2.5 categorical reference set (blue / orange / aqua) overlaps status hues and is
  withdrawn from the product until a status-free chart genuinely requires it.

---

## 5. Themes

### 5.1 Dark: "The Instrument"

- **Surface logic:** graphite, never black. The shell sits on `base`; the working area is `sheet`,
  one step lighter. Elevation is lighter surface plus `border.strong`, with a shadow only on
  dialogs (§9.5).
- **Character:** low glare for long monitoring sessions. Normal content sits at `text.secondary`;
  abnormal content earns `text.primary` weight plus a status glyph.
- **Starting values (R-25, Phase 4A gate):** sheet `#1A1F21` (step 1.12 over base, up from
  1.06), primary text `#DDE2E4` (12.7:1 on the sheet: lower glare than the original 14.7:1).
  The surfaces are numerically close to Grafana's, so the identity must come from structure
  (title blocks, stage track, ink controls), not surface colour.
- **Status:** status hues use the bright steps, with chroma held so nothing glows. No colour
  appears on large areas except subtle tints behind abnormal rows.
- **What prevents "hacker terminal":**
  - text is Plex Sans, not mono (mono only for identifiers);
  - no pure black and no green-on-black;
  - no glow, outlines on borders or animated "live" elements.

### 5.2 Light: "The Drawing Sheet"

- **Surface logic:** **a sheet on a desk, not cards on grey.**
  - The shell and nav rail sit on a warm paper tone, `#F1F0EC` (*Phase 4A starting value*, R-9:
    step 1.09 to the sheet so the two never merge on tablets and projectors; chroma capped at about
    OKLCH 0.006 to avoid an archival look). Brand Paper `#F3F4F1` is unchanged.
  - The working area is one full-bleed sheet (`#FAFAF8`) separated from the shell by a single
    `border.strong` rule.
  - Inside the sheet, structure comes from ruled sections and title blocks.
  - Pure white is reserved for inputs and overlays, which are the only floating things (with
    shadow).
- **Character:** Ink typography with hairlines, like an engineering document read in an office or at
  an approval, and legible in daylight on a tablet.
- **Status:** status uses the dark, text-safe steps, which read like a drafting pen rather than a
  highlighter.
- **Rule budget (R-8):** no vertical rules outside title blocks; a table uses **either** the sunken
  header band **or** a header rule, never both; hierarchy comes from spacing and type before any
  additional rule.
- **Uppercase budget (R-7):** see §6.2. Too many uppercase eyebrows plus rules is what makes a
  light UI read as a government form.
- **Not an inversion.** Differences from dark:

  | Aspect | Light | Dark |
  |---|---|---|
  | Page tone | Warm | Cool |
  | Elevation | White-on-paper | Lighter-is-higher |
  | Status steps | Darker | Brighter |
  | Rules | Stronger relative rule contrast (1.35 vs 1.24) | — |

### 5.3 Theme selection

| Setting | Behaviour |
|---|---|
| Default | Follows the operating system (`prefers-color-scheme`). There is **no product-preferred theme**. |
| Override | Preferences → Appearance: System / Light / Dark, stored per browser |
| Demo mode | Follows the same setting. Projection guidance: light is more legible on projectors (recommendation only). |
| Charts and print | Charts re-resolve tokens on theme change. Printing the case record forces light. |

---

## 6. Typography

### 6.1 Families and files

| Family | Purpose |
|---|---|
| **IBM Plex Sans (variable)** | All UI text. Weights used: 400, 500, 600 (700 unused). Width axis kept at 100 in product UI (condensed widths are reserved for brand display). |
| **IBM Plex Mono** | Identifiers only: asset tags, case references, revisions, hashes, requirement and receipt IDs, work-order numbers, API paths in System, raw values in the inspector |

- **Files:** IBM's official `@ibm/plex-sans-variable` and `@ibm/plex-mono` WOFF2 files,
  unmodified. They keep `zero` and `ss01–ss05`, which the fontsource builds strip (Phase 2.5 §9).
  This replaces the current `@fontsource/*` dependencies in Phase 4.
- **Features:**
  - `font-variant-numeric: tabular-nums` on every numeric cell and readout (Plex figures are
    tabular by default; declared anyway for fallbacks);
  - `font-feature-settings: "zero"` on Plex Mono for hashes and IDs (slashed zero);
  - U+2212 for minus;
  - thin space (U+2009) between value and unit is not used; one normal space instead.

### 6.2 Scale

Base size is 14 px on desktop and tablet and 16 px in touch layouts (§7.2).

| Token | Size / line height | Weight | Tracking | Use |
|---|---|---|---|---|
| `type.display` | 28 / 36 | 500 | −0.01 em | Sign-in and Demo-mode frame only. Not used on operational pages. |
| `type.title` | 22 / 28 (touch 20 / 26) | 600 | −0.005 em | Page title; case title |
| `type.heading` | 16 / 24 (touch 18 / 24) | 600 | 0 | Section heading in the case document and pages |
| `type.subheading` | 14 / 20 | 600 | 0 | Sub-section, group header in queues |
| `type.body` | 14 / 20 (touch 16 / 24) | 400 | 0 | Default text |
| `type.body.compact` | 13 / 18 | 400 | 0 | Dense lists, inspector body |
| `type.label` | 12 / 16 | 500 | +0.01 em | Form labels, column headers (sentence case) |
| `type.eyebrow` | 11 / 16 | 600 | +0.06 em, UPPERCASE | **Only** title-block cell labels and nav-rail group labels (R-7); ≤ 3 words; never running text |
| `type.caption` | 12 / 16 | 400 | 0 | Helper text, chart captions, freshness lines |
| `type.table` | 13 / 18 compact · 14 / 20 comfortable | 400 (values 500) | 0 | Table cells |
| `type.readout` | 24 / 28 | 500 | −0.01 em | Key values in asset detail and verification (risk score, latest torque) |
| `type.numeric` | inherits size | 500 | 0, tabular | Inline numbers |
| `type.mono` | 13 / 18 | 400 | 0 | Identifiers in tables and headers |
| `type.mono.small` | 12 / 16 | 400 | 0 | Hashes, IDs in metadata |
| `type.button` | 13 / 16 (sm) · 14 / 20 (md) · 16 / 24 (touch) | 500 (touch 600) | 0 | Buttons |
| `type.nav` | 13 / 20 | 500, active 600 | 0 | Primary navigation |
| `type.badge` | 12 / 16 | 500 | 0 | Status words, tag text |

Rules:
- **Minimum text is 12 px.** 11 px is allowed only for `type.eyebrow` (uppercase, weight 600,
  `text.tertiary` or better).
- **Casing:**
  - sentence case everywhere;
  - UPPERCASE only for title-block cell labels, nav-rail group labels and the `SIMULATED`
    provenance tag. Decision-surface keys, context-rail headings, section metadata and queue group
    headers are sentence case (`type.label` 12 px, weight 500);
  - no capitals for emphasis.
- **Units** follow the value in `text.tertiary`, one size step smaller in readouts
  (`24` + `13`, e.g. "42.1 Nm").
- **Prose measure:** ≤ 72 characters in reading regions (case summary, reasoning summaries).
  Tables and workspaces are not width-capped.
- **Timestamps:**
  - local plant time `HH:MM` in lists;
  - `HH:MM:SS` in the record and evidence;
  - full ISO date-time with zone in the inspector and on hover.
  - The plant time zone comes from `plant.timezone` (seeded `America/Chicago`). Exposing it is
    projection item X3 in `08` §1.

---

## 7. Space, size and density

### 7.1 Spacing scale (4 px base, 2 px half-steps)

`space.0 = 0` · `space.1 = 2` · `space.2 = 4` · `space.3 = 6` · `space.4 = 8` · `space.5 = 12` ·
`space.6 = 16` · `space.7 = 20` · `space.8 = 24` · `space.9 = 32` · `space.10 = 40` ·
`space.11 = 48` · `space.12 = 64`

Semantic aliases:

| Token | Value |
|---|---|
| `space.inline.xs` | 4 |
| `space.inline.sm` | 6 |
| `space.inline.md` | 8 |
| `space.inline.lg` | 12 |
| `space.stack.xs` | 4 |
| `space.stack.sm` | 8 |
| `space.stack.md` | 12 |
| `space.stack.lg` | 16 |
| `space.stack.xl` | 24 |
| `space.section` | 32 |
| `space.region.pad` | 16 / 24 |
| `space.gutter` | 24 / 16 / 16 |

`space.region.pad` is 16 at Compact and 24 at Comfortable. `space.gutter` is 24 on desktop, 16 on
tablet and 16 on phone.

### 7.2 Density modes

| Mode | Where it applies | Row height | Control height | Cell padding (y / x) | Text |
|---|---|---|---|---|---|
| **Compact** | Desktop tables and queues: Cases, Assets, Work orders, Audit log, Record, Evidence table, inspector | 32 | 28 | 6 / 8 | `type.table` 13 |
| **Comfortable** | Overview, My actions, the case summary and decision surface, forms, System, all tablet layouts | 40 (single line) · 56 (two-line queue items) | 32 (36 for primary in the decision surface) | 10 / 12 | 14 |
| **Touch** | Any layout < 768 px or with a coarse pointer; technician task and inspection; mobile approval | ≥ 56 (two-line ≥ 64) | 44 (primary actions 48) | 12 / 16 | 16 |

- Users may switch tables between Compact and Comfortable (Preferences → Density). Touch is
  automatic and can't be disabled on coarse pointers.
- Large whitespace is not a quality signal. Comfortable spacing exists for decision and reading
  regions, not for dense comparisons.

### 7.3 Sizes

| Token | Value |
|---|---|
| `size.control.sm` / `md` / `lg` / `touch` | 28 / 32 / 40 / 48 |
| `size.hit.min` | 24 × 24 (pointer, WCAG 2.5.8); **44 × 44** touch; 48 × 48 for primary touch actions; ≥ 8 px between adjacent touch targets |
| `size.icon.xs` / `sm` / `md` / `lg` | 12 / 16 / 20 / 24 |
| `size.mark` | 10 (**provenance marks only**; status shapes are ≥ 14, §10) |
| `size.status` | 14 in cells and inline · 16 in the plant band and title block (R-4) |
| `size.rail.nav` | 224 expanded · 56 collapsed |
| `size.rail.context` | 320 (case context rail) |
| `size.rail.inspector` | 380 docked (min 360, max 420); modal drawer width 420 below 1280 (CH-2, *Phase 4A prototype*) |
| `size.header.shell` | 48 (desktop) · 56 (touch) |

---

## 8. Layout and grid

### 8.1 Breakpoints

| Token | Min width | Layout class |
|---|---|---|
| `bp.phone` | 0 (designed from 360) | Touch task layouts, bottom bar |
| `bp.phone-lg` | 600 | Touch, two-column forms allowed |
| `bp.tablet` | 768 | Workbench minus multi-pane: collapsed nav rail, preview / inspector as a **modal drawer** |
| `bp.laptop` | 1024 | Workbench. Nav rail collapsible, case context rail folds into Summary. |
| `bp.desktop` | 1280 | Full workbench with case context rail; preview / inspector **docks** (pushes content, about 380 px). CH-2 *Phase 4A prototype hypothesis*. |
| `bp.workstation` | 1440 | Same as desktop with more table columns |
| `bp.wide` | 1920 | Additional columns in tables; no stretched prose |

**Minimum useful viewports:**
- 360 px for phone task flows;
- 1024 px for the full desktop workbench. Below 1024 the tablet layout applies; it is not a squeezed
  desktop.

### 8.2 Shell geometry (desktop)

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ shell header 48: name · plant ▾ · ─────────── · system status · updates · acct│
├──────────┬────────────────────────────────────────────────────────┬───────────┤
│ nav rail │ sheet (full-bleed working area; owns its scroll)       │ inspector │
│ 224 / 56 │   page title block (sticky within sheet)               │ ≈380      │
│          │   content regions (12-col fluid grid, 24 gutters)      │ (≥1280    │
│          │                                                        │  docks;   │
│          │                                                        │  <1280    │
│          │                                                        │  modal)   │
└──────────┴────────────────────────────────────────────────────────┴───────────┘
```

### 8.3 Grid and regions

| Breakpoint | Columns | Gutter | Sheet side padding | Notes |
|---|---|---|---|---|
| ≥ 1280 | 12, fluid | 24 | 24 | Width is not capped (tables and workspaces use the full width); prose blocks cap at 72 ch |
| 768–1279 | 8, fluid | 16 | 16 | |
| < 768 | 4, fluid | 16 | 16 | |

**Region templates:**

| Template | Composition | Used by |
|---|---|---|
| **Queue** | List region (8 / 12) plus optional preview (inspector) | My actions, Cases, Work orders, Audit log |
| **Document** | Section index rail (184 px) · document column (fluid, prose ≤ 72 ch inside) · context rail (320 px ≥ 1280) | Case workspace, Asset detail |
| **Board** | Full-width band plus a 2-column region grid (8 + 4) | Overview |
| **Settings** | Section list (224) plus form column (≤ 720) | System, Preferences |

**Scrolling ownership:**
- The window never scrolls in the workbench.
- The **sheet** owns vertical scroll; the nav rail and inspector scroll independently.
- Title blocks and case headers are sticky inside the sheet.
- Tables with more than one screen of rows scroll inside the sheet and keep sticky column headers.
  There are no nested scroll areas inside sections, except code wells and the record when embedded
  in the inspector.
- Phone layouts use normal document scroll with a sticky top bar and bottom bar.

**Full-height workspaces:** the case workspace and System use the full height below the shell
header; nothing below the fold is required to understand the current state (`08` per screen).

**Split views:**
- *Queue + preview:* docked preview of about 380 px at ≥ 1280; a **modal drawer** (scrim, focus
  trap, `Esc` and Back return focus to the row) below 1280; one pane at a time on phones.
  **There is never an "overlay but not modal, no scrim, queue still interactive" state** (CH-2).
  The 1280 boundary is a Phase 4A prototype hypothesis, tested at 1024, 1280 and 1440 (`08 §11`).
- *Document + context rail:* the rail collapses into Summary below 1280.

No other splits. Users can't resize panes in V2.

**Mobile stacking order** follows Phase 1 §16 progressive collapse:

1. action and next step
2. stage and waiting-on
3. condition
4. evidence summaries
5. investigation
6. telemetry
7. record and identifiers

---

## 9. Surfaces, borders, radius, elevation

### 9.1 Surface philosophy

- **One sheet per page.** Hierarchy inside it comes from rules, title blocks, type and space, not
  nested containers.
- A region is a heading row plus content, separated from the next by `space.section` and a
  `border.subtle` rule.

### 9.2 Borders

| Token | Value | Use |
|---|---|---|
| `border.width.hairline` | 1 px | All structure |
| `border.width.emphasis` | 2 px | Focus ring, selected-row bar, decision-surface top rule, current stage node outline |

- Decorative borders (`subtle`, `strong`) define structure.
- `border.control` defines interactive boundaries.
- Status-coloured borders appear only on status tags. The decision surface's 2 px top rule is
  **Ink** (CH-1); violet never draws a rule, border or container.

### 9.3 Cards: the only allowed framed objects

| Framed object | Why it may be framed |
|---|---|
| **Decision surface** | Acted on as a unit. **Ink** 2 px top rule, `surface.raised`. |
| **Technician task card** on mobile | One task, acted on as a unit |
| **Preview / inspector panel** | Docked pane (≥ 1280) or modal drawer (< 1280) |
| **Dialogs, menus, popovers, toasts** | Overlays |

**Bounded but not framed (R-11).** These use a tint and / or a rule, never a full frame:

| Element | Treatment |
|---|---|
| Next-step block (case context rail, mobile summary) | `surface.sunken` tint plus a 2 px **ink** left rule |
| Context rail | Tint plus a hairline separator from the document |
| Pinned open evidence request | 2 px left rule (ink) plus the waiting-on glyph |
| Identifier / hash wells; chart plot areas | `surface.sunken` tint |
| Exception banner | Rule plus status glyph plus text |

- **At most one framed object per viewport region.** If the decision surface is visible, nothing
  else in the same region is framed.
- Long scrolls keep **sticky section headings** so region boundaries are never lost.

Everything else (metrics, rows, evidence, hypotheses, events, assets) is **never** a card. Rows
are rows, and the record is a ruled timeline.

### 9.4 Title block (signature component)

```text
┌─────────────────┬──────────────┬──────────────────┬──────────────┬───────────┬──────────┐
│ ASSET CONDITION │ SEVERITY     │ STAGE            │ WAITING ON   │ DEADLINE  │ REVISION │
│ ⬣ Critical 0.86 │ ▮▮▮▯ High    │ Awaiting         │ ◈ Approver   │ 15:12     │ R33      │
│                 │              │ decision · 5/8   │              │ in 2 h 41 │          │
└─────────────────┴──────────────┴──────────────────┴──────────────┴───────────┴──────────┘
```

**Cell budget (R-6): at most six cells.** Canonical case set, in order: Asset condition ·
Severity (or Asset criticality until X2) · Stage · Waiting on · Deadline · Revision.
- The case reference, analysis run and incident UUID live in the context rail's **Identifiers**,
  not the title block (no duplication).
- **Cells that don't apply are dropped**, not shown empty (e.g. no Deadline cell when there is no
  pending requirement).
- Page title blocks (Overview, lists) use the same ≤ 6 rule.

- **Cells:** `type.eyebrow` label in `text.tertiary` above a 14 px value; padding 8 / 12.
  - Vertical `border.subtle` dividers between cells.
  - The block is bounded above and below by `border.strong`.
- **Overflow:** cells wrap to a second row on narrow widths; they never truncate a status value.
- **Mobile:** a two-column definition list in the same order.
- **Rules:** no icons except status glyphs (≥ 16 px here, R-4), and no numbers that aren't
  backend fields.

### 9.5 Radius and elevation

| Token | Value | Use |
|---|---|---|
| `radius.none` | 0 | Regions, tables, title blocks, timeline, sections, nav rail |
| `radius.xs` | 2 px | Tags, status tags, checkboxes, provenance marks, actor marks |
| `radius.sm` | 4 px | Buttons, inputs, menus, popovers, dialogs, toasts, tooltips, decision surface |

- **Nothing exceeds 4 px.** No pill shapes. Circles are used only for status dots and the progress
  glyph.
- **Elevation tokens:**

  | Token | Light | Dark |
  |---|---|---|
  | `elevation.0` | none | none |
  | `elevation.overlay` | `0 1px 2px rgb(12 20 24 / .08), 0 8px 24px rgb(12 20 24 / .12)` | `0 8px 24px rgb(0 0 0 / .40)` plus `border.strong` |
  | `elevation.dialog` | Overlay plus a scrim (`ink` at 40 % in light, `#000` at 55 % in dark) | Same |

- Shadows never appear on in-flow content.

### 9.6 Z-index layers

| Token | Value |
|---|---|
| `z.base` | 0 |
| `z.sticky` | 100 |
| `z.rail` | 200 |
| `z.drawer` | 300 |
| `z.popover` | 400 |
| `z.dialog` | 500 |
| `z.toast` | 600 |
| `z.tooltip` | 700 |

---

## 10. Iconography

| Topic | Rule |
|---|---|
| Libraries | **Tabler** (`@tabler/icons` 3.49.0, MIT; every icon name in this document verified to exist in its outline set) primary. **Lucide** only where Tabler lacks a concept (e.g. `inspection-panel`). Same 24-grid, round caps and joins. |
| Stroke | 1.5 px at 16, 1.75 at 20, 2 at 24. Set per size, never hairline. |
| Default sizes | 16 in tables and inline · 20 in navigation and section headings · 24 for touch actions |
| Outline vs filled | Outline by default. **Filled only for status shapes** (octagon, triangle) and the active navigation item. |
| Alignment | Optically centred on the text x-height in inline use. A 16 px icon with 13–14 px text aligns to the cap height. 8 px gap to its label. |
| Status shapes | Drawn as Operon-owned 14 / 16 px SVGs (simple geometry), not library glyphs, so weight is consistent: hollow dot (normal), filled triangle (warning), outlined diamond (watch), filled octagon (critical), person-in-square (decision), half-filled circle (active), check-circle (verified), dashed square + "?" (unknown), clock (stale), plug-off (offline). **Minimum 14 px in cells and inline; 16 px in the plant band and title block (R-4).** At 10–12 px the octagon, dot and diamond become indistinguishable (Phase 3.1 render). 10 px marks are reserved for **provenance**, which never carries severity. |
| Status overlay | **Not used in V2.** A status shape small enough to overlay an icon falls below the 14 px minimum. Status is always a standalone shape plus word (R-4). |
| Custom industrial glyphs (Phase 4 deliverable) | **pump, valve, compressor, conveyor, bearing**, plus **press, grinder, spot-weld robot** for the seeded fleet classes (`PUMP`, `COMPRESSOR`, `CONVEYOR`, `PRESS`, `GRINDER`, `ROBOT`; `CNC_MACHINE` uses Tabler `engine` or a custom mill glyph). Drawn on Tabler's 24 grid at 2 px round stroke, outline only, recognisable at 16 px. Not brand marks. |
| Action icons | Verb-specific and never alone for consequential actions:<br>• approve and dispatch: `square-check`<br>• reject and escalate: `square-x`<br>• request changes: `message-2-cog`<br>• inspect: `clipboard-check`<br>• attach: `camera` (future)<br>• open in workspace: `arrow-up-right` |
| Navigation | One outline icon per area (Overview `layout-dashboard`, My actions `checklist`, Cases `folders`, Assets `building-factory-2`, Work orders `tool`, Reliability `chart-line`, Audit log `history`, System `adjustments`). Text labels always visible when the rail is expanded; tooltips when collapsed. |
| Never | Robot, sparkle, brain, magic-wand or chat-bubble icons for analysis; decorative icons beside headings; icons as the only label of a status |

---

## 11. Motion

| Token | Value | Use |
|---|---|---|
| `motion.instant` | 0 ms | Reduced-motion substitute for everything below |
| `motion.fast` | 120 ms | Hover and press feedback, checkbox, tag state change |
| `motion.base` | 160 ms | Expand / collapse, tab change, preview open |
| `motion.slow` | 200 ms | Inspector and drawer slide, dialog enter |
| `motion.highlight` | 1200 ms | New-row tint fading to rest (new evidence, new event) |
| `easing.standard` | `cubic-bezier(0.2, 0, 0, 1)` | Enter and move |
| `easing.exit` | `cubic-bezier(0.4, 0, 1, 1)` | Leave |

**What motion explains:**

| Event | Motion |
|---|---|
| State change | 120 ms crossfade of the status glyph and word, plus a 2 px settle |
| Stage advance | The track fills the new node; the previous node becomes a completed square. No travelling dot. |
| New evidence or event | Row tint highlight that fades out over 1.2 s; nothing else moves |
| Expansion | Height plus opacity, 160 ms |
| Approval result | The decision surface is replaced immediately by the recorded decision ("Approved by … at …, dispatching"), then the receipt state. No celebration. |
| Work progression | Steps change only on real receipts (claimed → confirmed) |
| Verification | Increments as samples arrive (count updates); the outcome appears without fanfare |

**Forbidden:**
- pulsing or breathing indicators;
- "live" dots that animate while nothing changes;
- skeleton shimmer of any duration (skeletons are static; timing in §15, R-19);
- scanning or sweep effects;
- glow;
- motion that moves the Approve control or the bound identifiers;
- auto-scrolling feeds;
- looping animation of any kind.

**Reduced motion** (`prefers-reduced-motion: reduce`):
- all durations become `motion.instant`;
- highlights become a static "New" tag that clears on focus or after the user scrolls past;
- no translation or scale anywhere.

---

## 12. Status grammar

Eight dimensions, each with its own vocabulary, glyph family and **slot** (position). They are
never merged into one coloured badge.

### 12.1 Slots

| Slot | Position in a row / header | Carries |
|---|---|---|
| A | Leading edge (24 px column) | **Attention** rank glyph. **Omitted inside lists already grouped under an attention header** (R-14). |
| B | Asset cell | **Asset condition** glyph and word |
| C | Stage cell | **Case stage** (word plus n/8 in rows; square node only in the stage track, R-14) |
| D | Waiting-on cell | **Waiting on** role glyph and role |
| E | Severity cell | **Severity** bars and word |
| F | Inline, after a value or record | **Provenance** mark |
| G | Work cell | **Work state** |
| H | Verification cell | **Verification state** |

### 12.2 Dimension specifications

| Dimension | Vocabulary | Glyph / shape | Colour role | Text | Compact | Expanded |
|---|---|---|---|---|---|---|
| **Asset condition** | Normal · Elevated · Critical · No data · Stale | hollow dot · filled triangle · filled octagon · dashed "?" square · clock | nominal · warning · critical · unknown · stale | Word always shown, except Normal in the plant band (glyph only, with an `aria-label`) | Glyph plus word | Plus model risk score, thresholds, sample time: "Critical · risk score 0.86 (gate 0.80) · 14:32:05" |
| **Case stage** | Detected · Investigating · Awaiting inspection · Diagnosed · Planning · Awaiting decision · In work · Verifying · Closed · Escalated · Dispatch failed · Cancelled | Square node. Hollow = future, filled ink = current, ink with tick = completed, dashed = exception. | Neutral (ink). Exceptions add the critical octagon only for Dispatch failed and Regressed-escalation. | Stage word | Square plus word | Stage track (§13) |
| **Waiting on** | Analysis (automated) · Technician · Approver · Reliability engineer · Dispatch (system) · Verification (system) · No one | Person-in-square for human roles (decision violet glyph, plus violet role word where useful, when the human is the current blocker; §4.3); Tabler `settings` (gear) for system roles | decision (human blocker) · neutral (system) | "Waiting on Approver" | Glyph plus role | Plus what is needed: "Approve the work package · by 15:12" |
| **Severity** | Critical · High · Medium · Low | Four ascending bars (filled count = level) | **Neutral ink.** Severity is consequence, not state. | Word | Bars plus word | Plus basis: "High · asset criticality High, model triage" |
| **Attention** | Action required · At risk · Watch · Info | Rank glyph: ■ solid square · ◧ half square · □ outline square · none | **Neutral ink**, weight-coded | Group headers carry the words | Glyph in slot A | Group header with count |
| **Provenance** | Measured · Derived · Model-generated · Human-entered · Simulated | 10 px square: solid · diagonal split · dashed outline · person dot · hatched (+ `SIMULATED` tag when consequential) | None | Word on hover or in expanded form | Mark | Mark, word, source, time (§14) |
| **Work state** | Planned · Awaiting decision · Approved · Dispatching · Work order committed · Dispatch failed · *(field states: G10)* | Outline document · person-square · square-check · half circle · document-check · octagon | neutral · decision · neutral · active (neutral) · neutral · critical | Word plus work-order number | Glyph plus word | Plus WO number, technician, window, receipt time |
| **Verification state** | Not started · Observing (since {time}; a sample count only with X8) · Inconclusive · Verified recovery · Not recovered · Regressed | dashed circle · outline diamond · outline diamond with "~" · check-circle · circle-x · filled octagon | neutral · warning (outline = watch) · warning (outline) · verified · critical · critical | Word plus count where real | Glyph plus word | Plus before / after metrics, policy, last samples |

Notes:
- **Verified is the only green in the product.** "Work order committed", "Approved" and "Closed"
  without a verified outcome never use green or check-circle.
- **Closed** in the stage dimension is shown with the verification glyph beside it, because the
  only route to Closed is verified recovery (`outcome.py`). If a future backend adds other closure
  routes, Closed must carry its reason.
- **Severity source:**
  - `incident.severity` exists on `GET /api/incidents/{id}` but is not in the WebSocket alert
    projection (exposure X2, `08` §1).
  - Until it is projected, list rows show **asset criticality**, labelled "Asset criticality", not
    "Severity".

### 12.3 Combination example (brief §14)

A critical asset whose case awaits approval, waiting on the supervisor, with action required:

```text
A  B                         C                          D                     E        deadline
■  ⬣ Critical  AC-COMP-01   Awaiting decision · 5/8    ◈ Waiting on Approver  ▮▮▮▯ High  15:12 · in 2 h 41
```

(In a list already grouped under "Action required", slot A is omitted.)

- **Read left to right:** "needs action · the asset is critical · the case is at the decision ·
  the approver is the blocker · high consequence · deadline".
- **Colour:** only two glyphs carry colour:
  - the octagon (red: condition);
  - the person-square (violet: a person must act).

  Everything else is ink.

### 12.4 Combination rules

1. **Condition never derives from case existence.** A case in Verifying on an asset whose risk is
   now 0.02 shows *Normal* condition.
2. A row carries at most **two** hued glyphs: condition plus waiting-on, or verification.
3. **Exceptions are never softened.** Escalated and Dispatch failed rows always show their
   waiting-on role and what is unavailable (G2 / G3).
4. **Missing dimensions are stated in words, never "—"** (R-15): "Not projected", "No deadline",
   "No observation". The words are the accessible name too.
5. **Aggregates take the worst member plus a count** (R-14). Any roll-up (plant band line summary,
   grouped row, collapsed watch list) shows the most serious member's shape and word plus counts:
   "⬣ 1 critical · ▲ 2 elevated · 5 normal". An aggregate never shows a softer state than its
   worst member.
6. **Glyph budget:** at most about five status glyphs per row (Carbon's ceiling). Stage renders as a
   word in rows; attention glyphs are dropped inside attention-grouped lists.

### 12.5 Attention presentation

| Level | Derivation (Phase 1 §15, Phase 2 wording) | Presentation |
|---|---|---|
| **Action required** | A person is the blocker: Awaiting decision; Awaiting inspection; resource confirmation; Escalated; Dispatch failed; approval expired (G11) | Group 1. Solid square. Row text `text.primary`, weight 500 for the required response. Leads every queue. |
| **At risk** | Critical condition with a case progressing without a person; Regressed; reasoning unavailable while cases are open | Group 2. Half square. Normal weight. |
| **Watch** | Elevated condition without a case; Verifying; Inconclusive observation | Group 3. Outline square. `text.secondary`. More than 5 items show the first 5 plus "Show all n" (expands in place; never hidden). |
| **Info** | Closed and verified; routine updates | Not in queues. Updates only. |

**Each attention item states (in this order):**

1. Required response, as a verb: "Approve work package".
2. Object: asset tag and case.
3. Why it matters: one line from backend facts, e.g. "Risk score 0.86 above gate 0.80 · bearing wear
   confirmed".
4. Waiting-on role.
5. Deadline: only from `expires_at`, or the work window start when real.
6. Destination: the exact case section.

There are no cards, no per-item colour backgrounds and no "new" badges that persist.
**Burst grouping (safe rule, product-owner correction B).** Grouping repeated items is
**presentation only**:
- A group row ("5 assets crossed the warning band · 14:20–14:28") always takes the worst member's
  shape and word (rule 5 above) and **expands in place** to the full list of members.
- Every member stays individually accessible and inspectable, with its own asset, timestamp,
  severity, evidence, state and link to the authoritative record. Grouping never merges, drops or
  summarises away a member, and never applies to the case record or the audit log.
- Grouping is computed from items the UI already holds individually. **If the data needed to expand
  a group safely isn't available, grouping is not implemented.** Today the WebSocket projects at
  most one case per asset (G5), so case bursts can't occur; grouping applies only to session-local
  Updates and watch-list rows. It is **not in Phase 4A scope**.

---

## 13. Case lifecycle presentation

### 13.1 Stage model (Phase 1 §11.2, with Phase 2 / 2.5 wording)

| # | Stage (UI) | Internal phases | Where are we | What happens next | Waiting on | Possible action |
|---|---|---|---|---|---|---|
| 1 | Detected | OPEN | A model risk score crossed the action gate; a case was opened | Baseline evidence is collected automatically | Analysis (automated) | Open case; view telemetry |
| 2 | Investigating | INVESTIGATING | Evidence collected; hypotheses being tested by automated reviews | A diagnosis is promoted, or an inspection is requested, or the case escalates | Analysis (automated) | Direct the investigation (instruction) |
| 2a | Awaiting inspection | AWAITING_EVIDENCE | Analysis needs physical confirmation of a mechanism | A technician inspects and records the result | **Technician** | Inspect (G1) |
| 3 | Diagnosed | DIAGNOSIS_VALIDATED | The application accepted a diagnosis | Resources (technician, parts, window) are confirmed | **Approver** (resources) | Confirm resources (G1) |
| 4 | Planning | PLANNING, INTERVENTION_VALIDATED | A work package is drafted and reviewed (engineering, operations, critic, planner) | The exact package goes to decision | Analysis (automated) | Read reviews |
| 5 | Awaiting decision | AWAITING_APPROVAL | The exact package awaits a human decision before expiry | Approve and dispatch, or reject | **Approver** | Approve and dispatch · Reject and escalate · (Request changes, G4) |
| 6 | In work | READY, EXECUTING | Approved; the work package is being dispatched | The work order is committed; observation begins | Dispatch (system) | — |
| 7 | Verifying | OBSERVING | The work order is committed; post-work model scores are observed against the outcome policy | Verified → Closed; Not recovered → Investigating; Regressed → Escalated | Verification (system) | — (field completion G10) |
| 8 | Closed | CLOSED | Recovery verified by policy | — | No one | Read record |
| ⚠ | Escalated | ESCALATED | Rejected, failed analysis, blocked gate or regression; automated progress stopped | A person resumes or cancels (G2) | **Reliability engineer** | Resolve (G2), shown as unavailable |
| ⚠ | Dispatch failed | EXECUTION_FAILED | The work order wasn't confirmed by the CMMS adapter | Retry, reinvestigate or cancel (G3) | **Approver** | Resolve (G3), shown as unavailable |
| ⊘ | Cancelled | CANCELLED | Not reachable in this backend | — | — | — |

**Wording decisions:**
- **"Dispatch failed"** replaces "Execution failed", because execution here *is* the governed dispatch
  to the CMMS adapter, not field work.
- **"Awaiting inspection"** replaces "Needs inspection" to keep every waiting stage in one
  grammatical form.

### 13.2 Stage track (component)

```text
 Detected  Investigating  Diagnosed  Planning  ┃ Awaiting decision  In work  Verifying  Closed
    ▣───────────▣────────────■──────────□─────┃──────□───────────────□────────□─────────□
                └─ Awaiting inspection ◇ (loop)
                                                           ↘ ⚠ Escalated  (exception branch)
```

| Element | Rendering |
|---|---|
| Line | 1 px `border.strong` |
| Nodes | 10 px squares: ▣ completed (ink with tick) · ■ current (ink, 2 px ring) · □ future (outline `border.control`) |
| Hold point | `┃` 2 px × 14 px ink bar before *Awaiting decision*, labelled "Human decision" on hover. It marks the governed gate. |
| Loops | Inspection and "Not recovered → Investigating" render as a return arc below the line, with the count ("Reinvestigated 1×") |
| Exceptions | Drop below the track from the stage where they occurred, with a dashed node, the exception word and its waiting-on role |
| Current-stage caption | Current stage word in `type.subheading`, plus one-line "what happens next" beneath the track |
| Compact form (rows, mobile) | "Awaiting decision · 5/8" (word plus position). Mobile summary may add a 48 px mini-track of 8 ticks. |
| Not a stepper (R-22) | The track displays lifecycle position. It isn't clickable, doesn't navigate and never advances anything. It is not a progress indicator for a linear task, because the lifecycle loops. |
| Accessibility | `<ol>` of stages with `aria-current="step"`; exceptions announced as "Exception: Escalated" |

The full lifecycle diagram is in
[`diagrams/case-lifecycle.mmd`](diagrams/case-lifecycle.mmd).

---

## 14. Provenance pattern

| Provenance | Backend source | Mark (10 px) | Compact | Expanded |
|---|---|---|---|---|
| **Measured** | Evidence `provenance = OBSERVED` from sensors / telemetry; `sensor_reading` | ■ solid | Mark only | "Measured · TORQUE sensor · 14:32:05 · good quality" |
| **Derived** | Evidence `DERIVED` from deterministic application logic (observation metrics, freshness, aggregates) | ◩ diagonal split | Mark | "Derived · from 3 readings · policy operon-outcome-1" |
| **Model-generated** | Model risk score / predicted mode (`model_signal`, `health_score` kinds; backend marks these `DERIVED`) and all advisory analysis output (hypotheses, reviews, plan drafts) | ⬚ dashed outline | Mark, plus a dashed rule on advisory blocks | "Model-generated · GradientBoosting (AI4I) · version … · not a probability" or "Model-generated · Diagnostic review · run … · provider/model or deterministic" |
| **Human-entered** | Trusted confirmations (`TrustedTechnicalConfirmation`, `ResourceConfirmation`), `ApprovalDecision` | ▪︎ square with person dot | Mark plus actor | "Human-entered · TECH-201 (declared actor, G8) · 10:41" |
| **Simulated** | `provenance = SIMULATED`, outcome `basis = SIMULATED`, Guided Demo inputs, simulator telemetry | ▨ hatched | **`SIMULATED` tag (uppercase, hatched border) whenever the item is consequential** (evidence cited by a diagnosis, outcome basis, approval context) | "Simulated · Guided Demo scenario … · not plant data" |

**Mapping decision:** the backend classifies model signals as `DERIVED`. The UI shows them as
**Model-generated** when the evidence kind is `model_signal` or `health_score`, because users must
distinguish a learned model's estimate from deterministic arithmetic. The backend is unchanged.

**Authority** (Phase 0 / Phase 1 distinction) rides on the same pattern:
- authoritative records (accepted diagnosis, promotion, approval decision, receipt, outcome) use a
  **solid left rule**;
- advisory records (hypotheses, reviews, drafts) use a **dashed left rule**.

That gives one rule: dashed = advisory, solid = authoritative, hatched = simulated.

**Simulated must be unmistakable when consequential:**
- **Demo mode:** a persistent frame band reading "Demo mode · simulated plant data" is shown
  (screen 19).
- **Charts:** simulated spans are hatched.
- **Outcomes:** a simulated outcome reads "Verified recovery (simulated)" and its check-circle gains
  a hatched backing.

Non-consequential simulated values (e.g. a simulator telemetry tick in Demo mode) rely on the
frame band rather than per-value tags, to avoid badge noise.

---

## 15. Data-state pattern: freshness, loading, stale, error, offline

### 15.1 Freshness states (R-1)

One table per source (the stream as a whole, and each asset's readings).

**Time basis (backend truth).** Stream messages carry a tick index (`tick`) and a simulated
plant-minute counter (`plant_time_min`), but **no wall-clock server timestamp**. History points
carry the tick index `t`. The tick interval (`POC_TICK_SECONDS`) is server configuration and isn't
exposed.
- **Until X8 exists (`08 §1.2`):**
  - Stream age = time since the **last message was received** (browser clock).
  - The **expected interval** is the median gap between recent message arrivals, measured over the
    last 10 ticks and never hard-coded.
  - Per-asset staleness = how many ticks behind the latest tick its last point is.
  - Every age is labelled as "received …".
- **With X8:** ages come from server timestamps.
- Evidence and record times already use real backend timestamps (`observed_at`, `retrieved_at`,
  event `created_at`).

| Freshness | Condition | Presentation |
|---|---|---|
| **Live** | Stream connected and age ≤ 2 × expected interval | "Live · 14:32:05". Nothing animates. |
| **Delayed** | Age > 2 × and ≤ 5 × expected interval | Values stay visible with their age: "Delayed · 25 s". Condition unchanged. |
| **Stale** | Age > 5 × expected interval | Clock glyph plus "Stale since 14:18". Asset condition becomes **Stale**, never Normal. Charts draw the stale region (§16). |
| **Disconnected** | WebSocket closed | Banner (below). All live regions show "as of 14:32:05". |

**Stale never becomes Normal.** This is a deliberate departure from tools that treat missing series
as "OK" (e.g. Grafana `Normal (MissingSeries)`, CloudWatch `notBreaching`). A derived value takes
the **worst freshness of its inputs**.

### 15.2 Data states

| State | Trigger (real data) | Pattern |
|---|---|---|
| Loading (initial) | No snapshot yet | Nothing for the first ~300–750 ms; then **static** region skeletons (no shimmer); after a few seconds a line with elapsed time: "Waiting for plant data · 12 s" (R-19). Never zeros. |
| Partial loading | Snapshot present; `GET /api/incidents/{id}` pending | Case header from the snapshot renders immediately. Sections awaiting detail show "Loading case record…" in place. Expiry shows "Deadline loading" (never a fabricated countdown). |
| Stale / Delayed | §15.1 | Shell status shows the worst stream freshness. **Mixed staleness** is stated, not averaged: "7 of 8 assets current · CNC-MILL-07 stale since 14:18". |
| Unavailable | A sensor or feature is missing (evidence quality MISSING, no history) | "No data" with a dashed-square glyph. Charts show a gap and a label. |
| Disconnected | WebSocket closed | Shell banner: "Live connection lost at 14:32:05. Showing last received data. Reconnecting…" Decision and submission controls become **inactive** (focusable, `aria-disabled`, reason "Reconnect to make decisions", activating moves focus to the banner; R-3). Deadlines state that they are computed from server time and that the view is disconnected. |
| Retrying / reconnected | Reconnect attempts; then a new snapshot | Banner shows the attempt and next try time, plus a manual "Reconnect now". After reconnection, the missed interval is **marked as a backfilled gap** on charts and noted in the case record where it overlaps a case. |
| Request failure | REST error | Inline alert at the point of action, with the backend's refusal message verbatim when it is a typed lifecycle refusal (stale revision, expired requirement). Never a generic "Something went wrong". |
| Provider failure | `reasoning_provenance.status = awaiting_runtime` or a provider error | Shell status shows "Analysis unavailable". Open cases in automated stages show "Analysis paused: provider unavailable" as an At-risk item (screen 24). |
| Offline (device) | `navigator.onLine = false` | Phone top bar: "Offline: you can read the last data; actions need a connection." Actions inactive with that reason. (Offline capture is future.) |
| Not configured | A capability exists but isn't set up (no provider, trusted submissions off, no external CMMS) | States what configuring does and who can do it, in place of the region (e.g. "No external CMMS is connected. Work orders are recorded by the local adapter.") |
| Permission | Backend refusal (e.g. trusted submissions disabled, loopback-only secret entry) | States the exact reason and who can change it: "Inspection submission is turned off in this deployment (`OPERON_TRUSTED_SUBMISSIONS`). An administrator can enable it." |

### 15.3 Message hierarchy (R-18)

1. **One banner for the cause** (disconnected, analysis unavailable, demo mode). No more than one
   banner per cause; never a toast for an outage.
2. **"As of" in each title block** that shows live values (the freshness indicator).
3. **Value-level glyphs only where a value's freshness differs from its region** (e.g. one stale
   asset among live ones). A disconnect does not put a glyph on every value.
4. **Announcements, once each:** Live → Delayed / Stale is announced politely; Disconnected is
   announced assertively.
5. **Print and export** stamp "Data as of {server time}".

**Freshness indicator (component):**
- `clock` glyph plus relative age plus absolute time on hover;
- placed at the right end of every title block that shows live values;
- shows the §15.1 state word (Live / Delayed / Stale / Disconnected) whenever it isn't Live.

**Rule:** an interface that can't prove data is current must say so before showing it.

---

## 16. Data visualisation standards

| Chart | Encoding | Rules |
|---|---|---|
| **Telemetry** (5 real channels: air temperature K, process temperature K, rotational speed rpm, torque Nm, tool wear min) | Line, `viz.series`. Focal channel `viz.series.focus`. | One y-axis per chart. Small multiples for several channels (shared x, **synchronised crosshair**). Unit in the axis title. Latest value as a direct label. The y-axis may start above zero, with a **minimum visible span** per channel so noise doesn't read as a trend. **No vibration channel exists in this fleet; never imply one.** |
| **Time axis and staleness** (R-2) | The x-axis always ends at **"now"**: the latest tick received (until X8) or server time (with X8). After an asset's last sample, a `viz.stale` region labelled "No data since tick 1,204" (until X8) or "since 14:18" (X8). | A stale chart can never look identical to a live one. Applies to sparklines too (a stale sparkline ends in the stale marker). Scope and time range sit next to the chart title. Until X8, telemetry axes are labelled in samples / ticks, never as invented clock times. |
| **Gaps** (R-2) | Break the line when consecutive samples are more than **2 × the expected interval** apart (missing tick indices until X8). Label the gap with start and end. | Distinguish a **sensor gap** (an asset's missing points while the stream continued) from a **connection gap** (no messages received; marked after reconnect). Never interpolate. |
| **Sample quality** | Samples with quality SUSPECT drawn as `viz.sample.suspect` hollow markers, excluded from the line | Missing samples follow the gap rule |
| **Risk trajectory** (model risk score 0–1) | Line plus `viz.threshold.warning` at 0.45 and `viz.threshold.critical` at 0.80, labelled at the line end ("Warning band 0.45", "Action gate 0.80") | Y-axis 0–1, labelled "Model risk score" (not "probability"). Detection, decision, dispatch and observation-start events marked. |
| **Thresholds / bands** | Dashed status lines; abnormal spans as tint bands **with text** | No colour-only bands. **Thresholds come only from backend values** (`warn_threshold`, `trigger_threshold`), labelled with their source. Never draw a default threshold; if a value is missing, draw none. Thresholds in view are always inside the y-domain. |
| **Baselines** | `viz.baseline` dotted, labelled "Baseline (diagnosis)" from `ObservationPlan.baseline_metrics` | |
| **Prediction intervals** | `viz.prediction.band` only (no dashed forecast line), labelled with horizon and basis | **No forecast exists in the backend today.** Specified for the future; not drawn in V2. |
| **Events** | Glyphs in an **event lane** under the x-axis, with a `viz.event` hairline up through the plot: detection (signal), decision (person-square, **neutral, never violet**), dispatch (document-check), observation start (eye), outcome (check-circle / circle-x) | Labels live in the tooltip, not inside the plot (R-17) |
| **Maintenance** | `viz.work.span` over the work-order window, labelled "WO-… window" | Field completion is not drawn (G10) |
| **Verification** | Post-observation-start samples as discrete markers. Outcome label at the end: "Verified recovery · last 3 scores < 0.45". | Before / after values from `Outcome.before_metrics` / `after_metrics` |
| **Comparison** | Focus + context, or small multiples | No categorical colours (§4.6) |
| **Reliability** | Counts as text and tables first. Bars only for comparing ≥ 3 categories. Time series only with real timestamps. | Scope label is mandatory ("This engine run · since 05 Oct 13:00", G9) |
| **Simulated** | `viz.simulated` hatch on spans and points from simulated sources; legend entry "Simulated" | |
| **Missing** | Gap plus "No data" label; never interpolated | See Gaps |
| **Chart states** (R-17) | Every chart container has loading, empty ("No samples in this window"), error (problem → cause → remedy, backend message verbatim) and partial ("3 of 5 channels available") states | No blank plot areas |

**Interaction and accessibility:**
- **Tooltip:** a crosshair on hover or focus shows the sample's position (tick and plant time until
  X8; HH:MM:SS with X8), value plus unit and provenance mark for every series at that x. It is
  keyboard-reachable: arrow keys step through samples.
- **Legend:**
  - direct labels for ≤ 4 series;
  - a legend for more;
  - the legend uses the same line styles: solid series, dashed thresholds, dotted baseline,
    banded predictions, hatched simulation. Provenance appears in the tooltip and legend, **not as
    a line style on telemetry** (dash budget, R-17).
- **Table alternative:** every chart has a "Table" toggle rendering the same data (time, value,
  unit, provenance) and an `aria-describedby` summary sentence ("Risk score rose from 0.31 to 0.86
  between 13:20 and 14:32; crossed the action gate at 14:30").
- **Sparklines:** only in Asset rows and the plant band's expanded cell, never in queues.
  - 64 × 16, `viz.series`, no axes;
  - last point marked;
  - threshold line shown only if the series crosses it.
- **Forbidden:** gauges, donut KPIs, gradient area fills, 3D, dual axes, rainbow palettes, animated
  chart intros, "AI prediction" glow.

---

## 17. Accessibility

| Area | Decision |
|---|---|
| Standard | WCAG 2.2 AA throughout. AAA contrast for primary text (achieved: ≥ 11.8:1 on every surface in both themes). |
| Colour independence | Every status has glyph, shape and word (§12). Provenance is never colour. Charts use line styles plus labels. |
| Contrast | Text ≥ 4.5:1 on its actual surface; non-text (control borders, focus, chart lines, status glyphs) ≥ 3:1. Verified per token in §4. |
| Focus | 2 px `border.focus` ring with 2 px offset (ink in light, paper in dark), always visible on keyboard focus (`:focus-visible`). Never removed. Never coloured by status. |
| Keyboard | All functions keyboard-operable. Queue lists:<br>• `↑` / `↓` (aliases `J` / `K`, R-21) move;<br>• `Enter` opens preview;<br>• `Shift+Enter` opens workspace;<br>• `Esc` closes preview and returns focus to the row.<br>Case sections: `g` + `1–6` jumps (documented in a `?` shortcut sheet). No single-key shortcuts for consequential actions. **Approve has no shortcut.** |
| Landmarks / names | `banner`, `navigation` (primary), `main`, `complementary` (inspector, context rail). Page title = `<h1>`. Sections `<h2>`. Status glyphs carry `aria-label` with the full meaning ("Asset condition: Critical"). Icon-only buttons have accessible names. |
| Live regions | Action-required changes and Live → Delayed / Stale are announced **politely**, once each; Disconnected is announced **assertively**, once (§15.3). Telemetry is never announced. Field validation errors are **not** announced through live regions (they're associated with their field). |
| Tables | Semantic `<table>` with `<th scope>`, sortable headers as buttons with `aria-sort`, row headers for the asset or case. The data grid uses the ARIA grid pattern only where cell navigation is needed (Audit log). |
| Charts | Summary sentence plus table alternative (§16) |
| Forms and errors | Label above the field. **Validate on blur after the user has changed a field, and on submit**; never on each keystroke (R-16). Errors below the field, associated with `aria-describedby` and `aria-invalid`. Two levels: **error** (blocks submit) and **warning** (allows submit, e.g. "rationale is short"). Error summary at top for multi-field submission (inspection). No placeholder-as-label. |
| Inactive vs disabled (R-3) | A consequential control blocked by state (Approve before acknowledgement, any decision or submission while disconnected, Submit inspection while trusted submissions are off) is **inactive**: focusable, `aria-disabled="true"`, its reason linked via `aria-describedby`, and activating it moves focus to the blocker (the checkbox, the connection banner, the explanation). Plain `disabled` only for controls that are irrelevant in the current context. A **busy** (submitting) control is never `disabled`: it keeps its label plus progress text and `aria-busy`. |
| Read-only | Bound identifiers, past decisions and recorded inspections are **read-only**: readable, selectable and copyable, never rendered as disabled inputs. |
| Dialogs | Focus moves to the dialog title, is trapped inside and returns to the invoker. `Esc` closes non-destructive dialogs; destructive confirmations require explicit cancel or confirm. Never auto-focus the destructive button. |
| Touch | Targets ≥ 44 px (48 px primary), ≥ 8 px apart. No gesture-only actions (no swipe-to-approve). |
| Reduced motion | §11 |
| Zoom / reflow | Usable at 200 % zoom on desktop. At 320 CSS px the phone layouts apply (WCAG 1.4.10). |
| Time limits | Approval expiry is a real backend constraint. The UI states the absolute deadline well in advance and never adds its own time limits. |
| Language | `lang` set. Identifiers wrapped so screen readers spell them where appropriate (`AC-COMP-01` read as letters). |

---

## 18. Component inventory

Families, not cosmetic variants. **Sizes:** sm = 28, md = 32, lg = 40, touch = 48 (§7.3).

**Every interactive component has the same state set:**
- default
- hover
- active
- focus-visible
- **inactive** (blocked by state: focusable, `aria-disabled`, reason linked; R-3)
- disabled (irrelevant in this context only)
- **read-only** (perceivable and copyable, not editable)
- busy (an action awaits the backend; never `disabled`)
- error and warning (inputs)

### 18.1 Actions and inputs

| Component | Variants | Sizes | Usage | Misuse |
|---|---|---|---|---|
| **Button** | `primary` (ink control) · `secondary` (`border.control` outline, text.primary) · `ghost` (text only, for low-emphasis row actions) · `danger` (`action.danger.fg` text plus border; for Reject and escalate and destructive admin; R-24, provisional for Reject) | sm, md, lg, touch | **One primary per view** (R-5): when the decision surface is on screen, every other button (including the case-header CTA) is secondary. Label is a verb plus object ("Approve and dispatch", "Submit inspection"). | Coloured primary buttons; icon-only primary actions; two primaries in view; "Approve" without object; a blocked consequential button rendered `disabled` instead of inactive (R-3). |
| **IconButton** | `ghost`, `secondary` | sm (28), md (32), touch (44) | Toolbar and row utilities (open in inspector, copy ID) with tooltip and accessible name | Consequential actions |
| **Input / Textarea** | default, with prefix (unit or mono), read-only | md, touch | Labels above; unit suffix in `text.tertiary` | Placeholder-as-label |
| **Select / Combobox** | single; combobox with search | md, touch | Combobox for ≥ 8 options (assets, actors) | Selects for ≤ 3 options (use segmented control) |
| **Checkbox / Radio** | standard; radio group | 16 px box (pointer), 24 px (touch) in 44 px target | Acknowledgement of contradicting evidence (decision surface); filters; **any single choice inside a submitted form** (e.g. Pass / Flag / Fail, R-16) | Checkbox as the confirmation of a consequential action without consequence text |
| **Switch** | standard | md, touch | Immediate, reversible settings (Preferences) | Anything that commits operational work |
| **Tabs** | underline tabs (2 px ink indicator) | md | Switching views of the same object (Asset: Condition / Telemetry / Cases / Work) | Case workspace sections (those are a scrollable document with an index, not tabs) |
| **Segmented control** | 2–4 options | sm, md | Choices that **apply immediately**: filters with few states (Active / Resolved / All); chart table toggle | Navigation; choices inside a submitted form (use a radio group, which may be *styled* as segments) |

### 18.2 Status and identity

| Component | Variants | Usage | Misuse |
|---|---|---|---|
| **Status marker** | One per dimension (§12): condition, stage, verification, work. Compact (glyph plus word) and expanded. | The only way status is drawn | Free-form coloured text; status word without glyph |
| **Attention marker** | rank glyph (slot A); group header | Queues and lists only | As a badge on detail pages |
| **Severity marker** | bars plus word | Case rows and header | Colouring by severity |
| **Badge / tag** | `tag` (mono identifier, hairline frame, 2 px radius) · `count` (neutral number in a group header) · `simulated` (hatched border, uppercase) | Identifiers, counts, simulated label | Status pills; "New" badges that persist; counts on navigation items other than My actions |
| **Provenance indicator** | mark (compact) · line (expanded) | Beside values and records | Giant badges on every datum |
| **Freshness indicator** | live · delayed · stale · disconnected (§15.1) | Title blocks, values | Animated "live" dots |
| **Actor mark** | human (initials in a 20 px square, 2 px radius, neutral) · system (Tabler `settings` gear) · analysis role (role abbreviation: DX, ENG, OPS, CRT, PLN) | Record rows, decisions, reviews | Avatars with photos or faces for analysis roles; chat-style bubbles |

### 18.3 Overlays and feedback

| Component | Variants | Usage | Misuse |
|---|---|---|---|
| **Tooltip** | text only, ≤ 2 lines | Explaining glyphs, truncated values, collapsed nav | Required information; interactive content |
| **Popover** | anchored panel | Filter editors, identifier details (copy) | Decisions |
| **Menu** | actions menu | Row overflow actions, account menu | Consequential actions hidden in a menu |
| **Dialog** | `standard` · `destructive` (type-to-confirm for admin reset) | Destructive admin actions, unsaved-changes guard | **Approval** (the decision surface is in-page); routine confirmations |
| **Drawer** | right **modal** drawer (preview / inspector below 1280, CH-2), bottom (phone filters) | Preview, filters on phone | Primary workflows; non-modal overlays that leave the page interactive behind them |
| **Toast** | neutral only, auto-dismiss 6 s (persist if it contains an action); **pauses on hover and focus**; announced politely | Confirmation of reversible actions ("Filter saved") | Errors, outages, decisions, anything operational (those are inline or banners) |
| **Inline alert** | info · warning · critical · decision (left 2 px rule plus glyph) | Request failures, refusals, conditions at a point of action | Decoration |
| **Banner** | shell-level: disconnected, analysis unavailable, demo mode | Global states affecting everything | Marketing or tips |
| **Empty state** | `clear` (nothing requires attention) · `none-yet` · `filtered` · `unavailable` (data / provider / backend) · `not-configured` · `not-permitted` | Every list and region (`08` §6) | Illustrations, cheerful copy |
| **Skeleton** | text line, row, chart block (static) | Initial loads: appears only after ~300–750 ms, then an elapsed-time line (R-19) | Shimmer; skeleton for partial updates; skeleton for data that exists but can't load (that is an error state) |

### 18.4 Navigation and structure

| Component | Notes |
|---|---|
| **Navigation rail** | 8 items in two groups (§ `08` 3.1). Active item: filled icon plus weight 600 plus a 2 px ink left bar. Only My actions shows a count. |
| **Breadcrumb** | Object pages only: `Cases / AC-COMP-01 · 05 Oct 13:02`. Mono for identifiers. |
| **Pagination** | Cursor "Load older" for Audit log; none for lists under 200 rows (virtualise beyond). |
| **Title block** | §9.4 |
| **Section heading** | `02` (mono `text.tertiary`) · title (`type.heading`) · meta (right, `type.caption`) · rule |
| **Section index** | Vertical list of the six case sections with their state summary ("Evidence · 7 · 1 open request"); highlights the section in view |
| **Stage track** | §13.2 |

### 18.5 Data display

| Component | Variants | Usage | Misuse |
|---|---|---|---|
| **Table** | compact / comfortable; sortable; selectable rows (single) | Comparable flat records. **The active sort is shown on load**, including a default multi-key sort ("Sorted by attention, then deadline"). One datum per column. Identifier cells `nowrap` with middle truncation and full value on hover / copy (R-13). Sticky header. Unknown values in words, never "—" (R-15). | Heterogeneous items (use list rows); whole-row status tinting |
| **Data grid** | cell-navigable, column chooser | Audit log only | Elsewhere |
| **List row** | one-line; two-line queue item (verb line plus context line) | Queues, updates | Card grids |
| **Metric / value** | value plus unit plus provenance plus scope label | Reliability counts, outcome metrics | Without a scope or source; as a hero number |
| **Telemetry value** | readout (24 px) or inline; with freshness | Asset detail, evidence rows | Values without time |
| **Sparkline** | §16 | Asset rows, plant band expansion | Queues, decorative |
| **Chart container** | title, scope, legend / direct labels, table toggle, summary | All charts | Charts without scope or table alternative |
| **Timeline** | record (dense, typed), stage history (inline) | Case record, Audit log detail | Social feed styling (avatars, bubbles, likes) |

### 18.6 Domain components

| Component | Content (fields from backend) | Notes |
|---|---|---|
| **Case row** | attention · asset (tag, name, condition) · stage · waiting on · severity or criticality · next step · deadline · updated | Compact by default |
| **Asset row** | class glyph · tag · name · line · condition (plus risk score) · sparkline (risk) · active case (stage) · last reading (receipt time until X8, labelled "received") | Condition and case are separate cells |
| **Work-order row** | WO number (mono) · asset · case link · technician · window · work state · verification state | Field status column reads "Not reported (G10)" |
| **Evidence item** | provenance mark · kind · summary · source (system / capability) · observed at · quality (Good / Suspect / Missing) · cited by | Row in the evidence table. Expandable. Opens in inspector. |
| **Hypothesis row** | outcome (Supported / Refuted / Unresolved / Open) · mechanism · failure mode · supporting n · contradicting n · confidence basis (text) · falsification tests | **No model self-reported confidence value is displayed anywhere in V2**: not in rows, not in the inspector, not with a disclaimer (product-owner correction A). Backend `confidence` fields on hypotheses, diagnoses and assessments are uncalibrated (`calibrated = False`) and are omitted from every view, including raw payload views. Investigation UI relies on evidence, basis text, supporting / contradicting observations, specialist results and other truthful backend values. No replacement percentage is invented. A calibrated, explicitly defined metric would need new backend work and a design decision. |
| **Review row** | role (Diagnostic / Engineering / Operations / Critic / Planner review) · verdict · key finding · challenges · run reference | No avatars; role abbreviations |
| **Recommendation block** | finding (cause) → consequence → recommended work, with evidence links | §screens 7–8 |
| **Approval panel (decision surface)** | §`08` screens 8 and 22 | The only approval UI |
| **Inspection control** | Per check: **Pass / Flag / Fail** as a labelled **radio group** (may be styled as 48 px segments; R-16), note field, evidence references; submit | Today the backend can record only *confirmed* checks (G1, plus new G13 in `08` §1). Roll-up rule in G13. |
| **Next-step block** | Verb, owner, deadline, action or "nothing to do: waiting on …" | Exactly one per case. Tint plus 2 px ink left rule, not a frame (R-11). Its action is secondary while the decision surface is on screen (R-5). |

---

## 19. Copy system

**Voice:** clear, technical, calm, specific, accountable (Phase 2.5 §17).
- Lead with the fact, then the consequence, then the required response.
- Numbers carry units and thresholds.
- The system "opened", "recorded", "found", "proposed"; it doesn't "think", "feel" or "want".
- Uncertainty is stated with its basis.

**Fleet-specific note:**
- The brief's example sentences mention vibration. This fleet has no vibration channel.
- The real channels are air and process temperature, rotational speed, torque and tool wear, plus
  the model risk score.
- Patterns below are written against the real data; for a future vibration channel the pattern is
  identical.

| Situation | Pattern | Example |
|---|---|---|
| Detection | **{Signal} above {threshold} on {asset}.** {value} at {time}. A case was opened. | "Model risk score above action gate on AC-COMP-01. 0.86 at 14:32 (gate 0.80). Likely failure mode: power failure. A case was opened." |
| Warning (no case) | **{Asset} entered the warning band.** {value} since {time}. No case opened. | "HYD-PUMP-03 entered the warning band. Risk score 0.52 since 13:58. No case is opened below the action gate." |
| Recommendation | **Recommended: {action} ({parts}).** Finding: {cause}. Basis: {evidence}. Reviews: {verdicts}. | "Recommended: replace drive-end bearing (PRT-BRG × 1). Finding: bearing wear. Basis: torque deviation since 02:10; technician inspection confirmed wear. Critic review: accepted." |
| Approval request | **Decision required by {time}.** Approve the exact work package for {asset}: {summary}. Approving dispatches it immediately: {consequences}. | "Decision required by 15:12. Approving dispatches immediately: creates a work order, reserves 1 part, books TECH-201 for 13:12–15:12 and records a technician notification." |
| Approved | **Approved by {actor} at {time}.** Dispatching work package {hash}… | — |
| Request changes (G4) | **Changes requested by {actor}.** The plan returns to planning with your comments. | Not offered until G4 |
| Reject (today) | **Rejected and escalated by {actor} at {time}.** Reason: {reason}. Automated progress has stopped; an engineering decision is required. | Shown in the record; the decision surface warns before submitting |
| Escalation | **Escalated: engineering decision required.** {cause}. No work is planned. Resolving escalations isn't available in this version (G2); this asset can't open a new case until it is resolved. | — |
| Missing data | **No data from {asset} for {age}.** Condition can't be assessed; shown as No data, not Normal. | — |
| Provider failure | **Analysis unavailable.** {provider} isn't responding ({error}). Cases in automated stages are paused. Deterministic analysis is {available / not configured}. | — |
| Inspection request | **Inspect {asset}: {question}.** Check: {falsification tests}. Requested by diagnostic review at {time}. | — |
| Inspection submitted | **Inspection recorded by {actor} at {time}.** Result: {mechanism confirmed}. The case returns to investigation. | — |
| Work committed | **Work order {WO} committed.** {technician}, window {start–end}. Field completion isn't reported to this system (G10). | — |
| Dispatch failed | **Work order not confirmed.** {reason}. Nothing was dispatched (or: dispatch state unknown). Waiting on the approver. Retry isn't available in this version (G3). | — |
| Verification success | **Recovery verified.** Last 3 risk scores after the work ({values}) are below the 0.45 warning band; baseline {value}. Case closed. | — |
| Verification failure | **Not recovered.** {n} scores observed since {time}; none below 0.45. The case returned to investigation. / **Regressed.** Risk rose above {baseline} after the work. The case is escalated. | — |
| Inconclusive | **Verification inconclusive so far.** Observing since {observation_start}. Observation continues. (A sample count is shown only once X8 makes it truthful.) | — |

**Never:** exclamation marks, "Oops", "Something went wrong", "AI-powered", "smart", "Our AI
thinks", emoji, "Resolve" meaning acknowledge, "Done" meaning verified, percentages for model
self-confidence.

**Product naming in copy:** "the application" or the passive voice; never the product name inside
workflows (§1.4).

---

## 20. Confirmation philosophy

| Consequence class | Examples | Friction |
|---|---|---|
| Reversible, personal | Theme, density, filters, read state, collapsing groups | None. Toast only if the effect is off-screen. |
| Operational, reversible | Sending an investigation instruction (a new revision supersedes it) | Inline confirmation after the action; no modal |
| **Operational, consequential** | Inspection submission (G1); resource confirmation (G1) | A review step listing exactly what will be recorded and bound (case revision), then **Submit**. No modal. |
| **Decision** | Approve and dispatch · Reject and escalate · (Request changes, G4) | The **decision surface** (in-page). Approve needs no second confirmation; the surface *is* the confirmation. Reject requires a reason and states its consequence. |
| Destructive admin | Reset engine (clears runtime state), stop simulation, provider credential change | `destructive` dialog stating what is lost; type-to-confirm for reset ("RESET") |

**Fatigue control:** no "Are you sure?" on anything reversible, and no double confirmation of
decisions.

---

## 21. Responsive strategy and role-aware presentation

### 21.1 Workflow classes

| Class | Workflows |
|---|---|
| **Desktop-first** (tablet read; phone not a target) | Case investigation detail, Reliability, Audit log, System, Simulation & Demo, Assets table |
| **Fully responsive** | Overview, Cases list, case summary and next step, Asset detail (condition, active case), Work orders |
| **Mobile-task optimised** | My actions, technician task and inspection, approver mobile decision, asset lookup (QR to asset URL) |

### 21.2 What happens on smaller screens

| Element | Tablet (768–1279) | Phone (< 768) |
|---|---|---|
| Nav rail | Collapsed 56 px icons with tooltips | Bottom bar: My actions · Cases · Assets · More |
| Preview / inspector | Modal drawer (scrim, focus trap; CH-2) | Full-screen sheet with back (one pane at a time) |
| Case context rail | Folds into Summary | Next-step block at top |
| Case sections | Same document | Sequential accordion; one open at a time |
| Tables | Fewer columns (priority order per screen) | Two-line list rows |
| Charts | Full width | Latest values plus a 1-channel sparkline; full chart on demand |
| Record | Full | Last 10 events plus "Open full record" |
| Decision | Full surface | Phone decision layout (screen 22) or handoff |
| System, Simulation | Read and act | Read-only status; actions hidden with "Use a larger screen" |

### 21.3 Role-aware presentation

Same product and navigation, different defaults. Roles come from Preferences: a
**presentation-only** choice until G8 provides identity. **No permission is enforced by the
UI.** Copy never implies it is.

| Role | Landing | My actions shows | Emphasis |
|---|---|---|---|
| Reliability engineer | Cases (filtered: Investigating, Awaiting inspection, Escalated) | Escalations; investigations needing direction | Investigation sections expanded |
| Technician | My actions | Inspection requests; work orders in their window (by technician ID once G8) | Mobile task layout; evidence summaries |
| Supervisor / approver | My actions | Decisions; resource confirmations; dispatch failures | Decision surface; deadlines |
| Operations / plant supervisor | Overview | Action-required items across roles (read) | Plant band; active cases |
| Administrator | System | Provider and data-health issues | System status details |

The observer / manager role from Phase 1 maps to Reliability as landing.

**Actions are never hidden by role.** They are shown with the statement "Recorded as
{role} (declared, not verified: G8)".

---

## 22. Search and filtering

**No global search in V2.**
- **Why:** Phase 1 justified search by "many identifiers", but the plant has 8 assets and at most 8
  projected cases.
- **Local filters plus breadcrumbs plus deep links cover every job.**
- Revisit when G5 makes history large.

**Instead:**
- **Asset lookup:** a jump-to-asset field in the Assets page header that also accepts QR-scanned
  asset URLs on phone.
- **Command palette (`Ctrl/⌘ K`):** navigation only (pages and the 8 assets). Deferred to the
  accessibility-polish slice; optional.

| Surface | Search | Filters | Default |
|---|---|---|---|
| My actions | — | Response type (approve / inspect / confirm / resolve), asset, role scope (mine / all) | Mine |
| Cases | Text over asset tag and name | Status (Active / Exceptions / Resolved), stage, waiting on, asset | Active |
| Assets | Tag or name | Condition, class, line, has active case | All |
| Work orders | WO number, asset | Work state, verification state, technician | Committed |
| Audit log | Text over event summary | Actor, action (event type), case, asset, time range, decision (approve / reject), system / provider events | Last 24 h |

**Filter UX:**
- `key:value` chips above the list; each chip removable;
- "Clear filters" appears whenever any non-default filter is active;
- result count "6 of 8 cases".

**Persistence:**
- Filters persist per page in the URL query (shareable) and in session storage (per tab).
- Defaults restore on "Clear".
- **Filtered-empty** states always name the active filters (`08` §6).

---

## 23. What V2 rejects (binding)

The brief's §51 list, with the system mechanism that enforces each item:

| Rejected | Enforced by |
|---|---|
| Generic KPI-card dashboard | Board template (§8.3), no metric cards (§9.3), Overview spec (screen 1) |
| Chatbot home or page; AI orb, glow | Investigation is typed records (screens 5–7); §10 icon bans |
| Neon, cyberpunk, gaming, military, glass, gradients | §1.3, §4 (four restrained hues), §9.5 (no blur), §11 (no glow or pulse) |
| Everything in cards; rounded-pill overload | §9.3, §9.5 (radius ≤ 4) |
| Colour-coded everything; excessive badges | §4.3 colour budget; §12.4 rule 2 |
| Fake analytics, financial values, confidence | §2; `08` §1 data sources; Reliability screen 16; no `business` snapshot fields displayed |
| Fake live status; ambiguous stale data | §15 |
| Hidden approval consequences | Decision surface (screen 8) |
| "Resolve" meaning acknowledged; execution meaning verification | §12.2 work vs verification vocabularies; §19 |
| AI output without evidence | Hypothesis and recommendation rows require evidence links; rows without evidence show "No evidence cited" |
| Shrunk desktop on mobile | §21 |
| Dark styling for "technical" look | §5.3 (OS-driven theme) |
| Decorative industrial motifs | §1.3, §10 |

---

## 24. Contradictions with earlier phases: decisions recorded

| # | Earlier position | Phase 3 decision | Reason |
|---|---|---|---|
| R1 | Phase 2.5 §12: five status hues incl. "executing" blue | **Four hues**; executing / in work is neutral | Blue and violet collapse under CVD (ΔE 0.6–1.9); in-work is a process state, not an alarm |
| R2 | Phase 2.5 §12: light warning `#B36200` ("darken for page") | **`#7F5C00`** | 5.54:1 on brand Paper (5.36:1 on the reconciled light shell `#F1F0EC`); better critical separation under deutan |
| R3 | Phase 2.5 §11: light page `#F4F5F4`, white panels | Shell on a warm paper tone; working area = full-bleed sheet `#FAFAF8`; white only for inputs and overlays. *Reconciled after Phase 3.1:* shell `#F1F0EC` (R-9 starting value), brand Paper `#F3F4F1` unchanged. | Avoids "white cards on grey"; makes the drawing-sheet idea literal; the 1.056 step of brand Paper on the sheet was too low (`09 §16.6`) |
| R4 | Phase 2.5 §15: validated categorical palette for comparisons | **No categorical palette in V2** | Overlaps status hues; comparisons use focus + context |
| R5 | Phase 1 §9: global search | **No global search**; local filters plus asset jump | 8 assets, ≤ 8 projected cases; revisit after G5 |
| R6 | Phase 1 §15: "Act now", "Needs you", "Incident"; Phase 1 stage "Execution failed", "Needs inspection" | "Action required", "My actions", "Case" (Phases 2 / 2.5); **"Dispatch failed"**, **"Awaiting inspection"** | Accuracy: execution is dispatch to the CMMS adapter; consistent stage grammar |
| R7 | Phase 1 §15: waiting-on "Agent" | **"Analysis (automated)"** | No anthropomorphism (brief §3.8) |
| R8 | Phase 1 §14 / Phase 2 §7: decision verbs "Approve and dispatch / Reject / Request changes" | **"Approve and dispatch · Reject and escalate"** offered today; **"Request changes"** not rendered until G4 | Today REJECT always escalates (`lifecycle.py`); naming it plainly avoids a silent mapping |
| R9 | Brief §24: "completed" work state | Field completion is **not** a backend fact; shown as "Not reported (G10)" | `work_order.status` is written once; observation starts at dispatch confirmation |
| R10 | Brief §31: inspection Pass / Flag / Fail | Designed now; backend accepts only *confirmed* checks (`PerformedCheck.passed: Literal[True]`) | Recorded as proposed gap **G13** (`08` §1); not mapped onto the existing contract |
| R11 | Phase 2.5 §9: Plex condensed width for headers | Width axis **not used in product UI** | Legibility over character at UI sizes (Phase 2.5 §21 rule 2) |
| R12 | Phase 1 "Performance", Phase 2 "Reliability (conditional)" | **Reliability** (product-owner nav, Phase 2.5) | Accepted IA |

**Phase 3.1 reconciliation (product-owner reviewed; record in `09 §22`):**

| # | Phase 3 position | Reconciled baseline | Where |
|---|---|---|---|
| CH-1 | Violet `#6B47CC` / `#A98BF5`; violet top rule on the decision surface | Option A: `#674EB0` / `#AA95E8`, glyph plus role word only, Ink decision rule, adjacency bans, recognition test with Ink fallback | §4.3, §9.2–9.3 |
| CH-2 | Preview docks ≥ 1440; 1024–1439 "overlay, no scrim" | Docked ≈ 380 px ≥ 1280; modal drawer < 1280; one pane on mobile (prototype hypothesis) | §8, §18.3, `08 §4` |
| R-1, R-18, R-19 | Live < 10 s / Stale > 3×; skeleton 2 s | Live / Delayed / Stale / Disconnected; message hierarchy; skeleton timing | §15 |
| R-2, R-17 | 90-sample window; dashed forecast line; in-plot event labels | Axis ends at "now", stale region, gap rule, suspect markers, chart states, bands, event lane | §4.6, §16 |
| R-3, R-16 | `disabled` consequential controls; form rules thin | Inactive vs disabled vs read-only; validation timing and levels; radio group; toasts | §17, §18 |
| R-4 | 10 / 12 px status shapes; status overlays | ≥ 14 px (16 px band and title block); overlays dropped | §7.3, §10 |
| R-5, R-11 | Header CTA primary; next-step block framed | One primary per view; tint plus ink left rule; one framed object per region | §9.3, §18 |
| R-6, R-7, R-8 | Up to 9 title-block cells; uppercase eyebrows widely; rules unbudgeted | ≤ 6 cells; uppercase only in title-block and rail-group labels; rule budget | §6.2, §9.4, §5.2 |
| R-9, R-25 | Light shell `#F3F4F1`; dark sheet `#161A1C`, text `#E8ECEE` | `#F1F0EC`; `#1A1F21` and `#DDE2E4` (Phase 4A starting values) | §4.2 |
| R-13, R-14, R-15, R-22 | — | Identifier truncation; aggregate rule and glyph budget; words, not "—"; stage track not a stepper | §12, §13, §18 |
| R-24 | Danger button used the critical status colour | Separate `action.danger` token; Reject's danger emphasis provisional | §4.2, §4.3 |
| PO-A | Uncalibrated confidence shown in the inspector with a disclaimer | Never displayed anywhere in V2 | §18.6 |
| PO-B | Flood control collapsed items | Presentation-only, always expandable; not implemented without safe expansion | §12.5 |

No earlier phase document (00–06) was edited. These decisions supersede the earlier positions for
Phase 4.

---

## 25. Visual direction: self-evaluation

| Question | Assessment |
|---|---|
| Tacky or edgy? | No. There are no effects, gradients or novelty shapes; character comes from ruled structure and typography. The risk is austerity, mitigated by the warm Paper, generous decision regions and plain language. |
| Cyberpunk, gamer-like or military? | No. No neon, black-and-green, HUD frames or angular chamfers. Monochrome could read as defence-tech (Phase 2.5 risk); the warm light theme, Plex Sans and real units counter it. Dark is graphite, not black. |
| Does "industrial" become dark sci-fi? | No. Industrial is expressed as tags, title blocks, units and ISA-101 restraint. Theme follows the OS. |
| Generic AI SaaS? | No. No AI motifs or assistant surface. Analysis is typed records and roles. |
| Generic component-library dashboard? | No. Title blocks, ruled sections, the stage track, ink controls, provenance marks and instrument tags are not library defaults. Radius ≤ 4 and the absence of cards remove the default look. |
| Card-heavy? | No. Four framed object types only, at most one per viewport region (§9.3). |
| Excessively rounded? | No. Maximum 4 px. No pills. |
| Operational colour overused? | No. Four hues with one meaning each, a per-row limit of two hued glyphs and a ~20 % screen budget. Attention, severity, provenance and in-work are neutral. Violet is confined to the person glyph and role word. |
| Light mode intentionally designed? | Yes. Its own surface logic (Paper desk, sheet, white only for inputs and overlays), its own status steps and rule weights. |
| Dark mode restrained? | Yes. Graphite surfaces, lighter-is-higher, bright-but-controlled status, no glow. |
| Useful information removed to look clean? | No. Compact density for comparison surfaces; title blocks carry stage, waiting-on, deadline and revision; identifiers stay visible on the decision surface. |
| Distinctive without a logo? | Yes, through the eight signature elements in §1.2, especially the stage track with its hold point and the title blocks. |
| Credible for eight-hour use? | Yes. No motion while nothing changes, low-glare dark, normal recedes, stale is explicit and there are no animated attention-seekers. Residual risk: the plant band's quietness must be validated with operators so abnormal cells are noticed fast enough (Phase 4 usability check). |

---

## 26. Status of open items

The product owner approved Phase 3 in principle and reviewed Phase 3.1 (`09 §22`).

| Item | Status |
|---|---|
| R1 four hues; R3 sheet logic; OS-driven theme; R5 no global search; R7 "Analysis (automated)"; R6 stage names; phone approval under the screen-22 rules; favicon placeholder | Accepted with Phase 3 |
| G13 (structured inspection result) and G14 (attachments) | Accepted as proposed backend gaps (Phase 6) |
| Projection exposures X1–X8 (`08 §1.2`) | Phase 6 backend decisions. Phase 4 uses the documented fallbacks. |
| CH-1 violet, CH-2 preview, R-9 / R-25 starting values, Reject's danger emphasis | **Phase 4A gate items:** confirmed or revised after the screenshot / usability review (`08 §11`) |
