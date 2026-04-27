"""Session post-processing.

Runs when a session terminates. Two responsibilities:

1. **Memory writeback** for investigation sessions: extract finding signatures
   and baseline numbers from this session's findings, merge into agent memory.
   Phase 3 keeps memory tiny — last 50 findings + rolling p95.

2. **Issue state transitions** for verification sessions: parse the agent's
   terminal text — if "RESOLVED", mark the linked issue resolved and post a
   confirmation in the existing Slack thread; if "REGRESSED", re-open with
   higher severity; else leave verifying and rely on the cron loop to
   schedule the next attempt (with exponential backoff).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import structlog

from . import object_store, snapshot_store
from .config import get_settings
from .objects import canonical_bytes


log = structlog.get_logger(__name__)


async def finalize(session_id: str, *, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        sess = await conn.fetchrow("SELECT * FROM sessions WHERE id = $1", UUID(session_id))
    if sess is None:
        return

    if sess["kind"] == "investigation":
        await _post_investigation(sess, pool)
    elif sess["kind"] == "verification":
        await _post_verification(sess, pool)
    # manual sessions are noisy by design; nothing to clean up.


# ----------------------------------------------------------
# Investigation post-processing
# ----------------------------------------------------------

async def _post_investigation(sess: asyncpg.Record, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        findings = await conn.fetch(
            "SELECT * FROM findings WHERE session_id = $1 ORDER BY created_at",
            sess["id"],
        )
        agent = await conn.fetchrow("SELECT * FROM agents WHERE id = $1", sess["agent_id"])
    if agent is None:
        return

    # Update agent memory: append finding signatures (capped), record latest
    # baseline if the trigger payload included one.
    memory = await _load_memory(agent)
    sigs = list(memory.get("recent_finding_signatures", []))
    for f in findings:
        sig = f["signature"]
        if sig not in sigs:
            sigs.append(sig)
    sigs = sigs[-50:]
    memory["recent_finding_signatures"] = sigs

    trigger = sess["trigger_payload"]
    if isinstance(trigger, str):
        trigger = json.loads(trigger)
    if "current_p95_ms" in trigger:
        baselines = memory.get("baselines", {})
        scope = (trigger.get("endpoints") or ["__all__"])[0]
        baselines[scope] = {
            "p95_ms_observed": trigger["current_p95_ms"],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        memory["baselines"] = baselines

    memory["last_session_id"] = str(sess["id"])
    await _save_memory(agent_id=str(agent["id"]), memory=memory, pool=pool)


# ----------------------------------------------------------
# Verification post-processing
# ----------------------------------------------------------

async def _post_verification(sess: asyncpg.Record, pool: asyncpg.Pool) -> None:
    """The verification agent ends its turn with one of: RESOLVED,
    STILL_OPEN, REGRESSED. We pull the latest assistant_message from the
    snapshot chain and act on the keyword.
    """
    if not sess["latest_snapshot_id"]:
        return
    text = await _last_assistant_text(sess["latest_snapshot_id"])
    upper = (text or "").upper()

    trigger = sess["trigger_payload"]
    if isinstance(trigger, str):
        trigger = json.loads(trigger)
    issue_id = trigger.get("issue_id")
    if not issue_id:
        return

    if "RESOLVED" in upper:
        await _resolve_issue(
            issue_id=issue_id,
            session_id=str(sess["id"]),
            agent_id=str(sess["agent_id"]),
            pool=pool,
        )
    elif "REGRESSED" in upper:
        await _reopen_issue(issue_id=issue_id, pool=pool)
    # STILL_OPEN: cron will schedule the next attempt.


async def _resolve_issue(
    *, issue_id: str, session_id: str, agent_id: str, pool: asyncpg.Pool
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE issues
               SET status = 'resolved',
                   resolved_at = now(),
                   resolved_by_session_id = $2,
                   next_verification_at = NULL
             WHERE id = $1
            """,
            UUID(issue_id),
            UUID(session_id),
        )
        await conn.execute(
            "UPDATE agents SET current_issue_id = NULL WHERE id = $1 AND current_issue_id = $2",
            UUID(agent_id),
            UUID(issue_id),
        )
        # Post a "fix verified" message in the existing thread, if any.
        issue = await conn.fetchrow(
            "SELECT slack_thread_ts, slack_channel FROM issues WHERE id = $1",
            UUID(issue_id),
        )
        agent = await conn.fetchrow(
            """
            SELECT a.slack_channel, c.credentials_encrypted
              FROM agents a
              LEFT JOIN connections c ON c.id = a.slack_connection_id
             WHERE a.id = $1
            """,
            UUID(agent_id),
        )
    await _post_resolution_to_slack(issue=issue, agent=agent)


async def _reopen_issue(*, issue_id: str, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE issues
               SET status = 'regressed',
                   severity = CASE
                     WHEN severity = 'low' THEN 'medium'
                     WHEN severity = 'medium' THEN 'high'
                     WHEN severity = 'high' THEN 'critical'
                     ELSE severity
                   END
             WHERE id = $1
            """,
            UUID(issue_id),
        )


async def _post_resolution_to_slack(*, issue: Any, agent: Any) -> None:
    if not issue or not issue["slack_thread_ts"] or not agent or not agent["credentials_encrypted"]:
        return
    from . import crypto_runtime

    token = crypto_runtime.decrypt_str(agent["credentials_encrypted"])
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.agent_tool_timeout_seconds) as http:
        try:
            await http.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "channel": issue["slack_channel"] or agent["slack_channel"],
                    "thread_ts": issue["slack_thread_ts"],
                    "text": "✅ Fix verified. Metrics returned to baseline. Marking issue resolved.",
                },
            )
        except Exception as e:
            log.warning("resolution slack post failed", err=str(e))


# ----------------------------------------------------------
# Helpers
# ----------------------------------------------------------

async def _last_assistant_text(snapshot_id: str) -> str:
    snap = await snapshot_store.read_snapshot(snapshot_id)
    last_text = ""
    for h in snap.get("object_hashes", []):
        obj = await snapshot_store.read_object(h)
        if obj["type"] == "assistant_message":
            last_text = obj["content"].get("text", "")
    return last_text


async def _load_memory(agent: asyncpg.Record) -> dict[str, Any]:
    if not agent["memory_ref"]:
        return {}
    try:
        blob = await object_store.get(agent["memory_ref"])
        return json.loads(blob)
    except Exception:
        return {}


async def _save_memory(*, agent_id: str, memory: dict[str, Any], pool: asyncpg.Pool) -> None:
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()
    blob = canonical_bytes(memory)
    h = hashlib.sha256(blob).hexdigest()
    key = f"agents/{agent_id}/memory/{h}.json"
    await object_store.put(key, blob, content_type="application/json")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agents SET memory_ref = $1 WHERE id = $2",
            key,
            UUID(agent_id),
        )
