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
| `3fb1d2a` | Workspace browser checks, narrow-strip and stage-line fixes, captures, this handoff |
| (this commit) | Handoff corrections from the final audit (docs only) |

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
  reject are inactive for a declared role outside `required_roles`.
- Which restrictions the server enforces, and which only this interface applies:
  - **Server:** a production process or incident refuses any HTTP actor with 403 or
    `ActorRefused` (`core/reliability/actors.py`). Approvals and rejections need a role in
    `required_roles` (`decide_approval`). Every command checks the revision and its phase
    preconditions (409).
  - **Interface only:** the observer role (lifecycle commands record `actor_role` but don't
    check it), and withholding dispatch on production incidents. `/execute` has no actor or
    environment check; it is protected by READY needing a recorded approval for the exact
    package, which production can't produce before F3. The wording says "in this interface"
    where that applies.
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
- Backend `pytest` (unchanged backend, as a sanity check, Git Bash on PATH):
  `uv run --frozen pytest -q -p no:cacheprovider` gave 923 passed and 0 failed. That command has
  no marker filter, so it also runs the 3 `integration`-marked tests
  (`test_integration_a2a.py` ×2, `test_integration_mcp.py` ×1). The shared baseline was taken
  with `uv run pytest -m "not integration"`: 920 passed, 3 deselected. `tests/` is identical to
  `c2273a1`; collection gives 923, and 920/923 under that filter.
- Responsive coverage: 1440, 1280, 1024 and 390. The 390 checks cover no page overflow,
  navigator items that don't overlap, and a reachable decision. Light and dark themes.

## Remaining issues

- The expired fixture advances only the backend clock, so captures show a requirement that
  "expired at 10 Oct 03:30" beside a browser clock of 09 Oct. In real use the two clocks agree.
- The escalation reason is the backend journal text as written (for example "…returned to
  ESCALATED"). It is labelled "Recorded reason" and not rewritten.
- Retry and abandon after a failed dispatch are offered when `reconciliation_required` is false
  (that flag reflects the latest claim). The backend requires every claim on the current package
  to be FAILED. If an older claim were UNKNOWN, the UI would offer a command the server refuses;
  the refusal is shown. Not seen in the fixtures.
- `return_to_planning` is not offered from INTERVENTION_VALIDATED, where the backend allows it,
  because that phase is a brief automated step. It's a deliberate subset.
- Playwright's own Chromium isn't installed here; the suites use the system Chrome channel.
- The bundle exceeds Vite's 500 kB chunk warning (this predates F4.1).

## F1.2 dependencies (backend plan `12-f1.2-plant-work-verification-plan.md`, PROPOSED)

`frontend/src/v2/model/workBoundary.js` holds the work facts (`WORK_STATE`, `workFacts`,
`fieldStatus`), the verification basis and the observing line. `WorkSection`, Overview's work
list and the body of Now's OBSERVING block read those from it. That module is **not** the only
place with F1.2-dependent content. Everything that reads OBSERVING as "verifying since the
dispatch receipt" (accurate for F1.1, where the observation plan starts at the receipt) is:

| Location | What changes with F1.2 |
|---|---|
| `model/status.js` `STAGES` (IN_WORK / VERIFYING `next` text), `PHASE_STAGE.OBSERVING`, `PHASE_WAITING.OBSERVING`, `attentionOf` (OBSERVING → watch) | stage, waiting-on and attention must come from phase **plus** `verification.state` |
| `model/workBoundary.js` `VERIFICATION_BASIS`, `observingSince`, `WORK_STATE`, `fieldStatus` | verification starts at a qualifying work report; `DECLINED` and the overdue flags |
| `screens/CaseNow.jsx` OBSERVING block title ("Verifying recovery") | awaiting work vs collecting / evaluating |
| `screens/caseCopy.js` `nextStepSentence` (OBSERVING) | same |
| `screens/Overview.jsx` Watch list ("Verifying" for every OBSERVING case) | only COLLECTING / EVALUATING are verifying |
| `screens/DecisionSurface.jsx` approval consequence ("Starts post-work verification … once the work order is confirmed") | verification starts after the work report |
| `model/lifecycle.js` escalate consequence on OBSERVING, `sectionStates` work entry, `availableCommands` | OBSERVING `resume` (work not performed), `reassign_work` |

To integrate:

1. Consume `lifecycle.verification.state`. OBSERVING + `AWAITING_WORK` / `WORK_NOT_PERFORMED`
   should present as **In work**, waiting on the field or coordinator. `COLLECTING` /
   `EVALUATING` should present as **Verifying**, and `BLOCKED` with its `reason`. A small
   `verificationOf(lifecycle)` in `workBoundary.js` that `status.js` `stageOf` / `waitingOn`
   accept would keep the mapping in one place. The copy locations above then read from it.
2. `work[]` (F1.1 today: `ASSIGNED | ACKNOWLEDGED | REPORTED`, read by `workFacts`) gains
   `DECLINED`, plus `current`, `superseded_by`, `declined_at`, `declined_by`,
   `decline_reason`, `ack_overdue` and `report_overdue`. `WORK_STATE`, `workFacts` and
   `fieldStatus` should show the current assignment first, superseded ones as history,
   declines with their reason, and the overdue flags. A REPORTED fact stays a statement about
   people, never recovery.
3. Commands: `POST /work/{assignment_id}/decline` and `POST /commands/reassign_work`
   (`assignment_id`, `assignee_reference?`). `resume` from OBSERVING is allowed only when work
   wasn't performed. These go into `availableCommands` and `commandRequest`, plus the optional
   `request_key` (replays return `{ok: true, replayed: true}`). F4.1 doesn't yet expose the
   existing sandbox-gated acknowledge and report endpoints.
4. Optional and helpful: a projected `available_commands` list would replace the mirrored
   preconditions in `lifecycle.availableCommands`. Projecting `human_inputs_enabled` would
   let the UI gate work acknowledgement and reports without guessing the sandbox gate.
5. On fixture regeneration after F1.2: OBSERVING frames carry a reported assignment, and
   `f1.test.jsx` "dispatch records an assigned work fact" will need updating (the F1.2 plan
   §7.4 lists this).

The F1.2 branch (`v2/f1-2-plant-work`) changes no `frontend/**` file, so combining the two
branches should not conflict. The integration is frontend follow-up work against the merged
contract: the locations above, plus regenerated fixtures (`test/make_fixtures.py`, owned by F4).
