# UI specification

This doc describes every screen in the dashboard. Drop the visual mockups (the eight screenshots Aaryan provided) into `docs/design/` and reference them from here.

## Layout

Standard app shell across every authenticated screen:

```
┌────────────────────────────────────────────────────────────────────┐
│ ┌──────────────┐ ┌────────────────────────────────────────────┐ │
│ │ 🐅 Tigerlite│ │  Breadcrumb > Path                         │ │
│ │              │ │                                            │ │
│ │ 🏠 Home      │ │  Page Title                                │ │
│ │ 🤖 Agents    │ │                                            │ │
│ │ 📊 Change    │ │  [Tabs if applicable: Details Sessions Chat]│ │
│ │ ✨ Investigate│ │                                            │ │
│ │ 🚩 Issues 1  │ │  Main content                              │ │
│ │ 🧩 Integrate │ │                                            │ │
│ │              │ │                                            │ │
│ │              │ │                                            │ │
│ │              │ │                                            │ │
│ │              │ │                                            │ │
│ │ 👤 User      │ │                                            │ │
│ └──────────────┘ └────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

Sidebar items (left nav, in order): **Home**, **Agents**, **Change Monitor**, **Investigate**, **Issues** (with badge count), **Integrations**. User profile bottom-left. Bell icon top-left for notifications.

Main content area has a breadcrumb when nested (e.g. `Agents > Checkout flow monitor > Session`). Tab nav for views with multiple modes (Details / Sessions / Chat on agents).

## Routes

| Route | Purpose |
|-------|---------|
| `/signup`, `/signin` | Auth (Supabase UI styled with shadcn) |
| `/home` | Connect cards (Telemetry, GitHub, Slack), at-a-glance status |
| `/agents` | List of agents |
| `/agents/new` | Plain-language agent creation (chat UI) |
| `/agents/[id]` | Agent detail (Details tab default) |
| `/agents/[id]/sessions` | Sessions list for this agent |
| `/agents/[id]/sessions/[sid]` | Session timeline (the snapshot rendering) |
| `/agents/[id]/chat` | Chat with the agent (also where creation happens) |
| `/issues` | All open issues across all agents |
| `/issues/[id]` | Issue detail (the "view issue" target) |
| `/integrations` | Connection management (OTel, GitHub, Slack) |
| `/change-monitor` | Phase 3+ — view of recent deploys + correlated incidents |
| `/investigate` | Phase 3+ — ad-hoc DuckDB query interface |

## Home page

Hero section: "Welcome back, {name}." 

Three connection cards in a row. Each card:

- Icon for the service
- Service name
- Status pill ("Not connected" gray, "Connected" green, "Error" red)
- One-line description ("Receiving traces from 5 services" / "Connected to org/repo" / "Posting to #alerts")
- Action button ("Connect" / "Manage" / "Disconnect")

Below cards: a list of currently active agents with status pills (Active, Issue Found, Paused). Click goes to agent detail.

## Telemetry connect modal

Triggered from the Telemetry card. Modal contents:

```
Connect your telemetry

Point your OpenTelemetry-instrumented application at this endpoint.

  Endpoint:   https://api.tigerlite.dev/v1/traces
  Header:     Authorization: Bearer <token>

[Copy as env vars]  [Copy as docker-compose snippet]

Status: 🔄 Waiting for first event...

The card will flip to Connected once we receive your first event.
```

After first event arrives (poll the `connections` table for `last_event_at`), modal updates:

```
Status: ✅ Connected

Detected services: frontend, cart, checkout, payment, recommendation, ...

[Done]
```

## Agents list

Header: "Agents" + "New agent" button (top right).

Table or card-list:

| Name | Objective (truncated) | Last activity | Status |
|------|----------------------|---------------|--------|
| Checkout flow monitor | Watches /checkout and /payment | 2 minutes ago | 🟡 Issue found |
| Cart performance | Cart endpoints under 200ms | 1 hour ago | 🟢 All clear |

Empty state: a centered "New Agent" prompt matching the FireTiger empty state — title, description ("Define what matters to you in plain language"), input box with example placeholder.

## Agent creation (chat UI)

Reference: screenshots 1 + 2.

Two-column-ish layout but really a chat thread. Agent's questions on the left (with the agent avatar), user's answers on the right (highlighted bubble).

Step 1: User types their objective. Plain text input, submit on enter.

Step 2: Agent compiler responds with clarifying questions. Up to 2-3 questions, one per turn.

Examples of questions the compiler might ask (in priority order):

- "What endpoints or services should I watch?" — proposing detected service.name values as suggestions
- "What response time is acceptable?" — with reasonable defaults proposed
- "Which Slack channel should I post findings to?" — listing connected channels
- "How often should I check?" — defaulting to "continuously" (anomaly detection) plus optional cron

Step 3: Once enough info is gathered, agent posts a summary card (green callout, screenshot 2):

```
✅ New agent — {name}
{description}

Triggers
🕐 Scheduled every hour
✋ Manual

Notifications
💬 #alerts channel on Slack

