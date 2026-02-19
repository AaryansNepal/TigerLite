"""Agent runtime — orchestrates the snapshot-based investigation loop.

Each run_cycle():
1. Load (or create) the latest snapshot for the session
2. Replay all previous messages from the object store
3. Add a trigger message
4. Call Gemini with tools in a loop
5. Execute tool calls, store results
6. Save a new immutable snapshot with all new message hashes
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from google import genai
from google.genai import types

from ..config import GEMINI_API_KEY, GEMINI_MODEL
from ..query import query_customer_health, run_sql
from .object_store import ObjectStore
from .prompts import SYSTEM_PROMPT
from .snapshot import Snapshot, SnapshotStore
from .tools import TOOL_DECLARATIONS

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, catalog):
        self.catalog = catalog
        self.object_store = ObjectStore()
        self.snapshot_store = SnapshotStore()
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
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

    def _stored_to_content(self, stored_msg: dict) -> types.Content:
        """Convert a stored message dict back to a Gemini Content object for replay."""
        role = stored_msg["role"]

        if role == "user":
            return types.Content(
                role="user",
                parts=[types.Part(text=stored_msg["text"])],
            )
        elif role == "model":
            parts = []
            if stored_msg.get("text"):
                parts.append(types.Part(text=stored_msg["text"]))
            for fc in stored_msg.get("function_calls", []):
                parts.append(types.Part(
                    function_call=types.FunctionCall(
                        name=fc["name"], args=fc["args"],
                    )
                ))
            return types.Content(role="model", parts=parts)
        elif role == "function_response":
            parts = [
                types.Part(
                    function_response=types.FunctionResponse(
                        name=r["name"], response=r["response"],
                    )
                )
                for r in stored_msg["responses"]
            ]
            return types.Content(parts=parts)

        # Fallback
        return types.Content(role="user", parts=[types.Part(text=str(stored_msg))])

    def run_cycle(self, session_id: Optional[str] = None) -> dict:
        """Run one agent investigation cycle."""
        if not self.client:
            return {"error": "Gemini API key not configured"}

        if not session_id:
            session_id = str(uuid.uuid4())

        self._emit("cycle_start", {"session_id": session_id})

        # Load or create snapshot
        latest_version = self.snapshot_store.get_latest_version(session_id)
        if latest_version is not None:
            parent_snapshot = self.snapshot_store.load(session_id, latest_version)
            parent_version = latest_version
            previous_objects = self.snapshot_store.replay(session_id, self.object_store)
        else:
            parent_version = None
            previous_objects = []

        base_version = latest_version or 0
        new_descriptors = []

        # Build contents for Gemini (system instruction is passed separately)
        contents = []

        # Add replayed messages
        for obj in previous_objects:
            if obj.get("type") == "message":
                contents.append(self._stored_to_content(obj["message"]))

        # Add trigger message
        trigger_text = (
            f"Run anomaly detection cycle at {datetime.now(timezone.utc).isoformat()}. "
            "Investigate all customers for latency anomalies, error rate spikes, "
            "and deploy-correlated regressions. Be thorough and methodical."
        )
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=trigger_text)],
        ))

        # Store trigger
        sha = self.object_store.put({"type": "message", "message": {"role": "user", "text": trigger_text}})
        new_descriptors.append(sha)

        # Gemini tool calling loop — save a snapshot after each iteration
        max_iterations = 10
        current_version = base_version
        for i in range(max_iterations):
            self._emit("llm_call", {"iteration": i + 1, "session_id": session_id})

            try:
                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=[TOOL_DECLARATIONS],
                    ),
                )
            except Exception as e:
                logger.error(f"Gemini API error: {e}")
                self._emit("error", {"message": str(e)})
                break

            candidate = response.candidates[0]
            model_content = candidate.content

            # Parse response: extract text and function calls
            function_calls = []
            text_parts = []
            for part in model_content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)
                if part.text:
                    text_parts.append(part.text)

            text_content = " ".join(text_parts) if text_parts else ""

            # Store model message for snapshot
            stored_msg = {"role": "model", "text": text_content}
            if function_calls:
                stored_msg["function_calls"] = [
                    {"name": fc.name, "args": dict(fc.args)} for fc in function_calls
                ]

            sha = self.object_store.put({"type": "message", "message": stored_msg})
            new_descriptors.append(sha)
            contents.append(model_content)

            # If no tool calls, agent is done — save final snapshot
            if not function_calls:
                if text_content:
                    self._emit("agent_message", {"content": text_content})
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

            # Execute tool calls and build function response
            fn_response_parts = []
            stored_responses = []
            for fc in function_calls:
                fn_name = fc.name
                fn_args = dict(fc.args)
                logger.info(f"Executing tool: {fn_name}")
                result_str = self._execute_tool(fn_name, fn_args)

                fn_response_parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"result": result_str},
                    )
                ))
                stored_responses.append({
                    "name": fn_name,
                    "response": {"result": result_str},
                })

            # Store function responses for snapshot
            sha = self.object_store.put({
                "type": "message",
                "message": {"role": "function_response", "responses": stored_responses},
            })
            new_descriptors.append(sha)

            # Add function responses to conversation
            contents.append(types.Content(parts=fn_response_parts))

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
