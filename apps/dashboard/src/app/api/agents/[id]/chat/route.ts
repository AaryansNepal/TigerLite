import { NextRequest, NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane";

// Streams Server-Sent Events from the control plane chat endpoint
// directly to the browser. Edge-compatible streaming.
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.text();
  const r = await controlPlaneFetch(`/api/agents/chat/${id}`, {
    method: "POST",
    body,
  });

  if (!r.ok || !r.body) {
    return new NextResponse(await r.text(), { status: r.status });
  }

  return new NextResponse(r.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      "x-accel-buffering": "no",
    },
  });
}
