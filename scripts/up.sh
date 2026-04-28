#!/usr/bin/env bash
# Bring up everything TigerLite needs:
#   1. MinIO + Iceberg REST catalog (Docker)
#   2. ingest, control-plane, runtime, dashboard (foreground via concurrently)
#
# Usage:  ./scripts/up.sh
# Stop:   Ctrl+C, then ./scripts/down.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Sanity: don't double-start if something's already on our ports.
if lsof -i :8000 -i :8080 -i :3000 -P -n 2>/dev/null | grep -q LISTEN; then
  echo "ERROR: ports 8000/8080/3000 are already in use. Run ./scripts/down.sh first." >&2
  lsof -i :8000 -i :8080 -i :3000 -P -n 2>/dev/null | grep LISTEN
  exit 1
fi

echo "→ Bringing up infra (MinIO + Iceberg REST)"
pnpm infra:up

echo "→ Starting all 4 services"
echo "   ingest      :8080"
echo "   control     :8000"
echo "   runtime     (queue worker)"
echo "   dashboard   :3000"
echo
echo "Ctrl+C to stop foreground services. Run ./scripts/down.sh for a full clean shutdown."
echo

exec pnpm dev:all
