# OPERON V2: Final public-name selection

Status: final naming exploration, recommendation only. **Nothing has been renamed.** README
branding is unchanged, no domains were bought, no logos were made, and Phase 3 has not started.
OPERON remains the repository and internal codename. That covers the repository, Python modules,
packages, protocols, environment variables, migrations, database identifiers, tests and provenance
identifiers.

**This is not legal advice.** It is a preliminary screen, and nothing in it amounts to trademark
clearance (see §15).

## How this round builds on the last

The inputs are Phase 2.7 (`05-coined-name-exploration.md`, commit `b4630ae`) and the human review
of it:

| Decision | Names |
|---|---|
| Kept | **Trevane** (benchmark to beat, not approved), **Sorvel**, **Tallis** (weaker comparison) |
| Eliminated | Stedra, Halvard, Ergane, Varro, Moraine, Tribos, Orrery |

None of the eliminated names, nor obvious variants of Ergane, were reused.

The lesson taken from Phase 2.7 is that a clean namespace is necessary but not sufficient.
Trevane won mostly because nobody else was using it. This round therefore adds **brand
desirability** as the heaviest single criterion. It also adds a product-owner reaction-risk
rating that sits outside the numeric score.

**Method (2026-10-05):**
- **Candidates:** about 30 serious candidates (26 new plus the 3 retained benchmarks), drawn from 6
  naming philosophies. Weaker ideas were discarded privately before this list, as instructed.
- **Quality filter:** 26 new names cut to 15.
- **Collision screening:** three parallel passes on those 15. Each name got 6–8 web queries
  covering software, AI, industrial technology, manufacturing, reliability, predictive maintenance
  and trademarks, plus checks on GitHub, npm, PyPI and seven domain patterns.
- **Spot checks:** I re-searched the leading candidates myself. This changed one result: the
  screening pass had missed an exact-name reliability-engineering firm for Alidade.
- **Wordmark test:** IBM Plex set in uppercase and title case, on Ink and Paper.
- **Copy and scoring:** a product-copy test, then scores out of 100 for the top 8 using the new
  weights.

**Evidence labels** used throughout:

| Label | Meaning |
|---|---|
| **[F]** | Verified fact: something I queried directly (npm or PyPI registry status, DNS resolution, the GitHub repository search tool) |
| **[S]** | Search-result evidence: a search-engine summary. Company sites, USPTO, EUIPO, IP India and domain marketplaces are blocked by this session's egress proxy, so the pages themselves were not read. |
| **[I]** | My inference |
| **[U]** | Unknown or unverified |

DNS "RES" means a domain resolves, so it is registered. "NX" means it does not resolve. **NX does
not mean a domain is available.**

---

## Verdict

### TREVANE REMAINS BEST

Confidence is **moderate** that Trevane is the best name found across both rounds, and
**low-to-moderate** that it is the best name achievable.

- **No new candidate clearly beats it.**
- **Turnstone** is the most likeable alternative and the strongest in product copy. It is held
  back by an active AI agent-orchestration project of the same name, which also owns the PyPI
  name, and by Steelcase's Turnstone furniture brand.
- **Kenning** is the cleanest new name. It has less industrial credibility and sounds like a
  surname.
- **Alidade** was the most desirable new name until a spot check found *Alidade Maintenance,
  Engineering and Reliability*. That firm is a reliability-engineering consultancy selling to the
  same buyers. It disqualifies the name in practice.
- This round **does not upgrade Trevane** from "acceptable" to "great". It only shows that a
  further round of AI-generated names is unlikely to beat it.
- **Recommendation for the product owner's review:** say Trevane aloud in the product sentences
  (§11).
  - If it lands, take it to professional trademark clearance.
  - If it does not, commission **human or professional naming**. Do not start another round of
    this exercise.

---

## 1. Naming philosophies and candidates

There were 29 serious candidates: 26 new and 3 retained benchmarks. The pure-coined philosophy
produced the fewest names I could defend. Most invented words came out sounding like drugs,
like people's names, or like near-copies of Sorvel or Trevane, so they were discarded privately
as instructed.

