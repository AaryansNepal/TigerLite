import { SessionTimeline } from "@/components/session-timeline";

export default async function SessionPage({
  params,
}: {
  params: Promise<{ id: string; sid: string }>;
}) {
  const { id, sid } = await params;
  return <SessionTimeline agentId={id} sessionId={sid} />;
}
