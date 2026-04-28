"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; repo: string }
  | { kind: "err"; message: string };

export function GitHubInstalledHandler({
  installationId,
  setupAction,
}: {
  installationId: string;
  setupAction: string;
}) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "idle" });

  useEffect(() => {
    if (!installationId) {
      setState({ kind: "err", message: "No installation_id in URL." });
      return;
    }
    let cancelled = false;
    (async () => {
      setState({ kind: "loading" });
      const r = await fetch("/api/connections/github/exchange", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ installation_id: installationId }),
      });
      if (cancelled) return;
      if (!r.ok) {
        setState({ kind: "err", message: `${r.status} ${await r.text()}` });
        return;
      }
      const conn = await r.json();
      setState({ kind: "ok", repo: conn.display_name });
      // Auto-redirect after 1.5s
      setTimeout(() => router.push("/integrations" as any), 1500);
    })();
    return () => {
      cancelled = true;
    };
  }, [installationId, router]);

  if (state.kind === "loading" || state.kind === "idle") {
    return <p className="text-sm text-muted-foreground">Working…</p>;
  }
  if (state.kind === "err") {
    return (
      <div className="space-y-2">
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive whitespace-pre-wrap">
          {state.message}
        </div>
        <button
          onClick={() => router.push("/integrations" as any)}
          className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
        >
          Back to integrations
        </button>
      </div>
    );
  }
  return (
    <div className="rounded-md border bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
      ✓ Connected to <code className="font-mono">{state.repo}</code>. Redirecting…
    </div>
  );
}
