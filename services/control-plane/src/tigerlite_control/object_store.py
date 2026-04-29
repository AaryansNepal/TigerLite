"""Object store abstraction. MinIO (local dev) and AWS S3 (prod) share an
interface; we pick the implementation from settings.object_store.

Used for both:
  - Snapshot manifests + content-addressed objects (snapshots/, objects/)
  - Tool result artifacts (artifacts/)
  - Per-agent memory (agents/{id}/memory/)

The interface is deliberately tiny — get / put / put_if_not_exists — so the
agent runtime never has to think about which implementation it's talking to.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import structlog
from botocore.client import Config as BotoConfig

try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is required at runtime
    boto3 = None  # type: ignore[assignment]

from .config import get_settings

log = structlog.get_logger(__name__)


class ObjectStore(Protocol):
    async def get(self, key: str) -> bytes: ...
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    async def put_if_not_exists(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> bool: ...
    async def exists(self, key: str) -> bool: ...


def make_object_store(bucket: str | None = None) -> "S3CompatibleStore":
    """Returns the configured ObjectStore implementation. Both MinIO and AWS
    S3 are S3-compatible; the only differences are endpoint + signing region.

    The factory is also captured on the store so it can rebuild the boto3
    client on transient connection failures (poisoned connection pool
    after MinIO/S3 blips).
    """
    settings = get_settings()
    if boto3 is None:
        raise RuntimeError("boto3 is not installed; pip install boto3")

    target_bucket = bucket or settings.snapshots_bucket

    def _build():
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

    store = S3CompatibleStore(client=_build(), bucket=target_bucket)
    store._client_factory = _build
    return store


class S3CompatibleStore:
    """Wraps boto3 S3 client with retry-on-transient-failure + client rebuild.

    When MinIO/S3 has a brief blip, boto3's connection pool gets poisoned —
    subsequent requests fail fast against the dead pool even after the
    service comes back. Recovery requires rebuilding the client. This
    wrapper does that automatically on transient errors (3 attempts with
    exponential backoff). 4xx errors bubble up unchanged.
    """

    def __init__(self, client, bucket: str) -> None:
        self.client = client
        self.bucket = bucket
        self._client_factory: Any = None  # set by make_object_store

    def _rebuild(self) -> None:
        if self._client_factory is not None:
            self.client = self._client_factory()

    async def _with_retry(self, op, op_name: str):
        """Run sync op() in a thread; retry on transient connection errors,
        rebuilding the boto3 client between attempts."""
        import asyncio

        from botocore.exceptions import (
            ClientError,
            ConnectionClosedError,
            EndpointConnectionError,
            ReadTimeoutError,
        )

        delays = [0.0, 0.4, 1.0]
        last_exc: Exception | None = None
        for i, delay in enumerate(delays):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                return await asyncio.to_thread(op)
            except (
                EndpointConnectionError,
                ConnectionClosedError,
                ConnectionRefusedError,
                ReadTimeoutError,
                OSError,
            ) as e:
                last_exc = e
                log.warning(
                    "object_store transient error",
                    op=op_name,
                    attempt=f"{i + 1}/{len(delays)}",
                    err=str(e)[:120],
                )
                self._rebuild()
            except ClientError:
                raise
        assert last_exc is not None
        raise last_exc

    async def get(self, key: str) -> bytes:
        def _do() -> bytes:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
            return obj["Body"].read()

        return await self._with_retry(_do, f"get {key[:40]}")

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        def _do() -> None:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await self._with_retry(_do, f"put {key[:40]}")

    async def put_if_not_exists(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> bool:
        """Atomic put using If-None-Match: *. Returns True if we wrote it,
        False if another writer beat us.
        """
        from botocore.exceptions import ClientError

        def _do() -> bool:
            try:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    IfNoneMatch="*",
                )
                return True
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("PreconditionFailed", "412"):
                    return False
                raise

        return await self._with_retry(_do, f"put_if_not_exists {key[:40]}")

    async def exists(self, key: str) -> bool:
        import asyncio

        from botocore.exceptions import ClientError

        def _do() -> bool:
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise

        return await asyncio.to_thread(_do)


def sha256_key(data: bytes, prefix: str = "objects") -> str:
    """Return an S3 key for content-addressed storage of `data`.

    Layout: {prefix}/{sha256[0:2]}/{sha256}
    """
    h = hashlib.sha256(data).hexdigest()
    return f"{prefix}/{h[:2]}/{h}"
