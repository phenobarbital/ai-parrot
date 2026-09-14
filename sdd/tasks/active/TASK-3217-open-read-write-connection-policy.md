# TASK-3217: _open/_read/_write connection policy with BEGIN IMMEDIATE

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3216
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1, the core of FEAT-557. Today every `SQLiteWikiStore` operation — read or
write — funnels through one `_connect()` (store.py:888) that opens with SQLite's implicit
default timeout, leaves transactions deferred, and runs migration on every connection. A
pure reader therefore competes for the writer lock, and a read-then-write transaction can
fail with `SQLITE_BUSY_SNAPSHOT` without ever consulting the busy handler.

This task introduces the three replacement primitives — `_open()`, `_read()`, `_write()` —
and wires the policy into `__init__`. It deliberately LEAVES `_connect()` in place and
leaves all 21 existing call sites untouched; TASK-3219 does that sweep. Splitting it this
way keeps this task reviewable and keeps the tree green at every commit.

---

## Scope

- Add `sqlite_policy` and `persistent_writer` keyword-only parameters to
  `SQLiteWikiStore.__init__`, storing a validated `SQLitePragmaPolicy`.
- Add `_open(*, writable: bool)` — the single place that calls `aiosqlite.connect`, sets
  `timeout=`, `isolation_level=None`, `row_factory`, and applies the pragma set.
- Add `_read()` — an `@asynccontextmanager` that yields a read-safe connection and issues
  NO write statement, no migration, and no write-capable pragma.
- Add `_write(operation: str)` — an `@asynccontextmanager` that runs migration once per
  store instance, executes `BEGIN IMMEDIATE`, yields, then commits once on success or
  rolls back on failure; maps SQLite codes 5 / 517 at the begin boundary to
  `WikiStoreBusy`.
- Thread the busy timeout through `_connect_readonly()` and `_connect_immutable()`.
- Add the `asyncio.Event` migration latch attribute (the read-first migration BODY is
  TASK-3218; here only the latch attribute and the `_write` call into `_migrate` land).

**NOT in scope**: rewriting `_migrate()` to be read-first (TASK-3218); converting the 21
`self._connect()` call sites or deleting `_connect` (TASK-3219); `checkpoint()`
(TASK-3220); `sources.py` (TASK-3221); config fields (TASK-3222); any construction-site
plumbing (TASK-3223). `_connect()` MUST keep working unchanged after this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `__init__` params; new `_open`/`_read`/`_write`; timeout in the read-only ladder |
| `tests/knowledge/wiki/test_store_concurrency.py` | CREATE | First tests for the new primitives (extended by TASK-3226) |

> **Test directory — read this.** The store's real suite is `tests/knowledge/wiki/`
> (70 entries, incl. `test_store.py` with `TestReadOnlyFallback`,
> `TestExplicitReadOnlyMode`, `TestReadOnlyConcurrencySafety`). The spec §3 M5 text names
> `packages/ai-parrot/tests/knowledge/wiki/` — that is the *other*, smaller tree (18 CLI/
> MCP/Jira files) and holds NO store tests. New store tests go beside `test_store.py`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

All already present at the top of `store.py` — add NO new imports.

```python
import asyncio                                     # verified: store.py:29
import logging                                     # verified: store.py:31
import sqlite3                                     # verified: store.py:33
from contextlib import asynccontextmanager         # verified: store.py:36
from pathlib import Path                           # verified: store.py:38
from typing import AsyncIterator, Optional         # verified: store.py:39
from urllib.parse import quote                     # verified: store.py:40
import aiosqlite                                   # verified: store.py:42
```

