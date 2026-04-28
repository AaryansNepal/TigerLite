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


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(connection_id: UUID, ctx: CurrentUser) -> None:
    """Soft-delete a connection. Marks it revoked and clears the encrypted
    token so the agent runtime can't use it. Also unlinks any agents that
    reference it.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchrow(
            """
            UPDATE connections
               SET status = 'revoked',
                   credentials_encrypted = NULL,
                   updated_at = now()
             WHERE id = $1 AND tenant_id = $2
             RETURNING id, kind
            """,
            connection_id,
            UUID(ctx.tenant_id),
        )
        if deleted is None:
            raise HTTPException(status_code=404, detail="connection not found")

        # Detach any agents pointing at this connection
        if deleted["kind"] == "github":
            await conn.execute(
                "UPDATE agents SET github_connection_id = NULL WHERE github_connection_id = $1",
                connection_id,
            )
        elif deleted["kind"] == "slack":
            await conn.execute(
                "UPDATE agents SET slack_connection_id = NULL WHERE slack_connection_id = $1",
                connection_id,
            )


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


# ====================================================================
# GitHub App OAuth flow — exchange installation_id for an install token
# ====================================================================


@router.get("/github/install-url")
async def github_install_url(ctx: CurrentUser) -> dict[str, str]:
    """Return the public install URL the user clicks to install our App."""
    settings = get_settings()
    if not settings.github_app_slug:
        raise HTTPException(status_code=500, detail="GITHUB_APP_SLUG not configured")
    return {
        "install_url": f"https://github.com/apps/{settings.github_app_slug}/installations/new",
        "app_slug": settings.github_app_slug,
    }


@router.post("/github/exchange")
async def github_exchange(
    ctx: CurrentUser,
    payload: dict[str, Any],
) -> Connection:
    """Called after the user installs the App on a repo. GitHub redirects
    the browser back with `installation_id`; the dashboard then POSTs that
    here. We exchange the App JWT for an install token, list the installed
    repos, and persist an encrypted connection row.
    """
    installation_id_raw = payload.get("installation_id")
    if not installation_id_raw:
        raise HTTPException(status_code=400, detail="installation_id required")
    try:
        installation_id = int(installation_id_raw)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail="installation_id must be int") from e

    from ..agents import github_oauth

    try:
        token_resp = await github_oauth.get_installation_token(installation_id)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub token exchange failed: {e}",
        ) from e

    install_token = token_resp["token"]
    expires_at = token_resp.get("expires_at")

    # Fetch the actual repos so we can name the connection nicely
    try:
        repos = await github_oauth.list_installation_repos(install_token)
    except Exception:
        repos = []

    repo_names = [r.get("full_name") for r in repos if r.get("full_name")]

    # Pick a sensible primary repo for display. Prefer the opentelemetry-demo
    # fork (canonical TigerLite demo target), then anything containing
    # "demo"/"telemetry", then fall back to the first.
    def _score(name: str) -> int:
        lower = name.lower()
        if "opentelemetry-demo" in lower or "otel-demo" in lower:
            return 100
        if "demo" in lower or "telemetry" in lower:
            return 50
        return 0

    primary_repo = (
        max(repo_names, key=_score) if repo_names else f"installation-{installation_id}"
    )

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
            primary_repo,
            _json_dumps({
                "installation_id": installation_id,
                "repos": repo_names,
                "repo_full_name": primary_repo,
                "expires_at": expires_at,
            }),
            encrypted,
        )
    return Connection.model_validate(dict(row))


@router.post("/github/sync")
async def github_sync(ctx: CurrentUser) -> dict[str, Any]:
    """Recover from a missed callback. Lists every installation of our App
    and tries to find the most recent one — caller is the user we're
    serving so we trust whatever installation this returns. Useful when the
    user already clicked Install but the redirect hit a 404."""
    from ..agents import github_oauth

    try:
        installations = await github_oauth.list_installations()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub list_installations failed: {e}",
        ) from e

    if not installations:
        return {
            "found": False,
            "message": "No installations found. Install the App on a repo first.",
        }

    # Pick the most recent installation. (For multi-tenant prod we'd match
    # via the OAuth user identity; demo shortcut is fine.)
    latest = max(installations, key=lambda i: i.get("created_at", ""))
    installation_id = latest["id"]

    # Run the same exchange path
    conn = await github_exchange(ctx, {"installation_id": installation_id})
    return {"found": True, "connection": conn.model_dump(mode="json")}
