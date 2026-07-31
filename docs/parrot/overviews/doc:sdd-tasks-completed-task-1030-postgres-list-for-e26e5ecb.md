---
type: Wiki Overview
title: 'TASK-1030: Enrich `PostgresFormStorage.list_forms()` with `created_at` and
  `description`'
id: doc:sdd-tasks-completed-task-1030-postgres-list-forms-enriched-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (TASK-1032) needs `created_at` (ISO-8601) and `description` to build
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1030: Enrich `PostgresFormStorage.list_forms()` with `created_at` and `description`

**Feature**: FEAT-148 — Enriched List of Created Forms in parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-list-created-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`PostgresFormStorage.list_forms()` currently returns
`{"form_id", "version", "title"}` per row. The handler refactor
(TASK-1032) needs `created_at` (ISO-8601) and `description` to build
the enriched response. This task widens the SQL projection and the
result-dict shape.

Implements Module 2 of the spec.

---

## Scope

- Update `LIST_SQL` in `PostgresFormStorage` to project `created_at`
  alongside the existing columns.
- Update `list_forms()` to:
  - Convert `created_at` (a tz-aware `datetime` from asyncpg) to an
    ISO-8601 string via `.isoformat()`. Use `None` if the column is
    `NULL` (defensive — schema forbids NULL but be safe).
  - Extract `description` from the parsed `schema_json` using the same
    pattern as the existing `title` extraction (lines 230-240 of
    `storage.py`): if it is a dict (`LocalizedString`), pick the first
    value; if it is a string, use it directly; otherwise emit `None`.
- Keep the return type annotation `list[dict[str, str]]` as-is. Document
  in the updated docstring that `created_at` may be `None` and that
  values are no longer all-strings.

**NOT in scope**:
- Changing the method's `created_by` / `style_json` handling.
- Adding `updated_at` to the result.
- Pagination / WHERE clauses.
- Modifying `save()`, `load()`, or `delete()`.
- Touching `FormStorage` ABC (TASK-1029) or the handler (TASK-1032).
- Writing tests (TASK-1031).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py` | MODIFY | Update `LIST_SQL` projection (lines ~100-104) and `list_forms()` body (lines ~213-243) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present in storage.py:
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING, Any
from .registry import FormStorage
from ..core.schema import FormSchema
from ..core.style import StyleSchema
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:23-31
```

No new imports needed (asyncpg's `datetime` objects already round-trip
via `.isoformat()`).

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py
class PostgresFormStorage(FormStorage):                   # line 39

    LIST_SQL = """
    SELECT DISTINCT ON (form_id) form_id, version, schema_json, updated_at
    FROM form_schemas
    ORDER BY form_id, updated_at DESC
    """                                                   # lines 100-104  ← REPLACE

    def __init__(self, pool: Any) -> None: ...            # line 106
        self._pool = pool                                 # line 112
        self.logger = logging.getLogger(__name__)         # line 113

    async def list_forms(self) -> list[dict[str, str]]:   # line 213  ← MODIFY BODY
        # Current body extracts title from schema_json (lines 228-240).
```

### DB Schema Reference

```sql
-- packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:58-70
CREATE TABLE IF NOT EXISTS form_schemas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_id VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL DEFAULT '1.0',
    schema_json JSONB NOT NULL,
    style_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),       -- ← project this
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255),
    UNIQUE(form_id, version)
);
```

### Does NOT Exist

- ~~`row.get("created_at")`~~ — `asyncpg.Record` does not support `.get()`;
  use `row["created_at"]` and check the value (asyncpg returns `None` for
  `NULL` columns, but the schema declares `NOT NULL` so this is just defensive).
- ~~`schema_json["description"]`~~ when `schema_json` may be a JSON string —
  use the same `isinstance(raw, str)` / `json.loads` pattern as the
  existing title extraction.
- ~~`datetime.fromisoformat()` parsing~~ — asyncpg already returns
  `datetime` objects for `TIMESTAMPTZ` columns; just call `.isoformat()`.

---

## Implementation Notes

### Pattern to Follow

The existing title extraction is the template (lines 228-240):

```python
try:
    raw = row["schema_json"]
    data = json.loads(raw) if isinstance(raw, str) else raw
    title = data.get("title", "")
    if isinstance(title, dict):
        title = next(iter(title.values()), "")
    entry["title"] = str(title)
except Exception:
    entry["title"] = ""
