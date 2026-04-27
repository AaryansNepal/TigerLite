import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function GET() {
  const r = await controlPlaneFetch("/api/agents");
  return new NextResponse(await r.text(), {
    status: r.status,
    headers: { "content-type": "application/json" },
  });
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  const r = await controlPlaneFetch("/api/agents", { method: "POST", body });
  return new NextResponse(await r.text(), {
    status: r.status,
    headers: { "content-type": "application/json" },
  });
}
