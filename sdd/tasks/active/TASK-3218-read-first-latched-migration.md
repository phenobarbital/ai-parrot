# TASK-3218: Read-first, latched schema migration

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3217
**Assigned-to**: unassigned

---

## Context

Spec §2 ("Migration becomes read-first") and §3 Module 1. `_migrate()` (store.py:1109) is
the single largest source of spurious writes on this plane: it runs on EVERY connection
(called unconditionally at store.py:968) and always ends with

```python
await conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version' AND value != ?", ...)
await conn.commit()
```

The `UPDATE` is a no-op row-wise on a current plane, but it is still a **write statement**:
it takes the writer lock and starts a transaction. That is precisely what AC-4 forbids and
what makes N concurrent readers contend for the one writer lock.

TASK-3217 added the `self._migrated` latch and calls `_migrate` from `_write`. This task
rewrites `_migrate` itself so it probes first and only writes when a column or the version
actually differs.

> ### ⚠️ PR #1381 (wiki FTS schema v3) HAS LANDED — contract re-verified
> The FTS hotfix merged to `main` and synced into `dev` (`2394f2d95` → `641b16278`)
> **while this task was being written**. Every anchor below was re-verified against the
> post-merge tree on 2026-09-14. What changed, and why it matters here:
>
> - `SCHEMA_VERSION` is now **`"3"`** (store.py:50), not `"2"`.
> - `WIKI_SCHEMA_SQL` is now `WIKI_TABLES_SQL + WIKI_FTS_SQL` (store.py:216).
> - **`_migrate()` now calls `await self._migrate_fts(conn)`** (store.py:1123), between the
>   column loop and the version bump. Your rewrite MUST keep that call — dropping it leaves
>   a legacy plane's FTS indexes unmigrated and `search_fts` then raises
>   `no such column: pages_fts.concept_id`.
> - New siblings: `_migrate_fts` (store.py:1135), `_uses_legacy_fts` (store.py:1194), and a
>   `self._legacy_fts: dict[str, bool]` cache (store.py:835).
>
> **`_migrate_fts` is already read-first** — it probes with `PRAGMA table_info` plus one
> `sqlite_master` trigger count and returns early when there is nothing to do. It is the
> precedent for this task's design, not an obstacle to it. Note that it DOES commit
> (store.py:1185), but only on the migrating path.

---

## Scope

- Split `_migrate` into a read-only probe and a write-only apply step.
- The probe uses `PRAGMA table_info(...)` and a `SELECT` of `meta.schema_version` — both
  pure reads — and returns the set of missing columns plus whether the version is stale.
- When the probe finds nothing to do, `_migrate` returns having issued **zero** write
  statements and no `commit()`.
- When work is needed, apply the `ALTER TABLE`s and the version `UPDATE`, then commit.
- Preserve the existing behaviour exactly for a legacy plane: same columns added, same
  final `schema_version`.

**NOT in scope**: the `_migrated` latch itself or the `_write` call into `_migrate` (both
landed in TASK-3217); converting the 21 `_connect()` call sites (TASK-3219); removing the
`await self._migrate(conn)` call at store.py:968 inside the legacy `_connect` (TASK-3219
deletes `_connect` wholesale).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Rewrite `_migrate`; add `_migration_needed` probe |
| `tests/knowledge/wiki/test_store_concurrency.py` | MODIFY | Add the read-first / latch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports. Everything needed is already at the top of `store.py` (see TASK-3217).

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "3"                                              # line 50  (bumped by PR #1381)

_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]] = {          # line 229
    "pages": [
        ("origin", "TEXT NOT NULL DEFAULT 'ingest'"),
        ("asserted_by", "TEXT"),
        ("content_hash", "TEXT"),
    ],
}

_SCHEMA_TABLES = frozenset({"meta", "sources", "pages", "edges",
                            "pages_fts", "embeddings", "symbols",
                            "symbols_fts"})                       # line 240

class SQLiteWikiStore(BaseWikiStore):                             # line 774
    async def _migrate(self, conn: aiosqlite.Connection) -> None:     # line 1109
    async def _migrate_fts(self, conn: aiosqlite.Connection) -> None: # line 1135
    async def _uses_legacy_fts(self, conn, table: str) -> bool:       # line 1194
    self._legacy_fts: dict[str, bool]                                 # line 835

