import Link from "next/link";

import { createClient } from "@/lib/supabase/server";
import { relativeTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function AgentsPage() {
  const supabase = await createClient();
  const { data: agents = [] } = await supabase
    .from("agents")
    .select("id, name, objective, current_issue_id, status, updated_at")
    .neq("status", "archived")
    .order("updated_at", { ascending: false });

  return (
    <div className="p-8 space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
        <Link
          href="/agents/new"
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
        >
          New agent
        </Link>
      </div>

      {(!agents || agents.length === 0) ? (
        <div className="rounded-md border bg-card p-12 text-center space-y-3">
          <div className="text-3xl">🤖</div>
          <h2 className="text-lg font-medium">New Agent</h2>
          <p className="text-sm text-muted-foreground">Define what matters to you in plain language</p>
          <Link
            href="/agents/new"
            className="inline-block rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
          >
            Create agent
          </Link>
        </div>
      ) : (
        <div className="rounded-md border divide-y">
          {agents.map((a) => (
            <Link
              key={a.id}
              href={`/agents/${a.id}` as any}
              className="block px-4 py-3 hover:bg-accent transition"
            >
              <div className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{a.name}</div>
                  <div className="text-sm text-muted-foreground truncate">{a.objective}</div>
                </div>
                <div className="text-xs text-muted-foreground tabular-nums">
                  {relativeTime(a.updated_at)}
                </div>
                <span
                  className={`text-xs px-2 py-0.5 rounded ${
                    a.current_issue_id
                      ? "bg-amber-100 text-amber-800"
                      : "bg-emerald-100 text-emerald-800"
                  }`}
                >
                  {a.current_issue_id ? "Issue found" : "All clear"}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
