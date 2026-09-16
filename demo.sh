#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Operon — one-command demo launcher (Linux/macOS/WSL).  See docs/DEMO.md.
#
#   ./demo.sh                 check environment, sync deps, start Operon
#   ./demo.sh --check         only check environment + provider status, don't start
#   ./demo.sh --probe         also run the provider connection test (network)
#   ./demo.sh --dev           additionally run the Vite dev server (hot reload, :5173)
#   ./demo.sh --rebuild-frontend   rebuild frontend/dist before starting (needs Node)
#   ./demo.sh --reset-demo    reset the demo database before starting
#   ./demo.sh --open          open the portal in a browser once ready
#   ./demo.sh --no-sync       skip `uv sync`
#
# Guarantees: never prints a secret, never installs system packages or Ollama,
# never pulls a model, never requires AWS. Ctrl+C stops every child process.
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

HOST="${POC_HOST:-127.0.0.1}"
PORT="${POC_PORT:-8000}"
DEV_PORT=5173
CHECK_ONLY=0; PROBE=0; DEV=0; REBUILD=0; RESET=0; SYNC=1; OPEN=0
READY_TIMEOUT="${OPERON_READY_TIMEOUT:-180}"

usage() { sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --probe) PROBE=1 ;;
    --dev) DEV=1 ;;
    --rebuild-frontend) REBUILD=1 ;;
    --reset-demo) RESET=1 ;;
    --open) OPEN=1 ;;
    --no-sync) SYNC=0 ;;
    --port) shift; PORT="${1:?--port needs a value}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ]; then B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'; else B=""; D=""; G=""; Y=""; R=""; N=""; fi
ok()   { printf '%s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s⚠%s %s\n' "$Y" "$N" "$*"; }
fail() { printf '%s✗%s %s\n' "$R" "$N" "$*" >&2; }
die()  { fail "$@"; exit 1; }

printf '\n%sOPERON — Autonomous Reliability Platform%s\n%s%s%s\n\n' "$B" "$N" "$D" "$ROOT" "$N"

# ---- environment -----------------------------------------------------------
echo "Checking environment..."
command -v uv >/dev/null 2>&1 || die "uv is required (https://docs.astral.sh/uv/getting-started/installation/)"
ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"

HAVE_NODE=0
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  HAVE_NODE=1; ok "Node $(node --version) / npm $(npm --version)"
else
  warn "Node/npm not found (only needed for --dev or --rebuild-frontend; the committed frontend/dist is used)"
fi
HAVE_CURL=0; command -v curl >/dev/null 2>&1 && HAVE_CURL=1
if command -v ollama >/dev/null 2>&1; then ok "ollama CLI present (optional; never started or installed by this script)"; fi

# ---- dependencies ----------------------------------------------------------
if [ "$SYNC" = 1 ]; then
  if uv sync --quiet 2>"$ROOT/.demo-sync.err"; then ok "backend dependencies (uv sync)"; rm -f "$ROOT/.demo-sync.err"
  else fail "uv sync failed:"; sed 's/^/    /' "$ROOT/.demo-sync.err" >&2; rm -f "$ROOT/.demo-sync.err"; exit 1; fi
else
  ok "backend dependencies (sync skipped)"
fi

NEED_BUILD=0
if [ ! -f frontend/dist/index.html ] || [ "$REBUILD" = 1 ]; then NEED_BUILD=1; fi
if [ "$NEED_BUILD" = 1 ] || [ "$DEV" = 1 ]; then
  [ "$HAVE_NODE" = 1 ] || die "Node.js/npm are required to build or dev-serve the dashboard (install Node >= 18, or drop --dev/--rebuild-frontend)"
  if [ ! -d frontend/node_modules ]; then
    echo "  installing frontend dependencies (npm ci)…"
    (cd frontend && if [ -f package-lock.json ]; then npm ci --silent; else npm install --silent; fi) || die "npm install failed"
  fi
  ok "frontend dependencies"
  if [ "$NEED_BUILD" = 1 ]; then
    echo "  building the dashboard (vite build)…"
    (cd frontend && npm run build --silent >/dev/null) || die "frontend build failed (run: cd frontend && npm run build)"
    ok "dashboard built (frontend/dist)"
  fi
else
  ok "dashboard bundle (frontend/dist, pre-built)"
fi

