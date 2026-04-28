import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const r = await controlPlaneFetch("/api/connections/slack/store-install", {
    method: "POST",
    body,
  });
  return new NextResponse(await r.text(), {
    status: r.status,
    headers: { "content-type": "application/json" },
  });
}
