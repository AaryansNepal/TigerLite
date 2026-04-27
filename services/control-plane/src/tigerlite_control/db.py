"""Postgres connection pool. asyncpg.

We use the service-role connection (DATABASE_URL) which bypasses RLS — every
control-plane and runtime call is server-side and trusted. The dashboard's
Next.js API routes are responsible for tenant scoping when they call our
endpoints (and the endpoints validate too).
"""

from __future__ import annotations

import asyncpg
import structlog

from .config import get_settings

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
            server_settings={"application_name": "tigerlite-control-plane"},
        )
        log.info("postgres pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("postgres pool closed")
