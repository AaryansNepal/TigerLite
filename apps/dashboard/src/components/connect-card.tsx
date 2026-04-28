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
  secondary,
}: {
  icon: LucideIcon;
  name: string;
  status: Status;
  description: string;
  actionHref: string;
  actionLabel: string;
  secondary?: { href?: string; label: string; onClick?: string };
}) {
  const isExternal = /^https?:\/\//i.test(actionHref);
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
      <div className="flex items-center gap-2 flex-wrap">
        {isExternal ? (
          <a
            href={actionHref}
            className="inline-flex items-center text-sm rounded-md border px-3 py-1.5 hover:bg-accent"
          >
            {actionLabel}
          </a>
        ) : (
          <Link
            href={actionHref as any}
            className="inline-flex items-center text-sm rounded-md border px-3 py-1.5 hover:bg-accent"
          >
            {actionLabel}
          </Link>
        )}
        {secondary?.href && (
          <Link
            href={secondary.href as any}
            className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            {secondary.label}
          </Link>
        )}
      </div>
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
