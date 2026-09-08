"""Pure phase validation. This graph grants no approval or execution authority."""
from .models import IncidentPhase as Phase


class InvalidTransition(ValueError):
    pass


# Escalations and execution failures remain active, requiring an explicit
# application decision to resume or cancel. Only closed/cancelled release admission.
TERMINAL_PHASES = frozenset({Phase.CLOSED, Phase.CANCELLED})
TRANSITIONS = {
    Phase.OPEN: {Phase.INVESTIGATING},
    Phase.INVESTIGATING: {Phase.AWAITING_EVIDENCE, Phase.DIAGNOSIS_VALIDATED},
    Phase.AWAITING_EVIDENCE: {Phase.INVESTIGATING},
    Phase.DIAGNOSIS_VALIDATED: {Phase.PLANNING, Phase.INVESTIGATING},
    Phase.PLANNING: {Phase.INTERVENTION_VALIDATED, Phase.INVESTIGATING},
    Phase.INTERVENTION_VALIDATED: {Phase.AWAITING_APPROVAL, Phase.READY, Phase.PLANNING},
    Phase.AWAITING_APPROVAL: {Phase.READY, Phase.INVESTIGATING, Phase.PLANNING},
    Phase.READY: {Phase.EXECUTING, Phase.PLANNING},
    Phase.EXECUTING: {Phase.OBSERVING, Phase.EXECUTION_FAILED},
    Phase.OBSERVING: {Phase.CLOSED, Phase.INVESTIGATING},
    Phase.ESCALATED: {Phase.INVESTIGATING, Phase.CANCELLED},
    # READY is a trusted executor retry checkpoint. Policy and durable receipts
    # still decide which failed steps may be attempted again.
    Phase.EXECUTION_FAILED: {Phase.READY, Phase.INVESTIGATING, Phase.ESCALATED, Phase.CANCELLED},
    Phase.CLOSED: set(),
    Phase.CANCELLED: set(),
}
for _phase in Phase:
    if _phase not in TERMINAL_PHASES | {Phase.ESCALATED, Phase.EXECUTION_FAILED}:
        TRANSITIONS[_phase].update({Phase.ESCALATED, Phase.CANCELLED})


def validate_transition(current: Phase, target: Phase) -> None:
    current, target = Phase(current), Phase(target)
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(f"cannot transition {current.value} -> {target.value}")
