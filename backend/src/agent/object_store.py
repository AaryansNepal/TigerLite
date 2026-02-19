"""Content-addressable JSON object store on MinIO.

Mirrors FireTiger's immutable object storage pattern:
every object is stored at s3://snapshots/objects/{sha256}.json
"""

import hashlib
import json
import logging
from io import BytesIO

from minio import Minio

from ..config import MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY, SNAPSHOTS_BUCKET

logger = logging.getLogger(__name__)


class ObjectStore:
    def __init__(self):
        self.client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False,
        )
        self._ensure_bucket()

    def _ensure_bucket(self):
        if not self.client.bucket_exists(SNAPSHOTS_BUCKET):
            self.client.make_bucket(SNAPSHOTS_BUCKET)

    def put(self, data: dict) -> str:
        """Store a JSON object, return its content hash."""
        content = json.dumps(data, sort_keys=True, default=str).encode()
        sha = hashlib.sha256(content).hexdigest()
        key = f"objects/{sha}.json"

        try:
            self.client.stat_object(SNAPSHOTS_BUCKET, key)
        except Exception:
            self.client.put_object(
                SNAPSHOTS_BUCKET,
                key,
                BytesIO(content),
                len(content),
                content_type="application/json",
            )
            logger.debug(f"Stored object {sha[:12]}")

        return sha

    def get(self, sha: str) -> dict:
        """Retrieve a JSON object by its content hash."""
        key = f"objects/{sha}.json"
        resp = self.client.get_object(SNAPSHOTS_BUCKET, key)
        data = json.loads(resp.read())
        resp.close()
        resp.release_conn()
        return data
