"""Phase 4 stretch: ask Claude (via Anthropic API) to draft a fix PR using
the GitHub MCP through TigerLite's agent runtime. Optional — gated behind
ANTHROPIC_API_KEY env. Disabled by default to keep the demo deterministic.

Triggered from the dashboard when the user clicks "Open draft PR" on the
issue page (rather than the default "Copy as Claude Code prompt").

Implementation note: this is intentionally a separate code path from the
in-loop agent. Mixing model providers inside the snapshot loop would muddy
the audit trail.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..config import get_settings

log = structlog.get_logger(__name__)


async def draft_fix_pr(*, prompt: str, repo: str, base_branch: str = "main") -> dict[str, Any]:
    """Run Claude with GitHub MCP tools and ask it to open a draft PR with
    the fix described in `prompt`.

    Returns: { ok, pr_url? , error? }
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not configured"}

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"ok": False, "error": "anthropic SDK not installed"}

    # Phase 4 stretch — placeholder. The real implementation uses Anthropic's
    # tool-use loop with the GitHub MCP tools (create_branch, create_or_update_file,
    # create_pull_request). Wiring is parallel to our internal agent loop but
    # uses Claude rather than Gemini, and runs out-of-band.
    log.info("draft_fix_pr requested", repo=repo, base=base_branch, prompt_len=len(prompt))
    return {
        "ok": False,
        "error": "not_implemented_in_demo",
        "note": (
            "Wire the Anthropic tool-use loop here when you want auto-PRs. "
            "For the demo, the dashboard's 'Copy as Claude Code prompt' button "
            "is the supported path."
        ),
    }
