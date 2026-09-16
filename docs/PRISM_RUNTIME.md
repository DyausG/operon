# PRISM Interruptible Runtime (Stage 1 foundation)

Operon's adaptation for Samsung PRISM GenAI Hackathon 2026, Theme 5 (*Interruptible
Real-Time Agents*). Stage 1 builds the **runtime foundation**: durable sessions,
revisions and runs, a Fast Path that answers immediately, a Slow Path that can be
superseded, and an atomic commit fence that makes stale work harmless. It does not
implement multimodal grounding, the final interruption UX or Fast Path intelligence.
Theme 5 is **not** complete; this is the correctness base later stages build on.

## The invariant

> Once revision N is superseded by revision N+1, no result produced for revision N may
> mutate canonical state.

This holds whether the old coroutine keeps running, a provider ignores cancellation,
a tool cannot be cancelled, a result arrives late, the process restarts, a client
reconnects, a request is duplicated or two operations race.

**Cancellation is an optimization. Revision fencing is the correctness mechanism.**
Stale results are kept as history (audit) and never become canonical.

## Architecture

```
operator ──POST /api/prism/sessions/{id}/messages──▶ PrismRuntime.submit_message
                                                        │  (asyncio.Lock: in-process ordering only)
                                                        ▼
                                          PrismRepository.accept_turn  ── one BEGIN IMMEDIATE ──
                                            dedupe on (session, idempotency_key)
                                            revision N ➜ N+1 (CAS on current_revision)
                                            N's runs: QUEUED➜SUPERSEDED, RUNNING➜CANCELLING
                                            Fast Path acknowledgement persisted with the turn
                                            N+1 Slow Path run inserted QUEUED
                                                        │
                    ┌───────────────────────────────────┴──────────────────────────┐
                    ▼                                                              ▼
       RunCoordinator.supersede(N runs)                              RunCoordinator.schedule(N+1 run)
       token.cancel() + task.cancel() if cancellable                 asyncio task ➜ adapter.run(execution)
                    │                                                              │
                    ▼                                                              ▼
       worker returns late / ignores cancel ─────────▶ CommitFence.commit ◀───── result
                                                        PrismRepository.commit_result
                                                        (BEGIN IMMEDIATE; fencing.decide inside)
                                                   committed ➜ run COMPLETED, session.canonical ← result
                                                   stale     ➜ run STALE, result kept as history,
                                                               stale_result_discarded event
```

Modules (`core/prism/`):

| module | role |
| --- | --- |
| `models.py` | identity model, `RunStatus` graph, `SlowPathResult`, `CommitDecision` |
| `repository.py` | every durable transaction (accept, start, commit, fail, cancel, effects, events, recovery) |
| `fencing.py` | `decide()` (pure eligibility rule), `CommitFence` / `RunFence` (the only runtime handle) |
| `cancellation.py` | cooperative `CancellationToken`; `uninterruptible()` models non-cancellable work |
| `fast_path.py` | deterministic acknowledgement contract, `role="fast"` identity |
| `slow_path.py` | `SlowPathExecution` / adapter contract, deterministic + provider-backed adapters, incident context |
| `coordinator.py` | task registry, scheduling, cancellation signalling, deadline, result ➜ fence |
| `runtime.py` | `PrismRuntime` facade: sessions, messages, views, recovery, shutdown, metrics |
| `events.py` | versioned websocket envelope, `EventPublisher` |
| `idempotency.py` | request identity normalization |
| `recovery.py` | restart policy description |
| `observability.py` | secret-safe structured transition log, latency summary |
| `testing.py` | `ControlledAdapter`: block / ignore cancel / fail / duplicate completion / effects |

Server: `server/prism_api.py` (routes registered from `server/main.py`). Engine: `DemoEngine.prism`
(same SQLite database, events broadcast on `/ws`, `snapshot()["prism"]`, recovery on `start()`,
reset wipes sessions). Frontend: `frontend/src/state/prism.js`, `agentRuntime.js`, `engineState.js`
(`prism` message), `pages/AgentPage.jsx` (PRISM panel + operator console).

## Identity model and persistence (migration `008_prism_runtime.sql`)

| table | identity | notes |
| --- | --- | --- |
| `prism_session` | `session_id`, `incident_id?`, `current_revision`, `current_turn_id`, `canonical_revision/run_id/json`, `recovery_json` | exactly one canonical current revision per session |
| `prism_turn` | `turn_id`, `revision`, `request_id`, `idempotency_key`, content, `fast_path_json` | immutable; `UNIQUE(session, revision)`, `UNIQUE(session, idempotency_key)` |
| `prism_run` | `run_id`, `turn_id`, `revision`, `attempt`, `role`, `status`, `stale`, `runtime_json`, `result_json`, `error_json`, `recovered_from_run_id`, timestamps (`created/updated/started/superseded/cancelled/completed_at`, `deadline_at`) | a run belongs permanently to one revision; terminal rows are trigger-protected |
| `prism_effect` | `effect_id`, `revision`, `run_id`, `tool_call_id`, `idempotency_key`, `kind`, `request_hash`, `status` | `UNIQUE(session, revision, idempotency_key)`; completed rows immutable |
| `prism_event` | `event_id`, `session_id`, `revision`, `turn_id`, `run_id`, `event_type`, payload | immutable audit/timeline; reconnect catch-up by `event_id` |

