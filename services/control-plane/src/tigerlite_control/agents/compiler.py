"""Plain-language → AgentConfig compiler.

The user types one sentence ("checkout flow should always be fast"). We call
Gemini Flash with the tenant's auto-detected service inventory and a tight
prompt. The compiler returns either:
  - a complete `AgentConfig` ready to insert, or
  - a small list of clarifying questions (with options) for the dashboard
    to ask the user.

Multi-turn flow: the dashboard collects answers and resubmits the original
objective + answers. The compiler reads `answers` and, if it has enough
info, produces the final config. If still ambiguous, asks more.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import structlog
from google import genai
from google.genai import types as gtypes

from ..config import get_settings
from ..models import AgentConfig

log = structlog.get_logger(__name__)


COMPILER_SYSTEM_PROMPT = """\
You are TigerLite's agent compiler. The user has typed a one-sentence
operational objective in plain English, e.g. "checkout flow should always
be fast" or "alert me when the cart loads slowly".

Your job is to turn that into a structured monitoring spec. Available info:

- The tenant's currently observed services (from incoming OTel traces).
- Connected Slack channels and GitHub repos.
- The user's answers to your earlier clarifying questions, if any.

Decide:
1. Is the objective specific enough? If you need more info to pick endpoints,
   thresholds, or notification channels, return clarifying_questions. Each
   question must include 2-4 concrete options that you pulled from the data
   above (never invent options the user can't pick).
2. If you have enough info, return a complete agent_config with:
   - name: short title ("Checkout flow monitor")
   - description: one-sentence summary
   - plan: a multi-line runbook the user could read and trust
   - scope_config: { metric, endpoints, threshold_ms, ... }
   - schedule_cron: "0 * * * *" if hourly is reasonable, else null
   - slack_channel + github_repo: pick from the connected ones if available

Output STRICT JSON ONLY. Either:
  {"clarifying_questions": [{"slot": "...", "question": "...", "options": [...]}]}
or:
  {"agent_config": {...}}

Be concise. Don't add commentary outside the JSON.
"""


@dataclass
class CompilerResult:
    config: AgentConfig | None
    clarifying_questions: list[dict[str, Any]] | None


async def compile_agent(
    *,
    objective: str,
    answers: dict[str, str],
    detected_services: list[str],
    slack_channels: list[dict[str, Any]],
    github_repos: list[dict[str, Any]],
) -> CompilerResult:
    settings = get_settings()

    if settings.demo_mode and "checkout" in objective.lower() and not answers:
        # Skip clarifying questions for the canonical demo prompt.
        return CompilerResult(
            config=_demo_default_config(slack_channels, github_repos),
            clarifying_questions=None,
        )

    if not settings.gemini_api_key:
        # No LLM available — return a deterministic skeleton that the user
        # can refine on the agent detail page.
        return CompilerResult(
            config=_skeleton_config(objective, slack_channels, github_repos),
            clarifying_questions=None,
        )

    client = genai.Client(api_key=settings.gemini_api_key)

    user_payload = {
        "objective": objective,
        "answers": answers,
        "detected_services": detected_services,
        "slack_channels": [
            {"display_name": c.get("display_name"), "channel": (c.get("config") or {}).get("channel")}
            for c in slack_channels
        ],
        "github_repos": [
            {"display_name": r.get("display_name"), "repo": (r.get("config") or {}).get("repo_full_name")}
            for r in github_repos
        ],
    }

    try:
        resp = await client.aio.models.generate_content(
            model=settings.gemini_model_compiler,
            contents=[
                gtypes.Content(
                    role="user",
                    parts=[gtypes.Part(text=json.dumps(user_payload))],
                )
            ],
            config=gtypes.GenerateContentConfig(
                system_instruction=COMPILER_SYSTEM_PROMPT,
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        text = (resp.text or "").strip()
        parsed = _parse_compiler_json(text)
    except Exception as e:
        log.error("compiler call failed", err=str(e))
        return CompilerResult(
            config=_skeleton_config(objective, slack_channels, github_repos),
            clarifying_questions=None,
        )

    if "clarifying_questions" in parsed:
        return CompilerResult(config=None, clarifying_questions=parsed["clarifying_questions"])

    cfg = parsed.get("agent_config", {})
    cfg.setdefault("objective", objective)
    cfg.setdefault("anomaly_enabled", True)
    cfg.setdefault("schedule_cron", "0 * * * *")
    return CompilerResult(config=AgentConfig.model_validate(cfg), clarifying_questions=None)


def _parse_compiler_json(text: str) -> dict[str, Any]:
    # Defensive: strip code fences if Gemini wraps in ```.
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)


def _skeleton_config(
    objective: str,
    slack_channels: list[dict[str, Any]],
    github_repos: list[dict[str, Any]],
) -> AgentConfig:
    """Fallback when no LLM key is configured. Lets the dashboard work
    without Gemini for early Phase 0/1 testing."""
    slack_channel = None
    if slack_channels:
        slack_channel = (slack_channels[0].get("config") or {}).get("channel")
    github_repo = None
    if github_repos:
        github_repo = (github_repos[0].get("config") or {}).get("repo_full_name")

    return AgentConfig(
        name=objective[:60].rstrip(".").capitalize() or "Untitled monitor",
        objective=objective,
        description=objective,
        plan=(
            "Watch the configured endpoints for performance regressions.\n"
            "When current values exceed the threshold, investigate by querying\n"
            "telemetry for affected requests, correlating with recent commits,\n"
            "and posting a finding to Slack."
        ),
        scope_config={
            "metric": "latency_p95",
            "endpoints": [],
            "threshold_ms": 500,
            "comparison": "greater_than",
        },
        schedule_cron="0 * * * *",
        anomaly_enabled=True,
        slack_channel=slack_channel,
        github_repo=github_repo,
    )


def _demo_default_config(
    slack_channels: list[dict[str, Any]],
    github_repos: list[dict[str, Any]],
) -> AgentConfig:
    slack_channel = None
    if slack_channels:
        slack_channel = (slack_channels[0].get("config") or {}).get("channel") or "#alerts"
    github_repo = None
    if github_repos:
        github_repo = (github_repos[0].get("config") or {}).get("repo_full_name")

    return AgentConfig(
        name="Checkout flow monitor",
        objective="checkout flow should always be fast",
        description="Monitors /checkout and /payment endpoints for errors and slow downs.",
        plan=(
            "Monitor the checkout flow on /checkout and /payment endpoints.\n\n"
            "Response times should stay under 500ms at p95. If they go above\n"
            "that for more than 5 minutes, something is wrong.\n\n"
            "Watch for elevated error rates too — compare against the last 7\n"
            "days to know what's normal.\n\n"
            "When you find an issue:\n"
            "1. Figure out what changed — check recent deployments first.\n"
            "2. Find the code that's causing it.\n"
            "3. Identify which customers are affected.\n"
            "4. Send findings to the connected Slack channel.\n\n"
            "After a fix is deployed, watch for 15 minutes to make sure the\n"
            "metrics actually improve."
        ),
        scope_config={
            "metric": "latency_p95",
            "endpoints": ["/api/checkout", "/api/payment"],
            "threshold_ms": 500,
            "comparison": "greater_than",
        },
        schedule_cron="0 * * * *",
        anomaly_enabled=True,
        slack_channel=slack_channel,
        github_repo=github_repo,
    )
