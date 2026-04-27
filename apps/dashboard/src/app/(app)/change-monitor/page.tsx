export default function ChangeMonitorPage() {
  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight mb-2">Change Monitor</h1>
      <p className="text-sm text-muted-foreground">
        Phase 3+ feature — view recent deploys + correlated incidents in one
        timeline. Wires up the agent's <code>list_recent_commits</code> output
        with <code>findings</code> for the connected GitHub repo.
      </p>
    </div>
  );
}
