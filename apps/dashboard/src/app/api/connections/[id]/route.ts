import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await controlPlaneFetch(`/api/connections/${id}`, { method: "DELETE" });
  return new NextResponse(r.status === 204 ? null : await r.text(), {
    status: r.status,
  });
}
