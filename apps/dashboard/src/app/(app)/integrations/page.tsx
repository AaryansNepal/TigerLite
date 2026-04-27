import { Activity, GitBranch, MessagesSquare } from "lucide-react";

import { ConnectCard } from "@/components/connect-card";
import { TelemetryConnectCard } from "@/components/telemetry-connect-card";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function IntegrationsPage() {
  const supabase = await createClient();
  const { data: connections = [] } = await supabase.from("connections").select("*").order("created_at");
  const conns = connections ?? [];
  const otel = conns.find((c) => c.kind === "otel");
  const github = conns.find((c) => c.kind === "github");
  const slack = conns.find((c) => c.kind === "slack");

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
      <div className="grid md:grid-cols-3 gap-4">
        <TelemetryConnectCard connection={otel ?? null} />
        <ConnectCard
          icon={GitBranch}
          name="GitHub"
          status={github?.status ?? "pending"}
          description={
            github?.display_name ?? "Install the TigerLite GitHub App on the repo you want monitored."
          }
          actionHref="/integrations/github"
          actionLabel={github?.status === "connected" ? "Manage" : "Connect"}
        />
        <ConnectCard
          icon={MessagesSquare}
          name="Slack"
          status={slack?.status ?? "pending"}
          description={
            slack?.config?.channel
              ? `Posting to ${slack.config.channel}`
              : "Pick a channel for findings + verification updates."
          }
          actionHref="/integrations/slack"
          actionLabel={slack?.status === "connected" ? "Manage" : "Connect"}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Setup guides:{" "}
        <a href="https://github.com/AaryansNepal/TigerLite/blob/demo/docs/SETUP_GITHUB_APP.md" className="underline">GitHub</a>
        {" · "}
        <a href="https://github.com/AaryansNepal/TigerLite/blob/demo/docs/SETUP_SLACK_APP.md" className="underline">Slack</a>
      </p>
    </div>
  );
}
