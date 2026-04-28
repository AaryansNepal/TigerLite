import { GitHubInstalledHandler } from "@/components/github-installed-handler";

export const dynamic = "force-dynamic";

export default async function GitHubInstalledPage({
  searchParams,
}: {
  searchParams: Promise<{ installation_id?: string; setup_action?: string }>;
}) {
  const params = await searchParams;
  const installationId = params.installation_id ?? "";
  const setupAction = params.setup_action ?? "install";

  return (
    <div className="p-8 max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight mb-2">
        Connecting GitHub…
      </h1>
      <p className="text-sm text-muted-foreground mb-6">
        Exchanging installation <code className="font-mono">{installationId || "?"}</code>
        {" "}for an access token.
      </p>
      <GitHubInstalledHandler installationId={installationId} setupAction={setupAction} />
    </div>
  );
}
