import { ClaudeCodeHandoff } from "@/components/claude-code-handoff";
import { createClient } from "@/lib/supabase/server";

export default async function IssueDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data: issue } = await supabase.from("issues").select("*").eq("id", id).single();
  if (!issue) return <div>Not found</div>;
  const { data: findings = [] } = await supabase
    .from("findings")
    .select("*")
    .eq("session_id", issue.opened_by_session_id)
    .order("created_at");

  return (
    <div className="p-8 max-w-3xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">{issue.title}</h1>
      <p className="text-sm text-muted-foreground">{issue.summary}</p>

      <section className="rounded-md border p-4 space-y-2">
        <div className="text-sm">Severity: <strong>{issue.severity}</strong></div>
        <div className="text-sm">Status: <strong>{issue.status}</strong></div>
        <div className="text-sm">Verification attempts: {issue.verification_attempts}</div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Findings</h2>
        {(findings ?? []).length === 0 && <p className="text-sm text-muted-foreground">No findings yet.</p>}
        <ul className="space-y-2">
          {(findings ?? []).map((f) => (
            <li key={f.id} className="rounded-md border p-3 text-sm">
              <div className="font-medium">{f.title}</div>
              <p className="text-muted-foreground">{f.summary}</p>
              {f.suggested_action && (
                <p className="mt-2"><span className="text-xs uppercase text-muted-foreground">Suggestion:</span> {f.suggested_action}</p>
              )}
            </li>
          ))}
        </ul>
      </section>

      <ClaudeCodeHandoff issueId={issue.id} />
    </div>
  );
}