_FTS_TRIGGERS = frozenset({"pages_ai", "pages_ad", "pages_au",
                           "symbols_ai", "symbols_ad", "symbols_au"})  # line 221
_FTS_TABLES = ("pages_fts", "symbols_fts")                            # line 224
```

`_migrate` body as it stands today — **store.py:1116-1133**, verbatim, this is what you
are replacing:

```python
        for table, columns in _MIGRATION_COLUMNS.items():
            async with conn.execute(f"PRAGMA table_info({table})") as cur:
                existing = {row["name"] for row in await cur.fetchall()}
            for name, col_type in columns:
                if name not in existing:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")

        await self._migrate_fts(conn)

        # FEAT-498: bump a pre-existing plane's recorded schema version once
        # the symbols/symbols_fts tables and content_hash column above are
        # in place (INSERT OR IGNORE in _connect() never touches an
        # existing row, so a v1 plane would otherwise keep reporting "1").
        await conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version' AND value != ?",
            (SCHEMA_VERSION, SCHEMA_VERSION),
        )
        await conn.commit()
```

`_migrate_fts` (store.py:1135) — ALREADY read-first, and the shape this task applies to
`_migrate` itself:

```python
        legacy: list[str] = []
        for table in _FTS_TABLES:
            async with conn.execute(f"PRAGMA table_info({table})") as cur:
                columns = {row["name"] for row in await cur.fetchall()}
            if columns and "concept_id" in columns:
                legacy.append(table)

        placeholders = ", ".join("?" * len(_FTS_TRIGGERS))
        async with conn.execute(
            f"SELECT count(*) FROM sqlite_master WHERE type = 'trigger' AND name IN ({placeholders})",
            sorted(_FTS_TRIGGERS),
        ) as cur:
            live_triggers = (await cur.fetchone())[0]

        if not legacy and live_triggers == len(_FTS_TRIGGERS):
            return          # <- the early return this task mirrors in _migrate
        ...                 # DDL + commit, only on the migrating path
```

Callers of `_migrate` (verified — exactly two after TASK-3217):
- `store.py:968` — inside the legacy `_connect`, unconditional. Leave it; TASK-3219
  deletes `_connect`.
- `_write()` — added by TASK-3217, guarded by the `self._migrated` latch.

From TASK-3217, available on `self`:
```python
self._migrated: asyncio.Event      # latch, set after a successful probe/apply
self._init_lock: asyncio.Lock      # pre-existing, store.py:861
self._policy: SQLitePragmaPolicy
```

### Does NOT Exist

- ~~`_migration_needed` / `_probe_schema`~~ — this task creates the probe; no such helper
  exists today.
- ~~a `schema_version` row guaranteed to be present~~ — it is written with
  `INSERT OR IGNORE` at store.py:955-957 during first-time schema replay. On a plane that
  predates that, the `SELECT` can return **no row at all**; handle that.
- ~~`PRAGMA user_version`~~ — this codebase does NOT use it; the version lives in the
  `meta` table as a TEXT value (`SCHEMA_VERSION = "3"`, a string, not an int).
- ~~`conn.commit()` being harmless~~ — on the autocommit connection TASK-3217 introduces
  (`isolation_level=None`), a stray `commit()` is exactly the spurious write AC-4 forbids.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_migration_needed(conn)` returning the pending work — *why*: separating the probe
   from the apply is what makes "issued no write statement" testable rather than merely
   asserted; TASK-3226 traces SQL against it.
2. Probe columns with `PRAGMA table_info` — *why*: it is a pure read and is already the
   mechanism the current code uses, so a legacy plane is detected identically.
3. Probe the version with `SELECT value FROM meta WHERE key = 'schema_version'` — *why*:
   replacing the unconditional `UPDATE` with a `SELECT` is the single change that removes
   the writer-lock acquisition from every read (AC-4). Treat a MISSING row as stale.
4. Return early when nothing is pending, before issuing any write — *why*: AC-4. This is
   the whole point of the task; an early `return` with no `commit()` is required.
5. Only when work is pending, run the `ALTER TABLE`s and the `UPDATE`, then commit —
   *why*: preserves the FEAT-498 behaviour for legacy planes bit for bit.
6. Call `_migrate_fts(conn)` unconditionally, ABOVE the early return — *why*: it is
   already read-first and self-guarding, so it costs no write on a current plane, and
   moving it below the return would stop legacy planes from getting their FTS migration.