| Philosophy | Candidates |
|---|---|
| A. Pure coined | Vantel · *(benchmarks: Sorvel, Trevane)* |
| B. Adapted technical or scientific roots | Groma · Alidade · Pelorus · Skopos · Histor · Cardo · Invar · Constat |
| C. Indirect conceptual | Fermata · Legato · Kenning · Velin · Tidemark · *(benchmark: Tallis)* |
| D. Strong compounds | Turnstone · Fairlead · Sightglass · Daymark · Ironbark |
| E. Unexpected | Plimsoll · Andon · Gemba · Varde |
| F. India-origin | Spanda · Nidana · Tarka |

---

## 2. Rejected before collision screening (11)

| Name | Philosophy | Why rejected |
|---|---|---|
| Vantel | A | Invented and generic. It reads like "vantage" plus a telecom suffix and has no character. I would not defend it to a customer. |
| Histor | B | Greek *histōr* means "witness, one who knows", which fits well. But Histor is a Dutch paint brand (GK, unverified), and the name echoes "history" and "hysteria". |
| Cardo | B | Latin "hinge" and the Roman surveyed axis. Collides with Cardo Systems (motorcycle intercoms) and Cardo AI (fintech) (GK). |
| Invar | B | The alloy used in precision instruments because it barely expands with heat. It is a generic material name and an alloy trademark, so it cannot be owned in our sense. |
| Constat | B | Latin "it is established"; legally, a certificate of what is on the record. Functional rather than desirable. In French, *constat amiable* is a car-accident report. |
| Velin | C | French *vélin*, vellum. It reads as a given name (Bulgarian Velin), which breaks the first-name rule. Also an Arches paper line. |
| Daymark | D | An unlit navigational beacon. Daymark Solutions (IT services) and DayMark Safety Systems already use it (GK), and *-mark* compounds are saturated (Phase 2.6). |
| Ironbark | D | A very durable hardwood. The register is mining and ruggedness, and Ironbark Zinc and Ironbark Capital use it (GK). |
| Gemba | E | Lean manufacturing's "actual place". A generic industry term (Gemba Academy and others), so it cannot be owned. |
| Varde | E | Norwegian *varde*, a cairn or beacon. Pronunciation is ambiguous (VARD or VAR-deh). Danish town. |
| Tarka | F | Sanskrit *tarka*, "reasoning". In UK and Indian menus "tarka dal" is a lentil dish, and *Tarka the Otter* is a children's book. It fails "Have you checked Tarka?". |

GK means general knowledge, used only to reject a name early. It is not a claim about trademark
status.

---

## 3. Collision screen of the top 15, plus spot checks

