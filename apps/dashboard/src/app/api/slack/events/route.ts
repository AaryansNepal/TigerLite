import { NextRequest, NextResponse } from "next/server";

const BASE = process.env.CONTROL_PLANE_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const headers = new Headers();
  for (const k of [
    "x-slack-signature",
    "x-slack-request-timestamp",
    "content-type",
  ]) {
    const v = req.headers.get(k);
    if (v) headers.set(k, v);
  }
  const r = await fetch(`${BASE}/api/slack/events`, { method: "POST", body, headers });
  return new NextResponse(await r.text(), { status: r.status });
}
