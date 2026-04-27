"""Trigger router.

Handles non-snapshot_ready jobs:
  - anomaly       → new investigation session
  - cron          → manual run / scheduled check
  - slack_message → resume an existing session in the matched thread
  - verify_issue  → new verification session for an open issue

For each, we:
  1. Look up the agent + tenant.
  2. Decide new-or-resume.
  3. Compose the initial snapshot (system_prompt + trigger_event + memory + plan).
  4. Insert sessions row.
  5. Enqueue a snapshot_ready job for the runtime worker to pick up.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import structlog

from . import object_store, snapshot_store, queue_client
from .db import get_pool
from .objects import canonical_bytes, make_object
from .prompts import (
    render_investigation_system_prompt,
    render_verification_system_prompt,
)


log = structlog.get_logger(__name__)


async def handle_trigger(job: dict[str, Any]) -> None:
    kind = job["kind"]
    if kind == "anomaly":
        await _handle_anomaly(job)
    elif kind == "cron":
        await _handle_cron(job)
    elif kind == "slack_message":
        await _handle_slack(job)
    elif kind == "verify_issue":
        await _handle_verify(job)
    else:
        log.warning("trigger_router got unknown kind", kind=kind)


async def _handle_anomaly(job: dict[str, Any]) -> None:
    payload = job["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    agent_id = payload["agent_id"]
    evidence = payload.get("evidence", {})
    await _start_investigation(
        agent_id=agent_id,
        trigger_kind="anomaly",
        trigger_payload={
            "kind": "anomaly",
            **evidence,
        },
    )


async def _handle_cron(job: dict[str, Any]) -> None:
    payload = job["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    await _start_investigation(
        agent_id=payload["agent_id"],
        trigger_kind="cron",
        trigger_payload={
            "kind": payload.get("reason", "cron"),
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
        },
    )


async def _handle_slack(job: dict[str, Any]) -> None:
    payload = job["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT * FROM sessions WHERE id = $1",
            UUID(payload["session_id"]),
        )
    if sess is None:
        log.warning("slack thread → no session", payload=payload)
        return
    # Append a user_message object onto the existing session's chain by
    # writing a fresh snapshot with the new object appended.
    await _append_user_message(
        session_id=str(sess["id"]),
        text=payload.get("text", ""),
    )


async def _handle_verify(job: dict[str, Any]) -> None:
    payload = job["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    issue_id = payload["issue_id"]
    agent_id = payload["agent_id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        issue = await conn.fetchrow("SELECT * FROM issues WHERE id = $1", UUID(issue_id))
    if issue is None:
        return
    await _start_verification(agent_id=agent_id, issue=dict(issue))


# ----------------------------------------------------------
# Session creators
# ----------------------------------------------------------

async def _start_investigation(
    *, agent_id: str, trigger_kind: str, trigger_payload: dict[str, Any]
) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        agent = await conn.fetchrow(
            "SELECT a.*, t.name AS tenant_name FROM agents a JOIN tenants t ON t.id = a.tenant_id WHERE a.id = $1",
            UUID(agent_id),
        )
    if agent is None:
        log.warning("agent not found", agent_id=agent_id)
        return ""

    memory = await _load_memory(agent)

    system_prompt = render_investigation_system_prompt(
        agent={k: agent[k] for k in agent.keys()},
        tenant_name=agent["tenant_name"],
        memory=memory,
    )
    return await _compose_initial_snapshot(
        agent=agent,
        kind="investigation",
        trigger_kind=trigger_kind,
        trigger_payload=trigger_payload,
        system_prompt=system_prompt,
    )


async def _start_verification(*, agent_id: str, issue: dict[str, Any]) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        agent = await conn.fetchrow(
            "SELECT a.*, t.name AS tenant_name FROM agents a JOIN tenants t ON t.id = a.tenant_id WHERE a.id = $1",
            UUID(agent_id),
        )
    if agent is None:
        return ""

    # Pull the original baseline evidence from the finding that opened the issue.
    async with pool.acquire() as conn:
        finding = await conn.fetchrow(
            """
            SELECT * FROM findings WHERE session_id = $1 ORDER BY created_at LIMIT 1
            """,
            issue["opened_by_session_id"],
        )
    baseline_evidence = {}
    if finding:
        baseline_evidence = finding["evidence"]
        if isinstance(baseline_evidence, str):
            baseline_evidence = json.loads(baseline_evidence)

    system_prompt = render_verification_system_prompt(
        agent={k: agent[k] for k in agent.keys()},
        tenant_name=agent["tenant_name"],
        issue=issue,
        baseline_evidence=baseline_evidence,
    )

    return await _compose_initial_snapshot(
        agent=agent,
        kind="verification",
        trigger_kind="verification",
        trigger_payload={"issue_id": str(issue["id"]), "kind": "scheduled"},
        system_prompt=system_prompt,
    )


async def _compose_initial_snapshot(
    *,
    agent: asyncpg.Record,
    kind: str,
    trigger_kind: str,
    trigger_payload: dict[str, Any],
    system_prompt: str,
) -> str:
    sys_obj = make_object("system_prompt", system_prompt)
    trig_obj = make_object("trigger_event", trigger_payload)
    sys_h = await snapshot_store.write_object(sys_obj)
    trig_h = await snapshot_store.write_object(trig_obj)

    session_id = uuid4()
    pool = await get_pool()

    snap_key, manifest = await snapshot_store.write_snapshot_atomic(
        tenant_id=str(agent["tenant_id"]),
        agent_id=str(agent["id"]),
        session_id=str(session_id),
        version=0,
        object_hashes=[sys_h, trig_h],
        parent_snapshot_id=None,
    )

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (
                id, tenant_id, agent_id, kind, status,
                trigger_kind, trigger_payload,
                root_snapshot_id, latest_snapshot_id, step_count
            ) VALUES (
                $1, $2, $3, $4, 'running',
                $5, $6::jsonb,
                $7, $7, 0
            )
            """,
            session_id,
            agent["tenant_id"],
            agent["id"],
            kind,
            trigger_kind,
            json.dumps(trigger_payload, default=str),
            snap_key,
        )

    await queue_client.enqueue_snapshot_ready(str(agent["tenant_id"]), snap_key)
    return snap_key


