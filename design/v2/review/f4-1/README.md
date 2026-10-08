# F4.1 review: case workspace (layout D), truthful lifecycle, recovery, Cases list

Branch `v2/f4-frontend-next` (local only, no upstream), based on `c2273a1`
(`v2/integration-f1-routing`). Frontend only: no file outside `frontend/**` and this folder
changed, and tracked `frontend/dist` is untouched.

| Commit | Stage |
|---|---|
| `a4bf559` | Truthful case lifecycle model (`model/lifecycle.js`, `refusal.js`, `workBoundary.js`) |
| `ce35c9d` | Real-engine exception and recovery fixtures (`test/make_fixtures.py`) |
| `fe74853` | Layout D: identity row, stage line, case navigator, Now, decision surface in Now |
| `1366a49` | F1.1 recovery commands in Now, gated; decision-surface role and environment gates |
| `03cf89e` | Case inspector (asset, identifiers, full record, evidence, artifact detail) |
| `cb778fd` | Cases list (latest case per asset) and consistency across Overview / My actions / preview |
| (this commit) | Workspace browser checks, narrow-strip and stage-line fixes, captures, this handoff |

## Captures

From real engine fixture frames, production build (`vite preview`), system Chrome, clock pinned to
the fixture era. Reproduce with `frontend/test/visual/capture-f41.mjs` (header has the command).

| File | Shows |
|---|---|
| 01, 02, 03 | Pending decision in Now: 1440 light and dark, 1024 (navigator still a column) |
| 04 | BLOCKING uncertainty: waiting on a technician, journal reason, no decision |
| 05 | Suspended analysis (TIMEOUT ×3): waiting on a reliability engineer, resume / escalate / cancel |
| 06 | Expired approval: no decision surface; renew / return to planning |
| 07, 08 | Escalated by rejection; the resume confirmation with consequence, reason and binding |
| 09 | Definitive dispatch failure: retry / abandon and reinvestigate |
| 10 | READY after retry (dark): "approved, not dispatched", explicit dispatch |
| 11 | Planning after a recorded rejection |
| 12 | Cancelled, with who and why |
| 13, 14 | Inspector docked at 1440 (asset) and as a drawer at 1024 (full record) |
| 15, 16 | Cases list, and with the docked preview |
| 17 | 390 px phone: navigator strip, decision surface |

The fixtures put one case on one asset, so the list shows one row; it is not padded with
combined frames, which would contradict "latest case per asset".

## What is real, simulated or placeholder

- **Real (backend contracts at `c2273a1`)**: approval and rejection; `POST /commands/{resume,
  cancel, escalate, renew_approval, return_to_planning, retry_execution}` with
  `{actor_id, actor_role, expected_revision, rationale}`; explicit dispatch
  `POST /execute {intervention_id, intervention_hash}`; artifact detail
  `GET /api/demo/artifacts/{id}`. Only commands whose preconditions hold in
  `core/reliability/lifecycle.py` are offered.
- **Identity**: declared (or sandbox) and never verified. The UI says so wherever it records an
  actor. The server assigns the actor kind; the client never sends one. `/execute` records no actor
  in this build, and the confirmation says so.
- **Simulated**: the plant data and Guided Demo case (labelled SIMULATED / DEMO), and the
  exception fixtures. They come from the real engine driven through **test-only seams** in
  `make_fixtures.py`: `TimeoutAdvisory` (passed through DemoEngine's existing `runtime`
  parameter), `RejectingWorkOrders` and an advanced lifecycle clock (each a `patched(...)`
  context manager inside the generator process that restores the original), plus a declared
  fixture actor. The seams exist only in that script; `git grep` finds no reference in
  `core/`, `server/` or `frontend/src`.
- **Placeholders / not available**: technician inspection and resource confirmation from the
  UI (G1, X7); reconciliation of an unknown dispatch outcome (runs at engine restart); Assets,
  Work orders, Reliability, Audit, Updates and Preferences pages (labelled placeholders with
  legacy exits); case history beyond the latest case per asset (G5).

