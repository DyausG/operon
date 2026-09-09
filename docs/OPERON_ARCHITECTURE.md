Operon should retain the existing application infrastructure and replace its proposal-first agent layer with a Strands-led investigation system.

The central architectural change is this: a prediction opens an incident. Specialists investigate it, a critic challenges the conclusions, and an accepted intervention reaches an enforceable approval and execution boundary. The resulting evidence and outcome become reusable operational memory.

Product name: **Operon**  
Tagline: **Autonomous Reliability Operations for Industrial Systems**

This plan follows inspection of the requested source directories, all existing tests, configuration, launchers, and deployment files. I also checked official Strands documentation and the published 1.54.0 release. I did not modify files, install dependencies, run tests that create files, run migrations, or commit anything.

**A. Current architecture**

The current execution path is:

```text
FastAPI startup
  |
  +--> seed/reset SQLite
  +--> load or train AI4I model
  +--> start DemoEngine
          |
          v
    PlantSimulator.tick()
          |
          v
    HealthModel.predict() + predict_mode()
          |
          +--> fleet/history -> WebSocket -> React dashboard
          |
          v
    failure probability >= 0.80 while degrading
          |
          v
    Select predicted failure mode, or class default
          |
          v
    agent.decide()
          |
          +--> Always build deterministic proposal
          |      inventory -> technician -> schedule
          |      -> notification draft -> work-order draft
          |
          +--> Optional Gemini / Bedrock tool-calling enhancement
          |
          +--> Advisory governance review
          |
          v
    PENDING_APPROVAL
          |
          +--> Approve -> commit_actions()
          |                -> SQLite work package
          |                -> simulated recovery
          |                -> immediate "PREVENTED" outcome
          |
          +--> Reject -> simulated deterioration -> failure
```

The actual implementation has several useful foundations:

| Component | Current capability worth preserving |
|---|---|
| AI4I model | Failure classifier, failure-mode distribution, feature attribution, cached training artifact. |
| Simulator | Eight machines, seeded randomness, four degrading assets, overlapping pump scenarios, recovery and rejection branches. |
| Service layer | Seven domains with stable interfaces and selectable local/MCP/A2A/LLM adapters. |
| Local CMMS | Creates work order, maintenance event, reservations, labor booking, notification record, and package header in one SQLite transaction. |
| Governance | Existing policy concepts for labor, parts, exposure, and intervention justification. |
| Monitoring | Existing correlation candidates by equipment class and predicted failure mode. |
| Backend | Small FastAPI application with REST controls and WebSocket snapshots/events. |
| Frontend | Working fleet view, charts, incident-like queue, approval/rejection controls, trace display, business panel. |
| Tests | Service contracts, proposal generation, provider fallback, governance, monitoring, MCP and A2A round trips. |
| Distribution | Existing launchers and committed frontend bundle support a simple demo launch. |

The important limitations are architectural, with a few implementation defects that must be addressed before relying on the new architecture.

1. **Diagnosis is effectively selected before investigation.**  
   `_build_ctx()` selects a failure-mode record from the model or an equipment-class default. `build_proposal()` then follows a fixed tool sequence. There are no competing hypotheses, evidence requests, or diagnosis acceptance criteria. See [engine.py](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/core/engine.py:169) and [agent.py](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/core/agent.py:59).

2. **The LLM supplements an already complete plan.**  
   `decide()` always builds the deterministic proposal first. The optional model replaces narrative and selected tool results; it does not own an investigation lifecycle. The shallow merge also allows nested proposal data to be shared, which is unsuitable for versioned investigation state.

3. **Governance is advisory rather than enforced.**  
   `approve()` checks only that a proposal is pending. It does not enforce a governance veto, outstanding conditions, or manager co-sign. The MCP server also exposes `create_work_package(proposal)` without independent approval verification. See [approval handler](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/core/engine.py:252) and [MCP commit tool](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/mcp_app/server.py:127).

4. **Incident state is transient.**  
   Proposals, investigation-like traces, approval status, and outcomes live in `DemoEngine.alerts`. There is no durable incident identity or recovery mechanism. Startup seeds with reset enabled, and the launcher deletes the default database. See [server startup](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/server/main.py:22) and [run.py](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/run.py:26).

5. **Telemetry persistence contains a concrete identifier mismatch.**  
   The engine generates IDs such as `AC-COMP-01-AIR_TEMP`, while seed data creates `AC-COMP-01-AIRTEMP`. With foreign keys enabled, the insert fails; `_persist()` swallows the exception, also preventing the subsequent health-score inserts in that transaction. This is a source-level finding, not a runtime test result. See [telemetry persistence](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/core/engine.py:123) and [sensor seed records](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/core/seed_data.py:105).

6. **Concurrent degradation does not mean concurrent investigation.**  
   `_advance()` awaits each `_fire_agent()`, which awaits `agent.decide()`. While model execution runs in a thread, the simulation tick still waits for the whole investigation. Triage ranks displayed pending alerts rather than controlling admission before investigation.

7. **Resource checks are insufficient for concurrent execution.**  
   Reservations do not reduce calculated availability; bookings have no overlap enforcement. Workforce scoring can select an uncertified person merely because their shift matches—an existing test explicitly documents this. The schedule is a generated “two hours from now” window, not a checked production calendar. See [local adapters](/home/dyausg/Desktop/Hackathons/agentic-maintenance-hackathon/core/services/adapters/local.py:54).

8. **Execution and outcome are conflated.**  
   Approval immediately counts an event as prevented and recognizes recovered value. A work-package creation is not proof of physical repair. Local notifications record `SENT` in SQLite; they do not actually send SMS.

9. **The predictive output is overstated in the UI.**  
   The model is a classifier over AI4I feature rows. Its implementation does not establish a calibrated 24-hour forecast or remaining useful life. Preserve it, but present the output as a model risk signal and candidate failure mode.

10. **Existing tests do not cover the full engine lifecycle.**  
    There are no dedicated engine, telemetry-persistence, restart, duplicate-approval, transactional-failure, or frontend-event tests. Provider fallback tests cover enhancer failure, not failure of the deterministic planner’s service calls.

These findings support incremental renovation. They do not justify replacing FastAPI, SQLite, React, the simulator, or the working adapters.

**B. Target Operon architecture**

Use one application deployment, one SQLite database, and six Strands agent roles. Agents run in-process initially.

