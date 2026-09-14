"""Opt-in live advisory smoke through AgentCoreBackend using an isolated fixture DB."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import tempfile


def _args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="permit one live AgentCore invocation")
    parser.add_argument("--profile", required=True, help="explicit AWS shared-config profile")
    parser.add_argument("--runtime-arn", default=os.getenv("OPERON_AGENTCORE_RUNTIME_ARN", ""))
    parser.add_argument("--qualifier", default=os.getenv("OPERON_AGENTCORE_QUALIFIER", "DEFAULT"))
    parser.add_argument("--region", default=os.getenv("OPERON_AGENTCORE_REGION", "us-east-1"))
    parser.add_argument("--supervisor-model", default=os.getenv("OPERON_BEDROCK_SUPERVISOR_MODEL_ID", ""))
    parser.add_argument("--specialist-model", default=os.getenv("OPERON_BEDROCK_SPECIALIST_MODEL_ID", ""))
    parser.add_argument("--build-id", default=os.getenv("OPERON_RUNTIME_BUILD_ID", ""))
    return parser.parse_args(argv)


async def run(args) -> dict:
    if not args.execute or os.getenv("OPERON_LIVE_AWS") != "1":
        raise RuntimeError("live smoke requires both --execute and OPERON_LIVE_AWS=1")
    missing = [name for name, value in (("runtime ARN", args.runtime_arn),
               ("supervisor model", args.supervisor_model), ("specialist model", args.specialist_model)) if not value]
    if missing:
        raise ValueError("missing explicit " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="operon-agentcore-smoke-") as directory:
        db_path = Path(directory) / "fixture.db"
        # Imports follow path selection so no production/local SQLite path can be opened.
        from core import config, db
        config.DB_PATH = db.DB_PATH = db_path
        from core.agents.contracts import SpecialistContext, SupervisorBounds
        from core.reliability import models as m
        from core.reliability.evidence import EvidenceService
        from core.reliability.promotion import PromotionService
        from core.reliability.repository import IncidentRepository, new_id, utcnow
        from core.reasoning.agentcore import AgentCoreBackend, AgentCoreSettings
        from core.seed_data import seed
        import boto3
        db.init_schema(db_path)
        seed(reset=True)
        repo = IncidentRepository(db_path)
        promotion = PromotionService(repo)
        evidence = EvidenceService(repo)
        now = utcnow()
        signal = m.ModelSignal(
            id=new_id(), created_at=now, observed_at=now, equipment_id="AC-COMP-01",
            risk_score=0.91, health_score=0.09, candidate_failure_mode="OSF",
            mode_distribution={"OSF": 0.7, "PWF": 0.3},
            attribution=(m.Attribution(feature="torque", label="Torque", value=62, contribution=0.3),),
            features={"torque": 62}, model_source="scripts.agentcore.smoke.fixture",
            model_version="fixture-v1", input_source="explicit-smoke-fixture", input_provenance="SIMULATED")
        incident, _ = repo.admit_signal(signal)
        incident = repo.transition(incident.id, m.IncidentPhase.INVESTIGATING,
                                   expected_revision=incident.revision, reason="isolated smoke fixture")
        history = evidence.request_and_collect(
            incident.id, requested_by="application", equipment_ids=("AC-COMP-01",),
            question="Read fixture service history", capability="get_maintenance_history",
            required_for="diagnosis")
        settings = AgentCoreSettings(
            runtime_arn=args.runtime_arn, qualifier=args.qualifier, region=args.region,
            supervisor_model_id=args.supervisor_model, specialist_model_id=args.specialist_model,
            build_id=args.build_id or None)
        def client_factory(*, region_name, config):
            return boto3.Session(profile_name=args.profile, region_name=region_name).client(
                "bedrock-agentcore", config=config)
        backend = AgentCoreBackend(settings, client_factory=client_factory)
        snapshot = promotion.start_run(
            incident.id, asset_id="AC-COMP-01", stage="DIAGNOSIS",
            expected_revision=repo.fetch_incident(incident.id).revision,
            evidence_ids=(incident.signal_evidence_ids[0], history.evidence.id), runtime=backend)
        context = SpecialistContext.model_validate(snapshot.context_payload)
        before = repo.fetch_incident(incident.id)
        result = await backend.supervise(evidence, context,
                                         bounds=SupervisorBounds.model_validate(snapshot.bounds), snapshot=snapshot)
        after = repo.fetch_incident(incident.id)
        if after != before:
            raise RuntimeError("authority boundary failed: live advisory invocation mutated fixture lifecycle state")
        concise = {
            "incident_id": incident.id, "run_id": snapshot.run_id,
            "session_id": f"operon-run-{snapshot.run_id}", "snapshot_id": snapshot.id,
            "disposition": result.disposition, "termination_reason": result.termination_reason,
            "assessment_count": len(result.assessments), "blockers": list(result.blockers),
            "human_review_required": result.human_review_required,
            "authoritative_state_unchanged": True,
        }
        for key, value in concise.items():
            print(f"{key}={value}")
        return concise


def main(argv=None) -> int:
    asyncio.run(run(_args(argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
