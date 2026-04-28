import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function AgentChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data: agent } = await supabase.from("agents").select("*").eq("id", id).single();
  if (!agent) return <div>Not found</div>;

  const scope =
    typeof agent.scope_config === "string"
      ? JSON.parse(agent.scope_config)
      : agent.scope_config ?? {};
  const endpoints: string[] = scope.endpoints ?? scope.services ?? [];
  const threshold = scope.threshold_ms
    ? `${scope.threshold_ms}ms (p95)`
    : scope.threshold_percent
      ? `${scope.threshold_percent}% error rate`
      : null;

  const turns: Array<{ role: "user" | "agent"; text: string }> = [
    { role: "user", text: agent.objective },
    {
      role: "agent",
      text:
        agent.description ||
        "I'll set up monitoring for what you described. A few questions to scope it correctly:",
    },
  ];

  if (endpoints.length > 0) {
    turns.push({
      role: "agent",
      text:
        endpoints.length === 1
          ? `What I'll watch: ${endpoints[0]}.`
          : `What I'll watch: ${endpoints.join(", ")}.`,
    });
  } else {
    turns.push({
      role: "agent",
      text:
        "Heads-up — no specific endpoints or services are scoped yet. I'll watch broadly. " +
        "Edit the agent's scope on the Details tab to narrow it.",
    });
  }

  if (threshold) {
    turns.push({
      role: "agent",
      text: `Threshold: ${threshold}. I'll flag anything that crosses it.`,
    });
  }

  // Final confirmation message — Firetiger-style.
  const target = agent.slack_channel
    ? `${agent.slack_channel} on Slack`
    : "the dashboard (no Slack channel connected yet)";
  const cadence = agent.schedule_cron
    ? "I'll run scheduled checks plus continuous anomaly detection."
    : "I'll run continuous anomaly detection.";
  const repo = agent.github_repo
    ? ` When something breaks, I'll correlate against recent commits in ${agent.github_repo}.`
    : "";

  turns.push({
    role: "agent",
    text:
      `Got it. I'll monitor ${endpoints.length > 0 ? endpoints.join(" and ") : "the configured scope"}` +
      `${threshold ? ` for ${threshold}` : ""}${repo} and alert ${target}. ${cadence} Starting now.`,
  });

  return (
    <div className="space-y-3 max-w-2xl">
      {turns.map((m, i) => (
        <div
          key={i}
          className={
            m.role === "user"
              ? "rounded-lg bg-secondary px-3 py-2 text-sm self-end max-w-[80%] ml-auto"
              : "rounded-lg bg-card border px-3 py-2 text-sm max-w-[80%]"
          }
        >
          {m.text}
        </div>
      ))}

      <div className="pt-4 text-xs text-muted-foreground border-t mt-6">
        This is a reconstruction of the agent's setup conversation. Real
        ongoing chat happens via the connected Slack channel — replies in
        the agent's Slack thread resume the investigation session via the{" "}
        <code className="px-1 rounded bg-muted">/api/slack/events</code> webhook.
        {!agent.slack_connection_id && (
          <span> Connect Slack on <a href="/integrations" className="underline">Integrations</a> to enable this.</span>
        )}
      </div>
    </div>
  );
}
