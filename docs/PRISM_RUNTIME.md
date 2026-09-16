# PRISM Interruptible Runtime (Stage 1 foundation + Stage 2 real Slow Path)

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

## Stage 2: the production Slow Path over Operon's real reasoning

Stage 2 connects the Stage 1 substrate to Operon's **real supervisor/specialist reasoning
lifecycle** without duplicating it and without weakening the invariant. The production adapter
is `core/prism/operon.py` (`OperonSlowPathAdapter`, selected by `OPERON_PRISM_SLOW_PATH=auto|operon`,
the default). The Samsung Theme 5 adaptation is still not finished: multimodal grounding, the
model-backed Fast Path and the final interruption UX are Stage 3 work.

### Compute before commit

Operon's own reasoning path is `PromotionService.run_supervisor` = `start_run` (claim: freezes
the evidence packet into a `SupervisorRunSnapshot` and sets `incident.active_run_id`) →
`ReasoningBackend.supervise` (the supervisor and its specialists; only evidence acquisition
writes) → `_complete_run` (durable `SupervisorReport`) → lifecycle settlement (promotion gates,
`AWAITING_EVIDENCE`). Stage 2 does not call that combined method. It exposes the phases through
connection-injected seams (`start_run(conn=…, question=…)`, `_complete_run(conn=…)`,
`promote_diagnosis(conn=…)`, `IncidentRepository.transition_in(conn, …)`) and drives them as:

```
operator instruction (revision N)
   → bounded reasoning question            current instruction + last canonical summary only
   → CLAIM      start_run                  inside a fenced PRISM transaction (prism_effect claim:{run})
   → COMPUTE    backend.supervise          real supervisor/specialists; no canonical write
   → CANDIDATE  SupervisorResult → SlowPathResult (structured, reviewer-visible; nothing applied yet)
   → FENCE      PrismRepository.commit_result   BEGIN IMMEDIATE, fencing.decide inside
   → APPLY      _complete_run + settlement    inside that same transaction, recorded as prism_effect apply:{run}
     or STALE   candidate kept on the PRISM run as history; the incident is untouched
```

Because the PRISM tables and the incident tables live in the same SQLite file, the fence decision
and the incident write are one `BEGIN IMMEDIATE` unit: acceptance of revision N+1 and the apply of
revision N are strictly ordered by the database. A candidate that lost that race is recorded
`STALE` with its full structured result (audit) and no report, phase change, promotion or
approval request exists for it. Two repository primitives carry this: `PrismRepository.transact`
(atomic fenced write: eligibility → caller's write → effect row, all or nothing; refused with
`StaleRevisionError` once superseded; idempotent per key) and `commit_result(apply=…)` (the
application write executes only after the fence admits the result and rolls back with it).

### Current instruction and bounded context

`compose_question` builds the reasoning question from the **current** operator instruction
(authoritative, ≤ 1400 chars) plus, when an earlier revision committed, that canonical result's
summary (≤ 400 chars, explicitly overridden by the instruction where they conflict). Superseded
instructions are never included, so a correction cannot be silently outvoted by the text it
corrects. The question is frozen into the Operon snapshot (`context_payload.question`), the
request metadata (revision, instruction hash, prior canonical revision, context policy) is
persisted on the PRISM run (`result.details.reasoning_request`) and emitted as the
`reasoning_context_prepared` progress event. Prompts and model text are never emitted.

### Real supervisor cancellation

Supersession signals the token and, for the default cooperative adapter, cancels the asyncio task
(`agent.invoke_async` stops; a Strands `cancelled` stop reason now maps to termination
`CANCELLED`). Checkpoints: before the claim, before every pass, at the supervisor's tool boundary
(`SupervisorRun.before_tool` polls the token and calls `agent.cancel()`: no further delegation,
evidence acquisition or model turn) and inside `CancellationToken.sleep` while waiting for a busy
incident. Provider threads/streams that cannot be interrupted finish in isolation and are fenced.
`OPERON_PRISM_SLOW_COOPERATIVE=0` makes the adapter deliberately non-cooperative (the worker ignores
cancellation) and `OPERON_PRISM_SLOW_HOLD_SECONDS` holds a genuine candidate at the fence: both are
development knobs for reproducing a late real result being fenced. A stale run's failure or
cancellation is audited on the incident only when its revision is still current; otherwise it is
refused by the fence and stays PRISM history, never the session's current failure.

### Exactly-once apply, settlement and governance