| Name | Main findings | npm / PyPI [F] | DNS [F] (.com .ai .io get- -hq -systems -ops) | Risk |
|---|---|---|---|---|
| **Kenning** | **[S]** No company named Kenning in software, AI, industrial or reliability. **[S]** Antmicro's open-source *Kenning* is a framework for deploying ML on edge devices; one case study is industrial sorting machines, so it is adjacent. **[S]** Near names: Kennen Technologies (enterprise SaaS), KENN Software (Kolkata ERP). **[F]** 102 GitHub repos, the top one antmicro/kenning (147★). | free / free | RES RES RES RES RES NX NX | **LOW–MODERATE** |
| **Alidade** | **[S]** *Alidade Maintenance, Engineering and Reliability* (Satellite Beach, FL, founded 2004) sells maintenance management and reliability-engineering services. This is a **direct overlap**, found in my spot check and missed by the screening pass. **[S]** Alidade Technology (PA) does IBM lifecycle management, compliance automation, safety and traceability. **[S]** Alidade AI does messaging intelligence. **[S]** Alidade Systems provides IT leadership for mid-market manufacturers. **[S]** A US ALIDADE mark for survey software was cancelled in 2015. Near name: Alida (customer-experience SaaS). | taken / taken (tiny 2026 CAD viewer) | RES RES RES NX NX RES NX | **HIGH** (revised up from LOW–MODERATE) |
| **Turnstone** | **[S][F]** turnstonelabs/turnstone is a "multi-node AI orchestration platform with tool use, agent routing" (1,333★, 2026). It also holds the PyPI name. **[S]** Turnstone is Steelcase's office-furniture brand, founded 1993. **[S]** Turnstone Biologics (biotech), Turnstone Systems (former DSL hardware company). No industrial or reliability use. Can be confused with "Turnstile". | taken / taken | RES RES RES RES RES NX NX | MODERATE |
| **Groma** | **[S]** Groma LLC (Boston) is a proptech company using AI for multifamily operations. It raised a $29M Series A, holds groma.com and **sued another company over the mark** in 2022. **[S]** Bitsight Groma is an internet scanner for cyber assets and ICS/OT, inside a security product. No reliability use. Russian *грома* means "of thunder". | free / taken (placeholder) | RES RES RES NX RES NX RES | MODERATE |
| **Plimsoll** | **[S]** *Plimsoll* (Minneapolis, founded 2026) makes regulatory-compliance records and operational-documentation tools; its competitors are maritime, so it is adjacent to our "record" positioning. **[S]** Plimsoll Publishing (UK) sells business-risk intelligence SaaS. **[F]** Small 2026 repos use the name for AI verification gates. **[S]** Also a British word for a canvas gym shoe. | taken / taken | RES RES NX RES RES RES NX | MODERATE (revised up from LOW–MODERATE) |
| Tidemark | **[S]** Tidemark was a performance-management SaaS company that merged with Longview in 2017. Tidemark Capital is a vertical-software venture firm. **[F]** tidemark-security/intercept is a security case-management project. In British and Indian English a "tidemark" is also a ring of dirt. | free / taken | 6 of 7 RES | MODERATE |
| Skopos | **[S]** Skopos Security Labs (cyber risk for port operational systems). **[S]** Skopos, an ERP consultancy for industrial companies. **[S]** Sounds like **Scops.ai**, an AI predictive-maintenance company. Easily misspelled after hearing it. | taken / taken | RES NX RES RES RES RES NX | MODERATE |
| Nidana | **[S]** No exact-name company. Close to Nidan Labs (Indian diagnostics). In Hindi *nidān* simply means diagnosis, so the name is descriptive. It also sounds close to निधन *nidhan*, "death", which appears daily in Indian news. | free / free | RES RES RES NX NX NX NX | MODERATE (with a meaning problem) |
| Pelorus | **[S]** Pelorus Technologies Pvt Ltd (Mumbai, about 184 staff) does AI, forensics and surveillance. **[S]** Pelorus Technology (Dynamics ERP for manufacturers). **[F]** dora-metrics/pelorus (253★). The stress is ambiguous, and it sounds like "pylorus", part of the stomach. | taken / taken | NX RES RES RES RES RES RES | HIGH |
| Spanda | **[S]** Spanda.AI is an Indian enterprise AI platform. **[S]** SpandanSCADA is Indian industrial-automation SCADA software. The word carries heavy spiritual and yoga associations. | taken / taken | RES RES RES RES NX RES NX | HIGH |
| Fermata | **[S]** Fermata (Israel) is a funded computer-vision AI that detects crop pests and disease. **[S]** Fermata Energy (V2X charging, now Nuvve). **[S]** Fermata Discovery, an investigation-workflow SaaS. **[S]** FERMÀT, an e-commerce platform. In Italian it means "stop" and also police detention. | taken / taken | RES RES RES RES NX NX NX | HIGH |
| Legato | **[S]** Legato Sapient, an MES and machine-monitoring product (Kontron AIS). **[S]** Legato AI ($7M seed, 2026) builds "governed apps, workflows and AI agents". **[S]** Legato Systems/EMC marks. **[S]** Legato Health (now Carelon), a large employer in India. | stub / free | NX RES RES RES RES RES NX | HIGH |
| Fairlead | **[S]** Fairlead Integrated is a US Navy maintenance and power-systems contractor. **[S]** Fairlead Inspection & Testing (Gujarat). **[F]** The PyPI `fairlead` package is described as an "auditable **evidence and governance kernel** for LLM and agent applications", and the npm package as "guardrails for coding agents". | taken / taken | RES NX NX NX RES RES NX | HIGH |
| Sightglass | **[I][S]** A *sight glass* is a generic level window found in the very plants we sell to, so the name is descriptive and its search results are swamped by hardware. **[S]** Sightglass is also an AI investor-relations startup, and SightGlass Vision holds marks. | taken / taken | RES NX RES RES RES NX NX | HIGH |
| Andon | **[S]** A generic lean-manufacturing term, with many Andon software products, including Andonix (AI predictive maintenance). **[S]** **Andon Labs** (YC W24) works on AI-agent autonomy and safety. | taken / free | 6 of 7 RES | VERY HIGH |

