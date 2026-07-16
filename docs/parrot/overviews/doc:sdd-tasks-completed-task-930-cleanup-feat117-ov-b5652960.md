---
type: Wiki Overview
title: 'TASK-930: Remove FEAT-117 Override + Final Tests + Dep Audit'
id: doc:sdd-tasks-completed-task-930-cleanup-feat117-override-tests-deps-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 5 of the spec — the final cleanup after all framework-level
relates_to:
- concept: mod:parrot_tools.navigator.toolkit
  rel: mentions
---

# TASK-930: Remove FEAT-117 Override + Final Tests + Dep Audit

**Feature**: FEAT-118 — Database Toolkit asyncpg Native Boundary Refactor
**Spec**: `sdd/specs/database-toolkit-asyncpg-boundary-refactor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-926, TASK-927, TASK-928, TASK-929
**Assigned-to**: unassigned

---

## Context

Implements Module 5 of the spec — the final cleanup after all framework-level
fixes have landed. With the boundary unwrap (TASK-926), SQLAlchemy removal
(TASK-927), param normalisation (TASK-928), and transaction rewrite (TASK-929)
complete, the NavigatorToolkit workarounds from FEAT-117 are redundant.

This task also removes the NavigatorToolkit `_build_table_metadata` override
(which was a local fix for the params-ignored bug D2), adds final integration
tests, and audits the SQLAlchemy dependency in `pyproject.toml`.

---

## Scope

- Delete `NavigatorToolkit._run_on_conn` override in
  `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`.
- Delete `NavigatorToolkit._build_table_metadata` override (local D2 workaround).
- Verify NavigatorToolkit now inherits parent methods correctly.
- Write test asserting `NavigatorToolkit.__dict__` does NOT contain
  `_run_on_conn` (inherits from parent).
- Audit `pyproject.toml` for `sqlalchemy` runtime dependency — move to
  optional extras or remove entirely.
- Run full test suite to confirm no regressions.

**NOT in scope**: boundary unwrap (TASK-926), SQLAlchemy deletion (TASK-927),
query params (TASK-928), transaction rewrite (TASK-929).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Delete `_run_on_conn` and `_build_table_metadata` overrides |
| `tests/unit/bots/database/toolkits/test_navigator_no_override.py` | CREATE | Assert no local override |
| `pyproject.toml` | MODIFY | Audit sqlalchemy dependency |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures to Delete

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py:184-215
@staticmethod
async def _run_on_conn(sql, args, returning, conn, single_row):
    """Navigator-local override — unwrap asyncdb ``pg`` wrapper to raw asyncpg.
    ...
    TEMPORARY — remove when FEAT-118 lands ...
    """
    raw = conn.engine() if hasattr(conn, "engine") and callable(conn.engine) else conn
    if not returning:
        await raw.execute(sql, *args)
        return {"status": "ok"}
    if single_row:
        row = await raw.fetchrow(sql, *args)
        return dict(row) if row else {}
    rows = await raw.fetch(sql, *args)
    return [dict(r) for r in rows] if rows else []

# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py:217+
async def _build_table_metadata(
    self,
    schema: str,
    table: str,
    table_type: str,
    comment: Optional[str] = None,
) -> Optional[TableMetadata]:
    """Navigator-local override — build TableMetadata via raw asyncpg + ``$N`` params.
    ...
    """
    # This entire method is a D2 workaround — parent now handles params correctly
```

### Parent Signatures (what Navigator will inherit)

```python
# After TASK-926 — postgres.py:807-824 (simplified _run_on_conn):
@staticmethod
async def _run_on_conn(sql, args, returning, conn, single_row):
    # conn is now raw asyncpg.Connection — works correctly
    ...

# After TASK-928 — sql.py:581+ (_build_table_metadata):
async def _build_table_metadata(self, schema, table, table_type, comment=None):
    # Now passes params to _execute_asyncdb — works correctly
    ...
```

### Does NOT Exist
- ~~`NavigatorToolkit._run_on_conn` after deletion~~ — inherits from PostgresToolkit
- ~~`NavigatorToolkit._build_table_metadata` after deletion~~ — inherits from SQLToolkit
- ~~Keeping overrides "for safety"~~ — they become wrong after the parent is fixed

