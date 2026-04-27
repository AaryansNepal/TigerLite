"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Question = { slot: string; question: string; options: string[] };

export default function NewAgentPage() {
  const router = useRouter();
  const [objective, setObjective] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [questions, setQuestions] = useState<Question[]>([]);
  const [thread, setThread] = useState<{ role: "user" | "agent"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(currentAnswers: Record<string, string>) {
    setBusy(true);
    setErr(null);
    const res = await fetch("/api/agents", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ objective, answers: currentAnswers }),
    });
    setBusy(false);

    if (!res.ok) {
      setErr(await res.text());
      return;
    }
    const data = await res.json();
    if (data.clarifying_questions) {
      setQuestions(data.clarifying_questions as Question[]);
      const ask = (data.clarifying_questions as Question[])[0];
      if (ask) setThread((t) => [...t, { role: "agent", text: ask.question }]);
      return;
    }
    if (data.id) router.push(`/agents/${data.id}` as any);
  }

  function onObjectiveSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!objective.trim()) return;
    setThread([{ role: "user", text: objective }]);
    submit({});
  }

  function onAnswerChosen(slot: string, value: string) {
    const next = { ...answers, [slot]: value };
    setAnswers(next);
    setThread((t) => [...t, { role: "user", text: value }]);
    setQuestions([]);
    submit(next);
  }

  if (thread.length === 0) {
    return (
      <div className="p-12 max-w-2xl mx-auto space-y-6">
        <div className="text-center space-y-2">
          <div className="text-3xl">🤖</div>
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
            className="flex-1 rounded-md border border-input px-3 py-2 text-sm"
            autoFocus
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"
          >
            {busy ? "…" : "→"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-2xl mx-auto space-y-4">
      {thread.map((m, i) => (
        <div
          key={i}
          className={
            m.role === "user"
              ? "rounded-lg bg-secondary px-3 py-2 text-sm self-end max-w-[80%] ml-auto"
              : "rounded-lg bg-card border px-3 py-2 text-sm max-w-[80%]"
          }
        >
          {m.text}
        </div>
      ))}

      {questions.length > 0 && (
        <div className="space-y-2 max-w-[80%]">
          <div className="flex flex-wrap gap-2">
            {questions[0].options.map((opt) => (
              <button
                key={opt}
                onClick={() => onAnswerChosen(questions[0].slot, opt)}
                className="rounded-full border px-3 py-1 text-sm hover:bg-accent"
              >
                {opt}
              </button>
            ))}
          </div>
          <input
            type="text"
            placeholder="Or type a free-form answer and press Enter"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const value = (e.target as HTMLInputElement).value;
                if (value.trim()) onAnswerChosen(questions[0].slot, value);
              }
            }}
            className="w-full rounded-md border border-input px-3 py-2 text-sm"
          />
        </div>
      )}

      {busy && <div className="text-sm text-muted-foreground">Compiling…</div>}
      {err && <div className="text-sm text-destructive">{err}</div>}
    </div>
  );
}
