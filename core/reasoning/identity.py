"""Code identity shared by the application and any reasoning runtime. Pure hashing.

``PromotionService.start_run`` freezes ``code_identity()`` into every snapshot; a
runtime computes the same function over the code it ships and the application
refuses advice whose identity drifted (prompts, contract schemas, SDK, policy).
"""
from __future__ import annotations

from importlib.metadata import version

from core.agents import critic, diagnostic, engineering, invocation, operations, planner, supervisor
from core.agents.contracts import SpecialistContext, SupervisorResult
from core.reliability.promotion import POLICY_VERSION
from core.reliability.repository import content_hash
from .protocol import RuntimeIdentity


def prompt_identity() -> dict[str, str]:
    return {"supervisor": supervisor.SUPERVISOR_PROMPT, "diagnostic": diagnostic.DIAGNOSTIC_PROMPT,
            "engineering": engineering.ENGINEERING_PROMPT, "operations": operations.OPERATIONS_PROMPT,
            "critic": critic.CRITIC_PROMPT, "planner": planner.PLANNER_PROMPT,
            "grounding": invocation.GROUNDING_PROMPT}


def code_identity() -> dict[str, str]:
    """Exactly the ``version_identity`` frozen in ``SupervisorRunSnapshot``."""
    return {"policy": POLICY_VERSION, "strands": version("strands-agents"),
            "prompts": content_hash(prompt_identity()),
            "schema": content_hash(SupervisorResult.model_json_schema()),
            "context_schema": content_hash(SpecialistContext.model_json_schema())}


def runtime_identity(*, supervisor_model_id: str, specialist_model_id: str, region: str,
                     build_id: str | None = None) -> RuntimeIdentity:
    code = code_identity()
    return RuntimeIdentity(
        policy=code["policy"], strands_version=code["strands"], prompts=code["prompts"],
        result_schema=code["schema"], context_schema=code["context_schema"],
        supervisor_model_id=supervisor_model_id, specialist_model_id=specialist_model_id,
        region=region, build_id=build_id)
