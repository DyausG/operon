# OPERON V2 development workflow

## What `overhaul/v2` is

`overhaul/v2` is the long-lived development line for the next generation of OPERON: the UX and
product redesign, frontend architecture, design system, capability upgrades and backend/agent
improvements. It branched from `main` at `0594d16` (Merge pull request #11, 2026-09-17), the last
commit pushed before the post-submission overhaul began.

```text
main          0594d16  stable / submitted generation (frozen for V2 purposes)
  └─ overhaul/v2       OPERON V2 development line
       ├─ v2/<topic>   short-lived feature branches, merged back into overhaul/v2
       └─ ...
```

## Why the submitted version is frozen

OPERON has been submitted to hackathons, and judges and reviewers must be able to reproduce what
was submitted. So:

- **`main` is not the V2 development branch.** No V2 work is committed or merged to `main` unless
  the project owner explicitly decides so. `main` is also protected by the "Protect main" ruleset
  (pull request required, no force-push, no deletion).
- **Submission tags are immutable.** Once created, a `submission-*` tag is never moved, deleted or
  re-pointed.
- **The hosted demo follows the default branch.** `render.yaml` sets `autoDeploy: true`, so keeping
  V2 off `main` also keeps any Render deployment of `main` on the submitted generation.

## Submission tags

**Not created yet.** The exact submitted commit(s) can't be proven from repository evidence. The
candidates are:

| Candidate | Evidence |
|---|---|
| `4c00806` | Merge of PR #4 "Backend freeze", whose description reads "Final backend freeze before hackathon submission" (2026-09-14). |
| `0594d16` | Current `main`; the last push to the repository (2026-09-17). It includes the Samsung PRISM Stage 1/2 work, while the README states the Theme 5 adaptation is unfinished. |

Once the owner confirms which commit went to which hackathon, create one annotated tag per
submission, for example:

```bash
git tag -a submission-<hackathon>-<yyyymmdd> <sha> -m "Frozen OPERON submission to <hackathon>"
git push origin submission-<hackathon>-<yyyymmdd>
```

All candidates are ancestors of (or equal to) `overhaul/v2`'s base, so adding tags later doesn't
affect V2.

## Branch naming

Base substantial work on `overhaul/v2` and merge back into `overhaul/v2`, never directly into
`main`:

```text
v2/design-system   v2/app-shell   v2/dashboard   v2/machines   v2/incidents
v2/agent-workspace v2/maintenance v2/responsive  v2/accessibility
```

```bash
git switch overhaul/v2 && git pull
git switch -c v2/<topic>
# ...work, commit...
git push -u origin v2/<topic>   # then merge into overhaul/v2
```

## Switching between the submitted and V2 versions

```bash
git switch main          # stable / submitted generation
git switch overhaul/v2   # V2 development
# a confirmed submission snapshot (detached, read-only use):
git switch --detach submission-<hackathon>-<yyyymmdd>
```

Runtime state (`.venv/`, `data/poc.db`, `data/health_model.joblib`) is git-ignored and shared
between checkouts. Use `--reset-demo` (or the in-app Reset) when you need a fresh database after
switching.

## Running and viewing V2

The commands are the same as for `main` (see `docs/DEMO.md`):

```bash
./demo.sh                                   # one-command launcher → http://127.0.0.1:8000/
# or manually:
uv sync && uv run python run.py --no-browser
# deterministic, no model provider (no credentials needed):
OPERON_AI_PROVIDER=none OPERON_REASONING_BACKEND=none uv run python run.py --no-browser
```

Sign in with any well-formed email and a password of 8+ characters (browser-local demo session).

The frontend dev server (hot reload on `:5173`, proxying to the backend on `:8000`):

```bash
cd frontend && npm install && npm run dev
npm run build    # rebuilds the committed frontend/dist served by FastAPI
```

Tests: `uv run pytest -m "not integration"` (fast, offline) and `uv run pytest` (full).

## Design documentation layout

Keep design documentation in `design/`, one file per phase artifact:

| Phase | Document |
|---|---|
| 0 Surface classification | `design/mode.md` |
| 1 Product model & information architecture | `design/product-model.md`, `design/ia.md` |
| 2 Design / reference research | `design/references.md` |
| 3 Design system | `design/system/` |
| Process | `design/V2_WORKFLOW.md` (this file) |

Each phase artifact is reviewed and approved before the next phase starts.