From TASK-3216, defined in this same module (no import statement needed):
```python
SQLitePragmaPolicy   # store.py, inserted after _SCHEMA_TABLES (line 240)
WikiStoreBusy        # store.py, same block
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):                                     # line 774
    _READONLY_ENV_CODES = frozenset({8, 264, 1544, 14})                   # line 811
    @classmethod
    def _is_readonly_env_error(cls, exc: sqlite3.OperationalError) -> bool:  # line 813

    def __init__(self, db_path: str | Path, wiki_name: str = "", *,
                 read_only: bool = False) -> None:                        # lines 759-765
        # body 766-794; ends with:
        #   self._wiki_name = wiki_name            # 791
        #   self._warned_read_only = False         # 792
        #   self._init_lock = asyncio.Lock()       # 793
        #   self.logger = logging.getLogger(__name__)   # 794   <- ANCHOR

    @property
    def db_path(self) -> Path:                                            # line 865
    @property
    def read_only(self) -> bool:                                          # line 870
    def _assert_writable(self) -> None:                                   # line 874

    @asynccontextmanager                                                  # line 887
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:      # line 888
    def _sidecars_quiescent(self) -> bool:                                # line 978
    @asynccontextmanager                                                  # line 1000
    async def _connect_immutable(self) -> AsyncIterator[aiosqlite.Connection]:  # line 1001
    @asynccontextmanager                                                  # line 1018
    async def _connect_readonly(self) -> AsyncIterator[aiosqlite.Connection]:   # line 1019
    def _log_read_only_once(self) -> None:                                # line 1093
    async def _migrate(self, conn: aiosqlite.Connection) -> None:         # line 1109

SCHEMA_VERSION = "3"                                                      # line 50  (bumped by PR #1381)
WIKI_TABLES_SQL = """..."""                                               # line 54 (`PRAGMA journal_mode = WAL;` at line 55)
WIKI_FTS_SQL = """..."""                                                  # line 172 (external-content FTS5 + sync triggers)
WIKI_SCHEMA_SQL = WIKI_TABLES_SQL + WIKI_FTS_SQL                          # line 216
_FTS_TRIGGERS = frozenset({...})   # 6 trigger names                      # line 221
_FTS_TABLES = ("pages_fts", "symbols_fts")                                # line 224
_SCHEMA_TABLES = frozenset({...})   # 8 names                             # line 240
```

Verified connection-open forms already used in this file:
```python
async with aiosqlite.connect(str(self._db_path)) as conn:                        # line 943
async with aiosqlite.connect(f"{base}?mode=ro", uri=True) as conn:               # line 1046
async with aiosqlite.connect(f"{base}?mode=ro&immutable=1", uri=True) as conn:   # line 1011
base = f"file:{quote(str(self._db_path))}"                                       # lines 942, 975
```

### Does NOT Exist

- ~~`SQLiteWikiStore._open` / `._read` / `._write` / `.checkpoint` / `.close`~~ — verified
  0 hits; this task creates the first three.
- ~~`PRAGMA busy_timeout` / `BEGIN IMMEDIATE` / `PRAGMA synchronous` /
  `journal_size_limit` / `wal_checkpoint`~~ — verified 0 hits anywhere in `store.py`. Only
  five PRAGMA occurrences exist, none of them yours: `PRAGMA journal_mode = WAL;`
  (line 55, inside `WIKI_TABLES_SQL`) and four `PRAGMA table_info(...)` probes
  (lines 1117, 1152 in a docstring, 1160, 1217 — in `_migrate`, `_migrate_fts` and
  `_uses_legacy_fts`).
- ~~`self.logger` inherited from `BaseWikiStore`~~ — **it is NOT.** `BaseWikiStore`
  (line 478) has no `__init__` and no logger at all. `self.logger` is assigned only at
  `store.py:862`, inside `SQLiteWikiStore.__init__`. Keep that assignment.
- ~~`aiosqlite.Connection.begin()`~~ — not used in this codebase; issue
  `await conn.execute("BEGIN IMMEDIATE")` instead.
- ~~a `slow` pytest marker~~ — `pytest.ini` registers only `integration`, `live`,
  `real_llm`. TASK-3226 adds `slow`; do not use it here.

---

## Implementation Blueprint

### Steps (in order)
1. Extend `__init__` with keyword-only `sqlite_policy` and `persistent_writer`, defaulting
   the policy to `SQLitePragmaPolicy()` — *why*: every caller that passes nothing must keep
   today's construction working and silently gain the 15 s default (AC-2).
2. Add `self._migrated = asyncio.Event()` beside the existing `_init_lock` — *why*: spec §2
   requires the migration latch to be per-store, not process-global, so two stores on
   different planes never suppress each other's migration.
