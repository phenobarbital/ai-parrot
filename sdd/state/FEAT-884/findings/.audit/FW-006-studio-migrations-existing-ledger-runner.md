---
id: FW-006
query_id: Q003, Q006
type: wiki_page
intent: "Follow-up: parrot already ships a ledger-based migration runner for Agent Studio — read it as the in-repo pattern to reuse."
executed_at: 2026-11-12T20:41:43Z
duration_ms: 2400
parent_id: FW-002
depth: 1
---

# FW-006 — Parrot already has a versioned, checksummed, ledger-based migration runner: Agent Studio (navigator.ai_studio_migrations)

## Summary

Surfaced by the Q003 follow-up query (`sym:…/studio/storage/migrate.py#apply_studio_migrations`, score 1.00).
`packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py` ("Studio schema migrations … Never imported
at startup") + `migrations/` dir with `0001_studio_migrations_ledger.sql` … `0009_prompt_library_agent_id_sort_order.sql`
and a `MANIFEST.json`. Format: `NNNN_name.sql`, each file = **body** + **trailer** (`-- @studio-ledger` INSERT into
the ledger); checksum = sha256 of the body only; `list_migrations()` loads package data via importlib.resources and
validates contiguity from 1, manifest presence and checksum equality; `stamp_migrations()` is release tooling that
rewrites trailers + MANIFEST. Ledger `navigator.ai_studio_migrations(version int PK, name, checksum, applied_at)`.
Concurrency: every file begins with `SELECT pg_advisory_xact_lock(4715391001)` (transaction-level, not session).
`read_ledger(conn)` is read-only (server_version_num, to_regclass, applied versions); `LedgerState.complete_for /
problems / warnings` report 'server < 14', 'missing N', 'drift N', 'unknown N'. `apply_studio_migrations(pool, *,
dry_run)` applies each pending file in `studio_transaction`, re-reads the ledger after the body (another runner may
have recorded it), then runs the trailer. CLI `main(argv)`: `--dsn, --dry-run, --verify, --print, --stamp`. Live-DB
tests in `packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py` (apply twice, apply on a FEAT-467
database, detect altered and missing, CLI verify/dry-run of versions 1-9).

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 191-216
  symbol: `apply_studio_migrations`
  excerpt: |
    async def apply_studio_migrations(pool: Any, *, dry_run: bool = False) -> list[int]:
        """Per pending file: studio_transaction → body (advisory lock first) → re-read ledger → skip if
        recorded → trailer → commit. Returns versions applied (or pending, when dry_run). Never called at startup."""
        if state.server_version_num < STUDIO_MIN_SERVER_VERSION_NUM: raise RuntimeError(...)
        pending = [m for m in list_migrations() if m.version not in state.applied]

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: n/a (wiki API outline)
  symbol: `main`
  excerpt: |
    def main(argv): CLI: --dsn, --dry-run, --verify, --print, --stamp.
    def stamp_migrations(directory): Release tooling: rewrite every trailer hex and MANIFEST.json from the bodies
    def read_ledger(conn): SHOW server_version_num; to_regclass(...); SELECT version, checksum ... Never DDL.

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0001_studio_migrations_ledger.sql`
  lines: 1-13
  symbol: `navigator.ai_studio_migrations`
  excerpt: |
    SELECT pg_advisory_xact_lock(4715391001);   -- STUDIO_MIGRATION_LOCK_KEY
    CREATE TABLE IF NOT EXISTS navigator.ai_studio_migrations (
        version integer PRIMARY KEY, name text NOT NULL,
        checksum text NOT NULL,          -- sha256 hex of the file BODY (§2.12), never of the trailer
        applied_at timestamptz NOT NULL DEFAULT now(), …
    -- @studio-ledger
    INSERT INTO navigator.ai_studio_migrations (version, name, checksum) VALUES (1, …) ON CONFLICT (version) DO NOTHING;

- path: `packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py`
  lines: 76-191
  symbol: `test_migrations_apply_twice`
  excerpt: |
    test_migrations_apply_twice (L76-82) · test_migrations_apply_on_feat467_database (L85-119)
    test_migrations_detect_altered_and_missing (L142-172)
    test_cli_verifies_and_dry_runs_all_nine_versions (L175-191): a v5-only database fails --verify naming 6, 7, 8 and 9.

## Notes

This is a closer in-repo precedent than navauth: same schema (`navigator`), same `ai_*` table family
(ai_agents, ai_agent_drafts, ai_user_llm_keys, ai_user_credentials, ai_user_toolkit_overrides, prompt_library),
already proven against production-shaped DBs (0004/0005 adopt tables that pre-existed "on hosts that ran FEAT-467").
It differs from navauth in: single global version sequence (no sets), body/trailer split with the ledger write inside
the file, manifest-pinned checksums, transaction-level lock. A `parrot self migration` could generalize this runner
(ai_bots as a second set or as new versions) instead of porting navauth's.
[cross-lane: type=grep, intent=find who invokes studio migrate.main (console script, python -m, docs) and whether the studio runtime verifies the ledger at startup (LedgerState.complete_for callers)]
