import { createClient } from "@/lib/supabase/server";
import { TriggerNowButton } from "@/components/trigger-now-button";

export default async function AgentDetailsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data: agent } = await supabase.from("agents").select("*").eq("id", id).single();
  if (!agent) return <div>Not found</div>;

  return (
    <div className="space-y-6 max-w-3xl">
      <section>
        <h2 className="text-sm font-medium text-muted-foreground mb-1">Description</h2>
        <p className="text-sm">{agent.description}</p>
      </section>

      <section>
        <h2 className="text-sm font-medium text-muted-foreground mb-1">Triggers</h2>
        <ul className="text-sm space-y-1">
          <li>🕐 Scheduled: {agent.schedule_cron ?? "(none)"}</li>
          <li>🔔 Anomaly detection: {agent.anomaly_enabled ? "enabled" : "disabled"}</li>
          <li>✋ Manual: <TriggerNowButton agentId={agent.id} /></li>
        </ul>
      </section>

      <section>
        <h2 className="text-sm font-medium text-muted-foreground mb-1">Notifications</h2>
        <p className="text-sm">{agent.slack_channel ?? "(no Slack channel)"}</p>
      </section>

      <section>
        <h2 className="text-sm font-medium text-muted-foreground mb-1">Plan</h2>
        <pre className="text-sm whitespace-pre-wrap rounded-md bg-muted p-3 font-mono">{agent.plan}</pre>
      </section>

      <section>
        <h2 className="text-sm font-medium text-muted-foreground mb-1">Scope</h2>
        <pre className="text-xs rounded-md bg-muted p-3 font-mono">{JSON.stringify(agent.scope_config, null, 2)}</pre>
      </section>
    </div>
  );
}
