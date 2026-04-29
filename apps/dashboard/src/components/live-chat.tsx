"use client";

import { useEffect, useState } from "react";

import { ChatThread, type ChatTurn } from "./chat-thread";

export function LiveChat({ agentId, initial }: { agentId: string; initial: ChatTurn[] }) {
  const [turns, setTurns] = useState<ChatTurn[]>(initial);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Keep state in sync if SSR-passed transcript changes (after a reload)
  useEffect(() => {
    setTurns(initial);
  }, [initial]);

  async function send(message: string) {
    if (!message.trim() || busy) return;

    const userTurn: ChatTurn = {
      role: "user",
      text: message,
      ts: new Date().toISOString(),
    };
    const pendingAgentTurn: ChatTurn = {
      role: "agent",
      text: "",
      ts: new Date().toISOString(),
      pending: true,
    };
    setTurns((t) => [...t, userTurn, pendingAgentTurn]);
    setDraft("");
    setBusy(true);
    setErr(null);

    try {
      const res = await fetch(`/api/agents/${agentId}/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message }),
      });

      if (!res.ok || !res.body) {
        const errText = await res.text();
        setErr(`Chat failed: ${errText.slice(0, 200)}`);
        setTurns((t) => t.filter((x) => !x.pending));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events: "data: {...}\n\n"
        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const event = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const dataLine = event.split("\n").find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          const json = dataLine.slice(5).trim();
          if (!json) continue;
          try {
            const parsed = JSON.parse(json);
            if (parsed.delta) {
              acc += parsed.delta;
              setTurns((t) => {
                const copy = [...t];
                const last = copy[copy.length - 1];
                if (last && last.pending) {
                  copy[copy.length - 1] = { ...last, text: acc };
                }
                return copy;
              });
            } else if (parsed.error) {
              setErr(parsed.error);
            } else if (parsed.done) {
              setTurns((t) => {
                const copy = [...t];
                const last = copy[copy.length - 1];
                if (last && last.pending) {
                  copy[copy.length - 1] = parsed.turn ?? { ...last, pending: false, text: acc };
                }
                return copy;
              });
            }
          } catch {
            // partial frame; wait for more bytes
          }
        }
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setTurns((t) => t.filter((x) => !x.pending));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-220px)]">
      <div className="flex-1 overflow-y-auto py-4 px-1">
        {turns.length === 0 ? (
          <div className="text-sm text-muted-foreground text-center py-8">
            No conversation yet. Type below to start.
          </div>
        ) : (
          <ChatThread turns={turns} userLabel="You" />
        )}
      </div>
      {err && <div className="px-1 pb-2 text-sm text-destructive">{err}</div>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
        className="border-t pt-3 px-1 pb-2 flex gap-2"
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask anything — 'run an investigation now', 'change threshold to 1%', 'what did you find?'"
          disabled={busy}
          className="flex-1 rounded-md border border-input px-4 py-2 text-sm disabled:opacity-50"
          autoFocus
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
