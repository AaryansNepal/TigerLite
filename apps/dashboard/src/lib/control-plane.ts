/**
 * Server-side helper for forwarding requests from Next.js API routes to the
 * FastAPI control plane. We attach the user's Supabase access token so the
 * control plane resolves tenant_id from the membership table.
 */

import { createClient } from "./supabase/server";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

export async function controlPlaneFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const headers = new Headers(init.headers ?? {});
  if (session?.access_token) {
    headers.set("Authorization", `Bearer ${session.access_token}`);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store" });
}
