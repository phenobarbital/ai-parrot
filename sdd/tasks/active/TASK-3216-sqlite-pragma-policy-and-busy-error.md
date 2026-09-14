# TASK-3216: SQLitePragmaPolicy model and WikiStoreBusy typed error

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the dependency root of FEAT-557 (spec §3 Module 1). Every other task in this
feature imports either `SQLitePragmaPolicy` (the validated connection policy) or
`WikiStoreBusy` (the typed busy error). Landing them first, with zero behaviour change,
lets M2/M3/M4 proceed against stable names.

Today `SQLiteWikiStore` opens connections with SQLite's implicit default timeout and has
no typed error for an exhausted writer wait — callers see a raw
`sqlite3.OperationalError: database is locked`.

---

## Scope

- Add the `SQLitePragmaPolicy` Pydantic model to `store.py` with the exact field set and
  bounds fixed by spec §2 "Data Models".
- Add the `WikiStoreBusy` exception subclassing `sqlite3.OperationalError`, carrying
  `db_path`, `operation`, and `waited_seconds`.
- Add a unit test module covering policy defaults, bound validation, and the error's
  attributes/message.

**NOT in scope**: wiring the policy into `SQLiteWikiStore.__init__` (TASK-3217), any
`_open`/`_read`/`_write` method, pragma execution, `BEGIN IMMEDIATE`, migration changes,
`checkpoint()`, config fields (TASK-3222), or any call-site plumbing. After this task the
two new symbols exist and are tested but nothing constructs them yet.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Add `SQLitePragmaPolicy` + `WikiStoreBusy` after the schema constants |
| `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_policy.py` | CREATE | Unit tests for both new symbols |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Everything this task needs is ALREADY imported at the top of `store.py`. Add no new imports.

```python
import sqlite3                                    # verified: store.py:33
from pathlib import Path                          # verified: store.py:38
from pydantic import BaseModel, Field             # verified: store.py:43
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "3"                              # line 50  (bumped to "3" by PR #1381)
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]] = {...}   # line 229
_SCHEMA_TABLES = frozenset({...})                 # line 240  <- insertion anchor
_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)    # line 242

class SQLiteWikiStore(BaseWikiStore):             # line 774  (NOT modified by this task)
```

### Does NOT Exist

- ~~`SQLitePragmaPolicy`~~ — no policy model exists anywhere in the repo today.
- ~~`WikiStoreBusy`~~ — no typed SQLite busy exception exists today.
- ~~`parrot.knowledge.wiki.policy`~~ — there is no separate policy module; both symbols
  go in `store.py` beside the other module-level constants.
- ~~`packages/ai-parrot/tests/knowledge/wiki/test_store.py`~~ — does not exist; do not
  try to add to it.
- ~~a `slow` pytest marker~~ — not registered yet (TASK-3226 adds it). Do not use it here.

---

## Implementation Blueprint

### Steps (in order)
1. Insert both new symbols immediately AFTER the `_SCHEMA_TABLES` line and BEFORE
   `_FTS_TOKEN_RE` — *why*: they are module-level policy constants/types that belong with
   the other schema/connection constants, and placing them above `SQLiteWikiStore`
   (line 774) guarantees they are defined before the class body that will reference them
   in TASK-3217.
2. Give `busy_timeout_s` the bounds `ge=1.0, le=120.0` — *why*: AC-2 requires the config
   to reject a timeout below 1 or above 120 seconds, and validating on the policy model
   means every construction path inherits the check for free.
3. Make `WikiStoreBusy` subclass `sqlite3.OperationalError`, not `Exception` — *why*: the
   spec requires existing `except sqlite3.OperationalError` handlers across the CLI and
   federation ladder to keep catching it, so this must remain substitutable.
4. Build the message in `__init__` and pass it to `super().__init__` — *why*: the error is
   surfaced to CLI users and MCP tools, so it must be actionable on its own (AC-3), naming
   the plane, the operation and how long it waited.
5. Write the tests and run them — *why*: this task's whole value is that later tasks can
   trust these bounds and attributes.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '^_SCHEMA_TABLES = frozenset' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `_SCHEMA_TABLES = frozenset({"meta", "sources", "pages", "edges", "pages_fts", "embeddings", "symbols", "symbols_fts"})` (verified: store.py:240)


class SQLitePragmaPolicy(BaseModel):
    """Validated SQLite connection policy for one wiki plane.

    Attributes:
        busy_timeout_s: Seconds a connection waits for the writer lock
            before SQLite gives up. Installed both as the connect-time
            ``timeout=`` (which registers the busy handler) and as
            ``PRAGMA busy_timeout`` (which makes the setting readable
            back for diagnostics).
        performance_pragmas: Opt-in memory-oriented tuning (mmap, cache,
            temp-store). Off by default so that N concurrent agents do
            not each map excessive memory.
        journal_size_limit: Bytes of WAL retained after a successful
            checkpoint. Defaults to 64 MiB.
    """

    busy_timeout_s: float = Field(default=15.0, ge=1.0, le=120.0)
    performance_pragmas: bool = False
    journal_size_limit: int = Field(default=67_108_864, ge=0)


