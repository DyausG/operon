# Strands foundation and application promotion boundary (Steps 12A–13B)

Strands supplies model interaction, tool selection, and Pydantic structured output.
Operon supplies evidence capabilities and owns persistence, lifecycle, validation,
promotion, approval, and execution. Five independent specialists and a native
Reliability Supervisor are available through explicit application entry points.
Step 13A adds durable application run/report storage and authoritative promotion.
Step 13B binds that promotion boundary into the durable incident lifecycle, the
atomic approval flow and governed execution (`core/reliability/lifecycle.py`); the
engine drives it by default and the old proposal shortcut is opt-in legacy code.

## SDK and runtime

Both dependency manifests pin **strands-agents==1.54.0**, the approved architecture's
baseline. The installed package was inspected and tested on Python 3.12. Resolution
kept every existing dependency version, adding only Strands and its five missing
transitive dependencies. No AgentCore, extras, or strands-agents-tools are installed.

The factory uses native `Agent`, `BedrockModel`, `SequentialToolExecutor`, and
`@tool(context=True)`. Invocation uses `invoke_async(..., limits=...)`,
the role's `structured_output_model`, and `result.structured_output`.
It does not use the deprecated standalone structured-output method or parse model
prose as JSON. Scalar tool constraints are validated by Step 11's capability models;
1.54.0's decorator does not support `Annotated[scalar, Field(...)]`. Nested Pydantic
tool input models are supported and used for evidence requests.

Bedrock is the primary and only configured live runtime in this package. Model ID
and region are required; `live_enabled=False` prevents accidental client creation.
Imports and runtime construction create no model, client, or credential session.
An explicitly enabled agent creation resolves AWS credentials, then constructs the
Bedrock client. Missing credentials/configuration fail clearly. Access errors during
invocation propagate as `SpecialistInvocationError` with their original cause
(`DiagnosticInvocationError` remains a compatibility alias). There is no
Gemini selection or silent fallback here.

The legacy `core/config.py` model ID and provider auto-selection are not inherited.
Select an account-enabled model/inference profile explicitly. Live account/region
model availability has **not** been verified: this stage makes no cloud calls.

Defaults: 2,500 output tokens per model call, temperature 0.1, 3s connect and 30s
read timeouts, two total Botocore request attempts with standard retry mode, no
additional Strands retries, 90s invocation deadline, six turns, 8,000 cumulative
output tokens, and 32,000 cumulative total tokens. Token caps are native soft caps
checked between turns; one response can overshoot them. The evidence adapter also
allows at most 12 capability calls per invocation, including evidence and resource
reads and multiple calls in a single turn.

Tools execute sequentially, keeping Step 11's revision-checked evidence writes
ordered. Synchronous evidence work runs in threads. Cancellation stops awaiting an
invocation; an already running SDK request or evidence thread may finish under its
own timeout. Evidence already committed is retained, including if its response is
oversized or the model fails. No consequential action is available to those threads.

## Calling the reference specialist

From an application-owned async caller, with a known incident and selected durable
evidence IDs:

```python
from core.agents.diagnostic import assess_diagnosis
from core.agents.runtime import RuntimeSettings, StrandsRuntime
from core.reliability.assessments import prepare_diagnostic_context
from core.reliability.evidence import EvidenceService
from core.reliability.repository import IncidentRepository

repository = IncidentRepository()
context = prepare_diagnostic_context(
    repository, incident_id, asset_id=asset_id, run_id=run_id,
    evidence_ids=selected_evidence_ids,
)
runtime = StrandsRuntime(RuntimeSettings(
    model_id=account_enabled_model_id, aws_region=aws_region, live_enabled=True,
))
assessment = await assess_diagnosis(runtime, EvidenceService(repository), context)
```

Each call creates a fresh Strands Agent. Do not share stateful injected models
between concurrent runs; tests inject a scripted native Strands `Model`. Context
contains one selected asset, input revision, run ID, and at most 20 evidence records
within 64,000 bytes. Treat this context as trusted application input, never as a
model-selected scope. Use the same repository for context preparation and evidence
service. Input revision is provenance, not a lifecycle transition request or a lock.

The six exposed capability tools are `get_asset_context`, `get_telemetry_window`,
`get_maintenance_history`, `get_related_incidents`, `get_operating_context`, and
`request_evidence`. Their closures bind incident and asset; invocation state must
match the trusted run. Tools expose no caller-selectable role or approval authority.
Reads delegate to `EvidenceCapabilities.collect`. Requests delegate to
`EvidenceService.request_and_collect` with fixed diagnostic role/purpose.

Responses retain complete Step 11 provenance in Strands JSON content blocks and
reject payloads over 48,000 bytes rather than silently truncating them. Request
inputs are capped at 4,000 bytes and unsupported capabilities fail explicitly.
Read observations need `request_evidence` before they can be cited as new durable
evidence. Only successfully returned request evidence IDs join the citation set.

## Advisory output and separate application promotion

`DiagnosticAssessment`, `EngineeringAssessment`, `OperationsAssessment`,
`CriticAssessment`, and `MaintenancePlanAssessment` are bounded Pydantic reports.
They reference durable incident/evidence/artifact IDs; diagnostic hypothesis keys
are explicitly local labels. They do not inherit domain `Artifact` and are not
registered with the repository. Planner risk flags and critic recommendations are
advice, never executable parameters or policy decisions.

