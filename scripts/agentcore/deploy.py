"""Dry-run-first direct CodeZip deployment helper for manual Step 15B.3."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import os

import boto3

try:
    from .build_package import load_manifest
except ImportError:  # Direct ``python scripts/agentcore/deploy.py`` execution.
    from build_package import load_manifest

RUNTIME_NAME = "operon_reasoner"


def artifact_key(prefix: str, package_hash: str) -> str:
    return f"{prefix.strip('/')}/{package_hash}.zip"


def deployment_request(args, *, package_hash: str, operation: str) -> dict:
    key = artifact_key(args.s3_prefix, package_hash)
    return {
        "agentRuntimeName": RUNTIME_NAME,
        "agentRuntimeArtifact": {"codeConfiguration": {
            "code": {"s3": {"bucket": args.bucket, "prefix": key}},
            "runtime": "PYTHON_3_12", "entryPoint": load_manifest()["entry_point"]}},
        "roleArn": args.role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": args.idle_timeout},
        "environmentVariables": {
            "OPERON_AWS_REGION": args.region,
            "OPERON_BEDROCK_SUPERVISOR_MODEL_ID": args.supervisor_model,
            "OPERON_BEDROCK_SPECIALIST_MODEL_ID": args.specialist_model,
            "OPERON_RUNTIME_BUILD_ID": args.build_id,
            "UNIFIED_TRACES_DESTINATION_ENABLED": "true",
        },
        "description": "Operon packet-only advisory Reliability Supervisor",
    }


def confirmation(args, package_hash: str) -> str:
    if args.runtime_id:
        return f"UPDATE {RUNTIME_NAME} {args.runtime_id} {package_hash}"
    return f"CREATE {RUNTIME_NAME} {args.build_id} {package_hash}"


def client_token(request: dict, *, operation: str, runtime_id: str | None, package_hash: str,
                 region: str) -> str:
    material = {"operation": operation, "runtime": runtime_id or RUNTIME_NAME,
                "package_sha256": package_hash, "region": region, "request": request}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_update_target(control, args) -> dict:
    target = control.get_agent_runtime(agentRuntimeId=args.runtime_id)
    if target.get("agentRuntimeId") != args.runtime_id or target.get("agentRuntimeName") != RUNTIME_NAME:
        raise ValueError("update target is not the reviewed operon_reasoner runtime")
    arn = target.get("agentRuntimeArn", "")
    role_parts, runtime_parts = args.role_arn.split(":"), arn.split(":")
    if (len(role_parts) < 6 or len(runtime_parts) < 6 or runtime_parts[1] != role_parts[1]
            or runtime_parts[2] != "bedrock-agentcore"
            or runtime_parts[3] != args.region or runtime_parts[4] != role_parts[4]
            or not runtime_parts[5].endswith("/" + args.runtime_id)):
        raise ValueError("update runtime ARN/account/region differs from reviewed inputs")
    return target


def execute(args, *, session_factory=boto3.Session) -> dict:
    package = Path(args.package)
    if not package.is_file():
        raise FileNotFoundError(f"package is absent: {package}")
    package_hash = hashlib.sha256(package.read_bytes()).hexdigest()
    operation = "update" if args.runtime_id else "create"
    request = deployment_request(args, package_hash=package_hash, operation=operation)
    request["clientToken"] = client_token(request, operation=operation, runtime_id=args.runtime_id,
                                           package_hash=package_hash, region=args.region)
    expected_confirmation = confirmation(args, package_hash)
    key = request["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]["prefix"]
    print(f"mode={'EXECUTE' if args.execute else 'DRY-RUN'} profile={args.profile} region={args.region} runtime={RUNTIME_NAME}")
    print(f"role={args.role_arn}\npackage={package} sha256={package_hash}")
    print(f"s3=s3://{args.bucket}/{key}\nruntime_id={args.runtime_id or '<create new>'}")
    print(f"supervisor_model={args.supervisor_model}\nspecialist_model={args.specialist_model}\nbuild_id={args.build_id}")
    print(f"required_confirmation={expected_confirmation}")
    if not args.execute:
        return {"mode": "dry-run", "request": request}
    if args.confirm != expected_confirmation:
        raise ValueError(f"mutation requires --confirm {expected_confirmation!r}")
    session = session_factory(profile_name=args.profile, region_name=args.region)
    control = session.client("bedrock-agentcore-control")
    if args.runtime_id:
        verify_update_target(control, args)
    # The content-addressed key makes the reviewed SHA-256 the immutable artifact identity.
    session.client("s3").upload_file(str(package), args.bucket, key)
    if args.runtime_id:
        update = dict(request)
        update.pop("agentRuntimeName")
        response = control.update_agent_runtime(agentRuntimeId=args.runtime_id, **update)
    else:
        response = control.create_agent_runtime(**request)
    print(f"submitted agentRuntimeArn={response.get('agentRuntimeArn', '<not returned>')} status={response.get('status', '<not returned>')}")
    return response


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--profile", required=True, help="explicit AWS shared-config profile")
    result.add_argument("--region", default=os.getenv("OPERON_AGENTCORE_REGION", "us-east-1"))
    result.add_argument("--role-arn", required=True)
    result.add_argument("--bucket", required=True, help="existing private deployment bucket")
    result.add_argument("--s3-prefix", default="operon_reasoner")
    result.add_argument("--package", default="agentcore_app/build/operon_reasoner.zip")
    result.add_argument("--supervisor-model", required=True)
    result.add_argument("--specialist-model", required=True)
    result.add_argument("--build-id", required=True)
    result.add_argument("--runtime-id", help="explicit existing runtime ID to update; omitted means create")
    result.add_argument("--idle-timeout", type=int, default=120)
    result.add_argument("--execute", action="store_true")
    result.add_argument("--confirm", default="")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.role_arn.startswith("arn:") or not args.bucket.strip() or not args.supervisor_model.strip() or not args.specialist_model.strip():
        raise SystemExit("role ARN, bucket, and both verified model identifiers must be explicit")
    execute(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
