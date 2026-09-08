# Strands foundation (Step 12A)

Strands supplies model interaction, tool selection, and Pydantic structured output.
Operon supplies evidence capabilities and owns persistence, lifecycle, validation,
promotion, approval, and execution. One reference Diagnostic Specialist is available;
the running demo/provider path is unchanged.

## SDK and runtime

Both dependency manifests pin **strands-agents==1.54.0**, the approved architecture's
baseline. The installed package was inspected and tested on Python 3.12. Resolution
kept every existing dependency version, adding only Strands and its five missing
transitive dependencies. No AgentCore, extras, or strands-agents-tools are installed.

The factory uses native `Agent`, `BedrockModel`, `SequentialToolExecutor`, and
`@tool(context=True)`. Invocation uses `invoke_async(..., limits=...)`,
`structured_output_model=DiagnosticAssessment`, and `result.structured_output`.
It does not use the deprecated standalone structured-output method or parse model
prose as JSON. Scalar tool constraints are validated by Step 11's capability models;
1.54.0's decorator does not support `Annotated[scalar, Field(...)]`. Nested Pydantic
tool input models are supported and used for evidence requests.

Bedrock is the primary and only configured live runtime in this package. Model ID
and region are required; `live_enabled=False` prevents accidental client creation.
Imports and runtime construction create no model, client, or credential session.
An explicitly enabled agent creation resolves AWS credentials, then constructs the
Bedrock client. Missing credentials/configuration fail clearly. Access errors during
invocation propagate as a diagnostic error with their original cause. There is no
Gemini selection or silent fallback here.

The legacy `core/config.py` model ID and provider auto-selection are not inherited.
Select an account-enabled model/inference profile explicitly. Live account/region
model availability has **not** been verified: this stage makes no cloud calls.

Defaults: 2,500 output tokens per model call, temperature 0.1, 3s connect and 30s
read timeouts, two total Botocore request attempts with standard retry mode, no
additional Strands retries, 90s invocation deadline, six turns, 8,000 cumulative
output tokens, and 32,000 cumulative total tokens. Token caps are native soft caps
checked between turns; one response can overshoot them. The evidence adapter also
allows at most 12 calls per invocation, including multiple calls in a single turn.

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

Future specialists should add one narrow prompt, an explicit capability allowlist,
and application validation around these advisory contracts. A later supervisor can
wrap these entry points as native Strands agents-as-tools. Add independent review,
revision/freshness checks, cancellation handling, and promotion in application code
before integrating them into lifecycle or governance. Do not pass repositories or
consequential service methods as tools.

## Scope and verification

No material architecture deviations. The package lives at `core/agents/` as allowed
by Step 12A, rather than the architecture sketch's `core/reliability/agents/`.
Assessment names distinguish advice from the authoritative artifacts in the sketch.
The legacy deterministic fallback remains available; no second agent framework or
new deterministic diagnostic workflow is introduced.

Supervisor orchestration, the full diagnostic workflow, other specialist agents,
promotion, live fallback integration, AgentCore, RAG, procurement, outcome
verification, provider migration, and frontend work remain deferred.

Run `uv run pytest tests/test_strands_agents.py` for native SDK construction,
scripted model/tool/structured-output cycles, import checks, budget/error behavior,
and authoritative-state invariants. The existing test network guard blocks outbound
connections and DNS; the import smoke test installs its guard before Operon imports.
Then run the full suite and evidence/investigation/execution suites.

API references: [1.54.0 release](https://pypi.org/project/strands-agents/1.54.0/),
[structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/),
[tagged Agent source](https://raw.githubusercontent.com/strands-agents/harness-sdk/python/v1.54.0/strands-py/src/strands/agent/agent.py).
