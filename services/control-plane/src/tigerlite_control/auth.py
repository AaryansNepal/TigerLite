"""Per-request authentication.

Two flavours:
  - Bearer JWT (issued by Supabase Auth) — used by /api/* routes.
  - Internal HMAC (X-Tigerlite-Internal header) — used by /internal/* routes
    when the control plane talks to itself or to the Go ingest service. We
    don't bother with HMAC for demo; we rely on network isolation and the
    presence of the header. Tighten before going public.

For Phase 0+ we accept the Supabase JWT and resolve the user → tenant
membership lookup. The tenant_id is then injected into the request state.
"""

from __future__ import annotations

from typing import Annotated

import asyncpg
import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status

from .config import get_settings
from .db import get_pool

log = structlog.get_logger(__name__)


class TenantContext:
    def __init__(self, *, user_id: str, tenant_id: str, role: str) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role


async def require_user(request: Request) -> TenantContext:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    token = auth_header.split(" ", 1)[1].strip()

    settings = get_settings()
    try:
        # Supabase issues HS256 JWTs signed with the project's JWT secret.
        # In dev we accept service-role; in prod, require user JWTs.
        # The `aud` claim is "authenticated".
        claims = jwt.decode(
            token,
            settings.supabase_service_role_key,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_signature": False},  # demo: skip sig verification
        )
    except Exception as e:
        log.warning("jwt decode failed", err=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from e

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    pool = await get_pool()
    async with pool.acquire() as conn:
        membership = await conn.fetchrow(
            """
            SELECT tenant_id, role
              FROM memberships
             WHERE user_id = $1
             ORDER BY created_at
             LIMIT 1
            """,
            user_id,
        )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no tenant")
    return TenantContext(
        user_id=str(user_id),
        tenant_id=str(membership["tenant_id"]),
        role=str(membership["role"]),
    )


async def require_internal(request: Request) -> None:
    if request.headers.get("X-Tigerlite-Internal") != "1":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


CurrentUser = Annotated[TenantContext, Depends(require_user)]
InternalCaller = Annotated[None, Depends(require_internal)]
