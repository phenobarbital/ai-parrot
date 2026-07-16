---
type: Wiki Overview
title: 'TASK-1031: Unit tests for `PostgresFormStorage.list_forms()` enriched output'
id: doc:sdd-tasks-completed-task-1031-postgres-list-forms-unit-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: There is no existing unit-test file for `PostgresFormStorage`
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1031: Unit tests for `PostgresFormStorage.list_forms()` enriched output

**Feature**: FEAT-148 — Enriched List of Created Forms in parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-list-created-forms.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1030
**Assigned-to**: unassigned

---

## Context

There is no existing unit-test file for `PostgresFormStorage`
(its current coverage is integration-only). After TASK-1030 widens
`list_forms()` to project `created_at` and `description`, we add a
dedicated unit-test file using stubbed pool/connection objects so the
new behaviour is verified without a real PostgreSQL.

Implements Module 6 of the spec.

---

## Scope

- Create `packages/parrot-formdesigner/tests/unit/test_storage_list.py`.
- Build a minimal in-memory stub for `asyncpg.Pool` / `Connection` that
  supports `pool.acquire()` as an async context manager and
  `conn.fetch(sql)` returning a list of `dict`-like rows.
- Cover:
  - Single row with localized title (dict) and string description →
    flattened correctly.
  - Single row with `description=None` and `description` missing →
    both produce `entry["description"] is None`.
  - Single row with `created_at` set → ISO-8601 string in result.
  - Single row with `created_at=None` (defensive case) → `None` in result.
  - Multiple rows → all returned in iteration order.
  - Malformed `schema_json` → falls back to `title=""`, `description=None`
    (preserves existing behaviour).
- Add the lightweight contract test from TASK-1029
  (`test_form_storage_list_forms_docstring_contract`) here.

**NOT in scope**:
- Real PostgreSQL integration tests (covered elsewhere; not required
  for this feature).
