"""
MCP tool implementations for TigerLite.

Reuses the same DuckDB + iceberg_scan() pattern from backend/src/query.py,
connecting directly to the Iceberg REST catalog and MinIO object store.
"""

import json
import os
import re
from datetime import datetime

import duckdb
from pyiceberg.catalog import load_catalog

# Config — same env vars the backend uses
ICEBERG_REST_URI = os.getenv("ICEBERG_REST_URI", "http://localhost:8181")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "admin")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "password")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def _get_catalog():
    """Load the Iceberg REST catalog (same config as backend)."""
    return load_catalog(
        "rest",
        **{
            "type": "rest",
            "uri": ICEBERG_REST_URI,
            "s3.endpoint": S3_ENDPOINT,
            "s3.access-key-id": AWS_ACCESS_KEY_ID,
            "s3.secret-access-key": AWS_SECRET_ACCESS_KEY,
            "s3.region": AWS_REGION,
        },
    )


def _get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection configured for Iceberg via S3 (mirrors backend/src/query.py)."""
    conn = duckdb.connect()
    conn.execute("INSTALL iceberg; LOAD iceberg;")
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    s3_host = S3_ENDPOINT.replace("http://", "").replace("https://", "")
    conn.execute(f"""
        SET s3_endpoint = '{s3_host}';
        SET s3_access_key_id = '{AWS_ACCESS_KEY_ID}';
        SET s3_secret_access_key = '{AWS_SECRET_ACCESS_KEY}';
        SET s3_region = 'us-east-1';
        SET s3_url_style = 'path';
        SET s3_use_ssl = false;
    """)
    return conn


def _resolve_metadata_path() -> str:
    """Get the current Iceberg metadata.json path via PyIceberg."""
    catalog = _get_catalog()
    table = catalog.load_table("default.events")
    return table.metadata_location


def _serialize(obj):
    """JSON serializer that handles datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _run_query(sql: str) -> str:
    """Execute SQL with iceberg_scan() replacement, return JSON string."""
    try:
        metadata_path = _resolve_metadata_path()

        # Same FROM events -> iceberg_scan() replacement as backend/src/query.py
        # Use regex to handle any whitespace (newlines, indentation) between keyword and table name
        scan = f"FROM iceberg_scan('{metadata_path}')"
        modified_sql = re.sub(r'\bFROM\s+events\b', scan, sql, flags=re.IGNORECASE)
        modified_sql = re.sub(r'\bJOIN\s+events\b', scan.replace('FROM', 'JOIN'), modified_sql, flags=re.IGNORECASE)

        conn = _get_duckdb_connection()
        result = conn.execute(modified_sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
        return json.dumps(data, default=_serialize, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def query_events(sql: str) -> str:
    """Run arbitrary SQL against the events table."""
    return _run_query(sql)


def get_customer_health(minutes: int = 5) -> str:
    """Pre-built query: per-customer P50/P99 latency, error rates, request counts."""
    sql = f"""
        SELECT
            customer_id,
            customer_name,
            COUNT(*) as request_count,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms), 1) as p50_latency,
            ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms), 1) as p99_latency,
            ROUND(100.0 * SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) / COUNT(*), 2) as error_rate,
            MAX(deploy_version) as latest_deploy,
            MAX(timestamp) as last_seen
        FROM events
        WHERE timestamp > now() - INTERVAL '{minutes} minutes'
        GROUP BY customer_id, customer_name
        ORDER BY p99_latency DESC
    """
    return _run_query(sql)


def get_deploy_history(limit: int = 20) -> str:
    """Pre-built query: deploy version timeline with impact metrics."""
    sql = f"""
        SELECT
            deploy_version,
            MIN(timestamp) as first_seen,
            MAX(timestamp) as last_seen,
            COUNT(*) as event_count,
            COUNT(DISTINCT customer_id) as customers_affected,
            ROUND(AVG(latency_ms), 1) as avg_latency,
            ROUND(100.0 * SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) / COUNT(*), 2) as error_rate
        FROM events
        GROUP BY deploy_version
        ORDER BY first_seen DESC
        LIMIT {limit}
    """
    return _run_query(sql)
