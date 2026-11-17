---
id: FC-006
query_id: Q011
type: grep
intent: "Find existing navigator.* tables referenced in server code (naming + DDL conventions)."
executed_at: 2026-11-09T17:23:30Z
duration_ms: 1200
parent_id: null
depth: 0
---

# FC-006 — navigator.* tables: DDL lives next to the store (Python lists), `CREATE SCHEMA IF NOT EXISTS navigator`, `default_dsn`; PgUISurfaceStore is the closest store pattern

## Summary

`grep navigator\.[a-z_]+` over `packages/ai-parrot-server/src/` mixes Python imports from the
`navigator-api` package (`navigator.views`, `.types`, `.applications`, `.conf`, `.background`) with real
Postgres tables. Real tables: `ui_surfaces`, `ui_surface_shares`, `metric_definitions`, `service_scheduler`,
`ai_user_llm_keys`, `ai_skills_catalog`, `users_bots`, `ai_user_credentials`, `ai_user_toolkit_overrides`,
`studio_drafts`, `users_prompts`, `notification_batch_recipients`, `notification_templates`, `credentials`,
`ai_studio_migrations`, `ai_bots`, `ai_agent_drafts`, `ai_agents`, `connections`. No `crew_*` table exists in
the navigator schema. The closest hand-written store is `PgUISurfaceStore`
(`handlers/models/ui_surfaces.py`, FEAT-492/535): module-level `_DDL_STATEMENTS` starting with
`CREATE SCHEMA IF NOT EXISTS navigator`, `CREATE TABLE IF NOT EXISTS navigator.<t>`, additive
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` ("live migration idiom", citing `models/bots.py:573-577`), lazy
`ensure_schema()` tolerating "already exists" races between workers, `AsyncDB("pg", dsn=default_dsn)` per
call (`async with await db.connection() as conn`), and `save(..., overwrite=True)` → `ON CONFLICT DO UPDATE`.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 1-17
  symbol: `module docstring (pattern provenance)`
  excerpt: |
    Owns two auto-created Postgres tables:
    - ``navigator.ui_surfaces`` ...
    Follows the ``AsyncDB("pg", dsn=default_dsn)`` per-call idiom used by
    ``handlers/comm_center.py`` (``_get_db()`` + ``async with await
    db.connection() as conn:``) and the ``CREATE TABLE IF NOT EXISTS`` auto-create
    convention illustrated by ``handlers/models/bots.py`` / ``autonomous/ledger.py``.

- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 29-30
  symbol: `imports`
  excerpt: |
    from asyncdb import AsyncDB
    from parrot.conf import default_dsn

- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 107-154
  symbol: `_DDL_STATEMENTS`
  excerpt: |
    "CREATE SCHEMA IF NOT EXISTS navigator",
    CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (
        surface_id UUID PRIMARY KEY, kind VARCHAR(32) NOT NULL, title TEXT NOT NULL,
        envelope JSONB NOT NULL, ..., tenant VARCHAR(63), ...
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())
    "CREATE INDEX IF NOT EXISTS ix_ui_surfaces_user ON navigator.ui_surfaces (user_id)",
    # Live migration idiom (models/bots.py:573-577): additive ADD COLUMN IF NOT EXISTS ...
    "ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS tenant VARCHAR(63)",

- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 457-501
  symbol: `PgUISurfaceStore.__init__ / _get_db / _ensure_ready / ensure_schema`
  excerpt: |
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or default_dsn
        self._schema_ensured = False
    def _get_db(self) -> AsyncDB: return AsyncDB("pg", dsn=self.dsn)
    async def ensure_schema(self) -> None:
        async with await db.connection() as conn:
            for stmt in _DDL_STATEMENTS:
                try: await _exec(conn, stmt)
                except Exception as exc:
                    if "already exists" in str(exc).lower(): continue
                    raise

- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 503-520
  symbol: `PgUISurfaceStore.save`
  excerpt: |
    async def save(self, record: UISurfaceRecord, *, overwrite: bool = False) -> str:
        await self._ensure_ready()
        sql = _UPSERT_SQL if overwrite else _INSERT_OR_SKIP_SQL
        async with await db.connection() as conn:
            inserted = await conn.fetchval(sql, surface_uuid, record.kind.value, ...)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 495
  symbol: `BotManager (DB bot loader docstring)`
  excerpt: |
    bot_model: A loaded ``BotModel`` row (``navigator.ai_bots``).

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 182-185
  symbol: `navigator.ai_studio_migrations`
  excerpt: |
    (references navigator.ai_studio_migrations — a migration-tracking table; see FC-012)

## Notes

- Connection idiom differs between the two Postgres precedents: `PostgresResultStorage` (core) holds ONE
  lazy connection from `CREW_RESULT_STORAGE_PG_DSN`; `PgUISurfaceStore` (server) opens a fresh
  `AsyncDB("pg", dsn=default_dsn)` per call. A crew-definition store in the server package naturally
  follows the server idiom + `default_dsn` (the `navigator` schema lives in the main Navigator DB).
- `tenant VARCHAR(63)` is the navigator-schema tenant column convention here (vs `TEXT` in crew_executions).
- Full SQL bodies `_UPSERT_SQL` / `_INSERT_OR_SKIP_SQL` not read (lines ~157-450).
