"use client";

import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";

type Obj = { type: string; content: any };

export function SessionTimeline({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const supabase = createClient();
  const [objects, setObjects] = useState<Obj[]>([]);
  const [latestSnapshot, setLatestSnapshot] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Initial fetch with auto-retry on transient failures (5xx, network).
  // Supabase's pooler hiccups occasionally — without retry the user sees
  // "Failed to load session HTTP 500" and has to refresh. With retry +
  // exponential backoff, single blips become invisible.
  useEffect(() => {
    let cancelled = false;

    async function fetchOnce(): Promise<{ ok: true; data: any } | { ok: false; status: number; text: string }> {
      const r = await fetch(`/api/sessions/${sessionId}/timeline`, { cache: "no-store" });
      if (r.ok) return { ok: true, data: await r.json() };
      return { ok: false, status: r.status, text: await r.text() };
    }

    async function load() {
      setLoading(true);
      setErr(null);
      const delays = [0, 400, 1200, 2500]; // 4 tries, ~4s total worst case
      for (let i = 0; i < delays.length; i++) {
        if (cancelled) return;
        if (delays[i] > 0) await new Promise((r) => setTimeout(r, delays[i]));
        try {
          const result = await fetchOnce();
          if (cancelled) return;
          if (result.ok) {
            setObjects(result.data.objects ?? []);
            setLatestSnapshot(result.data.snapshot_id);
            setErr(null);
            setLoading(false);
            return;
          }
          // Only retry on 5xx + 408 (timeout). 4xx errors don't get better.
          const transient = result.status >= 500 || result.status === 408;
          if (!transient || i === delays.length - 1) {
            setErr(`HTTP ${result.status}: ${result.text.slice(0, 200)}`);
            setLoading(false);
            return;
          }
        } catch (e) {
          if (cancelled) return;
          if (i === delays.length - 1) {
            setErr(e instanceof Error ? e.message : String(e));
            setLoading(false);
            return;
          }
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Realtime: re-pull timeline when the session row updates (latest_snapshot_id changes)
  useEffect(() => {
    const channel = supabase
      .channel(`session-${sessionId}`)
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "sessions", filter: `id=eq.${sessionId}` },
        async (payload) => {
          const next = payload.new as { latest_snapshot_id: string | null };
          if (next.latest_snapshot_id && next.latest_snapshot_id !== latestSnapshot) {
            const r = await fetch(`/api/sessions/${sessionId}/timeline`);
            if (r.ok) {
              const data = await r.json();
              setObjects(data.objects ?? []);
              setLatestSnapshot(data.snapshot_id);
            }
          }
        }
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase, sessionId, latestSnapshot]);

  return (
    <div className="space-y-3">
      {loading && objects.length === 0 && (
        <div className="text-sm text-muted-foreground">Loading session timeline…</div>
      )}
      {err && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive flex items-center gap-3">
          <span className="flex-1">{err}</span>
          <button
            onClick={() => window.location.reload()}
            className="text-xs rounded-md border border-destructive/40 px-2 py-1 hover:bg-destructive/10"
          >
            Retry
          </button>
        </div>
      )}
      {!loading && !err && objects.length === 0 && (
        <div className="text-sm text-muted-foreground">
          This session has no objects yet. The agent may still be initialising —
          updates appear here in real time.
        </div>
      )}
      {objects.map((obj, i) => (
        <Card key={i} obj={obj} />
      ))}
    </div>
  );
}

function Card({ obj }: { obj: Obj }) {
  const t = obj.type;
  if (t === "system_prompt") {
    return null; // hide system prompt; it's always there
  }
  if (t === "trigger_event") {
    return (
      <div className="rounded-md border bg-amber-50 px-3 py-2 text-sm">
        <div className="font-medium">Trigger received</div>
        <pre className="text-xs mt-1 whitespace-pre-wrap">
          {JSON.stringify(obj.content, null, 2)}
        </pre>
      </div>
    );
  }
  if (t === "assistant_message") {
    return (
      <div className="rounded-md border bg-card px-3 py-2 text-sm whitespace-pre-wrap">
        {obj.content?.text}
      </div>
    );
  }
  if (t === "user_message") {
    return (
      <div className="rounded-md bg-secondary px-3 py-2 text-sm">{obj.content?.text}</div>
    );
  }
  if (t === "tool_call") {
    return (
      <div className="rounded-md border-l-2 border-primary pl-3 text-xs text-muted-foreground">
        → {obj.content?.name}({JSON.stringify(obj.content?.args).slice(0, 120)}…)
      </div>
    );
  }
  if (t === "tool_result") {
    const r = obj.content?.result ?? {};
    if (r.posted) {
      return (
        <div className="rounded-md border bg-emerald-50 px-3 py-2 text-sm">
          ✓ Posted to Slack thread {r.thread_ts}
        </div>
      );
    }
    if (r.finding_id) {
      return (
        <div className="rounded-md border bg-amber-50 px-3 py-2 text-sm">
          🚩 Finding recorded: {r.signature}
        </div>
      );
    }
    if (r.issue_id) {
      return (
        <div className="rounded-md border bg-amber-50 px-3 py-2 text-sm">
          📌 New issue: {r.deduped ? "(deduped existing)" : "opened"}
        </div>
      );
    }
    return (
      <div className="rounded-md border bg-muted/50 px-3 py-2 text-xs font-mono whitespace-pre-wrap">
        {JSON.stringify(r, null, 2).slice(0, 500)}
      </div>
    );
  }
  return null;
}
