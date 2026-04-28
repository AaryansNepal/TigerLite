"""Agents CRUD + chat-driven creation flow + manual trigger."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status

from .. import queue
from ..auth import CurrentUser
from ..db import get_pool, with_retry
from ..models import (
    Agent,
    AgentCreateRequest,
    AgentPatchRequest,
    ManualTriggerRequest,
)

router = APIRouter()
log = structlog.get_logger(__name__)


@router.post("", response_model=Agent | dict[str, Any])
async def create_agent(req: AgentCreateRequest, ctx: CurrentUser) -> Any:
    """Run the compiler with the user's NL objective + optional answers.

    Returns either:
      - the created Agent, if the compiler produced a complete config; or
      - {"clarifying_questions": [...]}, if the compiler needs more info.
    """
    # Lazy import to avoid pulling Gemini SDK when the dashboard hits other routes.
    from ..agents.compiler import compile_agent

    pool = await get_pool()
    async with pool.acquire() as conn:
        services = await conn.fetchval(
            """
            SELECT detected_services FROM connections
             WHERE tenant_id = $1 AND kind = 'otel'
             ORDER BY created_at DESC LIMIT 1
            """,
            UUID(ctx.tenant_id),
        )
        slack_channels = await conn.fetch(
            """
            SELECT id, display_name, config FROM connections
             WHERE tenant_id = $1 AND kind = 'slack' AND status = 'connected'
            """,
            UUID(ctx.tenant_id),
        )
        github_repos = await conn.fetch(
            """
            SELECT id, display_name, config FROM connections
             WHERE tenant_id = $1 AND kind = 'github' AND status = 'connected'
            """,
            UUID(ctx.tenant_id),
        )

    compiled = await compile_agent(
        objective=req.objective,
        answers=req.normalised_answers(),
        detected_services=list(services or []),
        slack_channels=[dict(r) for r in slack_channels],
        github_repos=[dict(r) for r in github_repos],
    )

    if compiled.clarifying_questions:
        return {"clarifying_questions": compiled.clarifying_questions}

    cfg = compiled.config
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agents (
                tenant_id, name, objective, description, plan, scope_config,
                schedule_cron, anomaly_enabled,
                slack_connection_id, slack_channel,
                github_connection_id, github_repo,
                status
            ) VALUES (
                $1, $2, $3, $4, $5, $6::jsonb,
                $7, $8,
                $9, $10,
                $11, $12,
                'active'
            )
            RETURNING *
            """,
            UUID(ctx.tenant_id),
            cfg.name,
            cfg.objective,
            cfg.description,
            cfg.plan,
            json.dumps(cfg.scope_config),
            cfg.schedule_cron,
            cfg.anomaly_enabled,
            req.slack_connection_id,
            cfg.slack_channel,
            req.github_connection_id,
            cfg.github_repo,
        )
    return _row_to_agent(row)


@router.get("", response_model=list[Agent])
async def list_agents(ctx: CurrentUser) -> list[Agent]:
    async def _query() -> list[Any]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT * FROM agents
                 WHERE tenant_id = $1 AND status != 'archived'
                 ORDER BY created_at DESC
                """,
                UUID(ctx.tenant_id),
            )

    rows = await with_retry(_query)
    return [_row_to_agent(r) for r in rows]


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(agent_id: UUID, ctx: CurrentUser) -> Agent:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agents WHERE id = $1 AND tenant_id = $2",
            agent_id,
            UUID(ctx.tenant_id),
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _row_to_agent(row)


@router.patch("/{agent_id}", response_model=Agent)
async def patch_agent(agent_id: UUID, patch: AgentPatchRequest, ctx: CurrentUser) -> Agent:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        return await get_agent(agent_id, ctx)

    set_parts: list[str] = []
    values: list[Any] = []
    idx = 1
    for k, v in fields.items():
        if k == "scope_config":
            set_parts.append(f"{k} = ${idx}::jsonb")
            values.append(json.dumps(v))
        else:
            set_parts.append(f"{k} = ${idx}")
            values.append(v)
        idx += 1
    values.append(agent_id)
    values.append(UUID(ctx.tenant_id))

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE agents
               SET {", ".join(set_parts)}
             WHERE id = ${idx} AND tenant_id = ${idx + 1}
             RETURNING *
            """,
            *values,
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _row_to_agent(row)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_agent(agent_id: UUID, ctx: CurrentUser) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE agents SET status = 'archived'
             WHERE id = $1 AND tenant_id = $2
            """,
            agent_id,
            UUID(ctx.tenant_id),
        )


@router.post("/{agent_id}/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_agent(
    agent_id: UUID, body: ManualTriggerRequest, ctx: CurrentUser
) -> dict[str, str]:
    """Manual run-now button. Enqueues a 'cron' kind job with the manual reason."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE id = $1 AND tenant_id = $2",
            agent_id,
            UUID(ctx.tenant_id),
        )
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    job_id = await queue.enqueue(
        tenant_id=ctx.tenant_id,
        kind="cron",
        payload={"agent_id": str(agent_id), "reason": body.reason or "manual_run"},
    )
    return {"job_id": str(job_id)}


def _row_to_agent(row: Any) -> Agent:
    d = dict(row)
    if isinstance(d.get("scope_config"), str):
        d["scope_config"] = json.loads(d["scope_config"])
    return Agent.model_validate(d)
