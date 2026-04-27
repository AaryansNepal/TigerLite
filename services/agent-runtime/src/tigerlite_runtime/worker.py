"""Long-running worker.

Consumes the queue. For snapshot_ready jobs, runs one step. For trigger
jobs (anomaly/cron/slack/verify), composes the initial snapshot then enqueues
a snapshot_ready that the next iteration picks up.

Run with: uv run python -m tigerlite_runtime.worker
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from typing import Any

import structlog

from . import queue_client, trigger_router
from .config import get_settings
from .db import close_pool
from .run_step import TerminalSignal, run_one_step

log = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        )
    )
    consumer_id = f"worker-{uuid.uuid4().hex[:8]}"
    log.info("agent runtime worker starting", consumer_id=consumer_id)

    stop = asyncio.Event()

    def _on_signal(*_):
        log.info("shutdown signal")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows
            signal.signal(sig, lambda *_: _on_signal())

    try:
        while not stop.is_set():
            try:
                job = await queue_client.consume(consumer_id)
            except Exception as e:
                log.error("queue consume failed", err=str(e))
                await asyncio.sleep(2)
                continue

            if job is None:
                # Idle backoff.
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                continue

            await _handle_job(job)
    finally:
        await close_pool()
        log.info("worker stopped")


async def _handle_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    kind = job["kind"]
    log.info("job", id=str(job_id), kind=kind, attempts=job["attempts"])

    try:
        if kind == "snapshot_ready":
            payload = job["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            try:
                next_id = await run_one_step(payload["snapshot_id"])
                if next_id is not None:
                    await queue_client.enqueue_snapshot_ready(
                        str(job["tenant_id"]), next_id
                    )
            except TerminalSignal:
                pass
        else:
            await trigger_router.handle_trigger(job)
        await queue_client.ack(job_id)
    except Exception as e:
        log.exception("job failed", id=str(job_id))
        await queue_client.nack(job_id, error=str(e))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