```text
Strands DiagnosticAssessment
    -> application schema, incident, and supplied/collected citation checks
    -> persisted advisory SupervisorReport
    -> independent application PromotionService gates
    -> atomic Hypothesis / Diagnosis promotion
```

The specialist validator in `assessments.py` checks structure and reference scope.
It does not establish causal truth, evidence sufficiency, freshness, or approval.
Step 13A implements these separate promotion prerequisites in `promotion.py`. The specialist cannot write Diagnosis,
ValidationVerdict, Intervention, ApprovalRequirement, or Outcome; it cannot change
phase, reserve parts, book labor, commit a schedule, dispatch notifications, or
invoke the governed executor. Requesting evidence may append only the existing
evidence/request records and corresponding incident revisions/events.

Each specialist has a narrow prompt, an explicit capability allowlist,
and application validation around its advisory contract. The supervisor now wraps
these entry points as native Strands agents-as-tools. `PromotionService` adds
independent review, revision/freshness checks, cancellation reporting, and atomic
promotion. Lifecycle orchestration and governance integration remain Step 13B. Do not pass repositories or
consequential service methods as tools.

## Independent specialist APIs and tools

All entry points are async functions taking `(runtime, evidence_service, context)`.
They create one fresh native Strands Agent through `StrandsRuntime.create_agent`.
`core/agents/invocation.py` shares only invocation limits, error handling, and
application validation; it does not sequence or dispatch specialists.

| Module / entry point | Advisory output / responsibility | Exact capability allowlist |
|---|---|---|
| `diagnostic.assess_diagnosis` | `DiagnosticAssessment`: competing causal hypotheses, opposing/supporting evidence, missing evidence and confidence | `get_asset_context`, `get_telemetry_window`, `get_maintenance_history`, `get_related_incidents`, `get_operating_context`, `request_evidence` |
| `engineering.assess_engineering` | `EngineeringAssessment`: feasibility, missing constraints, technical blockers, safety | `get_asset_context`, `get_telemetry_window`, `get_maintenance_history`, `get_operating_context` |
| `operations.assess_operations` | `OperationsAssessment`: resource feasibility, conflicts and coordination | `get_asset_context`, `get_maintenance_history`, `get_operating_context`, `check_part_availability`, `inspect_available_technicians`, `inspect_maintenance_windows` |
| `critic.review_assessment` | `CriticAssessment`: adversarial technical review, objections and evidence requests | `get_asset_context`, `get_telemetry_window`, `get_maintenance_history`, `get_related_incidents`, `request_evidence` |
| `planner.plan_maintenance` | `MaintenancePlanAssessment`: ordered proposal, dependencies, exposure, reversibility and approval relevance | `get_asset_context`, `get_maintenance_history`, `get_operating_context`, `check_part_availability`, `inspect_available_technicians`, `inspect_maintenance_windows` |

Strands adds the role's structured-output tool to that allowlist. No tool exposes
SQL, a registry/service object, consequential service methods, or lifecycle commands.
The evidence request wrapper enforces the role's read allowlist too. Diagnostic
requests have fixed diagnosis purpose; Critic requests use the application's
`context.evidence_purpose` (`diagnosis` by default, or `intervention`). Roles and
purpose are not model-selected tool arguments. Only these two specialists can
append evidence/request records, through the existing EvidenceService.

`get_maintenance_history` already reads existing work orders, status, maintenance
events, and parts; a duplicate CMMS lookup was unnecessary. The three new
`ResourceCapabilities` methods use the existing local service tables and the
application's evidence context. Their connections enable SQLite `query_only`.
They deliberately do not call legacy `assign_technician`, `block_schedule`, or
CMMS draft/write methods. Remote resource adapters are not implemented or selected
implicitly; these capabilities explicitly inspect the local Operon store.

Resource reads return typed observations with provenance and record IDs. Limits
are 1–50 records (default 20); overflow fails explicitly rather than presenting a
partial list as complete. Inventory distinguishes missing BOM/quantities (`UNKNOWN`)
from shortages (`UNAVAILABLE`) and subtracts outstanding reservations. Workforce
lists available same-plant roster entries with the exact recorded equipment-class
skill and active booking counts; it does not use the legacy on-shift fallback.
Qualified dated availability remains unknown. Scheduling exposes same-line booking
labels and reports `UNKNOWN`: there is no persisted production calendar or dated
maintenance-window source. Empty bookings never imply an available production window.
Resource results are snapshots, not reservations or new durable Evidence. Agents
can reference their source record IDs in observations but cannot cite them as
Evidence IDs. Step 13A provides a separate trusted application submission for
durable dated resource confirmation; agents cannot invoke it.

## Bounded inputs and reference validation

`prepare_specialist_context` builds `SpecialistContext`, extending the compatible
`DiagnosticContext` with lifecycle state, up to 10 selected durable domain artifacts,
and up to five supplied `AdvisoryInput` reports. The whole packet, including its
maximum 20 evidence records, remains capped at 64,000 bytes. Artifact snapshots
retain their durable IDs and status. The lower-level context remains disposable;
`PromotionService` freezes its complete payload in a durable run snapshot.

