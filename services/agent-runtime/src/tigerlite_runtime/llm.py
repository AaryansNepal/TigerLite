"""Gemini wrapper.

Returns a normalised response: text, tool_calls, terminal flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from google import genai
from google.genai import types as gtypes

from .config import get_settings

log = structlog.get_logger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    is_terminal: bool


def _to_gemini_tools(decls: list[dict[str, Any]]) -> list[gtypes.Tool]:
    fn_decls = [
        gtypes.FunctionDeclaration(
            name=d["name"],
            description=d["description"],
            parameters=d.get("parameters"),
        )
        for d in decls
    ]
    return [gtypes.Tool(function_declarations=fn_decls)]


def _to_gemini_contents(messages: list[dict[str, Any]]) -> list[gtypes.Content]:
    """Convert our internal message list into Gemini's Content format.

    Our messages look like:
      {"role": "user|model", "text": "...", "function_call": {...}, "function_response": {...}}
    """
    out: list[gtypes.Content] = []
    for m in messages:
        role = m["role"]
        parts: list[gtypes.Part] = []
        if "text" in m and m["text"] is not None:
            parts.append(gtypes.Part(text=m["text"]))
        if "function_call" in m:
            fc = m["function_call"]
            parts.append(
                gtypes.Part(
                    function_call=gtypes.FunctionCall(name=fc["name"], args=fc.get("args", {}))
                )
            )
        if "function_response" in m:
            fr = m["function_response"]
            parts.append(
                gtypes.Part(
                    function_response=gtypes.FunctionResponse(
                        name=fr["name"],
                        response=fr.get("response", {}),
                    )
                )
            )
        if not parts:
            continue
        out.append(gtypes.Content(role=role, parts=parts))
    return out


async def call_gemini(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_decls: list[dict[str, Any]],
) -> LLMResponse:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=settings.gemini_api_key)
    contents = _to_gemini_contents(messages)
    tools = _to_gemini_tools(tool_decls)

    resp = await client.aio.models.generate_content(
        model=settings.gemini_model_agent,
        contents=contents,
        config=gtypes.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0,
            tools=tools,
        ),
    )

    text_chunks: list[str] = []
    tool_calls: list[ToolCall] = []
    finish_reason = None

    for c in resp.candidates or []:
        finish_reason = getattr(c, "finish_reason", finish_reason)
        if not c.content or not c.content.parts:
            continue
        for i, part in enumerate(c.content.parts):
            if getattr(part, "text", None):
                text_chunks.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc and fc.name:
                tool_calls.append(
                    ToolCall(
                        id=f"call_{i}_{fc.name}",
                        name=fc.name,
                        args=dict(fc.args) if fc.args else {},
                    )
                )

    text = "\n".join(text_chunks).strip()
    is_terminal = (not tool_calls) and bool(text) and (finish_reason is None or "STOP" in str(finish_reason).upper())
    return LLMResponse(text=text, tool_calls=tool_calls, is_terminal=is_terminal)