3. Write `_open(writable=...)` as the ONLY place that calls `aiosqlite.connect` for the
   read-write path — *why*: centralizing it is the whole point of the policy layer; a
   second connect call site is how the timeout silently goes missing.
4. Pass `timeout=self._policy.busy_timeout_s` to `aiosqlite.connect` AND issue
   `PRAGMA busy_timeout` — *why*: the connect kwarg is what actually installs SQLite's
   busy handler, while the pragma is what `wikitoolkit status` can read back (AC-5). Both
   are required; neither substitutes for the other. The pragma takes MILLISECONDS.
5. Set `isolation_level=None` — *why*: it puts the driver in autocommit so `_write` owns
   `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` explicitly. Spec §7 forbids leaving implicit
   transaction boundaries anywhere this code owns a transaction.
6. Apply `journal_mode`/`synchronous`/`journal_size_limit` ONLY when `writable=True` —
   *why*: AC-4 requires the read-only ladder to apply no write-capable pragma; a `mode=ro`
   connection cannot change journal mode anyway and would error.
7. Gate mmap/cache/temp-store behind `self._policy.performance_pragmas` — *why*: AC-5 and
   the spec's non-goals; N agents must not each map excessive memory by default.
8. In `_write`, run `BEGIN IMMEDIATE` INSIDE a `try` that catches
   `sqlite3.OperationalError` and re-raises `WikiStoreBusy` only for `sqlite_errorcode` in
   `{5, 517}` — *why*: spec §7 says to test error CODES, not message substrings, and the
   spec is explicit that only the begin boundary maps to busy; a later statement error
   must keep its own semantics.
9. Commit exactly once on the success path and roll back on ANY exception — *why*: AC-3.
   Guard the rollback in its own `try/except` so a rollback failure never masks the
   original error.
10. Thread `timeout=` into `_connect_readonly`/`_connect_immutable`'s three
    `aiosqlite.connect` calls — *why*: AC-4 gives read-only planes the busy timeout (they
    still take SHARED locks against a live writer) while still writing nothing.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — part 1 of 3: `__init__`)

```python
# occurrences: 1 (verified: grep -c 'read_only: bool = False,$' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# REPLACE the signature at store.py:822-828 — add two keyword-only params after `read_only`:
    def __init__(
        self,
        db_path: str | Path,
        wiki_name: str = "",
        *,
        read_only: bool = False,
        sqlite_policy: SQLitePragmaPolicy | None = None,
        persistent_writer: bool = False,
    ) -> None:
```

```python
# occurrences: 1 (verified: grep -c 'self.logger = logging.getLogger(__name__)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `        self.logger = logging.getLogger(__name__)` (verified: store.py:862)
        self._policy = sqlite_policy or SQLitePragmaPolicy()
        self._persistent_writer = persistent_writer
        #: Latched once this store instance has proven the plane's schema
        #: is current, so later writes skip the migration probe entirely.
        #: Per-instance on purpose (spec §2): never process-global.
        self._migrated = asyncio.Event()
        self._writer_conn: Optional[aiosqlite.Connection] = None
```
**Why this shape**: `sqlite_policy=None` defaulting to `SQLitePragmaPolicy()` is what keeps
all ~28 existing construction sites source-compatible (AC-1) while giving them the bounded
15 s timeout. `persistent_writer` is accepted and stored now but stays inert — the spec
keeps connection-per-call as the default path, and `_writer_conn` is the slot a later
opt-in implementation would fill. Do NOT change the existing 766-794 body; the `mkdir` /
read-only / errno logic is load-bearing and separately tested.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — part 2 of 3: `_open`)

