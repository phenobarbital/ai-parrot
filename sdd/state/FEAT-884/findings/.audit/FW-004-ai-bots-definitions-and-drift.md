---
id: FW-004
query_id: Q005
type: wiki_query
intent: "Locate where navigator.ai_bots is defined (DDL, datamodel, BotModel) in parrot."
executed_at: 2026-11-12T20:41:06Z
duration_ms: 2600
parent_id: null
depth: 1
---

# FW-004 — navigator.ai_bots: strict asyncdb BotModel (core) + 3 hand-synced DDL copies, frozen by the FEAT-621 AC17 gate

## Summary

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

## Citations

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 100-468
  symbol: `BotModel`
  excerpt: |
    class BotModel(Model):  # "Unified Bot Model combining chatbot and agent functionality."

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 461-468
  symbol: `BotModel.Meta`
  excerpt: |
    class Meta:  # "Meta Bot Model." — schema=PARROT_SCHEMA, name=PARROT_BOTS_TABLE, driver="pg", strict=True (per FEAT-860 F006)

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

## Notes

Schema and table name are configurable (PARROT_SCHEMA / PARROT_BOTS_TABLE) while every SQL file hard-codes
`navigator.ai_bots` — a runner should render placeholders the way navauth renders `{schema}` (FW-001).
BotManager loads bots through `app["database"]` pool + `BotModel.filter(enabled=True)` (FEAT-860 F006, gated by
`ENABLE_DATABASE_BOTS`) — the natural place for a startup "pending migrations" warning.
[cross-lane: type=grep, intent=confirm BotModel.Meta field values and PARROT_SCHEMA/PARROT_BOTS_TABLE in conf.py]
