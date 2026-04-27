"""Snapshot store. Read snapshots, write objects (content-addressed),
write the next snapshot manifest atomically.

Atomicity: snapshot manifests use put_if_not_exists with `If-None-Match: *`
so concurrent writers can't both create version N+1 — the loser reads the
winner's version and decides what to do (usually nothing).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from . import object_store
from .objects import canonical_bytes, make_snapshot_manifest

log = structlog.get_logger(__name__)


async def read_snapshot(snapshot_id: str) -> dict[str, Any]:
    blob = await object_store.get(snapshot_id)
    return json.loads(blob)


async def read_object(h: str) -> dict[str, Any]:
    blob = await object_store.get(object_store.object_key(h))
    return json.loads(blob)


async def write_object(obj: dict[str, Any]) -> str:
    blob = canonical_bytes(obj)
    h, key = object_store.hash_key(blob, prefix="objects")
    # Idempotent: same content = same hash = same key. Putting again is fine.
    await object_store.put(key, blob, content_type="application/json")
    return h


async def write_snapshot_atomic(
    *,
    tenant_id: str,
    agent_id: str,
    session_id: str,
    version: int,
    object_hashes: list[str],
    parent_snapshot_id: str | None,
) -> tuple[str, dict[str, Any]]:
    manifest = make_snapshot_manifest(
        tenant_id=tenant_id,
        agent_id=agent_id,
        session_id=session_id,
        version=version,
        object_hashes=object_hashes,
        parent_snapshot_id=parent_snapshot_id,
        created_at_iso=datetime.now(timezone.utc).isoformat(),
    )
    blob = canonical_bytes(manifest)
    key = object_store.snapshot_key(
        tenant_id=tenant_id,
        agent_id=agent_id,
        session_id=session_id,
        version=version,
    )
    written = await object_store.put_if_not_exists(key, blob, content_type="application/json")
    if not written:
        log.info("snapshot already exists, another worker beat us", key=key)
        # Read the existing one and return it. The caller decides what to do.
        existing = await read_snapshot(key)
        return key, existing
    return key, manifest
