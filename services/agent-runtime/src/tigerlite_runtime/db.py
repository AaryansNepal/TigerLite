"""Postgres pool. Same shape as the control plane's; runtime uses its own
connection pool so the two services can be deployed independently.
"""

from __future__ import annotations

import json

import asyncpg
import structlog

from .config import get_settings

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Auto-decode JSONB / JSON columns to Python dicts. Without this asyncpg
    returns them as strings and call sites have to json.loads everywhere.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=5,
            command_timeout=30,
            init=_init_connection,
            server_settings={"application_name": "tigerlite-agent-runtime"},
        )
        log.info("postgres pool created (runtime)")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
