import { GitHubCard } from "@/components/github-card";
import { SlackCard } from "@/components/slack-card";
import { TelemetryConnectCard } from "@/components/telemetry-connect-card";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function IntegrationsPage() {
  const supabase = await createClient();
  const { data: connections = [] } = await supabase
    .from("connections")
    .select("*")
    .order("created_at");
  const conns = connections ?? [];
  const otel = conns.find((c) => c.kind === "otel");
  const github = conns.find((c) => c.kind === "github");
  const slack = conns.find((c) => c.kind === "slack");

  // The GitHub App slug is needed to build the install URL. We pull it
  // through a public env var on the dashboard side so we don't need an
  // API round-trip to render the Connect button.
  const appSlug = process.env.NEXT_PUBLIC_GITHUB_APP_SLUG ?? "tigerlite-dev";

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
      <div className="grid md:grid-cols-3 gap-4">
        <TelemetryConnectCard connection={otel ?? null} />
        <GitHubCard connection={github ?? null} appSlug={appSlug} />
        <SlackCard connection={slack ?? null} />
      </div>
      <p className="text-xs text-muted-foreground">
        Setup guides:{" "}
        <a
          href="https://github.com/AaryansNepal/TigerLite/blob/demo/docs/SETUP_GITHUB_APP.md"
          className="underline"
        >
          GitHub
        </a>
        {" · "}
        <a
          href="https://github.com/AaryansNepal/TigerLite/blob/demo/docs/SETUP_SLACK_APP.md"
          className="underline"
        >
          Slack
        </a>
      </p>
    </div>
  );
}
