#!/usr/bin/env bash
# Run all TigerLite services locally in one terminal.
#
# Loads .env.local from repo root once, then spawns four processes via
# concurrently with prefixed log output:
#   - ingest    Go OTLP receiver (port 8080)
#   - control   FastAPI control plane (port 8000)
#   - runtime   Python agent runtime worker
#   - dashboard Next.js dashboard (port 3000)
#
# Pass --backend-only to skip the dashboard (run `pnpm dev` separately).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.local ]]; then
  echo "ERROR: .env.local not found at $ROOT_DIR" >&2
  echo "       Copy .env.example → .env.local and fill in real values." >&2
  exit 1
fi

# Load .env.local into the shell so child processes inherit env vars.
# `set -a` exports every assignment.
set -a
# shellcheck disable=SC1091
. ./.env.local
set +a

BACKEND_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --backend-only) BACKEND_ONLY=1 ;;
  esac
done

# Sanity checks before launching anything (saves 4 confusing error blocks).
if ! command -v go &>/dev/null; then
  echo "ERROR: 'go' not found. Run: brew install go" >&2
  exit 1
fi
if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' not found. Run: brew install uv (or pipx install uv)" >&2
  exit 1
fi
if [[ ! -d services/control-plane/.venv ]]; then
  echo "Bootstrapping services/control-plane (uv sync)…"
  (cd services/control-plane && uv sync)
fi
if [[ ! -d services/agent-runtime/.venv ]]; then
  echo "Bootstrapping services/agent-runtime (uv sync)…"
  (cd services/agent-runtime && uv sync)
fi

CMD_INGEST="cd services/ingest && go run ./cmd/ingest"
CMD_CONTROL="cd services/control-plane && uv run uvicorn tigerlite_control.main:app --reload --port 8000"
CMD_RUNTIME="cd services/agent-runtime && uv run python -m tigerlite_runtime.worker"
CMD_DASHBOARD="pnpm --filter @tigerlite/dashboard dev"

if [[ $BACKEND_ONLY -eq 1 ]]; then
  exec npx --yes concurrently \
    --kill-others-on-fail \
    --names ingest,control,runtime \
    --prefix-colors blue,green,yellow \
    "$CMD_INGEST" "$CMD_CONTROL" "$CMD_RUNTIME"
else
  exec npx --yes concurrently \
    --kill-others-on-fail \
    --names ingest,control,runtime,dashboard \
    --prefix-colors blue,green,yellow,magenta \
    "$CMD_INGEST" "$CMD_CONTROL" "$CMD_RUNTIME" "$CMD_DASHBOARD"
fi
