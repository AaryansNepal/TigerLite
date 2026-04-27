"""Runtime config — same envs as control plane, but only the bits this
service needs."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = Field(default="info")
    database_url: str = Field(...)
    control_plane_url: str = Field(default="http://localhost:8000")

    object_store: str = Field(default="minio")
    snapshots_bucket: str = Field(default="tigerlite-dev-snapshots")
    minio_endpoint: str = Field(default="http://localhost:9000")
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin")
    aws_region: str = Field(default="us-east-1")
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")

    gemini_api_key: str = Field(default="")
    gemini_model_agent: str = Field(default="gemini-2.5-pro")

    anthropic_api_key: str = Field(default="")

    github_mcp_command: str = Field(default="github-mcp-server")
    slack_mcp_command: str = Field(default="mcp-server-slack")

    agent_max_steps: int = Field(default=30)
    agent_tool_timeout_seconds: int = Field(default=60)
    agent_query_result_token_cap: int = Field(default=5000)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