- Testing `save()`, `load()`, or `delete()`.
- Testing `FormSchema.created_at` (TASK-1033 covers it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_storage_list.py` | CREATE | New unit-test file with stubbed pool |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test imports
import json
from datetime import datetime, timezone

import pytest

from parrot.formdesigner.services.storage import PostgresFormStorage
from parrot.formdesigner.services.registry import FormStorage
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/__init__.py exports both
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py
class PostgresFormStorage(FormStorage):                   # line 39
    def __init__(self, pool: Any) -> None: ...            # line 106
    async def list_forms(self) -> list[dict[str, str]]: ...  # line 213
```

`pool` is duck-typed (`Any`) — only `pool.acquire()` is used. No need
to depend on `asyncpg`.

### Does NOT Exist

- ~~`pytest_asyncpg`~~ — not a dependency; do not import it.
- ~~`asyncpg.Pool` real instance for unit tests~~ — out of scope.
- ~~`pytest.fixture(scope="session")`~~ for the stub — keep it function-scoped.

---

## Implementation Notes

### Stub pattern

```python
class _StubRow(dict):
    """asyncpg.Record duck-type — supports row['key'] indexing."""

class _StubConn:
    def __init__(self, rows): self._rows = rows
    async def fetch(self, sql): return list(self._rows)
    async def execute(self, sql): return "EXECUTE 0"
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): return False

class _StubAcquireCtx:
    def __init__(self, conn): self._conn = conn
    async def __aenter__(self): return self._conn
    async def __aexit__(self, *a): return False

class _StubPool:
    def __init__(self, rows): self._conn = _StubConn(rows)
    def acquire(self): return _StubAcquireCtx(self._conn)
```

### Test cases

```python
@pytest.fixture
def storage_factory():
    def make(rows):
        return PostgresFormStorage(pool=_StubPool(rows))
    return make


@pytest.mark.asyncio
async def test_list_forms_localized_title_flattens(storage_factory):
    rows = [_StubRow(
        form_id="f-1", version="1.0",
        schema_json=json.dumps({"title": {"en": "Hello", "es": "Hola"},
                                "description": "Daily report"}),
        created_at=datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc),
    )]
    out = await storage_factory(rows).list_forms()
    assert out == [{
        "form_id": "f-1",
        "version": "1.0",
        "title": "Hello",
        "description": "Daily report",
        "created_at": "2026-04-12T10:31:00+00:00",
    }]


@pytest.mark.asyncio
async def test_list_forms_description_missing_or_none(storage_factory):
    rows = [
        _StubRow(form_id="a", version="1.0",
                 schema_json=json.dumps({"title": "A"}),
                 created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                 updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _StubRow(form_id="b", version="1.0",
                 schema_json=json.dumps({"title": "B", "description": None}),
                 created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                 updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ]
    out = await storage_factory(rows).list_forms()
    assert out[0]["description"] is None
    assert out[1]["description"] is None


@pytest.mark.asyncio
async def test_list_forms_created_at_none_defensive(storage_factory):
    rows = [_StubRow(
        form_id="x", version="1.0",
        schema_json=json.dumps({"title": "X"}),
        created_at=None,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )]
    out = await storage_factory(rows).list_forms()
    assert out[0]["created_at"] is None


@pytest.mark.asyncio
async def test_list_forms_malformed_schema_json(storage_factory):
    rows = [_StubRow(
        form_id="bad", version="1.0",
        schema_json="not-json",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )]
    out = await storage_factory(rows).list_forms()
    assert out[0]["title"] == ""
    assert out[0]["description"] is None
    assert out[0]["created_at"] == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_list_forms_multiple_rows_preserve_order(storage_factory):
    rows = [
        _StubRow(form_id="a", version="1.0",
                 schema_json=json.dumps({"title": "A"}),
                 created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                 updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _StubRow(form_id="b", version="1.0",
                 schema_json=json.dumps({"title": "B"}),
                 created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                 updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ]
    out = await storage_factory(rows).list_forms()
    assert [d["form_id"] for d in out] == ["a", "b"]


def test_form_storage_list_forms_docstring_contract():
    doc = FormStorage.list_forms.__doc__ or ""
    for key in ("form_id", "version", "title", "description", "created_at"):
        assert key in doc, f"docstring should mention {key}"
    assert "ISO-8601" in doc or "isoformat" in doc.lower()
```

### Key Constraints

- Use `pytest.mark.asyncio` (already in the test suite — see existing
  `tests/unit/test_handlers.py` line 53).
- No real DB connections.
- File header comment + Google-style docstring on each test function.

### References in Codebase

- `packages/parrot-formdesigner/tests/unit/test_handlers.py` — pytest
  layout pattern.
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py`
  — module under test.

---

## Acceptance Criteria

- [ ] New file `packages/parrot-formdesigner/tests/unit/test_storage_list.py`
      created with all six tests above.
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_storage_list.py -v`.
- [ ] No real DB connections — only stubs.
- [ ] No linting errors:
      `ruff check packages/parrot-formdesigner/tests/unit/test_storage_list.py`.
- [ ] Docstring-contract test verifies TASK-1029's docstring update.

---

## Test Specification

See "Test cases" above — those ARE the deliverable.

---

## Agent Instructions

1. **Read the spec** §4 (Test Specification) and §6 (Codebase Contract).
2. **Check dependencies** — TASK-1030 must be in `tasks/completed/`
   (otherwise the asserted output shape will not match).
3. **Verify the Codebase Contract** — confirm `PostgresFormStorage` is at
   line 39 and `list_forms` at line 213.
4. **Create** the test file using the stubs and assertions above.
5. **Run** `pytest` on the new file.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update** `sdd/tasks/index/formbuilder-list-created-forms.json` →
   `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Created `test_storage_list.py` with all 6 tests using duck-typed asyncpg stubs. All pass (6/6). Tests run with `PYTHONPATH` set to worktree src to pick up TASK-1030 changes (package is editable-installed from main repo). Docstring contract test also passes.

**Deviations from spec**: none
