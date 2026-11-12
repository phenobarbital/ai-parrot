---
id: FG-002
query_id: Q018
type: git_log
intent: "Schema drift of ai_bots in parrot — commits that added/changed columns (what migrations would have needed)."
executed_at: 2026-11-12T20:39:39Z
duration_ms: 2600
parent_id: null
depth: 0
---

# FG-002 — navigator.ai_bots drifted through ≥8 column changes in 7 months, tracked only by appended ALTERs and a hand-synced CREATE TABLE

## Summary

Pickaxe `-S ai_bots` (365 days, packages/) returns 27 commits. The DDL lives in `creation.sql` (moved from `packages/ai-parrot/src/parrot/handlers/creation.sql` to `packages/ai-parrot-server/src/parrot/handlers/creation.sql`), which is a "initial setup DDL only, DO NOT run against production" file whose bottom accumulates idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` blocks. Column timeline: reranker_config + parent_searcher_config JSONB (FEAT-133, 2026-04-29, ALTER+GIN indexes); prompt_config (2026-04-30); embedding_model folded into vector store config (2026-05-06); legacy LLM columns model_name/temperature/max_tokens/top_k/top_p folded into model_config (2026-07-14); toolkit_config + mcp_servers JSONB (FEAT-593, 2026-09-23); language made nullable (FEAT-638, 2026-10-08); CREATE TABLE re-homologated to BotModel "field-for-field (44 columns)" adding use_kb/kb/custom_kbs/bot_class (2026-10-21); suggestion columns (FEAT-752, 2026-10-28). The BotModel (asyncdb/datamodel, Meta.strict=True) moved to `packages/ai-parrot/src/parrot/models/bots.py` (2026-10-07) and had to grow a kwargs-fold decorator (TASK-4577) because "the fold migrations are still pending on staging/prod" — direct evidence that environments sit at unknown schema versions.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 1-11 (as of bb209cd2ff)
  symbol: null
  excerpt: |
    -- WARNING: Initial setup DDL only. DO NOT run against production.
    -- For migrations, use the ALTER TABLE ADD COLUMN IF NOT EXISTS statements at the bottom,
    -- or run sdd/migrations/ai-bots-homologate-botmodel.sql (idempotent, covers every column).
    -- The CREATE TABLE below tracks parrot.models.bots.BotModel field-for-field (44 columns).
    -- Columns dropped from the model live only in their fold migrations:
    --   model_name/temperature/max_tokens/top_k/top_p -> FEAT-fold-legacy-llm-columns.sql
    --   embedding_model                               -> FEAT-fold-embedding-model-into-vector-store-config.sql

- path: `packages/ai-parrot/src/parrot/handlers/creation.sql`
  lines: 192-203 (83e57987c9, 32d17205db)
  symbol: null
  excerpt: |
    -- FEAT-133: Add reranker_config and parent_searcher_config columns (idempotent)
    ALTER TABLE navigator.ai_bots
        ADD COLUMN IF NOT EXISTS reranker_config        JSONB DEFAULT '{}'::JSONB;
    CREATE INDEX IF NOT EXISTS idx_ai_bots_reranker_config
        ON navigator.ai_bots USING GIN (reranker_config);

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 203-215 (2a2bc4fe34)
  symbol: null
  excerpt: |
    -- FEAT-593: Agent Studio tool configuration (idempotent)
    ALTER TABLE navigator.ai_bots
        ADD COLUMN IF NOT EXISTS toolkit_config JSONB DEFAULT '{}'::JSONB;
    ALTER TABLE navigator.ai_bots
        ADD COLUMN IF NOT EXISTS mcp_servers    JSONB DEFAULT '[]'::JSONB;

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: n/a (4f05450930, 2026-10-22)
  symbol: `BotModel`
  excerpt: |
    A row hydrated from an ai_bots table that still carries the pre-fold columns
    (model_name/temperature/max_tokens/top_k/top_p/embedding_model) raised
    BotModel.__init__() got an unexpected keyword argument 'model_name' under Meta.strict=True.
    ... the fold migrations are still pending on staging/prod.
    asyncdb's pg driver puts every declared column into the INSERT ... RETURNING clause

- path: `packages/ai-parrot-server/src/parrot/handlers/models/bots.py`
  lines: n/a (9c022af2b4 2026-07-14 added / fd6748e669 2026-07-17 removed)
  symbol: `BotModel`
  excerpt: |
    +/- model_name, temperature, max_tokens, top_k, top_p, embedding_model : Optional[...] = Field(required=False, default=None)

## Notes

- Commits touching ai_bots by area: creation.sql (4f..: 83e57987c9, 32d17205db, 2a2bc4fe34, bb209cd2ff, 4953611047), BotModel (b16852f227, a8ac9ef85b, 9c022af2b4, fd6748e669, f855ef52ba, 4f05450930), consumers (manager.py d54dac95fd/84c876671d/a423a27937, studio handlers 4c2988f29f/5645781204/d2549877c0, registry fc304d5267, status.py a6a04cef70).
- The failure mode the feature must prevent is visible: model change shipped (fd6748e669) before the matching DDL was applied everywhere → runtime TypeError → compat shim (TASK-4577). A migration ledger + startup "pending migrations" warning (navauth has one, FG-001) would have surfaced this.
- See FG-003 for the parallel ad-hoc `sdd/migrations/` directory.
