"""Object store — boto3 wrapper with retry + client rebuild on transient
connection failures.

Why this is more involved than a simple wrapper: when MinIO (or S3) is
briefly unreachable, boto3's connection pool gets poisoned. Subsequent
requests retry against the dead connection and fail fast, even after the
service comes back. Recovery requires tearing down the client and
rebuilding.

This module:
  - Lazy-builds the singleton boto3 client.
  - On transient errors (EndpointConnectionError, ConnectionRefusedError,
    NewConnectionError, ReadTimeout), tears down the cached client,
    rebuilds, and retries the operation. 3 attempts with exponential
    backoff.
  - 4xx errors (NoSuchKey, PreconditionFailed, etc.) are NOT retried —
    they're application logic that won't get better.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Callable, TypeVar

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from .config import get_settings

log = logging.getLogger(__name__)

T = TypeVar("T")


def _build_client():
    settings = get_settings()
    if settings.object_store == "minio":
        return boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                # Bound the per-request retry budget so we fail fast and let
                # our outer retry handle client rebuild.
                retries={"max_attempts": 2, "mode": "standard"},
                connect_timeout=5,
                read_timeout=15,
            ),
        )
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        config=BotoConfig(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
        ),
    )


_client_singleton = None


def client():
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = _build_client()
    return _client_singleton


def _rebuild_client() -> None:
    """Tear down the cached client + force the next call to build fresh."""
    global _client_singleton
    _client_singleton = None


# Connection-level errors worth retrying with a fresh client. NOT 4xx
# (that's user/data error and won't get better).
_TRANSIENT_EXCEPTIONS = (
    EndpointConnectionError,
    ConnectionClosedError,
    ConnectionRefusedError,
    ReadTimeoutError,
    OSError,  # covers low-level socket errors
)


async def _with_retry(op: Callable[[], T], op_name: str) -> T:
    """Run op() in a thread, retrying on transient failures and rebuilding
    the boto3 client between attempts."""
    delays = [0.0, 0.4, 1.0]
    last_exc: Exception | None = None
    for i, delay in enumerate(delays):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            return await asyncio.to_thread(op)
        except _TRANSIENT_EXCEPTIONS as e:
            last_exc = e
            log.warning(
                "object_store transient error op=%s attempt=%d/%d err=%s",
                op_name, i + 1, len(delays), str(e)[:120],
            )
            _rebuild_client()
        except ClientError:
            # 4xx — bubble up to caller, don't retry
            raise
    assert last_exc is not None
    raise last_exc


async def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    settings = get_settings()

    def _do() -> None:
        client().put_object(
            Bucket=settings.snapshots_bucket, Key=key, Body=data, ContentType=content_type
        )

    await _with_retry(_do, f"put {key[:40]}")


async def put_if_not_exists(
    key: str, data: bytes, content_type: str = "application/octet-stream"
) -> bool:
    settings = get_settings()

    def _do() -> bool:
        try:
            client().put_object(
                Bucket=settings.snapshots_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                IfNoneMatch="*",
            )
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("PreconditionFailed", "412"):
                return False
            raise

    return await _with_retry(_do, f"put_if_not_exists {key[:40]}")


async def get(key: str) -> bytes:
    settings = get_settings()

    def _do() -> bytes:
        obj = client().get_object(Bucket=settings.snapshots_bucket, Key=key)
        return obj["Body"].read()

    return await _with_retry(_do, f"get {key[:40]}")


def hash_key(data: bytes, prefix: str = "objects") -> tuple[str, str]:
    h = hashlib.sha256(data).hexdigest()
    return h, f"{prefix}/{h[:2]}/{h}"


def object_key(h: str) -> str:
    return f"objects/{h[:2]}/{h}"


def snapshot_key(*, tenant_id: str, agent_id: str, session_id: str, version: int) -> str:
    return f"snapshots/{tenant_id}/{agent_id}/{session_id}/{version:08d}.json"