```text
                 OPERON
  Autonomous Reliability Operations for Industrial Systems

  Industrial telemetry / existing eight-machine simulator
                           |
                           v
               Existing AI4I signaling layer
            risk score + mode candidates + attribution
                           |
                           v
                 Signal / incident admission
             deduplication, persistence, triage
                           |
                           v
  +----------------------------------------------------------+
  |             STRANDS RELIABILITY SUPERVISOR                |
  |                                                          |
  |  Select specialists -> request evidence -> assess progress |
  |          ^                                |              |
  |          |         typed results          v              |
  |    +------------+ +-------------+ +------------+          |
  |    | Diagnostic | | Engineering | | Operations |          |
  |    +------------+ +-------------+ +------------+          |
  |          \               |              /                |
  |           +------ Candidate diagnosis --+                |
  |                           |                              |
  |                           v                              |
  |                  +------------------+                    |
  |                  | Critic/Validator |                    |
  |                  | Falsify / reject |                    |
  |                  +------------------+                    |
  |                     |            |                       |
  |           more evidence         accepted                 |
  |                     |            v                       |
  |                     |   +---------------------+          |
  |                     +---| Maintenance Planner |          |
  |                         +---------------------+          |
  |                                  |                       |
  |                     Engineering + Critic review          |
  +----------------------------------|-----------------------+
                                     v
                        Versioned intervention
                                     |
                                     v
                  Deterministic policy / approval gate
                      |                         |
                 permitted                  approval needed
                      |                         |
                      |                React approve/reject
                      +------------+------------+
                                   v
                         Governed execution service
                  recheck facts + deduplicate + commit
                                   |
                                   v
               Existing inventory/workforce/scheduling/
                     CMMS/notification capabilities
                                   |
                                   v
                 Execution receipt -> outcome monitoring
                                   |
                                   v
                     Persistent operational memory

  +----------------------------------------------------------+
  | SQLite: incidents, evidence, decisions, approvals, actions |
  | Existing asset, telemetry, maintenance and CMMS tables     |
  +----------------------------------------------------------+
            ^                       |
            |                       v
       All state changes      FastAPI + WebSocket -> React

  MCP: capability transport behind existing service interfaces
  A2A: optional remote peer boundary
  Bedrock: primary model provider for all six Strands roles
  AgentCore: future runtime / memory / observability adapters
```

The division of control matters:

- **Strands owns reasoning and specialist orchestration:** which investigation to run, which evidence to request, whether hypotheses need revision, and which intervention to propose.
- **Application code owns invariants:** allowed state transitions, evidence provenance, resource availability, approval authority, execution identity, and durable commits.
- **Existing services own capabilities:** querying inventory, proposing windows, drafting work, and committing authorized packages.

The application state machine constrains permissible actions. It does not prescribe every specialist call or decide the diagnosis.

An incident should normally follow:

```text
OPEN -> INVESTIGATING <-> AWAITING_EVIDENCE
                 |
                 v
       DIAGNOSIS_VALIDATED
                 |
                 v
             PLANNING
                 |
                 v
       INTERVENTION_VALIDATED
                 |
                 +--> AWAITING_APPROVAL
                 |             |
                 +-------------+
                               v
                            READY
                               |
                               v
                          EXECUTING
                               |
                               v
                           OBSERVING
                               |
                               v
                            CLOSED
```

Additional branches are `ESCALATED`, `EXECUTION_FAILED`, and `CANCELLED`. Rejection records a decision against an intervention version; it can return the incident to investigation or escalation. The existing run-to-failure behavior remains a clearly identified demo scenario.

Future capabilities fit these boundaries:

| Capability | Extension |
|---|---|
| Maintenance history and incident memory | Retrieve existing maintenance records plus previous validated incidents and observed outcomes. |
| OEM/manual retrieval | Evidence service returns versioned excerpts with source, section/page, applicability, and content hash. |
| Systemic investigation | Link incidents and compare related assets using BOM relationships, telemetry windows, and later installation/batch records. |
| Procurement | Add one specialist when a parts shortage requires sourcing judgment; engineering validates alternatives. |
| Quality/CAPA | Supervisor creates a governed escalation proposal referencing affected assets, batches, evidence, and containment needs. |
| Risk-based autonomy | Policy computes approval requirements for each action type and impact level. |
| AgentCore | Add an alternative investigation runtime and optional memory/trace integration without changing incident contracts. |

**C. Agent specifications**

All agent outputs are typed reports or proposed commands. None receives unrestricted SQL, shell access, or direct mutation tools.

“Write” below means submitting a permitted result through the incident coordinator. The coordinator is the only writer of authoritative incident state.

| Agent | Responsibility and invocation |
|---|---|
| Reliability Supervisor | Opens and directs investigations, chooses specialists, resolves evidence requests, assesses sufficiency, coordinates planning and intervention submission. Invoked for new incidents, meaningful new evidence, specialist completion, validation rejection, approval decisions, and outcome changes. |
| Diagnostic Agent | Investigates telemetry and history, develops competing root causes, assesses confidence, and identifies discriminating evidence. Invoked initially and whenever new evidence could change the diagnosis. |
| Engineering Agent | Checks technical applicability, component constraints, operating envelopes, and intervention compatibility. Invoked when diagnosis depends on engineering constraints and for every technical intervention before execution. |
| Operations Agent | Assesses criticality, production consequences, feasible timing, resource contention, and business impact. Invoked when prioritization, timing, downtime, or affected production matters. |
| Critic / Validator | Independently challenges diagnosis and intervention support, searches for contradictions, attempts falsification, and issues an enforceable verdict. Mandatory before diagnosis acceptance and before intervention release. |
| Maintenance Planner | Converts an accepted diagnosis into a feasible, executable maintenance proposal using current service capabilities. Invoked after diagnosis validation and when a plan needs revision. |

Detailed contracts:

1. **Reliability Supervisor**

   - **Inputs:** Incident snapshot, signal provenance, specialist reports, unresolved requests, related incidents, budget, policy status.
   - **Outputs:** `SupervisorDecision`: specialist assignments, scoped questions, evidence requests, proposed diagnosis acceptance, planning request, intervention submission, or escalation.
   - **Tools:** `investigate_diagnosis`, `assess_engineering`, `assess_operations`, `validate_candidate`, `plan_maintenance`, `read_incident`, `request_evidence`, `find_related_incidents`, `submit_intervention`.
   - **State:** Reads the whole incident; proposes phase changes, links, task assignments, and accepted artifact references. Cannot edit specialist findings, verdicts, approval records, or execution receipts.
   - **Separate-agent justification:** It must make adaptive coordination decisions across domains and manage unresolved disagreement.

2. **Diagnostic Agent**

   - **Inputs:** Signal, timestamped telemetry, data quality, failure-mode distribution, asset metadata, maintenance history, prior incidents, critic questions.
   - **Outputs:** `DiagnosticReport`: ranked hypotheses, supporting and contradicting evidence IDs, confidence assessments, suspected mechanism, requested evidence, candidate diagnosis.
   - **Tools:** Telemetry-window retrieval, trend/feature calculations, model attribution, failure-mode lookup, maintenance-history retrieval, related-asset comparison.
   - **State:** Reads relevant evidence/history; submits new hypotheses, diagnosis candidates, and evidence requests. Cannot accept its own diagnosis.
   - **Separate-agent justification:** It performs causal investigation; predictive classification is only one input to that work.

3. **Engineering Agent**

   - **Inputs:** Candidate mechanism or intervention, exact asset/component identity, manual excerpts, specifications, operating measurements.
   - **Outputs:** `EngineeringAssessment`: applicable constraints, compatible/incompatible/unknown findings, required precautions, unresolved technical questions, evidence citations.
   - **Tools:** Document search and excerpt retrieval, equipment/BOM lookup, specification lookup, unit-aware constraint checks.
   - **State:** Reads technical evidence and candidate artifacts; submits assessments and constraints. Cannot alter inventory, approve spending, or bypass missing applicability evidence.
   - **Separate-agent justification:** Technical compatibility requires a different evidence base and acceptance standard from fault diagnosis or production scheduling.