An `AdvisoryInput.key` is an application-assigned local packet label, never a
durable assessment ID. This supports advisory review independently of promotion:

```python
from core.agents.contracts import AdvisoryInput
from core.agents.engineering import assess_engineering
from core.reliability.assessments import prepare_specialist_context

# prior_diagnostic is a returned DiagnosticAssessment; the application selects it.
context = prepare_specialist_context(
    repository, incident_id, asset_id=asset_id, run_id=run_id,
    evidence_ids=selected_evidence_ids,
    advisory_inputs=(AdvisoryInput(key="diagnostic-input", assessment=prior_diagnostic),),
    question="Assess engineering support for inspection and identify missing constraints.",
)
engineering = await assess_engineering(runtime, EvidenceService(repository), context)
```

Include the evidence and domain artifacts cited by supplied advice, along with
any other local reports its `input_assessment_keys` references. Packet keys must be
unique, distinct from durable IDs, and cannot cite themselves. Engineering requires
a supplied durable Diagnosis or diagnostic advisory input. Operations requires a
durable Intervention or advisory input. Critic can target a durable diagnosis or
intervention, or `subject_kind="assessment"` with a supplied local subject key.
Planner requires durable input references and/or supplied advice. Its legacy
`validated_input_ids` field names selected domain records; membership alone does
not mean acceptance or policy validation. Null diagnosis/intervention IDs are
permitted for advisory-only inputs, never replaced by invented durable IDs.

Every invocation rechecks evidence/artifact content against the same repository
before model access, including manually built or copied contexts. Output checks
reject foreign incident IDs, foreign/unprovided evidence, nonexistent or wrong-type
domain references, unsupplied advisory keys, and out-of-scope planner equipment.
Plan dependencies must point to preceding zero-based step indices; nested citations
must appear in `evidence_reviewed`. Unknown exposure amount/currency travel together.
Strict confidence, exposure, and risk-flag types reject misleading scalar coercion.
Schema consistency rejects unconditional feasibility with missing constraints or
blockers, and advisory acceptance with unresolved objections. None of these checks
is authoritative engineering validation or governance policy.

The Reliability Supervisor calls these same functions through native agents-as-tools
wrappers. Application code still chooses trusted scope, independently reviews advice,
validates freshness before promotion, promotes artifacts, and applies governance.
The run guards handle bounds and cancellation; they confer no domain authority.

## Reliability Supervisor: native delegation

`core/agents/supervisor.py` supplies `supervise_reliability` and the native Agent
factory. The mechanism is **async `strands.tool(context=True)` agents-as-tools**:
the supervisor is a native `strands.Agent` with six decorated tools. Strands'
event loop selects and executes those tools using `SequentialToolExecutor`.
Five tools call the existing specialist entry points, each of which creates a
fresh native Agent and awaits `Agent.invoke_async` with its own structured-output
contract and original tool allowlist. Validated `AdvisoryInput` JSON returns to
the supervisor in a native tool-result content block. No application loop selects
the specialist order, and no specialist output is accepted by parsing prose.

The sixth tool, `acquire_requested_evidence`, refers to a supplied Diagnostic or
Critic assessment key and a zero-based evidence-need index. Its capability and
question come from that validated report. Parameters pass the existing bounded
capability schemas. There are no direct asset/database reads or consequential
operational tools in the supervisor allowlist.

