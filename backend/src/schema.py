from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TelemetryEvent(BaseModel):
    timestamp: datetime
    trace_id: str
    customer_id: str
    customer_name: str
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    deploy_version: str
    region: str
    error_message: Optional[str] = None