**Benchmarks**, from Phase 2.7 with this round's re-check:

| Name | Main findings | npm / PyPI | DNS | Risk |
|---|---|---|---|---|
| Trevane | **[S]** No active software, AI, industrial or reliability company. **[S]** Near names: TrevanAI (consumer chat agents on Telegram, trevanai.com), Trevena (biopharma), USPTO TREVANSOFT (status unverified) and TREVANNA TRACKS. **[S]** trevane.com is reportedly listed on BrandBucket. | free / free | RES NX NX NX NX RES NX | LOW–MODERATE |
| Sorvel | **[S]** No company in an adjacent field. "Sorvelutik" is a cluster of crypto-trading scam sites. Footballer Neil Sorvel. | free / free | RES NX NX NX NX NX NX | LOW–MODERATE |
| Tallis | **[S]** Tallis Engineering & Consulting (UK) does petrochemical maintenance and turnarounds. Searches are dominated by the composer Thomas Tallis. | free / free | RES RES RES NX NX NX NX | MODERATE |

**Process note.** The screening pass rated Alidade LOW–MODERATE, and my spot check found a
reliability firm of the same name. That is a concrete example of why every result here is
preliminary and must be repeated professionally (§15).

---

## 4. Top 8, scored out of 100

**Weights:**

| Criterion | Weight |
|---|---|
| Brand desirability | 15 |
| Distinctiveness | 12 |
| Collision / search risk | 12 |
| Pronunciation | 10 |
| Memorability | 10 |
| Industrial credibility | 10 |
| Enterprise credibility | 8 |
| Spelling | 6 |
| Expandability | 6 |
| Visual identity | 6 |
| Product-language fit | 5 |

Collision scores follow the risk levels: LOW–MODERATE ≈ 9–10, MODERATE ≈ 5–6, HIGH ≈ 3.

Owner risk is the **product-owner reaction risk**: how likely the name is to seem clever on
paper but feel unpleasant as an actual brand.

| Rank | Name | Desir /15 | Dist /12 | Coll /12 | Pron /10 | Mem /10 | Ind /10 | Ent /8 | Spell /6 | Exp /6 | Vis /6 | Lang /5 | **Total** | Collision risk | Owner risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Trevane** *(benchmark)* | 8 | 9 | 10 | 6 | 6 | 7 | 6 | 4 | 5 | 5 | 4 | **70** | LOW–MOD | MEDIUM |
| 2 | **Turnstone** | 10 | 6 | 5 | 9 | 8 | 6 | 7 | 5 | 5 | 3 | 5 | **69** | MODERATE | LOW |
| 3 | **Kenning** | 9 | 8 | 9 | 8 | 7 | 5 | 6 | 4 | 5 | 5 | 2 | **68** | LOW–MOD | MEDIUM |
| 4 | Alidade | 11 | 10 | 3 | 6 | 7 | 9 | 7 | 4 | 5 | 4 | 4 | **70** | **HIGH** | MEDIUM |
| 5 | Groma | 7 | 9 | 5 | 9 | 7 | 7 | 5 | 5 | 5 | 5 | 4 | **68** | MODERATE | HIGH |
| 6 | Sorvel *(benchmark)* | 6 | 8 | 9 | 8 | 5 | 5 | 5 | 5 | 5 | 4 | 3 | **63** | LOW–MOD | MEDIUM |
| 7 | Plimsoll | 7 | 9 | 6 | 6 | 8 | 7 | 5 | 3 | 4 | 3 | 3 | **61** | MODERATE | HIGH |
| 8 | Tallis *(benchmark)* | 6 | 5 | 6 | 9 | 7 | 5 | 6 | 4 | 4 | 2 | 3 | **57** | MODERATE | MEDIUM |

