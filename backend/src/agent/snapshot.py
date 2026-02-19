"""Snapshot-based session engine — mirrors FireTiger's Git-inspired design.

Each snapshot is immutable and contains:
- session_id: identifies the agent session
- version: monotonically increasing version number
- parent_version: pointer to previous snapshot (None for root)
- status: running | completed | error
- descriptors: list of content hashes pointing to objects in the object store

Snapshots are stored at: s3://snapshots/sessions/{session_id}/versions/{version}.json
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from io import BytesIO
from typing import Optional

from minio import Minio

from ..config import MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY, SNAPSHOTS_BUCKET

logger = logging.getLogger(__name__)


@dataclass
class Snapshot:
    session_id: str
    version: int
    parent_version: Optional[int]
    status: str  # "running" | "completed" | "error"
    descriptors: list[str] = field(default_factory=list)  # list of object SHA hashes
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class SnapshotStore:
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

    def save(self, snapshot: Snapshot) -> str:
        """Save an immutable snapshot, return its storage path."""
        key = f"sessions/{snapshot.session_id}/versions/{snapshot.version}.json"
        content = json.dumps(snapshot.to_dict(), default=str).encode()

        self.client.put_object(
            SNAPSHOTS_BUCKET,
            key,
            BytesIO(content),
            len(content),
            content_type="application/json",
        )
        logger.info(
            f"Saved snapshot session={snapshot.session_id} v={snapshot.version}"
        )
        return key

    def load(self, session_id: str, version: int) -> Snapshot:
        """Load a specific snapshot version."""
        key = f"sessions/{session_id}/versions/{version}.json"
        resp = self.client.get_object(SNAPSHOTS_BUCKET, key)
        data = json.loads(resp.read())
        resp.close()
        resp.release_conn()
        return Snapshot(**data)

    def get_latest_version(self, session_id: str) -> Optional[int]:
        """Find the latest version number for a session."""
        prefix = f"sessions/{session_id}/versions/"
        versions = []
        for obj in self.client.list_objects(SNAPSHOTS_BUCKET, prefix=prefix):
            # Extract version number from path
            name = obj.object_name.split("/")[-1].replace(".json", "")
            try:
                versions.append(int(name))
            except ValueError:
                continue
        return max(versions) if versions else None

    def list_sessions(self) -> list[str]:
        """List all session IDs."""
        sessions = set()
        for obj in self.client.list_objects(SNAPSHOTS_BUCKET, prefix="sessions/", recursive=False):
            parts = obj.object_name.strip("/").split("/")
            if len(parts) >= 2:
                sessions.add(parts[1])
        return sorted(sessions)

    def list_versions(self, session_id: str) -> list[dict]:
        """List all snapshot versions for a session with metadata."""
        prefix = f"sessions/{session_id}/versions/"
        snapshots = []
        for obj in self.client.list_objects(SNAPSHOTS_BUCKET, prefix=prefix):
            name = obj.object_name.split("/")[-1].replace(".json", "")
            try:
                version = int(name)
                snapshot = self.load(session_id, version)
                snapshots.append(snapshot.to_dict())
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to load snapshot {obj.object_name}: {e}")
        return sorted(snapshots, key=lambda s: s["version"])

    def replay(self, session_id: str, object_store) -> list[dict]:
        """Replay all objects from a session's snapshots in order.

        This reconstructs the full conversation/reasoning chain.
        """
        versions = self.list_versions(session_id)
        objects = []
        seen = set()
        for snapshot_data in versions:
            for sha in snapshot_data.get("descriptors", []):
                if sha not in seen:
                    seen.add(sha)
                    obj = object_store.get(sha)
                    objects.append(obj)
        return objects
