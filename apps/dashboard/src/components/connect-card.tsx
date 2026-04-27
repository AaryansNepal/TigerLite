import type { LucideIcon } from "lucide-react";
import Link from "next/link";

type Status = "pending" | "connected" | "failed" | "revoked";

export function ConnectCard({
  icon: Icon,
  name,
  status,
  description,
  actionHref,
  actionLabel,
}: {
  icon: LucideIcon;
  name: string;
  status: Status;
  description: string;
  actionHref: string;
  actionLabel: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <div className="flex items-center gap-3">
        <div className="size-9 rounded-md bg-muted grid place-items-center">
          <Icon size={18} />
        </div>
        <div>
          <div className="font-medium leading-tight">{name}</div>
          <StatusPill status={status} />
        </div>
      </div>
      <p className="text-sm text-muted-foreground line-clamp-2">{description}</p>
      <Link
        href={actionHref as any}
        className="inline-flex items-center text-sm rounded-md border px-3 py-1.5 hover:bg-accent"
      >
        {actionLabel}
      </Link>
    </div>
  );
}

function StatusPill({ status }: { status: Status }) {
  const map: Record<Status, string> = {
    pending: "bg-muted text-muted-foreground",
    connected: "bg-emerald-100 text-emerald-800",
    failed: "bg-rose-100 text-rose-800",
    revoked: "bg-muted text-muted-foreground",
  };
  const label: Record<Status, string> = {
    pending: "Not connected",
    connected: "Connected",
    failed: "Error",
    revoked: "Revoked",
  };
  return (
    <span className={`inline-block text-[10px] uppercase tracking-wide font-semibold rounded px-1.5 py-0.5 ${map[status]}`}>
      {label[status]}
    </span>
  );
}
