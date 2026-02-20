"""Pydantic models shared across ingestion, query, and agent modules.

Mirrors the Iceberg table schema defined in iceberg_writer.py.
The Go ingestion service uses the same field names for zero-translation forwarding.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TelemetryEvent(BaseModel):
    timestamp: datetime
    trace_id: str
    customer_id: str
    customer_name: str
    endpoint: str          # e.g. /api/v1/orders
    method: str            # GET, POST
    status_code: int       # 200 = ok, 500+ = server error
    latency_ms: float
    deploy_version: str    # e.g. v1.2.3
    region: str            # e.g. us-east-1
    error_message: Optional[str] = None  # only set when status_code >= 500
