---
id: F002
query_id: Q007
type: read
intent: "Read the ai_bots DDL to get the authoritative column list and detect drift against BotModel."
executed_at: 2026-11-12T20:40:22Z
duration_ms: 400
parent_id: null
depth: 1
merged_from: [FC-002]
---

# F002 — creation.sql: destructive setup DDL + appended idempotent ALTERs, already drifted

## Summary

`creation.sql` (250 lines) is an *initial-setup* script that starts with `DROP TABLE IF EXISTS navigator.ai_bots CASCADE`
and explicitly warns not to run it in production; it then CREATEs 44 columns, indexes, a UNIQUE(name) constraint,
an `updated_at` trigger, seed INSERTs, and finally a tail of hand-appended `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
blocks per feature (FEAT-133, FEAT-593, "columns added after the original release"). Its header claims it tracks
BotModel "field-for-field (44 columns)", but BotModel declares 49 fields: the five FEAT-752 suggestion columns
(`enable_suggestions`, `suggest_followups`, `suggestion_timeout_s`, `max_suggestions`, `suggestion_model`) are
absent from creation.sql (`grep -c enable_suggestions` = 0). Operators are pointed to `sdd/migrations/*.sql` for upgrades.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 1-9
  excerpt: |
    -- WARNING: Initial setup DDL only. DO NOT run against production.
    -- For migrations, use the ALTER TABLE ADD COLUMN IF NOT EXISTS statements at the bottom,
    -- or run sdd/migrations/ai-bots-homologate-botmodel.sql (idempotent, covers every column).
    -- The CREATE TABLE below tracks parrot.models.bots.BotModel field-for-field (44 columns).
    --   model_name/temperature/max_tokens/top_k/top_p -> FEAT-fold-legacy-llm-columns.sql
    --   embedding_model                               -> FEAT-fold-embedding-model-into-vector-store-config.sql
    DROP TABLE IF EXISTS navigator.ai_bots CASCADE;

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 12-81
  symbol: `navigator.ai_bots`
  excerpt: |
    chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR NOT NULL, ... llm VARCHAR DEFAULT 'google', model_config JSONB DEFAULT '{}'::JSONB,
    tools JSONB, toolkit_config JSONB, mcp_servers JSONB, operation_mode VARCHAR CHECK (...),
    use_kb, kb, custom_kbs, use_vector, vector_store_config, reranker_config, parent_searcher_config,
    memory_type CHECK IN ('memory','file','redis'), memory_config, max_context_turns, ...
    bot_class VARCHAR, permissions JSONB, language VARCHAR(10), disclaimer, created_at, created_by, updated_at

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 84-129
  excerpt: |
    CREATE INDEX IF NOT EXISTS idx_ai_bots_name ON navigator.ai_bots(name);  (+ GIN on tools/permissions/model_config)
    ALTER TABLE navigator.ai_bots ADD CONSTRAINT unq_navigator_ai_bots_name UNIQUE (name);
    CREATE OR REPLACE FUNCTION update_ai_bots_updated_at() ... CREATE TRIGGER trigger_ai_bots_updated_at

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 209-250
  excerpt: |
    -- FEAT-133: Add reranker_config and parent_searcher_config columns (idempotent)
    -- FEAT-593: Agent Studio tool configuration (idempotent)
    -- Columns added after the original release (idempotent — see
    -- sdd/migrations/ai-bots-homologate-botmodel.sql for the runnable migration)
    ALTER TABLE navigator.ai_bots
        ADD COLUMN IF NOT EXISTS prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB;

## Notes

The ALTERs at lines 98-99 (`ADD CONSTRAINT unq_...`) and trigger creation (126) are NOT idempotent — a re-run on an
existing table errors, so creation.sql cannot double as a migration. A baseline migration would need to be
rewritten guarded (`DO $$ ... IF NOT EXISTS`). Seed INSERTs (line 132) are data, not schema.
[cross-lane: type=git_log, intent=history of creation.sql and models/bots.py column additions to map each feature to a would-be migration file]
