import Link from "next/link";

import { createClient } from "@/lib/supabase/server";
import { relativeTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function AgentSessionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data: sessions = [] } = await supabase
    .from("sessions")
    .select("id, kind, status, outcome, started_at, ended_at, finding_summary")
    .eq("agent_id", id)
    .order("started_at", { ascending: false })
    .limit(50);

  if (!sessions || sessions.length === 0) {
    return <p className="text-sm text-muted-foreground">No sessions yet.</p>;
  }

  return (
    <ul className="rounded-md border divide-y">
      {sessions.map((s) => (
        <li key={s.id}>
          <Link
            href={`/agents/${id}/sessions/${s.id}` as any}
            className="flex items-center gap-3 px-4 py-3 hover:bg-accent"
          >
            <span
              className={`text-xs px-2 py-0.5 rounded ${
                s.outcome === "issue_found"
                  ? "bg-amber-100 text-amber-800"
                  : "bg-emerald-100 text-emerald-800"
              }`}
            >
              {s.outcome === "issue_found" ? "ISSUE FOUND" : s.outcome === "no_issues" ? "NO ISSUES" : s.status?.toUpperCase()}
            </span>
            <span className="text-sm text-muted-foreground">{s.kind}</span>
            <span className="text-sm flex-1 truncate">{s.finding_summary ?? ""}</span>
            <span className="text-xs text-muted-foreground tabular-nums">{relativeTime(s.started_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
