"use client";

import { MessagesSquare } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DisconnectButton } from "./disconnect-button";

type Connection = {
  id: string;
  status: "pending" | "connected" | "failed" | "revoked";
  display_name?: string | null;
  config?: { channel?: string; workspace_name?: string } | null;
};

export function SlackCard({ connection }: { connection: Connection | null }) {
  const router = useRouter();
  const [showForm, setShowForm] = useState(false);
  const [token, setToken] = useState("");
  const [channel, setChannel] = useState("#alerts");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    if (!token.startsWith("xoxb-")) {
      setErr('Bot tokens start with "xoxb-". Make sure you copied the Bot User OAuth Token.');
      return;
    }
    setBusy(true);
    setErr(null);
    const r = await fetch("/api/connections/slack/store-install", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ bot_token: token, channel, workspace_name: "Slack" }),
    });
    setBusy(false);
    if (!r.ok) {
      setErr(`Failed: ${r.status} ${await r.text()}`);
      return;
    }
    setShowForm(false);
    router.refresh();
  }

  if (connection?.status === "connected") {
    const ch = connection.config?.channel ?? "#alerts";
    return (
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-md bg-muted grid place-items-center">
            <MessagesSquare size={18} />
          </div>
          <div>
            <div className="font-medium leading-tight">Slack</div>
            <span className="inline-block text-[10px] uppercase tracking-wide font-semibold rounded px-1.5 py-0.5 bg-emerald-100 text-emerald-800">
              Connected
            </span>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          Posting findings to <code className="font-mono">{ch}</code>
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setShowForm(true)}
            className="inline-flex items-center text-sm rounded-md border px-3 py-1.5 hover:bg-accent"
          >
            Update token / channel
          </button>
          <DisconnectButton connectionId={connection.id} kind="slack" />
        </div>
        {showForm && <Form token={token} setToken={setToken} channel={channel} setChannel={setChannel} busy={busy} err={err} submit={submit} cancel={() => setShowForm(false)} />}
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <div className="flex items-center gap-3">
        <div className="size-9 rounded-md bg-muted grid place-items-center">
          <MessagesSquare size={18} />
        </div>
        <div>
          <div className="font-medium leading-tight">Slack</div>
          <span className="inline-block text-[10px] uppercase tracking-wide font-semibold rounded px-1.5 py-0.5 bg-muted text-muted-foreground">
            Not connected
          </span>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        Pick a channel for findings + verification updates.
      </p>
      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          className="inline-flex items-center text-sm rounded-md border px-3 py-1.5 hover:bg-accent"
        >
          Connect
        </button>
      ) : (
        <Form token={token} setToken={setToken} channel={channel} setChannel={setChannel} busy={busy} err={err} submit={submit} cancel={() => setShowForm(false)} />
      )}
    </div>
  );
}

function Form({
  token, setToken, channel, setChannel, busy, err, submit, cancel,
}: {
  token: string; setToken: (s: string) => void;
  channel: string; setChannel: (s: string) => void;
  busy: boolean; err: string | null;
  submit: () => void; cancel: () => void;
}) {
  return (
    <div className="space-y-2 pt-2 border-t">
      <p className="text-xs text-muted-foreground">
        Create a Slack App at{" "}
        <a className="underline" href="https://api.slack.com/apps" target="_blank">
          api.slack.com/apps
        </a>
        , add Bot Token Scopes <code>chat:write</code>, <code>chat:write.public</code>,
        install to your workspace, and paste the <code>xoxb-…</code> token.
      </p>
      <input
        type="password"
        placeholder="xoxb-…"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="w-full text-xs font-mono rounded-md border border-input px-3 py-2"
      />
      <input
        type="text"
        placeholder="#alerts"
        value={channel}
        onChange={(e) => setChannel(e.target.value)}
        className="w-full text-sm rounded-md border border-input px-3 py-2"
      />
      <div className="flex items-center gap-2">
        <button
          onClick={submit}
          disabled={busy || !token}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button
          onClick={cancel}
          className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
        >
          Cancel
        </button>
      </div>
      {err && <p className="text-xs text-destructive">{err}</p>}
    </div>
  );
}
