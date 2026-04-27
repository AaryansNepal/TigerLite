import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await controlPlaneFetch(`/api/issues/${id}/handoff`);
  return new NextResponse(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
}
