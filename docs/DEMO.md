# Operon demo guide

Operon is an autonomous reliability platform for industrial systems. An ML health model
scores a simulated plant floor, opens **durable incidents** when risk crosses the action
gate, lets model-backed specialist agents *advise*, and keeps every authoritative step
(diagnosis, intervention, governance, human approval, execution, outcome verification)
inside the application. Agents reason; the application owns authority.

This guide is the fastest path for a reviewer. Provider setup details live here so the
README stays short.

## Prerequisites

| Need | Required? | Notes |
|------|-----------|-------|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | yes | creates the Python 3.12 environment and installs dependencies |
| Node.js ≥ 18 + npm | no | only for `--dev` (hot reload) or `--rebuild-frontend`; the built dashboard is committed |
| A model provider | no | Operon starts without one (deterministic mode); Gemini, Ollama or Bedrock are optional |
| AWS account | no | never required |

## Fastest path

```bash
./demo.sh
```

The launcher detects the repository root, checks `uv` (and Node when needed), runs
`uv sync`, reuses the committed dashboard bundle, reports the AI provider status without
printing secrets, starts the backend (which serves the built portal), waits for
`/api/health`, prints the portal URL and stops every child process on **Ctrl+C**.

Useful flags:

```bash
./demo.sh --check              # environment + provider status only; starts nothing
./demo.sh --probe              # also runs the provider connection test (network)
./demo.sh --dev                # adds the Vite dev server on :5173 (needs Node)
./demo.sh --rebuild-frontend   # rebuild frontend/dist first (needs Node)
./demo.sh --reset-demo         # fresh demo database
./demo.sh --open               # open the portal in your browser when ready
POC_PORT=8010 ./demo.sh        # use another backend port
```

The launcher never installs system packages or Ollama and never pulls a model.

## Manual startup

```bash
uv sync
uv run python run.py            # http://127.0.0.1:8000/ ; opens a browser tab (use --no-browser to skip)
```

Dashboard development (optional):

```bash
cd frontend && npm install && npm run dev      # :5173, proxies /api and /ws to :8000
npm run build                                   # refresh the committed dist/ bundle
```

Windows users can keep using `install.bat` and `run.bat`.

## Portal and sign-in

Open the printed URL (default `http://127.0.0.1:8000/`). The login page is a **demo
session** that exists only in your browser: any well-formed email and a password of at
least 8 characters signs you in as a maintenance approver. The backend has no
authentication layer; approvals still require the exact requirement, intervention hash
and revision the lifecycle service demands.

## No-provider (deterministic) mode

With nothing configured Operon still runs everything that does not need a model:
telemetry simulation, ML health scoring, incident admission, baseline evidence, governance
policy, human approval, governed execution, outcome verification and the guided demo.
Model-backed reasoning (the Reliability Supervisor and specialists) reports itself as
**unavailable**; real incidents wait in `INVESTIGATING`. Operon never substitutes a
fabricated reasoning result. The header chip reads "No model provider · standby" and
Settings → AI provider explains the state.

## Google Gemini

1. Create a key at <https://aistudio.google.com/apikey>.
2. Put it in the server environment (never in the browser): `cp .env.example .env`,
   then set `GEMINI_API_KEY=...` and optionally `OPERON_GEMINI_MODEL=gemini-flash-latest`.
   Setting `OPERON_AI_PROVIDER=gemini` is optional; `auto` picks Gemini when a key exists.
3. Restart (`./demo.sh`). The launcher prints "Google Gemini selected".
4. In the portal, **Settings → AI provider → Test connection** validates the key and model
   using a metadata call (no generation). Capabilities: text, structured output, tool
   calling, streaming, image input.

You can also paste a key for the *current server process only* in Settings (loopback
clients only). It is held in server memory, never written to disk, never returned by the
API and never stored in the browser.

## Ollama / local models

