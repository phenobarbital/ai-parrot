---
id: FC-011
query_id: Q012
type: read
intent: "Existing parrot migration runner discovered via the studio ledger DDL (follow-up of Q012)."
executed_at: 2026-11-12T20:41:59Z
duration_ms: 600
parent_id: FC-012
depth: 1
---

# FC-011 — parrot already ships a ledger-based migration runner: Agent Studio's parrot-studio-migrate

## Summary

`parrot/handlers/studio/storage/migrate.py` (ai-parrot-server, 285 lines) is a complete, parrot-native precedent:
ledger `navigator.ai_studio_migrations(version int PK, name, checksum sha256 of BODY, applied_at)`, files
`000N_name.sql` loaded via `importlib.resources` from `parrot.handlers.studio.storage.migrations`, each file split at a
`-- @studio-ledger` marker into body + trailer (the trailer is the ledger INSERT), a `MANIFEST.json` of checksums,
`pg_advisory_xact_lock(4715391001)`, PG ≥ 14 check, per-file transaction with re-read of the ledger (concurrent-runner
safe). CLI (argparse, console script `parrot-studio-migrate`): `--dsn` (required), `--dry-run`, `--verify`
(missing/drift/unknown, exit 1), `--print` (emit pending SQL for a DBA), `--stamp` (release tooling rewrites trailers
+ MANIFEST). Startup only *probes* the ledger read-only (`backend.py:_probe`) to decide whether the database backend
is usable. It is scoped to Studio tables only; ai_bots is not in it.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0001_studio_migrations_ledger.sql`
  lines: 1-14
  excerpt: |
    SELECT pg_advisory_xact_lock(4715391001);   -- STUDIO_MIGRATION_LOCK_KEY
    CREATE SCHEMA IF NOT EXISTS navigator;
    CREATE TABLE IF NOT EXISTS navigator.ai_studio_migrations (
        version integer PRIMARY KEY, name text NOT NULL,
        checksum text NOT NULL,          -- sha256 hex of the file BODY (§2.12), never of the trailer
        applied_at timestamptz NOT NULL DEFAULT now(), ...
    -- @studio-ledger
    INSERT INTO navigator.ai_studio_migrations (version, name, checksum) VALUES (1, ...) ON CONFLICT (version) DO NOTHING;

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 18-25
  symbol: `STUDIO_SCHEMA_REQUIRED`
  excerpt: |
    STUDIO_SCHEMA_REQUIRED: int = 9
    STUDIO_MIGRATION_LOCK_KEY: int = 4715391001
    STUDIO_MIN_SERVER_VERSION_NUM: int = 140000
    LEDGER_MARKER: str = "-- @studio-ledger"
    MIGRATIONS_PACKAGE: str = "parrot.handlers.studio.storage.migrations"
    MANIFEST_NAME: str = "MANIFEST.json"

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 138-160
  symbol: `LedgerState.problems`
  excerpt: |
    found.extend(f"missing {v}" for v in range(1, required + 1) if v not in self.applied)
    found.extend(f"drift {v}" for v, digest in sorted(self.applied.items()) if v in manifest and manifest[v] != digest)
    found.extend(f"unknown {v}" for v in sorted(self.applied) if v not in manifest)

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 191-216
  symbol: `apply_studio_migrations`
  excerpt: |
    async def apply_studio_migrations(pool: Any, *, dry_run: bool = False) -> list[int]:
        pending = [m for m in list_migrations() if m.version not in state.applied]
        for mig in pending:
            async with studio_transaction(pool) as conn:
                await _exec(conn, mig.body.decode("utf-8"))
                if mig.version in (await read_ledger(conn)).applied: continue
                await _exec(conn, mig.trailer.decode("utf-8"))

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 219-227
  symbol: `_build_parser`
  excerpt: |
    parser = argparse.ArgumentParser(prog="parrot-studio-migrate", ...)
    mode.add_argument("--dry-run" ...); mode.add_argument("--verify" ...)
    mode.add_argument("--print", dest="print_" ...); mode.add_argument("--stamp" ...)

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py`
  lines: 58-64
  symbol: `_probe`
  excerpt: |
    async def _probe(pool: Any) -> migrate.LedgerState | Exception:
        """Read-only probe; a failure is returned (not raised) so the caller maps it to ``unavailable``."""
        async with pool.acquire() as conn:
            return await migrate.read_ledger(conn)

- path: `packages/ai-parrot-server/pyproject.toml`
  lines: 107-109
  excerpt: |
    [project.scripts]
    parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"
    parrot-studio-migrate = "parrot.handlers.studio.storage.migrate:main"

## Notes

Design fork for synthesis: generalize this runner (multi-set, ledger per set or a unified ledger) vs. port navauth's.
Any unified `parrot self migration` must either absorb `ai_studio_migrations` as one set or delegate to it — two
ledgers in `navigator` with diverging semantics would be confusing. Differences vs navauth: integer versions vs
(set, filename); checksum of body vs raw bytes; xact lock inside SQL vs session lock in Python; `--print` DBA mode and
release-time `--stamp`/MANIFEST (no navauth equivalent); no CHANGED/reapply, drift is only reported.
Tests: `packages/ai-parrot-server/tests/studio/storage/test_migration_files.py`, `test_migrations_db.py` (FC-016).
[cross-lane: type=wiki_query, intent=Agent Studio storage spec §2.12 migration design rationale]
