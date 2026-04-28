"""Internal tool implementations + MCP discovery hook.

Internal tools (always available):
  - query_telemetry(sql)         → DuckDB result via control plane
  - read_artifact(id, jq?)       → re-read stored artifact
  - record_finding(...)          → write finding row
  - create_issue(...)            → write issue row
  - post_to_slack(channel, blocks)  (Phase 2 — via Slack MCP if connected)
  - update_memory(key, value)    → patch agent memory_ref
  - prepare_fix_handoff(...)     → Phase 4 bundle generator

MCP-discovered tools (Phase 2): GitHub MCP exposes list_recent_commits,
get_commit_diff, read_file, search_code; Slack MCP exposes post_message.
We re-discover at the start of each step (atomic discovery per turn).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx
import structlog
from uuid import UUID

from .config import get_settings

log = structlog.get_logger(__name__)


# ----------------------------------------------------------
# Tool definitions (Gemini function declarations)
# ----------------------------------------------------------

INTERNAL_TOOL_DECLS: list[dict[str, Any]] = [
    {
        "name": "query_telemetry",
        "description": (
            "Run a DuckDB SQL query against this tenant's traces, logs, and metrics "
            "tables. The tables `traces`, `logs`, `metrics` are tenant-scoped CTEs. "
            "Returns columns + preview rows + an artifact_id you can pass to "
            "read_artifact for the full result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "DuckDB SQL. Reference traces, logs, metrics.",
                }
            },
            "required": ["sql"],
        },
    },
    {
        "name": "read_artifact",
        "description": (
            "Re-read a stored tool result by artifact_id. Optional jq filter to narrow."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "jq": {"type": "string", "description": "Optional jq filter."},
            },
            "required": ["artifact_id"],
        },
    },
    {
        "name": "record_finding",
        "description": (
            "Record a structured finding for this investigation. Severity: low|medium|high|critical."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "evidence": {
                    "type": "object",
                    "description": "Free-form JSON: counts, commits, file paths, etc.",
                },
                "suggested_action": {"type": "string"},
            },
            "required": ["title", "summary", "severity", "evidence"],
        },
    },
    {
        "name": "create_issue",
        "description": (
            "Open a persistent issue tracking this regression. The issue is what "
            "verification sessions watch for recovery."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "signature": {
                    "type": "string",
                    "description": "Stable hash describing this issue for dedup.",
                },
                "evidence": {"type": "object"},
            },
            "required": ["title", "summary", "severity", "signature"],
        },
    },
    {
        "name": "update_memory",
        "description": "Patch the agent's persistent memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": "Keys to merge into memory.",
                }
            },
            "required": ["patch"],
        },
    },
    {
        "name": "prepare_fix_handoff",
        "description": (
            "Phase 4: generate a Claude Code-ready fix prompt bundling root cause + "
            "affected files + verification plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "root_cause": {"type": "string"},
                "affected_files": {"type": "array", "items": {"type": "string"}},
                "expected_behavior": {"type": "string"},
                "recovery_criteria": {"type": "object"},
            },
            "required": ["root_cause", "affected_files"],
        },
    },
    {
        "name": "post_to_slack",
        "description": (
            "Post a structured message to the agent's Slack channel. Use blocks for "
            "rich formatting; the dashboard renders the same blocks in the session "
            "timeline."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "fields": {
                    "type": "object",
                    "description": "Key/value pairs to render below the summary.",
                },
            },
            "required": ["title", "summary"],
        },
    },
]


# ----------------------------------------------------------
# Tool execution dispatch
# ----------------------------------------------------------

class ToolContext:
    def __init__(self, *, tenant_id: str, agent_id: str, session_id: str) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.session_id = session_id


async def execute_tool(
    name: str,
    args: dict[str, Any],
    ctx: ToolContext,
    pool: asyncpg.Pool,
    http: httpx.AsyncClient,
) -> dict[str, Any]:
    settings = get_settings()
    log.info("tool", name=name, agent=ctx.agent_id, session=ctx.session_id)

    if name == "query_telemetry":
        return await _query_telemetry(args, ctx, http)
    if name == "read_artifact":
        return await _read_artifact(args, http)
    if name == "record_finding":
        return await _record_finding(args, ctx, pool)
    if name == "create_issue":
        return await _create_issue(args, ctx, pool)
    if name == "update_memory":
        return await _update_memory(args, ctx, pool)
    if name == "post_to_slack":
        return await _post_to_slack(args, ctx, pool)
    if name == "prepare_fix_handoff":
        return await _prepare_fix_handoff(args, ctx)

    # MCP-routed tools — look up the agent's connections and route.
    if name in _MCP_TOOL_NAMES_GITHUB:
        return await _call_github_mcp(name, args, ctx, pool)
    if name in _MCP_TOOL_NAMES_SLACK:
        return await _call_slack_mcp(name, args, ctx, pool)

    return {"error": f"unknown tool {name!r}"}


# Cache of MCP tool names per session so the dispatch knows what's MCP-routed.
_MCP_TOOL_NAMES_GITHUB: set[str] = set()
_MCP_TOOL_NAMES_SLACK: set[str] = set()


async def _call_github_mcp(
    name: str, args: dict[str, Any], ctx: ToolContext, pool: asyncpg.Pool
) -> dict[str, Any]:
    settings = get_settings()
    install_token = await _get_github_install_token(ctx.agent_id, pool)
    if not install_token:
        return {"error": "no GitHub connection for this agent"}

    from . import mcp_client

    return await mcp_client.call_tool(
        command=settings.github_mcp_command,
        args=["stdio", "--read-only"],
        tool_name=name,
        arguments=args,
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": install_token},
    )


async def _call_slack_mcp(
    name: str, args: dict[str, Any], ctx: ToolContext, pool: asyncpg.Pool
) -> dict[str, Any]:
    settings = get_settings()
    bot_token = await _get_slack_bot_token(ctx.agent_id, pool)
    if not bot_token:
        return {"error": "no Slack connection for this agent"}

    from . import mcp_client

    return await mcp_client.call_tool(
        command=settings.slack_mcp_command,
        tool_name=name,
        arguments=args,
        env={"SLACK_BOT_TOKEN": bot_token},
    )


async def _get_github_install_token(agent_id: str, pool: asyncpg.Pool) -> str | None:
    """Returns a non-expired GitHub install token for the agent's connection.
    Refreshes via the control plane's `/api/connections/github/{id}/refresh-token`
    when the stored token is within 5 min of expiry (or already expired).

    GitHub install tokens have a 1-hour TTL. Without refresh, every agent
    investigation after the first hour 401s on github_* tool calls.
    """
    from datetime import datetime, timedelta, timezone

    from . import crypto_runtime

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.id, c.credentials_encrypted, c.config
              FROM agents a
              JOIN connections c ON c.id = a.github_connection_id
             WHERE a.id = $1
            """,
            UUID(agent_id),
        )
    if row is None:
        return None

    cfg = row["config"]
    if isinstance(cfg, str):
        import json as _json
        cfg = _json.loads(cfg)
    cfg = cfg or {}

    expires_raw = cfg.get("expires_at")
    needs_refresh = True
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            # 5-minute buffer so we don't hand out tokens that expire mid-call
            needs_refresh = expires_at - now < timedelta(minutes=5)
        except Exception:
            needs_refresh = True

    if not needs_refresh and row["credentials_encrypted"]:
        try:
            return crypto_runtime.decrypt_str(row["credentials_encrypted"])
        except Exception:
            pass  # fall through to refresh

    # Refresh via the control plane's internal endpoint.
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.control_plane_url}/api/connections/github/{row['id']}/refresh-token",
                headers={"X-Tigerlite-Internal": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["token"]
    except Exception as e:
        log.warning("github token refresh failed", err=str(e), conn_id=str(row["id"]))
        # As a last resort, return the (possibly expired) cached token —
        # github_mcp will surface a clear 401 error to the agent.
        if row["credentials_encrypted"]:
            try:
                return crypto_runtime.decrypt_str(row["credentials_encrypted"])
            except Exception:
                return None
        return None


async def _get_slack_bot_token(agent_id: str, pool: asyncpg.Pool) -> str | None:
    from . import crypto_runtime

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.credentials_encrypted
              FROM agents a
              JOIN connections c ON c.id = a.slack_connection_id
             WHERE a.id = $1
            """,
            UUID(agent_id),
        )
    if row is None or not row["credentials_encrypted"]:
        return None
    try:
        return crypto_runtime.decrypt_str(row["credentials_encrypted"])
    except Exception:
        return None


# ----------------------------------------------------------
# Internal tool implementations
# ----------------------------------------------------------

async def _query_telemetry(
    args: dict[str, Any], ctx: ToolContext, http: httpx.AsyncClient
) -> dict[str, Any]:
    settings = get_settings()
    resp = await http.post(
        f"{settings.control_plane_url}/internal/telemetry/query",
        headers={"X-Tigerlite-Internal": "1"},
        json={"tenant_id": ctx.tenant_id, "sql": args["sql"], "artifact": True},
        timeout=settings.agent_tool_timeout_seconds,
    )
    resp.raise_for_status()
    return resp.json()


async def _read_artifact(args: dict[str, Any], http: httpx.AsyncClient) -> dict[str, Any]:
    settings = get_settings()
    resp = await http.post(
        f"{settings.control_plane_url}/internal/telemetry/read_artifact",
        headers={"X-Tigerlite-Internal": "1"},
        json=args,
        timeout=settings.agent_tool_timeout_seconds,
    )
    resp.raise_for_status()
    return resp.json()


async def _record_finding(
    args: dict[str, Any], ctx: ToolContext, pool: asyncpg.Pool
) -> dict[str, Any]:
    sig = hashlib.sha256(
        f"{args['title']}|{args.get('severity')}".encode()
    ).hexdigest()[:16]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO findings (
                tenant_id, agent_id, session_id, title, summary, severity,
                evidence, suggested_action, signature
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9
            ) RETURNING id
            """,
            UUID(ctx.tenant_id),
            UUID(ctx.agent_id),
            UUID(ctx.session_id),
            args["title"],
            args["summary"],
            args["severity"],
            json.dumps(args["evidence"], default=str),
            args.get("suggested_action"),
            sig,
        )
    return {"finding_id": str(row["id"]), "signature": sig}


