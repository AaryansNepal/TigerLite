"""Postgres connection pool. asyncpg.

We use the service-role connection (DATABASE_URL) which bypasses RLS — every
control-plane and runtime call is server-side and trusted. The dashboard's
Next.js API routes are responsible for tenant scoping when they call our
endpoints (and the endpoints validate too).
"""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable, TypeVar

import asyncpg
import structlog

from .config import get_settings

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


def _jsonb_encode(v: object) -> str:
    """Smart encoder for the JSONB codec.

    Some call-sites pass already-stringified JSON (`json.dumps(d)`) into
    `$N::jsonb` parameters. With a naive `json.dumps` encoder, asyncpg
    re-encodes that string and Postgres stores a JSON scalar of type
    string — `{"a": 1}` becomes `"{\"a\": 1}"`. That corrupts the row and
    later reads come back as a `str`, not a `dict`, breaking
    `cfg.get("...")` call sites with `AttributeError`.

    Pass-through strings (assumed to already be valid JSON), json.dumps
    everything else.
    """
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8")
    if isinstance(v, str):
        return v
    return json.dumps(v)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection setup. Register a JSONB codec so asyncpg auto-decodes
    JSON/JSONB columns to Python dicts. Without this, asyncpg returns
    those columns as strings and call sites have to json.loads
    everywhere — the cause of an `AttributeError: 'str' object has no
    attribute 'get'` in the agent compiler when iterating
    connections.config.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=_jsonb_encode,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=_jsonb_encode,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            # Larger pool absorbs Supabase pooler hiccups: requests don't
            # block waiting for a free connection.
            min_size=2,
            max_size=25,
            # Each query has 15s ceiling. Bigger and the user feels it as
            # "the page hung."
            command_timeout=15,
            # Auto-decode JSONB to Python dicts (default would return str).
            init=_init_connection,
            # How long to wait when acquiring a connection from the pool
            # before giving up. Default is 60s which is way too long; we'd
            # rather fail fast and let the retry decorator handle transient.
            server_settings={"application_name": "tigerlite-control-plane"},
        )
        log.info("postgres pool created", max_size=25)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("postgres pool closed")


T = TypeVar("T")


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    backoff_seconds: float = 0.5,
) -> T:
    """Retry a coroutine on transient Postgres failures (timeouts, connection
    errors). Re-raises the last exception if all attempts fail.

    Use to wrap pool.acquire-bound code paths so a single Supabase blip
    doesn't surface as a 500 to the user.
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return await fn()
        except (
            asyncio.TimeoutError,
            asyncpg.exceptions.PostgresConnectionError,
            asyncpg.exceptions.ConnectionDoesNotExistError,
            asyncpg.exceptions.InterfaceError,
            ConnectionError,
            OSError,
        ) as e:
            last_exc = e
            if i < attempts - 1:
                wait = backoff_seconds * (2**i)
                log.warning(
                    "transient postgres error, retrying",
                    attempt=i + 1,
                    of=attempts,
                    wait_s=wait,
                    err=str(e)[:100],
                )
                await asyncio.sleep(wait)
                continue
            raise
    # Unreachable but keeps type checker happy.
    raise last_exc  # type: ignore[misc]
