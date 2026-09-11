"""Offline tests for Step 15B.2 deployment preparation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
import pytest

from scripts.agentcore import build_package, deploy, preflight

ROOT = Path(__file__).resolve().parents[1]


def test_package_manifest_is_an_explicit_packet_runtime_allowlist():
    manifest = build_package.load_manifest()
    sources = set(manifest["sources"])
    assert manifest["python_runtime"] == "PYTHON_3_12"
    assert manifest["python_platform"] == "aarch64-manylinux2014"
    assert {"agentcore_app/main.py", "core/reasoning/handler.py", "core/reasoning/protocol.py",
            "core/reasoning/packet.py", "core/agents/supervisor.py"} <= sources
    assert set(build_package.IDENTITY_SOURCES) <= sources
    assert all((ROOT / name).is_file() for name in sources)
    assert not any(name.startswith(("tests/", "data/", "frontend/", "server/")) for name in sources)
    assert not any(Path(name).suffix in {".db", ".env", ".key", ".pem"} for name in sources)
    assert "core/engine.py" not in sources and "core/reliability/execution.py" not in sources
    build_package.validate_identity_dependencies(ROOT / "agentcore_app/requirements.txt")
    versions = build_package.locked_versions(ROOT / "agentcore_app/requirements.txt")
    assert {name: versions[name] for name in build_package.IDENTITY_DEPENDENCIES} == {
        "pydantic": "2.13.4", "pydantic-core": "2.46.4", "strands-agents": "1.54.0"}


def test_sources_only_package_is_deterministic_and_clean():
    first = build_package.build(dependencies=False).read_bytes()
    second = build_package.build(dependencies=False).read_bytes()
    assert first == second
    names = build_package.validate_tree(build_package.PACKAGE)
    assert "main.py" in names and "core/reasoning/trust.py" not in names
    assert not any("__pycache__" in name or name.endswith((".db", ".pyc")) for name in names)


def test_iam_assets_enforce_exact_actions_effects_resources_and_conditions():
    directory = ROOT / "scripts/agentcore/iam"
    runtime = json.loads((directory / "runtime-permissions-policy.json").read_text())
    trust = json.loads((directory / "runtime-trust-policy.json").read_text())
    invoker = json.loads((directory / "application-invoker-policy.json").read_text())
    documents = [runtime, trust, invoker]
    text = "\n".join(path.read_text() for path in directory.glob("*.json"))
    assert "${ACCOUNT_ID}" in text and "${RUNTIME_ARN}" in text
    assert not any(marker in text for marker in ("123456789012", "arn:aws:iam::", "claude-"))
    statements = {item["Sid"]: item for item in runtime["Statement"]}
    assert set(statements) == {"InvokeConfiguredModels", "WriteRuntimeLogs",
        "DiscoverAndConfigureRuntimeTelemetryLogs", "CreateRuntimeLogGroup",
        "PublishRuntimeMetrics", "PublishRuntimeTraces"}
    assert statements["InvokeConfiguredModels"]["Action"] == [
        "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    assert statements["InvokeConfiguredModels"]["Resource"] == ["${SUPERVISOR_MODEL_ARN}",
        "${SPECIALIST_MODEL_ARN}", "${SUPERVISOR_FOUNDATION_MODEL_ARN}",
        "${SPECIALIST_FOUNDATION_MODEL_ARN}"]
    assert statements["PublishRuntimeMetrics"]["Condition"] == {
        "StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}
    assert all(item["Effect"] == "Allow" for item in runtime["Statement"])
    trust_statement = trust["Statement"][0]
    assert trust_statement == {"Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
        "Action": "sts:AssumeRole", "Condition": {"StringEquals": {"aws:SourceAccount": "${ACCOUNT_ID}"},
        "ArnLike": {"aws:SourceArn": "arn:${PARTITION}:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:*"}}}
    assert invoker["Statement"] == [{"Sid": "InvokeAndStopOperonRuntime", "Effect": "Allow",
        "Action": ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:StopRuntimeSession"],
        "Resource": ["${RUNTIME_ARN}", "${RUNTIME_ENDPOINT_ARN}"]},
        {"Sid": "ForbidUserImpersonationInvocation", "Effect": "Deny",
         "Action": "bedrock-agentcore:InvokeAgentRuntimeForUser", "Resource": "*"}]
    all_actions = json.dumps(documents)
    assert not any(wildcard in all_actions for wildcard in (
        '"bedrock:*"', '"logs:*"', '"bedrock-agentcore:*"', '"iam:', '"s3:', '"dynamodb:'))


class FakeMeta:
    def __init__(self, operations):
        self.service_model = type("ServiceModel", (), {"operation_names": operations})()


class FakeClient:
    def __init__(self, *, operations=(), errors=None):
        self.meta = FakeMeta(operations)
        self.errors = errors or {}
        self.calls = []

    def _call(self, name, kwargs):
        self.calls.append((name, kwargs))
        if name in self.errors:
            raise self.errors[name]

    def list_agent_runtimes(self, **kwargs):
        self._call("list_agent_runtimes", kwargs)
        return {"agentRuntimes": []}

    def get_caller_identity(self):
        return {"Account": "fixture-account", "Arn": "fixture-caller"}

    def get_inference_profile(self, **kwargs):
        self._call("get_inference_profile", kwargs)
        return {"status": "ACTIVE"}

    def get_foundation_model(self, **kwargs):
        self._call("get_foundation_model", kwargs)
        return {"modelDetails": {"modelId": kwargs["modelIdentifier"].rsplit("/", 1)[-1]}}

    def get_foundation_model_availability(self, **kwargs):
        self._call("get_foundation_model_availability", kwargs)
        return {"agreementAvailability": {"status": "AVAILABLE"}, "authorizationStatus": "AUTHORIZED",
                "entitlementAvailability": "AVAILABLE", "regionAvailability": "AVAILABLE"}


class FakeSession:
    def __init__(self, *, auth_failure=False, clients=None):
        self.auth_failure, self.clients = auth_failure, clients or {}
    def client(self, name):
        if name == "sts" and self.auth_failure: raise NoCredentialsError()
        if name == "sts": return FakeClient()
        return self.clients.get(name, FakeClient(operations=["InvokeAgentRuntime", "StopRuntimeSession"]))


def test_preflight_missing_config_and_runtime_fail_without_creating_session():
    called = []
    checks = preflight.run(region="us-east-1", supervisor_model="", specialist_model="",
                           invocation_check=True, session_factory=lambda **kw: called.append(kw))
    assert called == []
    assert {check.category for check in checks if not check.ok} == {"MISSING_CONFIG", "RUNTIME_NOT_CONFIGURED"}


def test_preflight_categorizes_authentication_and_model_failures():
    auth = preflight.run(region="us-east-1", supervisor_model="ok", specialist_model="ok",
                         session_factory=lambda **_: FakeSession(auth_failure=True))
    assert any(check.category == "AWS_AUTHENTICATION_FAILURE" for check in auth)
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetInferenceProfile")
    bedrock = FakeClient(errors={"get_inference_profile": denied})
    control = FakeClient(operations=["CreateAgentRuntime", "UpdateAgentRuntime", "GetAgentRuntime", "ListAgentRuntimes"])
    model = preflight.run(region="us-east-1", supervisor_model="ok", specialist_model="denied-profile",
                          session_factory=lambda **_: FakeSession(clients={
                              "bedrock": bedrock, "bedrock-agentcore-control": control}))
    assert any(check.category == "MODEL_UNAVAILABLE_OR_UNAUTHORIZED" for check in model)
    assert control.calls == [("list_agent_runtimes", {"maxResults": 1})]


@pytest.mark.parametrize(("error", "category"), [
    (ClientError({"Error": {"Code": "UnrecognizedClientException", "Message": "auth"}}, "ListAgentRuntimes"),
     "AWS_AUTHENTICATION_FAILURE"),
    (ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "ListAgentRuntimes"),
     "AGENTCORE_ACCESS_DENIED"),
    (ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "ListAgentRuntimes"),
     "AGENTCORE_API_TRANSIENT"),
    (ClientError({"Error": {"Code": "InternalServerException", "Message": "failed"}}, "ListAgentRuntimes"),
     "AGENTCORE_API_TRANSIENT"),
    (EndpointConnectionError(endpoint_url="https://agentcore.invalid"), "AGENTCORE_API_UNAVAILABLE"),
])
def test_preflight_categorizes_control_plane_failures(error, category):
    control = FakeClient(operations=["CreateAgentRuntime", "UpdateAgentRuntime",
        "GetAgentRuntime", "ListAgentRuntimes"], errors={"list_agent_runtimes": error})
    checks = preflight.run(region="us-east-1", supervisor_model="profile-a", specialist_model="profile-b",
        session_factory=lambda **_: FakeSession(clients={"bedrock-agentcore-control": control}))
    assert any(check.category == category and not check.ok for check in checks)


def aws_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "operation")


@pytest.mark.parametrize(("identifier", "profile_result"), [
    ("us.vendor.profile-v1:0", {"status": "ACTIVE"}),
    ("bare-application-profile-id", {"status": "ACTIVE"}),
    ("arn:aws:bedrock:us-east-1:123456789012:inference-profile/example", {"status": "ACTIVE"}),
    ("arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/example", {"status": "ACTIVE"}),
])
def test_model_check_accepts_all_inference_profile_forms(identifier, profile_result):
    client = FakeClient()
    client.get_inference_profile = lambda **kwargs: profile_result
    assert preflight._model_check(client, identifier, "model").ok


@pytest.mark.parametrize("identifier", [
    "vendor.foundation-model-v1:0", "arn:aws:bedrock:us-east-1::foundation-model/vendor.model-v1:0"])
def test_model_check_handles_foundation_id_and_arn(identifier):
    client = FakeClient(errors={"get_inference_profile": aws_error("ResourceNotFoundException")})
    assert preflight._model_check(client, identifier, "model").ok
    if not identifier.startswith("arn:"):
        assert client.calls[0][0] == "get_inference_profile"
    assert any(call[0] == "get_foundation_model" for call in client.calls)


@pytest.mark.parametrize(("code", "category", "falls_back"), [
    ("ValidationException", "MODEL", True),
    ("AccessDeniedException", "MODEL_UNAVAILABLE_OR_UNAUTHORIZED", False),
    ("ThrottlingException", "MODEL_API_TRANSIENT", False),
    ("InternalServerException", "MODEL_API_TRANSIENT", False),
])
def test_ambiguous_model_fallback_and_error_categories(code, category, falls_back):
    client = FakeClient(errors={"get_inference_profile": aws_error(code)})
    result = preflight._model_check(client, "ambiguous-id", "model")
    assert result.category == category
    assert any(call[0] == "get_foundation_model" for call in client.calls) is falls_back


def deployment_args(package: Path, **changes):
    values = dict(profile="fixture-profile", region="us-east-1",
                  role_arn="arn:aws:iam::fixture-account:role/runtime", bucket="fixture-bucket",
                  s3_prefix="runtime", package=str(package), supervisor_model="supervisor-profile",
                  specialist_model="specialist-profile", build_id="build-fixture", runtime_id=None,
                  idle_timeout=120, execute=False, confirm="")
    return argparse.Namespace(**(values | changes))


def test_deployment_dry_run_makes_no_aws_client_and_is_parameterized(tmp_path):
    package = tmp_path / "package.zip"
    package.write_bytes(b"fixture")
    called = []
    result = deploy.execute(deployment_args(package), session_factory=lambda **kw: called.append(kw))
    assert result["mode"] == "dry-run" and called == []
    request = result["request"]
    assert request["agentRuntimeName"] == "operon_reasoner"
    assert request["agentRuntimeArtifact"]["codeConfiguration"]["runtime"] == "PYTHON_3_12"
    assert request["agentRuntimeArtifact"]["codeConfiguration"]["entryPoint"] == ["opentelemetry-instrument", "main.py"]
    assert request["environmentVariables"]["OPERON_BEDROCK_SUPERVISOR_MODEL_ID"] == "supervisor-profile"
    package_hash = hashlib.sha256(b"fixture").hexdigest()
    assert request["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]["prefix"] == f"runtime/{package_hash}.zip"
    assert len(request["clientToken"]) == 64


def test_deployment_execute_requires_exact_confirmation_before_aws(tmp_path):
    package = tmp_path / "package.zip"
    package.write_bytes(b"fixture")
    called = []
    with pytest.raises(ValueError, match="--confirm"):
        deploy.execute(deployment_args(package, execute=True), session_factory=lambda **kw: called.append(kw))
    assert called == []


class DeployS3:
    def __init__(self): self.uploads = []
    def upload_file(self, *args): self.uploads.append(args)


class DeployControl:
    def __init__(self, target):
        self.target, self.get_calls, self.update_calls = target, [], []
    def get_agent_runtime(self, **kwargs):
        self.get_calls.append(kwargs)
        return self.target
    def update_agent_runtime(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"agentRuntimeArn": self.target.get("agentRuntimeArn"), "status": "UPDATING"}


class DeploySession:
    def __init__(self, control, s3): self.control, self.s3 = control, s3
    def client(self, name): return self.control if name == "bedrock-agentcore-control" else self.s3


def update_target(runtime_id="runtime-1", name="operon_reasoner"):
    return {"agentRuntimeId": runtime_id, "agentRuntimeName": name,
            "agentRuntimeArn": f"arn:aws:bedrock-agentcore:us-east-1:fixture-account:runtime/{runtime_id}"}


def test_update_verifies_target_before_upload_and_refuses_unrelated_runtime(tmp_path):
    package = tmp_path / "package.zip"
    package.write_bytes(b"fixture")
    args = deployment_args(package, runtime_id="runtime-1", execute=True)
    args.confirm = deploy.confirmation(args, hashlib.sha256(b"fixture").hexdigest())
    s3, control = DeployS3(), DeployControl(update_target(name="unrelated"))
    with pytest.raises(ValueError, match="not the reviewed"):
        deploy.execute(args, session_factory=lambda **_: DeploySession(control, s3))
    assert control.get_calls == [{"agentRuntimeId": "runtime-1"}]
    assert s3.uploads == [] and control.update_calls == []


def test_confirmation_token_and_artifact_are_bound_to_exact_reviewed_inputs(tmp_path):
    package = tmp_path / "package.zip"
    package.write_bytes(b"fixture")
    args = deployment_args(package)
    first = deploy.execute(args)["request"]
    second = deploy.execute(args)["request"]
    assert first["clientToken"] == second["clientToken"]
    assert deploy.confirmation(args, hashlib.sha256(b"fixture").hexdigest()).startswith(
        "CREATE operon_reasoner build-fixture ")
    package.write_bytes(b"changed")
    changed_artifact = deploy.execute(args)["request"]
    assert changed_artifact["clientToken"] != first["clientToken"]
    args = deployment_args(package, specialist_model="changed-model")
    changed_config = deploy.execute(args)["request"]
    assert changed_config["clientToken"] != changed_artifact["clientToken"]
    assert changed_artifact["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]["prefix"].endswith(
        hashlib.sha256(b"changed").hexdigest() + ".zip")


def test_verified_update_uploads_content_addressed_artifact_and_uses_bound_token(tmp_path):
    package = tmp_path / "package.zip"
    package.write_bytes(b"fixture")
    args = deployment_args(package, runtime_id="runtime-1", execute=True)
    package_hash = hashlib.sha256(b"fixture").hexdigest()
    args.confirm = deploy.confirmation(args, package_hash)
    s3, control = DeployS3(), DeployControl(update_target())
    deploy.execute(args, session_factory=lambda **_: DeploySession(control, s3))
    assert s3.uploads == [(str(package), "fixture-bucket", f"runtime/{package_hash}.zip")]
    assert len(control.update_calls) == 1 and control.update_calls[0]["clientToken"]
    assert "agentRuntimeName" not in control.update_calls[0]


def test_smoke_tool_is_bound_to_backend_and_has_two_live_gates():
    source = (ROOT / "scripts/agentcore/smoke.py").read_text()
    assert "AgentCoreBackend(settings, client_factory=client_factory)" in source
    assert "backend.supervise" in source
    assert 'os.getenv("OPERON_LIVE_AWS") != "1"' in source
    assert "promotion._complete_run" not in source
    assert "promote_diagnosis" not in source
