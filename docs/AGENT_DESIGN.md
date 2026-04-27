# Agent design

This doc covers the heart of TigerLite: what an "agent" is, how the snapshot loop works, how the worker is structured, and how triggers, memory, and tools fit together. The other docs reference this one frequently — keep it canonical.

## The two definitions of "agent"

The word "agent" gets used for two distinct things. Be explicit about which one is meant in any given sentence.

**Agent as a resource.** A row in Postgres. Has a name, a plain-language objective, a `plan` field (user-editable runbook), a `scope_config` jsonb (which OTel signals it watches, what "good" looks like), a list of authorized connections, a status (active/paused), and a `memory_ref` pointing at its accumulated memory in S3. This is what the user creates when they click "New Agent" and type "checkout flow should always be fast." It's persistent. It exists whether or not anything is currently running.

**Agent as a runtime pattern.** The snapshot loop. Stateless, repeating compute that reads conversation state from S3, asks Gemini what to do next, executes one tool, writes new state. The runtime has no memory of which agent it's serving — it's a pure function from snapshot to snapshot.

These two are connected by a simple rule: **the runtime never holds state about the agent. All state lives in S3 (and Postgres). The runtime is replaceable, ephemeral, stateless.**

## Data model: snapshots and objects

A **session** is one investigation episode — starts when a trigger fires, ends when the agent reaches a terminal state (resolved, escalated, max steps).

A **snapshot** is a manifest — an ordered list of object references. Snapshots are immutable; you never modify snapshot N. You write snapshot N+1 that contains everything snapshot N had plus new objects.

An **object** is a single unit of conversation state. Each object has a type and a content-addressable hash (SHA-256 of canonical JSON). Same content always yields the same hash, always the same S3 key.

Object types:

```python
class ObjectType(str, Enum):
    SYSTEM_PROMPT = "system_prompt"      # the agent's identity + plan + memory
    TRIGGER_EVENT = "trigger_event"      # what woke the agent up
    USER_MESSAGE = "user_message"        # human follow-up (e.g. Slack reply)
    ASSISTANT_MESSAGE = "assistant_msg"  # LLM text output
    TOOL_CALL = "tool_call"              # LLM asked to call a tool
    TOOL_RESULT = "tool_result"          # result of executing the tool
    REASONING = "reasoning"              # optional: LLM's chain-of-thought
```

A session evolution looks like:

```
Snapshot 0 (right after trigger):
  objects: [obj_a1b2..., obj_c3d4...]
  - obj_a1b2: {type: "system_prompt", content: "You are an agent watching <plan>..."}
  - obj_c3d4: {type: "trigger_event", content: {kind: "anomaly", ...}}

Snapshot 1 (after one worker step):
  objects: [obj_a1b2..., obj_c3d4..., obj_e5f6..., obj_g7h8...]
  - (prior two)
  - obj_e5f6: {type: "assistant_message", content: "Let me check error rates."}
  - obj_g7h8: {type: "tool_call", content: {tool: "query_telemetry", args: {...}}}

Snapshot 2 (after next step — tool resolved):
  objects: [..., obj_i9j0...]
  - (prior four)
  - obj_i9j0: {type: "tool_result", content: {rows: [...], artifact_id: "..."}}
```

Each snapshot is small (just a manifest of hashes). Objects are stored separately and shared across snapshots — no duplication. Replaying a snapshot means loading each referenced object and concatenating into the LLM's conversation history.

## The snapshot loop — one cycle

```
                         ┌─────────────────────┐
                         │  Trigger received   │
                         └──────────┬──────────┘
                                    ▼
                         ┌─────────────────────┐
                         │  Read snapshot N    │
                         │  Replay objects     │
                         └──────────┬──────────┘
                                    ▼
                         ┌─────────────────────┐
                         │  Call Gemini        │
                         │  with state + tools │
                         └──────────┬──────────┘
                                    ▼
                         ┌─────────────────────┐
                         │  Execute tool call  │
                         │  (DuckDB / MCP)     │
                         └──────────┬──────────┘
                                    ▼
                         ┌─────────────────────┐
                         │  Compose new objects│
                         │  Write snapshot N+1 │
                         └──────────┬──────────┘
                                    │
                          (loop or terminate)
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Trigger next cycle │
                         └─────────────────────┘
```

