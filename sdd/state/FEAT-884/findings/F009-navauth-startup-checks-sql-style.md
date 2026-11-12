---
id: F009
query_id: Q010
type: read
intent: "Startup integration, pre/post-condition checks and SQL authoring style of the navauth migrations."
executed_at: 2026-11-12T20:41:59Z
duration_ms: 400
parent_id: null
depth: 1
merged_from: [FC-010]
---

# F009 — navauth startup is read-only (warn on pending); checks guard each file; SQL is idempotent

## Summary

`startup.py` never applies DDL: `warn_pending_migrations()` reads the ledger for the *enabled* sets and logs a warning
telling operators to run `navauth self upgrade` (probe failures are swallowed into a warning). `checks.py` defines
per-set prerequisite base tables (raises if absent, "provisioned by the Navigator platform") and per-file postconditions
(columns/NOT NULL/unique/FK/indexes) evaluated inside the file's transaction. SQL files are additive and idempotent
(`ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS`, guarded backfills) with a prose header explaining why.

## Citations

- path: `../navigator-auth/navigator_auth/migrations/startup.py`
  lines: 1-5
  excerpt: |
    """Startup migration checks — read-only (FEAT-110, spec M6).
    Application startup no longer applies schema changes; ``navauth self upgrade`` does.

- path: `../navigator-auth/navigator_auth/migrations/startup.py`
  lines: 56-79
  symbol: `warn_pending_migrations`
  excerpt: |
    pending = await pending_migrations(db_pool, enabled_migration_sets(backends))
    except Exception as err:
        logger.warning("Could not verify database migration state (%s); run `navauth self upgrade --check`", ...)
    logger.warning("Database migrations are pending or changed: %s. Run `navauth self upgrade`.", files)

- path: `../navigator-auth/navigator_auth/migrations/checks.py`
  lines: 128-154
  symbol: `check_prerequisites`
  excerpt: |
    def prerequisite_tables(migration_set: str) -> tuple[tuple[str, str], ...]:
        if migration_set == "vault": return ((RELEASED_SCHEMA, "users"),)
    async def check_prerequisites(conn, file):
        raise MigrationError(f"...: missing base table(s) {', '.join(missing)}; base tables are provisioned by the Navigator platform")

- path: `../navigator-auth/navigator_auth/migrations/sql/identity/004_identity_base_columns.sql`
  lines: 9-23
  excerpt: |
    -- Additive and idempotent -- re-run on every startup, and a no-op against a
    -- database already built from the canonical DDL.
    ALTER TABLE IF EXISTS auth.user_identities
        ADD COLUMN IF NOT EXISTS identity_id  UUID DEFAULT gen_random_uuid(),

## Notes

Postconditions are hand-coded per set in Python (oauth2 column/index lists) — heavy; a lighter parrot variant could
derive the column postcondition for ai_bots from BotModel's declared fields (F003).
`access.py` (GRANTs to the runtime role) was not read in detail (budget) — only its outline.
