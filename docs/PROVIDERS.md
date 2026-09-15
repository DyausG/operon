# Model providers — the boundary between Operon and any AI vendor

Operon's reliability domain (incident lifecycle, evidence, promotion, governance,
approval, execution, outcome verification) never imports a vendor SDK. Everything a
model does for Operon passes through one small interface:

```
Operon domain / runtime          core/reliability, core/engine, core/reasoning
          |
     ModelProvider               core/providers/base.py
     /    |      \
 Gemini  Ollama  Bedrock         core/providers/{gemini,ollama,bedrock}.py
          +  NoProvider          core/providers/none.py   (truthful deterministic mode)
```

Provider choice is **independent from Operon's reliability logic**. Whatever model
reasons, the same evidence packet, trust validation, promotion gates, governance policy,
exact-hash approval and outcome verification apply.

## What the interface asks for

`ModelProvider` (see `core/providers/base.py`) is deliberately small:

| Method | Used by |
|--------|---------|
| `strands_model(options)` | `core.agents.runtime.StrandsRuntime` — supervisor and specialist agents |
| `generate_json(system, user)` | the Governance/Monitoring peer adapters (bounded JSON completions) |
| `describe()` / `test_connection()` | `/api/providers`, Settings → AI provider, `demo.sh` |
| `capabilities()` | capability chips (text, structured output, tool calling, streaming, image input, local/cloud) |
| `credential_status()` | configured/masked status only; never a value |
| `identity_locator()` | the non-secret endpoint/region frozen into a run's runtime identity |

Construction performs no I/O. Clients, sessions and credential lookups happen inside a
call, so importing Operon or selecting a provider never opens a socket.

## Selection and construction

`core/providers/registry.py` is the only place a vendor is chosen or built:

- `OPERON_AI_PROVIDER` = `auto` (default) | `none` | `gemini` | `ollama` | `bedrock`.
  `auto` picks the first *configured* cloud provider (Gemini key, then AWS credentials)
  and otherwise `none`. Legacy `SENTINEL_LLM_PROVIDER` (`deterministic` → `none`) and
  `POC_FORCE_DETERMINISTIC=1` are honoured.
- `get_registry().build(kind, role=None)` returns a cached provider. The `role` argument
  and the `roles` map are **reserved**: later Samsung PRISM work may assign a local,
  low-latency provider to a Fast Path and a stronger cloud provider to a Slow Path
  through this same factory. That routing is **not implemented** in Stage 0; there is
  one active provider for every run today.
- The reasoning backend (`OPERON_REASONING_BACKEND`: `none` | `local` | `packet` |
  `agentcore`) builds its Strands runtimes from the active provider. Unset resolves to
  `local` when a provider is configured and to `none` otherwise. `agentcore` is a remote
  runtime invoker with its own protocol and trust validation and remains Bedrock-only.

## Errors

Vendor exceptions never cross the boundary. Each adapter maps its SDK's failures onto
`ProviderError` with one of: `provider_not_configured`, `authentication_failed`,
`provider_unreachable`, `model_not_found`, `rate_limited`, `timeout`,
`unsupported_capability`, `provider_error`. Messages are redacted against known secret
values and bounded in length. Specialist invocation failures carry the code as
`stop_reason`; the supervisor records them as a truthful `MODEL_FAILED` escalation.

## Secrets

- Secrets stay server-side: environment variables, or a session-scoped value set through
  `PUT /api/providers/gemini` (loopback clients or `OPERON_TRUSTED_SUBMISSIONS=1` only).
- They are held as pydantic `SecretStr` in process memory, never serialized, never logged,
  never persisted, never returned by any endpoint and never placed in browser storage.
- AWS credentials are never handled by Operon at all; the SDK chain resolves them.
- No secure persistent secret store exists in this stage, so none was invented.

## No-provider mode

`NoProvider` is a first-class provider: it reports `configured=false`, empty capabilities
and raises `provider_not_configured` for any model use. The engine reports the supervisor
as awaiting a runtime with the reason, incidents wait in `INVESTIGATING`, and every
deterministic capability keeps working. Operon never fabricates reasoning.

## Adding a provider

1. Implement `ModelProvider` in `core/providers/<name>.py` (construction without I/O,
   normalized errors, honest capabilities, secret-free `describe()`).
2. Register the factory in `ProviderRegistry.__init__` and add the kind to
   `PROVIDER_KINDS` / `UPDATABLE_FIELDS`.
3. Add the option to `PROVIDER_KINDS` in `frontend/src/state/providers.js` and its fields
   to `ProviderSettings.jsx`.
4. Write offline tests with fakes (see `tests/test_providers.py`); tests never call a
   live service.
