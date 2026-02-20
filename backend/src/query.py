import logging
import re
from typing import Optional

import duckdb

from .config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_ENDPOINT

logger = logging.getLogger(__name__)

# Module-level connection — reused across queries, extensions loaded once
_conn: Optional[duckdb.DuckDBPyConnection] = None


def get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Get or create the module-level DuckDB connection."""
    global _conn
    if _conn is not None:
        return _conn

    _conn = duckdb.connect()
    _conn.execute("INSTALL iceberg; LOAD iceberg;")
    _conn.execute("INSTALL httpfs; LOAD httpfs;")
    _conn.execute(f"""
        SET s3_endpoint = '{S3_ENDPOINT.replace("http://", "")}';
        SET s3_access_key_id = '{AWS_ACCESS_KEY_ID}';
        SET s3_secret_access_key = '{AWS_SECRET_ACCESS_KEY}';
        SET s3_region = 'us-east-1';
        SET s3_url_style = 'path';
        SET s3_use_ssl = false;
    """)
    return _conn


def _resolve_metadata_path(catalog) -> str:
    """Use PyIceberg to resolve the current metadata.json path for iceberg_scan()."""
    table = catalog.load_table("default.events")
    return table.metadata_location


def query_customer_health(catalog) -> list[dict]:
    """Query per-customer latency percentiles and error rates."""
    try:
        metadata_path = _resolve_metadata_path(catalog)
        conn = get_duckdb_connection()
        result = conn.execute(f"""
            SELECT
                customer_id,
                customer_name,
                COUNT(*) as request_count,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms), 1) as p50_latency,
                ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms), 1) as p99_latency,
                ROUND(100.0 * SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) / COUNT(*), 2) as error_rate,
                MAX(deploy_version) as latest_deploy,
                MAX(timestamp) as last_seen
            FROM iceberg_scan('{metadata_path}')
            WHERE timestamp > now() - INTERVAL '5 minutes'
            GROUP BY customer_id, customer_name
            ORDER BY p99_latency DESC
        """).fetchall()

        columns = [
            "customer_id", "customer_name", "request_count",
            "p50_latency", "p99_latency", "error_rate",
            "latest_deploy", "last_seen",
        ]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        logger.error(f"Customer health query failed: {e}")
        return []


def query_recent_telemetry(catalog, limit: int = 50) -> list[dict]:
    """Get most recent telemetry events."""
    try:
        metadata_path = _resolve_metadata_path(catalog)
        conn = get_duckdb_connection()
        result = conn.execute(f"""
            SELECT
                timestamp, trace_id, customer_id, customer_name,
                endpoint, method, status_code, latency_ms,
                deploy_version, region, error_message
            FROM iceberg_scan('{metadata_path}')
            ORDER BY timestamp DESC
            LIMIT {limit}
        """).fetchall()

        columns = [
            "timestamp", "trace_id", "customer_id", "customer_name",
            "endpoint", "method", "status_code", "latency_ms",
            "deploy_version", "region", "error_message",
        ]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        logger.error(f"Recent telemetry query failed: {e}")
        return []


# SQL statements the agent is allowed to use
_ALLOWED_STATEMENTS = {"SELECT", "WITH"}

# Hard limit on rows returned to the agent
_MAX_AGENT_ROWS = 500


def run_sql(catalog, sql: str) -> list[dict]:
    """Run agent-generated SQL against the events Iceberg table.

    - Only SELECT/WITH statements allowed
    - Table name 'events' is replaced with iceberg_scan()
    - Results capped at _MAX_AGENT_ROWS
    """
    sql = sql.strip().rstrip(";")

    # Safety: only allow read queries
    first_keyword = sql.split()[0].upper() if sql.split() else ""
    if first_keyword not in _ALLOWED_STATEMENTS:
        return [{"error": f"Only SELECT queries are allowed, got: {first_keyword}"}]

    try:
        metadata_path = _resolve_metadata_path(catalog)

        # Replace table references: FROM events, JOIN events, FROM "events"
        scan_expr = f"iceberg_scan('{metadata_path}')"
        modified_sql = re.sub(
            r'\bFROM\s+["\']?events["\']?\b',
            f"FROM {scan_expr}",
            sql,
            flags=re.IGNORECASE,
        )
        modified_sql = re.sub(
            r'\bJOIN\s+["\']?events["\']?\b',
            f"JOIN {scan_expr}",
            modified_sql,
            flags=re.IGNORECASE,
        )

        # Enforce row limit if query doesn't already have one
        if not re.search(r'\bLIMIT\s+\d+', modified_sql, flags=re.IGNORECASE):
            modified_sql += f" LIMIT {_MAX_AGENT_ROWS}"

        conn = get_duckdb_connection()
        result = conn.execute(modified_sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchmany(_MAX_AGENT_ROWS)
        return [dict(zip(columns, row)) for row in rows]

    except Exception as e:
        logger.error(f"Agent SQL query failed: {e}")
        return [{"error": str(e)}]