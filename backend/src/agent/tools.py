"""Agent tool definitions for Gemini function calling.

Tools mirror FireTiger's agentic approach:
- query_duckdb: Run SQL against the Iceberg data lake
- get_customer_list: Get active customers
- create_finding: Record an anomaly finding with evidence
"""

from google.genai import types

TOOL_DECLARATIONS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="query_duckdb",
        description=(
            "Execute a SQL query against the telemetry events table. "
            "The table is called 'events' with columns: timestamp, trace_id, "
            "customer_id, customer_name, endpoint, method, status_code, "
            "latency_ms, deploy_version, region, error_message. "
            "Use standard SQL. Timestamps are timezone-aware."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "sql": types.Schema(
                    type="STRING",
                    description="The SQL query to execute against the events table",
                ),
            },
            required=["sql"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_customer_list",
        description="Get a list of all customers with their recent request counts and basic health metrics.",
    ),
    types.FunctionDeclaration(
        name="create_finding",
        description=(
            "Create an anomaly finding after completing investigation. "
            "Use this when you have identified a confirmed issue with evidence."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "severity": types.Schema(
                    type="STRING",
                    enum=["critical", "warning", "info"],
                    description="Severity level of the finding",
                ),
                "customer_id": types.Schema(
                    type="STRING",
                    description="The affected customer ID",
                ),
                "customer_name": types.Schema(
                    type="STRING",
                    description="The affected customer name",
                ),
                "title": types.Schema(
                    type="STRING",
                    description="Short title summarizing the finding",
                ),
                "summary": types.Schema(
                    type="STRING",
                    description="Detailed summary of the anomaly, root cause analysis, and impact",
                ),
                "evidence_queries": types.Schema(
                    type="ARRAY",
                    items=types.Schema(type="STRING"),
                    description="SQL queries used as evidence during investigation",
                ),
            },
            required=["severity", "customer_id", "customer_name", "title", "summary", "evidence_queries"],
        ),
    ),
])
