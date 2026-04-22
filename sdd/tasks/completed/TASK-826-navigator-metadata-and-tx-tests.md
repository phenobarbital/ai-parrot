# TASK-826: Regression tests for `_build_table_metadata` + `transaction()` overrides

**Feature**: FEAT-117 — Navigator Toolkit asyncdb Connection Unwrap
**Spec**: `sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-824, TASK-825
**Assigned-to**: unassigned

---

## Context

TASK-824 and TASK-825 were shipped during a live-debug cycle without
tests to unblock production. This task backfills regression coverage
so that:

1. A future refactor (e.g. when FEAT-118 lands and these overrides
   become redundant) cannot silently revert the behaviour.
2. Both overrides' contracts are explicitly asserted:
   - `_build_table_metadata` runs the three introspection queries
     with positional `$1 / $2` parameters via raw asyncpg, producing
     a populated `TableMetadata`.
   - `transaction()` uses `asyncpg.Connection.transaction()` natively
     and yields the raw conn (the asyncdb wrapper's broken
     `transaction()` must never be invoked — wrapper stub raises if
     called).

Implements **Module 5** of the v0.4 spec.

---

## Scope

Create `tests/unit/test_navigator_toolkit_metadata_and_tx.py` with:

1. Stub classes mirroring the asyncdb wrapper / raw asyncpg contract
   (same pattern as `test_navigator_toolkit_run_on_conn.py`).
2. Fixture that monkeypatches `_acquire_asyncdb_connection` on a
   `NavigatorToolkit` instance so we can inject controlled stubs
   without hitting a real database.
3. Tests for `_build_table_metadata`:
   - Populates columns from `information_schema.columns` query.
   - Populates primary keys.
   - Groups unique constraints correctly.
   - Returns `None` on empty columns (table not found).
   - Passes `$1 / $2` as schema + table positional params.
4. Tests for `transaction()`:
   - Enters and exits cleanly; yields the raw asyncpg connection.
   - Wrapper's broken `transaction()` is never called.
   - Nested calls raise `RuntimeError` ("Nested transactions not supported").
   - `_in_transaction` flag is reset on normal exit AND on exception.

**NOT in scope**:
- Integration tests against a live DB (optional, gated).
- Any change to the overrides themselves (done in TASK-824/798).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/test_navigator_toolkit_metadata_and_tx.py` | CREATE | New regression test module. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Same pattern as tests/unit/test_navigator_toolkit_run_on_conn.py:14-31
import os, sys
from conftest_db import setup_worktree_imports   # tests/unit/conftest_db.py
import pytest
from parrot_tools.navigator.toolkit import NavigatorToolkit
from parrot.bots.database.models import TableMetadata
```

### Signatures to test

```python
NavigatorToolkit._build_table_metadata(schema, table, table_type, comment=None) -> Optional[TableMetadata]
NavigatorToolkit.transaction() -> AsyncContextManager[Any]
```

### Does NOT Exist

- ~~`NavigatorToolkit._test_override_conn` helper~~ — stubs are
  injected via `monkeypatch.setattr` on `_acquire_asyncdb_connection`.
- ~~A shared `conftest_fixtures.py`~~ — fixtures are defined per
  test file.

---

## Implementation Notes

Key design: monkeypatch `_acquire_asyncdb_connection` to return an
async context manager that yields a fake asyncdb wrapper. The
wrapper exposes `engine()` → raw stub; wrapper's own `transaction()` /
`fetch()` raise `AssertionError` if called (so we *prove* the
override uses the raw path).

For `_build_table_metadata`, the raw stub's `fetch` returns canned
rows per query (matched by SQL substring match for robustness:
`"information_schema.columns"` → columns; `"PRIMARY KEY"` → PKs;
`"'UNIQUE'"` → UNIQUEs).

For `transaction()`, the raw stub's `transaction()` returns a
proper async context manager (an `@asynccontextmanager` no-op).

---

## Acceptance Criteria

- [ ] File `tests/unit/test_navigator_toolkit_metadata_and_tx.py` exists.
- [ ] `pytest tests/unit/test_navigator_toolkit_metadata_and_tx.py -v`
      passes with all tests green.
- [ ] Existing tests continue to pass (20/20 from TASK-823 + refactor).
- [ ] Reuses `conftest_db.py` (no new conftest).
- [ ] No changes under `packages/ai-parrot/` or
      `packages/ai-parrot-tools/src/parrot_tools/`.

---

## Agent Instructions

1. Read the spec at `sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md`.
2. Verify TASK-824 + TASK-825 are `done` in the index.
3. Verify the overrides exist:
   `grep -nE "def _build_table_metadata|def transaction" packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
   → expect two hits on the `NavigatorToolkit` class.
4. Update `.index.json` → this task to `in-progress`.
5. Create the test file following the pattern.
6. Run `pytest tests/unit/test_navigator_toolkit_metadata_and_tx.py -v`.
7. Verify acceptance criteria.
8. Move task file to `completed/`, update index to `done`.
9. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (Opus 4.7)
**Date**: 2026-04-22
**Commits**: `b93644f0` (worktree), merged to dev.

**Notes**:
- 11 tests created, 11 passing.
- Stub classes `_RawAsyncpgStub` + `_AsyncdbWrapperStub` mirror the
  exact shape boundary: wrapper's `transaction()` is `async def`
  (coroutine, not CM); raw's is a sync-returned async CM.
- Monkeypatched `_acquire_asyncdb_connection` at the instance level
  via `__get__` binding to keep tests isolated.
- For `_build_table_metadata` tests, SQL substring matching
  (`information_schema.columns`, `'PRIMARY KEY'`, `'UNIQUE'`) makes
  the stub robust to minor SQL formatting changes in the override.

**Deviations from spec**: none.
