"""Independent operations advice through native Strands; no application authority."""
from core.reliability.evidence import EvidenceService
from .contracts import OperationsAssessment, SpecialistContext
from .invocation import invoke_specialist
from .runtime import StrandsRuntime

OPERATIONS_PROMPT = """You are Operon's Operations Specialist. Assess operational feasibility of the
supplied intervention or advisory candidate. Inspect bounded inventory, workforce,
scheduling, and maintenance/work-order context as needed. Expose shortages,
competing reservations, labor bookings, missing calendar data, and coordination
options. Distinguish missing information from unavailability. Roster entries and
booking labels do not confirm qualified labor at a dated time or a production
window. Use resource read provenance and record IDs in observations; these reads
are not new durable Evidence. Never reserve parts, assign technicians, block
schedules, open work orders, or send notifications. Reference intervention_id only
for a supplied durable Intervention; otherwise cite input_assessment_keys.
"""


async def assess_operations(runtime: StrandsRuntime, service: EvidenceService,
                           context: SpecialistContext) -> OperationsAssessment:
    return await invoke_specialist(runtime, service, context, role="operations",
                                   prompt=OPERATIONS_PROMPT, output_model=OperationsAssessment)
