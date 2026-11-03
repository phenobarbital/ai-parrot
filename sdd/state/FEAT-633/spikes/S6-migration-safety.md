# Spike S6 — Wiki store migration safety (FEAT-633)

**Date**: 2026-10-26 · **Task**: TASK-4093 · **Status**: pass

## Question
Does backup + O_EXCL lock + schema-version gate keep a plane safe when a newer and an older
runtime open it concurrently (spec §3 M0 S6 → M7)?

## Mechanism under test
- Backup: SQLite online backup API to `<db>.bak-<UTC>` (WAL-consistent), restore on failure.
- Lock: `<db>.migrate.lock` via `os.open(O_CREAT|O_EXCL)`; stale after 600 s; why not
  `project.py:39-42` (fcntl no-op off POSIX).
- Gate: stored `schema_version` vs the running `SCHEMA_VERSION` (TASK-4092), re-checked after the lock
  is acquired; the `min_runtime_version` meta row is informational, quoted in the error only. *[rev 0.5]*

## Evidence
Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (Linux, Python 3.11):
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_migration_safety.py -q` — 9 passed
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py -q` — 9 passed
- Regression: `test_store_meta.py` 8 passed, `test_sqlite_fts_external_content.py` 17 passed, `test_store_attrs.py` 3 passed.
Platforms exercised: Linux only (Windows not run; the lock uses only `os.open` O_EXCL, and the
cross-process test uses the `spawn` context).

## Scenarios
| Scenario | Expected | Observed |
|---|---|---|
| failed migration | backup restored, error re-raised | pass — `test_migration_backup_and_restore`: corrupted row restored to `v`, `.bak-*` kept, lock released |
| newer schema migrates, older schema opens *[rev 0.5]* | WikiStoreVersionError naming both schemas and the stamped release | pass — `test_store_migrate_then_old_open` |
| two processes race the lock | exactly one holds it | pass — `test_migration_lock_is_exclusive_across_processes` (spawned child holds; parent refused; reacquired after release) |
| fcntl unavailable | lock still exclusive | pass — `test_migration_lock_windows_safe` |
| read-only/foreign plane | never migrated, no backup/lock | pass — `test_read_only_plane_never_migrates` (schema_version stays `2`) |
| unwritable plane directory (rev 0.5 C24 / D8 (3)) | clear `WikiStoreMigrationError` naming the directory; not migrated, never silently skipped, store untouched; read-only open works | pass — `test_lock_or_backup_unwritable_dir` (lock step and, with the lock patched, backup step) and `test_read_only_open_in_unwritable_dir` |

## Limitations
- Runtimes predating FEAT-633 ignore the gate (spec §7).
- Stale-lock detection is age-based (600 s), so a holder that migrates longer than that could be overtaken.
- Backup is a full online copy of the plane; its time/size on a very large plane was not measured.
- Backups are kept (never auto-pruned) as the operator's downgrade path.

## Verdict
Mechanism confirmed; no changes required for M7.
