"""Pure-function snapshot step: snapshot_id → next_snapshot_id.

This is the architectural unfair advantage. A worker crash, a Lambda cold
start, a Gemini API timeout — none of them can corrupt agent state, because
state lives entirely in S3 and Postgres, and each step is idempotent through
content addressing + atomic write.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import structlog

from . import session_finalizer, snapshot_store, tools
from .config import get_settings
from .db import get_pool
from .llm import call_gemini
from .objects import make_object


log = structlog.get_logger(__name__)


class TerminalSignal(Exception):
    """Raised when the agent reaches a terminal state — no more steps."""


async def run_one_step(snapshot_id: str) -> str | None:
    """Execute one step of the snapshot loop.

    Returns the next_snapshot_id (a new S3 key) or None if terminal.
    """
    settings = get_settings()
    log.info("run_step start", snapshot_id=snapshot_id)

    snapshot = await snapshot_store.read_snapshot(snapshot_id)
    tenant_id = snapshot["tenant_id"]
    agent_id = snapshot["agent_id"]
    session_id = snapshot["session_id"]
    version = snapshot["version"]

    # Replay objects → Gemini conversation format.
    objects = []
    for h in snapshot["object_hashes"]:
        objects.append(await snapshot_store.read_object(h))

    system_prompt, messages = _replay(objects)

    # Discover tools (internal + MCP).
    pool = await get_pool()
    decls = list(tools.INTERNAL_TOOL_DECLS)
    decls.extend(await tools.discover_mcp_tools(agent_id, pool))

    # Step ceiling.
    if version >= settings.agent_max_steps:
        log.warning("max steps reached, forcing terminal", agent=agent_id, session=session_id)
        await _finalize_session(session_id, status="timed_out", outcome="inconclusive", pool=pool)
        raise TerminalSignal()

    # Single Gemini call.
    response = await call_gemini(
        system_prompt=system_prompt,
        messages=messages,
        tool_decls=decls,
    )

    new_objects: list[dict[str, Any]] = []

    if response.text:
        new_objects.append(make_object("assistant_message", {"text": response.text}))

    # Execute each tool call sequentially (Gemini may emit several per turn).
    is_terminal = response.is_terminal and not response.tool_calls

    if response.tool_calls:
        ctx = tools.ToolContext(
            tenant_id=tenant_id, agent_id=agent_id, session_id=session_id
        )
        async with httpx.AsyncClient() as http:
            for call in response.tool_calls:
                new_objects.append(
                    make_object(
                        "tool_call",
                        {"id": call.id, "name": call.name, "args": call.args},
                    )
                )
                try:
                    result = await tools.execute_tool(call.name, call.args, ctx, pool, http)
                except Exception as e:
                    log.exception("tool error", tool=call.name)
                    result = {"error": str(e)}
                new_objects.append(
                    make_object(
                        "tool_result",
                        {"call_id": call.id, "name": call.name, "result": result},
                    )
                )

    # Persist new objects.
    new_hashes = [await snapshot_store.write_object(o) for o in new_objects]

    next_version = version + 1
    next_key, _manifest = await snapshot_store.write_snapshot_atomic(
        tenant_id=tenant_id,
        agent_id=agent_id,
        session_id=session_id,
        version=next_version,
        object_hashes=snapshot["object_hashes"] + new_hashes,
        parent_snapshot_id=snapshot_id,
    )

    # Update sessions.latest_snapshot_id + step_count.
    await _update_session_pointer(
        session_id=session_id,
        latest_snapshot_id=next_key,
        step_count=next_version,
        pool=pool,
    )

    if is_terminal:
        # Walk the FULL session, not just this step's new_objects: a
        # `record_finding` or `create_issue` call from an earlier step still
        # makes the outcome `issue_found`. The previous bug looked only at
        # `new_objects` (the terminal step) and so misclassified investigations
        # whose terminal turn was a plain text recap as `no_issues`.
        outcome = _infer_outcome(objects + new_objects)
        await _finalize_session(session_id, status="done", outcome=outcome, pool=pool)
        await session_finalizer.finalize(session_id, pool=pool)
        raise TerminalSignal()

    return next_key


# ----------------------------------------------------------
# Helpers
# ----------------------------------------------------------

def _replay(objects: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Convert a list of objects into (system_prompt, messages_for_gemini)."""
    system_prompt = ""
    messages: list[dict[str, Any]] = []

    for obj in objects:
        otype = obj["type"]
        content = obj["content"]
        if otype == "system_prompt":
            system_prompt = content if isinstance(content, str) else content.get("text", "")
        elif otype == "trigger_event":
            # Render the trigger as a user message so Gemini reads it as the
            # opening of the conversation.
            text = "Trigger event:\n" + json.dumps(content, indent=2)
            messages.append({"role": "user", "text": text})
        elif otype == "user_message":
            messages.append({"role": "user", "text": content.get("text", "")})
        elif otype == "assistant_message":
            messages.append({"role": "model", "text": content.get("text", "")})
        elif otype == "tool_call":
            messages.append(
                {
                    "role": "model",
                    "function_call": {"name": content["name"], "args": content.get("args", {})},
                }
            )
        elif otype == "tool_result":
            messages.append(
                {
                    "role": "user",
                    "function_response": {
                        "name": content["name"],
                        "response": content.get("result", {}),
                    },
                }
            )
    return system_prompt, messages


async def _update_session_pointer(
    *, session_id: str, latest_snapshot_id: str, step_count: int, pool: asyncpg.Pool
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
               SET latest_snapshot_id = $1,
                   step_count = $2
             WHERE id = $3
            """,
            latest_snapshot_id,
            step_count,
            UUID(session_id),
        )


async def _finalize_session(
    session_id: str, *, status: str, outcome: str | None, pool: asyncpg.Pool
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
               SET status = $1, outcome = $2, ended_at = now()
             WHERE id = $3
            """,
            status,
            outcome,
            UUID(session_id),
        )


def _infer_outcome(objects: list[dict[str, Any]]) -> str:
    for obj in objects:
        if obj["type"] == "tool_call" and obj["content"].get("name") == "create_issue":
            return "issue_found"
        if obj["type"] == "tool_call" and obj["content"].get("name") == "record_finding":
            return "issue_found"
    return "no_issues"
