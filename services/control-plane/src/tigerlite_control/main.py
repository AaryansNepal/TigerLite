"""FastAPI app entry point.

Routes are mounted under /api for client traffic and /internal for trusted
service-to-service calls (e.g. Go ingest → PyIceberg writer).

In production the dashboard's Next.js API routes call /api endpoints with the
end-user's JWT, and we re-validate the JWT before doing anything tenant-scoped.
For demo simplicity the JWT is checked via Supabase JWKS at request time.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import scheduler
from .config import get_settings
from .db import close_pool, get_pool
from .routes import (
    agents,
    chat,
    connections,
    findings,
    iceberg_internal,
    issues,
    sessions,
    slack_events,
    telemetry_internal,
)


log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        )
    )
    log.info("control plane starting", stage=settings.stage)
    await get_pool()

    # Background tasks: anomaly watcher, cron scheduler, queue reaper.
    bg_tasks = await scheduler.start()

    try:
        yield
    finally:
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        await close_pool()
        log.info("control plane stopped")


app = FastAPI(
    title="TigerLite control plane",
    version="2.0.0-dev",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().dashboard_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(chat.router, prefix="/api/agents/chat", tags=["chat"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(findings.router, prefix="/api/findings", tags=["findings"])
app.include_router(issues.router, prefix="/api/issues", tags=["issues"])
app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
app.include_router(slack_events.router, prefix="/api/slack", tags=["slack"])

app.include_router(iceberg_internal.router, prefix="/internal/iceberg", tags=["internal"])
app.include_router(telemetry_internal.router, prefix="/internal/telemetry", tags=["internal"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tigerlite-control"}