7. Keep `_MIGRATION_COLUMNS` and `SCHEMA_VERSION` as the sources of truth — *why*: do not
   inline the column list; a future migration must keep working by editing that dict only.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'async def _migrate' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# REPLACE the whole method at store.py:1109-1133 (`async def _migrate` through its
# trailing `await conn.commit()`) with the two methods below.

    async def _migration_needed(
        self,
        conn: aiosqlite.Connection,
    ) -> tuple[list[tuple[str, str, str]], bool]:
        """Probe the plane for pending migration work, writing nothing.

        Pure reads only: ``PRAGMA table_info`` per migrated table and one
        ``SELECT`` of the recorded schema version. This is what lets a
        read on an already-current plane take no writer lock (AC-4).

        Args:
            conn: An open connection; not mutated.

        Returns:
            ``(missing_columns, version_is_stale)`` where each missing
            column is ``(table, name, col_type)``.
        """
        missing: list[tuple[str, str, str]] = []
        for table, columns in _MIGRATION_COLUMNS.items():
            async with conn.execute(f"PRAGMA table_info({table})") as cur:
                existing = {row["name"] for row in await cur.fetchall()}
            for name, col_type in columns:
                if name not in existing:
                    missing.append((table, name, col_type))
        async with conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ) as cur:
            row = await cur.fetchone()
        # A plane with no recorded version predates the meta row and
        # counts as stale — never as current.
        version_stale = row is None or row[0] != SCHEMA_VERSION
        return missing, version_stale

    async def _migrate(self, conn: aiosqlite.Connection) -> None:
        """Add post-schema columns and bump the version, only if needed.

        Read-first: on a current plane this issues ZERO write statements
        and does not commit (AC-4). ``CREATE TABLE IF NOT EXISTS`` never
        alters existing tables, so planes created before the
        origin/asserted_by/content_hash columns shipped are upgraded here
        via idempotent ``ALTER TABLE``.

        Args:
            conn: An open connection.
        """
        # _migrate_fts self-guards and is read-first: on a current plane it
        # issues two PRAGMA table_info calls and one sqlite_master SELECT,
        # then returns. Calling it unconditionally therefore costs no write
        # and keeps a legacy plane's FTS migration intact. It must NOT move
        # below the early return — see the box at the top of this file.
        await self._migrate_fts(conn)

        missing, version_stale = await self._migration_needed(conn)
        if not missing and not version_stale:
            # Nothing to do — return WITHOUT writing or committing. This
            # early return is the point of the whole task; do not add a
            # commit() here "for safety".
            return
        self.logger.debug(
            "migrating wiki plane %s: %d column(s), version_stale=%s",
            self._db_path,
            len(missing),
            version_stale,
        )
        for table, name, col_type in missing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")
        if version_stale:
            # FEAT-498: bump a pre-existing plane's recorded version once
            # the symbols/symbols_fts tables and content_hash column are
            # in place (INSERT OR IGNORE during schema replay never
            # touches an existing row, so a v1 plane would otherwise keep
            # reporting "1").
            # FILL IN: write SCHEMA_VERSION into meta.schema_version —
            # bounded by: it must also work when the row is ABSENT (use an
            # upsert, not a bare UPDATE), and it must leave a current
            # plane byte-identical. See the original statement in the
            # Codebase Contract above.
            raise NotImplementedError
        await conn.commit()
```
**Why this shape**: `_migrate_fts` stays unconditional because it is already its own read-first gate (store.py:1160-1174) — moving it under the early return would silently stop migrating legacy FTS indexes, which is the bug PR #1381 just fixed. The probe/apply split is what makes AC-4 provable — TASK-3226 traces
every statement a read issues and asserts none of them is DML/DDL. The early `return`
before `commit()` is load-bearing: on the autocommit connection from TASK-3217, a stray
`commit()` still takes the writer lock. The `row is None` case matters because
`schema_version` is written with `INSERT OR IGNORE` (store.py:955-957) and an old plane may
lack it entirely — a bare `UPDATE` would silently never insert it, leaving the plane
permanently "stale" and re-migrating on every write.

### `tests/knowledge/wiki/test_store_concurrency.py` (MODIFY)

```python
# AFTER — append a new class at the end of the file created by TASK-3217.

