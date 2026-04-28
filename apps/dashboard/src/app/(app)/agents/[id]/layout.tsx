import { headers } from "next/headers";
import Link from "next/link";

import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

export default async function AgentLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await createClient();
  const { data: agent } = await supabase
    .from("agents")
    .select("id, name, current_issue_id, status")
    .eq("id", id)
    .single();

  if (!agent) return <div className="p-8">Agent not found.</div>;

  // Read the current path so we can highlight the active tab and adjust the
  // breadcrumb when we're inside a session detail page.
  const h = await headers();
  const pathname = h.get("x-invoke-path") || h.get("x-pathname") || h.get("referer") || "";
  const path = pathname.replace(/^https?:\/\/[^/]+/, "");

  const tabs = [
    { href: `/agents/${agent.id}`, label: "Details", match: (p: string) => p === `/agents/${agent.id}` || p === `/agents/${agent.id}/` },
    { href: `/agents/${agent.id}/sessions`, label: "Sessions", match: (p: string) => p.startsWith(`/agents/${agent.id}/sessions`) },
    { href: `/agents/${agent.id}/chat`, label: "Chat", match: (p: string) => p.startsWith(`/agents/${agent.id}/chat`) },
  ];

  // Detect "I'm inside a specific session" so we can show that in the breadcrumb.
  const inSession = /\/agents\/[^/]+\/sessions\/[0-9a-f-]{36}/i.test(path);

  return (
    <div className="px-8 pt-6">
      <div className="text-sm text-muted-foreground mb-2">
        <Link href="/agents" className="hover:underline">Agents</Link>
        {" / "}
        <Link href={`/agents/${agent.id}` as any} className="hover:underline">{agent.name}</Link>
        {inSession && (
          <>
            {" / "}
            <Link href={`/agents/${agent.id}/sessions` as any} className="hover:underline">Sessions</Link>
            {" / "}
            <span>Session</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-3 mb-4">
        <h1 className="text-2xl font-semibold tracking-tight">{agent.name}</h1>
        <span
          className={cn(
            "text-xs px-2 py-0.5 rounded font-semibold",
            agent.current_issue_id
              ? "bg-amber-100 text-amber-800"
              : "bg-emerald-100 text-emerald-800"
          )}
        >
          {agent.current_issue_id ? "ISSUE FOUND" : "ALL CLEAR"}
        </span>
      </div>
      <nav className="border-b mb-6 flex">
        {tabs.map((t) => {
          const active = t.match(path);
          return (
            <Link
              key={t.href}
              href={t.href as any}
              className={cn(
                "inline-block px-3 py-2 text-sm border-b-2 transition",
                active
                  ? "border-foreground font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground"
              )}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
