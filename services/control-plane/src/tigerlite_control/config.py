"""Centralised configuration. Single source of truth for env vars."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    stage: str = Field(default="dev")
    log_level: str = Field(default="info")

    # Database
    database_url: str = Field(...)
    supabase_url: str = Field(...)
    supabase_service_role_key: str = Field(...)

    # Object store
    object_store: str = Field(default="minio")  # minio | s3
    telemetry_bucket: str = Field(default="tigerlite-dev-telemetry")
    snapshots_bucket: str = Field(default="tigerlite-dev-snapshots")

    minio_endpoint: str = Field(default="http://localhost:9000")
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin")

    aws_region: str = Field(default="us-east-1")
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")

    # Iceberg
    iceberg_catalog_uri: str = Field(default="http://localhost:8181")
    iceberg_warehouse: str = Field(default="s3a://tigerlite-dev-telemetry/")

    # Service URLs
    ingest_url: str = Field(default="http://localhost:8080")
    control_plane_url: str = Field(default="http://localhost:8000")
    dashboard_url: str = Field(default="http://localhost:3000")

    # Crypto
    credential_encryption_key: str = Field(default="00" * 32)

    # LLM
    gemini_api_key: str = Field(default="")
    gemini_model_agent: str = Field(default="gemini-2.5-pro")
    gemini_model_compiler: str = Field(default="gemini-2.5-flash")

    # GitHub
    github_app_id: str = Field(default="")
    github_app_slug: str = Field(default="tigerlite-dev")
    github_app_private_key_path: str = Field(default="./.secrets/github-app.pem")
    github_app_client_id: str = Field(default="")
    github_app_client_secret: str = Field(default="")
    github_app_webhook_secret: str = Field(default="")

    # Slack
    slack_client_id: str = Field(default="")
    slack_client_secret: str = Field(default="")
    slack_signing_secret: str = Field(default="")
    slack_bot_user_oauth_token: str = Field(default="")

    # MCP
    github_mcp_command: str = Field(default="github-mcp-server")
    slack_mcp_command: str = Field(default="mcp-server-slack")

    # Anthropic (optional)
    anthropic_api_key: str = Field(default="")

    # Agent runtime
    agent_max_steps: int = Field(default=30)
    agent_tool_timeout_seconds: int = Field(default=60)
    agent_query_result_token_cap: int = Field(default=5000)

    # Watchers
    anomaly_watch_interval_seconds: int = Field(default=60)
    job_visibility_timeout_seconds: int = Field(default=300)
    job_reaper_interval_seconds: int = Field(default=60)

    # Demo
    demo_mode: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    # Walk up to repo root to find .env.local.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env.local").exists() or (parent / ".env").exists():
            # pydantic-settings already reads from env_file paths; this just
            # ensures we run from the right cwd if needed.
            break
    return Settings()  # type: ignore[call-arg]
