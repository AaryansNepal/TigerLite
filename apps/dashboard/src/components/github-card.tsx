import { GitBranch } from "lucide-react";

import { ConnectCard } from "./connect-card";
import { DisconnectButton } from "./disconnect-button";

type Connection = {
  id: string;
  status: "pending" | "connected" | "failed" | "revoked";
  display_name?: string | null;
  config?: {
    repos?: string[];
    repo_full_name?: string;
    expires_at?: string;
  } | null;
};

export function GitHubCard({
  connection,
  appSlug,
}: {
  connection: Connection | null;
  appSlug: string;
}) {
  // Direct GitHub install URL — no Next.js round-trip, no JWT, no failure modes
  // before the user reaches GitHub.
  const installUrl = `https://github.com/apps/${appSlug}/installations/new`;

  if (connection?.status === "connected") {
    const repos = connection.config?.repos ?? [];
    const primary = connection.display_name ?? "GitHub";
    const description =
      repos.length > 1
        ? `Connected to ${primary} (+${repos.length - 1} more repos)`
        : `Connected to ${primary}`;

    return (
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-md bg-muted grid place-items-center">
            <GitBranch size={18} />
          </div>
          <div>
            <div className="font-medium leading-tight">GitHub</div>
            <span className="inline-block text-[10px] uppercase tracking-wide font-semibold rounded px-1.5 py-0.5 bg-emerald-100 text-emerald-800">
              Connected
            </span>
          </div>
        </div>
        <p className="text-sm text-muted-foreground line-clamp-2">{description}</p>
        <div className="flex items-center gap-2 flex-wrap">
          <a
            href={installUrl}
            className="inline-flex items-center text-sm rounded-md border px-3 py-1.5 hover:bg-accent"
          >
            Change repos
          </a>
          <DisconnectButton connectionId={connection.id} kind="github" />
        </div>
      </div>
    );
  }

  // Not connected — single anchor straight to GitHub install. Skips
  // the intermediate /integrations/github page entirely.
  return (
    <ConnectCard
      icon={GitBranch}
      name="GitHub"
      status={connection?.status ?? "pending"}
      description="Install the TigerLite app on the repo you want monitored. The agent will correlate regressions with recent commits."
      actionHref={installUrl}
      actionLabel="Connect"
    />
  );
}
