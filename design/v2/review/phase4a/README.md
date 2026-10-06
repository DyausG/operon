# Phase 4A visual gate: captures

Screenshots for the Phase 4A screenshot review (`08 §11`). Branch `v2/phase4a-visual-gate`.

## How they were produced

- **Real application, real data.**
  - Backend: `OPERON_AI_PROVIDER=none OPERON_REASONING_BACKEND=none uv run python run.py --no-browser` (no model provider).
  - Frontend: the Vite dev server (`npm run dev`), because the design specimen is a development-only route.
- **Script:** `frontend/test/visual/capture-phase4a.mjs`. It:
  - signs in through the UI as a declared demo identity ("Reviewer");
  - starts the Guided Demo from **System → Simulation & Demo** (the real lifecycle with simulated inputs);
  - captures each state as the engine reaches it;
  - stops the backend process to capture the real disconnected state.
- **No fixtures, mocks or injected records** appear in these images, except the clearly labelled specimen sheet (12/13).
- **Time basis:**
  - Times are the browser's zone (UTC in the capture container); the plant time zone isn't projected (X3).
  - Stream ages are **browser receipt times**, labelled "received" (X8 fallback).
- **The investigation state is transient.** The engine holds *Awaiting inspection* for about 5 s. The script asserted the case was still `AWAITING_EVIDENCE` after captures 06/06b/07.

## Inventory

| # | File | State | Theme | Viewport |
|---|---|---|---|---|
| 1 | `01-overview-active-light-1440.png` | Overview, Guided Demo case awaiting decision | light | 1440×900 |
| 1b | `01b-overview-active-dark-1440.png` | same | dark | 1440×900 |
| 2 | `02-overview-disconnected-light-1440.png` | Backend stopped: disconnected banner, "as of" statement | light | 1440×900 |
| 2b | `02b-case-decision-disconnected-light-1440.png` | Backend stopped: decision controls **inactive** with reason | light | 1440×900 |
| 3 | `03-my-actions-docked-light-1440.png` | My actions, preview **docked** | light | 1440×900 |
| 4 | `04-my-actions-docked-light-1280.png` | My actions, preview **docked** (CH-2 boundary) | light | 1280×800 |
| 5 | `05-my-actions-modal-drawer-light-1024.png` | My actions, preview as **modal drawer** (scrim, focus in drawer) | light | 1024×768 |
| 5b | `05b-my-actions-dark-1440-docked.png` | My actions, docked | dark | 1440×900 |
| 6 | `06-case-investigation-light-1440.png` | Case, *Awaiting inspection* (investigation loop) | light | 1440×900 |
| 6b | `06b-case-investigation-section-light-1440.png` | same, Investigation section: hypotheses, reviews | light | 1440×900 |
| 7 | `07-case-investigation-light-1024.png` | same | light | 1024×768 |
| 8 | `08-case-awaiting-approval-light-1440.png` | Case, awaiting decision (header, title block, stage track) | light | 1440×900 |
| 8b | `08b-case-decision-surface-light-1440.png` | Decision surface in context | light | 1440×900 |
| 8c | `08c-case-decision-surface-full-light-1440.png` | Decision surface, whole element | light | 1440 wide |
| 9 / 9b | `09-…-light-1024.png`, `09b-case-decision-surface-light-1024.png` | Case awaiting decision | light | 1024×768 |
| 10 / 10b / 10c | `10-…-dark-1440.png`, `10b-…`, `10c-…-full-dark-1440.png` | Case awaiting decision | dark | 1440 |
| 11 / 11b | `11-…-dark-1024.png`, `11b-case-decision-surface-dark-1024.png` | Case awaiting decision | dark | 1024×768 |
| 12 / 12b | `12-specimen-light.png`, `12b-specimen-light-full.png` | Status-primitives specimen (dev-only route, placeholder values) | light | 1440 |
| 13 / 13b | `13-specimen-dark.png`, `13b-specimen-dark-full.png` | same | dark | 1440 |

## States that the real lifecycle doesn't reach

These are shown only on the labelled specimen sheet (section 09: "Decision surface states (specimen)"):
- **Acknowledgement forcing function.** The Guided Demo produces no contradicting evidence and no unresolved critic challenge, so the checkbox correctly does not appear on the real case.
- **Approaching deadline.** The real requirement expires 24 h after it is created.
- **Changed since opened.** The specimen has a button that changes the bound revision.

The inactive Approve state *is* reached for real (2b).
