---
id: F006
query_id: Q012, Q004
type: read
intent: "Read the bot-definition Postgres model (ai_bots) — existing 'definitions live in Postgres' pattern and how BotManager loads from DB."
executed_at: 2026-11-09T17:25:30Z
duration_ms: 1400
parent_id: null
depth: 1
merged_from: [FC-007, FW-007]
---

# F006 — BotModel (navigator.ai_bots): asyncdb `Model` with Meta schema/name from config (PARROT_SCHEMA/PARROT_BOTS_TABLE); BotManager loads via `app["database"]` pool + `BotModel.filter(enabled=True)`

## Summary

[FC-007] Bot definitions in Postgres use an `asyncdb.models.Model` subclass, `BotModel`, now in CORE
(`packages/ai-parrot/src/parrot/models/bots.py`, re-exported by server `handlers/models/bots.py`). Its
`Meta` takes `schema = PARROT_SCHEMA` (config, fallback `"navigator"`) and `name = PARROT_BOTS_TABLE`
(fallback `"ai_bots"`), `driver = "pg"`, `strict = True`; the `CREATE TABLE IF NOT EXISTS navigator.ai_bots`
DDL appears only in the docstring (documentation of production shape, not executed there).
`BotManager._load_database_bots` (gated by `ENABLE_DATABASE_BOTS`) borrows a connection from the app pool
`app["database"]` (`async with await db.acquire() as conn: BotModel.Meta.connection = conn`) and calls
`BotModel.filter(enabled=True)`, then builds each bot. So two Postgres access idioms coexist: asyncdb
`Model` + `app["database"]` pool (bots) vs raw `AsyncDB("pg", dsn=...)` (ui_surfaces, crew_executions).

[FW-007] Memory `mem-65f89185cb0d` (lesson, 2026-10-21): navigator.ai_bots is documented in three places that must
track `parrot.models.bots.BotModel` field-for-field (BotModel docstring, creation.sql,
`sdd/migrations/botmodel-recreate-table.sql`). BotModel has `Meta.strict=True`, so asyncdb SELECTs every
declared field by name and one missing column broke every bot load (`column "toolkit_config" does not exist`).
creation.sql and the BotModel DDL are frozen by the FEAT-621 AC17 gate; deliberate edits go through
`_SANCTIONED_REWRITES`.

## Citations

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 16
  symbol: `import Model`
  excerpt: |
    from asyncdb.models import Model

- path: `packages/ai-parrot/src/parrot/models/bots.py`
  lines: 100-112
  symbol: `BotModel (docstring DDL)`
  excerpt: |
    class BotModel(Model):
        """ Unified Bot Model ...
        SQL Table Creation (matches production):
        CREATE TABLE IF NOT EXISTS navigator.ai_bots (
            chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name VARCHAR NOT NULL,

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

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 121-122
  symbol: `PARROT_BOTS_TABLE / PARROT_SCHEMA`
  excerpt: |
    PARROT_BOTS_TABLE = config.get("PARROT_BOTS_TABLE", fallback="ai_bots")
    PARROT_SCHEMA = config.get("PARROT_SCHEMA", fallback="navigator")

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 662-680
  symbol: `BotManager._load_database_bots`
  excerpt: |
    from ..handlers.models import BotModel
    db = app["database"]
    async with await db.acquire() as conn:
        BotModel.Meta.connection = conn
        try:
            all_bots = await BotModel.filter(enabled=True)
    for bot_model in all_bots:
        bot_instance = await self._build_database_bot(bot_model, app)
        self.add_bot(bot_instance)

- path: `packages/ai-parrot-server/src/parrot/handlers/models/bots.py`
  lines: 1-18
  symbol: `re-export`
  excerpt: |
    ``BotModel`` and its companions moved to core :mod:`parrot.models.bots` so that
    ``parrot.bots`` ... no longer depends on the ai-parrot-server distribution at import time.
    from parrot.models.bots import (BotModel, ...)

- path: `sdd/migrations/botmodel-recreate-table.sql`
  excerpt: |
    third documented DDL site for navigator.ai_bots

## Notes

[FC-007] - `PARROT_SCHEMA` is the configurable schema name; a `navigator.crew_definitions` table should probably
  honour it (e.g. `f"{PARROT_SCHEMA}.crew_definitions"`) rather than hard-code `navigator`.
- `app["database"]` (pool) is only available inside the aiohttp app; `CrewRedis` is constructed in
  `BotManager.__init__` before the app exists — a Postgres crew store must connect lazily (like
  `PgUISurfaceStore` / `PostgresResultStorage`) or be created in `on_startup`.
- `ui_surfaces.py` docstring claims a "live migration idiom" at `models/bots.py:573-577`; those lines are in
  `PromptLibrary`/`ChatbotFeedback` region of the CORE file now — exact lines not verified.
- `BotModel.Meta.connection = conn` mutates class state (not concurrency-safe); not a pattern to copy.

[FW-007] Design implication for crew_definitions: storing the CrewDefinition as one JSONB document (plus a few indexed
identity columns) avoids per-field column drift — CrewDefinition evolves often (FW-002 `_strip_unknown_keys`),
and a column-per-field table would reproduce the ai_bots drift problem.