Legal run states: `QUEUED ➜ RUNNING | SUPERSEDED | CANCELLED | FAILED`,
`RUNNING ➜ COMPLETED | FAILED | CANCELLING | CANCELLED | STALE`, `CANCELLING ➜ CANCELLED | STALE | FAILED`.
`COMPLETED / FAILED / CANCELLED / SUPERSEDED / STALE` are terminal; a database trigger refuses any
update of a terminal row, and `validate_run_transition` refuses illegal moves before SQL runs.
No table holds a provider secret; runtime identity is provider kind/model/role only.

## Fast Path vs Slow Path

* **Fast Path** (`DeterministicFastPath`) is a pure function evaluated *inside* the acceptance
  transaction. It returns `accepted`, `accepted_superseding` or `clarification_required`, the
  current context and whether deeper reasoning was scheduled. It never waits for a model, a tool
  or the Slow Path, and carries `role="fast"` so a later stage can bind a provider through
  `registry.build(role="fast")`. Its latency (request start ➜ durable acknowledgement) is stored
  on the turn and exposed by `/api/prism/metrics`.
* **Slow Path** adapters receive a `SlowPathExecution` that knows `session_id`, `turn_id`,
  `revision`, `run_id`, `attempt`, `request_id`, the cancellation token, the deadline, the
  runtime/provider role identity and its `RunFence`. They return a `SlowPathResult`; they never
  write canonical state. `DeterministicSlowPathAdapter` (labelled `DETERMINISTIC`) and
  `ProviderSlowPathAdapter` (`registry.build(role="slow")`, bounded JSON completion run off the
  event loop, labelled `LIVE`) are built in; `OPERON_PRISM_SLOW_PATH=auto|deterministic|provider`
  selects one. Nothing in `core/prism` imports Gemini, Ollama or Bedrock.

## Revision and supersession

When input arrives while revision N is active, one transaction: accepts the turn, creates
N+1, marks N's queued run `SUPERSEDED` and N's running run `CANCELLING` (`superseded_at`,
`stale=1`), persists the Fast Path acknowledgement, queues N+1's run and records
`turn_accepted`, `interruption_received`, `revision_superseded`, `cancellation_requested`,
`fast_path_acknowledged`, `slow_path_queued`. After commit the coordinator signals N's token,
hard-cancels the task when the adapter is cancellable, and schedules N+1. N+1 never waits
for N to stop.

## Why cancellation alone is insufficient

An `asyncio` cancel only lands at the next `await`; a provider thread keeps running; a tool
may be mid-flight; a result may already be on its way back; the process may restart with a
run still marked RUNNING. Any of those can deliver a revision-N result after N+1 exists.
The only reliable defence is to decide *at commit time*, under the same lock that advances
revisions, whether the result's run is still the canonical revision's active run.

## The atomic commit fence

`fencing.decide(session, run, identity)` is a pure rule: the result's claimed identity must
match the durable run row, the session must be `ACTIVE`, the run must be `RUNNING` (not
`CANCELLING`, not superseded, not terminal) and `run.revision == session.current_revision`.
`PrismRepository.commit_result` evaluates it inside `BEGIN IMMEDIATE`, then either commits
(`UPDATE prism_run … WHERE status='RUNNING'` and `UPDATE prism_session … WHERE current_revision=?`,
both checked for `rowcount == 1`) or records the result on the run as `STALE` with a
`stale_result_discarded` event. Because SQLite serialises `BEGIN IMMEDIATE` writers, an
acceptance of N+1 and a commit of N cannot interleave: whichever runs second sees the first's
state. A result that "looked current" before the transaction but lost the race is recorded
stale. Effects use the same rule (`begin_effect` refuses with `StaleRevisionError` and an
`effect_refused` event once the revision is superseded). If the session or run row is missing
or inconsistent the decision is "not committed": the fence fails closed.

## Idempotency

* **Requests**: `idempotency_key` (defaulting to `request_id`) is unique per session. The
  acceptance transaction returns the original turn, revision and run for a replay and refuses
  (`409`) the same key with different content. Concurrent duplicates serialise on the write
  lock and dedupe durably, across processes; the in-process `asyncio.Lock` only orders work.
