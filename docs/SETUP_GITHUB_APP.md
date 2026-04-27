# Setting up the TigerLite GitHub App

For Phase 2. The agent reads commits, diffs, and files from your repo via
the official [`github/github-mcp-server`](https://github.com/github/github-mcp-server).

## 1. Install the binary

```bash
brew install github/github-mcp-server/github-mcp-server
# OR
go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest
```

Confirm:
```bash
which github-mcp-server
```

If it lives somewhere else, set `GITHUB_MCP_COMMAND` in `.env.local`.

## 2. Create the GitHub App

1. https://github.com/settings/apps/new
2. **GitHub App name**: `TigerLite (dev — yourname)` (must be unique).
3. **Homepage URL**: `http://localhost:3000`
4. **Callback URL**: `http://localhost:3000/integrations/github/callback`
5. **Webhook URL**: leave empty for now (Phase 2 polls; webhooks are Phase 3+).
6. **Repository permissions**:
   - Contents: Read
   - Metadata: Read
   - Pull requests: Read & write (Phase 4 stretch — auto-PR)
7. **Where can this GitHub App be installed?** Only on this account.
8. Click *Create GitHub App*.

After creation:
- Generate a **client secret** → copy.
- Generate a **private key** → download. Save it as `.secrets/github-app.pem` at repo root (this path is in `.gitignore`).
- Note the **App ID** at the top.

## 3. Wire into `.env.local`

```
GITHUB_APP_ID=12345678
GITHUB_APP_SLUG=tigerlite-dev-yourname
GITHUB_APP_PRIVATE_KEY_PATH=./.secrets/github-app.pem
GITHUB_APP_CLIENT_ID=Iv1.xxxxxxxxxxxxxxxx
GITHUB_APP_CLIENT_SECRET=replace-with-the-secret-you-just-generated
GITHUB_APP_WEBHOOK_SECRET=anything-random-for-now
```

## 4. Install the App on your fork

1. https://github.com/settings/apps/tigerlite-dev-yourname → *Install App*.
2. Pick *Only select repositories* → choose your `opentelemetry-demo` fork.
3. After install, GitHub redirects to the dashboard's `/integrations/github/callback` route.

The dashboard exchanges the install code for an install token, posts it to
`/api/connections/github/store-install`, and the control plane stores it
encrypted in the `connections` table. The agent runtime then has access via
the `github_connection_id` reference on each agent.

## 5. Test the MCP server

```bash
# Set the token in env, then list tools manually
GITHUB_PERSONAL_ACCESS_TOKEN=<install-token> github-mcp-server --help
```

The agent runtime spawns the MCP server fresh per step; you don't need to
run it manually under normal operation.
