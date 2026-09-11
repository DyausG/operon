"""Read-only AWS readiness report for the manual Step 15B.3 bring-up."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import platform
from typing import Callable

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError


@dataclass(frozen=True)
class Check:
    name: str
    category: str
    ok: bool
    detail: str


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        return str(exc.response.get("Error", {}).get("Code", "ClientError"))
    return type(exc).__name__


_AUTH_ERRORS = {"ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId", "UnrecognizedClientException"}
_ACCESS_ERRORS = {"AccessDenied", "AccessDeniedException", "UnauthorizedException"}
_NOT_FOUND_ERRORS = {"ResourceNotFoundException", "ValidationException"}
_TRANSIENT_ERRORS = {"InternalServerException", "ServiceUnavailableException", "ThrottlingException",
                     "TooManyRequestsException"}


def _client_error_category(exc: ClientError, *, model: bool = False) -> str:
    code = _error_code(exc)
    if code in _AUTH_ERRORS:
        return "AWS_AUTHENTICATION_FAILURE"
    if code in _ACCESS_ERRORS:
        return "MODEL_UNAVAILABLE_OR_UNAUTHORIZED" if model else "AGENTCORE_ACCESS_DENIED"
    if code in _TRANSIENT_ERRORS:
        return "MODEL_API_TRANSIENT" if model else "AGENTCORE_API_TRANSIENT"
    if model and code in _NOT_FOUND_ERRORS:
        return "MODEL_UNAVAILABLE_OR_UNAUTHORIZED"
    return "MODEL_API_UNAVAILABLE" if model else "AGENTCORE_API_UNAVAILABLE"


def _foundation_check(client, identifier: str, label: str) -> Check:
    try:
        model = client.get_foundation_model(modelIdentifier=identifier)
        model_id = model.get("modelDetails", {}).get("modelId") or identifier
        availability = client.get_foundation_model_availability(modelId=model_id)
    except ClientError as exc:
        return Check(label, _client_error_category(exc, model=True), False,
                     f"{identifier}: {_error_code(exc)}")
    except BotoCoreError as exc:
        return Check(label, "MODEL_API_UNAVAILABLE", False, f"{identifier}: {_error_code(exc)}")
    refused = {key: value for key, value in availability.items()
               if key in {"authorizationStatus", "entitlementAvailability", "regionAvailability"}
               and value in {"NOT_AUTHORIZED", "NOT_AVAILABLE"}}
    agreement = availability.get("agreementAvailability", {})
    if agreement.get("status") in {"PENDING", "NOT_AVAILABLE"}:
        refused["agreementAvailability"] = agreement.get("status")
    if refused:
        return Check(label, "MODEL_UNAVAILABLE_OR_UNAUTHORIZED", False,
                     f"{identifier}: " + ", ".join(f"{key}={value}" for key, value in refused.items()))
    if agreement.get("status") == "ERROR":
        return Check(label, "MODEL_API_TRANSIENT", False,
                     f"{identifier}: agreementAvailability=ERROR")
    return Check(label, "MODEL", True, identifier)


def _model_check(client, identifier: str, label: str) -> Check:
    if identifier.startswith("arn:") and ":foundation-model/" in identifier:
        return _foundation_check(client, identifier, label)
    # Both system and application inference profiles use GetInferenceProfile.
    # Bare identifiers are ambiguous, so profile lookup comes first.
    try:
        profile = client.get_inference_profile(inferenceProfileIdentifier=identifier)
        if profile.get("status") not in (None, "ACTIVE"):
            return Check(label, "MODEL_UNAVAILABLE_OR_UNAUTHORIZED", False,
                         f"{identifier}: profile status={profile.get('status')}")
        return Check(label, "MODEL", True, identifier)
    except ClientError as exc:
        if _error_code(exc) not in _NOT_FOUND_ERRORS:
            return Check(label, _client_error_category(exc, model=True), False,
                         f"{identifier}: {_error_code(exc)}")
    except BotoCoreError as exc:
        return Check(label, "MODEL_API_UNAVAILABLE", False, f"{identifier}: {_error_code(exc)}")
    return _foundation_check(client, identifier, label)


def run(*, profile: str = "", region: str, supervisor_model: str, specialist_model: str,
        runtime_arn: str = "", qualifier: str = "DEFAULT", invocation_check: bool = False,
        session_factory: Callable[..., object] = boto3.Session) -> list[Check]:
    checks = [Check("region", "CONFIG", bool(region), region or "region is missing")]
    for name, value in (("supervisor model", supervisor_model), ("specialist model", specialist_model)):
        checks.append(Check(name, "CONFIG" if value else "MISSING_CONFIG", bool(value), value or "identifier is missing"))
    if invocation_check:
        checks.append(Check("runtime", "CONFIG" if runtime_arn else "RUNTIME_NOT_CONFIGURED",
                            bool(runtime_arn), f"{runtime_arn or 'runtime ARN is missing'} qualifier={qualifier}"))
    if not region or not supervisor_model or not specialist_model or invocation_check and not runtime_arn:
        return checks
    try:
        session = session_factory(profile_name=profile, region_name=region)
        identity = session.client("sts").get_caller_identity()
        checks.append(Check("caller identity", "AWS_AUTH", True,
                            f"account={identity.get('Account')} arn={identity.get('Arn')}"))
    except (NoCredentialsError, PartialCredentialsError, ClientError, BotoCoreError) as exc:
        checks.append(Check("caller identity", "AWS_AUTHENTICATION_FAILURE", False, _error_code(exc)))
        return checks
    try:
        control = session.client("bedrock-agentcore-control")
        required = {"CreateAgentRuntime", "UpdateAgentRuntime", "GetAgentRuntime", "ListAgentRuntimes"}
        missing = sorted(required - set(control.meta.service_model.operation_names))
        checks.append(Check("AgentCore control SDK", "AGENTCORE_API_UNAVAILABLE" if missing else "SDK",
                            not missing, "missing operations: " + ", ".join(missing) if missing else "required operations available"))
        if not missing:
            control.list_agent_runtimes(maxResults=1)
            checks.append(Check("AgentCore control API", "AGENTCORE_API", True, "read-only list succeeded"))
        data = session.client("bedrock-agentcore")
        data_required = {"InvokeAgentRuntime", "StopRuntimeSession"}
        data_missing = sorted(data_required - set(data.meta.service_model.operation_names))
        if data_missing:
            checks.append(Check("AgentCore data SDK", "AGENTCORE_API_UNAVAILABLE", False,
                                "missing operations: " + ", ".join(data_missing)))
    except ClientError as exc:
        checks.append(Check("AgentCore control API", _client_error_category(exc), False, _error_code(exc)))
    except (BotoCoreError, KeyError) as exc:
        checks.append(Check("AgentCore SDK/API", "AGENTCORE_API_UNAVAILABLE", False, _error_code(exc)))
    try:
        bedrock = session.client("bedrock")
        checks.extend((_model_check(bedrock, supervisor_model, "supervisor model access"),
                       _model_check(bedrock, specialist_model, "specialist model access")))
    except (BotoCoreError, ClientError, KeyError) as exc:
        checks.append(Check("Bedrock API", "MODEL_UNAVAILABLE_OR_UNAUTHORIZED", False, _error_code(exc)))
    checks.append(Check("package target", "ARCHITECTURE", True,
                        f"build host={platform.machine()} target=Python 3.12/aarch64-manylinux2014 CodeZip"))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="explicit AWS shared-config profile")
    parser.add_argument("--region", default=os.getenv("OPERON_AGENTCORE_REGION", "us-east-1"))
    parser.add_argument("--supervisor-model", default=os.getenv("OPERON_BEDROCK_SUPERVISOR_MODEL_ID", ""))
    parser.add_argument("--specialist-model", default=os.getenv("OPERON_BEDROCK_SPECIALIST_MODEL_ID", ""))
    parser.add_argument("--runtime-arn", default=os.getenv("OPERON_AGENTCORE_RUNTIME_ARN", ""))
    parser.add_argument("--qualifier", default=os.getenv("OPERON_AGENTCORE_QUALIFIER", "DEFAULT"))
    parser.add_argument("--invocation-check", action="store_true")
    args = parser.parse_args(argv)
    checks = run(profile=args.profile, region=args.region, supervisor_model=args.supervisor_model,
                 specialist_model=args.specialist_model, runtime_arn=args.runtime_arn,
                 qualifier=args.qualifier, invocation_check=args.invocation_check)
    for check in checks:
        print(f"{'OK' if check.ok else 'FAIL'} [{check.category}] {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 2


if __name__ == "__main__":
    raise SystemExit(main())
