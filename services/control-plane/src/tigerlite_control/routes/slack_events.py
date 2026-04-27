"""Slack inbound events: app_mention, thread replies.

Slack signs each event with the signing secret. We verify the signature, then
enqueue a slack_message job for the trigger router to resume the matching
agent session (looked up by thread_ts).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request

from .. import queue
from ..config import get_settings
from ..db import get_pool

router = APIRouter()
log = structlog.get_logger(__name__)


@router.post("/events")
async def slack_events(
    request: Request,
    x_slack_signature: str | None = Header(default=None),
    x_slack_request_timestamp: str | None = Header(default=None),
) -> dict[str, Any]:
    body = await request.body()

    if not _verify(body, x_slack_signature, x_slack_request_timestamp):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(body)

    # URL verification handshake
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    if payload.get("type") != "event_callback":
        return {"ok": True}

    event = payload.get("event", {})
    event_type = event.get("type")

    # Resolve to a session via thread_ts.
    thread_ts = event.get("thread_ts") or event.get("ts")
    channel = event.get("channel")
    text = event.get("text", "")
    if not thread_ts or not channel:
        return {"ok": True}

    pool = await get_pool()
    async with pool.acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT id, tenant_id, agent_id FROM sessions
             WHERE slack_thread_ts = $1
             LIMIT 1
            """,
            thread_ts,
        )

    if sess is None:
        log.info("slack event without matching session", thread_ts=thread_ts, type=event_type)
        return {"ok": True}

    await queue.enqueue(
        tenant_id=str(sess["tenant_id"]),
        kind="slack_message",
        payload={
            "agent_id": str(sess["agent_id"]),
            "session_id": str(sess["id"]),
            "thread_ts": thread_ts,
            "channel": channel,
            "text": text,
            "from_user": event.get("user"),
            "event_type": event_type,
        },
    )
    return {"ok": True}


def _verify(body: bytes, signature: str | None, timestamp: str | None) -> bool:
    settings = get_settings()
    secret = settings.slack_signing_secret
    if not secret or not signature or not timestamp:
        # During Phase 0/1 the Slack secret is empty; we accept all (logged).
        return secret == ""

    # Reject replays older than 5 minutes
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > 300:
        return False

    sig_basestring = f"v0:{timestamp}:".encode() + body
    expected = "v0=" + hmac.new(secret.encode(), sig_basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