class WikiStoreBusy(sqlite3.OperationalError):
    """Writer lock was not acquired within the configured busy timeout.

    Subclasses :class:`sqlite3.OperationalError` so existing handlers
    keep working; raised ONLY at the ``BEGIN IMMEDIATE`` boundary, never
    for an arbitrary later statement error.

    Attributes:
        db_path: Plane whose writer lock was contended.
        operation: Logical write operation that was waiting.
        waited_seconds: Configured busy timeout that was exhausted.
    """

    def __init__(self, db_path: Path, operation: str, waited_seconds: float) -> None:
        self.db_path = db_path
        self.operation = operation
        self.waited_seconds = waited_seconds
        super().__init__(
            f"wiki plane {db_path} is busy: could not acquire the SQLite writer "
            f"lock for {operation!r} within {waited_seconds:g}s. Another build, "
            f"ingest or agent write is holding it; retry, or raise "
            f"sqlite_busy_timeout in .parrot/wiki.json."
        )
```
**Why this shape**: `SQLitePragmaPolicy` is the single object every later task passes
around, so its field names are fixed by spec §2 and are NOT renegotiable — TASK-3217,
3221, 3222 and 3223 all reference `busy_timeout_s` / `performance_pragmas` /
`journal_size_limit` verbatim. `WikiStoreBusy` stores its three attributes BEFORE calling
`super().__init__` so they are set even if message formatting is later changed. Do not
make `WikiStoreBusy` a Pydantic model and do not add a `sqlite_errorcode` — it is raised
by our code, not by the driver.

### `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_policy.py` (CREATE)

```python
"""Unit tests for the FEAT-557 SQLite connection policy primitives."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy


class TestSQLitePragmaPolicy:
    def test_defaults(self) -> None:
        """Policy defaults match the spec: 15s, opt-in pragmas, 64 MiB WAL cap."""
        policy = SQLitePragmaPolicy()
        assert policy.busy_timeout_s == 15.0
        assert policy.performance_pragmas is False
        assert policy.journal_size_limit == 67_108_864

    @pytest.mark.parametrize("value", [0.0, 0.999, 120.001, -5.0])
    def test_rejects_out_of_range_timeout(self, value: float) -> None:
        """Timeout is validated to the inclusive 1-120 second window (AC-2)."""
        with pytest.raises(ValidationError):
            SQLitePragmaPolicy(busy_timeout_s=value)

    @pytest.mark.parametrize("value", [1.0, 15.0, 120.0])
    def test_accepts_boundary_timeouts(self, value: float) -> None:
        """Both bounds are inclusive."""
        assert SQLitePragmaPolicy(busy_timeout_s=value).busy_timeout_s == value


class TestWikiStoreBusy:
    def test_is_an_operational_error(self) -> None:
        """Existing `except sqlite3.OperationalError` handlers still catch it."""
        assert issubclass(WikiStoreBusy, sqlite3.OperationalError)

    def test_carries_actionable_attributes(self) -> None:
        """Path, operation and waited seconds are addressable and in the message."""
        exc = WikiStoreBusy(Path("/tmp/wiki.db"), "upsert_pages", 15.0)
        assert exc.db_path == Path("/tmp/wiki.db")
        assert exc.operation == "upsert_pages"
        assert exc.waited_seconds == 15.0
        # FILL IN: assert the rendered message names the plane, the operation and
        # the timeout — bounded by AC-3 (the error must be actionable on its own).
```
**Why**: `asyncio_mode = "auto"` is set in `packages/ai-parrot/pyproject.toml`, so async
tests need no decorator — but every test here is synchronous anyway. Import both symbols
from `parrot.knowledge.wiki.store`; they are NOT re-exported from the package `__init__`.

### FILL IN checklist
- [ ] `test_sqlite_policy.py::TestWikiStoreBusy.test_carries_actionable_attributes` —
      assert on the message text; bounded by AC-3.

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy` works.
- [ ] `SQLitePragmaPolicy()` yields `busy_timeout_s=15.0`, `performance_pragmas=False`,
      `journal_size_limit=67108864`.
- [ ] `SQLitePragmaPolicy(busy_timeout_s=0.5)` and `(busy_timeout_s=121)` both raise
      `pydantic.ValidationError`; `1.0` and `120.0` are accepted.
- [ ] `issubclass(WikiStoreBusy, sqlite3.OperationalError)` is `True`.
- [ ] No behaviour change: `SQLiteWikiStore` is untouched by this task.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_policy.py -v`
- [ ] Existing suite still green:
      `pytest packages/ai-parrot/tests/knowledge/wiki/ -q`
- [ ] No linting errors:
      `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/store.py packages/ai-parrot/tests/knowledge/wiki/test_sqlite_policy.py`

---

## Test Specification

See the blueprint above — `test_sqlite_policy.py` is the complete scaffold. The only gap
is the message assertion marked `FILL IN`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Data Models, §3 M1).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `_SCHEMA_TABLES` is still at store.py:240
   and that `BaseModel, Field` are still imported at line 42. If they moved, update this
   contract FIRST, then implement.
4. **Implement** from the blueprint; complete the single `FILL IN`.
5. **Verify** every acceptance criterion.
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
