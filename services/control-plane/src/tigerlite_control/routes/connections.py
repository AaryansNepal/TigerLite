"""Connections (OTel ingest, GitHub install, Slack OAuth).

Phase 0:
  - POST /api/connections/otel/issue   — generate a fresh ingest token, store
    bcrypt hash, return the token *once* to the client. This is what the
    Telemetry connect modal calls.

Phase 2:
  - GET /api/connections/github/install-url
  - POST /api/connections/github/callback
  - GET /api/connections/slack/install-url
  - POST /api/connections/slack/callback
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

import bcrypt
from fastapi import APIRouter, HTTPException, status

from ..auth import CurrentUser
from ..config import get_settings
from ..crypto import encrypt
from ..db import get_pool
from ..models import Connection

router = APIRouter()


@router.get("", response_model=list[Connection])
async def list_connections(ctx: CurrentUser) -> list[Connection]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM connections
             WHERE tenant_id = $1
             ORDER BY created_at
            """,
            UUID(ctx.tenant_id),
        )
    return [Connection.model_validate(dict(r)) for r in rows]


@router.post("/otel/issue")
async def issue_otel_token(ctx: CurrentUser) -> dict[str, Any]:
    """Issue a fresh ingest token. Stores its bcrypt hash on the tenant
    (and ensures a 'pending' otel connection exists). Returns the plaintext
    token to the caller — this is the ONLY time it's available; we never
    show it again.
    """
    plain = "tigerlite_live_" + secrets.token_urlsafe(32)
    hashed = bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Update the tenant's hash (single ingest token per tenant for demo)
        await conn.execute(
            "UPDATE tenants SET ingest_token_hash = $1 WHERE id = $2",
            hashed,
            UUID(ctx.tenant_id),
        )
        # Ensure an otel connection exists, status pending until first event arrives
        await conn.execute(
            """
            INSERT INTO connections (tenant_id, kind, status, display_name)
            VALUES ($1, 'otel', 'pending', 'OpenTelemetry')
            ON CONFLICT (tenant_id, kind, display_name)
              DO UPDATE SET status = 'pending', updated_at = now()
            """,
            UUID(ctx.tenant_id),
        )
    settings = get_settings()
    return {
        "token": plain,
        "endpoint": f"{settings.ingest_url}/v1/traces",
        "instructions": "Set Authorization: Bearer <token> on your OTLP/HTTP exporter.",
    }


@router.post("/github/store-install")
async def store_github_install(
    ctx: CurrentUser,
    payload: dict[str, Any],
) -> Connection:
    """Phase 2 helper. Stores the install token after the user completes the
    GitHub App install flow on the dashboard side.
    Expects: { installation_id, repo_full_name, install_token, expires_at }
    """
    install_token = payload.get("install_token")
    if not install_token:
        raise HTTPException(status_code=400, detail="install_token required")
    encrypted = encrypt(install_token)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO connections (
                tenant_id, kind, status, display_name, config, credentials_encrypted
            ) VALUES (
                $1, 'github', 'connected', $2, $3::jsonb, $4
            )
            ON CONFLICT (tenant_id, kind, display_name) DO UPDATE
              SET status = 'connected',
                  config = EXCLUDED.config,
                  credentials_encrypted = EXCLUDED.credentials_encrypted,
                  updated_at = now()
            RETURNING *
            """,
            UUID(ctx.tenant_id),
            payload.get("repo_full_name") or "github",
            _json_dumps({
                "installation_id": payload.get("installation_id"),
                "repo_full_name": payload.get("repo_full_name"),
                "expires_at": payload.get("expires_at"),
            }),
            encrypted,
        )
    return Connection.model_validate(dict(row))


@router.post("/slack/store-install")
async def store_slack_install(
    ctx: CurrentUser,
    payload: dict[str, Any],
) -> Connection:
    """Phase 2 helper. Stores the Slack OAuth bot token + selected channel."""
    token = payload.get("bot_token")
    if not token:
        raise HTTPException(status_code=400, detail="bot_token required")
    encrypted = encrypt(token)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO connections (
                tenant_id, kind, status, display_name, config, credentials_encrypted
            ) VALUES (
                $1, 'slack', 'connected', $2, $3::jsonb, $4
            )
            ON CONFLICT (tenant_id, kind, display_name) DO UPDATE
              SET status = 'connected',
                  config = EXCLUDED.config,
                  credentials_encrypted = EXCLUDED.credentials_encrypted,
                  updated_at = now()
            RETURNING *
            """,
            UUID(ctx.tenant_id),
            payload.get("workspace_name") or "slack",
            _json_dumps({
                "workspace_id": payload.get("workspace_id"),
                "workspace_name": payload.get("workspace_name"),
                "channel": payload.get("channel"),
                "channel_id": payload.get("channel_id"),
            }),
            encrypted,
        )
    return Connection.model_validate(dict(row))


def _json_dumps(d: dict) -> str:
    import json
    return json.dumps(d, default=str)
