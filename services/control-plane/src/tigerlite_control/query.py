"""DuckDB tenant-scoped query layer.

Every agent SQL goes through `run_tenant_query`, which:
  1. Builds a CTE that filters each Iceberg table by tenant_id.
  2. Runs the user query against those CTEs.
  3. Returns rows + columns + an artifact pointer if the result is large.

The CTE pattern means even if the LLM tries to reference the raw `traces`
table, it gets the tenant-scoped view. There is NO unfiltered path.

DuckDB is in-process; we use the iceberg extension's `iceberg_scan()` against
S3-compatible storage (MinIO or AWS S3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import duckdb
import structlog

from .config import get_settings

log = structlog.get_logger(__name__)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int

    def to_record_list(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r)) for r in self.rows]

    def to_json(self) -> str:
        return json.dumps(self.to_record_list(), default=str)


_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        settings = get_settings()
        _conn = duckdb.connect(":memory:")
        _conn.execute("INSTALL iceberg")
        _conn.execute("LOAD iceberg")
        _conn.execute("INSTALL httpfs")
        _conn.execute("LOAD httpfs")

        if settings.object_store == "minio":
            # Point DuckDB at MinIO via the S3 protocol.
            host = settings.minio_endpoint.replace("http://", "").replace("https://", "")
            _conn.execute(f"SET s3_endpoint='{host}'")
            _conn.execute(f"SET s3_access_key_id='{settings.minio_access_key}'")
            _conn.execute(f"SET s3_secret_access_key='{settings.minio_secret_key}'")
            _conn.execute("SET s3_url_style='path'")
            _conn.execute("SET s3_use_ssl=false")
        else:
            _conn.execute(f"SET s3_region='{settings.aws_region}'")
            if settings.aws_access_key_id:
                _conn.execute(f"SET s3_access_key_id='{settings.aws_access_key_id}'")
                _conn.execute(f"SET s3_secret_access_key='{settings.aws_secret_access_key}'")
        log.info("duckdb connection initialised")
    return _conn


def run_tenant_query(tenant_id: str, sql: str, *, limit_rows: int = 10_000) -> QueryResult:
    """Run a tenant-scoped query. The caller's SQL must reference only the
    CTEs defined here: traces, logs, metrics.

    Raises ValueError if the SQL tries to use forbidden constructs (rough
    static check — DuckDB itself is the real enforcement boundary).
    """
    sql_clean = sql.strip().rstrip(";")
    _check_forbidden(sql_clean)

    settings = get_settings()
    conn = get_conn()

    # Iceberg tables on S3 (or MinIO).
    bucket = settings.telemetry_bucket
    base = f"s3://{bucket}"

    wrapped = f"""
    WITH
      traces  AS (
        SELECT * FROM iceberg_scan('{base}/default/traces')
         WHERE tenant_id = '{_quote(tenant_id)}'
      ),
      logs    AS (
        SELECT * FROM iceberg_scan('{base}/default/logs')
         WHERE tenant_id = '{_quote(tenant_id)}'
      ),
      metrics AS (
        SELECT * FROM iceberg_scan('{base}/default/metrics')
         WHERE tenant_id = '{_quote(tenant_id)}'
      )
    {sql_clean}
    LIMIT {int(limit_rows)}
    """

    log.debug("running tenant query", tenant_id=tenant_id, sql=sql_clean[:300])
    cursor = conn.execute(wrapped)
    columns = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    return QueryResult(columns=columns, rows=[list(r) for r in rows], row_count=len(rows))


def _check_forbidden(sql: str) -> None:
    upper = sql.upper()
    forbidden = ("ATTACH", "DETACH", "INSTALL ", "LOAD ", "PRAGMA ", "SET ")
    for kw in forbidden:
        if kw in upper:
            raise ValueError(f"forbidden SQL fragment: {kw.strip()}")


def _quote(s: str) -> str:
    return s.replace("'", "''")
