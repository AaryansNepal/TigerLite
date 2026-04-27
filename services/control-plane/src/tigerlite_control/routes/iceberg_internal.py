"""Internal endpoint hit by the Go ingest service.

Receives row batches (already converted from OTLP shapes), commits them to
the right Iceberg table.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from ..auth import InternalCaller
from ..iceberg_writer import append_rows

router = APIRouter()
log = structlog.get_logger(__name__)


class AppendRequest(BaseModel):
    tenant_id: str
    signal: Literal["traces", "logs", "metrics"]
    rows: list[dict[str, Any]]
    generated_at: str | None = None


@router.post("/append")
async def append(req: AppendRequest, _: InternalCaller) -> dict[str, int]:
    n = append_rows(req.signal, req.rows)
    log.debug("iceberg appended", tenant=req.tenant_id, signal=req.signal, n=n)
    return {"rows_written": n}
