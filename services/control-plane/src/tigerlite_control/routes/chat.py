"""Live agent chat — Tier 2.

Endpoint:
  POST /api/agents/{id}/chat   body: {message: str}
  → SSE stream of token chunks, finalized with the saved turn

Uses Gemini Flash-Lite (low latency, ~300-500ms first token, ~1s total)
with the agent's compiled config + recent transcript as context.

The agent has a *narrow* tool surface here, intentionally different from
the investigation runtime — this is conversational/control plane, not
the heavy snapshot loop:

  - run_investigation()   → enqueues a manual cron trigger
  - update_threshold(value, unit)  → patches scope_config
  - get_recent_findings(limit)     → reads findings rows
  - update_plan(text)              → updates the agent's plan field

If the user asks something the LLM can't directly act on, it just
answers conversationally.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types as gtypes
from pydantic import BaseModel

from .. import queue
from ..auth import CurrentUser
from ..config import get_settings
from ..db import get_pool

router = APIRouter()
log = structlog.get_logger(__name__)


CHAT_SYSTEM_PROMPT = """\
You are TigerLite — the conversational assistant for an autonomous
operations agent the user owns. Each agent monitors a software system
and investigates anomalies. You speak ON BEHALF of one specific agent.

Your tone: brief, direct, like a senior SRE colleague. Don't repeat
the user. Don't say "I understand". Just answer.

You can do these things by calling tools (do them, don't ask):
  - run_investigation: trigger a manual investigation now
  - update_scope: change the agent's threshold or window
  - get_recent_findings: read what the agent has recently flagged
  - update_plan: rewrite the agent's runbook

When the user asks something you can't do (e.g. "what's the weather"),
say so plainly. When the user makes small talk, be friendly and brief.
"""


class ChatMessage(BaseModel):
    message: str


@router.post("/{agent_id}")
async def chat(agent_id: UUID, body: ChatMessage, ctx: CurrentUser) -> StreamingResponse:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")

    pool = await get_pool()
    async with pool.acquire() as conn:
        agent = await conn.fetchrow(
            "SELECT * FROM agents WHERE id = $1 AND tenant_id = $2",
            agent_id,
            UUID(ctx.tenant_id),
        )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Append user turn immediately so it shows up in the transcript even
    # if the agent's reply fails halfway through.
    user_turn = {
        "role": "user",
        "text": body.message,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await _append_turn(agent_id, user_turn)

    transcript = (agent["chat_transcript"] or []) + [user_turn]

    # Build Gemini conversation context from recent transcript (cap so
    # token cost stays low + reply latency low).
    recent = transcript[-10:]
    contents = []
    for t in recent:
        role = "user" if t.get("role") == "user" else "model"
        text = t.get("text", "") or ""
        if text:
            contents.append(gtypes.Content(role=role, parts=[gtypes.Part(text=text)]))

    # Inject a brief agent context line in the system prompt
    agent_context = (
        f"Agent name: {agent['name']}\n"
        f"Objective: {agent['objective']}\n"
        f"Plan:\n{agent['plan']}\n"
        f"Scope: {json.dumps(agent['scope_config'])}\n"
    )
    sys_prompt = CHAT_SYSTEM_PROMPT + "\n\n" + agent_context

    async def event_stream() -> AsyncIterator[str]:
        client = genai.Client(api_key=settings.gemini_api_key)
        accumulated: list[str] = []
        try:
            async for chunk in await client.aio.models.generate_content_stream(
                model=settings.gemini_model_chat,
                contents=contents,
                config=gtypes.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    temperature=0.4,
                ),
            ):
                if chunk.text:
                    accumulated.append(chunk.text)
                    yield f"data: {json.dumps({'delta': chunk.text})}\n\n"
        except Exception as e:
            log.exception("chat stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        full_text = "".join(accumulated).strip() or "(no response)"
        agent_turn = {
            "role": "agent",
            "text": full_text,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        await _append_turn(agent_id, agent_turn)
        yield f"data: {json.dumps({'done': True, 'turn': agent_turn})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _append_turn(agent_id: UUID, turn: dict[str, Any]) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE agents
               SET chat_transcript = chat_transcript || $2::jsonb
             WHERE id = $1
            """,
            agent_id,
            json.dumps([turn]),
        )
