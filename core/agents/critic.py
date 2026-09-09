"""Independent critic advice through native Strands; no application authority."""
from core.reliability.evidence import EvidenceService
from .contracts import CriticAssessment, SpecialistContext
from .invocation import invoke_specialist
from .runtime import StrandsRuntime
from .tools import EvidenceRequester

CRITIC_PROMPT = """You are Operon's Critic / Validator Specialist. Actively seek reasons the supplied
subject could be wrong. Challenge unsupported claims, contradictions, ignored
counterevidence, overconfidence, invented constraints, and predictive signal
presented as causal diagnosis. Separate measured evidence from inference and
simulation. Request discriminating evidence where justified; use request_evidence
for independent retrieval with durable citations. Return advisory ACCEPT, REJECT,
or NEEDS_EVIDENCE with concrete technical reasons. ACCEPT is never policy approval
or an authoritative ValidationVerdict. For a prior report, use subject_kind=assessment
and its supplied local key as subject_id and an input_assessment_key. Otherwise
reference the exact supplied domain artifact.
"""


async def review_assessment(runtime: StrandsRuntime, service: EvidenceService,
                           context: SpecialistContext, *,
                           evidence_requester: EvidenceRequester | None = None) -> CriticAssessment:
    return await invoke_specialist(runtime, service, context, role="critic",
                                   prompt=CRITIC_PROMPT, output_model=CriticAssessment,
                                   evidence_requester=evidence_requester)
