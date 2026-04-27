"""Sessions API: list per-agent sessions, fetch session detail with snapshot
chain rendered as objects.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from ..auth import CurrentUser
from ..db import get_pool
from ..models import Session
from ..object_store import make_object_store

router = APIRouter()
log = structlog.get_logger(__name__)


@router.get("", response_model=list[Session])
async def list_sessions(
    ctx: CurrentUser,
    agent_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> list[Session]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if agent_id:
            rows = await conn.fetch(
                """
                SELECT * FROM sessions
                 WHERE tenant_id = $1 AND agent_id = $2
                 ORDER BY started_at DESC
                 LIMIT $3
                """,
                UUID(ctx.tenant_id),
                agent_id,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM sessions
                 WHERE tenant_id = $1
                 ORDER BY started_at DESC
                 LIMIT $2
                """,
                UUID(ctx.tenant_id),
                limit,
            )
    return [_row_to_session(r) for r in rows]


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: UUID, ctx: CurrentUser) -> Session:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sessions WHERE id = $1 AND tenant_id = $2",
            session_id,
            UUID(ctx.tenant_id),
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _row_to_session(row)


@router.get("/{session_id}/timeline")
async def session_timeline(session_id: UUID, ctx: CurrentUser) -> dict[str, Any]:
    """Return the latest snapshot's objects, in order, for rendering the
    session timeline cards. The dashboard uses this to draw assistant
    messages, tool calls, tool results, findings, etc.
    """
    sess = await get_session(session_id, ctx)
    if sess.latest_snapshot_id is None:
        return {"snapshot_id": sess.root_snapshot_id, "objects": []}

    snap_store = make_object_store()
    obj_store = make_object_store()  # same bucket for objects + snapshots

    # Snapshot manifest is JSON: { object_hashes: [...], ... }
    manifest_bytes = await snap_store.get(sess.latest_snapshot_id)
    manifest = json.loads(manifest_bytes)

    objects: list[dict[str, Any]] = []
    for h in manifest.get("object_hashes", []):
        key = f"objects/{h[:2]}/{h}"
        try:
            blob = await obj_store.get(key)
            objects.append(json.loads(blob))
        except Exception as e:
            log.warning("missing object", hash=h, err=str(e))
    return {"snapshot_id": sess.latest_snapshot_id, "objects": objects, "manifest": manifest}


def _row_to_session(row: Any) -> Session:
    d = dict(row)
    if isinstance(d.get("trigger_payload"), str):
        d["trigger_payload"] = json.loads(d["trigger_payload"])
    return Session.model_validate(d)
