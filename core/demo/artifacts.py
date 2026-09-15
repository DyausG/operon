"""Disposable artifact detail index and integrity checks for the Guided Demo."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Iterable, Mapping


class DemoArtifactGraphError(ValueError):
    """The Guided Demo read-model graph contains an invalid or stale relationship."""


class DemoArtifactIndex:
    """In-memory, non-authoritative detail lookup for one demo generation."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def clear(self) -> None:
        self._items.clear()

    def register(self, artifact: dict) -> None:
        artifact_id = artifact["id"]
        if artifact_id in self._items:
            raise DemoArtifactGraphError(f"duplicate demo artifact id: {artifact_id}")
        self._items[artifact_id] = artifact

    def get(self, artifact_id: str) -> dict | None:
        artifact = self._items.get(artifact_id)
        return deepcopy(artifact) if artifact is not None else None

    def values(self) -> list[dict]:
        return deepcopy(list(self._items.values()))

    def sync_projection(self, projection: dict) -> None:
        """Keep a registered detail payload aligned with its compact snapshot row."""
        artifact_id = projection.get("artifact_id") or projection.get("id")
        artifact = self._items.get(artifact_id)
        if artifact is None:
            return
        common = {"id", "artifact_id", "created_at", "updated_at", "provenance", "runtime", "live_model"}
        artifact["payload"] = deepcopy({key: value for key, value in projection.items() if key not in common})
        if projection.get("status") is not None:
            artifact["status"] = projection["status"]
        if projection.get("created_at"):
            artifact["created_at"] = projection["created_at"]


def _as_artifacts(artifacts: Mapping[str, dict] | Iterable[dict]) -> tuple[list[dict], dict[str, dict]]:
    values = list(artifacts.values()) if isinstance(artifacts, Mapping) else list(artifacts)
    by_id: dict[str, dict] = {}
    for artifact in values:
        artifact_id = artifact.get("id")
        if not artifact_id:
            raise DemoArtifactGraphError("demo artifact is missing id")
        if artifact_id in by_id:
            raise DemoArtifactGraphError(f"duplicate demo artifact id: {artifact_id}")
        by_id[artifact_id] = artifact
    return values, by_id


