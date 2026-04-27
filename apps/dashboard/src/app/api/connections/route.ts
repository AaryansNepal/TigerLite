import { NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function GET() {
  const r = await controlPlaneFetch("/api/connections");
  return new NextResponse(await r.text(), {
    status: r.status,
    headers: { "content-type": "application/json" },
  });
}
