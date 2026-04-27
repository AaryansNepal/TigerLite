"use client";

import { Activity } from "lucide-react";
import { useEffect, useState } from "react";

import { ConnectCard } from "./connect-card";
import { createClient } from "@/lib/supabase/client";

type Connection = {
  id: string;
  kind: "otel" | "github" | "slack";
  status: "pending" | "connected" | "failed" | "revoked";
  display_name?: string | null;
  detected_services?: string[] | null;
  last_event_at?: string | null;
};

export function TelemetryConnectCard({ connection }: { connection: Connection | null }) {
  const supabase = createClient();
  const [conn, setConn] = useState<Connection | null>(connection);
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Realtime: react when the connection row updates (status flips, last_event_at fills in).
  // RLS scopes events to this user's tenant, so we accept any otel-kind row
  // we receive — even if `prev` was null (which happens between signup and
  // first token issuance).
  useEffect(() => {
    const channel = supabase
      .channel("telemetry-connection")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "connections" },
        (payload) => {
          const next = (payload.new ?? payload.old) as Connection | undefined;
          if (!next || next.kind !== "otel") return;
          setConn(next);
        }
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  // Belt-and-braces: poll for a connection while the modal is open and we
  // haven't seen one yet. Realtime is the primary path; this only fires
  // until the first row appears, then stops. Cheap and robust against
  // missed events on slow networks.
  useEffect(() => {
    if (conn) return;
    const id = setInterval(async () => {
      const r = await fetch("/api/connections", { cache: "no-store" });
      if (!r.ok) return;
      const list = (await r.json()) as Connection[];
      const otel = list.find((c) => c.kind === "otel");
      if (otel) setConn(otel);
    }, 2000);
    return () => clearInterval(id);
  }, [conn]);

  const description = conn?.detected_services?.length
    ? `Receiving data from ${conn.detected_services.slice(0, 4).join(", ")}${
        conn.detected_services.length > 4 ? "…" : ""
      }`
    : "Point your OpenTelemetry SDK at our OTLP endpoint.";

  async function issueToken() {
    setBusy(true);
    const res = await fetch("/api/connections/otel/issue", { method: "POST" });
    setBusy(false);
    if (!res.ok) return;
    const data = (await res.json()) as { token: string; endpoint: string };
    setToken(data.token);
    setEndpoint(data.endpoint);
  }

  return (
    <>
      <div onClick={() => setOpen(true)} className="cursor-pointer">
        <ConnectCard
          icon={Activity}
          name="OpenTelemetry"
          status={conn?.status ?? "pending"}
          description={description}
          actionHref="#"
          actionLabel={conn?.status === "connected" ? "Manage" : "Connect"}
        />
      </div>

      {open && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40">
          <div className="rounded-lg bg-card p-6 w-full max-w-lg space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Connect your telemetry</h3>
              <button onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground">
                ✕
              </button>
            </div>
            <p className="text-sm text-muted-foreground">
              Point your OpenTelemetry-instrumented application at this endpoint. The card flips to
              Connected once we receive your first event.
            </p>
            {!token && (
              <button
                onClick={issueToken}
                disabled={busy}
                className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90"
              >
                {busy ? "Generating…" : "Generate ingest token"}
              </button>
            )}
            {token && endpoint && (
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-muted-foreground">Endpoint</div>
                  <code className="block rounded bg-muted p-2 text-xs">{endpoint}</code>
                </div>
                <div>
                  <div className="text-muted-foreground">Header</div>
                  <code className="block rounded bg-muted p-2 text-xs break-all">
                    Authorization: Bearer {token}
                  </code>
                </div>
                <p className="text-xs text-muted-foreground">
                  This token is shown once. Save it now — we never display it again.
                </p>
              </div>
            )}
            {conn?.status === "connected" && (
              <div className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                ✓ Connected. Detected services:{" "}
                {(conn.detected_services ?? []).join(", ") || "(none yet)"}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