```python
# occurrences: 1 (verified: grep -c '    async def _connect(self)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# BEFORE — insert above the `@asynccontextmanager` (store.py:887) that decorates
#          `async def _connect(self)` (verified: store.py:888)

    async def _apply_pragmas(self, conn: aiosqlite.Connection, *, writable: bool) -> None:
        """Apply the policy's pragmas to a freshly opened connection.

        Args:
            conn: Connection to configure.
            writable: When False, only read-safe pragmas are issued — a
                read-only plane must never receive a write-capable
                pragma (AC-4).
        """
        # busy_timeout is read-safe: it only bounds how long THIS
        # connection waits for a lock. Milliseconds, not seconds.
        await conn.execute(f"PRAGMA busy_timeout = {int(self._policy.busy_timeout_s * 1000)}")
        if writable:
            await conn.execute("PRAGMA journal_mode = WAL")
            await conn.execute("PRAGMA synchronous = NORMAL")
            await conn.execute(f"PRAGMA journal_size_limit = {self._policy.journal_size_limit}")
        if self._policy.performance_pragmas:
            # FILL IN: issue the opt-in mmap_size / cache_size / temp_store
            # pragmas — bounded by AC-5 (these three, and ONLY with
            # performance_pragmas=True) and by spec §7 (temp_store and
            # cache_size are read-safe; keep any write-capable one under
            # `writable`).
            pass

    @asynccontextmanager
    async def _open(self, *, writable: bool) -> AsyncIterator[aiosqlite.Connection]:
        """Open one policy-configured connection to this plane.

        The single ``aiosqlite.connect`` call site for the read-write
        path: ``timeout=`` installs SQLite's busy handler, and
        ``isolation_level=None`` puts the driver in autocommit so that
        :meth:`_write` owns every transaction boundary explicitly.

        Args:
            writable: Whether write-capable pragmas may be applied.

        Yields:
            A configured connection.
        """
        async with aiosqlite.connect(
            str(self._db_path),
            timeout=self._policy.busy_timeout_s,
            isolation_level=None,
        ) as conn:
            conn.row_factory = aiosqlite.Row
            await self._apply_pragmas(conn, writable=writable)
            yield conn
```
**Why this shape**: `timeout=` and `PRAGMA busy_timeout` are BOTH required and are not
redundant — the kwarg installs the handler that actually makes a contended write wait, the
pragma is what `status` reads back for AC-5. `isolation_level=None` is what makes
`BEGIN IMMEDIATE` in `_write` meaningful rather than nested inside a driver-managed
deferred transaction. `_apply_pragmas` is split out so TASK-3225's `status` block and
TASK-3226's tests can assert the pragma set without duplicating the SQL.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — part 3 of 3: `_read` / `_write`)

```python
# Insert immediately AFTER the `_open` block above, still before `_connect`.

    @asynccontextmanager
    async def _read(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield a read-safe connection; never migrate, never write.

        The only route for pure reads. On an already-migrated plane this
        issues zero DML/DDL (AC-4). Preserves the existing read-only
        ladder: an explicitly read-only store, or a plane that turns out
        to be unwritable, degrades exactly as :meth:`_connect` does today.

        Yields:
            A connection safe to SELECT from.
        """
        if self._read_only:
            # FILL IN: reproduce the read-only branch of `_connect`
            # (store.py:908-938) VERBATIM — the quiescent-sidecar probe,
            # the immutable rung, the post-open re-check, and the
            # `_connect_readonly` fallback — bounded by AC-4 and by spec
            # §7 ("preserve the current read-only fallback's live-sidecar
            # safety checks"). Do not simplify it; it is separately
            # covered by tests/knowledge/wiki/test_store.py::
            # TestReadOnlyFallback and ::TestExplicitReadOnlyMode.
            raise NotImplementedError
        yielded = False
        try:
            async with self._open(writable=True) as conn:
                yielded = True
                yield conn
            return
        except sqlite3.OperationalError as exc:
            if yielded or not self._db_path.is_file() or not self._is_readonly_env_error(exc):
                raise
        async with self._connect_readonly() as conn:
            yield conn

    @asynccontextmanager
    async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:
        """Acquire ``BEGIN IMMEDIATE``, then commit or roll back exactly once.

        Args:
            operation: Logical name of the write, used in the error and
                in debug logs (e.g. ``"upsert_pages"``).

        Yields:
            A connection inside an open immediate transaction.

        Raises:
            WikiStoreBusy: The writer lock was not acquired within the
                configured busy timeout. Raised ONLY at the begin
                boundary.
            PermissionError: The store was opened read-only.
        """
        self._assert_writable()
        async with self._open(writable=True) as conn:
            if not self._migrated.is_set():
                async with self._init_lock:
                    if not self._migrated.is_set():
                        await self._migrate(conn)
                        self._migrated.set()
            try:
                await conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                # Codes, not message substrings (spec §7): 5 = SQLITE_BUSY,
                # 517 = SQLITE_BUSY_SNAPSHOT. Anything else is a real
                # error and keeps its own semantics.
                if getattr(exc, "sqlite_errorcode", None) in (5, 517):
                    raise WikiStoreBusy(
                        self._db_path, operation, self._policy.busy_timeout_s
                    ) from exc
                raise
            try:
                yield conn
            except BaseException:
                try:
                    await conn.execute("ROLLBACK")
                except sqlite3.Error:  # pragma: no cover - rollback best effort
                    self.logger.debug("rollback failed after %s", operation, exc_info=True)
                raise
            await conn.execute("COMMIT")
```
**Why this shape**: `_write` is the ONLY place `BEGIN IMMEDIATE` appears, so the writer
reservation is taken before any read in the transaction — that is what removes the
read-to-write upgrade contention that produces `SQLITE_BUSY_SNAPSHOT` (spec §7). The
double-checked `_migrated` latch under the existing `_init_lock` means migration runs at
most once per store instance without a process-global. `except BaseException` (not
`Exception`) ensures a cancelled task still rolls back. `COMMIT` sits outside the try so a
commit failure is never swallowed as a rollback. The `operation` string is required, not
optional — it is what makes `WikiStoreBusy` actionable (AC-3).

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — read-only ladder timeout)