The installed **1.54.0** source was audited before implementation: `Agent`,
`invoke_async`, `Limits`, the async decorator, sequential executor, tool hooks,
and structured-output behavior are exercised offline. The installed Agent also
supports `Agent.as_tool(name=..., preserve_context=False, delegate=False)` and
direct Agents in `tools`. Its adapter accepts a free-form `input` string, calls
the child streaming API, and returns text. Custom decorated wrappers fit this
step better: they reuse the existing validated entry points, pass trusted invocation
scope and explicit child limits, and return bounded typed assessment JSON. The
supervisor uses those genuine native custom tools rather than the convenience
adapter. See the official
[agents-as-tools pattern](https://strandsagents.com/docs/user-guide/concepts/multi-agent/agents-as-tools/)
and [custom tools](https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/).

The conceptual workflow is Diagnostic → Critic → justified evidence → Diagnostic
refinement → Engineering → Operations → Critic → Planner. The prompt guides that
workflow, while model-selected delegation also supports early stops and different
orders. Application completeness checks determine whether an advisory conclusion
is structurally supported; they do not drive a fixed pipeline or establish truth.

## Application run boundary and contracts

`core/reliability/orchestration.py` owns disposable `SupervisorRun` bookkeeping,
scope/reference checks, dependency closure, budgets, evidence collection, and final
result assembly. It calls only existing evidence/application boundaries. It never
adds Diagnosis, Intervention, ValidationVerdict, ApprovalRequirement, or Outcome,
changes lifecycle phase, reserves stock, assigns labor, books downtime, writes CMMS
operations, or invokes consequential execution. Step 13A wraps this lower-level
runner with separate durable run/report commands. EvidenceService may append evidence,
request, resolution, incident revision, and event records.

`SupervisorDecision` is the native Pydantic model output: incident/run identity,
advisory disposition and reasoning, evidence citations, typed-role assessment keys,
unanswered evidence needs, and blockers. Extra fields and invented or out-of-scope
references are rejected. It cannot supply audit counters or authoritative objects.

The application returns a frozen `SupervisorResult`, containing the validated
decision (or null on failure), effective advisory disposition, actual delegations,
complete validated assessments and citations, evidence acquisition records, current
diagnostic/engineering/operations/plan keys, critic keys, unresolved needs, blockers,
termination reason, configured bounds, and exhausted limits. All keys identify
ephemeral advice, not durable diagnosis or intervention records. All results require
human review, including `ADVISORY_CONCLUSION`; that label never grants approval.

The effective disposition conservatively retains unknown engineering constraints,
operational blockers, critic objections, failed acquisitions, and model/tool errors.
An optimistic model summary cannot erase these findings. A supported conclusion
in the default `INVESTIGATION` purpose requires all five roles, a recommended hypothesis, current linked engineering and
operations advice, critic review of those current inputs, and a planner proposal
with known risk/exposure metadata. Re-review of an unchanged subject cannot erase
earlier objections. A revised report needs a new review; old reports remain in the
audit. These are structural completeness checks, not causal validation or policy.

Contexts are prepared with `prepare_specialist_context`. Each delegation receives
the application's selected asset, evidence, and artifacts, plus only the requested
advisory reports and their complete transitive dependencies. The existing limits
remain: 20 evidence records, 10 selected artifacts, five advisory reports, and
64,000 bytes per context. Unknown keys and cyclic dependencies fail. A dependency
closure exceeding five reports is blocked without stripping provenance. Fresh
evidence is included in subsequent packets, whose durable content is rechecked.
There is no unrestricted database dump and no model-selectable incident or asset.

## Orchestration bounds and evidence loop

| Bound | Default | Configurable maximum / behavior |
|---|---:|---|
| Supervisor model turns | 12 | 12, native `limits.turns`; overrides the specialist-oriented runtime turn setting for the supervisor only |
| Supervisor tool calls | 24 | 64, native `BeforeToolCallEvent` guard counts even malformed/unknown calls and structured output; excess cancels the loop |
| Specialist invocations | 10 | 12 total, including failures/cancellations |
| Invocations of one role | 3 | 4, shared across that role's fresh Agents |
| Evidence acquisition rounds | 3 | 10, or 0 to disable; one attempted request per round, shared by supervisor, Diagnostic, and Critic |
| Entire supervisor invocation | 240 seconds | 600 seconds, includes awaited nested specialists and evidence collection |
| Each specialist invocation | Runtime default 90 seconds / 6 turns | Existing runtime settings and capability-call limits remain in force |

Supervisor and specialist token budgets use the existing runtime's native soft
output/total-token caps (defaults 8,000/32,000 each). They are per Agent invocation,
not an aggregate billing meter. The total number of such invocations is bounded;
the default run can invoke at most one supervisor and ten specialists. A response
may overshoot a token cap before the SDK checks it. Model transport timeouts and
retry settings remain as documented above; live model/credential construction is
explicit and precedes the invocation deadline.

Delegation fingerprints use role, complete selected report keys, and evidence IDs.
Rephrasing a question with identical inputs reuses the successful result; identical
failed work is not restarted. Changed evidence or report inputs permits refinement,
subject to total/per-role limits. There is no recursive supervisor tool available
to specialists. Tools remain sequential within each Agent.

Diagnostic and Critic retain their independent `request_evidence` tools. An optional
application callback in their invocation path enforces the same run-wide evidence
budget as the supervisor tool. It binds incident/asset/purpose, rechecks capability
parameters, and calls `EvidenceService.request_and_collect`. Normalized identical
capability/parameter/purpose requests reuse returned durable provenance even if
question text changes; failed identical requests are not retried during that run.
Unsupported and failed acquisition attempts consume the shared budget. Capability
calls rejected before acquisition still consume the existing per-specialist tool
budget or supervisor tool budget. No evidence is invented.

Collection results are checked against persisted evidence and resolution records,
and oversized output fails without truncation. Missing evidence remains explicit:
`UNAVAILABLE` records can be cited as missing data; successful collection alone
does not mean a diagnostic question is resolved. Diagnostic refinement and fresh
critic review may establish a more complete advisory packet. Unsupported inspection
and OEM retrieval stay unresolved. Resource reads remain local, read-only snapshots;
these tools cannot create the trusted dated resource confirmation required for promotion.

Model failures, invalid final references/output, specialist failures, evidence
failures, and exhausted budgets produce bounded unresolved/blocked/escalated results.
Native structured-output validation may give the model a correction turn within its
limits; invalid data never joins the accepted report set. Caller cancellation is
propagated and timeout returns a structured escalation snapshot. An already-running
SDK request or synchronous evidence worker may finish under its own limits after
cancellation. Committed evidence remains durable; late worker results cannot modify
the returned run snapshot. A cancelled request record may therefore lack the IDs of
evidence subsequently committed by that worker. Future application reconciliation
must inspect durable records; this step introduces no background task manager.

## Calling the supervisor

```python
from core.agents.contracts import SupervisorBounds
from core.agents.supervisor import supervise_reliability
from core.reliability.assessments import prepare_specialist_context

# repository, runtime and evidence_service are explicitly configured by the app.
context = prepare_specialist_context(
    repository, incident_id, asset_id=asset_id, run_id=run_id,
    evidence_ids=selected_evidence_ids,
    question="Investigate competing causes and propose supported next steps.",
)
advice = await supervise_reliability(
    runtime, evidence_service, context,
    bounds=SupervisorBounds(max_delegations=10, max_evidence_requests=3),
)
# advice is advisory data. It must not be dispatched as an executable command.
```

An optional `specialist_runtime` supports a separately injected native Model/runtime
for specialist calls. Offline tests script only the Model boundary and exercise
actual nested Strands loops. Each run and each specialist conversation is fresh;
do not share mutable scripted model state between concurrent incident runs.

## Step 13A: persisted runs and authoritative promotion

**Agents reason. The application owns authority.** `SupervisorResult` remains
advisory, including a schema-valid result with Critic `ACCEPT`. No agent tool
exposes `PromotionService`, trusted confirmation submission, or authority pointers.
The existing direct `supervise_reliability` API remains an advisory-only API.

The trusted application uses `PromotionService.run_supervisor(...)`. It calls
`start_run(...)` to claim an application-assigned `active_run_id` and persist one
immutable `SupervisorRunSnapshot` in a short `BEGIN IMMEDIATE` transaction. The
snapshot includes incident/asset/stage, the committed input revision, exact evidence
and artifact hashes, the complete input packet, bounds, runtime settings and model
implementation/configuration identity, prompt/schema hashes, SDK version and time.
This version starts fresh advisory packets; its advisory input manifest is empty.
Prior planner advice is referenced through its durable source report when binding
a draft, rather than injecting caller-supplied advisory JSON into a new run.

Model invocation starts **after** the transaction commits. On return, the private
application completion command persists one terminal `SupervisorReport`: snapshot
reference, complete result JSON and hash, input/completion/checkpoint revisions,
evidence manifest, termination classification, staleness reasons and completion
time. Loading a report explicitly validates its JSON as `SupervisorResult`.
Cancellation retains the native partial audit and propagates cancellation; model
construction failures also leave a terminal failed report. Process death can leave
a snapshot without a report; automatic recovery/reconciliation remains deferred.

The revision sequence is explicit:

```text
incident revision r
  -> atomic run claim + snapshot at input revision r+1
  -> model reasoning, with no application write transaction held
  -> completion observes c; report commits checkpoint c+1
  -> promotion requires c == r+1 and current revision == c+1
  -> all promoted artifacts + pointer + phase commit in one revision c+2
```

Any incident revision change during reasoning makes the report ineligible,
including evidence requested and acquired by the same run. The original input
revision is never rewritten. Such a report remains an evidence-acquisition audit;
a new run over the committed evidence is required. Later evidence, superseded
sources, unresolved durable evidence requests, or a newer active run also block
promotion. An old run's late report is retained with a stale classification.

Raw operational changes are checked independently. Migration 004 adds a local
source generation counter with insert/update/delete triggers over the operational
source tables. Run snapshots and application-collected evidence retain a hash of
the raw source rows, generation and other incidents' revisions. Promotion compares
these under the same SQLite write lock; even a source change followed by restoration
invalidates the checkpoint. Version 1 deliberately uses a broad local manifest, so
unrelated asset changes can require fresh collection and reasoning. Older evidence
without a source checkpoint is not eligible for new promotion. No external adapter
or model call happens inside a promotion transaction.
EvidenceService refreshes stale cached source reads into new superseding evidence
and request records; unchanged-source retries retain their existing identities.

### Diagnosis

`submit_technical_confirmation` accepts a typed `TrustedTechnicalConfirmation`
from a trusted application caller and stores it as `Evidence(kind="inspection")`.
It records exact incident/asset/mechanism, optional validated failure-mode code,
durable supporting evidence, checks actually performed and their results,
observation time, actor/source and explicit `OBSERVED` or `SIMULATED` provenance.
Submission verifies supporting technical evidence; classifier/model evidence alone
is insufficient. The reserved confirmation capability cannot be written through
the generic public repository method and is not an agent tool. Authentication of
the submitting inspector/dispatcher belongs to the calling application; no public
submission endpoint or identity system is added in 13A.

`promote_diagnosis` loads a report by ID; it never accepts a result payload. It
requires a fresh successful run, no cancellation/timeouts/invalid outputs/limits/
failed invocations, canonical diagnostic advice from that run, a recommended
hypothesis with nonempty uncontradicted technical support, explicit Critic review
of the unchanged selected assessment, no unresolved requests or objections, valid
evidence closure, and an **exact** compatible trusted mechanism confirmation.
Missing confirmation raises `PromotionRefused(disposition="NEEDS_EVIDENCE")`.
There is no confidence threshold, fuzzy reconciliation or SHAP causal inference.

The transaction creates new application IDs for competing `Hypothesis` artifacts,
an accepted `Diagnosis`, an application `ValidationVerdict(ACCEPT)`, a
`PromotionRecord`, `current_diagnosis_id`, and `DIAGNOSIS_VALIDATED`. The record maps
report-local hypothesis keys to durable IDs and records report/target hashes,
policy, input/output revisions, verdict, evidence and idempotency identity.
Alternative hypotheses and suggested falsification tests survive translation.
Suggested tests do not become performed falsification attempts. Numerical causal
confidence is `None`; advisory confidence stays in the report. Critic findings are
preserved in reports and verdict challenges.

**CriticAssessment(ACCEPT) != ValidationVerdict(ACCEPT).** Application verdicts
carry validator identity `operon.application.promotion`, policy
`operon-promotion-1`, original input revision, exact target hash and named
deterministic check results. They are constructed only after these gates pass.

### Exact draft review and intervention promotion

`create_draft` requires current diagnosis promotion lineage and structured trusted
`WorkPackageBinding` fields: source plan/report, equipment, validated failure-mode
ID, qualified technician, BOM quantities, dated confirmed availability/window,
duration, reviewed instructions, technical preconditions, evidence, explicit cost,
downtime, avoided loss, business assumption version and safety/risk metadata.
There are no zero defaults for missing business values. Planner exposure is never
substituted for cost or avoided loss. This first adapter path requires a validated
failure-mode ID; diagnoses without one remain non-executable through this path.

`submit_resource_confirmation` persists a separate typed, dated trusted resource
attestation as resource evidence. It checks the actual local BOM, stock less
reservations, same-plant technician identity and exact equipment-class skill.
The resource evidence retains the application-checked part numbers, on-hand and
reserved quantities and required quantities for later audit.
Availability, qualification validity and production-window confirmation must cover
the dated work interval. Read-only workforce/schedule snapshots with `UNKNOWN`
remain insufficient; an absence of bookings supplies no confirmation. No inventory
reservation, schedule booking or notification is made here.

The application stores the binding and a `DRAFT Intervention` together, entering
`PLANNING` if necessary. It contains one governed `create_work_package` step;
physical instructions remain inside that step. The existing `WorkPackageParameters`
contract validates concrete parameters. Its legacy classifier-context field comes
from a durable model signal and has no causal confidence or business meaning.

A fresh run with `stage="INTERVENTION_REVIEW"` receives the current diagnosis,
application verdict and exact draft. `review_target_id`/`review_target_hash` survive
every delegation; Engineering, Operations and Critic explicitly return that pair.
Engineering must be `FEASIBLE` with reviewed constraints, no missing constraints,
blockers or safety concerns. Operations must be `FEASIBLE`, cite durable resource
confirmation and current engineering advice. Critic must review the exact draft
and the current engineering/operations inputs without outstanding objections.
For these durable stages, failed specialist tools or invalid intermediate output
make the invocation ineligible even if the model later emits a valid schema.

`promote_intervention` independently repeats freshness, lineage, resource, window,
identity, parameter, capability and business checks. It produces a `VALIDATED`
artifact whose executable content hash equals the reviewed draft's; only identity,
timestamp, status, revision and supersession envelope fields may differ. Any
substantive change requires a new binding/draft/review. Application risk is
conservatively `HIGH`. The accepting verdict, promotion lineage including the
diagnosis promotion and draft hash, `current_intervention_id`, and
`INTERVENTION_VALIDATED` transition commit atomically. No approval is created.

### Retry, migration and compatibility

Promotion identity is deterministic per incident/run/stage. Successful lookup
precedes revision/freshness rejection, so a retry returns the original record/IDs.
A changed command payload under that identity is a conflict. `BEGIN IMMEDIATE`
and unique indexes serialize concurrent attempts. Retrying an old success never
writes pointers or reactivates superseded authority. Rollback tests inject failure
after every artifact, pointer/revision and event write for both promotion stages.

Migration `004_authoritative_promotion.sql` uses the existing immutable artifact
store for snapshots, reports, bindings and promotion records. Unique indexes enforce
one snapshot/run, one terminal report/run, one promotion/incident/run/stage,
idempotency identity and target. It is additive and repeat-safe under the existing
migration ledger. Optional new metadata does not change hashes of old artifacts;
legacy records receive no promotion backfill.

`prepare_legacy_intervention` is explicitly deprecated and compatibility-only.
Its artifacts lack new promotion lineage and authority pointers, and cannot satisfy
new promotion APIs. Since Step 13B the engine calls it only when `OPERON_LEGACY_DEMO`
is set, it emits `DeprecationWarning`, and the lifecycle approval/execution commands
refuse its artifacts. The pure state graph still grants no authority; promotion and
lifecycle commands establish the prerequisites and include their phase transition
in the same transaction.

Run `uv run pytest tests/test_promotion.py` for durable/native paths, negative gates,
source freshness, exact review, rollback, concurrency, migration and legacy checks.
These tests require neither AWS credentials nor network access.

## Step 13B: lifecycle, approval and governed execution

`LifecycleService` (`core/reliability/lifecycle.py`) is the trusted application
owner of every transition after promotion. It is not an agent tool, it invokes
models only through `PromotionService.run_supervisor`, and every authoritative
command is one `BEGIN IMMEDIATE` transaction that re-derives authority from durable
pointers plus `PromotionService._lineage(current=True)`. Phase alone proves nothing:
an incident moved to `READY` by graph-legal transitions without a `PromotionRecord`
is refused by every lifecycle command (`AuthorityRefused`).

The durable flow is:

```text
ModelSignal -> admit_signal (atomic)                          OPEN
  -> DeterministicInvestigator baseline evidence              INVESTIGATING
  -> LifecycleService.diagnose: refresh stale baseline reads,
     start_run + SupervisorRunSnapshot, native supervisor,
     SupervisorReport, promote_diagnosis                      DIAGNOSIS_VALIDATED
       NEEDS_EVIDENCE / UNRESOLVED / no trusted confirmation  AWAITING_EVIDENCE
       failed, exhausted, BLOCKED, ESCALATED, gate failure    ESCALATED
       report stale (concurrent change)                       stays INVESTIGATING (bounded retry)
  -> submit_technical_confirmation (trusted)   AWAITING_EVIDENCE -> INVESTIGATING
  -> LifecycleService.plan: create_draft (binding + DRAFT)    PLANNING
     fresh INTERVENTION_REVIEW run, promote_intervention      INTERVENTION_VALIDATED
     request_approval (deterministic governance)              AWAITING_APPROVAL
       NEEDS_EVIDENCE at planning                             stays PLANNING (new binding required)
       governance BLOCKED / unsafe review                     ESCALATED
  -> decide_approval APPROVE (exact identifiers)              READY
     decide_approval REJECT                                   ESCALATED
  -> execute: claim transaction                               EXECUTING
     adapter call with no lock held
     receipt transaction   CONFIRMED                          OBSERVING
                           FAILED / UNKNOWN                   EXECUTION_FAILED
  -> retry_execution (only after definitive FAILED)           READY
```

Nothing in 13B verifies outcomes or closes incidents. **Execution SUCCESS means
the commanded work-package action was confirmed by the adapter; it does not mean
the machine recovered.** No `Outcome` is created and `CLOSED` is never reached.

### Governance

`LifecycleService._governance` is deterministic and consumes only the exact
promoted `Intervention`, its `PromotionRecord`, its `WorkPackageBinding` and local
rows. Checks: one governed `create_work_package` step, valid `WorkPackageParameters`
matching the binding, permitted risk and policy-bound risk metadata, the confirmed
window has not started, resources (same-plant qualified technician, BOM stock less
reservations) can still be established, and no application verdict rejects the
target. Blockers raise `GovernanceBlocked` and are never converted into an approval
request. A passing assessment always yields `REQUIRES_HUMAN_APPROVAL`: in 13B every
promoted work package is an external, safety-relevant, irreversible commitment.
Critic `ACCEPT`, planner advice, supervisor disposition and legacy
`LocalGovernanceAdapter` output play no part.

### Approval (authorization, not validation)

`request_approval` runs authority + governance and, in the same transaction, inserts
an `ApprovalRequirement` bound to incident, exact intervention ID and hash,
`promotion_id`, `operon-lifecycle-1`, `HUMAN` mode, the approver role, and an expiry
bounded by the confirmed window start, then transitions to `AWAITING_APPROVAL`.
Concurrent requests serialize on the incident revision; a retry with the current
revision returns the existing pending requirement. Migration 005 additionally
enforces one decision per requirement per actor.

`decide_approval` requires the caller's exact `requirement_id`, `intervention_id`,
`intervention_hash` and `context_revision`. In one transaction it rejects stale
context revisions, wrong phases, superseded or expired requirements, hash or ID
mismatches, mismatched promotion lineage, wrong roles, blank rationale, conflicting
duplicates, decisions after new technical evidence invalidated lineage, and any
governance blocker; then it inserts the `ApprovalDecision` (with `promotion_id`) and
moves `AWAITING_APPROVAL -> READY` (APPROVE) or `-> ESCALATED` (REJECT). An identical
decision from the same actor is returned idempotently without any write. Approval
creates no `ValidationVerdict`; the only verdicts are promotion verdicts.

### Execution claim, adapter call, receipt

`execute` resolves the CMMS adapter before any lock, then in one transaction
requires phase `READY`, current lineage, `VALIDATED` status, exact ID/hash,
deterministic governance, a current requirement bound to the same promotion, an
`APPROVED` state, valid parameters, and an idempotency key (identical derivation to
`GovernedExecutor`) whose claim is absent or definitively `FAILED`. `IN_FLIGHT`
raises `ExecutionBusy`; `UNKNOWN`/`CONFIRMED` raise `ReconciliationRequired`. The
claim insert/update, `READY -> EXECUTING` and the `EXECUTION_CLAIMED` event commit
together, so two callers cannot dispatch the same action. The adapter is invoked with
the sealed `ExecutionAuthorization` outside any transaction.

`record_receipt` CASes on the claim identity (key, attempt, `IN_FLIGHT`), never on
the pre-call incident revision. New evidence arriving during the external call
advances the revision but cannot lose the receipt; the receipt, claim state and
phase (`CONFIRMED -> OBSERVING`, `FAILED`/`UNKNOWN -> EXECUTION_FAILED`) commit
together, always against the intervention that was dispatched. If the phase left
`EXECUTING` through another command, the receipt is still recorded and an
`INCIDENT_UPDATED` reconciliation event is appended. Duplicate completion callbacks
with the same status are idempotent; conflicting ones raise `ReconciliationRequired`.
Afterwards `_lineage` reports the new-evidence condition, so approval/execution
authority is re-evaluated without erasing what happened. `UNKNOWN` is never replayed:
`execute` and `retry_execution` refuse until a human reconciles.
`GovernedExecutor.finish_execution_claim` received the same claim-identity CAS,
because the old revision CAS could drop a receipt after a real external action.

### Recovery

`LifecycleService.recover()` reconciles every active incident from durable pointers:
authority validity via lineage, current requirement and approval state, latest claim,
receipts. An `IN_FLIGHT` claim older than the ambiguity window becomes an `UNKNOWN`
receipt plus `EXECUTION_FAILED`; nothing is ever dispatched during recovery. A crash
after the atomic approval leaves a reconstructible `READY`; dispatch then requires an
explicit `execute` command or API call. An old promotion retry still returns the old
record without pointer writes, and the old intervention cannot execute.

### Engine and API

`DemoEngine` admits signals, runs the deterministic investigation and, when a
supervisor runtime is configured (`agent_mode() == "bedrock"` or an injected runtime),
schedules bounded, serialized `diagnose` attempts. Trusted confirmations, bindings,
approvals and execution arrive through `LifecycleService` calls or the API:
`POST /api/approve|reject/{equipment_id}` now require the exact requirement,
intervention, hash and context revision in the body (the dashboard sends them from
the alert projection); `POST /api/incidents/{id}/approval|execute` and
`GET /api/incidents/{id}` expose the same identifiers; typed trusted submission
endpoints (`confirmations/technical`, `confirmations/resource`, `drafts`) are disabled
unless `OPERON_TRUSTED_SUBMISSIONS=1` declares the host boundary trusted. No endpoint
accepts `PromotionRecord`, `ValidationVerdict`, `SupervisorReport` or other authority
JSON. `OPERON_LEGACY_DEMO=1` re-enables the deprecated proposal shortcut.

### 13A corrections made for integration

Two narrow corrections were required, both documented in code:

1. `IncidentRepository.finish_execution_claim` and `LifecycleService.record_receipt`
   use the execution claim identity as completion CAS (see above).
2. `PromotionService._fresh` still blocks on OPEN durable evidence requests and on
   resolved GOOD evidence missing from the packet, but no longer blocks on requests
   whose only resolution is SUSPECT/MISSING evidence (UNAVAILABLE capability, partial
   baseline context). Such evidence can never enter a packet under the GOOD-quality
   rule, so the old check made promotion impossible for any investigated incident.

### Known conflict: whole-store source checkpoint versus live operation

13A's `source_state_hash` covers every operational table (including streaming
`sensor_reading`/`health_score`) and other incidents' revisions. Consequently a run
is stale whenever the simulator persists a tick or another incident advances. The
lifecycle refreshes stale baseline reads before each diagnosis run and the engine
serializes reasoning, but promotion still requires quiescent raw sources between
evidence collection, reasoning and promotion (for example, the plant stream paused
via `/api/stop`, as the offline engine tests do). Source-specific versioning remains
the deferred fix; 13B deliberately did not weaken the checkpoint.

