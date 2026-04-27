"use client";

import { useState } from "react";

export function ClaudeCodeHandoff({ issueId }: { issueId: string }) {
  const [busy, setBusy] = useState(false);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setErr(null);
    const r = await fetch(`/api/issues/${issueId}/handoff`);
    setBusy(false);
    if (!r.ok) {
      setErr(await r.text());
      return;
    }
    const data = await r.json();
    setPrompt(data.prompt);
  }

  async function copy() {
    if (!prompt) return;
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="rounded-md border p-4 space-y-3">
      <h2 className="text-sm font-medium">Hand off to Claude Code</h2>
      <p className="text-xs text-muted-foreground">
        Generates a prompt you can paste into Claude Code to fix this issue,
        bundling root cause + affected files + verification plan.
      </p>
      {!prompt && (
        <button
          onClick={load}
          disabled={busy}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Preparing…" : "Generate fix prompt"}
        </button>
      )}
      {prompt && (
        <div className="space-y-2">
          <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap font-mono max-h-96 overflow-auto">
            {prompt}
          </pre>
          <button
            onClick={copy}
            className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
          >
            {copied ? "Copied!" : "Copy as Claude Code prompt"}
          </button>
        </div>
      )}
      {err && <p className="text-xs text-destructive">{err}</p>}
    </section>
  );
}