**Where judgement overrides the numbers, as instructed:**
- **Alidade (70) is ranked 4th, not joint 1st.** Its collision is with a firm that sells
  reliability engineering to our buyers. That blocks it qualitatively, whatever the total says.
- **Turnstone (69) and Kenning (68) are ranked above Groma (68).** Groma's owner holds the .com and
  has litigated over the mark. Groma also sounds blunt in speech ("grom", "groan", "grime").
- **Trevane scored 81 in Phase 2.7 and 70 here.** The new weights give desirability 15 points and
  collision 12 instead of 15. Its desirability is middling (8/15).

**Top 5:** Trevane · Turnstone · Kenning · Alidade · Groma

**Top 3:** Trevane · Turnstone · Kenning

---

## 5. Pronunciation of the top 8

| Name | Say | Notes |
|---|---|---|
| Trevane | **treh-VANE** (/trəˈveɪn/) | Stress is ambiguous on first sight. People may write Trevain or Trevayne. Contains the homophone "vain". |
| Turnstone | **TURN-stone** | Unambiguous in English and Indian English. May be misheard as "Turnstile". |
| Kenning | **KEN-ing** | Clear. People may write Kening or Kenneng. It sounds like the surnames Jennings and Henning. |
| Alidade | **AL-ih-dayd** (/ˈælɪdeɪd/, per dictionaries [S]) | Unfamiliar to most buyers. Indian English may say "a-li-DAA-de". Spelling after hearing is weak. |
| Groma | **GROH-mah** | Clear. Some hearers may say "Grama". |
| Sorvel | **SOR-vel** | Clear. People may write Sorvell. |
| Plimsoll | **PLIM-sol** | Unfamiliar in India, where it may come out as "plim-SOUL". People may write Plimsol or Plimsole. |
| Tallis | **TAL-is** | Clear. People may write Talis. |

---

## 6. Actual origin versus the brand association we could build

Rule for this round: no manufactured etymology. Where Phase 2.7 gave a rationale after the fact,
it is corrected here.

| Name | Actual origin | Brand association we could build |
|---|---|---|
| **Trevane** | **Mostly invented.** *Vane* is a real English word: the blade of a wind or flow instrument. *Tre-* was chosen for sound. Phase 2.7 linked it to Latin *trans* (via Old French *tres-*, as in *trespass*); **that link is a stretch and should not be used in brand copy.** | An instrument that shows which way conditions are moving. The *vane* reading is genuine. |
| Turnstone | A real English word: the shorebird *Arenaria interpres*, named for turning over stones to find food. | Leaving no stone unturned, which suggests investigation and evidence. "Stone" adds solidity. |
| Kenning | Real. In Old Norse poetics a *kenning* is a compound metaphor (from *kenna*, "to know, recognise"). English *ken* means range of sight or knowledge. An older nautical sense, the distance visible at sea, is **[U]**: remembered from dictionaries, not re-checked this session. | The range of what can be seen and known, which suggests observation and knowledge. |
| Alidade | Real. A surveying sight-rule, the upper rotating part of a theodolite. From Medieval Latin *alhidada*, from Arabic *al-ʿiḍāda*, "the revolving radius" [S]. | Precise line of sight, survey and record. It fits the engineering-drawing character. |
| Groma | Real. Latin *groma*, the Roman surveyor's cross-staff for laying out straight lines and right angles [S]. | Alignment, foundations, infrastructure. |
| Sorvel | **Purely invented.** No root. The 2.7 gloss "level, vellum" was post-hoc. | Any association would have to be built through use. |
| Plimsoll | Real. The *Plimsoll line* is the ship load-line mark, named for Samuel Plimsoll MP (Merchant Shipping Act, 1876). The British word for a gym shoe comes from the same line [S/I]. | A safe-limit mark, a regulated threshold, a visible line not to be crossed. |
| Tallis | Real surname (the composer Thomas Tallis). Echoes "tally". | Counting and record. Weak. |