---

## Implementation Notes

### Deletion Checklist
1. Open `navigator/toolkit.py`.
2. Delete the `_run_on_conn` static method (lines ~184-215).
3. Delete the `_build_table_metadata` method (lines ~217+).
4. Remove any imports that were only used by these deleted methods.
5. Verify no other method in NavigatorToolkit references `_run_on_conn` or
   `_build_table_metadata` locally.

### pyproject.toml Audit
Search for `sqlalchemy` in dependencies:
```bash
grep -n sqlalchemy pyproject.toml
```
If it's a runtime dependency, either:
- Move to `[project.optional-dependencies]` under an `sqlalchemy` extra.
- Remove entirely if no other code uses it.

### Key Constraints
- NavigatorToolkit has many other methods — only delete the two overrides.
- The `_build_table_metadata` override may be large (it reimplements the
  full metadata query with `$N` params). All of it goes — the parent now
  does this correctly.

---

## Acceptance Criteria

- [ ] `NavigatorToolkit.__dict__` does NOT contain `_run_on_conn`
- [ ] `NavigatorToolkit.__dict__` does NOT contain `_build_table_metadata`
- [ ] `test_navigator_toolkit_no_local_override` passes
- [ ] `sqlalchemy` audited in `pyproject.toml` (moved to optional or removed)
- [ ] Full test suite passes with no regressions
- [ ] NavigatorToolkit CRUD operations work via inherited parent methods

---

## Test Specification

```python
# tests/unit/bots/database/toolkits/test_navigator_no_override.py
import pytest


def test_navigator_toolkit_no_run_on_conn_override():
    """NavigatorToolkit must NOT have a local _run_on_conn."""
    from parrot_tools.navigator.toolkit import NavigatorToolkit
    assert "_run_on_conn" not in NavigatorToolkit.__dict__, (
        "NavigatorToolkit still has a local _run_on_conn override — "
        "it should inherit from PostgresToolkit after FEAT-118"
    )


def test_navigator_toolkit_no_build_table_metadata_override():
    """NavigatorToolkit must NOT have a local _build_table_metadata."""
    from parrot_tools.navigator.toolkit import NavigatorToolkit
    assert "_build_table_metadata" not in NavigatorToolkit.__dict__, (
        "NavigatorToolkit still has a local _build_table_metadata override — "
        "it should inherit from SQLToolkit after FEAT-118"
    )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-926, TASK-927, TASK-928, TASK-929
   are ALL in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm override methods exist at
   the listed locations in `navigator/toolkit.py`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** — delete overrides, audit pyproject.toml
6. **Run full test suite** — `pytest tests/ -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-930-cleanup-feat117-override-tests-deps.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-29
**Notes**: Deleted `_run_on_conn`, `_build_table_metadata`, and `transaction` overrides
from NavigatorToolkit — all three were FEAT-117 workarounds marked "TEMPORARY —
remove when FEAT-118 lands". `_run_on_conn` and `_build_table_metadata` were in spec
scope; `transaction` was also deleted because it referenced `self._in_transaction` which
was removed from PostgresToolkit in TASK-929, making it broken code.
Removed `asynccontextmanager` / `AsyncIterator` imports (only used by `transaction`).
pyproject.toml audit: SQLAlchemy is NOT a listed dependency in any package's
pyproject.toml — it's used by other unrelated modules (vectorstores, catalog) but
not the database toolkit layer. No changes needed.
Created `test_navigator_no_override.py` with 6 tests confirming overrides are gone.
Deleted two stale FEAT-117 test files (`test_navigator_toolkit_run_on_conn.py`,
`test_navigator_toolkit_metadata_and_tx.py`). Also fixed `test_table_metadata_unique.py`
(TASK-928 collateral: params became tuple) and `test_toolkit_variants.py` (tool_prefix
`any()` pattern). Full suite: 300 tests passing.

**Deviations from spec**: Also deleted NavigatorToolkit.transaction() override (not
listed in task scope but was a FEAT-117 workaround that referenced removed _in_transaction
attribute — leaving it would have caused runtime AttributeError).
