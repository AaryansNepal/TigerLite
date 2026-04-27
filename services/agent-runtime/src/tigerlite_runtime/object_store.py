"""Object store — boto3 wrapper. Mirrors the control plane's so the runtime
is fully decoupled (could even run in a different cluster, talking to S3 only).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from .config import get_settings


def _client():
    settings = get_settings()
    if settings.object_store == "minio":
        return boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )


_client_singleton = None


def client():
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = _client()
    return _client_singleton


async def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    settings = get_settings()
    c = client()

    def _do() -> None:
        c.put_object(Bucket=settings.snapshots_bucket, Key=key, Body=data, ContentType=content_type)

    await asyncio.to_thread(_do)


async def put_if_not_exists(
    key: str, data: bytes, content_type: str = "application/octet-stream"
) -> bool:
    settings = get_settings()
    c = client()

    def _do() -> bool:
        try:
            c.put_object(
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

    return await asyncio.to_thread(_do)


async def get(key: str) -> bytes:
    settings = get_settings()
    c = client()

    def _do() -> bytes:
        obj = c.get_object(Bucket=settings.snapshots_bucket, Key=key)
        return obj["Body"].read()

    return await asyncio.to_thread(_do)


def hash_key(data: bytes, prefix: str = "objects") -> tuple[str, str]:
    h = hashlib.sha256(data).hexdigest()
    return h, f"{prefix}/{h[:2]}/{h}"


def object_key(h: str) -> str:
    return f"objects/{h[:2]}/{h}"


def snapshot_key(*, tenant_id: str, agent_id: str, session_id: str, version: int) -> str:
    return f"snapshots/{tenant_id}/{agent_id}/{session_id}/{version:08d}.json"