Each iteration is a pure function: `(snapshot_id) → next_snapshot_id`. No state held by the worker between iterations. If the worker crashes mid-step, the next worker reads snapshot N and tries the step again. Snapshots are immutable, so retries are safe by construction.

## Worker — pseudocode

This is the entire agent runtime. Everything else (anomaly watcher, trigger router, tool implementations) is supporting infrastructure around this loop.

```python
# services/agent-runtime/worker.py

import asyncio
from .run_step import run_one_step
from .queue import Queue, Job

async def run_worker(worker_id: str):
    queue = Queue()
    while True:
        job: Job = await queue.consume(consumer_id=worker_id)
        if job is None:
            await asyncio.sleep(1)
            continue
        try:
            await run_one_step(job.payload["snapshot_id"])
            await queue.ack(job.id)
        except TerminalSignal:
            await queue.ack(job.id)
        except Exception as e:
            log.error("step failed", job_id=job.id, exc_info=e)
            await queue.nack(job.id)  # release lock, will retry after visibility timeout

# services/agent-runtime/run_step.py

async def run_one_step(snapshot_id: str) -> str | None:
    """Pure function: snapshot in, snapshot out. Returns next snapshot_id or None if terminal."""
    snapshot = await s3.read_snapshot(snapshot_id)
    objects = await asyncio.gather(*[s3.read_object(h) for h in snapshot.object_hashes])
    
    # rebuild what Gemini will see
    messages = replay_to_gemini_format(objects)
    tools = await discover_tools(snapshot.agent_id)  # internal + MCP
    
    response = await gemini.generate(
        model="gemini-2.5-pro",
        messages=messages,
        tools=tools,
    )
    
    new_objects = [make_assistant_object(response.text, response.reasoning)]
    
    if response.tool_calls:
        for call in response.tool_calls:
            new_objects.append(make_tool_call_object(call))
            result = await execute_tool(call, snapshot.agent_id, snapshot.tenant_id)
            new_objects.append(make_tool_result_object(call.id, result))
    
    if response.is_terminal or len(snapshot.object_hashes) > MAX_STEPS:
        await finalize_session(snapshot.session_id, snapshot.agent_id)
        raise TerminalSignal()
    
    new_hashes = await asyncio.gather(*[s3.write_object(o) for o in new_objects])
    
    next_snapshot = Snapshot(
        agent_id=snapshot.agent_id,
        tenant_id=snapshot.tenant_id,
        session_id=snapshot.session_id,
        version=snapshot.version + 1,
        object_hashes=snapshot.object_hashes + new_hashes,
    )
    next_snapshot_id = await s3.write_snapshot_atomic(next_snapshot)
    
    await queue.enqueue(
        kind="snapshot_ready",
        payload={"snapshot_id": next_snapshot_id},
    )
    return next_snapshot_id
```

That's the agent runtime. ~30 lines of meaningful logic. Treat any expansion beyond this as a code smell — supporting infrastructure (tool implementations, MCP discovery, queue management) lives outside.

## Lambda alternative — same function, different driver

If you ever want to migrate to the Firetiger architecture exactly:

```python
# services/agent-runtime/lambda_handler.py

def handler(event, context):
    # S3 event notification triggers this Lambda when a snapshot manifest is written
    snapshot_id = parse_s3_event_key(event)
    asyncio.run(run_one_step(snapshot_id))
    # the new snapshot write inside run_one_step triggers the next Lambda automatically
```

That's it. Same `run_one_step`. Lambda concurrency replaces queue concurrency. S3 events replace queue messages. The agent state model is unchanged. **Do not implement Lambda for the demo.** Note the option in the README and move on.

## Triggers — three sources, one queue

```
┌─────────────────────┐
│   Anomaly watcher   │  Python process, runs every 60s.
│                     │  For each active agent, runs scope query against
│                     │  DuckDB, compares to baseline. On deviation,
│                     │  pushes {kind: "anomaly", agent_id, evidence}.
└──────────┬──────────┘
           │
┌─────────────────────┐
│   Cron scheduler    │  APScheduler in Python.
│                     │  Per-agent schedules (default: hourly).
│                     │  Verification sessions also use cron.
│                     │  Pushes {kind: "cron", agent_id, reason}.
└──────────┬──────────┘
           │              ┌──────────────────┐         ┌────────────────────┐
┌──────────┴──────────┐   │                  │         │                    │
│   Slack webhook     │──▶│   Job queue      │────────▶│   Trigger router   │
│                     │   │   (Postgres)     │         │                    │
│   POST /api/slack   │   │                  │         └─────────┬──────────┘
│   → enqueue events  │   └──────────────────┘                   │
└─────────────────────┘                                          ▼
                                                       ┌────────────────────┐
                                                       │  Initial snapshot  │
                                                       │  written to S3     │
                                                       └────────────────────┘
                                                                 │
                                                                 ▼
                                                       (kicks off worker loop)
```