## Gating and refusals

- PRODUCTION incidents get no human controls; the valid commands are still named. The observer
  role is read-only. A lost connection makes the controls inactive with a reason. Approve and
  reject are inactive for a declared role outside `required_roles` (the backend refuses it).
- Each command needs a reason of 1–2,000 characters (none for dispatch) and is bound to the
  revision the person reviewed. A change while confirming must be reviewed first; a command
  that stops being valid closes.
- A refusal shows a lead per status (0, 400, 403, 404, 409, 422, 5xx), the server's `error`
  or `detail` (control characters removed, at most 300 characters, rendered as text) and the
  HTTP status.

## Compatibility

- Routes: V2 `/app`, legacy `/legacy`, and the old `/app/<legacy>` redirects are unchanged.
  `/app/cases` is now a V2 screen; its placeholder and legacy exit are removed.
- Case deep links: `#decision` and `#decision-surface` open Now while a decision is pending,
  otherwise Plan & decision. `#summary` opens Now, and `#work`, `#evidence` and `#record` open
  their sections. Unknown hashes open Now. `?inspect=` sits beside the hash.
- Waiting-on change (F0 #19): DIAGNOSIS_VALIDATED now waits on the maintenance planner, not
  the approver.

## Verification (final run)

- Vitest: 10 files, **1007 passed**.
- Smoke (`npm run test:smoke`): all 15 checks ok.
- Playwright, system Chrome: **54 passed** on the Vite dev server and **54 passed** on the
  production preview of the external build (`C:/Temp/operon-f41-dist`).
- Backend `pytest` (unchanged backend, as a sanity check, Git Bash on PATH): 923 passed, 0
  failed.
- Responsive coverage: 1440, 1280, 1024 and 390. The 390 checks cover no page overflow,
  navigator items that don't overlap, and a reachable decision. Light and dark themes.

## Remaining issues

- The expired fixture advances only the backend clock, so captures show a requirement that
  "expired at 10 Oct 03:30" beside a browser clock of 09 Oct. In real use the two clocks agree.
- The escalation reason is the backend journal text as written (for example "…returned to
  ESCALATED"). It is labelled "Recorded reason" and not rewritten.
- Playwright's own Chromium isn't installed here; the suites use the system Chrome channel.
- The bundle exceeds Vite's 500 kB chunk warning (this predates F4.1).

## F1.2 dependencies (backend plan `12-f1.2-plant-work-verification-plan.md`, PROPOSED)

All work and verification wording and mapping live in `frontend/src/v2/model/workBoundary.js`.
The OBSERVING branch of `CaseNow.jsx` and `WorkSection` read only from that module. To integrate:

1. Consume `lifecycle.verification.state`. OBSERVING + `AWAITING_WORK` / `WORK_NOT_PERFORMED`
   should present as **In work**, and `COLLECTING` / `EVALUATING` as **Verifying**. Today
   `stageOf(phase)` maps OBSERVING to Verifying. The change belongs in `status.js` (`stageOf`
   taking the verification state) and `workBoundary.js` (`VERIFICATION_BASIS`, `observingSince`).
2. Work states `DECLINED`, the overdue flags, and `decline_work` / `reassign_work` commands
   should be added to `WORK_STATE` and to `availableCommands`, along with OBSERVING `resume`
   when work wasn't performed.
3. Optional and helpful: a projected `available_commands` list would replace the mirrored
   preconditions in `lifecycle.availableCommands`. Projecting `human_inputs_enabled` would
   let the UI gate work acknowledgement and reports without guessing the sandbox gate.
4. On fixture regeneration after F1.2: OBSERVING frames carry a reported assignment, and
   `f1.test.jsx` "dispatch records an assigned work fact" will need updating (the F1.2 plan
   §7.4 lists this).

Files a merge is most likely to touch on both sides: `model/status.js`, `model/workBoundary.js`,
`screens/CaseNow.jsx`, `test/make_fixtures.py` and the fixtures (owned by F4).