---

## 7. Wordmark and monogram test (typography only, not logos)

Every name was set in IBM Plex Sans variable on Paper #F3F4F1 and Ink #0C1418:
- uppercase tracked, width axis 88, weight 560;
- title case at 29 px;
- small sizes: "<Name> Reliability" at 13 px and caps at 10.5 px;
- "Verified by <Name>" at 13 px;
- monogram tiles at 28 and 16 px.

The render is in the session scratchpad and was not committed.

| Name | Silhouette and rhythm | Distinctive characters | Monogram at 16 px | Small-size readability | Resemblance to other industrial brands |
|---|---|---|---|---|---|
| Trevane | Even 7-letter run. The V–A diagonal is the one point of motion and needs kerning. | V | **T**: strong but common | Good | Trevena (biopharma), weak |
| Turnstone | Long, 9 letters. The tracked uppercase line gets long. | none in particular | **T**: common | "Verified by Turnstone" **wraps** in a 13 px column | Steelcase *Turnstone* (furniture) |
| Kenning | Firm. NN and ING give a regular picket rhythm. The *g* descender anchors title case. | **K** | **K**: strongest of the set and uncommon | Good | Keyence and Kistler use K wordmarks, but in a different style |
| Alidade | Symmetric, architectural (A·D·A·D). The *lid* ascender cluster is busy in title case. | A, D | **A**: generic | Good | none notable |
| Groma | Short, heavy, compact block. Round O beside M. | **G** | **G**: distinctive | Very good | none notable |
| Sorvel | Soft and even. Weak at the *l* end. | — | **S**: generic | Good | none |
| Plimsoll | The *ll* ending repeats the 1/l/I legibility problem flagged in 2.5. | — | **P** | Fair | none |
| Tallis | The *ll* plus *i* cluster is poor in title case. | — | **T** | Fair | none |

Most ownable monograms: **K (Kenning)** and **G (Groma)**. Weakest: **A (Alidade)**,
**S (Sorvel)** and **T** (Trevane, Turnstone, Tallis), because the letter is common.

---

## 8. Conversational test (all top 8)

The test sentences were "Have you checked ___?", "___ flagged the pump.", "Open ___.", "We run ___
across the plant." and "___ is waiting for approval."

| Name | Result |
|---|---|
| Trevane | Natural in every sentence. Slightly synthetic. |
| Turnstone | Natural, warm and real. The best of the set. |
| Kenning | "Kenning is waiting for approval" sounds like a person (surname), and "Kenning flagged" has a verb-like *-ing*. **Fails the "sounds like a person" check partially.** |
| Alidade | Fine once known. "Open Alidade" blurs into "open a lid…". |
| Groma | Fine and punchy. Blunt. |
| Sorvel | Fine. Forgettable. |
| Plimsoll | "Plimsoll flagged the pump" comes out slightly comic (the shoe). |
| Tallis | A person's surname. |

---

## 9. Product-copy test (top 5)

### Trevane
- Trevane detected an abnormal vibration pattern on Pump P-204.
- Trevane recommends inspecting the drive-end bearing.
- Trevane is waiting for technician evidence.
- Trevane requires approval before execution.
- Verified by Trevane.
- Trevane — From early warning to verified recovery.
- Nothing closes without proof. Trevane verifies the result.
- Open Trevane. · We use Trevane for reliability operations. · Have you checked Trevane?

**Result:** every sentence works. It reads as a system, never a person. It is credible but
neutral; the copy carries the name rather than the name lifting the copy.

### Turnstone
- Turnstone detected an abnormal vibration pattern on Pump P-204.
- Turnstone recommends inspecting the drive-end bearing.
- Turnstone is waiting for technician evidence.
- Turnstone requires approval before execution.
- Verified by Turnstone.
- Turnstone — From early warning to verified recovery.
- Nothing closes without proof. Turnstone verifies the result.
- Open Turnstone. · We use Turnstone for reliability operations. · Have you checked Turnstone?

**Result:** the strongest copy of the set. "Nothing closes without proof" and "turn every stone"
reinforce each other. "Verified by Turnstone" feels solid. Its only cost in copy is length.

