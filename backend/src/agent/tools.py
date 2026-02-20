"""Agent tool declarations for Gemini function calling.

Gemini-specific optimizations:
- Descriptions state WHEN to use each tool, not just what it does
- Enums used where possible for constrained inputs
- Parameter descriptions are concise and example-driven
"""

from google.genai import types

TOOL_DECLARATIONS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_customer_list",
        description=(
            "Call this first at the start of every investigation. "
            "Returns all customers with health metrics from the last 5 minutes: "
            "request_count, p50_latency, p99_latency, error_rate. "
            "Use the results to identify which customers have elevated error rates "
            "or latency before drilling down with SQL queries."
        ),
        # No parameters — this is a simple data fetch
    ),
    types.FunctionDeclaration(
        name="query_duckdb",
        description=(
            "Execute a read-only SQL query against the telemetry events table. "
            "Use this after get_customer_list identifies an anomalous customer, "
            "to investigate endpoints, deploy versions, error messages, and timing. "
            "The table is called 'events'. "
            "Server errors are status_code >= 500 only. "
            "Timestamps are timezone-aware. Use standard SQL."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "sql": types.Schema(
                    type="STRING",
                    description=(
                        "SQL SELECT query against the events table. "
                        "Example: SELECT customer_id, COUNT(*) as cnt "
                        "FROM events WHERE timestamp > now() - INTERVAL '5 minutes' "
                        "GROUP BY customer_id"
                    ),
                ),
            },
            required=["sql"],
        ),
    ),
    types.FunctionDeclaration(
        name="create_finding",
        description=(
            "Record a confirmed anomaly finding. "
            "Call this only after you have evidence from at least two SQL queries "
            "that confirms a real issue. Do not call this for baseline noise."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "severity": types.Schema(
                    type="STRING",
                    enum=["critical", "warning", "info"],
                    description="critical: error_rate>10% or p99>1000ms. warning: error_rate 5-10%. info: notable pattern.",
                ),
                "customer_id": types.Schema(
                    type="STRING",
                    description="Affected customer ID, e.g. cust_007",
                ),
                "customer_name": types.Schema(
                    type="STRING",
                    description="Affected customer name, e.g. Wonka Industries",
                ),
                "title": types.Schema(
                    type="STRING",
                    description="One-line summary, e.g. 'Latency regression for Wonka Industries after deploy v1.2.4'",
                ),
                "summary": types.Schema(
                    type="STRING",
                    description="Detailed analysis: what is happening, which endpoints are affected, probable root cause, and impact scope.",
                ),
                "evidence_queries": types.Schema(
                    type="ARRAY",
                    items=types.Schema(type="STRING"),
                    description="The SQL queries you ran that support this finding.",
                ),
            },
            required=["severity", "customer_id", "customer_name", "title", "summary", "evidence_queries"],
        ),
    ),
])