---
type: Wiki Overview
title: 'TASK-1033: Tests for handler `list_forms` merge + `FormSchema.created_at`'
id: doc:sdd-tasks-completed-task-1033-handler-and-schema-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task closes FEAT-148 by:'
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1033: Tests for handler `list_forms` merge + `FormSchema.created_at`

**Feature**: FEAT-148 — Enriched List of Created Forms in parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-list-created-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1028, TASK-1032
**Assigned-to**: unassigned

---

## Context

This task closes FEAT-148 by:
1. Updating the two existing handler tests broken by the response-shape
   change (`test_list_forms_empty`, `test_list_forms_with_registered_form`).
2. Adding new handler tests for the merge + dedupe + storage-failure
   behaviours specified in §4 of the spec.
3. Adding two `FormSchema.created_at` round-trip tests.

Implements Module 5 of the spec.

---

## Scope

### A. Update existing handler tests

In `packages/parrot-formdesigner/tests/unit/test_handlers.py`:

- `test_list_forms_empty` (line ~55): keep `data["forms"]` as a list,
  but assert the new shape:
  ```python
  data = await resp.json()
  assert data == {"forms": []}
  ```
- `test_list_forms_with_registered_form` (line ~78): replace
  `assert "test" in data["forms"]` with:
  ```python
  ids = [f["form_id"] for f in data["forms"]]
  assert "test" in ids
  desc = next(f for f in data["forms"] if f["form_id"] == "test")
  assert desc["title"] == "Test Form"
  assert desc["version"] == "1.0"
  assert desc["source"] == "memory"
  assert desc["created_at"] is None
  assert desc["description"] is None
  ```

### B. Add new handler tests

Add the following tests inside the existing `TestFormAPIHandler` class
(or a new `TestListFormsRich` class in the same file):

| Test | What it verifies |
|---|---|
| `test_list_forms_dict_shape` | One registry form → descriptor has every required key |
| `test_list_forms_localized_title_flattening` | `title={"en":"Hello","es":"Hola"}` → `desc["title"] == "Hello"` |
| `test_list_forms_with_storage_only_form` | Fake storage returns one form not in registry → appears with `source=="db"` and ISO `created_at` |
| `test_list_forms_storage_and_registry_dedupe` | Same `form_id` in both → exactly one descriptor; registry wins for title/version; `created_at` from storage; `source=="db"` |
| `test_list_forms_sorted_by_form_id` | Three forms registered as `c, a, b` → response order is `a, b, c` |
| `test_list_forms_storage_failure_falls_back` | `FakeStorage.list_forms` raises → response is registry-only, status 200 |

The tests need a small `FakeStorage` test double inheriting from
`FormStorage`. Define it once at module level (or in a shared fixture).

### C. Add `FormSchema.created_at` tests

In `packages/parrot-formdesigner/tests/unit/test_core_models.py` (or a
new file `test_form_schema_created_at.py` in the same dir):

- `test_form_schema_created_at_optional` — construct `FormSchema`
  without `created_at`; `f.created_at is None`.
- `test_form_schema_created_at_serializes_iso` — construct with a
  tz-aware `datetime`, assert
  `'"created_at":"2026-04-12T10:31:00+00:00"' in f.model_dump_json()`,
  and confirm `FormSchema.model_validate_json(f.model_dump_json())`
  round-trips equal.

**NOT in scope**:
- Real `PostgresFormStorage` integration tests (TASK-1031 covers stubbed
  storage tests).
- Permission/scoping tests (spec §1 Non-Goals).
- Pagination tests.
- Tests for unrelated handlers (`get_form`, `validate`, etc.).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_handlers.py` | MODIFY | Update 2 tests + add 6 new tests + `FakeStorage` |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | Add 2 `FormSchema.created_at` tests (or create `test_form_schema_created_at.py`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at top of tests/unit/test_handlers.py (lines 1-7):
import pytest
from aiohttp import web
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.services import FormRegistry
from parrot.formdesigner.handlers import setup_form_routes

# NEW imports needed for FakeStorage and timestamps:
from datetime import datetime, timezone
from parrot.formdesigner.services.registry import FormStorage
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/__init__.py
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29
```

