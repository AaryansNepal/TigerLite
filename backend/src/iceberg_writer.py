"""Iceberg table management — schema definition, catalog connection, and writes.

Defines the events table schema with partition spec (day + customer_id),
connects to the REST catalog with retry logic, and appends batches via PyArrow.
Partitioning by customer_id enables fast per-customer queries in DuckDB.
"""

import logging
import time

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import (
    NamespaceAlreadyExistsError,
    NoSuchTableError,
)
from pyiceberg.schema import Schema
from pyiceberg.types import (
    DoubleType,
    IntegerType,
    NestedField,
    StringType,
    TimestamptzType,
)
from pyiceberg.partitioning import PartitionSpec, PartitionField
from pyiceberg.transforms import DayTransform, IdentityTransform

from .config import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    ICEBERG_REST_URI,
    S3_ENDPOINT,
)

logger = logging.getLogger(__name__)

EVENTS_SCHEMA = Schema(
    NestedField(1, "timestamp", TimestamptzType(), required=True),
    NestedField(2, "trace_id", StringType(), required=True),
    NestedField(3, "customer_id", StringType(), required=True),
    NestedField(4, "customer_name", StringType(), required=True),
    NestedField(5, "endpoint", StringType(), required=True),
    NestedField(6, "method", StringType(), required=True),
    NestedField(7, "status_code", IntegerType(), required=True),
    NestedField(8, "latency_ms", DoubleType(), required=True),
    NestedField(9, "deploy_version", StringType(), required=True),
    NestedField(10, "region", StringType(), required=True),
    NestedField(11, "error_message", StringType(), required=False),
)

EVENTS_PARTITION_SPEC = PartitionSpec(
    PartitionField(source_id=1, field_id=1000, transform=DayTransform(), name="timestamp_day"),
    PartitionField(source_id=3, field_id=1001, transform=IdentityTransform(), name="customer_id"),
)


def connect_catalog(max_retries: int = 10, delay: float = 2.0):
    """Connect to the Iceberg REST catalog with retry logic."""
    for attempt in range(max_retries):
        try:
            catalog = load_catalog(
                "rest",
                **{
                    "type": "rest",
                    "uri": ICEBERG_REST_URI,
                    "s3.endpoint": S3_ENDPOINT,
                    "s3.access-key-id": AWS_ACCESS_KEY_ID,
                    "s3.secret-access-key": AWS_SECRET_ACCESS_KEY,
                    "s3.region": "us-east-1",
                    "s3.path-style-access": "true",
                },
            )
            # Test connectivity by listing namespaces
            catalog.list_namespaces()
            logger.info("Connected to Iceberg REST catalog")
            return catalog
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Catalog connection attempt {attempt + 1}/{max_retries} failed: {e}"
                )
                time.sleep(delay)
            else:
                raise RuntimeError(
                    f"Failed to connect to Iceberg catalog after {max_retries} attempts"
                ) from e


def ensure_events_table(catalog):
    """Create the default.events Iceberg table if it doesn't exist."""
    try:
        catalog.create_namespace("default")
    except NamespaceAlreadyExistsError:
        pass

    try:
        table = catalog.load_table("default.events")
        logger.info("Loaded existing default.events table")
    except NoSuchTableError:
        table = catalog.create_table(
            "default.events",
            schema=EVENTS_SCHEMA,
            partition_spec=EVENTS_PARTITION_SPEC,
        )
        logger.info("Created default.events table")

    return table


def append_events(table, events: list[dict]):
    """Append a batch of events to the Iceberg table via PyArrow."""
    if not events:
        return

    arrow_schema = table.schema().as_arrow()
    arrays = {}
    for field in arrow_schema:
        values = [e.get(field.name) for e in events]
        arrays[field.name] = values

    arrow_table = pa.table(arrays, schema=arrow_schema)
    table.append(arrow_table)
    logger.info(f"Appended {len(events)} events to Iceberg table")
