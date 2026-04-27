"""AWS Lambda alternative driver.

This is the Firetiger architecture exactly: each snapshot manifest write
to S3 triggers a Lambda via S3 Event Notifications, which runs one step
of the agent loop. The new snapshot from that step triggers the next
Lambda automatically.

We do NOT use this for the demo (the worker is simpler), but the property
that matters — `run_one_step` is a pure function with no in-memory state —
means swapping drivers is mechanical.

To deploy:
  1. Package this module + run_step + snapshot_store + tools + llm + crypto
     into a Lambda function.
  2. Configure S3 Event Notifications on the snapshots/ prefix to invoke
     this handler for every PutObject ending in .json.
  3. The Lambda needs DATABASE_URL, GEMINI_API_KEY, and the snapshots bucket
     credentials.

For dev parity: `python -m tigerlite_runtime.lambda_handler '<snapshot-key>'`
runs a single step against the configured S3 bucket.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import structlog

from . import queue_client
from .run_step import TerminalSignal, run_one_step

log = structlog.get_logger(__name__)


def handler(event: dict[str, Any], context: Any | None = None) -> dict[str, Any]:
    """Lambda entry point. Pulls the S3 key from the event and runs one step.

    The function shape matches AWS Lambda's expected signature
    (event: dict, context: object) → dict.
    """
    snapshot_key = _parse_s3_event_key(event)
    if not snapshot_key:
        return {"statusCode": 400, "body": "no snapshot key in event"}
    try:
        next_id = asyncio.run(_run_and_chain(snapshot_key))
    except TerminalSignal:
        return {"statusCode": 200, "body": "terminal"}
    return {"statusCode": 200, "body": json.dumps({"next_snapshot": next_id})}


async def _run_and_chain(snapshot_id: str) -> str | None:
    next_id = await run_one_step(snapshot_id)
    # In Lambda mode, the next Lambda is triggered automatically by the S3
    # event for the new snapshot. We still enqueue a snapshot_ready so the
    # mixed-driver case works.
    if next_id is not None:
        # Postgres queue is optional in pure-S3 mode; we skip on error.
        try:
            from .db import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                tenant_id = (await _read_tenant_id(snapshot_id))
            if tenant_id:
                await queue_client.enqueue_snapshot_ready(tenant_id, next_id)
        except Exception as e:
            log.warning("failed to enqueue snapshot_ready", err=str(e))
    return next_id


async def _read_tenant_id(snapshot_id: str) -> str | None:
    from . import snapshot_store
    snap = await snapshot_store.read_snapshot(snapshot_id)
    return snap.get("tenant_id")


def _parse_s3_event_key(event: dict[str, Any]) -> str | None:
    # AWS S3 event shape: event["Records"][0]["s3"]["object"]["key"]
    try:
        return event["Records"][0]["s3"]["object"]["key"]
    except (KeyError, IndexError, TypeError):
        # Direct invocation: {"snapshot_id": "..."}
        return event.get("snapshot_id") if isinstance(event, dict) else None


# Local invocation for parity testing.
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m tigerlite_runtime.lambda_handler <snapshot-key>", file=sys.stderr)
        sys.exit(2)
    result = handler({"snapshot_id": sys.argv[1]})
    print(json.dumps(result))