```

Mirror this for `description` (note: description may be missing entirely;
default to `None`, not `""`). Pull both in the same `try/except` block to
avoid a second JSON parse:

```python
try:
    raw = row["schema_json"]
    data = json.loads(raw) if isinstance(raw, str) else raw

    title = data.get("title", "")
    if isinstance(title, dict):
        title = next(iter(title.values()), "")
    entry["title"] = str(title) if title else ""

    desc = data.get("description")
    if isinstance(desc, dict):
        desc = next(iter(desc.values()), None)
    entry["description"] = str(desc) if desc else None
except Exception:
    entry["title"] = ""
    entry["description"] = None
```

`created_at` is straight from the row:

```python
ts = row["created_at"]
entry["created_at"] = ts.isoformat() if ts is not None else None
```

### New `LIST_SQL`

```sql
SELECT DISTINCT ON (form_id)
    form_id,
    version,
    schema_json,
    created_at,
    updated_at
FROM form_schemas
ORDER BY form_id, updated_at DESC
```

### Updated docstring

```
"""List all persisted forms (latest version of each).

Returns:
    List of dicts with keys ``form_id``, ``version``, ``title``,
    ``description``, and ``created_at``. ``description`` may be
    ``None`` when the form has no description; ``created_at`` is
    an ISO-8601 string (e.g. ``"2026-04-12T10:31:00+00:00"``) or
    ``None``. The dict's value type is therefore not strictly
    ``str`` — the annotation is kept loose for backwards
    compatibility.
"""
```

### Key Constraints

- Use parameterized queries — none added in this task; `LIST_SQL` has
  no parameters.
- Do NOT bump the method to `Any` return type — leave the existing
  annotation. The looser contract is documented in the docstring.
- Do NOT swallow `created_at` parsing errors silently — there should be
  none (asyncpg returns `datetime`); if `.isoformat()` fails, let it raise
  and surface in the handler's storage-failure fallback (TASK-1032).

### References in Codebase

- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:228-240`
  — current title extraction pattern to mirror.

---

## Acceptance Criteria

- [ ] `LIST_SQL` projects `created_at` (in addition to the existing
      `form_id`, `version`, `schema_json`, `updated_at`).
- [ ] Each result dict has the keys `form_id`, `version`, `title`,
      `description`, `created_at`.
- [ ] `created_at` is `<datetime>.isoformat()` when present, else `None`.
- [ ] `description` is a string when present (flattened from
      `LocalizedString` if needed), else `None`.
- [ ] Method docstring describes the new keys.
- [ ] Method signature and return-type annotation unchanged.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py`.
- [ ] Unit tests added in TASK-1031 will pass.

---

## Test Specification

> Tests live in TASK-1031. This task only writes the implementation.
> Smoke check (manual, requires `.venv`):

```python
# Pseudo — replace pool with a stub that returns a fake row
import asyncio
from datetime import datetime, timezone

class _Row(dict):
    def __getitem__(self, k): return super().__getitem__(k)

class _Conn:
    async def fetch(self, sql):
        return [_Row({
            "form_id": "f-1",
            "version": "1.0",
            "schema_json": '{"title":{"en":"Hello"},"description":"A form"}',
            "created_at": datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc),
        })]
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

class _Pool:
    def acquire(self): return _Conn()

from parrot.formdesigner.services.storage import PostgresFormStorage
async def main():
    s = PostgresFormStorage(pool=_Pool())
    out = await s.list_forms()
    assert out == [{
        "form_id": "f-1", "version": "1.0",
        "title": "Hello", "description": "A form",
        "created_at": "2026-04-12T10:31:00+00:00",
    }]
asyncio.run(main())
```

---

## Agent Instructions

1. **Read the spec** §3 Module 2 and §6 (DB Schema Reference, Existing
   Class Signatures).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract**:
   - `grep -n "LIST_SQL\|async def list_forms" packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py`
   - Confirm lines 100 and 213 still match.
4. **Implement** the SQL change + dict construction.
5. **Run** the smoke check above (or wait for TASK-1031).
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update** `sdd/tasks/index/formbuilder-list-created-forms.json` →
   `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Updated `LIST_SQL` to project `created_at` in addition to existing columns. Updated `list_forms()` body to include `created_at` (isoformat string or None) and `description` (flattened LocalizedString or None) in each result dict. Also removed pre-existing unused `TYPE_CHECKING`/`asyncpg` imports. Ruff check clean.

**Deviations from spec**: none
