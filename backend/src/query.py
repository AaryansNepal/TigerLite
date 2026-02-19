import logging
from contextlib import contextmanager

import duckdb

from .config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_ENDPOINT

logger = logging.getLogger(__name__)


def get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection configured for Iceberg via S3."""
    conn = duckdb.connect()
    conn.execute("INSTALL iceberg; LOAD iceberg;")
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    conn.execute(f"""
        SET s3_endpoint = '{S3_ENDPOINT.replace("http://", "")}';
        SET s3_access_key_id = '{AWS_ACCESS_KEY_ID}';
        SET s3_secret_access_key = '{AWS_SECRET_ACCESS_KEY}';
        SET s3_region = 'us-east-1';
        SET s3_url_style = 'path';
        SET s3_use_ssl = false;
    """)
    return conn


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


def run_sql(catalog, sql: str) -> list[dict]:
    """Run arbitrary SQL against the events Iceberg table.

    Replaces any reference to 'events' table with iceberg_scan().
    """
    try:
        metadata_path = _resolve_metadata_path(catalog)
        # Replace table references with iceberg_scan
        modified_sql = sql.replace(
            "FROM events", f"FROM iceberg_scan('{metadata_path}')"
        ).replace(
            "from events", f"FROM iceberg_scan('{metadata_path}')"
        ).replace(
            "JOIN events", f"JOIN iceberg_scan('{metadata_path}')"
        ).replace(
            "join events", f"JOIN iceberg_scan('{metadata_path}')"
        )

        conn = get_duckdb_connection()
        result = conn.execute(modified_sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        logger.error(f"SQL query failed: {e}")
        return [{"error": str(e)}]
