"""MCP stdio client.

Per Firetiger's "atomic discovery per turn" pattern, we spawn the MCP server
subprocess at the start of each step, list its tools, route the LLM's calls
through it, and tear it down at the end of the step. ~100-500ms overhead per
step, but it sidesteps the operational complexity of long-lived MCP processes.

We use the official `mcp` Python SDK to handle the JSON-RPC framing.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = structlog.get_logger(__name__)


@asynccontextmanager
async def mcp_session(
    *,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    """Open an MCP session over stdio. Use as:

        async with mcp_session(command="github-mcp-server") as sess:
            tools = await sess.list_tools()
    """
    params = StdioServerParameters(
        command=command,
        args=args or [],
        env={**os.environ, **(env or {})},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def list_tool_decls(
    *, command: str, args: list[str] | None = None, env: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Return tool declarations in the format Gemini expects (name +
    description + parameters).
    """
    out: list[dict[str, Any]] = []
    try:
        async with mcp_session(command=command, args=args, env=env) as sess:
            result = await sess.list_tools()
            for t in result.tools:
                out.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    }
                )
    except Exception as e:
        log.warning("mcp list_tools failed", command=command, err=str(e))
    return out


async def call_tool(
    *,
    command: str,
    tool_name: str,
    arguments: dict[str, Any],
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        async with mcp_session(command=command, args=args, env=env) as sess:
            result = await sess.call_tool(tool_name, arguments)
            # Result.content is a list of content blocks (text/image/etc.).
            # For simplicity we coalesce text blocks.
            text_chunks: list[str] = []
            for c in (result.content or []):
                if hasattr(c, "text") and c.text:
                    text_chunks.append(c.text)
            return {
                "ok": not result.isError,
                "content": "\n".join(text_chunks),
                "is_error": bool(result.isError),
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}
