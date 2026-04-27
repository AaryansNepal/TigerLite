# Demo

What this demo proves, what the audience sees, what success looks like.

## The thesis

The Firetiger thesis in miniature: **observability can stop being a thing humans do with dashboards and become a thing agents do on your behalf.**

The audience watches a sequence of events that today would take a human SRE 20-30 minutes — log in, search logs, correlate with recent deploys, ask in Slack, form a theory, write the message — collapse into ~60 seconds of autonomous work. The agent didn't need to be told what "broken" means. It didn't need a threshold tuned by an engineer. It watched the system, noticed change, reasoned about it, and explained itself.

If the demo lands, the takeaway is: **"oh — the loop between 'something broke' and 'someone understands what broke' can actually be closed by an agent, end-to-end, with nothing more than a one-sentence agent definition. That changes what observability is."**

## The narrative arc

### Setup (3 minutes, on stage)

1. Open the dashboard at the live URL. Sign up — email, password, done. New tenant created automatically.
2. Land on home with three Connect cards.
3. Connect Telemetry: copy the OTLP endpoint and token. Switch to a terminal showing the running Astronomy Shop fork. Show the env vars in `docker-compose.yml`. The card flips to "Connected — receiving data from `frontend`, `cart`, `checkout`, `payment`, ..." (Service names auto-detected from incoming traces.)
4. Connect GitHub: GitHub App install flow. Pick the Astronomy Shop fork.
5. Connect Slack: OAuth, pick channel.
6. Click "New Agent." Type: *"checkout flow should always be fast."*
7. Agent compiler asks 1-2 clarifying questions in chat ("which endpoints should I watch?", "what response time is acceptable?"). Answer them. Agent commits with a green confirmation card.

At this point: agent is active and watching.

### The injection (30 seconds, on stage)

8. Open the Astronomy Shop's flagd UI in another browser tab.
9. Toggle `paymentServiceFailure` to `on`.
10. Switch back to the TigerLite dashboard. Don't click anything. Wait.

### The payoff (60-90 seconds, automated)

11. The dashboard's session list updates: a new session appears under the agent, status "Running."
12. Optional: click into the session to show the timeline live-updating as the agent works. Audience sees the agent's reasoning, the queries it runs, the GitHub files it reads.
13. Switch to Slack. A structured message arrives: "Payment service is failing about 30% of checkout attempts. Started at [timestamp]. The most recent change was commit `abc123` titled 'switch to new currency provider' that landed at [timestamp] — it modified `src/payment/transaction.go`. This looks like the cause."
14. Click into the issue from the agent detail page. Show the full evidence — the offending file, the affected request count, the suggested fix approach.

### The follow-through (optional, ~5 minutes if asked)

15. Disable the failing flag. Back to the agent's session list. A new "verification" session appears.
16. After ~5 minutes (or fast-forward in the demo if needed), the verification session resolves: "Metrics returned to baseline. Marking issue resolved." Posted to the same Slack thread.

## What success looks like

A 15-minute demo with these checkpoints:

- ✅ User signs up and reaches "ready to create agent" state in under 3 minutes (live, on stage, no hand-waving).
- ✅ Agent creation is conversational — back-and-forth Q&A, not a 12-field form.
- ✅ Failure injection to Slack message: under 90 seconds.
- ✅ Slack message names a specific commit SHA. Not "a recent change" — the specific one.
- ✅ Audience can click into the dashboard and see the agent's reasoning trail. Every step. Every query. Every file the agent read.
- ✅ Optional: verification loop closes when the fix is applied.

## What success does not require

- Multiple agents running simultaneously. One is fine.
- Production-grade UI polish.
- A pretty dashboard for telemetry exploration. The dashboard's job is to render agent sessions, not be a Datadog replacement.
- High volume / scale. A single Astronomy Shop instance generates plenty of telemetry.
- Multiple users. The demo tenant is fine.

## The thing that almost always breaks demos

LLM latency variability. Gemini calls can take 5 seconds or 30 seconds depending on load. **Mitigations:**

- Pre-warm the agent with a dry-run before the demo (run an investigation that produces a finding, then reset).
- Have a backup recording of the demo flow to fall back on if live LLM calls take too long.
- During the live demo, if the agent stalls, narrate the architecture while waiting — "this is the snapshot loop, each step persists to S3, so even if Gemini hangs, we never lose state."

## The other failure mode

The agent posts a wrong root cause. Specifically: it identifies the wrong commit, or describes a fix that wouldn't work.

**Mitigations:**

- Make sure the Astronomy Shop fork has a *very recent* commit that's plausibly related to the failure being injected. The agent's correlation will land on it.
- Constrain the agent's `plan` field to encourage caveats: "If the evidence is ambiguous, say so. Don't speculate."
- If during the demo the agent posts something hilariously wrong, use it as a teaching moment — "this is why human-in-the-loop matters" — rather than panicking.

## Demo tier list (what to drop if time is tight)

If you have to cut features to ship, cut in this order:

1. **Last to cut**: the Slack message arriving with a commit SHA. This is the moment that sells the entire pitch.
2. Multi-agent (one agent is enough for the demo).
3. Verification loop (Phase 3) — nice to have, not required.
4. GitHub PR creation (Phase 4) — definitely cut.
5. Real Slack threading for follow-up replies — can be visual-only ("imagine you replied here").
6. Self-instrumentation of TigerLite ("dogfooding") — dev-time only.

If the demo can hit point 1 reliably, the rest is upside.
