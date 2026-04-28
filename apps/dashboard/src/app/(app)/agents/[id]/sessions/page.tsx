import { SessionsList } from "@/components/sessions-list";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function AgentSessionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data: sessions } = await supabase
    .from("sessions")
    .select("id, agent_id, kind, status, outcome, finding_summary, step_count, started_at, ended_at")
    .eq("agent_id", id)
    .order("started_at", { ascending: false })
    .limit(50);

  return <SessionsList agentId={id} initial={(sessions ?? []) as any} />;
}
