import Link from "next/link";
import { Bell, Bot, Boxes, Flag, Home, MessagesSquare, Search, Settings } from "lucide-react";

import { createClient } from "@/lib/supabase/server";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/home", label: "Home", icon: Home },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/change-monitor", label: "Change Monitor", icon: Boxes },
  { href: "/investigate", label: "Investigate", icon: Search },
  { href: "/issues", label: "Issues", icon: Flag, badgeKey: "issues" as const },
  { href: "/integrations", label: "Integrations", icon: MessagesSquare },
];

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  // Open issues count for the sidebar badge — fetched server-side.
  let openIssues = 0;
  if (user) {
    const { count } = await supabase
      .from("issues")
      .select("*", { count: "exact", head: true })
      .in("status", ["open", "verifying", "regressed"]);
    openIssues = count ?? 0;
  }

  return (
    <div className="grid grid-cols-[260px_1fr] min-h-screen">
      <aside className="border-r bg-card flex flex-col">
        <div className="px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xl">🐅</span>
            <span className="font-semibold tracking-tight">TigerLite</span>
          </div>
          <Bell size={16} className="text-muted-foreground" />
        </div>
        <nav className="px-2 flex-1">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href as any}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
                "hover:bg-accent hover:text-accent-foreground transition"
              )}
            >
              <item.icon size={16} />
              <span className="flex-1">{item.label}</span>
              {item.badgeKey === "issues" && openIssues > 0 && (
                <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-amber-200 text-amber-900">
                  {openIssues}
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="border-t p-3 text-sm flex items-center gap-2">
          <div className="size-7 rounded-full bg-muted grid place-items-center text-xs font-medium">
            {user?.email?.[0]?.toUpperCase() ?? "?"}
          </div>
          <span className="truncate text-muted-foreground">{user?.email}</span>
          <Link href="/settings" className="ml-auto text-muted-foreground hover:text-foreground">
            <Settings size={14} />
          </Link>
        </div>
      </aside>
      <main className="bg-background">{children}</main>
    </div>
  );
}