### Kenning
- Kenning detected an abnormal vibration pattern on Pump P-204.
- Kenning recommends inspecting the drive-end bearing.
- Kenning is waiting for technician evidence.
- Kenning requires approval before execution.
- Verified by Kenning.
- Kenning — From early warning to verified recovery.
- Nothing closes without proof. Kenning verifies the result.
- Open Kenning. · We use Kenning for reliability operations. · Have you checked Kenning?

**Result:** "Kenning recommends…", "Kenning is waiting…" and "Have you checked Kenning?" read like a
colleague named Kenning. That is personification, which the Phase 2.5 rule (agent advises, people
approve, record proves) argues against. This **lowers its product-language fit to 2/5.**

### Alidade
- Alidade detected an abnormal vibration pattern on Pump P-204.
- Alidade recommends inspecting the drive-end bearing.
- Alidade is waiting for technician evidence.
- Alidade requires approval before execution.
- Verified by Alidade.
- Alidade — From early warning to verified recovery.
- Nothing closes without proof. Alidade verifies the result.
- Open Alidade. · We use Alidade for reliability operations. · Have you checked Alidade?

**Result:** distinctive and instrument-like, and "Verified by Alidade" is strong. The copy works,
but the reliability firm of the same name blocks it (§3).

### Groma
- Groma detected an abnormal vibration pattern on Pump P-204.
- Groma recommends inspecting the drive-end bearing.
- Groma is waiting for technician evidence.
- Groma requires approval before execution.
- Verified by Groma.
- Groma — From early warning to verified recovery.
- Nothing closes without proof. Groma verifies the result.
- Open Groma. · We use Groma for reliability operations. · Have you checked Groma?

**Result:** short and functional. Next to the tagline it feels heavy and blunt rather than
premium. "Verified by Groma" works.

---

## 10. Head-to-head against Trevane (top 3)

### Turnstone vs Trevane

**Why choose Turnstone instead:**
- It is a real, warm, memorable word that people like on first hearing (owner risk LOW).
- It has the best copy of any candidate.
- Its investigation meaning is genuine, not constructed.
- It does not sound synthetic.

**Why choose Trevane instead:**
- Turnstone Labs, an active AI agent-orchestration project, already uses the name in software and
  owns the PyPI name.
- Steelcase's Turnstone is a long-established brand. It is in furniture, a different class, but
  it dominates search.
- All the main domains resolve.
- At 9 letters it wraps at small sizes, and its T monogram is common.
- Trevane's namespace is clean, and that is a real advantage for an early-stage company.

**Net:** Turnstone is the better *brand*, but not a *safe* name. If the product owner prefers it, a
professional check on Turnstone Labs' trademark position is the first gate.

### Kenning vs Trevane

**Why choose Kenning instead:**
- It is a real word with an honest meaning (knowledge, range of sight).
- Its namespace is nearly as clean: npm and PyPI are free and no company uses the name.
- It has the strongest monogram (K).

**Why choose Trevane instead:**
- Kenning sounds like a surname and personifies the system in exactly the sentences that matter
  ("Kenning is waiting", "Kenning recommends").
- Kenning has weaker industrial credibility; poetics are not engineering.
- Antmicro's Kenning is an industrial edge-AI framework.

**Net:** Kenning does not beat Trevane.

### Alidade vs Trevane (shown because it was the leading candidate until the spot check)

**Why choose Alidade instead:**
- It is the most desirable new name and the best fit with Instrument & Record and the
  engineering-drawing character.
- Its meaning is real and specific to instruments.

**Why choose Trevane instead:**
- *Alidade Maintenance, Engineering and Reliability* sells to our buyers.
- Three other software and IT firms named Alidade exist, one of them serving manufacturers.
- Pronunciation and spelling after hearing are weak in India.

**Net:** blocked.

**Conclusion:** no new candidate is clearly preferable to Trevane. The only one preferable as an
identity, Turnstone, is not preferable on risk.

---

## 11. Recommendation and confidence

### TREVANE REMAINS BEST

