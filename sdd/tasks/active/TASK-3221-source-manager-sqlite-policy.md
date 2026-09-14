# TASK-3221: SourceCollectionManager busy timeout and explicit write transactions

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3216
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. `SourceCollectionManager` is the *other* writer against the very same
`wiki.db` file — it is synchronous stdlib `sqlite3`, and `_connect()` (sources.py:995)
opens with SQLite's implicit default timeout and deferred transactions. So a source upsert
racing a `build` gets a raw `database is locked` immediately, without ever waiting.

This task gives it the same bounded, explicit policy as the async store. It is
**parallel-safe with TASK-3217/3218/3219/3220**: it touches only `sources.py`, shares no
file with them, and depends solely on TASK-3216 for the `WikiStoreBusy` type.

---

## Scope

- Add a `busy_timeout: float = 15.0` keyword argument to `SourceCollectionManager.__init__`.
- `_connect()` passes `timeout=` and `isolation_level=None` and sets `PRAGMA busy_timeout`.
- Add a `_write(operation)` sync context manager running `BEGIN IMMEDIATE` / `COMMIT` with
  `ROLLBACK` on failure, mapping busy at the begin boundary to `WikiStoreBusy`.
- Route the SQLite write paths — `_upsert`, `_upsert_many`, `_migrate_sources_columns`, and
  the `__init__` schema replay — through `_write`.
- Leave the JSON and ArangoDB branches behaviourally unchanged.

**NOT in scope**: anything in `store.py`; forwarding the configured timeout from call
sites (TASK-3223); `remove_source` / query paths that only read.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | `busy_timeout` kwarg; `_connect` policy; `_write`; route SQLite writes |
| `tests/knowledge/wiki/test_sources_concurrency.py` | CREATE | Timeout + immediate-write tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Already present in `sources.py`: `asyncio`, `logging`, `sqlite3`, `Path`, `Any`,
`Literal`. **You must ADD** the context-manager import and the cross-module error import:

```python
from contextlib import contextmanager          # ADD — not currently imported in sources.py
from typing import Iterator                    # ADD if not already in the typing import
from parrot.knowledge.wiki.store import WikiStoreBusy   # ADD (TASK-3216 defines it)
```

> **Import-cycle note — verified.** `sources.py` already imports from `store` lazily
> INSIDE `__init__` (`from parrot.knowledge.wiki.store import WIKI_SCHEMA_SQL`, at the
> `if backend == "sqlite":` branch, sources.py:~211). That lazy form exists for a reason.
> Prefer the same lazy, function-local import for `WikiStoreBusy`, or verify a top-level
> import does not cycle before using one.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                                    # line 107
    _MANIFEST_FILENAME: str = ".manifest.json"                    # line 141

    def __init__(                                                 # lines 143-148
        self,
        sources_dir: Path,
        db_path: Path | None = None,
        backend: Literal["sqlite", "json", "arangodb"] = "sqlite",
        arango_db: Any | None = None,
        arango_store: Any | None = None,
    ) -> None:
        # body 181-221; the sqlite branch (sources.py:~209-216) is:
        #     if backend == "sqlite":
        #         from parrot.knowledge.wiki.store import WIKI_SCHEMA_SQL
        #         self.db_path.parent.mkdir(parents=True, exist_ok=True)
        #         with self._connect() as conn:
        #             conn.executescript(WIKI_SCHEMA_SQL)
        #         self._migrate_sources_columns()
        #         self._migrate_json_manifest()

    def _connect(self) -> sqlite3.Connection:                     # line 995
    def _upsert(self, entry: SourceManifestEntry) -> None:        # line 1007
    def _upsert_many(self, entries: list[SourceManifestEntry]) -> None:   # line 1019
    def _migrate_sources_columns(self) -> None:                   # line 1370
    def _migrate_json_manifest(self) -> None:                     # line 1393
```

`_connect` today — **sources.py:995-1005**, verbatim:

```python
    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection to the shared wiki database.

        Per-call connections keep the sync API thread-safe when invoked
        via ``asyncio.to_thread`` (sqlite3 connections have thread
        affinity); WAL mode allows concurrency with async WikiStore
        connections on the same file.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
