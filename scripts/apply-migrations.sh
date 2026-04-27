#!/usr/bin/env bash
# Apply Postgres migrations in infra/migrations/ in lexical order.
#
# Reads DATABASE_URL from .env.local at the repo root.
# Migrations are idempotent — safe to run repeatedly.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.local"
MIGRATIONS_DIR="$ROOT_DIR/infra/migrations"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy .env.example to .env.local first." >&2
  exit 1
fi

# Load DATABASE_URL from .env.local (without exposing other vars to subshells).
DATABASE_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'")"

if [[ -z "$DATABASE_URL" || "$DATABASE_URL" == *"replace-me"* ]]; then
  echo "ERROR: DATABASE_URL is not set or still contains a placeholder in $ENV_FILE" >&2
  echo "       Get the connection string from Supabase → Settings → Database → Connection string (URI)." >&2
  exit 1
fi

if ! command -v psql &>/dev/null; then
  echo "ERROR: psql is not installed. Install it (e.g. brew install libpq) or run migrations via Supabase SQL editor." >&2
  exit 1
fi

echo "Applying migrations from $MIGRATIONS_DIR"
shopt -s nullglob
for migration in "$MIGRATIONS_DIR"/*.sql; do
  echo "  → $(basename "$migration")"
  PGPASSWORD="" psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration" >/dev/null
done
echo "Migrations applied."
