# Strands foundation and independent specialists (Steps 12A–12B)

Strands supplies model interaction, tool selection, and Pydantic structured output.
Operon supplies evidence capabilities and owns persistence, lifecycle, validation,
promotion, approval, and execution. Five independent specialists are available;
the running demo/provider path is unchanged. No supervisor or automatic sequencing
is implemented.

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

## Advisory output and future promotion

`DiagnosticAssessment`, `EngineeringAssessment`, `OperationsAssessment`,
`CriticAssessment`, and `MaintenancePlanAssessment` are bounded Pydantic reports.
They reference durable incident/evidence/artifact IDs; diagnostic hypothesis keys
are explicitly local labels. They do not inherit domain `Artifact` and are not
registered with the repository. Planner risk flags and critic recommendations are
advice, never executable parameters or policy decisions.

```text
Strands DiagnosticAssessment
    -> application schema, incident, and supplied/collected citation checks
    -> future independently reviewed Hypothesis / Diagnosis promotion
```

The current application validator only checks structure and reference scope. It
does not establish causal truth, evidence sufficiency, freshness, or approval.
Promotion is deliberately deferred. The specialist cannot write Diagnosis,
ValidationVerdict, Intervention, ApprovalRequirement, or Outcome; it cannot change
phase, reserve parts, book labor, commit a schedule, dispatch notifications, or
invoke the governed executor. Requesting evidence may append only the existing
evidence/request records and corresponding incident revisions/events.

Each specialist has a narrow prompt, an explicit capability allowlist,
and application validation around its advisory contract. A later supervisor can
wrap these entry points as native Strands agents-as-tools. Add independent review,
revision/freshness checks, cancellation handling, and promotion in application code
before integrating them into lifecycle or governance. Do not pass repositories or
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
Evidence IDs. Durable resource-evidence collection remains a later application task.

## Bounded inputs and reference validation

`prepare_specialist_context` builds `SpecialistContext`, extending the compatible
`DiagnosticContext` with lifecycle state, up to 10 selected durable domain artifacts,
and up to five supplied `AdvisoryInput` reports. The whole packet, including its
maximum 20 evidence records, remains capped at 64,000 bytes. Artifact snapshots
retain their durable IDs and status; no new persistence model is introduced.

An `AdvisoryInput.key` is an application-assigned local packet label, never a
durable assessment ID. This supports review before authoritative promotion exists:

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

The future Reliability Supervisor can call these same functions through native
agents-as-tools wrappers. Application code must still choose trusted scope,
validate freshness, handle late/cancelled results, independently review advice,
promote artifacts, and apply governance. This stage adds none of those orchestration
or promotion behaviors.

## Scope and verification

No material architecture deviations. The package lives at `core/agents/` as allowed
by Step 12A, rather than the architecture sketch's `core/reliability/agents/`.
Assessment names distinguish advice from the authoritative artifacts in the sketch.
The legacy deterministic fallback remains available; no second agent framework or
new deterministic diagnostic workflow is introduced.

Supervisor orchestration, the full diagnostic workflow,
promotion, live fallback integration, AgentCore, RAG, procurement, outcome
verification, provider migration, and frontend work remain deferred.

Run `uv run pytest tests/test_strands_agents.py tests/test_specialists.py` for native SDK construction,
scripted model/tool/structured-output cycles, import checks, budget/error behavior,
and authoritative-state invariants. The existing test network guard blocks outbound
connections and DNS; the import smoke test installs its guard before Operon imports.
Then run the full suite and evidence/investigation/execution suites.

Known limitations: no OEM specifications/manual retrieval; no real production
calendar, qualification-expiry records, or dated booking overlap checks; local
resource observations may include seeded demo data. Prompts and scripted native
model tests verify integration contracts and state boundaries, not live-model
reasoning quality or factual truth of narrative claims. Real Bedrock access and
live specialist-quality evaluation have not been run. No semantic validator can
infer missing engineering facts from a valid citation alone.

API references: [1.54.0 release](https://pypi.org/project/strands-agents/1.54.0/),
[structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/),
[tagged Agent source](https://raw.githubusercontent.com/strands-agents/harness-sdk/python/v1.54.0/strands-py/src/strands/agent/agent.py).