[View Agent]
```

Click "View Agent" navigates to `/agents/[id]` (Details tab).

The compiler must populate, at minimum: `name`, `objective`, `description`, `plan`, `scope_config`, `slack_channel`, `github_repo`. The user can edit any of these on the Details tab.

## Agent detail — Details tab

Reference: screenshots 4 + 5.

Sections, top to bottom:

**Status card.** Big visual element. Shows current state with colored pill:

- `ALL CLEAR` (green) — no open issues
- `ISSUE FOUND` (yellow) — has an open issue, with relative time ("1 minute ago")
- `INVESTIGATING` (blue, animated) — has a running session right now

Status card includes:
- Status pill + relative time
- One-line summary of the current issue (if any)
- "View session →" link
- "View Issue" button (if there's an open issue)

**Description.** Editable single-line text field. Generated by compiler, user can update.

**Triggers.** List of trigger types:
- 🕐 Scheduled every hour [edit]
- 🔔 Anomaly detection: enabled [toggle]
- ✋ Manual [Run now button]

**Notifications.** Connected Slack channel. Editable.

**Plan.** Big editable textarea. The user-editable runbook that gets injected into the agent's system prompt at session start. Default content from compiler:

```
Monitor the checkout flow on /checkout and /payment endpoints.

Response times should stay under 500ms at p95. If they go above that for more than
5 minutes, something is wrong.

Watch for elevated error rates too — compare against the last 7 days to know what's
normal.

When you find an issue:
1. Figure out what changed — check recent deployments first
2. Find the code that's causing it
3. Identify which customers are affected
4. Send findings to #eng-alerts on Slack

After a fix is deployed, watch for 15 minutes to make sure the metrics actually
improve.
```

**Danger zone** (collapsed by default): pause agent, archive agent.

## Agent detail — Sessions tab

Reference: screenshot 7.

Header with date range picker (default: last 24 hours).

List of sessions, most recent first:

```
🟡 ISSUE FOUND        2 minutes ago
🟢 NO ISSUES FOUND    1 hour ago
🟡 ISSUE FOUND        3 hours ago
🟢 NO ISSUES FOUND    yesterday
```

Click any session to navigate to session detail.

Show empty (`NO ISSUES FOUND`) sessions too — they're audit trail proving the agent is actually checking. Don't filter them out.

## Session detail

Reference: screenshots 3 + 6 + 8.

Header: breadcrumb `Agents > {agent name} > Session`. Title: `{agent name} agent session`. Timestamp.

Body: timeline of objects from the snapshot chain rendered as cards. Each card type renders differently:

- **Assistant message**: plain text, like a chat message from the agent.
- **Tool call**: small subtle card showing tool name + summarized args ("Querying telemetry: SELECT ...").
- **Tool result (text)**: indented panel showing the result text (truncated to 5 lines with "Show more").
- **Tool result (file)**: GitHub-styled file panel matching screenshot 3 — file path with GitHub icon, syntax-highlighted code, line numbers.
- **Tool result (table)**: small data table for query results.
- **`record_finding`**: yellow callout with "Issue found" header, summary text, optional code snippet, "View Issue" button (matches screenshot 6).
- **`create_issue`**: green confirmation callout matching screenshot 6 bottom — "New issue — {title}" with summary and "View Issue" button.
- **Verification result**: special card showing metrics comparison (matches screenshot 8) — "Response time (p95): 2.4s → 285ms (88% improvement)."

Footer: if session is still running, live indicator. If terminal, "Session completed in {duration}, {n} steps."

## Issues list

`/issues` — all open issues across all agents for this tenant.

Table:

| Severity | Title | Agent | Status | Opened |
|----------|-------|-------|--------|--------|
| 🟡 High | N+1 query in cart loading | Checkout flow monitor | Verifying | 23 minutes ago |
| 🟢 Low | Slow recommendation queries | Cart performance | Open | 2 hours ago |

Click → issue detail.

## Issue detail

Issue summary + history of related sessions:

- Initial investigation that opened it
- Verification sessions
- Resolution session (if resolved)

Buttons: "Hand off to Claude Code" (Phase 4 — generates context bundle), "Mark resolved manually," "Add comment."

## Integrations page

List of connections. For each: kind, status, connected metadata, actions.

```
OpenTelemetry
✅ Connected — receiving from 5 services
[View endpoint]  [Rotate token]  [Disconnect]

GitHub
✅ Connected — AaryansNepal/opentelemetry-demo
[Manage]  [Disconnect]

Slack
✅ Connected — Workspace Acme, channel #alerts
[Manage]  [Disconnect]
```

## Visual language

- **Colors**: shadcn defaults. Severity uses Tailwind's `red-500` (critical), `amber-500` (high), `yellow-500` (medium), `green-500` (resolved/healthy).
- **Status pills**: rounded-md, small, uppercase, bordered to match screenshots.
- **Cards**: shadcn `Card` primitive. White bg in light mode, restrained borders.
- **Code blocks**: monospace (`var(--font-mono)`), light gray bg, line numbers for files.
- **No emoji decoration** in the UI itself — use Lucide icons throughout. (Sidebar icons are Lucide.)
- **Sentence case** on every label. Never title case. Never all caps except for status pills (a deliberate visual cue).

## Real-time updates

Use Supabase Realtime to subscribe to inserts on `sessions`, `findings`, `issues` for the current tenant. The dashboard updates without polling. Specifically:

- Session detail page: subscribes to that session's snapshot chain. New objects animate in.
- Sessions list: new sessions appear at the top.
- Issues list / sidebar badge: count updates immediately when an agent opens or resolves an issue.
- Status card on agent detail: flips to "Investigating" when a session starts, "Issue found" when a finding records.

Real-time updates are what make the demo feel magical. Audience clicks one button (toggle the flagd flag), and watches the dashboard react without any further input. Don't compromise on this.