The **trigger router** decides:

- *Which agent does this concern?* For anomalies and cron, the message says. For Slack, look up the channel/thread → agent mapping.
- *New session or resume?* Slack reply in an existing thread → resume. Anomaly while a session is already investigating the same scope → ignore (the agent is already on it). Otherwise → new session.
- *Compose initial snapshot.* System prompt + agent's `plan` + agent's memory + the trigger event details. Write to S3.

The S3 write produces a snapshot ID; router pushes `{kind: "snapshot_ready", snapshot_id}` to the queue. Workers pick it up.

## Memory between sessions

Every agent has a `memory_ref` column in Postgres pointing at its current memory snapshot in S3. Memory is also content-addressed — a new memory yields a new hash, the column is updated.

What's in memory:

- **Rolling baselines** — for each watched signal, the recent percentile distribution. Used so the agent knows what "normal" looks like for *this* tenant.
- **Recent findings** — last N findings, deduplicated by signature. Lets the agent recognize repeats: "this looks like the cart-OOM pattern from last week."
- **Self-written runbooks** — the agent can `update_memory(runbook="when payment latency spikes, first check Stripe status")` based on past investigations. Prepended to system prompt.

Loaded at session start, included in `system_prompt` object. Updated at session end based on `record_finding` calls in that session.

For the demo, **start simple**: just rolling baselines + last 50 findings. The runbook-writing capability is nice-to-have, defer until Phase 3+.

## The toolbox — small, generic, composable

Achille's principle from "How Firetiger works": *a small set of generic tools that the agent has a deep understanding of will always outperform a long list of specialized ones.* Don't make `get_top_5_slow_endpoints` — let the agent express that as `query_telemetry(SELECT endpoint, p95(latency_ms) FROM traces ... GROUP BY 1 ORDER BY 2 DESC LIMIT 5)`.

### Internal tools (implemented in agent runtime)

```python
# Telemetry exploration
query_telemetry(sql: str) -> {rows, columns, artifact_id}
read_artifact(id: str, jq: str | None = None, line_range: tuple | None = None) -> str

# Output / state
record_finding(title, summary, severity, evidence, suggested_action) -> finding_id
create_issue(title, summary, severity, evidence, suggested_action) -> issue_id
update_memory(key, value)  # writes to agent memory
```

### MCP tools (discovered per-step)

GitHub MCP server (`github/github-mcp-server`):

```
list_recent_commits(owner, repo, since)
get_commit_diff(owner, repo, sha)
read_file(owner, repo, path, ref?, line_start?, line_end?)
search_code(owner, repo, query)
create_pull_request(...)   # Phase 4 only
```

Slack MCP server:

```
post_message(channel, blocks)
post_in_thread(channel, thread_ts, blocks)
read_thread_history(channel, thread_ts)
```

## Tool result handling — truncate + saved artifacts

This is non-optional. Real DuckDB queries return rows with embedded JSON, stack traces, high-cardinality attributes. A single `SELECT * FROM traces WHERE service='checkout' LIMIT 100` will easily blow 40,000 tokens. From Firetiger's "Agent Engineering Patterns" post — the saved-artifact approach delivered 5x speedup and 94% one-shot accuracy versus 50% for naive truncation.

Implementation pattern for `query_telemetry`:

