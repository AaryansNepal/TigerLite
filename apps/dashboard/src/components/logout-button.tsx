"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LogOut } from "lucide-react";

import { createClient } from "@/lib/supabase/client";

export function LogoutButton() {
  const router = useRouter();
  const supabase = createClient();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function logout() {
    setBusy(true);
    setErr(null);
    const { error } = await supabase.auth.signOut();
    if (error) {
      setBusy(false);
      setErr(error.message);
      return;
    }
    // Force middleware to re-evaluate with the cleared cookie before navigating.
    router.refresh();
    router.replace("/");
  }

  return (
    <div className="space-y-2">
      <button
        onClick={logout}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
      >
        <LogOut size={14} />
        {busy ? "Signing out…" : "Sign out"}
      </button>
      {err && <p className="text-sm text-destructive">{err}</p>}
    </div>
  );
}
