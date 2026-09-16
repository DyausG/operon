"""Native Strands agents-as-tools; authoritative state remains in the application.

Strands selects each delegation. Typed tools call existing specialist entry points
through disposable application guards; no Python pipeline drives specialist order.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from strands import Agent, ToolContext, tool
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent

from core.reliability.assessments import validate_specialist_context
from core.reliability.evidence import EvidenceService
from core.reliability.orchestration import SupervisorRun, validate_supervisor_decision
from .contracts import (
    DelegationQuery, EvidenceFollowup, SpecialistContext, SupervisorBounds,
    SupervisorDecision, SupervisorResult,
)
from core.providers.errors import normalize_exception
from .invocation import GROUNDING_PROMPT, trace_attributes
from .rendering import model_message
from .runtime import StrandsRuntime

logger = logging.getLogger(__name__)

SUPERVISOR_TOOL_NAMES = frozenset({
    "delegate_diagnostic", "delegate_engineering", "delegate_operations",
    "delegate_critic", "delegate_planner", "acquire_requested_evidence",
})

SUPERVISOR_PROMPT = """You are Operon's Reliability Supervisor, an advisory reasoning orchestrator.
Honor context.run_purpose: DIAGNOSIS requires diagnostic and explicit critic review.
INTERVENTION_REVIEW requires engineering, operations and critic review of the exact
supplied DRAFT Intervention. All three must return reviewed_intervention_id and its
exact artifact hash (provided in the application question). Do not change the draft.
Engineering must reference the current durable diagnosis. Operations and Critic must
reference the supplied draft; Critic must explicitly cover current engineering and
operations input_assessment_keys. No new diagnostic or planner report is required
for this stage. Unknown constraints and dated availability remain blocking.
Choose specialist tools according to the incident's evidence and unanswered questions.
A useful workflow is Diagnostic -> Critic -> justified evidence -> Diagnostic refinement
when needed -> Engineering -> Operations -> Critic -> Maintenance Planner. Adapt it:
do not repeat successful calls without changed evidence or inputs, and stop when blocked.
Use returned application-assigned assessment keys in delegation queries and final output.
Select at most five input reports; their complete dependency closure must also fit five.
New diagnosis can be grounded directly in newly acquired evidence; retain prior report
references whenever relying on prior advice. Do not discard objections to manufacture agreement.
Engineering needs diagnostic input. Critic reviews explicit supplied subjects and inputs.
Planner combines the current technical inputs and their critic reviews. Neither critic
ACCEPT nor your conclusion is a ValidationVerdict, approval, or permission to execute.
Only Diagnostic/Critic evidence needs can justify acquire_requested_evidence: pass the
source assessment key, zero-based need_index and capability parameters. Unsupported
inspection/OEM retrieval stays missing. Collection does not prove the question answered.
Limits in the application run envelope apply across nested agents. Do not retry failures
or rephrase duplicate queries; report unresolved/needs evidence/blocked/escalated instead.
ADVISORY_CONCLUSION requires supported current diagnosis, engineering and operations,
critic review of those inputs, and a grounded proposal with known risk metadata. Otherwise
preserve blockers, unknown constraints, missing evidence and the need for human review.
Return SupervisorDecision; never fabricate delegations, evidence IDs or durable artifacts.
"""


def model_failure_text(exc: BaseException, provider: str) -> str:
    """Normalized, secret-free description of a model/provider failure for the run audit.

    Vendor exceptions map onto ``ProviderError`` codes; anything else is named by
    type only. The text is application-authored and never resembles advisory content.
    """
    error = normalize_exception(exc, provider=provider)
    if error is not None:
        return f"Model invocation failed [{error.provider}:{error.code}]: {error}"[:2000]
    return f"Model invocation failed [{provider}:{type(exc).__name__}]: {str(exc)[:300]}".strip()


def create_supervisor_agent(run: SupervisorRun) -> Agent:
    """These are real SDK tools executed inside the supervisor event loop."""
    @tool(context=True)
    async def delegate_diagnostic(query: DelegationQuery, tool_context: ToolContext) -> dict:
        """Delegate competing causal hypotheses and missing evidence to the Diagnostic Agent."""
        return await run.delegate("diagnostic", query, tool_context)

    @tool(context=True)
    async def delegate_engineering(query: DelegationQuery, tool_context: ToolContext) -> dict:
        """Delegate feasibility, unknown constraints and safety to the Engineering Agent."""
        return await run.delegate("engineering", query, tool_context)

    @tool(context=True)
    async def delegate_operations(query: DelegationQuery, tool_context: ToolContext) -> dict:
        """Delegate read-only inventory, workforce and schedule feasibility to the Operations Agent."""
        return await run.delegate("operations", query, tool_context)

    @tool(context=True)
    async def delegate_critic(query: DelegationQuery, tool_context: ToolContext) -> dict:
        """Delegate adversarial technical review to the Critic Agent; it has no governance authority."""
        return await run.delegate("critic", query, tool_context)

    @tool(context=True)
    async def delegate_planner(query: DelegationQuery, tool_context: ToolContext) -> dict:
        """Delegate an advisory maintenance proposal to the Planner Agent; it cannot approve or execute."""
        return await run.delegate("planner", query, tool_context)

    @tool(context=True)
    async def acquire_requested_evidence(request: EvidenceFollowup, tool_context: ToolContext) -> dict:
        """Acquire a numbered Diagnostic/Critic evidence need through the trusted application service."""
        return await run.acquire(request, tool_context)

    agent = run.runtime.create_agent(
        name="operon_supervisor", system_prompt=SUPERVISOR_PROMPT + "\n" + GROUNDING_PROMPT,
        output_model=SupervisorDecision,
        tools=[delegate_diagnostic, delegate_engineering, delegate_operations,
               delegate_critic, delegate_planner, acquire_requested_evidence],
        trace_attributes=trace_attributes(run.scope, role="supervisor"),
    )
    agent.hooks.add_callback(BeforeToolCallEvent, run.before_tool)
    agent.hooks.add_callback(AfterToolCallEvent, run.after_tool)
    return agent


async def supervise_reliability(runtime: StrandsRuntime, service: EvidenceService,
                                context: SpecialistContext, *, bounds: SupervisorBounds | None = None,
                                specialist_runtime: StrandsRuntime | None = None,
                                cancellation_result_handler: Callable[[SupervisorResult], None] | None = None) -> SupervisorResult:
    """Application entry point. Context/configuration errors fail before model access.

    Model/tool failures return bounded advisory escalation. Caller cancellation is
    propagated; an already-running evidence thread can finish its evidence-only write.
    """
    if not service.same_store():
        raise ValueError("evidence capabilities and repository must use the same application store")
    if not isinstance(context, SpecialistContext):
        raise TypeError("supervisor requires an application-assembled SpecialistContext")
    scope = validate_specialist_context(service.repository, context)
    bounds = SupervisorBounds.model_validate(bounds or SupervisorBounds())
    run = SupervisorRun(runtime, specialist_runtime or runtime, service, scope, bounds)
    agent = create_supervisor_agent(run)
    decision, reason = None, "MODEL_COMPLETED"
    # An explicit bound wins; otherwise the provider's run policy (local inference is slow).
    run_timeout = bounds.timeout_seconds if bounds.timeout_seconds is not None else runtime.run_timeout()
    try:
        result = await asyncio.wait_for(
            agent.invoke_async(
                model_message({"context": scope, "bounds": bounds}),
                invocation_state=run.invocation_state(),
                limits=runtime.settings.invocation_limits() | {"turns": bounds.max_iterations},
            ), timeout=run_timeout,
        )
        if result.stop_reason.startswith("limit_"):
            run.exhausted.add(f"supervisor_{result.stop_reason}")
        elif result.stop_reason not in {"end_turn", "tool_use"} or result.structured_output is None:
            reason = "INVALID_OUTPUT" if run.invalid_output else "MODEL_FAILED"
        else:
            decision = validate_supervisor_decision(
                SupervisorDecision.model_validate(result.structured_output), scope, run.advice, set(run.evidence_ids))
    except asyncio.TimeoutError:
        reason = "TIMEOUT"
        run.exhausted.add("run_timeout")
    except ValueError:
        reason = "INVALID_OUTPUT"
    except asyncio.CancelledError:
        agent.cancel()
        run.closed = True
        if cancellation_result_handler is not None:
            cancellation_result_handler(run.finish(None, "CANCELLED"))
        raise
    except Exception as exc:
        logger.exception("supervisor model invocation failed")
        reason = "INVALID_OUTPUT" if run.invalid_output else "MODEL_FAILED"
        run.errors.add(model_failure_text(exc, runtime.settings.provider))
    finally:
        run.closed = True
    return run.finish(decision, reason)
