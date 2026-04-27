import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await controlPlaneFetch(`/api/agents/${id}`);
  return new NextResponse(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
}

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.text();
  const r = await controlPlaneFetch(`/api/agents/${id}`, { method: "PATCH", body });
  return new NextResponse(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await controlPlaneFetch(`/api/agents/${id}`, { method: "DELETE" });
  return new NextResponse(null, { status: r.status });
}
