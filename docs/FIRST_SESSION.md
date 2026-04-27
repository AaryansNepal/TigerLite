# First session with Claude Code

How to start working on TigerLite v2 with Claude Code.

## Setup (do once)

1. Install Claude Code: `npm install -g @anthropic-ai/claude-code`
2. Optional: install the VS Code extension ("Claude Code" in the marketplace) for inline diff views.
3. Get an Anthropic API key from https://console.anthropic.com — the CLI will prompt you on first run.

## Drop these docs into the repo

```bash
cd ~/path/to/TigerLite
git checkout -b v2

# Copy the docs in
cp ~/Downloads/CLAUDE.md ./
mkdir -p docs
cp ~/Downloads/docs/* ./docs/

git add CLAUDE.md docs/
git commit -m "docs: add v2 plan and architecture"
```

Optionally drop the eight UI screenshots into `docs/design/`:

```bash
mkdir -p docs/design
# ...copy the screenshots in
git add docs/design/
git commit -m "docs: add UI mockups"
```

## Open Claude Code

```bash
cd ~/path/to/TigerLite
claude
```

Or for the VS Code extension: open the repo in VS Code, open the Claude Code panel from the sidebar.

## First prompt

Paste this verbatim. Claude Code will read the docs, understand the project, and start working.

```
Read CLAUDE.md and docs/PLAN.md. We're starting Phase 0 of TigerLite v2 — multi-tenant
foundation and OTLP intake.

Before writing any code, give me your understanding of:
1. What's already in the v1 codebase on the aaryans branch that we should keep, port,
   or rewrite.
2. The first three concrete tasks from Phase 0 you'd tackle, in order.
3. Anything in the plan you'd push back on.

Don't start coding yet. I want to align on the approach first.
```

This forces Claude Code to actually read the context before acting, instead of jumping into half-informed work.

## What to expect

Claude Code will probably:
- Read CLAUDE.md, PLAN.md, ARCHITECTURE.md, DATA_MODEL.md
- Look at the existing repo structure
- Inspect the v1 code on the `aaryans` branch
- Come back with a structured response

If the response is solid, your next prompt is something like:

```
Good. Let's start with the monorepo restructure first — set up the apps/ services/
packages/ infra/ layout per CLAUDE.md, and move the existing code into the new structure
without breaking the v1 build on the aaryans branch.

Show me the proposed file moves before doing them.
```

## Tips for working with Claude Code on a project this size

**Update PLAN.md after every meaningful change.** Tell Claude Code to do this — it's good at maintenance work like keeping checkboxes accurate. Example: `Update docs/PLAN.md to reflect the work we just did. Mark completed checkboxes. Append a status log entry.`

**Reference docs by `@` syntax.** In Claude Code, `@docs/AGENT_DESIGN.md` pulls that file into context for the current message. Use this when working on something specific — don't dump the whole `docs/` every prompt.

**Commit small, often.** Claude Code occasionally goes off the rails. A clean git history with small commits lets you `git reset` to the last known good point without losing days of work.

**For architectural questions during the build, come back to chat.** This Claude.ai conversation has the full design context. If a real architectural question comes up mid-build, paste it into chat for discussion, then bring the decision back to Claude Code as a concrete instruction.

**When you switch phases, start a new Claude Code session.** Long sessions accumulate confused context. After Phase 0 acceptance criteria are met, exit Claude Code, commit, then start fresh with: `Read CLAUDE.md and docs/PLAN.md. Phase 0 is complete (see status log). We're moving to Phase 1.`

## When to ask for help

If Claude Code:
- Proposes architecture changes that contradict CLAUDE.md → push back, point at the doc.
- Wants to add a dependency you've never heard of → ask why; if the answer is "it'll be easier" instead of "we need X capability," reject.
- Suggests removing the snapshot/object pattern in favor of a "simpler" design → hard no. The snapshot model is the architectural unfair advantage. It looks like overhead but it's not.
- Says "it would be cleaner if we just used Lambda" → also no, we're using a worker for the demo. Document, move on.

Most of these are covered in CLAUDE.md's "Critical decisions" and "Anti-patterns" sections — when Claude Code proposes something against those, point at CLAUDE.md and ask it to re-read.

Have fun building. The first time you trigger a feature flag in the Astronomy Shop and watch a Slack message arrive 90 seconds later with the right commit SHA — that's the moment this whole architecture earns its keep.
