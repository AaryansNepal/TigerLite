"""Agent runtime — orchestrates the snapshot-based investigation loop.

Each run_cycle():
1. Load (or create) the latest snapshot for the session
2. Replay all previous messages from the object store
3. Add a trigger message
4. Call OpenAI GPT-4o with tools in a loop
5. Execute tool calls, store results
6. Save a new immutable snapshot with all new message hashes
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from openai import OpenAI

from ..config import OPENAI_API_KEY, OPENAI_MODEL
from ..query import query_customer_health, run_sql
from .object_store import ObjectStore
from .prompts import SYSTEM_PROMPT
from .snapshot import Snapshot, SnapshotStore
from .tools import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, catalog):
        self.catalog = catalog
        self.object_store = ObjectStore()
        self.snapshot_store = SnapshotStore()
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        self.findings: list[dict] = []
        self._event_callback = None

    def set_event_callback(self, callback):
        """Set a callback for SSE events: callback(event_type, data)"""
        self._event_callback = callback

    def _emit(self, event_type: str, data: dict):
        if self._event_callback:
            self._event_callback(event_type, data)

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool call and return the result as a string."""
        if name == "query_duckdb":
            sql = args.get("sql", "")
            self._emit("tool_call", {"tool": "query_duckdb", "sql": sql})
            result = run_sql(self.catalog, sql)
            return json.dumps(result, default=str)

        elif name == "get_customer_list":
            self._emit("tool_call", {"tool": "get_customer_list"})
            result = query_customer_health(self.catalog)
            return json.dumps(result, default=str)

        elif name == "create_finding":
            finding = {
                "id": str(uuid.uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
                **args,
            }
            self.findings.append(finding)
            self._emit("finding", finding)
            logger.info(f"Finding created: {args.get('title')}")
            return json.dumps({"status": "finding_created", "finding_id": finding["id"]})

        return json.dumps({"error": f"Unknown tool: {name}"})

    def run_cycle(self, session_id: Optional[str] = None) -> dict:
        """Run one agent investigation cycle."""
        if not self.client:
            return {"error": "OpenAI API key not configured"}

        if not session_id:
            session_id = str(uuid.uuid4())

        self._emit("cycle_start", {"session_id": session_id})

        # Load or create snapshot
        latest_version = self.snapshot_store.get_latest_version(session_id)
        if latest_version is not None:
            parent_snapshot = self.snapshot_store.load(session_id, latest_version)
            parent_version = latest_version
            # Replay previous messages
            previous_objects = self.snapshot_store.replay(session_id, self.object_store)
        else:
            parent_version = None
            previous_objects = []

        base_version = latest_version or 0
        new_descriptors = []

        # Build message history
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add replayed messages
        for obj in previous_objects:
            if obj.get("type") == "message":
                messages.append(obj["message"])

        # Add trigger message
        trigger = {
            "role": "user",
            "content": (
                f"Run anomaly detection cycle at {datetime.now(timezone.utc).isoformat()}. "
                "Investigate all customers for latency anomalies, error rate spikes, "
                "and deploy-correlated regressions. Be thorough and methodical."
            ),
        }
        messages.append(trigger)

        # Store trigger
        sha = self.object_store.put({"type": "message", "message": trigger})
        new_descriptors.append(sha)

        # OpenAI tool calling loop — save a snapshot after each iteration
        max_iterations = 10
        current_version = base_version
        for i in range(max_iterations):
            self._emit("llm_call", {"iteration": i + 1, "session_id": session_id})

            try:
                response = self.client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                )
            except Exception as e:
                logger.error(f"OpenAI API error: {e}")
                self._emit("error", {"message": str(e)})
                break

            choice = response.choices[0]
            assistant_message = choice.message

            # Store assistant message
            msg_dict = {"role": "assistant", "content": assistant_message.content or ""}
            if assistant_message.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_message.tool_calls
                ]

            sha = self.object_store.put({"type": "message", "message": msg_dict})
            new_descriptors.append(sha)
            messages.append(msg_dict)

            # If no tool calls, agent is done — save final snapshot
            if not assistant_message.tool_calls:
                if assistant_message.content:
                    self._emit("agent_message", {"content": assistant_message.content})
                current_version += 1
                snapshot = Snapshot(
                    session_id=session_id,
                    version=current_version,
                    parent_version=current_version - 1 if current_version > 1 else None,
                    status="completed",
                    descriptors=list(new_descriptors),
                    metadata={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "findings_count": len(self.findings),
                    },
                )
                self.snapshot_store.save(snapshot)
                break

            # Execute tool calls
            for tool_call in assistant_message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                logger.info(f"Executing tool: {fn_name}")
                result = self._execute_tool(fn_name, fn_args)

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
                sha = self.object_store.put({"type": "message", "message": tool_msg})
                new_descriptors.append(sha)
                messages.append(tool_msg)

            # Save intermediate snapshot after this reasoning step
            current_version += 1
            snapshot = Snapshot(
                session_id=session_id,
                version=current_version,
                parent_version=current_version - 1 if current_version > 1 else None,
                status="running",
                descriptors=list(new_descriptors),
                metadata={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "findings_count": len(self.findings),
                },
            )
            self.snapshot_store.save(snapshot)

        else:
            # Max iterations reached — save final snapshot
            current_version += 1
            snapshot = Snapshot(
                session_id=session_id,
                version=current_version,
                parent_version=current_version - 1 if current_version > 1 else None,
                status="completed",
                descriptors=list(new_descriptors),
                metadata={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "findings_count": len(self.findings),
                },
            )
            self.snapshot_store.save(snapshot)

        self._emit("cycle_complete", {
            "session_id": session_id,
            "version": current_version,
            "findings_count": len(self.findings),
        })

        return {
            "session_id": session_id,
            "version": current_version,
            "findings": self.findings.copy(),
            "status": "completed",
        }
