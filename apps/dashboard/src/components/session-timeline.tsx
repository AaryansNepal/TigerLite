"use client";

import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";

type Obj = { type: string; content: any };

export function SessionTimeline({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const supabase = createClient();
  const [objects, setObjects] = useState<Obj[]>([]);
  const [latestSnapshot, setLatestSnapshot] = useState<string | null>(null);

  // Initial fetch
  useEffect(() => {
    let cancelled = false;
    async function load() {
      const r = await fetch(`/api/sessions/${sessionId}/timeline`);
      if (!r.ok || cancelled) return;
      const data = (await r.json()) as { objects: Obj[]; snapshot_id: string };
      setObjects(data.objects ?? []);
      setLatestSnapshot(data.snapshot_id);
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
      {objects.length === 0 && (
        <div className="text-sm text-muted-foreground">Investigation starting…</div>
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