4. **Operations Agent**

   - **Inputs:** Asset/line context, criticality, active incidents, production calendar, proposed duration, available labor/windows, business assumptions.
   - **Outputs:** `OperationsAssessment`: feasible windows, operational conflicts, downtime consequences, priority recommendation, impact calculation references.
   - **Tools:** Existing scheduling/workforce queries, production-context lookup, booking-conflict lookup, monitoring assessment, deterministic business-impact calculator.
   - **State:** Reads fleet and operational context; submits constraints and impact assessments. Does not reserve resources.
   - **Separate-agent justification:** A technically valid repair can still be operationally unacceptable or poorly timed.

5. **Critic / Validator**

   - **Inputs:** Candidate diagnosis or intervention, evidence references, competing hypotheses, engineering findings, unresolved requests.
   - **Outputs:** `ValidationVerdict`: `ACCEPT`, `REJECT`, or `NEEDS_EVIDENCE`; challenges, falsification attempts, blocking issues, and explicit evidence requests.
   - **Tools:** Independent retrieval of telemetry, history, document excerpts, related-asset evidence, and deterministic constraint checks.
   - **State:** Reads underlying evidence independently; submits immutable verdicts and challenges. Cannot silently rewrite the proposal.
   - **Separate-agent justification:** It has a different objective: actively find why the proposed conclusion or intervention might be wrong.

   Adversarial behavior must be testable. For example:

   - Challenge whether two pump alerts establish a shared cause.
   - Test whether apparent wear is compatible with a recent replacement record.
   - Reject a manual citation applying to a different component revision.
   - Reject a replacement plan when evidence supports inspection but not replacement.
   - Require evidence that distinguishes cooling restriction from measurement error.

   The supervisor cannot override `REJECT` by asking another agent to agree. A revised artifact must address the recorded objections and receive a new verdict.

6. **Maintenance Planner**

   - **Inputs:** Accepted diagnosis, engineering constraints, operational constraints, current parts/labor/window evidence.
   - **Outputs:** `Intervention`: ordered steps, required parts and quantities, technician requirements, proposed booking, work-order draft, notification draft, verification criteria, estimated impact.
   - **Tools:** Existing inventory, workforce, scheduling, CMMS drafting, notification drafting, and impact calculation.
   - **State:** Reads accepted findings and current resources; submits intervention versions. Cannot reserve, dispatch, approve, or mark work complete.
   - **Separate-agent justification:** It solves execution feasibility after investigative uncertainty has been addressed.

The existing governance and monitoring capabilities remain services. They do not need two additional mandatory LLM agents.

A future **Procurement Agent** would receive a shortage and validated requirements; return ranked alternatives and a procurement proposal; use supplier/catalog/availability tools; and write proposal artifacts only. Invoke it only when sourcing choices exist. Engineering compatibility and purchase approval remain separate gates.

**D. Strands design**

Use the Python **agents-as-tools supervisor pattern**.

Implementation checkpoint (Step 12C): `core/agents/supervisor.py` now provides a
native Strands 1.54.0 Supervisor using async `@tool(context=True)` wrappers around
all five specialist entry points. Strands selects delegation; application-owned
guards in `core/reliability/orchestration.py` bound calls/evidence and assemble an
advisory `SupervisorResult`. There is no authoritative promotion, lifecycle wiring,
or run persistence. The historical design sketch below remains a target; see
[STRANDS_FOUNDATION.md](STRANDS_FOUNDATION.md) for implemented APIs, limits, and
offline validation. Live Bedrock and AgentCore remain unvalidated.

