"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function DeleteAgentButton({
  agentId,
  agentName,
}: {
  agentId: string;
  agentName: string;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onDelete() {
    setBusy(true);
    setErr(null);
    const r = await fetch(`/api/agents/${agentId}`, { method: "DELETE" });
    setBusy(false);
    if (!r.ok && r.status !== 204) {
      setErr(`Failed: ${r.status}`);
      return;
    }
    router.push("/agents");
    router.refresh();
  }

  if (!confirming) {
    return (
      <button
        onClick={() => setConfirming(true)}
        className="text-sm rounded-md border border-destructive/30 text-destructive px-3 py-1.5 hover:bg-destructive/10"
      >
        Delete agent
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <span>
        Delete <strong>{agentName}</strong>? This archives it; sessions and findings stay.
      </span>
      <button
        onClick={onDelete}
        disabled={busy}
        className="rounded-md bg-destructive px-3 py-1 text-destructive-foreground disabled:opacity-50"
      >
        {busy ? "Deleting…" : "Confirm delete"}
      </button>
      <button
        onClick={() => setConfirming(false)}
        disabled={busy}
        className="rounded-md border px-3 py-1 hover:bg-accent"
      >
        Cancel
      </button>
      {err && <span className="text-destructive">{err}</span>}
    </div>
  );
}