class TestReadFirstMigration:
    async def test_current_plane_needs_no_migration(self, store: SQLiteWikiStore) -> None:
        """The probe reports nothing pending on a freshly built plane."""
        async with store._open(writable=True) as conn:
            missing, stale = await store._migration_needed(conn)
        assert missing == []
        assert stale is False

    async def test_migrate_writes_nothing_on_current_plane(self, store: SQLiteWikiStore) -> None:
        """`_migrate` issues no DML/DDL when there is nothing to do (AC-4)."""
        # FILL IN: wrap the connection's `execute` (or use
        # `conn.set_trace_callback` on the underlying sqlite3 connection) to
        # record every statement `_migrate` issues, then assert none of them is
        # an ALTER / UPDATE / INSERT / DELETE / COMMIT — bounded by AC-4.

    async def test_legacy_plane_migrates_once_and_bumps_version(self, tmp_path: Path) -> None:
        """A legacy plane gains its columns and reaches SCHEMA_VERSION."""
        # FILL IN: build a plane with stdlib sqlite3 that is missing
        # `pages.content_hash` and carries meta.schema_version = '1'; run a write;
        # assert the column exists and the version is now '3' — bounded by AC-1
        # (no data rewrite) and the FEAT-498 behaviour preserved.

    async def test_absent_version_row_is_treated_as_stale(self, tmp_path: Path) -> None:
        """A plane with no schema_version row migrates and gains the row."""
        # FILL IN: bounded by the `row is None` branch above — a bare UPDATE would
        # leave the row absent forever.

    async def test_migration_latch_suppresses_second_probe(self, store: SQLiteWikiStore) -> None:
        """`self._migrated` stops the per-connection probe after the first write."""
        # FILL IN: assert `store._migrated.is_set()` after one `_write`, and that a
        # second `_write` does not call `_migration_needed` again (monkeypatch it to
        # raise) — bounded by spec §2 ("an asyncio.Event ... suppresses the
        # post-success per-connection migration probe without becoming
        # process-global").

    async def test_latch_is_per_store_not_global(self, tmp_path: Path) -> None:
        """Two stores on two planes do not share the latch (spec §2)."""
        # FILL IN: bounded by spec §2's "without becoming process-global".
```

### FILL IN checklist
- [ ] `_migrate` version bump — upsert that also works when the row is absent; bounded by
      the `row is None` branch and FEAT-498 parity.
- [ ] `test_migrate_writes_nothing_on_current_plane`; bounded by AC-4.
- [ ] `test_legacy_plane_migrates_once_and_bumps_version`; bounded by AC-1.
- [ ] `test_absent_version_row_is_treated_as_stale`.
- [ ] `test_migration_latch_suppresses_second_probe`; bounded by spec §2.
- [ ] `test_latch_is_per_store_not_global`; bounded by spec §2.

---

## Acceptance Criteria

- [ ] On a current-schema plane, `_migrate()` issues zero write statements and does not
      commit.
- [ ] On a legacy plane missing `pages.content_hash`, the column is added and
      `meta.schema_version` becomes `"3"` — same end state as before this task.
- [ ] `_migrate()` still calls `_migrate_fts()`, and a legacy-FTS plane is still migrated
      to the external-content shape (PR #1381 behaviour preserved).
- [ ] A plane with no `schema_version` row ends up WITH the row set to `"3"`.
- [ ] `_migration_needed()` issues only `PRAGMA table_info` and one `SELECT`.
- [ ] A current plane's whole `_migrate()` call (including `_migrate_fts`) issues zero
      write statements.
- [ ] `self._migrated` is set after the first successful migration and is per-instance.
- [ ] No regression:
      `pytest tests/knowledge/wiki/test_store.py tests/knowledge/wiki/test_store_migration_v2.py -q`
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_store_concurrency.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/store.py`

---

## Test Specification

See the blueprint. `tests/knowledge/wiki/test_store_migration_v2.py` already covers the
legacy-plane upgrade — run it as the regression guard and do NOT change its expectations.

---

## Agent Instructions

1. **Read the spec** — §2 "Migration becomes read-first", §3 Module 1, AC-4.
2. **Check dependencies** — TASK-3217 completed; `self._migrated` and `_open` must exist.
3. **Verify the Codebase Contract** — confirm `_migrate` is still at store.py:1109 and
   `_MIGRATION_COLUMNS` at 166. Update this contract first if they moved.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