```

The two SQLite write tails to convert (both end their method):

```python
# sources.py:1017-1018, end of _upsert
        with self._connect() as conn:
            conn.execute(_SOURCES_UPSERT_SQL, self._entry_params(entry))

# sources.py:1040-1041, end of _upsert_many
        with self._connect() as conn:
            conn.executemany(_SOURCES_UPSERT_SQL, [self._entry_params(e) for e in entries])
```

`_migrate_sources_columns` body — **sources.py:1382-1390**:
```python
        with self._connect() as conn:
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
            for column_map in (_SOURCES_DECISION_COLUMNS, _SOURCES_DOCUMENT_COLUMNS, _SOURCES_EXTERNAL_COLUMNS):
                for name, col_type in column_map.items():
                    if name in existing:
                        continue
                    conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {col_type}")
                    self.logger.debug("Migrated sources table: added column %s (%s)", name, col_type)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_external_id ON sources(external_id)")
```

### Backend branching — verified

The discriminator is the plain string attribute `self.backend`, assigned at
**sources.py:185**. Every polymorphic method inlines the SAME ladder, with sqlite as the
implicit fall-through:

```python
        if self.backend == "json":
            ...
            return
        if self.backend == "arangodb":
            self._run_async(self._async_...(...))
            return
        with self._connect() as conn:      # <- sqlite, the implicit else
            ...
```

Branch sites (all verified): 315/317, 355/357, 502/504, 520/522, 781/788, 826/831,
853/859, 894/898, **1009/1013** (`_upsert`), **1031/1036** (`_upsert_many`), 1149/1154.
Only the two bolded ones are in this task's scope.

### Does NOT Exist

- ~~`SourceCollectionManager._write`~~ — this task creates it.
- ~~`with self._connect() as conn:` closing the connection~~ — **it does NOT.** A
  `sqlite3.Connection` used as a context manager commits (or rolls back) the transaction
  and leaves the connection OPEN. The existing code therefore leaks a connection per call.
  Your `_write` must close it explicitly in a `finally`.
- ~~an async `SourceCollectionManager`~~ — it is synchronous by design (spec §7); do NOT
  make these methods `async`. Callers bridge via `asyncio.to_thread`.
- ~~`SQLitePragmaPolicy` being used here~~ — spec §2 gives the sync manager a plain
  `busy_timeout: float` kwarg, not the policy model. Follow the spec.

---

## Implementation Blueprint

### Steps (in order)
1. Add `busy_timeout: float = 15.0` as a keyword argument and store it — *why*: matches the
   spec's `SourceCollectionManager.__init__(..., busy_timeout: float = 15.0, ...)` exactly,
   and keeps all ~10 existing construction sites source-compatible.
2. Give `_connect` `timeout=` and `isolation_level=None` plus `PRAGMA busy_timeout` —
   *why*: same reasoning as the async store (the kwarg installs the handler; the pragma is
   readable back), and autocommit is required before `_write` can own `BEGIN IMMEDIATE`.
3. Write `_write(operation)` as a `@contextmanager` that closes the connection in a
   `finally` — *why*: see the "Does NOT Exist" note; the current `with self._connect()`
   pattern never closes, and once connections carry a 15 s busy handler a leaked one holds
   resources much longer.
4. Map `sqlite3.OperationalError` with `sqlite_errorcode` in `{5, 517}` at the begin
   boundary to `WikiStoreBusy` — *why*: spec §7 says test codes, not message substrings,
   and a source write must fail the same, recognizable way an async store write does.
5. Convert `_upsert`, `_upsert_many`, `_migrate_sources_columns` and the `__init__` schema
   replay — *why*: those are exactly the SQLite write paths spec §3 M2 names.
6. Leave the JSON and ArangoDB early-return branches untouched — *why*: AC-6 requires them
   behaviourally unchanged.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` (MODIFY — `__init__`)

