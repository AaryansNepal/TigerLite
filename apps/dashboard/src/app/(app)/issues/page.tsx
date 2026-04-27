import Link from "next/link";

import { createClient } from "@/lib/supabase/server";
import { relativeTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function IssuesPage() {
  const supabase = await createClient();
  const { data: issues = [] } = await supabase
    .from("issues")
    .select("id, title, severity, status, agent_id, opened_at")
    .order("opened_at", { ascending: false })
    .limit(100);

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Issues</h1>
      {(!issues || issues.length === 0) ? (
        <p className="text-sm text-muted-foreground">No issues yet — your agents will report findings here.</p>
      ) : (
        <ul className="rounded-md border divide-y">
          {issues.map((i) => (
            <li key={i.id}>
              <Link href={`/issues/${i.id}` as any} className="flex items-center gap-3 px-4 py-3 hover:bg-accent">
                <SeverityPill severity={i.severity} />
                <span className="flex-1 truncate font-medium">{i.title}</span>
                <span className="text-xs px-2 py-0.5 rounded bg-muted">{i.status}</span>
                <span className="text-xs text-muted-foreground tabular-nums">{relativeTime(i.opened_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SeverityPill({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    low: "bg-emerald-100 text-emerald-800",
    medium: "bg-yellow-100 text-yellow-800",
    high: "bg-amber-100 text-amber-800",
    critical: "bg-rose-100 text-rose-800",
  };
  return (
    <span className={`text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${map[severity] ?? "bg-muted"}`}>
      {severity}
    </span>
  );
}
