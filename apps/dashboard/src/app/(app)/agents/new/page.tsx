"use client";

import { useEffect, useRef, useState } from "react";

import { ChatThread, type ChatTurn } from "@/components/chat-thread";

type Question = { slot: string; question: string; options: (string | number)[] };

export default function NewAgentPage() {
  const [objective, setObjective] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pendingQuestion, setPendingQuestion] = useState<Question | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus the input when chat opens
  useEffect(() => {
    if (turns.length > 0) inputRef.current?.focus();
  }, [turns.length]);

  async function callCompiler(userText: string, currentAnswers: Record<string, string>) {
    setBusy(true);
    setErr(null);

    // Optimistic user turn
    const userTurn: ChatTurn = {
      role: "user",
      text: userText,
      ts: new Date().toISOString(),
    };
    setTurns((t) => [...t, userTurn]);

    // Pending agent turn (typing indicator)
    setTurns((t) => [...t, { role: "agent", text: "", pending: true, ts: new Date().toISOString() }]);

    const res = await fetch("/api/agents", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        objective,
        answers: currentAnswers,
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      setErr(`Compiler failed: ${errText.slice(0, 200)}`);
      // Remove the pending turn
      setTurns((t) => t.filter((x) => !x.pending));
      setBusy(false);
      return;
    }

    const data = await res.json();

    // Replace the pending turn with the real reply
    if (data.clarifying_questions) {
      const q = (data.clarifying_questions as Question[])[0];
      const agentTurn: ChatTurn = {
        role: "agent",
        text: q.question,
        options: q.options,
        ts: new Date().toISOString(),
      };
      setTurns((t) => {
        const filtered = t.filter((x) => !x.pending);
        return [...filtered, agentTurn];
      });
      setPendingQuestion(q);
    } else if (data.id) {
      // Final agent created. Build a confirmation turn with a card.
      const agentTurn: ChatTurn = {
        role: "agent",
        text: confirmationText(data),
        ts: new Date().toISOString(),
        card: {
          agent_id: data.id,
          name: data.name,
          description: data.description,
          schedule_cron: data.schedule_cron,
          manual: true,
          slack_channel: data.slack_channel,
        },
      };
      setTurns((t) => {
        const filtered = t.filter((x) => !x.pending);
        return [...filtered, agentTurn];
      });
      setPendingQuestion(null);

      // Persist transcript on the agent now that we have an id
      const finalTranscript = [
        ...turns.filter((x) => !x.pending),
        userTurn,
        agentTurn,
      ];
      // Fire-and-forget — we already got the agent record back
      void fetch(`/api/agents/${data.id}/transcript`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ transcript: finalTranscript }),
      });
    }

    setBusy(false);
  }

  async function onObjectiveSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!objective.trim()) return;
    await callCompiler(objective, {});
  }

  async function onAnswerSubmit(value: string) {
    if (!value.trim() || !pendingQuestion) return;
    setDraft("");
    const next = { ...answers, [pendingQuestion.slot]: String(value) };
    setAnswers(next);
    await callCompiler(value, next);
  }

  // Initial state: centered prompt
  if (turns.length === 0) {
    return (
      <div className="p-12 max-w-2xl mx-auto space-y-6">
        <div className="text-center space-y-2">
          <div className="text-4xl">🐅</div>
          <h1 className="text-2xl font-semibold">New Agent</h1>
          <p className="text-sm text-muted-foreground">
            Define what matters to you in plain language
          </p>
        </div>
        <form onSubmit={onObjectiveSubmit} className="flex gap-2">
          <input
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Checkout flow should always be fast"
            className="flex-1 rounded-md border border-input px-4 py-3 text-sm"
            autoFocus
          />
          <button
            type="submit"
            disabled={busy || !objective.trim()}
            className="rounded-md bg-primary px-4 py-3 text-sm text-primary-foreground disabled:opacity-50"
          >
            {busy ? "…" : "→"}
          </button>
        </form>
      </div>
    );
  }

  // Chat layout
  return (
    <div className="flex flex-col h-[calc(100vh-180px)] max-w-3xl mx-auto">
      <div className="flex-1 overflow-y-auto py-6 px-2">
        <ChatThread turns={turns} userLabel="You" onOptionPick={onAnswerSubmit} />
      </div>
      {err && (
        <div className="px-2 pb-2 text-sm text-destructive">{err}</div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) onAnswerSubmit(draft);
        }}
        className="border-t pt-3 px-2 pb-4 flex gap-2"
      >
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={pendingQuestion ? "Type your answer or pick a chip above…" : "Type a message…"}
          disabled={busy}
          className="flex-1 rounded-md border border-input px-4 py-2 text-sm disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
        >
          {busy ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}

function confirmationText(agent: any): string {
  const endpoints = agent.scope_config?.endpoints?.join(" and ") ?? "the configured scope";
  const threshold =
    agent.scope_config?.threshold_ms != null
      ? `${agent.scope_config.threshold_ms}ms (p95)`
      : agent.scope_config?.threshold_percent != null
        ? `${agent.scope_config.threshold_percent}% error rate`
        : "the configured threshold";
  const slack = agent.slack_channel ? `${agent.slack_channel} on Slack` : "the dashboard";
  return `Got it. I'll monitor ${endpoints} for ${threshold} and alert ${slack}. Starting now.`;
}