# ---- port availability -----------------------------------------------------
port_free() { uv run --no-sync python - "$1" "$2" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket(); s.settimeout(0.5)
try: sys.exit(1 if s.connect_ex((host, port)) == 0 else 0)
finally: s.close()
PY
}
if ! port_free "$HOST" "$PORT"; then die "port $PORT on $HOST is already in use (stop the other Operon, or: POC_PORT=8010 ./demo.sh)"; fi

# ---- AI provider (never prints secrets) -----------------------------------
echo
if [ "$PROBE" = 1 ]; then uv run --no-sync python -m core.providers.status --probe; else uv run --no-sync python -m core.providers.status; fi
echo

if [ "$CHECK_ONLY" = 1 ]; then ok "environment check complete (nothing started)"; exit 0; fi

# ---- start -----------------------------------------------------------------
LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/operon-demo.XXXXXX")"
PIDS=()
STOPPING=0

stop_all() {
  [ "$STOPPING" = 1 ] && return; STOPPING=1
  echo; echo "Stopping Operon…"
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] || continue
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    alive=0; for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break; sleep 0.5
  done
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && { kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true; }
  done
  ok "stopped (logs: $LOG_DIR)"
}
trap 'stop_all; exit 130' INT
trap 'stop_all; exit 143' TERM
trap 'stop_all' EXIT

spawn() {  # spawn <name> <logfile> <cmd...>  — own process group so Ctrl+C reaches every child
  local name="$1" log="$2"; shift 2
  if command -v setsid >/dev/null 2>&1; then setsid "$@" >"$log" 2>&1 < /dev/null & else "$@" >"$log" 2>&1 < /dev/null & fi
  local pid=$!; PIDS+=("$pid"); echo "  $name started (pid $pid, log $log)"
}

echo "Starting Operon…"
BACKEND_ARGS=(--no-browser); [ "$RESET" = 1 ] && BACKEND_ARGS+=(--reset-demo)
export OPERON_OPEN_BROWSER=0 POC_HOST="$HOST" POC_PORT="$PORT"
spawn "backend" "$LOG_DIR/backend.log" uv run --no-sync python run.py "${BACKEND_ARGS[@]}"
BACKEND_PID="${PIDS[0]}"
if [ "$DEV" = 1 ]; then
  spawn "frontend dev server" "$LOG_DIR/frontend.log" npm --prefix frontend run dev -- --host "$HOST" --port "$DEV_PORT"
fi

health_ok() {
  if [ "$HAVE_CURL" = 1 ]; then curl -fsS -m 2 "http://$HOST:$PORT/api/health" >/dev/null 2>&1
  else uv run --no-sync python -c "import urllib.request,sys; urllib.request.urlopen('http://$HOST:$PORT/api/health', timeout=2)" >/dev/null 2>&1; fi
}
echo "  waiting for the engine (first run trains the health model, ~10-60 s)…"
elapsed=0
until health_ok; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then fail "backend exited early; last log lines:"; tail -n 30 "$LOG_DIR/backend.log" >&2; exit 1; fi
  if [ "$elapsed" -ge "$READY_TIMEOUT" ]; then fail "engine not ready after ${READY_TIMEOUT}s; log: $LOG_DIR/backend.log"; exit 1; fi
  sleep 1; elapsed=$((elapsed + 1))
done

PORTAL="http://$HOST:$PORT/"
[ "$DEV" = 1 ] && PORTAL_DEV="http://$HOST:$DEV_PORT/"
echo
ok "Operon is ready"
echo "Portal:      $PORTAL"
[ "$DEV" = 1 ] && echo "Dev server:  ${PORTAL_DEV} (hot reload; proxies /api and /ws to :$PORT)"
echo "Demo guide:  docs/DEMO.md"
echo "Logs:        $LOG_DIR"
echo
echo "Press Ctrl+C to stop."
if [ "$OPEN" = 1 ]; then (command -v xdg-open >/dev/null && xdg-open "$PORTAL" || command -v open >/dev/null && open "$PORTAL") >/dev/null 2>&1 || true; fi

wait "$BACKEND_PID" || true
if [ "$STOPPING" = 0 ]; then fail "backend stopped unexpectedly; last log lines:"; tail -n 30 "$LOG_DIR/backend.log" >&2; exit 1; fi
