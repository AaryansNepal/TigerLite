"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function DisconnectButton({
  connectionId,
  kind,
}: {
  connectionId: string;
  kind: "github" | "slack" | "otel";
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function disconnect() {
    setBusy(true);
    setErr(null);
    const r = await fetch(`/api/connections/${connectionId}`, { method: "DELETE" });
    setBusy(false);
    if (!r.ok && r.status !== 204) {
      setErr(`Failed: ${r.status} ${await r.text()}`);
      return;
    }
    router.refresh();
  }

  if (!confirming) {
    return (
      <button
        onClick={() => setConfirming(true)}
        className="text-xs text-muted-foreground hover:text-destructive hover:underline"
      >
        Disconnect
      </button>
    );
  }

  return (
    <span className="text-xs flex items-center gap-2">
      <span className="text-muted-foreground">Sure?</span>
      <button
        onClick={disconnect}
        disabled={busy}
        className="text-destructive font-medium hover:underline disabled:opacity-50"
      >
        {busy ? "…" : "Yes, disconnect"}
      </button>
      <button
        onClick={() => setConfirming(false)}
        disabled={busy}
        className="text-muted-foreground hover:underline"
      >
        Cancel
      </button>
      {err && <span className="text-destructive">{err}</span>}
    </span>
  );
}
