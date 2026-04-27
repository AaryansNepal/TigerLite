import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function GET(req: NextRequest) {
  const search = req.nextUrl.search;
  const r = await controlPlaneFetch(`/api/sessions${search}`);
  return new NextResponse(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
}
