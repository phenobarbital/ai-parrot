---
id: F003
query_id: Q013, Q005, Q018
type: read + wiki_query + git_log
intent: "Find the datamodel bound to ai_bots and its column list (source of truth for current schema). | Locate where navigator.ai_bots is defined (DDL, datamodel, BotModel) in parrot. | Schema drift of ai_bots in parrot — commits that added/changed columns (what migrations would have needed)."
executed_at: 2026-11-12T20:41:06Z
duration_ms: 5700
parent_id: null
depth: 1
merged_from: [FC-003, FW-004, FG-002]
---

# F003 — BotModel: strict asyncdb Model, 49 fields, tolerates legacy columns in code

## Summary

`BotModel(Model)` (datamodel/asyncdb, `driver = "pg"`, `name = PARROT_BOTS_TABLE`, `schema = PARROT_SCHEMA`,
`strict = True`) declares 49 fields. Because the driver SELECTs/INSERTs every declared field by name, a column the
model declares but the table lacks breaks **every bot load** — schema drift is a hard runtime failure, not a soft one.
The model's docstring embeds yet another copy of the CREATE TABLE (incl. FEAT-752 columns), and legacy columns
dropped from the model (`model_name, temperature, max_tokens, top_k, top_p, embedding_model`) are folded in code via
`_fold_legacy_bot_columns` so both pre- and post-fold databases keep working; the comment tells operators to run
`sdd/migrations/FEAT-fold-*.sql` by hand.

`wikitoolkit query` top hits: `file:sdd/migrations/ai-bots-homologate-botmodel.sql` (1.00), FEAT-860 finding F006
(0.88), `file:sdd/migrations/botmodel-recreate-table.sql` (0.76). `BotModel` is in core
(`packages/ai-parrot/src/parrot/models/bots.py` L100-468, `Meta` L461-468): asyncdb `Model`, `schema = PARROT_SCHEMA`
(fallback "navigator"), `name = PARROT_BOTS_TABLE` (fallback "ai_bots"), `driver="pg"`, `strict=True` — asyncdb
SELECTs every declared field, so **one missing column fails every bot load** (`column "toolkit_config" does not
exist`). Lesson `mem-65f89185cb0d` (score 1.00): the table is documented in three places that must track BotModel
field-for-field (44 columns as of 2026-10-21) — the BotModel docstring DDL, `packages/ai-parrot-server/src/parrot/handlers/creation.sql`,
`sdd/migrations/botmodel-recreate-table.sql`; on 2026-10-21 all three had drifted. `creation.sql` starts with
`DROP TABLE IF EXISTS navigator.ai_bots CASCADE` (line 9) before `CREATE TABLE IF NOT EXISTS` (line 12) — it is a
destructive bootstrap, not a migration. `ai-bots-homologate-botmodel.sql` is the idempotent additive catch-up
(`ADD COLUMN IF NOT EXISTS` for avatar, timezone, prompt_config, model_config, toolkit_config, mcp_servers, use_kb,
kb, custom_kbs, reranker_config, parent_searcher_config, bot_class…) with a `Status : pending` header — applied by
hand. creation.sql + the BotModel docstring DDL are byte-frozen by
`packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py::test_load_database_bots_untouched`; deliberate
edits must be registered in `_SANCTIONED_REWRITES`.

Pickaxe `-S ai_bots` (365 days, packages/) returns 27 commits. The DDL lives in `creation.sql` (moved from `packages/ai-parrot/src/parrot/handlers/creation.sql` to `packages/ai-parrot-server/src/parrot/handlers/creation.sql`), which is a "initial setup DDL only, DO NOT run against production" file whose bottom accumulates idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` blocks. Column timeline: reranker_config + parent_searcher_config JSONB (FEAT-133, 2026-04-29, ALTER+GIN indexes); prompt_config (2026-04-30); embedding_model folded into vector store config (2026-05-06); legacy LLM columns model_name/temperature/max_tokens/top_k/top_p folded into model_config (2026-07-14); toolkit_config + mcp_servers JSONB (FEAT-593, 2026-09-23); language made nullable (FEAT-638, 2026-10-08); CREATE TABLE re-homologated to BotModel "field-for-field (44 columns)" adding use_kb/kb/custom_kbs/bot_class (2026-10-21); suggestion columns (FEAT-752, 2026-10-28). The BotModel (asyncdb/datamodel, Meta.strict=True) moved to `packages/ai-parrot/src/parrot/models/bots.py` (2026-10-07) and had to grow a kwargs-fold decorator (TASK-4577) because "the fold migrations are still pending on staging/prod" — direct evidence that environments sit at unknown schema versions.

## Citations

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 461-468
  symbol: `BotModel.Meta`
  excerpt: |
    class Meta:
        driver = "pg"
        name = PARROT_BOTS_TABLE
        schema = PARROT_SCHEMA
        strict = True
        frozen = False

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 24-40
  symbol: `_LEGACY_LLM_COLUMNS`
  excerpt: |
    # Older ``navigator.ai_bots`` tables still carry the pre-fold standalone
    # columns, and a row hydrated from such a table reaches ``BotModel`` as
    # unexpected keyword arguments, which ``Meta.strict = True`` rejects.
    # Run ``sdd/migrations/FEAT-fold-legacy-llm-columns.sql`` and
    # ``sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql``
    _LEGACY_LLM_COLUMNS = ("model_name", "temperature", "max_tokens", "top_k", "top_p")
    _LEGACY_EMBEDDING_COLUMN = "embedding_model"

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 43-44
  symbol: `_fold_legacy_bot_columns`
  excerpt: |
    def _fold_legacy_bot_columns(kwargs: dict) -> None:
        """Fold the legacy ``ai_bots`` columns found in *kwargs* into the canonical JSONB.

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 100-468
  symbol: `BotModel`
  excerpt: |
    A row hydrated from an ai_bots table that still carries the pre-fold columns
    (model_name/temperature/max_tokens/top_k/top_p/embedding_model) raised
    BotModel.__init__() got an unexpected keyword argument 'model_name' under Meta.strict=True.
    ... the fold migrations are still pending on staging/prod.
    asyncdb's pg driver puts every declared column into the INSERT ... RETURNING clause

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 156-161
  excerpt: |
    -- Follow-up suggestion chips (FEAT-752)
    enable_suggestions BOOLEAN DEFAULT FALSE,
    suggest_followups BOOLEAN DEFAULT FALSE,
    suggestion_timeout_s REAL DEFAULT 4.0,
    max_suggestions INTEGER DEFAULT 6,
    suggestion_model VARCHAR,

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 9-86
  symbol: `navigator.ai_bots DDL`
  excerpt: |
    9:  DROP TABLE IF EXISTS navigator.ai_bots CASCADE;
    12: CREATE TABLE IF NOT EXISTS navigator.ai_bots (
    84: CREATE INDEX IF NOT EXISTS idx_ai_bots_name ON navigator.ai_bots(name);

- path: `sdd/migrations/ai-bots-homologate-botmodel.sql`
  lines: 1-40
  symbol: `ai-bots-homologate-botmodel`
  excerpt: |
    -- Homologate navigator.ai_bots with parrot.models.bots.BotModel
    --   BotModel has Meta.strict = True, so asyncdb SELECTs every declared field by name.
    -- Safe   : additive, idempotent, no data loss. Safe to re-run anywhere.
    -- Status : pending
    BEGIN;
    ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS toolkit_config JSONB DEFAULT '{}'::JSONB;

- path: `sdd/migrations/botmodel-recreate-table.sql`
  lines: 1-20
  symbol: `botmodel-recreate-table`
  excerpt: |
    -- WARNING: DROP TABLE ... CASCADE destroys all existing bot rows …
    DROP TABLE IF EXISTS navigator.ai_bots CASCADE;
    CREATE TABLE navigator.ai_bots ( chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), …

- path: `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
  lines: n/a (from lesson mem-65f89185cb0d)
  symbol: `test_load_database_bots_untouched`
  excerpt: |
    byte-compares creation.sql and the BotModel docstring DDL against the origin/dev merge-base;
    a deliberate change must be registered in _SANCTIONED_REWRITES

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

