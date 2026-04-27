import { NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function POST() {
  const r = await controlPlaneFetch("/api/connections/otel/issue", { method: "POST" });
  const body = await r.text();
  return new NextResponse(body, { status: r.status, headers: { "content-type": "application/json" } });
}