1. Install and start Ollama yourself (<https://ollama.com>); Operon never installs it.
2. Pull a model you can afford to run, for example `ollama pull qwen2.5:7b` or
   `ollama pull llama3.1:8b` (any tool-capable chat model works; small models may
   struggle with the structured supervisor output, which surfaces as a truthful
   escalation rather than a fake result).
3. Configure: `OPERON_AI_PROVIDER=ollama`, `OPERON_OLLAMA_MODEL=qwen2.5:7b`, and
   `OPERON_OLLAMA_BASE_URL=http://127.0.0.1:11434` if not default. Or pick the provider in
   Settings, type the model, save and **Test connection**.
4. The connection test reports "Ollama is not running" or "model not installed" (with the
   installed list and the exact `ollama pull` hint) as normalized errors, and shows which
   capabilities the pulled model declares (tool calling, vision).

## AWS Bedrock

1. Enable a model or cross-region inference profile under **Bedrock → Model access**.
2. Provide credentials by any standard AWS method (`aws configure`, `AWS_PROFILE`, a role,
   or keys in `.env`). Set `AWS_REGION` and `BEDROCK_MODEL_ID` (or
   `OPERON_BEDROCK_SUPERVISOR_MODEL_ID` / `OPERON_BEDROCK_SPECIALIST_MODEL_ID`).
   `OPERON_AI_PROVIDER=bedrock` forces it; `auto` picks Bedrock when credentials are present
   and no Gemini key is set.
3. **Test connection** calls STS and the Bedrock control plane to confirm credentials and
   model visibility. The remote AgentCore runtime is a separate backend
   (`OPERON_REASONING_BACKEND=agentcore`, see `docs/AGENTCORE_DEPLOYMENT.md`).

Credentials are read only by the server through the AWS SDK; the API exposes their
*source* (environment, profile, role, file), never a value.

## Running the guided demo

The **guided demo** is a scripted, clearly labelled *SIMULATED* walkthrough of the whole
lifecycle that needs no provider. Start it from the Engine menu in the header, from
**Settings → Plant & system → Start guided demo**, or with
`curl -X POST localhost:8000/api/demo/scenario -H 'Content-Type: application/json' -d '{"equipment_id":"AC-COMP-01"}'`.
Approve the plan when the approval card appears and watch execution, observation and
verified closure. **Reset engine** returns to the live simulation.

## Recommended reviewer walkthrough (about 5 minutes)

1. `./demo.sh` → open the portal → sign in.
2. **Settings → AI provider**: note the provider choice cards, the honest "not configured"
   states, capability chips, and Test connection. Select Ollama or Gemini if you have one.
3. **Dashboard**: fleet risk, action gate, KPI deck.
4. Start the **guided demo**; follow the incident on the **Incidents** and **Operon Agent**
   pages: evidence ledger with provenance, advisory lane vs. authoritative records.
5. Approve the exact work package (hash and revision shown), then watch OBSERVING →
   verified recovery → CLOSED.
6. With a provider configured, let a live incident open (risk ≥ 0.80) and observe the
   supervisor run and its normalized outcome in the agent workspace.

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| `uv is required` | install uv, reopen the shell |
| `port 8000 ... already in use` | stop the other instance or `POC_PORT=8010 ./demo.sh` |
| "Ollama is not running or not reachable" | start Ollama (`ollama serve`) or fix `OPERON_OLLAMA_BASE_URL` |
| "model ... is not installed" | `ollama pull <model>` or pick an installed one from the chips shown after the test |
| Gemini `authentication_failed` | the key is invalid or restricted; `model_not_found` means the model id is wrong for your key |
| Bedrock `authentication_failed` / `model_not_found` | credentials expired, IAM denies, or the model is not enabled in that region |
| Supervisor "awaiting runtime" | no configured provider, or `OPERON_REASONING_BACKEND=none`; the reason is shown in Settings |
| Backend exits early | the launcher prints the last log lines; logs live in the temp directory it names |
| Dashboard build missing and no Node | the committed `frontend/dist` should exist; `git checkout frontend/dist` restores it |

## Stopping services

Press **Ctrl+C** in the launcher terminal. It sends SIGTERM to every child process group
(backend, and the dev server with `--dev`), waits, then force-kills stragglers and prints
the log directory. With manual startup, Ctrl+C the `run.py` process (and the Vite process
if you started one).
