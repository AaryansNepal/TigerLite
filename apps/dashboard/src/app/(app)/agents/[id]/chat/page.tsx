import { LiveChat } from "@/components/live-chat";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function AgentChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data: agent } = await supabase
    .from("agents")
    .select("id, name, chat_transcript, objective, description, scope_config, slack_channel, github_repo, schedule_cron")
    .eq("id", id)
    .single();

  if (!agent) return <div>Not found</div>;

  let transcript = Array.isArray(agent.chat_transcript) ? agent.chat_transcript : [];

  // Backfill: if this agent was created before chat persistence existed,
  // synthesize a starter transcript from its config so the user lands on
  // a chat that has at least their original objective + the agent's
  // description as the first reply.
  if (transcript.length === 0) {
    transcript = [
      {
        role: "user",
        text: agent.objective || "(starting conversation)",
        ts: new Date(0).toISOString(),
      },
      {
        role: "agent",
        text:
          agent.description ||
          "I'll set up monitoring for what you described. Ask me anything below.",
        ts: new Date(0).toISOString(),
      },
    ];
  }

  return <LiveChat agentId={agent.id} initial={transcript as any} />;
}
