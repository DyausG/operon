"""Application authority boundary for admission and legacy demo checkpoints.

No agent orchestration or validation/approval policy is implemented here. The
legacy path leaves incidents OPEN: an old proposal is not a validated diagnosis,
and an old PREVENTED result is not evidence of recovery. These incidents remain
available for later investigation until explicitly transitioned or demo-reset.
Legacy CMMS commits and these checkpoints are separate transactions; crash-safe
execution reconciliation belongs to the subsequent governed-execution stage.
"""
from .models import Incident, IncidentPhase, LegacyAlert, ModelSignal
from .repository import IncidentRepository, new_id, utcnow


class IncidentCoordinator:
    def __init__(self, repository: IncidentRepository):
        self.repository = repository

    def admit(self, signal: ModelSignal, *, severity: str, triage_score: float) -> tuple[Incident, bool]:
        return self.repository.admit_signal(signal, severity=severity, triage_score=triage_score)

    def transition(self, incident_id: str, target: IncidentPhase, *, expected_revision: int,
                   reason: str) -> Incident:
        """Trusted application command; never bind this directly to model output."""
        return self.repository.transition(incident_id, target, expected_revision=expected_revision, reason=reason)

    def checkpoint_legacy(self, incident: Incident, alert: dict, simulator_state) -> Incident:
        snapshot = LegacyAlert(
            id=new_id(), created_at=utcnow(), incident_id=incident.id,
            **{k: v for k, v in alert.items() if k != "incident_id"},
            simulator_progress=simulator_state.prog, simulator_tick=simulator_state.tick,
        )
        return self.repository.add_artifact(snapshot, expected_revision=incident.revision)

    def recover(self) -> list[tuple[Incident, LegacyAlert | None]]:
        return [(incident, self.repository.get_artifact(incident.id, incident.legacy_alert_id)
                 if incident.legacy_alert_id else None)
                for incident in self.repository.list_active_incidents()]


def legacy_projection(snapshot: LegacyAlert) -> dict:
    return snapshot.model_dump(mode="json", exclude={
        "id", "schema_version", "created_at", "simulator_progress", "simulator_tick",
    })