## Scope and verification

No material architecture deviations. The package lives at `core/agents/` as allowed
by Step 12A, rather than the architecture sketch's `core/reliability/agents/`.
Assessment names distinguish advice from the authoritative artifacts in the sketch.
The legacy deterministic fallback remains available; no second agent framework or
new deterministic diagnostic workflow is introduced.

Live fallback integration, AgentCore, RAG/OEM ingestion, procurement, outcome
verification, automatic closure, provider migration, source-specific freshness
versioning, host authentication and frontend redesign remain deferred after 13B.

Run `uv run pytest tests/test_reliability_lifecycle.py tests/test_engine_lifecycle.py`
for the 13B lifecycle: atomic approval/claim/receipt transactions with rollback
injection, concurrency (two approval requests, two executions, duplicate decisions
and callbacks), stale/superseded approvals, governance blocks, the evidence-during-
execution race for CONFIRMED/FAILED/UNKNOWN, UNKNOWN non-replay, restart after claim
or approval, legacy artifacts and phase-only incidents refused, and the engine/API
contract. These tests require neither AWS credentials nor network access.

Run `uv run pytest tests/test_supervisor.py tests/test_strands_agents.py tests/test_specialists.py` for native SDK construction,
scripted model/tool/structured-output cycles, import checks, budget/error behavior,
and authoritative-state invariants. The existing test network guard blocks outbound
connections and DNS; the import smoke test installs its guard before Operon imports.
Then run the full suite and evidence/investigation/execution suites.

Known limitations: no OEM specifications/manual retrieval; no real production
calendar, qualification-expiry records, or dated booking overlap checks; local
resource observations may include seeded demo data. Prompts and scripted native
model tests verify integration contracts and state boundaries, not live-model
reasoning quality or factual truth of narrative claims. Long dependency chains can
exceed the five-report/64 KB packet bound and require a new application-selected
investigation packet. Lower-level direct specialist/supervisor calls remain advisory
and disposable; only the PromotionService wrapper establishes a durable run checkpoint.
Real Bedrock access, live supervisor/specialist-quality evaluation, and AgentCore
functionality have not been validated. No semantic validator can
infer missing engineering facts from a valid citation alone.

API references: [1.54.0 release](https://pypi.org/project/strands-agents/1.54.0/),
[structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/),
[tagged Agent source](https://raw.githubusercontent.com/strands-agents/harness-sdk/python/v1.54.0/strands-py/src/strands/agent/agent.py).