```python
# occurrences: 1 (verified: grep -c 'arango_store: Any | None = None,' packages/ai-parrot/src/parrot/knowledge/wiki/sources.py)
# REPLACE the signature at sources.py:143-148 — add one keyword-only param at the end:
    def __init__(
        self,
        sources_dir: Path,
        db_path: Path | None = None,
        backend: Literal["sqlite", "json", "arangodb"] = "sqlite",
        arango_db: Any | None = None,
        arango_store: Any | None = None,
        *,
        busy_timeout: float = 15.0,
    ) -> None:
```

```python
# occurrences: 1 (verified: grep -c 'self.logger: logging.Logger = logging.getLogger(__name__)' packages/ai-parrot/src/parrot/knowledge/wiki/sources.py)
# AFTER — insert below `        self.logger: logging.Logger = logging.getLogger(__name__)` (verified: sources.py:188)
        self.busy_timeout: float = busy_timeout
```
**Why**: keyword-only (`*`) so it can never be passed positionally into the `arango_db`
slot by an existing caller. Assigning it before the `if backend == "sqlite":` branch at
~209 matters — that branch calls `_connect()`, which now reads `self.busy_timeout`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` (MODIFY — `_connect` + `_write`)

```python
# occurrences: 1 (verified: grep -c '    def _connect(self) -> sqlite3.Connection:' packages/ai-parrot/src/parrot/knowledge/wiki/sources.py)
# REPLACE the body of `_connect` at sources.py:1003-1005 (the three lines after the
# docstring) and APPEND `_write` immediately after the method.

        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.busy_timeout,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout * 1000)}")
        return conn

    @contextmanager
    def _write(self, operation: str) -> Iterator[sqlite3.Connection]:
        """Run one SQLite write inside an explicit immediate transaction.

        Args:
            operation: Logical name of the write, used in the error.

        Yields:
            An open connection inside a ``BEGIN IMMEDIATE`` transaction.

        Raises:
            WikiStoreBusy: The writer lock was not acquired within
                ``busy_timeout``. Raised only at the begin boundary.
        """
        from parrot.knowledge.wiki.store import WikiStoreBusy

        conn = self._connect()
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                # Codes, not message substrings (spec §7):
                # 5 = SQLITE_BUSY, 517 = SQLITE_BUSY_SNAPSHOT.
                if getattr(exc, "sqlite_errorcode", None) in (5, 517):
                    raise WikiStoreBusy(self.db_path, operation, self.busy_timeout) from exc
                raise
            try:
                yield conn
            except BaseException:
                # FILL IN: roll back, swallowing only a rollback-time
                # sqlite3.Error (log it at debug), then re-raise the ORIGINAL
                # exception — bounded by AC-6 and by the async twin in
                # SQLiteWikiStore._write; a rollback failure must never mask
                # the real error.
                raise
            conn.execute("COMMIT")
        finally:
            # The existing `with self._connect() as conn:` pattern commits but
            # never CLOSES — close explicitly here.
            conn.close()
```
**Why this shape**: `isolation_level=None` puts stdlib `sqlite3` in autocommit so the
explicit `BEGIN IMMEDIATE` is the real transaction start rather than being nested inside a
driver-managed deferred one. Closing in `finally` fixes the pre-existing leak, which
matters more now that each connection carries a 15 s busy handler. The lazy
`WikiStoreBusy` import mirrors the existing lazy `WIKI_SCHEMA_SQL` import in `__init__`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` (MODIFY — route the writes)

```python
# FILL IN: convert these four SQLite write paths from `with self._connect() as conn:`
# to `with self._write("<operation>") as conn:`, leaving the json/arangodb early
# returns above each one untouched — bounded by AC-6:
#   1. `_upsert`                  — sources.py:1017 (operation "upsert_source")
#   2. `_upsert_many`             — sources.py:1040 (operation "upsert_sources")
#   3. `_migrate_sources_columns` — sources.py:1382 (operation "migrate_sources")
#   4. the __init__ schema replay — sources.py:~212 (operation "init_schema")
# Each `with self._connect() as conn:` is NOT unique in the file; disambiguate by the
# enclosing `def` line given in the Codebase Contract above.
```
**Why**: these four are the complete set of SQLite *write* paths in this class. The query
methods (`list_sources`, `get_source`, `find_by_uri`, …) stay on `_connect` — they are
pure reads and must not take a writer reservation.