| | |
|---|---|
| Confidence that Trevane is the best name found so far (about 165 names across Phases 2.7 and 2.8) | **Moderate** |
| Confidence that Trevane is the best name achievable | **Low to moderate.** Its desirability is middling. This round confirms it is hard to beat by generation and screening, not that it is excellent. |

Steps for the product owner's review:

1. **Listen first.** Read §9 aloud for Trevane and Turnstone. If Trevane feels acceptable and
   Turnstone does not justify its risk, take Trevane to professional clearance.
2. **If Turnstone is preferred,** commission a professional trademark search on Turnstone, Turnstone
   Labs and Steelcase in classes 9 and 42 before going further.
3. **If neither lands,** the honest next step is **human or professional naming** (an agency or
   naming specialist, with access to the trademark registers). Do not run another round of this
   exercise. Two rounds show that names with strong meaning in this space are taken and that
   free names have middling appeal.

Not done, by design: no rename, no README branding change, no domain purchase, no logo, no
Phase 3.

---

## 12. What remains unverified

1. **Trademark registers.** None was searched directly; USPTO TSDR, EUIPO/TMview, IP India, UKIPO
   and WIPO were all blocked. Searches are needed for TREVANE (and TREVAN\*, TREVENA, TREVANSOFT,
   TREVANNA), TURNSTONE (Steelcase's marks, Turnstone Labs' filings) and KENNING, in classes 9, 42,
   and possibly 35 and 37.
2. **Every [S] company fact** must be re-checked on the companies' own sites. This includes Turnstone
   Labs' corporate status, the scope of Alidade MER, and Groma LLC's litigation.
3. **Domains:** ownership and price of trevane.com (the BrandBucket listing), and who holds
   trevanesystems.com and turnstone.ai/.io.
4. **Pronunciation:** a spoken test with 5–10 Indian and international plant staff for Trevane and
   Turnstone.
5. **Linguistic check:** native speakers of Tamil, Telugu, Kannada, Marathi, Bengali and Korean.
   This round checked only English, Hindi and major European languages.
6. **Social handles and app-store names.** Not checked.
7. **Screening completeness.** The Alidade miss shows that a 6–8-query screen can overlook an
   exact-name company in the same field. Every risk level here is a floor, not a ceiling.

---

## 13. Sources and evidence notes

- **[F]** gathered on 2026-10-05:
  - status codes from `registry.npmjs.org/<name>` and `pypi.org/pypi/<name>/json`;
  - DNS resolution of `<n>.com`, `.ai`, `.io`, `get<n>.com`, `<n>hq.com`, `<n>systems.com` and
    `<n>ops.com`;
  - GitHub repository search through the session's GitHub tool;
  - the wordmark render, using fontsource `@fontsource-variable/ibm-plex-sans` 5.3.0 in headless
    Chromium.
- **[S]** come from three screening passes (6–8 queries per name), plus my spot checks. The spot
  checks returned:
  - [Alidade Maintenance, Engineering and Reliability (CB Insights)](https://www.cbinsights.com/company/alidade-maintenance-engineering-and-reliability)
  - [Alidade AI](https://www.alidade-ai.com/)
  - [Alidade Technology](https://www.alidadetech.com/)
  - [Alidade Systems](https://alidade.systems/)
  - [Alidade (Merriam-Webster)](https://www.merriam-webster.com/dictionary/alidade)
  - [Alidade (Wikipedia)](https://en.wikipedia.org/wiki/Alidade)
  - [Plimsoll company profile (Tracxn)](https://tracxn.com/d/companies/plimsoll/__GehviXHRP1y8eN1r3yhvF0M5XGEqqVsKmoe7rIc8Bgg)
  - [Plimsoll Publishing](https://www.plimsoll.co.uk/)
  - [Antmicro: AutoML models for embedded in Kenning](https://antmicro.com/blog/2025/03/automl-models-for-embedded-in-kenning)
  - [Kennen Technologies](https://kennen-technologies.com/about-us)
  - [TrevanAI](https://www.trevanai.com/)
  - [TREVANNA TRACKS (Justia)](https://trademark.justia.com/980/88/trevanna-98088544.html)
- **GK** in §2 means general knowledge, used only for early rejection.
