"use client";

import { useState } from "react";

export function TriggerNowButton({ agentId }: { agentId: string }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setMsg(null);
    const r = await fetch(`/api/agents/${agentId}/trigger`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reason: "manual_run" }),
    });
    setBusy(false);
    if (r.ok) setMsg("Run queued — check Sessions tab.");
    else setMsg("Failed to queue.");
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={run}
        disabled={busy}
        className="text-sm rounded-md border px-2 py-0.5 hover:bg-accent disabled:opacity-50"
      >
        {busy ? "Queuing…" : "Run now"}
      </button>
      {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
    </span>
  );
}
