---
id: F017
query_id: Q004
type: wiki_page
intent: "Read navigator.ai_bots DDL as the reference convention for a navigator.crew_definitions table."
executed_at: 2026-11-09T17:13:15Z
duration_ms: 300
parent_id: null
depth: 1
merged_from: [FW-006]
---

# F017 — navigator.ai_bots DDL conventions: UUID pk, JSONB config, TIMESTAMPTZ, unique name, updated_at trigger

## Summary

`creation.sql` creates `navigator.ai_bots` with `chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`, JSONB
for every structured config (`model_config`, `tools`, `permissions`, …), `created_at/updated_at TIMESTAMPTZ
DEFAULT NOW()`, `created_by INTEGER`, a `UNIQUE (name)` constraint, GIN indexes on JSONB columns and a
`BEFORE UPDATE` trigger maintaining `updated_at`. The file header says it is initial-setup DDL only — real
environments are moved by the idempotent `sdd/migrations/*.sql` files. ai_bots has no tenant column; crews do.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 12-14
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.ai_bots (
        -- Primary key
        chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 98-99
  excerpt: |
    ALTER TABLE navigator.ai_bots
    ADD CONSTRAINT unq_navigator_ai_bots_name UNIQUE (name);

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 126-129
  excerpt: |
    CREATE TRIGGER trigger_ai_bots_updated_at
        BEFORE UPDATE ON navigator.ai_bots
        FOR EACH ROW
        EXECUTE FUNCTION update_ai_bots_updated_at();

## Notes

A crew table would need a composite uniqueness `(tenant, name)` plus `(tenant, crew_id)` (FW-002), not a bare
`UNIQUE (name)`. creation.sql is byte-frozen by the AC17 gate (FW-008) — the crew DDL must go in its own file,
not appended to creation.sql.