The official Strands documentation supports specialist agents wrapped in custom `@tool` functions, allowing controlled inputs, error handling, and result processing. That fits Operon’s typed boundaries better than passing unconstrained specialist prose directly between agents. [Strands agents-as-tools documentation](https://strandsagents.com/docs/user-guide/concepts/multi-agent/agents-as-tools/)

Version baseline:

- Proposed dependency: `strands-agents==1.54.0`.
- Published release verified: August 27, 2026.
- Published Python requirement: Python 3.10 or newer; the repository targets Python 3.12.
- Strands is not installed in the current environment.
- Keep the existing A2A integration initially; do not add Strands’ optional A2A extras without checking compatibility with the repository’s `a2a-sdk<0.3` constraint.
- No `strands-agents-tools` dependency is needed for our own decorated service wrappers.

The release is published on [PyPI](https://pypi.org/project/strands-agents/1.54.0/), and the [tagged 1.54.0 Agent source](https://raw.githubusercontent.com/strands-agents/harness-sdk/python/v1.54.0/strands-py/src/strands/agent/agent.py) confirms the relevant constructor and invocation parameters. Dependency resolution and executable compatibility verification belong to the first approved integration stage.

The intended construction uses real SDK APIs:

```python
# Architecture sketch only; not added to the repository.
from strands import Agent, tool, ToolContext
from strands.models import BedrockModel

diagnostic = Agent(
    name="operon_diagnostic",
    model=BedrockModel(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        temperature=0.1,
        max_tokens=2500,
    ),
    system_prompt=DIAGNOSTIC_PROMPT,
    tools=diagnostic_read_tools,
    structured_output_model=DiagnosticReport,
    callback_handler=None,
)

result = await diagnostic.invoke_async(
    diagnostic_request.model_dump_json(),
    invocation_state={
        "incident_id": incident_id,
        "run_id": run_id,
        "input_revision": revision,
    },
)

report = result.structured_output
```

`DiagnosticReport`, settings, and tool collections are proposed application objects. `Agent`, `BedrockModel`, `invoke_async`, `invocation_state`, and `structured_output_model` are SDK APIs.

Model configuration follows the documented Bedrock provider interface. Specify region and model explicitly rather than depending on SDK defaults. Use one account-enabled Claude Sonnet model across the six roles initially, with optional per-role overrides later. The current repository model ID must be checked for account/region availability during implementation. [Strands Bedrock provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/)

The integration details are:

| Concern | Proposed design |
|---|---|
| Construction | Create agents through one factory. Give each role a distinct prompt, output schema, and explicit tool allowlist. |
| Instance ownership | Separate instances per incident/run. Never share one mutable specialist instance across concurrent incidents. |
| Specialist handoff | Supervisor calls typed `@tool` wrappers with scoped questions and artifact IDs. Wrappers invoke specialists and return validated JSON plus artifact references. |
| Structured output | Use `structured_output_model` and `result.structured_output`; avoid deprecated `Agent.structured_output()` methods. |
| Tool context | Use `@tool(context=True)` and `ToolContext.invocation_state` for trusted incident/run context. Never let model-supplied arguments choose approval authority. |
| State | SQLite is authoritative. Strands conversation state is temporary reasoning context; explicitly include the relevant incident snapshot in model input. |
| Execution | FastAPI-managed background tasks invoke the supervisor asynchronously. The telemetry loop persists/adopts signals without awaiting complete investigations. |
| Progress | Emit structured task, evidence, verdict, and phase events as work completes. Stream through the existing WebSocket. |
| Observability | Correlate agent/tool activity with incident ID, run ID, role, model, prompt version, latency, token usage, and fallback status. |

Structured-output validation and the newer invocation syntax are documented in [Strands structured outputs](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/). Trusted invocation context is documented in [custom tools](https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/). Strands distinguishes conversation history, agent state, and invocation state; none replaces Operon’s durable business records. [Strands state management](https://strandsagents.com/docs/user-guide/concepts/agents/state/)

Workflow control:

1. The supervisor receives an incident snapshot.
2. It chooses a specialist and a specific question.
3. The specialist can make multiple evidence tool calls before producing its report.
4. The coordinator validates and persists the report.
5. The supervisor uses the returned findings to choose the next action.
6. The critic may send the investigation back for evidence.
7. After diagnosis acceptance, the planner constructs an intervention.
8. Engineering and critic review the actual intervention version.
9. `submit_intervention` checks all required artifacts before creating an approval requirement.

Start with one specialist assignment at a time within an incident and up to two active investigations across incidents. This gives meaningful adaptive orchestration without introducing difficult parallel merges immediately. All wrappers still enforce concurrency and revision checks because models may request multiple tools in one response.

Do not introduce Swarm, Graph, Workflow, LangGraph, or a separate orchestration framework in this phase. The Strands supervisor already supplies the required orchestration pattern.

Error handling and budgets:

- Explicit per-invocation turn/token limits and an application-level incident deadline.
- Bound total specialist calls and allow at most two evidence-driven revision rounds initially.
- Treat invalid structured output, truncated output, missing evidence IDs, and forbidden transitions as failed results.
- Retry transient read/model failures within a bounded budget.
- Never retry a possibly committed write without checking its execution receipt.
- Reconstruct agents from durable state after interruption; do not depend on serializing a suspended Python call stack.
- Quarantine late results from cancelled or superseded runs.
- Keep synchronous service adapters off the FastAPI event loop.

Strands 1.54.0 exposes invocation limits and cancellation parameters. These are useful execution controls, but their in-memory invocation deduplication does not provide durable business-action idempotency. [Agent invocation API](https://strandsagents.com/docs/api/python/strands.agent.agent/)

Deterministic fallback:

- The live path runs Strands directly. It does not first produce the old deterministic plan.
- Explicit offline mode uses a deterministic investigation runner implementing the same typed contracts.
- That runner uses actual fixture evidence, deterministic hypothesis checks, independent validation rules, and existing planning/service functions.
- Reuse the current planner’s resource/draft assembly after a diagnosis is accepted.
- If a model fails mid-investigation, resume from the last validated checkpoint and label subsequent work as fallback.
- A fallback cannot erase a critic rejection or waive a technical/approval requirement.
- Supported demo scenarios must complete without any model API.
- Missing critical evidence or a failed operational service produces a visible hold/escalation, not fabricated success.

**E. Shared state model**

Use Pydantic models for application contracts. Keep nine core concepts distinct:

- Incident: the lifecycle and references.
- Evidence: sourced observations.
- Hypothesis: a falsifiable explanation.
- Diagnosis: a proposed or accepted causal conclusion.
- Validation verdict: an independent decision about a specific artifact.
- Intervention: proposed executable work.
- Agent action: recorded activity and provenance.
- Approval requirement: policy-derived authority needed for a specific plan.
- Outcome: what was actually observed, or explicitly simulated.

Proposed type sketches:

```python
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, JsonValue

Score = Annotated[float, Field(ge=0, le=1)]
Role = Literal[
    "supervisor", "diagnostic", "engineering",
    "operations", "critic", "planner", "procurement"
]

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    schema_version: int = 1
    created_at: AwareDatetime

class EvidenceRequest(BaseModel):
    id: str
    requested_by: Role
    equipment_ids: tuple[str, ...]
    question: str
    capability: str                 # validated against available capabilities
    required_for: Literal["diagnosis", "intervention", "outcome"]
    status: Literal["OPEN", "SATISFIED", "UNAVAILABLE"]
    resolved_by_evidence_ids: tuple[str, ...] = ()

class Evidence(Record):
    incident_id: str
    equipment_ids: tuple[str, ...]
    kind: Literal[
        "telemetry", "model_signal", "maintenance_history",
        "document", "asset_relation", "operational_context",
        "resource_availability", "inspection", "outcome"
    ]
    source_uri: str
    source_locator: str             # row IDs, time window, section/page
    source_version: str
    content_hash: str
    observed_at: AwareDatetime
    retrieved_at: AwareDatetime
    quality: Literal["GOOD", "SUSPECT", "MISSING"]
    provenance: Literal["OBSERVED", "SIMULATED", "DERIVED"]
    summary: str
    payload: dict[str, JsonValue]   # additionally validated by evidence kind
    derived_from_ids: tuple[str, ...] = ()
    supersedes_id: str | None = None

class Hypothesis(Record):
    incident_id: str
    equipment_ids: tuple[str, ...]
    mechanism: str
    failure_mode_code: str | None
    status: Literal["OPEN", "SUPPORTED", "REFUTED", "UNRESOLVED"]
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    confidence: Score
    confidence_basis: str
    calibrated: bool = False
    falsification_tests: tuple[str, ...]
    evidence_requests: tuple[EvidenceRequest, ...] = ()

class Diagnosis(Record):
    incident_id: str
    hypothesis_ids: tuple[str, ...]
    equipment_ids: tuple[str, ...]
    conclusion: str
    failure_mode_code: str | None
    evidence_ids: tuple[str, ...]
    alternative_hypothesis_ids: tuple[str, ...]
    unresolved_assumptions: tuple[str, ...]
    confidence: Score
    status: Literal["CANDIDATE", "ACCEPTED", "SUPERSEDED"]
    supersedes_id: str | None = None

class ValidationVerdict(Record):
    incident_id: str
    target_kind: Literal["diagnosis", "intervention"]
    target_id: str
    target_hash: str
    input_revision: int
    decision: Literal["ACCEPT", "REJECT", "NEEDS_EVIDENCE"]
    challenges: tuple[str, ...]
    falsification_attempts: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    blocking_issues: tuple[str, ...]
    evidence_requests: tuple[EvidenceRequest, ...]
    validator_run_id: str

class InterventionStep(BaseModel):
    id: str
    capability: Literal[
        "inspect", "create_work_package", "notify",
        "verify_recovery", "propose_procurement", "raise_quality_case"
    ]
    equipment_ids: tuple[str, ...]
    parameters: dict[str, JsonValue]  # checked against capability schema
    depends_on: tuple[str, ...] = ()
    preconditions: tuple[str, ...]
    verification_criteria: tuple[str, ...]

class Intervention(Record):
    incident_id: str
    diagnosis_id: str
    revision: int
    content_hash: str
    steps: tuple[InterventionStep, ...]
    evidence_ids: tuple[str, ...]
    engineering_assessment_id: str
    operations_assessment_id: str | None
    risk: Literal["LOW", "MEDIUM", "HIGH", "PROHIBITED"]
    window_start: AwareDatetime | None
    window_end: AwareDatetime | None
    estimated_cost: float
    estimated_downtime_minutes: int
    estimated_avoided_loss: float
    business_assumption_version: str
    status: Literal[
        "DRAFT", "VALIDATED", "AWAITING_APPROVAL",
        "READY", "EXECUTING", "DISPATCHED", "REJECTED", "SUPERSEDED"
    ]

class AgentAction(Record):
    incident_id: str
    run_id: str
    actor: str                     # agent role, system, or authenticated operator
    kind: Literal[
        "HANDOFF", "TOOL_CALL", "REPORT", "TRANSITION",
        "APPROVAL", "EXECUTION", "FALLBACK", "ERROR"
    ]
    input_revision: int
    input_artifact_ids: tuple[str, ...]
    output_artifact_ids: tuple[str, ...]
    status: Literal["STARTED", "SUCCEEDED", "FAILED", "CANCELLED"]
    mode: Literal["LIVE", "DETERMINISTIC", "SYSTEM"]
    model_id: str | None
    prompt_version: str | None
    tool_name: str | None
    tool_call_id: str | None
    idempotency_key: str | None
    summary: str
    error_code: str | None
    completed_at: AwareDatetime | None

class ApprovalRequirement(Record):
    incident_id: str
    intervention_id: str
    intervention_hash: str
    policy_version: str
    mode: Literal["AUTOMATIC", "HUMAN", "PROHIBITED"]
    required_roles: tuple[str, ...]
    minimum_distinct_approvers: int
    conditions: tuple[str, ...]
    expires_at: AwareDatetime | None
    decision_ids: tuple[str, ...]
    status: Literal[
        "PENDING", "SATISFIED", "REJECTED", "EXPIRED", "INVALIDATED"
    ]

class Outcome(Record):
    incident_id: str
    intervention_id: str | None
    execution_receipt_ids: tuple[str, ...]
    result: Literal[
        "RECOVERED", "NO_IMPROVEMENT", "FAILED",
        "NO_INTERVENTION", "INCONCLUSIVE"
    ]
    basis: Literal["OBSERVED", "SIMULATED"]
    verification_evidence_ids: tuple[str, ...]
    observation_start: AwareDatetime
    observation_end: AwareDatetime
    before_metrics: dict[str, float]
    after_metrics: dict[str, float]
    estimated_avoided_loss: float | None
    measured_cost: float | None
    diagnosis_confirmed: bool | None
    lesson: str
    supersedes_id: str | None = None

class Incident(Record):
    equipment_ids: tuple[str, ...]
    signal_evidence_ids: tuple[str, ...]
    related_incident_ids: tuple[str, ...]
    demo_run_id: str | None
    revision: int
    active_run_id: str | None
    phase: Literal[
        "OPEN", "INVESTIGATING", "AWAITING_EVIDENCE",
        "DIAGNOSIS_VALIDATED", "PLANNING",
        "INTERVENTION_VALIDATED", "AWAITING_APPROVAL",
        "READY", "EXECUTING", "OBSERVING",
        "CLOSED", "ESCALATED", "EXECUTION_FAILED", "CANCELLED"
    ]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    triage_score: float
    evidence_ids: tuple[str, ...]
    hypothesis_ids: tuple[str, ...]
    diagnosis_id: str | None
    validation_ids: tuple[str, ...]
    intervention_ids: tuple[str, ...]
    approval_requirement_ids: tuple[str, ...]
    outcome_ids: tuple[str, ...]
    open_requests: tuple[EvidenceRequest, ...]
    mode: Literal["LIVE", "DETERMINISTIC", "MIXED"]
```

Additional small contracts are needed for specialist reports, approval decisions, and execution receipts. Approval decisions record the authenticated actor, role, decision, rationale, timestamp, and exact intervention hash. Execution receipts record the operation key, adapter, request hash, external/local identifiers, and confirmed/failed/unknown status.

Critical invariants:

- Agent-generated confidence is not treated as calibrated probability.
- IDs, timestamps, hashes, authorship, and policy decisions are assigned or verified by trusted application code.
- References must exist and belong to the permitted incident/equipment scope.
- Evidence and completed reports are immutable; corrections create superseding artifacts.
- Only the coordinator can accept a diagnosis or advance a phase.
- Validation applies to an exact artifact hash.
- Material changes to evidence, steps, parts, timing, or risk invalidate affected approvals.
- “Work dispatched” is separate from “recovery observed.”
- Estimated avoided losses are never recorded as measured financial savings.

SQLite design:

Use the existing database with five additional tables initially:

| Table | Purpose |
|---|---|
| `incident` | Indexed identity, status, revision, active run, equipment scope, and serialized reference state. |
| `incident_artifact` | Immutable evidence, hypotheses, reports, diagnoses, verdicts, interventions, requirements, and outcomes. |
| `incident_event` | Append-only actions and transitions with ordered event IDs. |
| `approval_decision` | Decisions bound to intervention hash and trusted actor identity. |
| `execution_receipt` | Unique operation keys, claims, outcomes, and package identifiers. |

Existing telemetry, asset, maintenance, work-order, reservation, and booking tables remain relational.

Use short transactions and revision-checked updates. Do not hold SQLite transactions open during model calls. In-memory per-incident locks reduce contention; database revision checks remain the correctness mechanism.

**F. Tool map**

| Existing capability | New consumer | Required work |
|---|---|---|
| `HealthModel.predict()` / `predict_mode()` | Signal admission; Diagnostic reads outputs | Preserve implementation; wrap outputs with signal provenance. |
| `HealthModel.attribute()` | Diagnostic | Read tool wrapper; label attribution as model explanation. |
| `tools.get_equipment()` | Diagnostic, Engineering, Operations, Planner | Typed, scoped read wrapper. |
| `get_failure_mode_by_code()` | Diagnostic, Engineering, Planner | Typed lookup wrapper; record is reference knowledge, not accepted diagnosis. |
| `inventory().check_parts()` | Planner; Engineering for BOM | Wrapper; distinguish missing BOM from known availability; account for reservations. |
| `workforce().assign_technician()` | Planner, Operations | Wrapper; require a genuine qualification match and booking feasibility. |
| `scheduling().block_schedule()` | Operations, Planner | Expose as `propose_maintenance_window`; preserve existing method while adding dated windows and conflict checks. |
| `cmms().propose_work_order()` | Planner | Draft-only wrapper. |
| `notifications().notify(send=False)` | Planner | Dedicated `draft_notification` wrapper; no model-controlled `send` flag. |
| `notifications().raise_alert()` | Signal admission; governed escalation | Authorized system operation with deduplication. |
| `governance().review_plan()` | Policy evaluation | Reuse rules; make deterministic rules authoritative and conditions enforceable. |
| `monitoring().assess()` | Supervisor, Operations, Diagnostic | Candidate correlation tool; do not treat matching modes as causal proof. |
| `commit_actions()` / `create_work_package()` | Execution service only | Require persisted execution authorization and idempotency; remove unrestricted agent access. |
| `commit_work_order()` | Compatibility path | Govern through the same execution boundary. |
| Business functions in `config.py` | Operations, Planner, outcome UI | Preserve formulas; accept actual proposed duration and label assumptions. |
| Simulator `set_mode()` / `failed()` | Demo outcome adapter | Preserve; keep out of agent tool lists. |

Genuinely new tools:

| Tool | Why needed |
|---|---|
| `get_telemetry_window` | Investigations need timestamped history and quality, not only the alert snapshot. |
| `get_maintenance_history` | Existing tables exist, but there is no retrieval capability. |
| `find_related_incidents` | Persistent memory retrieval across investigations. |
| `search_documents` / `get_document_excerpt` | Engineering evidence with source applicability and citations. |
| `get_operating_context` | Production calendar, line dependencies, and known operating conditions. |
| `compare_related_assets` | Compare synchronized windows and existing shared-part relationships. |
| `check_engineering_constraints` | Reproducible unit/range/applicability checks. |
| `request_evidence` | Explicitly track unresolved information and resume triggers. |
| `record_outcome_observation` | Close incidents using verification evidence. |

Start document retrieval with a small indexed collection of authored demo excerpts, marked synthetic. Keyword/metadata retrieval is sufficient for the hackathon. A vector database is unnecessary.

Do not pretend the current repository already contains OEM manuals, supplier batches, installation dates, verified repairs, or production calendars. These require curated fixtures or future integrations.

**G. File-by-file migration plan**

Paths below describe proposed future work only.

| Existing file | Disposition and reason |
|---|---|
| `core/model.py` | Remain unchanged initially. Preserve inference, training, and artifact loading. |
| `core/dataset.py` | Remain unchanged. Preserve feature engineering and dataset handling. |
| `core/simulator.py` | Remain unchanged initially. Preserve fleet and degradation behavior; control it through the engine/demo outcome adapter. |
| `data/ai4i2020.csv` | Remain unchanged. |
| `core/agent.py` | Incrementally replace live orchestration with a compatibility facade. Move reusable deterministic planning and triage logic before retiring provider-specific loops. |
| `core/engine.py` | Modify signal admission, task lifecycle, sensor mapping, incident projections, restart behavior, and outcome observation. Preserve simulation/scoring/broadcast responsibilities. |
| `core/tools.py` | Preserve read/draft facade; redirect all mutations through authorized execution. |
| `core/config.py` | Operon branding, Bedrock-first settings, run budgets, fallback mode, autonomy policy, explicit demo mode. Preserve old environment aliases temporarily. |
| `core/db.py` | Add versioned additive schema changes, incident persistence, execution uniqueness, and explicit transactional behavior. |
| `core/seed_data.py` | Make initial seeding non-destructive and repeatable. Preserve fleet/master records; add explicit demo-fixture seeding. |
| `core/gemini.py` | Retain unchanged during migration for legacy compatibility; remove from the active Operon path. |
| `core/__init__.py` | Update product/module description. |
| `core/services/base.py` | Preserve existing interfaces; add evidence-query contracts and execution authorization requirements. |
| `core/services/registry.py` | Preserve registry; add evidence domain, Operon aliases, deterministic governance/monitoring defaults. |
| `core/services/__init__.py` | Export added contracts/accessors. |
| `core/services/adapters/local.py` | Keep implementations; correct qualification, reservation, scheduling, authorization, and outcome assumptions. Preserve atomic package assembly. |
| `core/services/adapters/mcp_adapter.py` | Preserve transport bridge; pass execution identifiers; align notification semantics; improve timeout/cleanup behavior where necessary. |
| `core/services/adapters/a2a_adapter.py` | Preserve initial transport implementation and compatibility. Add typed result validation at the application boundary. |
| `core/services/adapters/gemini_peers.py` | Retain as legacy optional code initially; stop selecting it by default for Operon. |
| `core/services/adapters/__init__.py` | Register new adapters and preserve optional import behavior. |
| `mcp_app/server.py` | Preserve read/draft tools; add evidence tools; govern writes independently; update advertised product name. |
| `mcp_app/__init__.py` | Branding/documentation only. |
| `a2a_app/server.py` | Preserve governance/monitoring endpoints; update branding and validate payloads. No mandatory remote specialist deployment. |
| `a2a_app/__init__.py` | Branding/documentation only. |
| `server/main.py` | Non-destructive startup, managed task shutdown, incident APIs, revision-bound approvals, evidence endpoints, richer snapshots. Preserve existing routes through compatibility projections. |
| `server/__init__.py` | Remain unchanged. |
| `frontend/src/App.jsx` | Preserve fleet/chart/business components; introduce incident investigation and validation views; correct risk/outcome wording. |
| `frontend/src/useEngine.js` | Track incidents by incident ID, event sequence/revision, action errors, pending requests, and effective execution mode. |
| `frontend/src/lib.jsx` | Add lifecycle/agent labels and status formatting; preserve existing formatting and icons. |
| `frontend/src/styles.css` | Extend current visual system for evidence, hypotheses, verdicts, and approvals. |
| `frontend/src/main.jsx` | Remain unchanged. |
| `frontend/index.html` | Operon title, tagline, metadata. |
| `frontend/package.json` | Product metadata and focused frontend test command. Preserve framework dependencies. |
| `frontend/package-lock.json` | Regenerate only alongside approved package metadata/dependency changes. |
| `frontend/vite.config.js` | Remain unchanged unless a test configuration requires adjustment. |
| `frontend/dist/index.html` | Regenerate from source at release stage. |
| Existing hashed files in `frontend/dist/assets/` | Replace only through the frontend build; preserve no-Node launch capability. |
| `tests/conftest.py` | Unique test databases, robust network/provider isolation, isolated artifact/model paths, deterministic clocks. |
| `tests/test_agent.py` | Preserve fallback intent; migrate provider and tool tests to Strands contracts. |
| `tests/test_services.py` | Preserve service tests; intentionally replace the uncertified-shift fallback expectation; add transactional/resource checks. |
| `tests/test_peers.py` | Preserve policy/correlation tests; add enforced-gate expectations. |
| `tests/test_llm_peers.py` | Retain while legacy adapters exist; retire with those adapters, not prematurely. |
| `tests/test_integration_mcp.py` | Preserve read round trips; add authorized/unauthorized write and retry cases. |
| `tests/test_integration_a2a.py` | Preserve existing round trips; add malformed/unavailable peer cases. |
| `pyproject.toml` | Operon metadata; pin Strands; make Pydantic an explicit dependency; preserve existing infrastructure. |
| `uv.lock` | Regenerate after approved dependency integration and verification. |
| `requirements.txt` | Align supported dependency constraints with the project definition. |
| `.env.example` | Document Operon, Bedrock-first configuration, fallback, budgets, autonomy, and legacy aliases. |
| `run.py` | Remove unconditional database deletion; preserve warm-up and launch convenience; add explicit demo reset behavior. |
| `run.bat`, `install.bat` | Branding/instructions only; preserve launcher workflow. |
| `Dockerfile` | Preserve single-container packaging and model warm-up; document durable storage and explicit demo configuration. |
| `render.yaml` | Branding/configuration as needed; explicitly identify ephemeral hosted demo behavior. |
| `README.md`, `docs/EXTENDING.md` | Update architecture, contracts, demo instructions, and capability limits. |
| `docs/banner.svg` | Update existing vector text/branding. |
| `THIRD_PARTY_NOTICES.md` | Preserve; amend only if new bundled assets introduce attribution requirements. |
| `.python-version`, `.gitignore`, `.gitattributes`, `.dockerignore`, `frontend/.gitignore` | Remain unchanged unless a concrete new generated artifact requires a narrow rule. |

Proposed new files:

| New file | Purpose |
|---|---|
| `core/reliability/__init__.py` | Small public entry point. |
| `core/reliability/models.py` | Incident/artifact/report contracts. |
| `core/reliability/repository.py` | SQLite persistence, revision checks, atomic transitions. |
| `core/reliability/coordinator.py` | Incident task lifecycle, state admission, budgets, cancellation, result commits. |
| `core/reliability/signals.py` | Prediction-to-signal conversion and incident deduplication. |
| `core/reliability/triage.py` | Reused triage calculations and pending-work ordering. |
| `core/reliability/policy.py` | Risk classification, validation gates, approval requirements. |
| `core/reliability/execution.py` | Authorized execution, revalidation, receipts, retry reconciliation. |
| `core/reliability/outcomes.py` | Recovery verification and reusable incident lessons. |
| `core/reliability/fallback.py` | Deterministic investigation and planning implementation. |
| `core/reliability/events.py` | Versioned application events and legacy UI projection. |
| `core/reliability/agents/__init__.py` | Agent factory exports. |
| `core/reliability/agents/factory.py` | Model construction, common budgets, role-specific tool allowlists. |
| `core/reliability/agents/supervisor.py` | Supervisor prompt, output contract, delegation tools. |
| `core/reliability/agents/diagnostic.py` | Diagnostic prompt and report contract. |
| `core/reliability/agents/engineering.py` | Engineering prompt and assessment contract. |
| `core/reliability/agents/operations.py` | Operations prompt and assessment contract. |
| `core/reliability/agents/critic.py` | Adversarial prompt and verdict contract. |
| `core/reliability/agents/planner.py` | Planning prompt and intervention contract. |
| `core/reliability/agents/tools.py` | Typed Strands wrappers around services and evidence retrieval. |
| `core/services/adapters/evidence_local.py` | Local telemetry/history/document/context retrieval. |
| `core/migrations/001_operon.sql` | Initial additive persistence changes, applied by a small versioned runner. |
| `data/operon_demo.json` | Clearly synthetic manual excerpts, operational context, historical examples, and scenario evidence. |
| `frontend/src/components/IncidentPanel.jsx` | Investigation lifecycle and specialist activity. |
| `frontend/src/components/EvidencePanel.jsx` | Evidence and source detail. |
| `frontend/src/components/ValidationPanel.jsx` | Hypotheses, objections, verdicts, and unresolved evidence. |
| `frontend/src/components/InterventionPanel.jsx` | Plan, impact, conditions, approval state, execution/outcome distinction. |
| `frontend/src/engineState.js` | Pure event reducer suitable for focused tests. |
| `tests/test_incident_state.py` | Persistence, revisions, recovery, invalid transitions. |
| `tests/test_evidence.py` | Retrieval provenance, applicability, missing/stale evidence. |
| `tests/test_strands_agents.py` | Independent role behavior and tool restrictions. |
| `tests/test_orchestration.py` | Adaptive handoffs and bounded evidence loops. |
| `tests/test_execution.py` | Governance, atomicity, deduplication, contention. |
| `tests/test_fallback.py` | Offline and mid-run fallback behavior. |
| `tests/test_engine.py` | Telemetry persistence, eight-machine lifecycle, pause/reset/recovery. |
| `tests/test_api.py` | Approval/version/identity/error contracts and snapshots. |
| `frontend/src/engineState.test.js` | Event ordering, reconnect snapshots, duplicate events. |
| `docs/OPERON_ARCHITECTURE.md` | Approved architecture and decision rationale. |

These are cohesive modules, not separate services. Procurement, CAPA integrations, and AgentCore files should be created only when their implementation is selected.

**H. Safest migration sequence**

| Stage | Change | Runnable/testable exit condition |
|---|---|---|
| 1. Baseline | Capture existing contracts and add engine characterization tests. | Current application still launches; baseline suite established. |
| 2. Persistence foundations | Fix sensor identifiers/error visibility; introduce non-destructive seed/startup and explicit demo reset. | Telemetry and health rows persist; restart preserves records. |
| 3. Incident contracts | Add models, additive schema, repository, revisions, events, and legacy projections. | Existing UI still works while incidents persist. |
| 4. Governed execution | Add policy enforcement, approval identity/hash binding, receipts, resource rechecks, and MCP write enforcement. | Existing deterministic flow works through the new gate; duplicate approvals cannot duplicate packages. |
| 5. Evidence capabilities | Add telemetry/history/context retrieval and a small synthetic document collection. | Evidence tools work independently without an LLM. |
| 6. Deterministic investigation | Introduce hypotheses, critic checks, intervention validation, and observed demo outcomes. | Complete new lifecycle works offline; old planner assembly is reused. |
| 7. Strands compatibility | Install/pin only after approval; verify tool schemas, async calls, structured outputs, limits, and Bedrock access in an isolated environment. | SDK tests pass without changing the default runnable path. |
| 8. Independent specialists | Implement each role with restricted tools and contract tests. | Each agent can produce valid, grounded reports; critic rejects negative fixtures. |
| 9. Supervisor integration | Add dynamic delegation, evidence loops, task supervision, and checkpoint fallback. | Live Strands owns orchestration; telemetry remains responsive. |
| 10. Frontend transition | Add incident/evidence/validation/intervention views and effective-mode labels. | Approvals, failures, reconnects, and outcome monitoring work end to end. |
| 11. Demo and release | Rebuild committed frontend, update branding/docs, rehearse offline and live scenarios. | One-command launch and five-minute demonstration pass. |
| 12. Optional extensions | Systemic evidence depth, procurement proposal, or AgentCore integration. | Added only after the core acceptance criteria pass. |

Switch defaults only after the new path meets its stage criteria. Keep the legacy route available temporarily behind configuration, using the same governed execution boundary.

**I. Test strategy**

Verification should distinguish deterministic correctness from model quality.

| Area | Verification |
|---|---|
| Existing behavior | Preserve inventory, workforce, drafting, CMMS transaction, monitoring, MCP/A2A contracts and eight-machine scenarios. |
| Telemetry | Assert exact sensor identity mapping, persisted readings/health scores, and surfaced persistence errors. |
| Independent agents | Scripted model responses exercise actual Strands tool calls and structured output; assert role tool allowlists and evidence references. |
| Diagnostic quality | Conflicting evidence, ambiguous mode, recent maintenance, bad sensor quality, and missing history fixtures. |
| Critic behavior | Unsupported diagnosis, wrong manual revision, ignored contradiction, and unjustified replacement must not receive acceptance. |
| Orchestration | Supervisor chooses different specialist sequences for different evidence; critic requests cause another evidence pass; budgets cause escalation. |
| Offline fallback | Run with outbound access disabled. Assert complete supported workflows, actual service reads, validation, approval, package creation, and simulated outcome verification. |
| Mid-run fallback | Inject model failure after evidence collection or a specialist report; preserve accepted artifacts and unresolved objections. |
| State integrity | Invalid schema/reference/revision cannot partially update state; restart reconstructs pending incidents; late cancelled results are rejected. |
| Execution | Double-clicks, concurrent approvals, retries, stale plans, expired approvals, wrong roles, and direct MCP writes cannot bypass governance. |
| Resource contention | Two incidents cannot reserve the same last unit or book the same technician in overlapping windows. |
| Atomicity | Inject failure between local package inserts; assert no partial package and no successful receipt. |
| External uncertainty | Simulate remote success followed by response loss; retain `UNKNOWN` and reconcile before retry. |
| Frontend | Duplicate/out-of-order events, reconnect snapshots, pending buttons, API errors, and approval invalidation. |
| Outcomes | Package dispatch alone does not close an incident or recognize observed recovery. |

Use unique temporary databases and explicitly blocked network/provider access in tests. The current shared temporary DB filename should not survive the migration.

For live evaluation, use a small fixed scenario suite and score:

- Evidence citation validity.
- Appropriate specialist selection.
- Recognition of contradictions.
- Critic rejection of unsupported candidates.
- Intervention feasibility.
- Latency, tokens, fallback rate, and budget adherence.

Do not require identical prose or an identical live tool sequence. Require stable safety and state invariants.

**J. Risks and implementation traps**

| Risk | Mitigation |
|---|---|
| Strands becomes cosmetic | Live mode must let the supervisor and specialists choose tools and evidence paths before any plan exists. |
| Six similar agents | Distinct tool allowlists, report contracts, invocation conditions, and authority boundaries. |
| Critic merely agrees | Independent retrieval, explicit falsification obligations, negative fixtures, and enforced verdicts. |
| Shared mutable state | Immutable artifacts, incident/run identities, short revision-checked commits. |
| Agent concurrency errors | Separate instances; serialize assignments initially; never hold a parent lock while awaiting a child. |
| Nested concurrency deadlocks | Scope model-call limits separately from investigation-task limits; do not hold all model capacity while waiting for specialists. |
| Duplicate execution | Durable operation keys and receipts, checked at service/MCP boundaries. |
| False exactly-once claims | Local writes can be atomic; remote operations need idempotency or reconciliation for unknown outcomes. |
| Approval races | Bind decisions to exact intervention hash, verify authority server-side, recheck before execution. |
| Stale stock or bookings | Check and reserve within the same local transaction; use dated booking intervals. |
| LLM nondeterminism | Bounded loops, structured outputs, semantic validation, deterministic calculations, tested fallback. |
| SDK API drift | Exact dependency pin and smoke tests; avoid experimental features. |
| Hidden Gemini reasoning | Default governance/monitoring to deterministic services; all required live reasoning flows through Strands/Bedrock. |
| MCP/A2A duplication | MCP transports capabilities; A2A transports optional remote peer requests; local agents collaborate through Strands. |
| Reset during active work | Cancel/mark runs, reject late results, scope reset to the selected demo run. |
| Correlation presented as causation | Treat monitoring matches as investigative leads; demand distinguishing evidence. |
| Invented engineering authority | Mark synthetic documents and missing applicability explicitly; unknown compatibility blocks technical release. |
| Inflated business impact | Preserve assumptions, use actual planned duration, avoid double-counting common line downtime, separate estimates from measurements. |
| Demo depends on cloud | Preflight live access; explicit deterministic mode; no network requirement for supported demo completion. |

AgentCore deserves a specific boundary.

A future Runtime deployment should host the investigation worker, while FastAPI retains the authoritative SQLite store and governed service access. The worker receives snapshots and returns typed commands/results over authenticated application boundaries. Do not assume multiple cloud agent sessions can share one local SQLite file.

AgentCore Runtime sessions provide isolated execution environments; default compute-local state is ephemeral, although persistent filesystem options now exist. That is a separate storage/deployment decision. [AgentCore session documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)

AgentCore Memory can later enrich retrieval with cross-session experience. It should not become the approval ledger or execution authority; retain references back to original evidence and incidents. [AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)

**K. Hackathon value**

| Addition | Categories strengthened | Demonstrable value |
|---|---|---|
| Strands supervisor and specialists | Technical Implementation, Design | Adaptive tool use and delegation visible in one incident. |
| Adversarial critic | Technical Implementation, Creativity & Originality | A plausible diagnosis is rejected, investigated further, and corrected. |
| Cited engineering evidence | Design, Potential Impact | Intervention justified against an applicable specification. |
| Persistent incident memory | Technical Implementation, Potential Impact | A later incident retrieves an earlier outcome and avoids repeating an error. |
| Cross-machine investigation | Creativity & Originality, Potential Impact | Two pump alerts prompt a shared-cause investigation. |
| Enforced autonomy policy | Design, Technical Implementation, Potential Impact | Low-risk analysis proceeds; consequential work waits for appropriate authority. |
| Atomic, deduplicated execution | Technical Implementation | Repeated approval produces one work package. |
| Complete offline fallback | Technical Implementation, Presentation | The workflow survives a model outage without hiding the mode change. |
| Investigation-focused frontend | Design, Presentation | Judges can see signal, hypothesis, challenge, evidence, intervention, and outcome. |
| Honest impact accounting | Potential Impact, Presentation | Estimated avoided downtime is understandable and traceable. |
| Optional AgentCore integration | Technical Implementation | Cloud runtime/memory/observability becomes an extension of the same contracts. |

A five-minute demo should follow one understandable story:

1. The existing fleet produces overlapping signals.
2. The supervisor delegates diagnosis and operational assessment.
3. The critic challenges a plausible conclusion.
4. Additional history or manual evidence changes or strengthens the diagnosis.
5. The planner proposes a feasible intervention; policy requires approval.
6. Approval produces one work package.
7. Subsequent simulated telemetry verifies recovery, and the incident becomes retrievable memory.

Show concise findings and evidence references in the timeline, not an unrestricted stream of model reasoning.

**1. MUST BUILD**

- Operon branding and exact tagline.
- Correct telemetry persistence and non-destructive startup.
- Durable incident/artifact/event state with revision checks.
- Six distinct Strands roles, Bedrock as the primary live provider.
- Adaptive supervisor delegation and bounded evidence loops.
- A critic whose rejection actually blocks release.
- Minimal history retrieval and cited synthetic engineering evidence.
- Planning through existing services.
- Enforced approval/execution boundary, including MCP.
- Duplicate-execution protection and resource revalidation.
- Complete offline workflow for supported demo scenarios.
- Outcome observation separated from dispatch.
- Incident, evidence, verdict, approval, and mode visibility in the existing frontend.
- Tests for state integrity, governance, fallback, and the full demo lifecycle.

**2. SHOULD BUILD**

- One substantive cross-machine investigation using the existing pump scenarios.
- Retrieval of a previous incident’s verified or simulated outcome.
- Low-risk automatic evidence collection and explicitly governed action classification.
- Restart recovery and a visible resume path.
- Structured Strands activity metrics and latency/token budgets.
- Real dated scheduling windows and contention handling across simultaneous incidents.

**3. NICE TO HAVE**

- Procurement Agent producing a proposal with engineering-reviewed alternatives.
- Quality/CAPA escalation proposal.
- AgentCore Memory integration.
- AgentCore Runtime deployment of the investigation worker.
- AgentCore/CloudWatch trace presentation.
- Selective parallel specialist investigations after state handling is proven.

**4. DO NOT BUILD FOR THIS HACKATHON**

- Kubernetes, Kafka, Redis, Celery, a new database, or a vector database.
- A custom agent framework or simultaneous orchestration frameworks.
- Separate deployed services for all six agents.
- A procurement marketplace or automatic purchasing.
- Full CMMS/ERP/MES replacement.
- General-purpose PDF ingestion and enterprise document management.
- A fleet digital twin or a new predictive model.
- Autonomous PLC commands or physical machine control.
- Full enterprise identity/approval administration; use a clearly scoped demo identity boundary.
- A cloud migration that makes the demo dependent on cloud availability.
- Another privacy-sanitization pass.

This is the architecture plan only. Implementation remains paused pending your explicit approval.