async def _append_user_message(session_id: str, text: str) -> str:
    """Append a user_message object onto an existing session's snapshot chain."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT * FROM sessions WHERE id = $1", UUID(session_id)
        )
    if sess is None:
        return ""
    if not sess["latest_snapshot_id"]:
        return ""

    snap = await snapshot_store.read_snapshot(sess["latest_snapshot_id"])
    msg_obj = make_object("user_message", {"text": text})
    msg_h = await snapshot_store.write_object(msg_obj)

    next_key, _ = await snapshot_store.write_snapshot_atomic(
        tenant_id=str(sess["tenant_id"]),
        agent_id=str(sess["agent_id"]),
        session_id=str(sess["id"]),
        version=snap["version"] + 1,
        object_hashes=snap["object_hashes"] + [msg_h],
        parent_snapshot_id=sess["latest_snapshot_id"],
    )
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET latest_snapshot_id = $1, step_count = $2, status = 'running', ended_at = NULL WHERE id = $3",
            next_key,
            snap["version"] + 1,
            UUID(session_id),
        )
    await queue_client.enqueue_snapshot_ready(str(sess["tenant_id"]), next_key)
    return next_key


async def _load_memory(agent: asyncpg.Record) -> dict[str, Any] | None:
    if not agent["memory_ref"]:
        return None
    try:
        blob = await object_store.get(agent["memory_ref"])
        return json.loads(blob)
    except Exception as e:
        log.warning("memory load failed", err=str(e))
        return None
