"""PyIceberg writer for OTel-shaped tables.

The Go ingest service POSTs JSON batches to /internal/iceberg/append in
this service, and we land them as Iceberg appends. We keep schemas, the
catalog handle, and the table cache here.

Tables (one per signal):
  - traces
  - logs
  - metrics

All three are partitioned by (tenant_id, day) so DuckDB scans only relevant
files for tenant-scoped queries.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import structlog
from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DoubleType,
    IntegerType,
    LongType,
    MapType,
    NestedField,
    StringType,
    TimestampType,
    DateType,
    BooleanType,
)

from .config import get_settings

log = structlog.get_logger(__name__)


# ----------------------------------------------------------
# Schemas (mirror docs/DATA_MODEL.md)
# ----------------------------------------------------------

TRACES_SCHEMA = Schema(
    NestedField(1, "tenant_id", StringType(), required=True),
    NestedField(2, "trace_id", StringType(), required=True),
    NestedField(3, "span_id", StringType(), required=True),
    NestedField(4, "parent_span_id", StringType()),
    NestedField(5, "trace_state", StringType()),
    NestedField(6, "start_time", TimestampType(), required=True),
    NestedField(7, "end_time", TimestampType(), required=True),
    NestedField(8, "duration_ms", DoubleType()),
    NestedField(9, "service_name", StringType()),
    NestedField(10, "service_version", StringType()),
    NestedField(11, "scope_name", StringType()),
    NestedField(12, "scope_version", StringType()),
    NestedField(13, "span_name", StringType()),
    NestedField(14, "span_kind", StringType()),
    NestedField(15, "status_code", StringType()),
    NestedField(16, "status_message", StringType()),
    NestedField(
        17,
        "attributes",
        MapType(50, StringType(), 51, StringType(), value_required=False),
    ),
    NestedField(
        18,
        "resource_attributes",
        MapType(52, StringType(), 53, StringType(), value_required=False),
    ),
    NestedField(19, "http_method", StringType()),
    NestedField(20, "http_route", StringType()),
    NestedField(21, "http_status_code", IntegerType()),
    NestedField(22, "http_url", StringType()),
    NestedField(23, "rpc_method", StringType()),
    NestedField(24, "rpc_service", StringType()),
    NestedField(25, "db_system", StringType()),
    NestedField(26, "db_statement", StringType()),
    NestedField(27, "events", StringType()),
    NestedField(28, "links", StringType()),
    NestedField(29, "ingested_at", TimestampType(), required=True),
    NestedField(30, "day", DateType(), required=True),
)


LOGS_SCHEMA = Schema(
    NestedField(1, "tenant_id", StringType(), required=True),
    NestedField(2, "trace_id", StringType()),
    NestedField(3, "span_id", StringType()),
    NestedField(4, "time", TimestampType(), required=True),
    NestedField(5, "observed_time", TimestampType()),
    NestedField(6, "severity_text", StringType()),
    NestedField(7, "severity_number", IntegerType()),
    NestedField(8, "service_name", StringType()),
    NestedField(9, "scope_name", StringType()),
    NestedField(10, "body", StringType()),
    NestedField(11, "body_type", StringType()),
    NestedField(
        12,
        "attributes",
        MapType(50, StringType(), 51, StringType(), value_required=False),
    ),
    NestedField(
        13,
        "resource_attributes",
        MapType(52, StringType(), 53, StringType(), value_required=False),
    ),
    NestedField(14, "ingested_at", TimestampType(), required=True),
    NestedField(15, "day", DateType(), required=True),
)


METRICS_SCHEMA = Schema(
    NestedField(1, "tenant_id", StringType(), required=True),
    NestedField(2, "metric_name", StringType(), required=True),
    NestedField(3, "metric_type", StringType(), required=True),
    NestedField(4, "metric_unit", StringType()),
    NestedField(5, "metric_description", StringType()),
    NestedField(6, "service_name", StringType()),
    NestedField(7, "scope_name", StringType()),
    NestedField(8, "time", TimestampType(), required=True),
    NestedField(9, "start_time", TimestampType()),
    NestedField(10, "gauge_value", DoubleType()),
    NestedField(11, "sum_value", DoubleType()),
    NestedField(12, "sum_is_monotonic", BooleanType()),
    NestedField(13, "histogram_count", LongType()),
    NestedField(14, "histogram_sum", DoubleType()),
    NestedField(15, "histogram_buckets", StringType()),
    NestedField(
        16,
        "attributes",
        MapType(50, StringType(), 51, StringType(), value_required=False),
    ),
    NestedField(
        17,
        "resource_attributes",
        MapType(52, StringType(), 53, StringType(), value_required=False),
    ),
    NestedField(18, "ingested_at", TimestampType(), required=True),
    NestedField(19, "day", DateType(), required=True),
)


# Partition spec: identity on tenant_id + day. PyIceberg numbers partition
# fields with their own IDs (1000+); identity transform on existing fields.
def _partition_spec(schema: Schema) -> PartitionSpec:
    tenant_field = schema.find_field("tenant_id")
    day_field = schema.find_field("day")
    return PartitionSpec(
        PartitionField(
            source_id=tenant_field.field_id,
            field_id=1000,
            transform=IdentityTransform(),
            name="tenant_id",
        ),
        PartitionField(
            source_id=day_field.field_id,
            field_id=1001,
            transform=IdentityTransform(),
            name="day",
        ),
    )


SIGNAL_SCHEMAS = {
    "traces": (TRACES_SCHEMA, _partition_spec(TRACES_SCHEMA)),
    "logs": (LOGS_SCHEMA, _partition_spec(LOGS_SCHEMA)),
    "metrics": (METRICS_SCHEMA, _partition_spec(METRICS_SCHEMA)),
}


# ----------------------------------------------------------
# Catalog wiring
# ----------------------------------------------------------

_catalog = None


def get_catalog():
    global _catalog
    if _catalog is None:
        settings = get_settings()
        if settings.object_store == "minio":
            _catalog = load_catalog(
                "tigerlite",
                **{
                    "uri": settings.iceberg_catalog_uri,
                    "warehouse": settings.iceberg_warehouse,
                    "s3.endpoint": settings.minio_endpoint,
                    "s3.access-key-id": settings.minio_access_key,
                    "s3.secret-access-key": settings.minio_secret_key,
                    "s3.path-style-access": "true",
                    "s3.region": "us-east-1",
                },
            )
        else:
            _catalog = load_catalog(
                "tigerlite",
                **{
                    "uri": settings.iceberg_catalog_uri,
                    "warehouse": settings.iceberg_warehouse,
                    "s3.region": settings.aws_region,
                    "s3.access-key-id": settings.aws_access_key_id,
                    "s3.secret-access-key": settings.aws_secret_access_key,
                },
            )
    return _catalog


def get_or_create_table(signal: str):
    if signal not in SIGNAL_SCHEMAS:
        raise ValueError(f"unknown signal {signal!r}")
    catalog = get_catalog()
    identifier = ("default", signal)
    try:
        return catalog.load_table(identifier)
    except NoSuchTableError:
        log.info("creating iceberg table", signal=signal)
        schema, spec = SIGNAL_SCHEMAS[signal]
        try:
            catalog.create_namespace("default")
        except Exception:
            pass
        return catalog.create_table(
            identifier=identifier,
            schema=schema,
            partition_spec=spec,
            properties={"write.target-file-size-bytes": "134217728"},
        )


# ----------------------------------------------------------
# Append entry point
# ----------------------------------------------------------

def append_rows(signal: str, rows: list[dict[str, Any]]) -> int:
    """Append rows to the named Iceberg table. Returns rows written."""
    if not rows:
        return 0
    table = get_or_create_table(signal)

    # Coerce timestamp / date strings into datetime / date objects.
    coerced = [_coerce_row(signal, r) for r in rows]

    # Build a pyarrow table to feed table.append().
    import pyarrow as pa

    arrow_table = pa.Table.from_pylist(coerced, schema=table.schema().as_arrow())
    table.append(arrow_table)
    return len(coerced)


def _coerce_row(signal: str, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k in (
        "start_time",
        "end_time",
        "time",
        "observed_time",
        "ingested_at",
    ):
        if k in out and isinstance(out[k], str) and out[k]:
            out[k] = _parse_dt(out[k])
        elif k in out and out[k] in ("", None):
            out[k] = None
    if "day" in out and isinstance(out["day"], str):
        out["day"] = date.fromisoformat(out["day"])
    return out


def _parse_dt(s: str) -> datetime:
    # OTel timestamps come through as RFC3339Nano. fromisoformat handles
    # most cases; trim any trailing 'Z' and excess nanos.
    s = s.replace("Z", "+00:00")
    # Trim nanos beyond 6 digits
    if "." in s:
        head, _, tail = s.partition(".")
        sep = ""
        for ch in tail:
            if ch in "+-":
                sep = ch
                break
        nanos, tz = (tail.split(sep, 1) + [""])[:2] if sep else (tail, "")
        nanos = nanos[:6].ljust(6, "0") if nanos else "000000"
        s = f"{head}.{nanos}{sep}{tz}" if sep else f"{head}.{nanos}"
    return datetime.fromisoformat(s)
