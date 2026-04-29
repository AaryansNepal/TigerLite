"use client";

import Link from "next/link";
import { Bot } from "lucide-react";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

export type ChatTurn = {
  role: "user" | "agent";
  text: string;
  ts?: string;
  options?: (string | number)[];
  card?: AgentCard;
  pending?: boolean;
};

export type AgentCard = {
  agent_id: string;
  name: string;
  description: string;
  schedule_cron?: string | null;
  manual?: boolean;
  slack_channel?: string | null;
};

export function ChatThread({
  turns,
  userLabel = "You",
  onOptionPick,
}: {
  turns: ChatTurn[];
  userLabel?: string;
  onOptionPick?: (option: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the newest turn whenever the thread grows
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, turns[turns.length - 1]?.text]);

  return (
    <div className="space-y-5">
      {turns.map((t, i) =>
        t.role === "user" ? (
          <UserTurn key={i} turn={t} label={userLabel} />
        ) : (
          <AgentTurn key={i} turn={t} onOptionPick={onOptionPick} />
        )
      )}
      <div ref={scrollRef} />
    </div>
  );
}

function UserTurn({ turn, label }: { turn: ChatTurn; label: string }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="rounded-2xl rounded-tr-sm bg-primary text-primary-foreground px-4 py-2 text-sm max-w-[75%] whitespace-pre-wrap">
        {turn.text}
      </div>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="size-4 rounded-full bg-primary/20 grid place-items-center text-[10px] font-medium text-primary">
          {label[0]?.toUpperCase() ?? "U"}
        </span>
        <span>{label} · {formatTime(turn.ts)}</span>
      </div>
    </div>
  );
}

function AgentTurn({
  turn,
  onOptionPick,
}: {
  turn: ChatTurn;
  onOptionPick?: (option: string) => void;
}) {
  return (
    <div className="flex gap-3 max-w-[85%]">
      <div className="shrink-0 size-7 rounded-full bg-primary/10 grid place-items-center text-primary mt-0.5">
        <Bot size={14} />
      </div>
      <div className="flex-1 space-y-1">
        <div className="text-sm whitespace-pre-wrap text-foreground">
          {turn.text}
          {turn.pending && (
            <span className="inline-block w-1 h-4 bg-foreground/60 ml-0.5 animate-pulse align-middle" />
          )}
        </div>
        {turn.options && turn.options.length > 0 && onOptionPick && (
          <div className="flex flex-wrap gap-2 pt-1">
            {turn.options.map((opt) => (
              <button
                key={String(opt)}
                onClick={() => onOptionPick(String(opt))}
                className="rounded-full border px-3 py-1 text-sm hover:bg-accent transition"
              >
                {String(opt)}
              </button>
            ))}
          </div>
        )}
        {turn.card && <AgentCardBlock card={turn.card} />}
        <div className="text-xs text-muted-foreground pt-0.5">
          TigerLite · {formatTime(turn.ts)}
        </div>
      </div>
    </div>
  );
}

function AgentCardBlock({ card }: { card: AgentCard }) {
  return (
    <div className="rounded-lg border-2 border-emerald-500/40 bg-emerald-50/50 dark:bg-emerald-950/20 p-4 my-2 max-w-md space-y-3">
      <div className="flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-300">
        <span className="size-5 rounded-full bg-emerald-500 grid place-items-center text-white text-xs">
          ✓
        </span>
        New agent — {card.name}
      </div>
      {card.description && (
        <p className="text-sm text-muted-foreground">{card.description}</p>
      )}
      <div className="space-y-2 text-sm">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
            Triggers
          </div>
          {card.schedule_cron && <div>🕐 Scheduled: {humanCron(card.schedule_cron)}</div>}
          {card.manual !== false && <div>✋ Manual</div>}
        </div>
        {card.slack_channel && (
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
              Notifications
            </div>
            <div>💬 {card.slack_channel} channel on Slack</div>
          </div>
        )}
      </div>
      <Link
        href={`/agents/${card.agent_id}` as any}
        className="inline-flex items-center rounded-md bg-foreground text-background px-3 py-1.5 text-sm font-medium"
      >
        View Agent
      </Link>
    </div>
  );
}

function humanCron(cron: string): string {
  if (cron === "0 * * * *") return "every hour";
  if (cron === "*/5 * * * *") return "every 5 minutes";
  if (cron === "0 0 * * *") return "daily";
  return cron;
}

function formatTime(ts?: string): string {
  if (!ts) return "now";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "now";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
