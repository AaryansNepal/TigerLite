export default function AgentChatPage() {
  return (
    <div className="text-sm text-muted-foreground">
      Direct chat with the agent is wired through the Slack thread for now —
      reply in the connected channel and the agent picks it up via the
      <code className="mx-1 px-1 rounded bg-muted">/api/slack/events</code> webhook.
      Future: surface the same conversation here.
    </div>
  );
}