async def _create_issue(
    args: dict[str, Any], ctx: ToolContext, pool: asyncpg.Pool
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        # Dedup: if an open issue with the same signature exists, return it.
        existing = await conn.fetchrow(
            """
            SELECT id FROM issues
             WHERE tenant_id = $1 AND agent_id = $2 AND signature = $3
               AND status IN ('open', 'verifying')
             LIMIT 1
            """,
            UUID(ctx.tenant_id),
            UUID(ctx.agent_id),
            args["signature"],
        )
        if existing:
            return {"issue_id": str(existing["id"]), "deduped": True}

        row = await conn.fetchrow(
            """
            INSERT INTO issues (
                tenant_id, agent_id, title, summary, severity, status,
                opened_by_session_id, signature,
                next_verification_at, verification_attempts
            ) VALUES (
                $1, $2, $3, $4, $5, 'verifying',
                $6, $7,
                now() + interval '10 minutes', 0
            ) RETURNING id
            """,
            UUID(ctx.tenant_id),
            UUID(ctx.agent_id),
            args["title"],
            args["summary"],
            args["severity"],
            UUID(ctx.session_id),
            args["signature"],
        )
        # Point the agent's current_issue_id at the new issue.
        await conn.execute(
            "UPDATE agents SET current_issue_id = $1 WHERE id = $2",
            row["id"],
            UUID(ctx.agent_id),
        )
    return {"issue_id": str(row["id"]), "deduped": False}


async def _update_memory(
    args: dict[str, Any], ctx: ToolContext, pool: asyncpg.Pool
) -> dict[str, Any]:
    """Phase 3: patch the agent's memory blob in the snapshots bucket."""
    from . import object_store
    from .objects import canonical_bytes

    # Read current memory ref
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT memory_ref FROM agents WHERE id = $1",
            UUID(ctx.agent_id),
        )
    cur: dict[str, Any] = {}
    if row and row["memory_ref"]:
        try:
            blob = await object_store.get(row["memory_ref"])
            cur = json.loads(blob)
        except Exception:
            cur = {}

    # Merge patch
    patch = args.get("patch", {})
    if not isinstance(patch, dict):
        return {"error": "patch must be an object"}
    cur.update(patch)
    cur["updated_at"] = datetime.now(timezone.utc).isoformat()

    blob = canonical_bytes(cur)
    h = hashlib.sha256(blob).hexdigest()
    key = f"agents/{ctx.agent_id}/memory/{h}.json"
    await object_store.put(key, blob, content_type="application/json")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agents SET memory_ref = $1 WHERE id = $2",
            key,
            UUID(ctx.agent_id),
        )
    return {"memory_ref": key, "merged_keys": list(patch.keys())}


