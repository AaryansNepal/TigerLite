"""Snapshot + object schemas. Content-addressable JSON.

These shapes match docs/AGENT_DESIGN.md. Each object is a dict with a
"type" field; we serialise canonically (sorted keys) so the SHA-256 hash is
stable across re-encodings.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID


# ----------------------------------------------------------
# Object types
# ----------------------------------------------------------

OBJECT_TYPES = {
    "system_prompt",
    "trigger_event",
    "user_message",
    "assistant_message",
    "tool_call",
    "tool_result",
    "reasoning",
}


def make_object(otype: str, content: Any) -> dict[str, Any]:
    if otype not in OBJECT_TYPES:
        raise ValueError(f"unknown object type {otype!r}")
    return {"type": otype, "version": 1, "content": content}


def canonical_bytes(obj: dict[str, Any]) -> bytes:
    """Canonical JSON for hashing. sort_keys, no whitespace, default str."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


# ----------------------------------------------------------
# Snapshot manifest
# ----------------------------------------------------------

def make_snapshot_manifest(
    *,
    tenant_id: str | UUID,
    agent_id: str | UUID,
    session_id: str | UUID,
    version: int,
    object_hashes: list[str],
    parent_snapshot_id: str | None,
    created_at_iso: str,
) -> dict[str, Any]:
    return {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "session_id": str(session_id),
        "version": version,
        "object_hashes": object_hashes,
        "parent_snapshot_id": parent_snapshot_id,
        "created_at": created_at_iso,
    }
