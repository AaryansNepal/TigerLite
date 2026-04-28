"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { createClient } from "@/lib/supabase/client";
import { relativeTime } from "@/lib/utils";

type Session = {
  id: string;
  agent_id: string;
  kind: string;
  status: string;
  outcome: string | null;
  finding_summary: string | null;
  step_count: number;
  started_at: string;
  ended_at: string | null;
};

export function SessionsList({ agentId, initial }: { agentId: string; initial: Session[] }) {
  const supabase = createClient();
  const [sessions, setSessions] = useState<Session[]>(initial);

  useEffect(() => {
    const channel = supabase
      .channel(`sessions-${agentId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "sessions", filter: `agent_id=eq.${agentId}` },
        (payload) => {
          if (payload.eventType === "INSERT") {
            setSessions((prev) => [payload.new as Session, ...prev]);
          } else if (payload.eventType === "UPDATE") {
            const next = payload.new as Session;
            setSessions((prev) => prev.map((s) => (s.id === next.id ? next : s)));
          } else if (payload.eventType === "DELETE") {
            const old = payload.old as Session;
            setSessions((prev) => prev.filter((s) => s.id !== old.id));
          }
        }
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase, agentId]);

  if (!sessions || sessions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No sessions yet. Click <strong>Run now</strong> on the Details tab to start one.
      </p>
    );
  }

  return (
    <ul className="rounded-md border divide-y">
      {sessions.map((s) => (
        <li key={s.id}>
          <Link
            href={`/agents/${agentId}/sessions/${s.id}` as any}
            className="flex items-center gap-3 px-4 py-3 hover:bg-accent"
          >
            <StatusPill outcome={s.outcome} status={s.status} />
            <span className="text-sm text-muted-foreground">{s.kind}</span>
            <span className="text-xs text-muted-foreground">{s.step_count} step{s.step_count === 1 ? "" : "s"}</span>
            <span className="text-sm flex-1 truncate">{s.finding_summary ?? ""}</span>
            <span className="text-xs text-muted-foreground tabular-nums">{relativeTime(s.started_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function StatusPill({ outcome, status }: { outcome: string | null; status: string }) {
  if (status === "running") {
    return (
      <span className="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-800 animate-pulse">
        RUNNING
      </span>
    );
  }
  if (outcome === "issue_found") {
    return <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800">ISSUE FOUND</span>;
  }
  if (outcome === "no_issues") {
    return <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">NO ISSUES</span>;
  }
  if (status === "failed") {
    return <span className="text-xs px-2 py-0.5 rounded bg-rose-100 text-rose-800">FAILED</span>;
  }
  if (status === "timed_out") {
    return <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800">TIMED OUT</span>;
  }
  return <span className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground">{status.toUpperCase()}</span>;
}