async def _post_to_slack(
    args: dict[str, Any], ctx: ToolContext, pool: asyncpg.Pool
) -> dict[str, Any]:
    """Post via the configured Slack MCP, falling back to direct Web API call.

    Phase 2 wires the Slack MCP. For Phase 1 we just stash the message on the
    session as a finding-style record so the dashboard can render it.
    """
    settings = get_settings()
    async with pool.acquire() as conn:
        agent = await conn.fetchrow(
            """
            SELECT a.slack_channel, a.slack_connection_id, c.credentials_encrypted
              FROM agents a
              LEFT JOIN connections c ON c.id = a.slack_connection_id
             WHERE a.id = $1
            """,
            UUID(ctx.agent_id),
        )

    if not agent or not agent["slack_channel"]:
        return {"posted": False, "reason": "no slack channel configured"}

    if not agent["credentials_encrypted"]:
        # No real token; record locally and return.
        log.info("slack-post-skipped (no credentials)", channel=agent["slack_channel"])
        return {"posted": False, "reason": "no credentials"}

    # Decrypt and call Slack Web API directly. (MCP-based posting is wired in Phase 2.)
    from . import crypto_runtime
    token = crypto_runtime.decrypt_str(agent["credentials_encrypted"])

    payload = {
        "channel": agent["slack_channel"],
        "text": f"*{args['title']}*\n{args['summary']}",
    }
    async with httpx.AsyncClient(timeout=settings.agent_tool_timeout_seconds) as http:
        resp = await http.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        data = resp.json()
    if not data.get("ok"):
        return {"posted": False, "error": data.get("error")}
    thread_ts = data.get("ts")

    # Record the thread on the session so replies resume it.
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET slack_thread_ts = $1 WHERE id = $2",
            thread_ts,
            UUID(ctx.session_id),
        )
    return {"posted": True, "thread_ts": thread_ts}


