import Link from "next/link";

import { createClient } from "@/lib/supabase/server";

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

  const tabs = [
    { href: `/agents/${agent.id}`, label: "Details" },
    { href: `/agents/${agent.id}/sessions`, label: "Sessions" },
    { href: `/agents/${agent.id}/chat`, label: "Chat" },
  ];

  return (
    <div className="px-8 pt-6">
      <div className="text-sm text-muted-foreground mb-2">
        <Link href="/agents" className="hover:underline">Agents</Link>
        {" / "}
        <span>{agent.name}</span>
      </div>
      <div className="flex items-center gap-3 mb-4">
        <h1 className="text-2xl font-semibold tracking-tight">{agent.name}</h1>
        <span
          className={`text-xs px-2 py-0.5 rounded ${
            agent.current_issue_id
              ? "bg-amber-100 text-amber-800"
              : "bg-emerald-100 text-emerald-800"
          }`}
        >
          {agent.current_issue_id ? "ISSUE FOUND" : "ALL CLEAR"}
        </span>
      </div>
      <nav className="border-b mb-6">
        {tabs.map((t) => (
          <Link
            key={t.href}
            href={t.href as any}
            className="inline-block px-3 py-2 text-sm border-b-2 border-transparent hover:border-foreground"
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
