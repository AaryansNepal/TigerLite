"""GitHub App authentication helpers.

The flow:
  1. Sign a short-lived JWT with the App's RSA private key (10-minute exp).
  2. Use that JWT to call GitHub's /app/installations/{id}/access_tokens
     endpoint, which returns a 1-hour-lifetime install token scoped to the
     repos the user installed the App on.
  3. Store the install token encrypted in connections.credentials_encrypted.
  4. The agent runtime decrypts and passes it to github-mcp-server via env.

Reference:
  https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import jwt
import structlog

from ..config import get_settings

log = structlog.get_logger(__name__)

GITHUB_API = "https://api.github.com"


def _read_private_key() -> str:
    settings = get_settings()
    path = Path(settings.github_app_private_key_path)
    if not path.is_absolute():
        # Resolve relative to repo root (config.py walks up to find .env.local)
        for parent in Path(__file__).resolve().parents:
            candidate = parent / settings.github_app_private_key_path
            if candidate.exists():
                path = candidate
                break
    if not path.exists():
        raise FileNotFoundError(
            f"GitHub App private key not found at {settings.github_app_private_key_path}. "
            "Download the .pem from your GitHub App settings and save it there."
        )
    return path.read_text()


def make_app_jwt() -> str:
    """RS256-signed JWT identifying our App. Valid for 10 minutes."""
    settings = get_settings()
    if not settings.github_app_id:
        raise ValueError("GITHUB_APP_ID not set")
    private_key = _read_private_key()
    now = int(time.time())
    payload = {
        # Slight backdate to absorb clock skew between us and GitHub
        "iat": now - 60,
        "exp": now + 9 * 60,
        # GitHub accepts either "iss": <int> or "iss": "<str>". PyJWT
        # post-2.0 strict-checks claims and requires iss as a string.
        "iss": str(settings.github_app_id),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def list_installations() -> list[dict[str, Any]]:
    """List every installation of this App. Used when we want to sync an
    existing install (user already clicked Install but the callback was lost).
    """
    token = make_app_jwt()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{GITHUB_API}/app/installations",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        return r.json()


async def get_installation_token(installation_id: int) -> dict[str, Any]:
    """Exchange App JWT + installation_id for a 1-hour install access token."""
    app_jwt = make_app_jwt()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        return r.json()  # { token, expires_at, permissions, repository_selection }


async def list_installation_repos(install_token: str) -> list[dict[str, Any]]:
    """List the repos the user picked during installation."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{GITHUB_API}/installation/repositories",
            headers={
                "Authorization": f"Bearer {install_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        body = r.json()
        return body.get("repositories", [])