async def _prepare_fix_handoff(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Phase 4. Just shape the bundle; the actual prompt rendering happens in
    the issues route when the user clicks the button."""
    return {
        "ok": True,
        "session_id": ctx.session_id,
        "agent_id": ctx.agent_id,
        "bundle": {
            "root_cause": args.get("root_cause"),
            "affected_files": args.get("affected_files", []),
            "expected_behavior": args.get("expected_behavior"),
            "recovery_criteria": args.get("recovery_criteria", {}),
        },
    }


# ----------------------------------------------------------
# MCP discovery (Phase 2)
# ----------------------------------------------------------

async def discover_mcp_tools(agent_id: str, pool: asyncpg.Pool) -> list[dict[str, Any]]:
    """At the start of each step, look up which MCP servers are connected
    for the agent's tenant and append their tool declarations.

    Spawns each MCP server via stdio, calls tools/list, tears it down. The
    set of MCP tool names is cached at module level so execute_tool can
    route by name.
    """
    settings = get_settings()
    decls: list[dict[str, Any]] = []

    # GitHub
    gh_token = await _get_github_install_token(agent_id, pool)
    if gh_token:
        from . import mcp_client

        try:
            gh_decls = await mcp_client.list_tool_decls(
                command=settings.github_mcp_command,
                args=["stdio", "--read-only"],
                env={"GITHUB_PERSONAL_ACCESS_TOKEN": gh_token},
            )
            decls.extend(gh_decls)
            _MCP_TOOL_NAMES_GITHUB.update(d["name"] for d in gh_decls)
        except Exception as e:
            log.warning("github mcp discovery failed", err=str(e))

    # Slack
    slack_token = await _get_slack_bot_token(agent_id, pool)
    if slack_token:
        from . import mcp_client

        try:
            sl_decls = await mcp_client.list_tool_decls(
                command=settings.slack_mcp_command,
                env={"SLACK_BOT_TOKEN": slack_token},
            )
            decls.extend(sl_decls)
            _MCP_TOOL_NAMES_SLACK.update(d["name"] for d in sl_decls)
        except Exception as e:
            log.warning("slack mcp discovery failed", err=str(e))

    return decls
