"""Internal tenant-scoped telemetry queries.

The agent runtime calls this when it needs DuckDB results. We do NOT expose
this to the dashboard (UI users hit the agent, not raw SQL).
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth import InternalCaller
from ..config import get_settings
from ..object_store import make_object_store, sha256_key
from ..query import run_tenant_query

router = APIRouter()
log = structlog.get_logger(__name__)


class QueryRequest(BaseModel):
    tenant_id: str
    sql: str
    artifact: bool = True
    limit_rows: int = 10_000


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    artifact_id: str | None = None
    summary: str
    truncated: bool


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, _: InternalCaller) -> QueryResponse:
    try:
        result = run_tenant_query(req.tenant_id, req.sql, limit_rows=req.limit_rows)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        log.error("query error", err=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    settings = get_settings()
    full = result.to_record_list()
    artifact_id = None

    if req.artifact and full:
        # Always write the artifact (even small results) so the agent can
        # re-query later via read_artifact.
        store = make_object_store(bucket=settings.snapshots_bucket)
        blob = json.dumps(full, default=str).encode()
        key = sha256_key(blob, prefix="artifacts")
        await store.put(key, blob, content_type="application/json")
        # Surface the hash without the prefix path for the agent to use.
        artifact_id = key.split("/")[-1]

    # Truncate preview if the full payload is large
    cap = settings.agent_query_result_token_cap
    payload_size = len(json.dumps(full, default=str))
    truncated = payload_size > cap * 4  # rough byte≈4×token estimate
    preview_rows = result.rows[:5] if truncated else result.rows
    summary = f"{result.row_count} rows × {len(result.columns)} columns"

    return QueryResponse(
        columns=result.columns,
        rows=preview_rows,
        row_count=result.row_count,
        artifact_id=artifact_id,
        summary=summary,
        truncated=truncated,
    )


class ArtifactReadRequest(BaseModel):
    artifact_id: str
    jq: str | None = None
    line_range: list[int] | None = None  # [start, end]


@router.post("/read_artifact")
async def read_artifact(req: ArtifactReadRequest, _: InternalCaller) -> dict[str, Any]:
    settings = get_settings()
    store = make_object_store(bucket=settings.snapshots_bucket)
    key = f"artifacts/{req.artifact_id[:2]}/{req.artifact_id}"
    try:
        blob = await store.get(key)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    text = blob.decode()
    if req.jq:
        try:
            import jq

            parsed = json.loads(text)
            filtered = jq.compile(req.jq).input(parsed).all()
            text = json.dumps(filtered, default=str)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"jq error: {e}") from e

    if req.line_range:
        lines = text.splitlines()
        start, end = req.line_range[0], req.line_range[1]
        text = "\n".join(lines[start:end])

    # Cap returned size so we don't blow tokens.
    cap = settings.agent_query_result_token_cap * 4
    if len(text) > cap:
        text = text[:cap] + f"\n... (truncated to {cap} bytes; refine jq filter to narrow)"

    return {"content": text, "artifact_id": req.artifact_id}
