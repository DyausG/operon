<div align="center">
  <img src="docs/banner.svg" alt="Operon — Autonomous Reliability Operations for Industrial Systems" width="100%">
</div>

# Operon

**Autonomous Reliability Operations for Industrial Systems**

A live, self-contained demonstration of the **governed agentic loop** for industrial
reliability. An ML health model — trained on the public **UCI AI4I 2020** benchmark —
continuously scores a simulated plant floor of eight machines. When failure risk crosses the
action gate, Operon opens a **durable incident** and runs it through an enforced lifecycle:
deterministic baseline evidence is collected, **Strands specialist agents** (diagnostic,
engineering, operations, critic, planner) reason under a Reliability Supervisor on the
**model provider you choose** (Google Gemini, a local Ollama model, or AWS Bedrock — or none,
in a truthful deterministic mode), and the application — never the model — promotes a diagnosis, validates an
intervention, evaluates deterministic governance, and issues an approval requirement. A human
approves the **exact** work package by hash. Execution is claimed and receipted, the asset is
observed, and the incident closes only when the application **verifies recovery** from
persisted post-intervention evidence. The dashboard quantifies recovered value and OEE lift
against configured economics.

The governing invariant is enforced by distinct records:
**prediction ≠ diagnosis ≠ intervention ≠ approval ≠ execution ≠ outcome.**
Agents reason; the application owns authority.

> **Vendor-neutral portfolio project.** The bundled AI4I 2020 dataset is synthetic and
> licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); the remaining
> demo data is synthetic. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for
> attribution. This POC is not affiliated with, endorsed by, or built for any specific company.