* **Effects**: `(session_id, revision, idempotency_key)` is unique. `SlowPathExecution.effect`
  begins the effect (fenced), performs it once, completes it once; a retry returns the recorded
  outcome without performing anything. Completion of a completed effect is a no-op. Existing
  Operon approval/execution governance is untouched: PRISM never writes incident state.

## Recovery

On `DemoEngine.start()` (once per process) `PrismRuntime.recover()` runs one transaction per
startup with policy `retry_current_revision`:

* canonical revision = `prism_session.current_revision` (a pointer, never inferred);
* incomplete runs of older revisions ➜ `SUPERSEDED`/`CANCELLED` history, never revived;
* a `RUNNING` run of the current revision ➜ `FAILED("process_restart")` and, unless that
  revision already has canonical state, a new attempt (`attempt+1`, new `run_id`,
  `recovered_from_run_id`) is queued; `CANCELLING` runs are closed, never retried;
* `QUEUED` runs of the current revision are rescheduled unchanged;
* `PENDING` effects of interrupted runs ➜ `UNKNOWN` (outcome not observed), never replayed;
  completed effects stay in the ledger so the retry attempt finds them and does not repeat them.

The report is stored on the session (`recovery_json`), emitted as `session_recovered`, shown in
the Agent Workspace, and returned by `GET /api/prism/sessions/{id}/events` (`recovery`).
`fail_only` is the alternative policy (classification without retry).

## External-effect safety

Three things are kept apart: (1) reasoning cancellation (token + task cancel), (2)
proposed-action invalidation (a newer revision's canonical result replaces the old proposal;
the old one stays as history), (3) already-committed external effects (recorded truthfully in
`prism_effect`; a later revision never pretends they were undone). Approval boundaries are
unchanged: PRISM sessions link to an incident read-only; a stale revision cannot trigger an
effect, overwrite a diagnosis or plan, or touch incident closure.

## API and events

| route | purpose |
| --- | --- |
| `POST /api/prism/sessions` | create a session (`incident_id?`, bounded `metadata`) ➜ `201` |
| `GET /api/prism/sessions[?incident_id=]` | compact session views |
| `GET /api/prism/sessions/{id}` | full durable view (turns, runs, effects, last events, incident) |
| `POST /api/prism/sessions/{id}/messages` | accept input ➜ `202` with turn, revision, Fast Path state, Slow Path run; `409` on key conflict |
| `GET /api/prism/sessions/{id}/events?after=N` | reconnect: view + events after `N` |
| `GET /api/prism` / `GET /api/prism/metrics` | overview / Fast Path latency summary |

Websocket: existing message types are unchanged; `snapshot` gains `prism`, and each durable
event is sent as `{"type": "prism", "prism_version": 1, "event": {...}, "session": {...}}`.
Event types: `session_created`, `session_recovered`, `turn_accepted`, `fast_path_acknowledged`,
`slow_path_queued`, `slow_path_started`, `slow_path_progress`, `interruption_received`,
`revision_superseded`, `cancellation_requested`, `run_cancelled`, `run_completed`, `run_failed`,
`stale_result_discarded`, `canonical_state_updated`, `effect_started`, `effect_completed`,
`effect_refused`. Payloads carry identity, timestamps and bounded summaries only.

## Deterministic interruption verification (no cloud model)

```
uv run python scripts/prism_interruption_check.py            # non-cooperative worker: stale result discarded
uv run python scripts/prism_interruption_check.py --cooperative   # worker honours cancellation
```

Manually in the portal: run Operon with `OPERON_PRISM_SLOW_PATH=deterministic
OPERON_PRISM_SLOW_DELAY_SECONDS=8 OPERON_PRISM_SLOW_COOPERATIVE=0`, open **Operon Agent**,
pick the Guided Demo incident, send `Investigate the compressor temperature anomaly.` in the
Activity tab, then before the delay elapses send `Correction: prioritize the vibration spike
and ignore the temperature hypothesis for now.` The PRISM panel advances to revision 2
immediately, shows revision 1 as superseded/cancelling, then records one stale result
discarded when the old worker returns; revision 2 becomes canonical. Restart the server:
revision 2 remains canonical and nothing is revived. Every deterministic result is labelled
`DETERMINISTIC`; a provider-backed run is labelled `LIVE`.

## Stage 1 versus later work

Done here: persistent identity model, revision/supersession, cooperative cancellation,
atomic fencing, request and effect idempotency, recovery, versioned events, minimal Agent
Workspace visibility, deterministic adapters and tests. Later: Fast Path intelligence
(provider `role="fast"`), production Slow Path integration with the supervisor lifecycle,
multimodal grounding (`voice_transcript`, `image_reference` are accepted but not processed),
the final interruption UX, latency optimisation and benchmark/demo hardening.
