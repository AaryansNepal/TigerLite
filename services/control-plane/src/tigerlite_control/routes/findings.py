"""Findings list per session/agent."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from ..auth import CurrentUser
from ..db import get_pool
from ..models import Finding

router = APIRouter()


@router.get("", response_model=list[Finding])
async def list_findings(
    ctx: CurrentUser,
    agent_id: UUID | None = Query(default=None),
    session_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> list[Finding]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        clauses = ["tenant_id = $1"]
        params: list[Any] = [UUID(ctx.tenant_id)]
        if agent_id:
            params.append(agent_id)
            clauses.append(f"agent_id = ${len(params)}")
        if session_id:
            params.append(session_id)
            clauses.append(f"session_id = ${len(params)}")
        params.append(limit)
        rows = await conn.fetch(
            f"""
            SELECT * FROM findings
             WHERE {" AND ".join(clauses)}
             ORDER BY created_at DESC
             LIMIT ${len(params)}
            """,
            *params,
        )
    return [_row_to_finding(r) for r in rows]


def _row_to_finding(row: Any) -> Finding:
    d = dict(row)
    if isinstance(d.get("evidence"), str):
        d["evidence"] = json.loads(d["evidence"])
    return Finding.model_validate(d)
