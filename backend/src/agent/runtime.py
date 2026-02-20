"""Agent runtime — orchestrates the snapshot-based investigation loop.

Each run_cycle():
1. Load (or create) the latest snapshot for the session
2. Replay all previous messages from the object store
3. Add a trigger message with the specific customer + reason
4. Call Gemini with tools in a loop
5. Execute tool calls, store results
6. Save a new immutable snapshot after each step
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
from .prompts import build_system_prompt
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

    def _execute_tool(self, name: str, args: dict, session_id: str) -> str:
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
                "session_id": session_id,
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

        return types.Content(role="user", parts=[types.Part(text=str(stored_msg))])

    def _build_trigger(self, customer_id: Optional[str], reason: Optional[str],
                       error_rate: Optional[float], avg_latency: Optional[float]) -> str:
        """Build the trigger message based on what we know."""
        now = datetime.now(timezone.utc).isoformat()

        if customer_id and reason:
            # Targeted investigation — triggered by Go anomaly detector
            parts = [f"ALERT at {now}: Anomaly detected for customer {customer_id}."]
            if error_rate is not None:
                parts.append(f"Current error rate: {error_rate:.1%}.")
            if avg_latency is not None:
                parts.append(f"Current avg latency: {avg_latency:.0f}ms.")
            parts.append(
                "Investigate this customer specifically. Query the telemetry data to find: "
                "1) When did the degradation start? "
                "2) Which endpoints are affected? "
                "3) Is it correlated with a deploy version? "
                "4) What error messages are appearing? "
                "Create a finding with your root cause analysis."
            )
            return " ".join(parts)
        else:
            # Manual trigger — broad sweep
            return (
                f"Run anomaly detection cycle at {now}. "
                "Investigate all customers for latency anomalies, error rate spikes, "
                "and deploy-correlated regressions. Be thorough and methodical."
            )

    def run_cycle(
        self,
        session_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        reason: Optional[str] = None,
        error_rate: Optional[float] = None,
        avg_latency: Optional[float] = None,
    ) -> dict:
        """Run one agent investigation cycle.

        Args:
            session_id: UUID for this session (generated if not provided)
            customer_id: Which customer to investigate (from Go detector)
            reason: Why the investigation was triggered
            error_rate: Current error rate that tripped the threshold
            avg_latency: Current avg latency that tripped the threshold
        """
        if not self.client:
            return {"error": "Gemini API key not configured"}

        if not session_id:
            session_id = str(uuid.uuid4())

        self._emit("cycle_start", {
            "session_id": session_id,
            "customer_id": customer_id,
            "trigger": reason or "manual",
        })

        # Load or create snapshot
        latest_version = self.snapshot_store.get_latest_version(session_id)
        if latest_version is not None:
            previous_objects = self.snapshot_store.replay(session_id, self.object_store)
        else:
            previous_objects = []

        base_version = latest_version or 0
        new_descriptors = []

        # Build contents for Gemini
        contents = []

        for obj in previous_objects:
            if obj.get("type") == "message":
                contents.append(self._stored_to_content(obj["message"]))

        # Build and add trigger message
        trigger_text = self._build_trigger(customer_id, reason, error_rate, avg_latency)
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=trigger_text)],
        ))

        sha = self.object_store.put({
            "type": "message",
            "message": {"role": "user", "text": trigger_text},
        })
        new_descriptors.append(sha)

        # LLM tool-calling loop
        max_iterations = 10
        current_version = base_version

        for i in range(max_iterations):
            self._emit("llm_call", {"iteration": i + 1, "session_id": session_id})

            try:
                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=build_system_prompt(customer_id),
                        tools=[TOOL_DECLARATIONS],
                    ),
                )
            except Exception as e:
                logger.error(f"Gemini API error: {e}")
                self._emit("error", {"message": str(e)})
                break

            candidate = response.candidates[0]
            model_content = candidate.content

            function_calls = []
            text_parts = []
            for part in model_content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)
                if part.text:
                    text_parts.append(part.text)

            text_content = " ".join(text_parts) if text_parts else ""

            # Store model message
            stored_msg = {"role": "model", "text": text_content}
            if function_calls:
                stored_msg["function_calls"] = [
                    {"name": fc.name, "args": dict(fc.args)} for fc in function_calls
                ]

            sha = self.object_store.put({"type": "message", "message": stored_msg})
            new_descriptors.append(sha)
            contents.append(model_content)

            # No tool calls → agent is done
            if not function_calls:
                if text_content:
                    self._emit("agent_message", {"content": text_content})
                current_version += 1
                self.snapshot_store.save(Snapshot(
                    session_id=session_id,
                    version=current_version,
                    parent_version=current_version - 1 if current_version > 1 else None,
                    status="completed",
                    descriptors=list(new_descriptors),
                    metadata={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "customer_id": customer_id,
                        "trigger": reason or "manual",
                        "findings_count": len(self.findings),
                    },
                ))
                break

            # Execute tool calls
            fn_response_parts = []
            stored_responses = []
            for fc in function_calls:
                fn_name = fc.name
                fn_args = dict(fc.args)
                logger.info(f"Executing tool: {fn_name}({list(fn_args.keys())})")
                result_str = self._execute_tool(fn_name, fn_args, session_id)

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

            sha = self.object_store.put({
                "type": "message",
                "message": {"role": "function_response", "responses": stored_responses},
            })
            new_descriptors.append(sha)
            contents.append(types.Content(parts=fn_response_parts))

            # Save intermediate snapshot
            current_version += 1
            self.snapshot_store.save(Snapshot(
                session_id=session_id,
                version=current_version,
                parent_version=current_version - 1 if current_version > 1 else None,
                status="running",
                descriptors=list(new_descriptors),
                metadata={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "customer_id": customer_id,
                    "trigger": reason or "manual",
                    "findings_count": len(self.findings),
                },
            ))

        else:
            # Max iterations reached
            current_version += 1
            self.snapshot_store.save(Snapshot(
                session_id=session_id,
                version=current_version,
                parent_version=current_version - 1 if current_version > 1 else None,
                status="completed",
                descriptors=list(new_descriptors),
                metadata={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "customer_id": customer_id,
                    "trigger": reason or "manual",
                    "findings_count": len(self.findings),
                },
            ))

        self._emit("cycle_complete", {
            "session_id": session_id,
            "version": current_version,
            "customer_id": customer_id,
            "findings_count": len(self.findings),
        })

        return {
            "session_id": session_id,
            "version": current_version,
            "customer_id": customer_id,
            "findings": [f for f in self.findings if f.get("session_id") == session_id],
            "status": "completed",
        }