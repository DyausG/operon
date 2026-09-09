"""Independent diagnostic advice through native Strands; no application authority."""
from core.reliability.evidence import EvidenceService
from .contracts import DiagnosticAssessment, DiagnosticContext
from .invocation import SpecialistInvocationError, invoke_specialist
from .runtime import StrandsRuntime

DIAGNOSTIC_PROMPT = """You are Operon's Diagnostic Specialist. Compare competing causal hypotheses;
identify supporting and opposing evidence and discriminating falsification tests.
Recommend a hypothesis only when justified. A predictive model risk score or
candidate mode is a clue, never a confirmed diagnosis or causal proof. Calibrate
confidence to evidence strength; numerical confidence is not statistically
calibrated. Expose uncertainty and request missing evidence. Use request_evidence
before citing a new read observation as durable evidence. Never claim unavailable
OEM limits or prescribe consequential execution. Hypothesis keys are local
suggestions, not domain IDs.
"""

# Preserve the Step 12A exception API.
DiagnosticInvocationError = SpecialistInvocationError


async def assess_diagnosis(runtime: StrandsRuntime, service: EvidenceService,
                           context: DiagnosticContext) -> DiagnosticAssessment:
    return await invoke_specialist(runtime, service, context, role="diagnostic",
                                   prompt=DIAGNOSTIC_PROMPT, output_model=DiagnosticAssessment)
