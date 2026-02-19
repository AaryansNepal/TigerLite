"""
TigerLite MCP Tool Server

Exposes the Iceberg data lake to Claude Desktop (or any MCP client) via three tools:
  - query_events: run arbitrary SQL against the events table
  - get_customer_health: pre-built P50/P99 latency + error rate query
  - get_deploy_history: deploy version timeline with impact metrics

Uses stdio transport (standard MCP protocol) — Claude Desktop launches this as a subprocess.
"""

import os

from mcp.server.fastmcp import FastMCP

from tools import query_events, get_customer_health, get_deploy_history

# Config from environment (same vars as docker-compose.yml)
ICEBERG_REST_URI = os.getenv("ICEBERG_REST_URI", "http://localhost:8181")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "admin")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "password")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

mcp = FastMCP("TigerLite")


@mcp.tool()
def mcp_query_events(sql: str) -> str:
    """Run arbitrary SQL against the TigerLite events table.

    Use 'FROM events' in your query — it will be rewritten to use iceberg_scan() automatically.
    Example: SELECT customer_name, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """
    return query_events(sql)


@mcp.tool()
def mcp_get_customer_health(minutes: int = 5) -> str:
    """Get per-customer health metrics: request count, P50/P99 latency, error rate.

    Args:
        minutes: Look-back window in minutes (default 5)
    """
    return get_customer_health(minutes)


@mcp.tool()
def mcp_get_deploy_history(limit: int = 20) -> str:
    """Get deploy version timeline showing when each version appeared and its impact.

    Args:
        limit: Max number of deploy events to return (default 20)
    """
    return get_deploy_history(limit)


if __name__ == "__main__":
    mcp.run(transport="stdio")
