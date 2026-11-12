---
id: F005
query_id: Q008
type: read
intent: "Sample the ad-hoc ai_bots migration scripts to learn their current conventions."
executed_at: 2026-11-12T20:40:51Z
duration_ms: 300
parent_id: null
depth: 1
merged_from: [FC-005]
---

# F005 — Ad-hoc ai_bots migration scripts: idempotent, self-transacted, rollback in comments, deploy-order prose

## Summary

`FEAT-752-ai-bots-suggestion-columns.sql` shows the de-facto convention: own `BEGIN;/COMMIT;`, `ADD COLUMN IF NOT EXISTS`,
`COMMENT ON COLUMN` with the FEAT id, rollback DDL as comments, and a prose ordering rule ("Apply BEFORE deploying the
code: BotModel selects these columns and fails on a missing one"). `ai-bots-homologate-botmodel.sql` is a catch-up
"add every column" script (14 `ADD COLUMN IF NOT EXISTS`) with a `Status : pending` header — but it predates FEAT-752
and does not include the suggestion columns, so even the "covers every column" script is stale.

## Citations

- path: `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql`
  lines: 1-12
  excerpt: |
    -- Apply BEFORE deploying the code: BotModel selects these columns and fails on a missing one.
    -- Idempotent: safe to re-run on any environment. Defaults match AbstractBot's constructor defaults.
    BEGIN;
    ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS enable_suggestions   BOOLEAN DEFAULT FALSE;

- path: `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql`
  lines: 20-27
  excerpt: |
    COMMIT;
    -- Rollback:
    --   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS suggestion_model;

- path: `sdd/migrations/ai-bots-homologate-botmodel.sql`
  lines: 1-30
  excerpt: |
    -- Homologate navigator.ai_bots with parrot.models.bots.BotModel
    --   BotModel has Meta.strict = True, so asyncdb SELECTs every declared
    --   field by name. Any column the model declares but the table lacks
    --   fails EVERY bot load ...
    -- Safe   : additive, idempotent, no data loss. Safe to re-run anywhere.
    -- Status : pending

## Notes

Files embedding their own BEGIN/COMMIT conflict with a runner that wraps each file in a transaction (navauth's
runner does `async with conn.transaction()`, F007) — import into a catalog requires stripping them.