### `tests/knowledge/wiki/test_sources_concurrency.py` (CREATE)

```python
"""FEAT-557 — SourceCollectionManager SQLite policy tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import WikiStoreBusy


@pytest.fixture
def manager(tmp_path: Path) -> SourceCollectionManager:
    """A SQLite-backed source manager on a temp plane."""
    return SourceCollectionManager(tmp_path / "sources", db_path=tmp_path / "wiki.db")


class TestSQLitePolicy:
    def test_default_busy_timeout(self, manager: SourceCollectionManager) -> None:
        """Defaults to 15 seconds (spec §2)."""
        assert manager.busy_timeout == 15.0

    def test_connection_applies_busy_timeout_pragma(self, manager: SourceCollectionManager) -> None:
        """PRAGMA busy_timeout reflects the configured value, in ms."""
        conn = manager._connect()
        try:
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 15_000
        finally:
            conn.close()

    def test_busy_at_begin_raises_wiki_store_busy(self, tmp_path: Path) -> None:
        """A held peer writer surfaces as WikiStoreBusy, not 'database is locked'."""
        # FILL IN: build a manager with `busy_timeout=1.0`, hold `BEGIN IMMEDIATE` on a
        # separate stdlib sqlite3 connection to the same file, then assert
        # `with manager._write("t"):` raises WikiStoreBusy — bounded by AC-6.

    def test_failed_write_rolls_back(self, manager: SourceCollectionManager) -> None:
        """An exception inside the body leaves no row behind."""
        # FILL IN: bounded by AC-6.


class TestOtherBackendsUnchanged:
    def test_json_backend_writes_no_sqlite(self, tmp_path: Path) -> None:
        """The JSON branch is behaviourally unchanged (AC-6)."""
        # FILL IN: upsert through a `backend="json"` manager and assert the manifest
        # file is written and no wiki.db appears — bounded by AC-6.
```

### FILL IN checklist
- [ ] `_write` rollback branch; bounded by AC-6.
- [ ] Four write-path conversions (sources.py 1017, 1040, 1382, ~212); bounded by AC-6.
- [ ] `test_busy_at_begin_raises_wiki_store_busy`; bounded by AC-6.
- [ ] `test_failed_write_rolls_back`; bounded by AC-6.
- [ ] `test_json_backend_writes_no_sqlite`; bounded by AC-6.

---

## Acceptance Criteria

- [ ] `SourceCollectionManager(...)` still constructs with no `busy_timeout` and defaults
      to `15.0`.
- [ ] `_connect()` returns a connection with `PRAGMA busy_timeout = 15000` and
      `isolation_level is None`.
- [ ] `_write()` issues `BEGIN IMMEDIATE`, commits once, rolls back on error, and CLOSES
      the connection in every path.
- [ ] A contended write raises `WikiStoreBusy`, not a bare `database is locked`.
- [ ] `_upsert`, `_upsert_many`, `_migrate_sources_columns` and the `__init__` schema
      replay all go through `_write`; the read/query methods do not.
- [ ] JSON and ArangoDB branches are unchanged — `pytest tests/knowledge/wiki/test_sources.py
      tests/knowledge/wiki/test_sources_arango.py -q` stays green.
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_sources_concurrency.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/sources.py tests/knowledge/wiki/test_sources_concurrency.py`

---

## Test Specification

See the blueprint. `tests/knowledge/wiki/test_sources.py` is the existing regression guard
for the JSON/Arango branches — do not change its expectations.

---

## Agent Instructions

1. **Read the spec** — §3 Module 2, §7 Patterns, AC-6.
2. **Check dependencies** — TASK-3216 completed; `WikiStoreBusy` importable.
3. **Verify the Codebase Contract** — confirm `_connect` at sources.py:995, `_upsert` at
   1007, `_upsert_many` at 1019, `_migrate_sources_columns` at 1370. Update first if moved.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