def validate_demo_artifact_graph(artifacts: Mapping[str, dict] | Iterable[dict]) -> None:
    """Validate referential, semantic, provenance, and chronological demo integrity."""
    values, by_id = _as_artifacts(artifacts)
    timestamps: dict[str, datetime] = {}
    for artifact in values:
        artifact_id = artifact["id"]
        if artifact.get("provenance") != "SIMULATED" or artifact.get("live_model") is not False:
            raise DemoArtifactGraphError(f"{artifact_id} is not explicitly simulated")
        if artifact.get("runtime") != "operon.demo.guided-v1":
            raise DemoArtifactGraphError(f"{artifact_id} has an unexpected demo runtime")
        if artifact.get("incident_id") != "DEMO-INCIDENT-01" or not artifact.get("equipment_id"):
            raise DemoArtifactGraphError(f"{artifact_id} is outside the active demo incident scope")
        try:
            timestamps[artifact_id] = datetime.fromisoformat(artifact["created_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DemoArtifactGraphError(f"{artifact_id} has an invalid created_at") from exc
        for field in ("parent_ids", "supporting_ids", "related_ids"):
            for reference in artifact.get(field, []):
                if reference not in by_id:
                    raise DemoArtifactGraphError(f"{artifact_id} has broken {field} reference: {reference}")

    # A cause/support must exist no later than the artifact that depends on it.
    for artifact in values:
        for reference in (*artifact.get("parent_ids", []), *artifact.get("supporting_ids", [])):
            if timestamps[reference] > timestamps[artifact["id"]]:
                raise DemoArtifactGraphError(f"{artifact['id']} predates dependency {reference}")

    def one(kind: str) -> dict | None:
        matches = [item for item in values if item["artifact_type"] == kind]
        if len(matches) > 1:
            raise DemoArtifactGraphError(f"multiple {kind} artifacts exist")
        return matches[0] if matches else None

    diagnosis = one("diagnosis")
    diagnosis_verdict = one("diagnosis_validation")
    intervention = one("intervention")
    work_package = one("work_package")
    approval_request = one("approval_request")
    approval = one("approval_binding")
    work_order = one("work_order")
    receipt = one("execution_receipt")
    outcome = one("outcome_verification")
    closure = one("incident_closure")

    if diagnosis:
        for evidence_id in diagnosis["payload"].get("evidence_ids", []):
            target = by_id.get(evidence_id)
            if target is None or target["artifact_type"] not in {"predictive_signal", "evidence", "technician_inspection"}:
                raise DemoArtifactGraphError(f"diagnosis has invalid evidence reference: {evidence_id}")
    if diagnosis_verdict and diagnosis_verdict["payload"].get("subject_artifact_id") != (diagnosis or {}).get("id"):
        raise DemoArtifactGraphError("diagnosis validation does not reference the actual diagnosis")
    if intervention:
        if intervention["payload"].get("diagnosis_id") != (diagnosis or {}).get("id"):
            raise DemoArtifactGraphError("intervention does not reference the actual diagnosis")
        if diagnosis_verdict and diagnosis_verdict["id"] not in intervention.get("supporting_ids", []):
            raise DemoArtifactGraphError("intervention is not supported by diagnosis validation")
    for review_type in ("engineering_review", "operations_review", "critic_intervention_review"):
        review = one(review_type)
        if review and review["payload"].get("intervention_id") != (intervention or {}).get("id"):
            raise DemoArtifactGraphError(f"{review_type} does not reference the actual intervention")
    if work_package and work_package["payload"].get("intervention_id") != (intervention or {}).get("id"):
        raise DemoArtifactGraphError("work package does not reference the actual intervention")
    for resource_type in ("inventory_reservation", "technician_assignment", "scheduling_record"):
        resource = one(resource_type)
        if resource and (resource["payload"].get("work_package_id") != (work_package or {}).get("id") or
                         resource["payload"].get("intervention_id") != (intervention or {}).get("id")):
            raise DemoArtifactGraphError(f"{resource_type} is not bound to the intended plan")
    if approval_request and (approval_request["payload"].get("intervention_id") != (intervention or {}).get("id") or
                             approval_request["payload"].get("work_package_id") != (work_package or {}).get("id") or
                             approval_request["payload"].get("intervention_hash") !=
                             (work_package or {}).get("payload", {}).get("plan_hash")):
        raise DemoArtifactGraphError("approval request does not bind the exact displayed plan")
    if approval and (approval["payload"].get("approval_request_id") != (approval_request or {}).get("id") or
                     approval["payload"].get("intervention_id") != (intervention or {}).get("id") or
                     approval["payload"].get("work_package_id") != (work_package or {}).get("id") or
                     approval["payload"].get("intervention_hash") !=
                     (work_package or {}).get("payload", {}).get("plan_hash")):
        raise DemoArtifactGraphError("approval does not bind the exact displayed plan")
    if work_order and (work_order["payload"].get("approval_binding_id") != (approval or {}).get("id") or
                       work_order["payload"].get("work_package_id") != (work_package or {}).get("id") or
                       work_order["payload"].get("intervention_id") != (intervention or {}).get("id")):
        raise DemoArtifactGraphError("work order does not reference the exact approved plan")
    if receipt and (receipt["payload"].get("work_order_id") != (work_order or {}).get("id") or
                    receipt["payload"].get("approval_binding_id") != (approval or {}).get("id") or
                    receipt["payload"].get("intervention_id") != (intervention or {}).get("id") or
                    receipt["payload"].get("work_package_id") != (work_package or {}).get("id")):
        raise DemoArtifactGraphError("execution receipt does not reference the exact approved plan")
    observations = [item for item in values if item["artifact_type"] == "recovery_observation"]
    for observation in observations:
        if observation["payload"].get("execution_receipt_id") != (receipt or {}).get("id") or \
                observation["payload"].get("intervention_id") != (intervention or {}).get("id"):
            raise DemoArtifactGraphError("recovery observation does not reference execution and intervention")
    if outcome:
        expected = [item["id"] for item in sorted(observations, key=lambda item: item["payload"]["sequence"])]
        if outcome["payload"].get("observation_ids") != expected or \
                outcome["payload"].get("execution_receipt_id") != (receipt or {}).get("id"):
            raise DemoArtifactGraphError("verified recovery does not reference its execution observations")
    if closure and (closure["payload"].get("outcome_id") != (outcome or {}).get("id") or
                    closure["payload"].get("final_phase") != "CLOSED"):
        raise DemoArtifactGraphError("incident closure does not reference the verified outcome")
