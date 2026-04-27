import Link from "next/link";
import { Activity, GitBranch, MessagesSquare } from "lucide-react";

import { ConnectCard } from "@/components/connect-card";
import { TelemetryConnectCard } from "@/components/telemetry-connect-card";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  const { data: connections = [] } = await supabase
    .from("connections")
    .select("*")
    .order("created_at");
  const conns = connections ?? [];

  const otel = conns.find((c) => c.kind === "otel");
  const github = conns.find((c) => c.kind === "github");
  const slack = conns.find((c) => c.kind === "slack");

  const { data: agents = [] } = await supabase
    .from("agents")
    .select("id, name, status, current_issue_id, updated_at")
    .neq("status", "archived")
    .order("updated_at", { ascending: false });

  return (
    <div className="p-8 space-y-8 max-w-5xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome back{user?.email ? `, ${user.email.split("@")[0]}` : ""}
        </h1>
        <p className="text-sm text-muted-foreground">
          Connect your data, then create agents that watch it for you.
        </p>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <TelemetryConnectCard connection={otel ?? null} />
        <ConnectCard
          icon={GitBranch}
          name="GitHub"
          status={github?.status ?? "pending"}
          description={github?.display_name ?? "Connect a repo so the agent can correlate regressions with commits."}
          actionHref="/integrations"
          actionLabel={github?.status === "connected" ? "Manage" : "Connect"}
        />
        <ConnectCard
          icon={MessagesSquare}
          name="Slack"
          status={slack?.status ?? "pending"}
          description={
            slack?.config?.channel
              ? `Posting to ${slack.config.channel}`
              : "Pick a channel for findings and verification updates."
          }
          actionHref="/integrations"
          actionLabel={slack?.status === "connected" ? "Manage" : "Connect"}
        />
      </div>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium tracking-wide uppercase text-muted-foreground">Active agents</h2>
          <Link href="/agents" className="text-sm underline">View all</Link>
        </div>
        {(!agents || agents.length === 0) && (
          <div className="rounded-md border bg-card p-6 text-sm text-muted-foreground">
            No agents yet. <Link href="/agents/new" className="underline">Create your first agent</Link> in plain language.
          </div>
        )}
        {agents && agents.length > 0 && (
          <ul className="rounded-md border divide-y">
            {agents.map((a) => (
              <li key={a.id} className="px-4 py-3 flex items-center gap-3">
                <Activity size={16} className="text-muted-foreground" />
                <Link href={`/agents/${a.id}` as any} className="font-medium hover:underline">{a.name}</Link>
                <span
                  className={`ml-auto text-xs px-2 py-0.5 rounded ${
                    a.current_issue_id
                      ? "bg-amber-100 text-amber-800"
                      : a.status === "active"
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-muted text-muted-foreground"
                  }`}
                >
                  {a.current_issue_id ? "Issue found" : a.status === "active" ? "All clear" : a.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