### Existing Test Fixtures

```python
# tests/unit/test_handlers.py
@pytest.fixture
def registry() -> FormRegistry: ...                      # line 11
@pytest.fixture
def sample_schema() -> FormSchema: ...                   # line 16
@pytest.fixture
def app_with_routes(registry) -> web.Application: ...    # line 33
```

`app_with_routes` calls `setup_form_routes(app, registry=registry)` which
creates a `FormAPIHandler`. The handler reads `self.registry._storage` —
to inject a test storage we attach it to the registry BEFORE calling
`setup_form_routes` (or before the request runs). Easiest path: create a
new fixture `app_with_storage(registry)` that sets `registry._storage = FakeStorage(...)` and then calls `setup_form_routes`.

### Existing Signatures to Use

```python
# After TASK-1028:
class FormSchema(BaseModel):
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None

# After TASK-1032:
async def list_forms(self, request) -> web.Response:
    # Returns: {"forms": [<descriptor>, ...]}

# FormStorage ABC (target for FakeStorage):
class FormStorage(ABC):
    @abstractmethod async def save(self, form, style=None) -> str: ...
    @abstractmethod async def load(self, form_id, version=None) -> FormSchema | None: ...
    @abstractmethod async def delete(self, form_id) -> bool: ...
    @abstractmethod async def list_forms(self) -> list[dict[str, str]]: ...
```

### Does NOT Exist

- ~~`FormRegistry.attach_storage()`~~ — no such method; assign
  `registry._storage = ...` directly in tests.
- ~~`FormSchema.from_dict()`~~ — use `FormSchema.model_validate()`.
- ~~`pytest.mark.parametrize` is needed~~ — straight-line tests are
  clearer for the merge logic; do not parametrize.

---

## Implementation Notes

### `FakeStorage`

```python
class FakeStorage(FormStorage):
    """In-memory FormStorage stub for unit tests."""

    def __init__(self, rows: list[dict] | None = None,
                 *, raise_on_list: bool = False) -> None:
        self._rows = rows or []
        self._raise = raise_on_list

    async def save(self, form, style=None): return form.form_id
    async def load(self, form_id, version=None): return None
    async def delete(self, form_id): return False
    async def list_forms(self):
        if self._raise:
            raise RuntimeError("storage offline")
        return list(self._rows)
```

### Fixture for storage-backed app

```python
@pytest.fixture
def app_with_storage(registry):
    def _build(rows, *, raise_on_list=False):
        registry._storage = FakeStorage(rows, raise_on_list=raise_on_list)
        app = web.Application()
        setup_form_routes(app, registry=registry)
        return app
    return _build
```

### Sample new tests (illustrative — adapt as needed)

```python
async def test_list_forms_with_storage_only_form(self, aiohttp_client, app_with_storage):
    rows = [{
        "form_id": "persisted-only", "version": "1.0",
        "title": "Persisted", "description": None,
        "created_at": "2026-04-12T10:31:00+00:00",
    }]
    client = await aiohttp_client(app_with_storage(rows))
    resp = await client.get("/api/v1/forms")
    data = await resp.json()
    assert resp.status == 200
    assert len(data["forms"]) == 1
    d = data["forms"][0]
    assert d["form_id"] == "persisted-only"
    assert d["source"] == "db"
    assert d["created_at"] == "2026-04-12T10:31:00+00:00"


async def test_list_forms_storage_and_registry_dedupe(self, aiohttp_client,
                                                       app_with_storage,
                                                       registry, sample_schema):
    await registry.register(sample_schema)  # form_id="test", version "1.0"
    rows = [{
        "form_id": "test", "version": "0.9",  # storage has older version
        "title": "Stale Storage Title", "description": "stale",
        "created_at": "2026-01-01T00:00:00+00:00",
    }]
    client = await aiohttp_client(app_with_storage(rows))
    resp = await client.get("/api/v1/forms")
    data = await resp.json()
    assert len(data["forms"]) == 1
    d = data["forms"][0]
    assert d["form_id"] == "test"
    assert d["source"] == "db"
    assert d["title"] == "Test Form"          # registry wins
    assert d["version"] == "1.0"              # registry wins
    assert d["created_at"] == "2026-01-01T00:00:00+00:00"  # storage wins


async def test_list_forms_storage_failure_falls_back(self, aiohttp_client,
                                                      app_with_storage,
                                                      registry, sample_schema):
    await registry.register(sample_schema)
    client = await aiohttp_client(app_with_storage([], raise_on_list=True))
    resp = await client.get("/api/v1/forms")
    assert resp.status == 200
    data = await resp.json()
    assert len(data["forms"]) == 1
    assert data["forms"][0]["source"] == "memory"
```

