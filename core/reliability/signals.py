"""Convert the existing classifier output into explicitly sourced evidence."""
from hashlib import sha256
from pathlib import Path

from core.seed_data import SENSOR_FEATURES
from .freshness import observation_manifest
from .models import Evidence, ModelSignal
from .repository import content_hash, new_id, utcnow


def model_version(model_path: Path) -> str:
    if model_path.is_file():
        return "sha256:" + sha256(model_path.read_bytes()).hexdigest()
    # Tests/custom models may have no saved artifact. Do not invent a model version.
    return "unavailable:no-persisted-model-artifact"


def from_prediction(equipment_id, asset, drivers, *, observed_at, source, version) -> ModelSignal:
    mode = asset["predicted_mode"]
    return ModelSignal(
        id=new_id(), created_at=utcnow(), equipment_id=equipment_id,
        observed_at=observed_at, risk_score=asset["failure_prob"],
        health_score=asset["health_score"], candidate_failure_mode=mode["mode"],
        mode_distribution=mode.get("distribution", mode.get("mode_probs", {})),
        attribution=tuple(drivers),
        features={key: asset[key] for key in ("type_code", *(f[0] for f in SENSOR_FEATURES))},
        model_source=source, model_version=version,
        input_source="core.simulator.PlantSimulator", input_provenance="SIMULATED",
    )


def signal_evidence(signal: ModelSignal, incident_id: str) -> Evidence:
    payload = signal.model_dump(mode="json")
    now = utcnow()
    return Evidence(
        id=new_id(), incident_id=incident_id, created_at=now,
        equipment_ids=(signal.equipment_id,), kind="model_signal",
        source_uri=signal.model_source, source_locator=f"signal:{signal.id}",
        source_version=signal.model_version, content_hash=content_hash(payload),
        observed_at=signal.observed_at, retrieved_at=now, quality="GOOD", provenance="DERIVED",
        source_capability="admit_model_signal",
        source_system=f"{signal.input_source}+{signal.model_source}",
        summary=f"Model risk signal {signal.risk_score:.1%}; candidate mode {signal.candidate_failure_mode}",
        payload=payload,
        # A dated classifier observation: later telemetry cannot make it false.
        source_dependencies=observation_manifest(),
    )