A current candidate applies once: the PRISM run row moves `RUNNING → COMPLETED` under a CAS, the
`apply:{run_id}` effect is unique per (session, revision), `_complete_run` is idempotent per Operon
run id (a different result for the same run is a `PromotionConflict`), and the whole apply rolls
back with the commit if any step fails. Duplicate completion, a replayed execution (refused at the
claim: `already_terminal`), a retried HTTP/websocket message (idempotency key) and a restart after
the apply cannot apply twice. Settlement inside the apply is the lifecycle's deterministic rule:
`ADVISORY_CONCLUSION` goes through the unchanged diagnosis gates (`promote_diagnosis` still requires
the trusted technical confirmation; without it the incident parks in `AWAITING_EVIDENCE`),
`NEEDS_EVIDENCE` parks the incident, blocked/failed candidates are recorded and left to the
operator (PRISM never escalates on the operator's behalf). A plan proposed by the run is exposed
as `plan_candidate` only; approval, execution and outcome verification are untouched. If the
frozen inputs changed during reasoning (evidence collected mid-run), the report is recorded as
history through the fence and one bounded further pass reasons over the refreshed packet
(`OPERON_PRISM_SLOW_MAX_PASSES`, default 2).

### Recovery

`retry_current_revision` now retries production reasoning: the new attempt claims a **new** Operon
run (the dead attempt's snapshot stays as history; its claim effect stays COMPLETED), reasons again
from the current canonical instruction over the authoritative incident, and applies once. An
abandoned pre-restart worker that returns later meets a terminal run row and is refused.

### Provider role and provenance

The adapter resolves its backend through `backend_from_environment(role="slow")` →
`registry.build(role="slow")`: a role override in the provider configuration wins, otherwise the
active provider (Gemini, Ollama or Bedrock) is used, so today's selection stays valid. Without any
configured provider the labelled `DeterministicAdvisoryBackend` reasons (provider `none`,
provenance `SIMULATED`, `live_model=false`); a configured but unusable provider is reported as a
run failure, never silently replaced. Every PRISM run records the effective backend, provider,
model id, `live_model`, provenance (`LIVE` / `INJECTED` / `SIMULATED`) and pass, the Operon
snapshot freezes the same identity, and the Agent Workspace shows it next to the revision.

### Progress events, view and UI

Real progress rides `slow_path_progress` with a `stage`: `reasoning_context_prepared`,
`run_claimed`, `supervisor_started`, `specialist_started`, `specialist_completed`,
`evidence_considered`, `cancellation_observed`, `candidate_ready`, `development_hold`,
`candidate_fenced` (`committed` / `stale` / `retry`), `candidate_applied`, `waiting_for_incident`,
`stale_failure_fenced`. Every event carries session/revision/run identity and only safe status
fields. The session view gains `reasoning`: the current instruction, the current run's progress,
a structured candidate summary (disposition, recommended hypothesis, confidence, specialists,
evidence used, next step), the apply outcome (report id, settlement, incident phase), the current
failure and the stale candidates that were fenced. The Agent Workspace PRISM panel renders these.

While a PRISM revision reasons over an incident, the engine's autonomous diagnosis for that
incident is suppressed (`normal_diagnosis_suppressed`, `suppressed_prism_active`); the adapter in
turn waits (cooperatively, bounded by the deadline) while the Guided Demo controller or an engine
diagnosis owns the incident. An instruction on an `AWAITING_EVIDENCE` incident resumes
`INVESTIGATING` inside the fenced claim (audited as `operator instruction (PRISM revision N)`).

### Verification

```
uv run python scripts/prism_production_seam_check.py            # no cloud: injected backend at the production seam
uv run python scripts/prism_production_seam_check.py --live     # configured provider (Gemini first); candidate held 6 s
uv run python scripts/prism_interruption_check.py               # Stage 1 deterministic adapter check still passes
```

The injected check drives a real incident through the production adapter: revision 1 claims an
Operon run and starts, the correction is accepted as revision 2 while revision 1 is held at the
seam, revision 2 claims its own run with the correction as the authoritative instruction, both
results are released, revision 1's valid diagnosis candidate is recorded `STALE` and leaves no
report, revision 2 applies exactly once, and a restart changes nothing. `--live` refuses to run
(exit 2) unless a live provider is configured for role `slow`, and only reports `LIVE` when the
run's provenance is `LIVE`. Tests: `tests/test_prism_production.py` (wiring, correction, stale and
non-cooperative candidates, the apply race on durable connections, exactly-once apply, stale
failure, recovery, responsiveness, bounded retry pass, lifecycle boundaries, the transact primitive).

## Stage 1 / Stage 2 versus later work

Done: persistent identity model, revision/supersession, cooperative cancellation, atomic fencing,
request and effect idempotency, recovery, versioned events, the production Slow Path over the real
supervisor/specialist stack with compute-before-commit, fenced incident apply, bounded instruction
context, real progress events and Agent Workspace visibility. Stage 3+: Fast Path intelligence
(provider `role="fast"`), multimodal grounding (`voice_transcript`, `image_reference` are accepted
but not processed; image/voice understanding and evidence fusion), the final interruption UX,
intervention-review stages under PRISM, benchmark suite, demo video and submission hardening.