### `FormSchema.created_at` tests

```python
def test_form_schema_created_at_optional():
    f = FormSchema(form_id="x", title="t", sections=[])
    assert f.created_at is None


def test_form_schema_created_at_serializes_iso():
    ts = datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc)
    f = FormSchema(form_id="x", title="t", sections=[], created_at=ts)
    js = f.model_dump_json()
    assert '"created_at":"2026-04-12T10:31:00+00:00"' in js
    f2 = FormSchema.model_validate_json(js)
    assert f2.created_at == ts
```

### Key Constraints

- Use `pytest.mark.asyncio` on async tests (already configured in this
  test suite).
- Do NOT spin up a real `PostgresFormStorage` — only `FakeStorage`.
- Keep the Google-style docstring on each new test.
- Run ruff on every file edited.

### References in Codebase

- `packages/parrot-formdesigner/tests/unit/test_handlers.py:53-117` —
  layout / fixture pattern.
- `packages/parrot-formdesigner/tests/unit/test_core_models.py` — for
  the schema test additions.

---

## Acceptance Criteria

- [ ] Both pre-existing handler tests pass under the new response shape.
- [ ] All six new handler tests pass.
- [ ] Both `FormSchema.created_at` round-trip tests pass.
- [ ] No linting errors on edited files.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/ -v` passes
      (suite-wide, including this file and TASK-1031's
      `test_storage_list.py`).
- [ ] No real DB connections — only `FakeStorage`.
- [ ] No reliance on TASK-1029's docstring contract test (that one lives
      in TASK-1031).

---

## Test Specification

See "Sample new tests" above and the table in §B.

---

## Agent Instructions

1. **Read the spec** §4 (Test Specification) and §6 (Codebase Contract).
2. **Check dependencies**:
   - TASK-1028 must be completed (otherwise `FormSchema.created_at`
     does not exist and the schema tests fail to import).
   - TASK-1032 must be completed (otherwise the response shape is
     `list[str]` and the new handler tests fail).
3. **Verify the Codebase Contract**:
   - `grep -n "test_list_forms_empty\|test_list_forms_with_registered_form" packages/parrot-formdesigner/tests/unit/test_handlers.py`
     → confirm lines ~55, ~78.
   - `grep -n "class FormSchema" packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py`
     → still line 107.
4. **Edit** the two test files.
5. **Run** `pytest packages/parrot-formdesigner/tests/unit/ -v`.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update** `sdd/tasks/index/formbuilder-list-created-forms.json` →
   `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Updated `test_list_forms_empty` and `test_list_forms_with_registered_form` to assert the new dict-shaped payload. Added `FakeStorage` class and `app_with_storage` fixture. Added 6 new handler tests (dict_shape, localized_title_flattening, storage_only_form, storage_and_registry_dedupe, sorted_by_form_id, storage_failure_falls_back). Added 2 FormSchema.created_at round-trip tests in test_core_models.py. Handler tests fail with "400 Authentication Backend is not enabled" — this is a pre-existing environment issue also affecting all pre-existing handler tests (verified by running baseline). The ISO-8601 assertion was updated to accept Pydantic v2's "Z" suffix. All non-handler tests (16) pass. Ruff check clean.

**Deviations from spec**: Handler tests fail due to pre-existing navigator-auth configuration issue in test environment (same as baseline before this task).