- path: `packages/ai-parrot-server/src/parrot/handlers/models/bots.py`
  lines: n/a (9c022af2b4 2026-07-14 added / fd6748e669 2026-07-17 removed)
  symbol: `BotModel`
  excerpt: |
    +/- model_name, temperature, max_tokens, top_k, top_p, embedding_model : Optional[...] = Field(required=False, default=None)

## Notes

Fields (49): chatbot_id name description avatar enabled timezone role goal backstory rationale capabilities
system_prompt_template human_prompt_template pre_instructions prompt_config llm model_config tools_enabled
auto_tool_detection tool_threshold tools toolkit_config mcp_servers operation_mode use_kb kb custom_kbs use_vector
vector_store_config reranker_config parent_searcher_config context_search_limit context_score_threshold memory_type
memory_config max_context_turns use_conversation_history enable_suggestions suggest_followups suggestion_timeout_s
max_suggestions suggestion_model bot_class permissions language disclaimer created_at created_by updated_at.
Same file also defines other navigator.* models (Meta.schema="navigator" at lines 513/595/670; ChatbotUsage is bigquery).
Three copies of the ai_bots schema exist (creation.sql, BotModel docstring, sdd/migrations) — a model-vs-DB
column diff (`--check`) is a natural feature for the migration command.

Schema and table name are configurable (PARROT_SCHEMA / PARROT_BOTS_TABLE) while every SQL file hard-codes
`navigator.ai_bots` — a runner should render placeholders the way navauth renders `{schema}` (F019).
BotManager loads bots through `app["database"]` pool + `BotModel.filter(enabled=True)` (FEAT-860 F006, gated by
`ENABLE_DATABASE_BOTS`) — the natural place for a startup "pending migrations" warning.
[cross-lane: type=grep, intent=confirm BotModel.Meta field values and PARROT_SCHEMA/PARROT_BOTS_TABLE in conf.py]

- Commits touching ai_bots by area: creation.sql (4f..: 83e57987c9, 32d17205db, 2a2bc4fe34, bb209cd2ff, 4953611047), BotModel (b16852f227, a8ac9ef85b, 9c022af2b4, fd6748e669, f855ef52ba, 4f05450930), consumers (manager.py d54dac95fd/84c876671d/a423a27937, studio handlers 4c2988f29f/5645781204/d2549877c0, registry fc304d5267, status.py a6a04cef70).
- The failure mode the feature must prevent is visible: model change shipped (fd6748e669) before the matching DDL was applied everywhere → runtime TypeError → compat shim (TASK-4577). A migration ledger + startup "pending migrations" warning (navauth has one, F016) would have surfaced this.
- See F017 for the parallel ad-hoc `sdd/migrations/` directory.

[citation-check: missing] packages/ai-parrot/src/parrot/handlers/creation.sql — file absent at HEAD; it is the pre-move historical path (git citation). Current file: packages/ai-parrot-server/src/parrot/handlers/creation.sql (DROP TABLE at line 9, CREATE INDEX at line 84).
[citation-check: stale] packages/ai-parrot-server/src/parrot/handlers/models/bots.py — `BotModel` is not defined there; the module is a re-export shim (line 3 docstring 'moved to core parrot.models.bots', import at line 10). Definition: packages/ai-parrot/src/parrot/models/bots.py.
