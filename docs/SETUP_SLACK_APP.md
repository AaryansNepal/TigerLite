# Setting up the TigerLite Slack App

For Phase 2. The agent posts findings to Slack via the
[`modelcontextprotocol/servers/slack`](https://github.com/modelcontextprotocol/servers/tree/main/src/slack)
reference MCP server, and Slack pushes thread replies back to the
`/api/slack/events` endpoint so the agent can answer in-thread.

## 1. Install the Slack MCP server

```bash
npm install -g @modelcontextprotocol/server-slack
```

Confirm:
```bash
which mcp-server-slack
```

If your install path differs, set `SLACK_MCP_COMMAND` in `.env.local`.

## 2. Create the Slack App

1. https://api.slack.com/apps/new → *From scratch*.
2. Name: `TigerLite`. Workspace: pick yours.
3. **OAuth & Permissions** → Bot Token Scopes:
   - `chat:write`
   - `chat:write.public`
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `app_mentions:read`
4. **Event Subscriptions** → Enable.
   - Request URL: `https://<your-domain>/api/slack/events`
     (use ngrok in dev: `ngrok http 3000` → use the ngrok URL).
   - Subscribe to bot events: `app_mention`, `message.channels`, `message.groups`.
5. **Install App** to your workspace. Copy the **Bot User OAuth Token** (`xoxb-...`).
6. Copy the **Signing Secret** from Basic Information.

## 3. Wire into `.env.local`

```
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_SIGNING_SECRET=...
SLACK_BOT_USER_OAUTH_TOKEN=xoxb-...
```

## 4. Connect a workspace via the dashboard

The dashboard has an "Add Slack" button on `/integrations` that walks you
through OAuth. For demo purposes we accept the bot token directly via
`POST /api/connections/slack/store-install` so you can paste the `xoxb-...`
token from step 2 above.

## 5. Test the MCP server

```bash
SLACK_BOT_TOKEN=xoxb-... mcp-server-slack
```

The agent runtime spawns it fresh per step; manual run is for debugging only.

## Notes

- The `/api/slack/events` endpoint verifies signatures using
  `SLACK_SIGNING_SECRET`. If you leave that empty in dev, signature
  verification is bypassed (useful for ngrok testing without HTTPS quirks).
- Thread replies in a connected channel resume the agent session that was
  posted to that thread (see `routes/slack_events.py`).
