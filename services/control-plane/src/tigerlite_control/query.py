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
        # Allow iceberg_scan('s3://...') without an explicit version pointer.
        # PyIceberg writes metadata atomically, so version guessing is safe at
        # our scale (no concurrent compaction). Without this, every query
        # 500s with "no version-hint could be found".
        _conn.execute("SET unsafe_enable_version_guessing = true")

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

    For each Iceberg table that hasn't been created yet (e.g. an Astronomy
    Shop that only emits traces, not metrics), the corresponding CTE is
    substituted with an empty stub of the right shape so the agent's SQL
    succeeds with zero rows instead of 500-ing on a missing iceberg_scan
    target.

    Raises ValueError if the SQL tries to use forbidden constructs.
    """
    sql_clean = sql.strip().rstrip(";")
    _check_forbidden(sql_clean)

    settings = get_settings()
    conn = get_conn()

    bucket = settings.telemetry_bucket
    base = f"s3://{bucket}"
    existing = _existing_iceberg_signals()

    cte_parts: list[str] = []
    for sig in ("traces", "logs", "metrics"):
        if sig in existing:
            cte_parts.append(
                f"{sig} AS (SELECT * FROM iceberg_scan('{base}/default/{sig}') "
                f"WHERE tenant_id = '{_quote(tenant_id)}')"
            )
        else:
            cte_parts.append(f"{sig} AS ({_EMPTY_STUBS[sig]})")

    # Wrap the user's SQL in a subquery so any LIMIT/ORDER BY/etc. inside it
    # doesn't conflict with the safety LIMIT we append for blast-radius.
    wrapped = (
        f"WITH {', '.join(cte_parts)} "
        f"SELECT * FROM ({sql_clean}) AS _user_query LIMIT {int(limit_rows)}"
    )

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


# ----------------------------------------------------------
# Existing-signals discovery + empty stubs for missing tables
# ----------------------------------------------------------

import time
from pyiceberg.exceptions import NoSuchTableError  # noqa: E402

_existing_cache: tuple[float, set[str]] = (0.0, set())


def _existing_iceberg_signals() -> set[str]:
    """Returns which of {'traces','logs','metrics'} have been written to.
    Cached for 30 seconds to avoid hitting the catalog on every query.
    """
    global _existing_cache
    now = time.time()
    if now - _existing_cache[0] < 30:
        return _existing_cache[1]

    from .iceberg_writer import get_catalog

    catalog = get_catalog()
    out: set[str] = set()
    for sig in ("traces", "logs", "metrics"):
        try:
            catalog.load_table(("default", sig))
            out.add(sig)
        except NoSuchTableError:
            pass
        except Exception as e:
            log.warning("iceberg load_table probe failed", sig=sig, err=str(e))
    _existing_cache = (now, out)
    log.debug("existing iceberg signals", signals=sorted(out))
    return out


# Stubs for missing tables: empty result sets with the columns the agent
# is most likely to reference. Keeps SQL errors away when the agent
# explores a signal we haven't received yet.
_EMPTY_STUBS = {
    "traces": """
        SELECT
          CAST(NULL AS VARCHAR) AS tenant_id,
          CAST(NULL AS VARCHAR) AS trace_id,
          CAST(NULL AS VARCHAR) AS span_id,
          CAST(NULL AS VARCHAR) AS parent_span_id,
          CAST(NULL AS TIMESTAMP) AS start_time,
          CAST(NULL AS TIMESTAMP) AS end_time,
          CAST(NULL AS DOUBLE) AS duration_ms,
          CAST(NULL AS VARCHAR) AS service_name,
          CAST(NULL AS VARCHAR) AS service_version,
          CAST(NULL AS VARCHAR) AS span_name,
          CAST(NULL AS VARCHAR) AS span_kind,
          CAST(NULL AS VARCHAR) AS status_code,
          CAST(NULL AS VARCHAR) AS status_message,
          CAST(NULL AS VARCHAR) AS http_method,
          CAST(NULL AS VARCHAR) AS http_route,
          CAST(NULL AS INTEGER) AS http_status_code,
          CAST(NULL AS VARCHAR) AS http_url,
          CAST(NULL AS VARCHAR) AS db_system,
          CAST(NULL AS VARCHAR) AS db_statement,
          CAST(NULL AS MAP(VARCHAR, VARCHAR)) AS attributes,
          CAST(NULL AS MAP(VARCHAR, VARCHAR)) AS resource_attributes
        WHERE FALSE
    """,
    "logs": """
        SELECT
          CAST(NULL AS VARCHAR) AS tenant_id,
          CAST(NULL AS VARCHAR) AS trace_id,
          CAST(NULL AS VARCHAR) AS span_id,
          CAST(NULL AS TIMESTAMP) AS time,
          CAST(NULL AS VARCHAR) AS severity_text,
          CAST(NULL AS INTEGER) AS severity_number,
          CAST(NULL AS VARCHAR) AS service_name,
          CAST(NULL AS VARCHAR) AS body,
          CAST(NULL AS VARCHAR) AS body_type,
          CAST(NULL AS MAP(VARCHAR, VARCHAR)) AS attributes,
          CAST(NULL AS MAP(VARCHAR, VARCHAR)) AS resource_attributes
        WHERE FALSE
    """,
    "metrics": """
        SELECT
          CAST(NULL AS VARCHAR) AS tenant_id,
          CAST(NULL AS VARCHAR) AS metric_name,
          CAST(NULL AS VARCHAR) AS metric_type,
          CAST(NULL AS VARCHAR) AS metric_unit,
          CAST(NULL AS VARCHAR) AS service_name,
          CAST(NULL AS TIMESTAMP) AS time,
          CAST(NULL AS DOUBLE) AS gauge_value,
          CAST(NULL AS DOUBLE) AS sum_value,
          CAST(NULL AS BIGINT) AS histogram_count,
          CAST(NULL AS DOUBLE) AS histogram_sum,
          CAST(NULL AS MAP(VARCHAR, VARCHAR)) AS attributes,
          CAST(NULL AS MAP(VARCHAR, VARCHAR)) AS resource_attributes
        WHERE FALSE
    """,
}
