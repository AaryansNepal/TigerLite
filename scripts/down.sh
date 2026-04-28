#!/usr/bin/env bash
# Kill everything TigerLite — app processes + infra containers.
#
# Usage:  ./scripts/down.sh
# Or:     ./scripts/down.sh --keep-infra   (kill apps but leave Docker up)

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

KEEP_INFRA=0
for arg in "$@"; do
  case "$arg" in
    --keep-infra) KEEP_INFRA=1 ;;
  esac
done

echo "→ killing app processes"
pkill -9 -f "tigerlite_runtime|tigerlite_control|services/ingest|next dev|concurrently" 2>/dev/null || true
sleep 1

# Anything still holding our ports? Force-kill it.
PIDS=$(lsof -t -i :8000 -i :8080 -i :3000 2>/dev/null || true)
if [[ -n "$PIDS" ]]; then
  echo "→ force-killing port holders: $PIDS"
  echo "$PIDS" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

# Confirm
if lsof -i :8000 -i :8080 -i :3000 -P -n 2>/dev/null | grep -q LISTEN; then
  echo "WARNING: something is still listening on a TigerLite port:"
  lsof -i :8000 -i :8080 -i :3000 -P -n 2>/dev/null | grep LISTEN
fi

if [[ $KEEP_INFRA -eq 1 ]]; then
  echo "→ leaving Docker containers running (--keep-infra)"
else
  echo "→ stopping infra containers"
  docker compose -f infra/docker-compose.yml down 2>/dev/null || true
fi

echo "✓ done"
