"""Agent tool definitions for OpenAI function calling.

Tools mirror FireTiger's agentic approach:
- query_duckdb: Run SQL against the Iceberg data lake
- get_customer_list: Get active customers
- create_finding: Record an anomaly finding with evidence
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_duckdb",
            "description": (
                "Execute a SQL query against the telemetry events table. "
                "The table is called 'events' with columns: timestamp, trace_id, "
                "customer_id, customer_name, endpoint, method, status_code, "
                "latency_ms, deploy_version, region, error_message. "
                "Use standard SQL. Timestamps are timezone-aware."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL query to execute against the events table",
                    }
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_list",
            "description": "Get a list of all customers with their recent request counts and basic health metrics.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_finding",
            "description": (
                "Create an anomaly finding after completing investigation. "
                "Use this when you have identified a confirmed issue with evidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                        "description": "Severity level of the finding",
                    },
                    "customer_id": {
                        "type": "string",
                        "description": "The affected customer ID",
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "The affected customer name",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title summarizing the finding",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Detailed summary of the anomaly, root cause analysis, and impact",
                    },
                    "evidence_queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "SQL queries used as evidence during investigation",
                    },
                },
                "required": ["severity", "customer_id", "customer_name", "title", "summary", "evidence_queries"],
            },
        },
    },
]