```python
# occurrences: 2 (verified: grep -c 'mode=ro&immutable=1' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# FILL IN: disambiguate — there are THREE `aiosqlite.connect(f"{base}...` calls in the
# read-only ladder (store.py:1011 in `_connect_immutable`, store.py:1046 and store.py:1084
# in `_connect_readonly`). Add `timeout=self._policy.busy_timeout_s` to EACH, quoting 2-3
# lines of surrounding context per edit to make each anchor unique. Do NOT add
# `isolation_level` and do NOT call `_apply_pragmas(writable=True)` on any of them —
# bounded by AC-4 (read-only ladder gets the timeout and nothing write-capable).
```
**Why**: a `mode=ro` reader still takes SHARED locks and can be blocked by a writer's
EXCLUSIVE phase, so it benefits from the bounded wait; but issuing `journal_mode` or
`synchronous` on it would fail or mutate a foreign plane, which AC-4 forbids.

### `tests/knowledge/wiki/test_store_concurrency.py` (CREATE)

```python
"""FEAT-557 — SQLite connection-policy and transaction tests.

Lives beside ``test_store.py`` (the store's real suite); the
``packages/ai-parrot/tests/knowledge/wiki/`` tree holds only CLI/MCP/Jira
tests and no store coverage.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki.store import (
    SQLitePragmaPolicy,
    SQLiteWikiStore,
    WikiStoreBusy,
)


@pytest.fixture
async def store(tmp_path: Path) -> SQLiteWikiStore:
    """A built, current-schema SQLite plane."""
    plane = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")
    # Force schema creation + migration once so tests start migrated.
    await plane.stats()
    return plane


class TestOpenPolicy:
    async def test_busy_timeout_pragma_is_applied(self, store: SQLiteWikiStore) -> None:
        """PRAGMA busy_timeout reflects the policy, in milliseconds (AC-5)."""
        async with store._open(writable=True) as conn:
            cur = await conn.execute("PRAGMA busy_timeout")
            assert (await cur.fetchone())[0] == 15_000

    async def test_write_pragmas_only_on_writable_open(self, tmp_path: Path) -> None:
        """A read-only open issues no write-capable pragma (AC-4)."""
        # FILL IN: assert `synchronous` / `journal_size_limit` are NOT set by a
        # `writable=False` open — bounded by AC-4.


class TestWriteTransaction:
    async def test_write_begins_immediate_and_commits(self, store: SQLiteWikiStore) -> None:
        """The happy path opens an immediate transaction and commits once."""
        # FILL IN: assert `sqlite3` sees the row after the context exits —
        # bounded by AC-3.

    async def test_failed_body_rolls_back(self, store: SQLiteWikiStore) -> None:
        """An exception inside the body leaves no row behind (AC-3)."""
        # FILL IN: raise inside `async with store._write("t")`, assert the row is
        # absent and the original exception propagates unchanged — bounded by AC-3.

    async def test_busy_at_begin_raises_wiki_store_busy(self, tmp_path: Path) -> None:
        """A held peer writer surfaces as a typed, actionable error (AC-3)."""
        # FILL IN: open a second stdlib `sqlite3` connection, run `BEGIN IMMEDIATE`
        # on it to hold the reservation, then assert `_write` on a store built with
        # `SQLitePragmaPolicy(busy_timeout_s=1.0)` raises `WikiStoreBusy` carrying
        # db_path / operation / waited_seconds — bounded by AC-3. Use a SHORT
        # timeout so the test stays fast.

    async def test_non_busy_error_keeps_its_semantics(self, store: SQLiteWikiStore) -> None:
        """A non-busy OperationalError is NOT converted to WikiStoreBusy (AC-3)."""
        # FILL IN: bounded by AC-3 ("ordinary statement, read-only, disk and I/O
        # errors retain their existing semantics").
```
**Why**: `asyncio_mode = auto` is set in the root `pytest.ini`, so `async def` tests and
async fixtures need no decorator. Touching `_open`/`_write` directly is deliberate — this
task changes no public method, so the private primitives are the only surface to test
until TASK-3219 migrates the call sites.

### FILL IN checklist
- [ ] `_apply_pragmas` — the three opt-in performance pragmas; bounded by AC-5.
- [ ] `_read` — verbatim reproduction of `_connect`'s read-only branch (store.py:908-938);
      bounded by AC-4 and spec §7.
- [ ] read-only ladder — add `timeout=` to all three `aiosqlite.connect` calls
      (store.py:1011, 978, 1016), disambiguating each anchor; bounded by AC-4.
- [ ] `test_write_pragmas_only_on_writable_open`; bounded by AC-4.
- [ ] `test_write_begins_immediate_and_commits`; bounded by AC-3.
- [ ] `test_failed_body_rolls_back`; bounded by AC-3.
- [ ] `test_busy_at_begin_raises_wiki_store_busy`; bounded by AC-3.
- [ ] `test_non_busy_error_keeps_its_semantics`; bounded by AC-3.

---

## Acceptance Criteria

- [ ] `SQLiteWikiStore(path)` still constructs with no policy argument and gets
      `busy_timeout_s == 15.0`.
- [ ] `SQLiteWikiStore(path, sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=2.0))` applies
      `PRAGMA busy_timeout = 2000`.
- [ ] `_write()` issues `BEGIN IMMEDIATE` before any caller statement, commits once on
      success, rolls back on exception.
- [ ] A contended `BEGIN IMMEDIATE` raises `WikiStoreBusy` carrying `db_path`,
      `operation`, `waited_seconds`; a non-busy `OperationalError` propagates unchanged.
- [ ] `_read()` on a migrated plane issues no DML/DDL.
- [ ] The read-only ladder receives the busy timeout but no write-capable pragma.
- [ ] `_connect()` still exists and behaves exactly as before (TASK-3219 removes it).
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_store_concurrency.py -v`
- [ ] No regression:
      `pytest tests/knowledge/wiki/test_store.py tests/knowledge/wiki/test_store_migration_v2.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/store.py tests/knowledge/wiki/test_store_concurrency.py`

---

## Test Specification

See the blueprint's `test_store_concurrency.py` block. TASK-3226 extends this same file
with the multiprocess contention test and the read-path SQL trace.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Overview/Data Models, §3 Module 1, §7 Patterns & Gotchas.
2. **Check dependencies** — TASK-3216 must be in `sdd/tasks/completed/`;
   `SQLitePragmaPolicy` and `WikiStoreBusy` must already be importable from `store.py`.
3. **Verify the Codebase Contract** — re-check that `_connect` is still at store.py:888,
   `self.logger = ...` at 794, and the three `aiosqlite.connect` ladder calls at 943/978/
   1016. If they moved, update this contract FIRST.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion — especially that `_connect` still works.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update** `sdd/tasks/index/wikitoolkit-sqlite-optimizations.json` → `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
