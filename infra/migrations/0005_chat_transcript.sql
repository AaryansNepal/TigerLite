-- Persist the agent creation conversation + ongoing chat turns on the agent
-- row. The /agents/new flow saves each turn here as it happens; the Chat
-- tab replays them.

BEGIN;

ALTER TABLE agents
  ADD COLUMN IF NOT EXISTS chat_transcript JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Each entry shape:
--   { "role": "user" | "agent",
--     "text": "...",
--     "ts":   "2026-04-28T22:45:00Z",
--     "options": ["/checkout", ...]?,    // suggestion chips
--     "card":    { type, title, description, triggers, channel, ... }?  // final agent card
--   }

COMMIT;
