import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function GET(req: NextRequest) {
  const r = await controlPlaneFetch(`/api/issues${req.nextUrl.search}`);
  return new NextResponse(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
}
