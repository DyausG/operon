"""Independent planner advice through native Strands; no application authority."""
from core.reliability.evidence import EvidenceService
from .contracts import MaintenancePlanAssessment, SpecialistContext
from .invocation import invoke_specialist
from .runtime import StrandsRuntime

PLANNER_PROMPT = """You are Operon's Maintenance Planner Specialist. Combine supplied diagnostic,
engineering, operational, and review inputs into a structured maintenance proposal.
Preserve their advisory or domain status; never treat an advisory acceptance as
validated application state. Reference durable inputs in validated_input_ids and
local advice in input_assessment_keys. Order steps and express dependencies as
zero-based preceding step indices. Include preconditions, verification criteria,
unresolved blockers, operational exposure, reversibility, external commitment,
and safety/approval considerations. Inspect resource reads where useful; never
fabricate availability, cost, or downtime. Unknown exposure amount and currency
must both be null. Cite resource record IDs/provenance in narrative, not as newly
persisted evidence. Never approve or execute the proposal, create an authoritative
Intervention, or mutate services.
"""


async def plan_maintenance(runtime: StrandsRuntime, service: EvidenceService,
                           context: SpecialistContext) -> MaintenancePlanAssessment:
    return await invoke_specialist(runtime, service, context, role="planner",
                                   prompt=PLANNER_PROMPT, output_model=MaintenancePlanAssessment)