```python
async def query_telemetry(sql: str, agent_id: str, tenant_id: str) -> dict:
    # Tenant scoping (CRITICAL — never let agent bypass this)
    sql = enforce_tenant_filter(sql, tenant_id)
    
    rows = await duckdb_run(sql)
    columns = [...]
    
    # Tokenize the result preview
    full_json = json.dumps(rows)
    tokens = estimate_tokens(full_json)  # use tiktoken for rough estimate
    
    # Save full result as artifact (always — even if it would fit)
    artifact_id = await s3.write_artifact(
        content=full_json,
        content_type="application/json",
    )
    
    if tokens > 5000:
        # Return preview + artifact reference
        preview_rows = rows[:5]
        return {
            "summary": f"Query returned {len(rows)} rows × {len(columns)} columns",
            "columns": columns,
            "preview_rows": preview_rows,
            "artifact_id": artifact_id,
            "note": (
                "Full result is too large for context. Use read_artifact "
                f"with jq filter to inspect, e.g. read_artifact('{artifact_id}', "
                "jq='.[0:10]') or read_artifact('{artifact_id}', jq='group_by(.service) "
                "| map({service: .[0].service, count: length})')."
            ),
        }
    else:
        return {
            "rows": rows,
            "columns": columns,
            "artifact_id": artifact_id,  # still return so agent can re-query later
        }
```

`read_artifact` runs `gojq` (via subprocess) over the stored JSON. Per the Firetiger post, Gemini and other models reliably write sophisticated jq filters with no parsing errors in production.

## System prompt structure

The `system_prompt` object that opens every session is built from these components. Order matters — Gemini weights early tokens more.

```
You are an autonomous operations agent for the TigerLite platform.

## Your identity
Name: {agent.name}
Tenant: {tenant.name}

## Your plan (user-defined)
{agent.plan}

## Your scope
{agent.scope_config rendered as readable text}

## Your memory from prior sessions
{baselines, recent findings summary, runbooks}

## Your tools
You have these tools available. Use them iteratively to investigate.
- query_telemetry(sql): runs DuckDB SQL against this tenant's traces, logs, and metrics tables.
- read_artifact(id, jq?): re-reads a stored tool result with an optional jq filter.
- list_recent_commits, get_commit_diff, read_file: inspect the tenant's GitHub repo.
- post_to_slack: notify the user.
- record_finding, create_issue: record what you've discovered.

## Available tables
{auto-discovered list of OTel tables and columns for this tenant}

## How to investigate
1. Read the trigger event carefully.
2. Form a hypothesis. Use query_telemetry to test it.
3. If telemetry suggests a recent change caused the issue, check recent commits.
4. If you have high confidence, record_finding and post_to_slack.
5. If you don't have enough information, say so plainly. Don't speculate.

Be terse. Use specific numbers, specific commit SHAs, specific file paths.
Don't fabricate. If a tool returns no data, say so.
```

The agent's plan field (Image 5 in the screenshots) is concatenated in. This is what makes plain-language agent definitions actually trustworthy — the user's plan is the agent's playbook.

## Trigger event structure

The trigger event object differs by source:

```python
# Anomaly trigger
{
  "type": "trigger_event",
  "kind": "anomaly",
  "metric": "p95_latency_ms",
  "service": "checkout",
  "endpoint": "/api/checkout",
  "current_value": 2400,
  "baseline": {"p50": 240, "p95": 380, "p99": 520},
  "window": "last_5_minutes",
  "detected_at": "2026-04-27T16:34:12Z",
}

# Cron trigger
{
  "type": "trigger_event",
  "kind": "scheduled",
  "reason": "hourly_check",
  "scheduled_at": "2026-04-27T17:00:00Z",
}

# Slack trigger
{
  "type": "trigger_event",
  "kind": "slack_message",
  "from_user": "U123ABC",
  "channel": "C456DEF",
  "thread_ts": "1745764800.001234",
  "text": "@checkout-monitor what's the latency look like right now?",
}
```

Each kind drives a different opening behavior from the agent. The system prompt is general; the trigger event is what tells the agent what's actually happening.

## Concurrency and safety

**Atomic snapshot writes via `If-None-Match`**: when writing snapshot version N+1, set `If-None-Match: *` so the write fails if another writer already created version N+1. Only one writer wins. Losing writer reads the new state and decides what to do (usually: nothing — work was already done).

**Tenant isolation**: every storage path is `{tenant_id}/...`. Every DuckDB query has a tenant filter enforced by a wrapper. Every API call validates the calling user's tenant. Don't trust query parameters or args from the LLM for tenant scoping.

**Tool execution timeouts**: every tool has a hard timeout (default 60s, configurable per tool). Long-running queries are killed and surface as `tool_result` with `error: "timeout"` so the agent can adapt.

**MAX_STEPS guard**: every session has a hard step ceiling (default 30). When hit, agent is forced to `record_finding` with whatever it has and terminate. Prevents runaway loops.
