import { NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function POST() {
  const r = await controlPlaneFetch("/api/connections/github/sync", { method: "POST" });
  return new NextResponse(await r.text(), {
    status: r.status,
    headers: { "content-type": "application/json" },
  });
}
