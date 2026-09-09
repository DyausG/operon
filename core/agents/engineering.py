"""Independent engineering advice through native Strands; no application authority."""
from core.reliability.evidence import EvidenceService
from .contracts import EngineeringAssessment, SpecialistContext
from .invocation import invoke_specialist
from .runtime import StrandsRuntime

ENGINEERING_PROMPT = """You are Operon's Engineering Specialist. Assess technical feasibility of supplied
candidate interventions against the supplied diagnosis or diagnostic advice.
Distinguish FEASIBLE, CONDITIONAL, UNKNOWN (unsupported), INFEASIBLE (blocked),
and UNSAFE. Record only evidenced constraints; identify missing constraints,
technical blockers, safety concerns, and supported intervention elements.
Never invent OEM limits, materials, tolerances, pressure/temperature ratings,
certifications, or dimensions. Missing required applicability data prevents an
unconditional feasibility claim. Reference diagnosis_id only when supplied as a
durable Diagnosis; otherwise cite diagnostic input_assessment_keys.
"""


async def assess_engineering(runtime: StrandsRuntime, service: EvidenceService,
                           context: SpecialistContext) -> EngineeringAssessment:
    return await invoke_specialist(runtime, service, context, role="engineering",
                                   prompt=ENGINEERING_PROMPT, output_model=EngineeringAssessment)
