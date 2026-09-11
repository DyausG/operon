# AgentCore Step 15B.2 preparation / Step 15B.3 runbook

These assets prepare one direct CodeZip runtime named `operon_reasoner`. They do not provision anything by themselves. AgentCore receives only Operon's bounded `ReasoningRequest`; its response remains advisory and is accepted only through application-side correlation, identity, schema, evidence, and authority checks. Approval, execution, outcome verification, incident state, and SQLite remain exclusively in the application.

## Prerequisites and configuration

- Python 3.12, `uv`, and an existing private S3 deployment bucket.
- An AWS identity explicitly selected by the operator, with separate deployment permissions. Scripts do not infer account IDs or create IAM/buckets.
- A pre-created runtime execution role using the templates under `scripts/agentcore/iam/`.
- Verified Bedrock model or inference-profile identifiers and their exact ARNs. Do not guess these values.

```text
OPERON_AGENTCORE_REGION=us-east-1
OPERON_AGENTCORE_RUNTIME_ARN=                         # only after deployment
OPERON_AGENTCORE_QUALIFIER=DEFAULT
OPERON_BEDROCK_SUPERVISOR_MODEL_ID=
OPERON_BEDROCK_SPECIALIST_MODEL_ID=
OPERON_RUNTIME_BUILD_ID=                             # immutable source/build identifier
```

The IAM templates require explicit substitution of `PARTITION`, `ACCOUNT_ID`, `REGION`, both model/inference-profile ARNs, both underlying foundation-model ARNs where a cross-region profile uses them, `RUNTIME_LOG_PREFIX`, `RUNTIME_ARN`, and `RUNTIME_ENDPOINT_ARN`. Validate rendered policies before creating them manually. The execution policy permits only Bedrock invocation plus scoped runtime logs, AgentCore-namespace metrics, and X-Ray telemetry. X-Ray, `cloudwatch:PutMetricData`, `logs:DescribeLogGroups`, and `logs:PutResourcePolicy` require `Resource: "*"` because those APIs do not support resource-level permissions; the metric namespace condition narrows its write. `PutResourcePolicy` is included only for unified AgentCore trace delivery. The invoker permits only invoke/stop on the selected runtime/endpoint and explicitly denies user-impersonation invocation.

## Build and read-only preflight

```bash
UV_CACHE_DIR=/tmp/operon-uv-cache uv run python scripts/agentcore/build_package.py
UV_CACHE_DIR=/tmp/operon-uv-cache uv run python scripts/agentcore/preflight.py --profile "$AWS_PROFILE"
```

The build installs the hash-locked `requirements.txt` generated from `requirements.in` under the exported application-lock constraints, resolves only Python 3.12 `aarch64-manylinux2014` wheels, and refuses identity-affecting version drift. It copies an explicit source allowlist, validates exact source-byte parity and the packaged ADOT console entry point, normalizes zip timestamps/modes, rejects databases/secrets/caches/tests, and prints a SHA-256. Regenerate the locks only intentionally with the commands recorded in their headers. The build contacts package indexes only if dependencies are not cached; it never contacts AWS. Preflight is read-only but does contact AWS: it reports configuration, caller identity, local AgentCore SDK operations, one `ListAgentRuntimes(maxResults=1)` control-plane reachability check, model/profile lookup/access, and package architecture. Failure categories distinguish missing config, authentication, AgentCore access denial, transient/API availability, model authorization/availability, and (with `--invocation-check`) an absent runtime ARN. It never invokes a model or runtime.

## Deployment

The default command only prints the exact plan and makes no SDK client:

```bash
uv run python scripts/agentcore/deploy.py --profile "$AWS_PROFILE" --role-arn "$EXECUTION_ROLE_ARN" \
  --bucket "$DEPLOYMENT_BUCKET" --supervisor-model "$OPERON_BEDROCK_SUPERVISOR_MODEL_ID" \
  --specialist-model "$OPERON_BEDROCK_SPECIALIST_MODEL_ID" --build-id "$OPERON_RUNTIME_BUILD_ID"
```

The dry run prints a `required_confirmation` bound to the operation, exact target, build ID, and package SHA-256. After reviewing it, copy that value exactly into the live form:

```bash
uv run python scripts/agentcore/deploy.py --profile "$AWS_PROFILE" --execute --confirm "$REQUIRED_CONFIRMATION" \
  --role-arn "$EXECUTION_ROLE_ARN" --bucket "$DEPLOYMENT_BUCKET" \
  --supervisor-model "$OPERON_BEDROCK_SUPERVISOR_MODEL_ID" \
  --specialist-model "$OPERON_BEDROCK_SPECIALIST_MODEL_ID" --build-id "$OPERON_RUNTIME_BUILD_ID"
```

This uploads to a content-addressed `<s3-prefix>/<package-sha256>.zip` key and creates the runtime with a deterministic request token. For an intentional update, also pass the already verified `--runtime-id`; the tool reads that ID first and refuses unless its name, ID, ARN region, and account match `operon_reasoner` and the reviewed role/region. Update confirmation includes the exact runtime ID. No lookup-by-name, replacement, polling, IAM mutation, bucket creation, endpoint mutation, or deletion occurs. A submission response/ARN is success; access errors, invalid role/model/artifact, or a non-ready runtime must be investigated with read-only control-plane calls before retrying.

## Live smoke

After the runtime is ready and preflight passes with `--invocation-check`:

```bash
OPERON_LIVE_AWS=1 uv run python scripts/agentcore/smoke.py --profile "$AWS_PROFILE" --execute
```

The smoke creates and deletes an isolated temporary fixture database, freezes a real diagnosis packet, invokes through `AgentCoreBackend`, and requires the normal untrusted-response validation path. It prints incident/run/snapshot/session correlation and a concise advisory result. It never completes the report, promotes diagnosis/intervention, requests approval, executes work, verifies an outcome, or closes an incident. Malformed, drifted, or foreign output fails closed.

## Rollback, cleanup, cost, and safety

Rollback the application first with `OPERON_REASONING_BACKEND=local` or `none`. AWS cleanup is deliberately manual: identify the exact runtime ID/version, inspect it, call `DeleteAgentRuntime` only for that target, then remove only the uploaded object/version from the named bucket. Delete IAM attachments/roles and the bucket only after checking for other users. None of these destructive operations is implemented by the scripts.

Runtime, Bedrock, CloudWatch/X-Ray, and S3 can incur charges. Run one bounded smoke, stop its session (the backend does this in `finally`), retain the 120-second idle timeout, inspect logs, then remove unused resources. Transaction Search/GenAI Observability enablement is a separate manual account-level Step 15B.3 action; it is not changed here.