![architecture](https://img.shields.io/badge/stack-FastAPI%20%2B%20React%20%2B%20Strands%20%2B%20Gemini%20%7C%20Ollama%20%7C%20Bedrock-7c8cff)

---

## Run the Operon Demo

```bash
git clone <repository-url> operon && cd operon
./demo.sh            # checks uv/Node, syncs deps, starts Operon, prints the portal URL; Ctrl+C stops everything
```

Then open **http://127.0.0.1:8000/**, sign in with any email (demo session, browser-only) and
press **Start Guided Demo**. No cloud account, API key or AWS credentials are required: without a
provider Operon runs in a deterministic, demo-safe mode and says so. To enable model-backed
reasoning, configure **Google Gemini**, a local **Ollama** model or **AWS Bedrock** in
**Settings → AI provider** or through `.env` — the full guide, provider setup, reviewer
walkthrough and troubleshooting are in **[docs/DEMO.md](docs/DEMO.md)**.

---

## Architecture

```mermaid
flowchart LR
    S[8 machines<br/>simulated telemetry] --> M[ML health model<br/>UCI AI4I 2020]
    M -->|risk ≥ 0.80| O[OPEN incident<br/>baseline evidence]
    O --> AG{Reliability Supervisor<br/>Strands · Gemini | Ollama | Bedrock}
    AG -->|advisory reports| PR[Application promotion<br/>diagnosis · intervention]
    PR --> G[Deterministic governance]
    G --> H{Human approval<br/>exact hash}
    H -->|APPROVE| EX[Governed execution<br/>claim → receipt]
    EX --> OB[OBSERVING]
    OB -->|verified recovery| C[CLOSED]
    OB -->|not recovered| O
```

Every phase change is a journaled SQLite transaction. The full state graph
(`OPEN → INVESTIGATING → AWAITING_EVIDENCE → DIAGNOSIS_VALIDATED → PLANNING →
INTERVENTION_VALIDATED → AWAITING_APPROVAL → READY → EXECUTING → OBSERVING → CLOSED`, plus
`ESCALATED`, `EXECUTION_FAILED`, `CANCELLED`) lives in `core/reliability/state.py`; the design
is documented in [docs/OPERON_ARCHITECTURE.md](docs/OPERON_ARCHITECTURE.md) and
[docs/STRANDS_FOUNDATION.md](docs/STRANDS_FOUNDATION.md).

## Quick start (Windows, ~2 minutes)

Linux/macOS/WSL: `./demo.sh` (see [docs/DEMO.md](docs/DEMO.md)). Windows:

Uses **[uv](https://docs.astral.sh/uv/)** for a reproducible Python env (pins Python 3.12).
The React dashboard is **pre-built and committed**, so you need **no Node.js** to run it.

1. Install uv once: `irm https://astral.sh/uv/install.ps1 | iex`
2. Double-click **`install.bat`** (creates the env; downloads Python 3.12 if needed).
3. Double-click **`run.bat`**. Your browser opens the dashboard automatically.

Manual / cross-platform:

```bash
git clone <repository-url> operon
cd operon
uv sync                    # create .venv + install deps
uv run python run.py       # trains model on first run, serves http://127.0.0.1:8000/
```

The fleet simulation starts with the server and runs **fully offline** — no cloud account
required. Press **Start Guided Demo** in the header to replay a reproducible, deterministic
telemetry and failure scenario through Operon's real incident lifecycle; with a provider
configured its reasoning runs on that provider. Without a reasoning backend configured,
real incidents still open and collect baseline evidence, but they wait in `INVESTIGATING`
because no specialist can run; Operon never substitutes a silent fallback for reasoning.

Normal relaunches preserve the SQLite database. Use **Reset** in the dashboard, or launch
with `uv run python run.py --reset-demo`, when you explicitly want a fresh run.

---

## Turning on live reasoning (optional)

Specialist and supervisor reasoning is built on the **Strands Agents SDK** (pinned
`strands-agents==1.54.0`) over a **provider-agnostic model layer** (`core/providers`, see
[docs/PROVIDERS.md](docs/PROVIDERS.md)). Pick the provider with `OPERON_AI_PROVIDER` or in
**Settings → AI provider**; `auto` (default) uses the first configured cloud provider and
otherwise the truthful no-provider mode:

| Provider | Needs | Notes |
|----------|-------|-------|
| `none` | nothing | deterministic monitoring, incidents, governance, approvals and the Guided Demo; model reasoning reports *unavailable* |
| `gemini` | `GEMINI_API_KEY` (server-side) | configurable model, rate-limited free-tier friendly client |
| `ollama` | a running Ollama + a pulled model | local open-source models; Operon never installs Ollama or pulls models |
| `bedrock` | AWS credentials + Bedrock model access | the original Step 15 path, now optional; never required to start |

The reasoning backend is selected with `OPERON_REASONING_BACKEND` and builds its Strands
runtimes from the active provider:

| Value | What runs | Needs |
|-------|-----------|-------|
| `none` | No reasoning; incidents wait in `INVESTIGATING` | nothing (default without a provider) |
| `local` | Strands supervisor in-process, holding the evidence service | a configured provider (default when one is configured) |
| `packet` | The remote request/response contract executed in-process — offline parity for AgentCore | a configured provider |
| `agentcore` | The same contract invoked on a deployed **Bedrock AgentCore Runtime** | a deployed runtime (Bedrock-only, see below) |

Whatever the provider or backend, its output is **advisory**. Every response is re-validated
against the frozen run snapshot (protocol version, correlation, code/prompt/schema identity,
schema, citations) before the application decides whether anything is promoted. A provider
failure is normalized (`provider_not_configured`, `authentication_failed`,
`provider_unreachable`, `model_not_found`, `rate_limited`, `timeout`, …), persists an escalated
audit report and leaves the incident phase unchanged. Secrets stay server-side: the
configuration API and the portal only ever see configured/masked status.

Provider setup steps (Gemini key, Ollama model, AWS credentials and model access) are in
[docs/DEMO.md](docs/DEMO.md); environment variables are documented in `.env.example`.

### AWS Bedrock AgentCore — remote reasoning runtime (implemented, not live-validated)

The repository contains the application side of an AgentCore deployment:
`core/reasoning/agentcore.py` (the `bedrock-agentcore` invoke/stop client with bounded
streaming reads and error mapping), `agentcore_app/main.py` (the `BedrockAgentCoreApp`
entrypoint that runs the supervisor over a bounded evidence packet with **no** database or
authority access), and `scripts/agentcore/` (offline CodeZip builder, read-only preflight,
dry-run-by-default deploy, double-gated live smoke, IAM templates). Configure
`OPERON_REASONING_BACKEND=agentcore` plus `OPERON_AGENTCORE_RUNTIME_ARN`,
`OPERON_AGENTCORE_REGION` and both `OPERON_BEDROCK_*_MODEL_ID` values; the runbook is
[docs/AGENTCORE_DEPLOYMENT.md](docs/AGENTCORE_DEPLOYMENT.md). Bucket/IAM provisioning,
readiness polling, teardown and observability enablement are deliberately **manual**, the
tests use fake clients only, and no live AgentCore run is recorded in this repository. A
deferred-evidence loop across the remote boundary is planned, not implemented: remote
evidence requests park the incident in `AWAITING_EVIDENCE`.

Diagnosis promotion also requires a **trusted technical confirmation** (an independent
inspection record), and a draft intervention requires a trusted resource confirmation and
work-package binding. The HTTP endpoints that accept those submissions are disabled unless
`OPERON_TRUSTED_SUBMISSIONS=1`, because the server has no authentication layer.

---

## Deploy a public demo

The whole app is a single container (FastAPI + the pre-built dashboard), so it drops onto
any container host. An included **Render Blueprint** (`render.yaml`) provides the service
configuration.

- **Render** — *New → Blueprint → pick this repository*. Free tier, WebSockets supported.
- **Railway / Fly.io** — both auto-detect the `Dockerfile`; no extra config needed.
- **Locally** — `docker build -t operon . && docker run -p 8000:8000 operon`

The hosted demo sets `POC_FORCE_DETERMINISTIC=1` — no credentials, no cost, no shared keys —
so it serves the offline fleet simulation and the guided SIMULATED demo. To run live
Strands reasoning in a deployment, set `POC_FORCE_DETERMINISTIC=0` and add a provider's
environment variables (`GEMINI_API_KEY`, or `AWS_*` + `BEDROCK_MODEL_ID`) in the host's
dashboard; see `.env.example`. On free tiers the service sleeps when idle and cold-starts in
~30 s.

---

## The 90-second Guided Demo

Press **Start Guided Demo** (header). The Guided Demo Scenario is a reproducible,
deterministic telemetry and failure progression on the seeded simulator (seed 7, one
asset degrading on a fixed ramp toward its class's failure mode) plus clearly labelled
**SIMULATED** trusted inputs (inspection, resources). Everything else is the real
product: a durable incident is admitted from the persisted model signal, the configured
**reasoning backend** runs the Reliability Supervisor and specialists over the frozen
evidence packet, and promotion, governance, exact human approval, governed execution and
outcome verification are the ordinary services. The scenario is deterministic; the
reasoning is whatever you configured:

| Provider in Settings | What reasons on the Guided Demo incident | What the portal shows |
|----------------------|------------------------------------------|-----------------------|
| Gemini / Ollama / Bedrock | the real Strands supervisor and specialists on that provider; their output becomes the hypotheses, diagnosis and reviews | `Model · <provider> · <model>`, `live_model true`, run snapshots frozen with the provider and model id |
| none | the explicitly labelled **deterministic advisory** (`backend deterministic`, no model call is made) so the workflow remains demonstrable | `No model · deterministic advisory`, `live_model false`, `provenance SIMULATED` |

A provider failure (unreachable Ollama, a model without tool support, a bad key) ends
the scenario as **failed** with the normalized provider error; no advisory text is ever
substituted for reasoning that did not happen. Changing the provider in Settings applies
to the next Guided Demo and the next live incident without a restart.

1. **Signal.** `AC-COMP-01` (compressor) climbs from 14 % to 86 % failure risk. Crossing the
   **80 % action gate** opens incident `DEMO-INCIDENT-01`: *prediction, not cause*.
2. **Investigate.** Baseline evidence is collected, a diagnosis run delegates to the
   diagnostic specialist and critic, and the incident parks in `AWAITING_EVIDENCE` until a
   simulated technician inspection arrives. Only then is a diagnosis **promoted**.
3. **Plan and validate.** A work-package binding produces a draft intervention; engineering,
   operations, critic and planner advisories review the exact draft; the application
   promotes it and issues an approval requirement bound to the intervention hash.
4. **Human-in-the-loop.** The scenario stops at `AWAITING_APPROVAL` — no timer or callback can
   approve. Click **Approve exact plan & dispatch** (about 42 s in). The call carries the
   exact `requirement_id`, `intervention_id`, `intervention_hash` and `context_revision`.
5. **Execute, observe, verify.** A work order and execution receipt appear, the incident
   enters `OBSERVING`, recovery samples accumulate against the frozen observation plan, and
   a `VERIFIED_RECOVERY` outcome closes the incident (about 33 s). The impact bar shows the
   intervention's estimated avoided loss. **Reject** instead and the incident is escalated for
   human follow-up, exactly as on any live incident.

Use **Reset** (top-right) to run it again. The live simulator behind the Guided Demo stages
four degradations — `AC-COMP-01` (power), `CNC-MILL-07` (overstrain), then the pumps
`HYD-PUMP-03` and `COOL-PMP-09` on the same heat-dissipation trajectory — and its response
to a confirmed work package is profile-driven (recovers or persists), so verification can
also report `NOT_RECOVERED` (back to investigation) or `REGRESSED` (escalated).

**API surface.** The dashboard talks to `server/main.py` over REST + a `/ws` WebSocket:
`GET /api/state`, `GET /api/incidents/{id}` (lifecycle projection + read model),
`POST /api/approve|reject/{equipment_id}` and `POST /api/incidents/{id}/approval` (exact
approval intent required), `/execute`, `/outcome` (deterministic verification, no body),
`/confirmations/technical`, `/confirmations/resource` and `/drafts` (trusted, flag-gated),
`POST /api/demo/scenario`, `POST /api/reset`, `/api/start`, `/api/stop`, `GET /api/health`.

> **Legacy path.** The original proposal-first demo (agent drafts a plan on threshold
> crossing, approval commits it immediately) is deprecated compatibility code: run it with
> `OPERON_LEGACY_DEMO=1`. Its artifacts carry no promotion lineage and are refused by the
> authoritative lifecycle.

---

## What's inside

```text
operon/
  demo.sh                            one-command reviewer launcher (docs/DEMO.md)
  run.py / run.bat / install.bat     launcher + first-time setup (uv)
  pyproject.toml / uv.lock           reproducible Python env (3.12)
  .env.example                       provider (Gemini / Ollama / Bedrock) + AgentCore + tuning template
  data/
    ai4i2020.csv                     UCI AI4I 2020 dataset (public benchmark)
  core/                              UI-agnostic domain logic (pure Python)
    config.py       thresholds, economics, reasoning-backend selection (providers decide the model)
    providers/      provider-agnostic model layer: ModelProvider boundary, registry,
                    Gemini / Ollama / Bedrock adapters, truthful no-provider mode, normalized errors
    dataset.py      AI4I loader + feature engineering (power, ΔT, overstrain)
    model.py        GradientBoosting: P(failure) head + failure-mode head
    db.py           SQLite semantic model (governed tables)
    migrations/     001–007: incidents, governed execution, promotion,
                    lifecycle, dependency-scoped freshness, outcome verification
    seed_data.py    fleet master data: 8 assets, 4 failure modes, crew, parts
    simulator.py    multi-equipment telemetry, staggered failures, intervention response
    reliability/    the authoritative incident lifecycle: state graph + append-only
                    repository, signal admission, baseline evidence, provenance +
                    dependency-scoped freshness, promotion boundary, deterministic
                    governance, approval, execution claims/receipts, outcome policy
    agents/         Strands specialists + Reliability Supervisor (advisory contracts)
    reasoning/      backend seam: local | packet | agentcore, packet protocol, trust checks
    demo_scenario.py deterministic Guided Demo Scenario inputs + deterministic advisory (no model)
    services/       swappable capability layer: 7 interfaces (5 tools + 2 peers),
                    SENTINEL_*_ADAPTER registry, adapters local/mcp/a2a/gemini_peers
    tools.py        thin facade over services/
    agent.py        legacy proposal agent + triage helpers (OPERON_LEGACY_DEMO)
    engine.py       tick loop: scoring, admission, lifecycle progression, projections
  server/main.py    FastAPI — REST + WebSocket; serves the built dashboard
  server/providers_api.py  /api/providers: status, select, configure, test (no secrets returned)
  mcp_app/server.py FastMCP server — governed tools over MCP
  a2a_app/server.py A2A peer server — Governance + Monitoring agents
  agentcore_app/    Bedrock AgentCore Runtime entrypoint + hash-locked requirements
  scripts/agentcore/  build, preflight, deploy, smoke, IAM policy templates
  docs/             DEMO, PROVIDERS, OPERON_ARCHITECTURE, STRANDS_FOUNDATION, AGENTCORE_DEPLOYMENT, EXTENDING
  frontend/         React + Vite dashboard (source + committed dist/)
  tests/            32 offline test modules (network guarded)
```

Every number a stakeholder might challenge lives in `core/config.py` and is surfaced in the
UI, so the business case is transparent and editable.

---

## Building on it — the services layer

Operon doesn't call external systems directly; it calls **service interfaces**, each
satisfied by a **swappable adapter** (ports-and-adapters). The repo ships a local,
SQLite-backed adapter for each so it runs offline, but you can point any service at your
real systems — a CMMS (SAP PM / IBM Maximo), a warehouse system, an MES scheduler, a paging
service — without touching the lifecycle:

| Service | Operon uses it to… | Swap with |
|---------|--------------------|-----------|
| `InventoryService`    | check spare-parts stock              | `SENTINEL_INVENTORY_ADAPTER` |
| `WorkforceService`    | find a certified technician          | `SENTINEL_WORKFORCE_ADAPTER` |
| `SchedulingService`   | reserve a planned window             | `SENTINEL_SCHEDULING_ADAPTER` |
| `CmmsService`         | commit a **repair work package**     | `SENTINEL_CMMS_ADAPTER` |
| `NotificationService` | raise alerts, page technicians       | `SENTINEL_NOTIFICATIONS_ADAPTER` |
| `GovernanceService`   | peer review of a plan (legacy path)  | `SENTINEL_GOVERNANCE_ADAPTER` |
| `MonitoringService`   | flag systemic patterns across alerts | `SENTINEL_MONITORING_ADAPTER` |

On the authoritative path the work package — work order + reserved spares + labor booking +
schedule hold + dispatch notification — is committed by **governed execution**, not by
approval: the lifecycle claims the approved intervention in one transaction, hands the CMMS
adapter a sealed execution authorization, and records a receipt against the claim identity.
A `CONFIRMED` receipt means the commit happened, not that the asset recovered. The local
adapter writes to the same SQLite database; notifications are recorded, not sent.

The same tool capabilities are also exposed over **MCP** (Model Context Protocol) by a
FastMCP server, including `execute_governed_intervention`, so external hosts and agents can
use them:

```bash
uv run python -m mcp_app.server            # stdio (e.g. for Claude Desktop)
uv run python -m mcp_app.server --http      # streamable-http on :8100
```

There's an `mcp` adapter behind every tool interface — set `SENTINEL_<DOMAIN>_ADAPTER=mcp`
and Operon reaches its own capabilities *over MCP* (self-spawned, no port), with `local`
still the offline default.

Two capabilities are **peer agents**, not tools — a **Governance** agent (APPROVE /
CONDITIONS / VETO on a proposed plan) and a **Monitoring** agent (systemic patterns across
alerts). Their default adapter is `llm`: they reason with Gemini when a key is set and fall
back to deterministic engines otherwise; set `SENTINEL_GOVERNANCE_ADAPTER=local` to pin the
deterministic path. Monitoring feeds the triage broadcast; the Governance peer is consulted
only on the legacy proposal path — the authoritative lifecycle uses the deterministic policy
in `core/reliability/governance.py`. Both peers can be reached over the **A2A** protocol:

```bash
uv run python -m a2a_app.server            # Governance + Monitoring peers on :8200
# then: SENTINEL_GOVERNANCE_ADAPTER=a2a  SENTINEL_MONITORING_ADAPTER=a2a
```

**A2A is for agents; MCP is for tools** — both are transports behind the same
service interfaces. See **[docs/EXTENDING.md](docs/EXTENDING.md)** for the adapter
recipe, MCP setup, and A2A peers.

---

## Portal routes

The dashboard is a multi-page portal: `/login` (browser-local demo session; the host has no
authentication layer) and `/app/{dashboard,machines,incidents,agent,maintenance,analytics,
activity,notifications,profile,settings}`. FastAPI serves the SPA for those paths so deep
links survive a refresh. Light and dark themes are persisted in the browser.

## Editing the dashboard (needs Node ≥ 18)

The committed `frontend/dist/` means the app runs without Node. The dashboard (React 18,
Recharts, Framer Motion, Vite) shows the fleet grid with risk sparklines, the predictive
signal chart with the action gate, an incident queue, and an incident command view: the
lifecycle strip, evidence ledger with provenance, agent runs and delegations, the promoted
diagnosis and intervention, the approval card bound to the intervention hash, the
execution → observe → verify outcome card, and the event journal. To change the UI:

```bash
cd frontend
npm install
npm run dev        # hot-reload at :5173, proxies API+WS to the backend on :8000
npm run build      # rebuild the committed dist/ bundle
```

Run `uv run python run.py` in another terminal so the dev server has a live backend.

---

## Tests

```bash
uv run pytest                    # full suite
uv run pytest -m "not integration"   # fast unit/functional only (no subprocess/server)
```

The suite (32 modules, 785 tests) runs entirely offline behind a socket guard: no live
Bedrock, Gemini, Ollama or AgentCore calls. It covers the incident state graph, admission and
baseline evidence, provenance and dependency-scoped freshness, promotion (failure injection,
concurrent retries, stale sources, legacy exclusion), governance, exact approval, execution
claims and receipts, outcome verification (execution never closes, pre-boundary samples do
not count, recovered / not-recovered / regressed / inconclusive), the engine tick and
recovery, the Strands specialists and supervisor with in-test model doubles, the reasoning packet
protocol and trust checks, the provider layer (selection, no-provider mode, mocked Gemini,
Ollama and Bedrock adapters, normalized errors, capabilities, the configuration API's secret
non-disclosure, connection tests), the `demo.sh` launcher, the AgentCore backend and
deployment tools with fake clients, the Guided Demo Scenario (deterministic advisory, injected model double,
truthful provider failure, Settings switch, reproducibility), the services layer, and the peer policies. The `integration` tests exercise a
real **MCP** round-trip (self-spawned stdio server, through governed execution) and a real
**A2A** round-trip (peer server in-process via ASGI). Tests use a throwaway SQLite file.

---

## The ML model

Trained on the **AI4I 2020** dataset (10,000 rows, 3.4 % failure rate) with two heads:

- **Failure head** — GradientBoosting classifier → P(failure). Held-out **AUC ≈ 0.97**.
- **Mode head** — classifies the specific failure mode (Tool-Wear / Heat-Dissipation /
  Power / Overstrain). Held-out accuracy **≈ 0.96**.

Three engineered features (mechanical power, process–air ΔT, overstrain = tool-wear × torque)
map directly onto the documented AI4I failure physics, and ablation-based attribution
explains every signal ("dominant driver is …"). The model retrains in ~10 s on first run and
is cached to `data/health_model.joblib`. Its score is a **signal**, never a diagnosis: it
admits incidents at the 0.80 gate and, with the same 0.45 / 0.80 bands, is the persisted
evidence the outcome policy reads to verify recovery.
