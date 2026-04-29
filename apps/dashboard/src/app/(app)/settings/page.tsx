import { LogoutButton } from "@/components/logout-button";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  let tenantName: string | null = null;
  let tenantSlug: string | null = null;
  let role: string | null = null;
  if (user) {
    const { data: membership } = await supabase
      .from("memberships")
      .select("role, tenants(name, slug)")
      .eq("user_id", user.id)
      .order("created_at")
      .limit(1)
      .maybeSingle();
    role = membership?.role ?? null;
    const t = (membership as any)?.tenants;
    tenantName = t?.name ?? null;
    tenantSlug = t?.slug ?? null;
  }

  return (
    <div className="p-8 space-y-8 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Account and workspace.
        </p>
      </div>

      <section className="border rounded-lg bg-card divide-y">
        <Row label="Email" value={user?.email ?? "—"} />
        <Row label="Workspace" value={tenantName ?? "—"} hint={tenantSlug ?? undefined} />
        <Row label="Role" value={role ?? "—"} />
      </section>

      <section className="border rounded-lg bg-card p-5 space-y-3">
        <div>
          <h2 className="font-medium">Sign out</h2>
          <p className="text-sm text-muted-foreground">
            End this session on this device.
          </p>
        </div>
        <LogoutButton />
      </section>
    </div>
  );
}

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="px-5 py-4 flex items-center justify-between gap-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-right">
        {value}
        {hint && <span className="block text-xs text-muted-foreground font-normal">{hint}</span>}
      </span>
    </div>
  );
}
