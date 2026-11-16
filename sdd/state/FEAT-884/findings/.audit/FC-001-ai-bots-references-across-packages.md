---
id: FC-001
query_id: Q007
type: grep
intent: "Locate every reference to ai_bots across packages (models, SQL, handlers, botmanager loader)."
executed_at: 2026-11-12T20:40:22Z
duration_ms: 900
parent_id: null
depth: 0
---

# FC-001 — Where navigator.ai_bots is referenced

## Summary

33 files mention `ai_bots` (incl. tests and stale `build/` copies). The two **definitions** are the SQL DDL
`packages/ai-parrot-server/src/parrot/handlers/creation.sql` (ai-parrot-server) and the datamodel
`BotModel` in `packages/ai-parrot/src/parrot/models/bots.py` (core), whose table/schema names come from
`PARROT_BOTS_TABLE` / `PARROT_SCHEMA` in `parrot/conf.py`. Every other hit is a consumer (manager loader,
agent_guard permissions, reranker/parent-searcher factories, studio handlers, server status UI). No Python
code issues CREATE/ALTER on ai_bots at runtime — DDL lives only in SQL files.

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 121-122
  symbol: `PARROT_BOTS_TABLE`
  excerpt: |
    PARROT_BOTS_TABLE = config.get("PARROT_BOTS_TABLE", fallback="ai_bots")
    PARROT_SCHEMA = config.get("PARROT_SCHEMA", fallback="navigator")

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 9-12
  excerpt: |
    DROP TABLE IF EXISTS navigator.ai_bots CASCADE;
    CREATE TABLE IF NOT EXISTS navigator.ai_bots (

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 522
  excerpt: |
    bot_model: A loaded ``BotModel`` row (``navigator.ai_bots``).

- path: `packages/ai-parrot/src/parrot/auth/agent_guard.py`
  lines: 76
  excerpt: |
    """Validate and parse the JSONB shape stored in ``ai_bots.permissions``.

- path: `packages/ai-parrot-server/src/parrot/server/ui/status.py`
  lines: 176
  excerpt: |
    Number of enabled rows in the ``ai_bots`` table, or 0 when the

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_db.py`
  lines: 77
  excerpt: |
    """GLOBAL partition: the duplicate check also covers the legacy registry and ``ai_bots``; bot class check."""

- tests: `packages/ai-parrot/tests/handlers/test_bot_model_fields.py`, `packages/ai-parrot/tests/manager/test_bot_loading_with_factories.py`, `packages/ai-parrot/tests/fixtures/bot_rows/*.sql`, `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`

## Notes

`packages/*/build/lib*/` hold stale copies of creation.sql/bots.py — not sources; ignore.
The DDL (server package) and the model (core package) live in different distributions — placement question
for the migration catalog. See FC-002 (DDL contents), FC-003 (model), FC-004 (sdd/migrations).
