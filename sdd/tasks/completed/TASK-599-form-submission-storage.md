# TASK-599: FormSubmissionStorage

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Creates the local persistence layer for form submission data. When users submit data via `POST /api/v1/forms/{form_id}/data`, the validated data is stored in a `form_submissions` PostgreSQL table before (optionally) being forwarded to an external endpoint.

This is independent of the auth system (TASK-597/598) — it only stores data locally.

Implements Spec Module 3.

---

## Scope

- Create `services/submissions.py` with:
  - `FormSubmission` Pydantic model (submission_id, form_id, form_version, data, is_valid, forwarded, forward_status, forward_error, created_at)
  - `FormSubmissionStorage` class with:
    - `__init__(self, pool: asyncpg.Pool)`
    - `async def initialize(self) -> None` — creates `form_submissions` table
    - `async def store(self, submission: FormSubmission) -> str` — inserts record, returns submission_id
- Create table schema per spec (see Implementation Notes)
- Export from `services/__init__.py`

**NOT in scope**: Forwarding logic (TASK-600), API endpoint (TASK-602), retrieval/listing of submissions

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py` | CREATE | FormSubmission model + FormSubmissionStorage |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/__init__.py` | MODIFY | Export new classes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Follow the same pattern as services/storage.py:
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING, Any
from pydantic import BaseModel, Field
from datetime import datetime

if TYPE_CHECKING:
    import asyncpg
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39
# Follow PostgresFormStorage as the pattern for table creation and insertion
class PostgresFormStorage(FormStorage):
    CREATE_TABLE_SQL = """..."""  # line 58 — class-level SQL constant
    UPSERT_SQL = """..."""  # line 72

    def __init__(self, pool: Any) -> None:  # line 106
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:  # line 115
        async with self._pool.acquire() as conn:
            await conn.execute(self.CREATE_TABLE_SQL)

    async def save(self, form: FormSchema, ...) -> str:  # line 124
        async with self._pool.acquire() as conn:
            await conn.execute(self.UPSERT_SQL, ...)
```

### Does NOT Exist
- ~~`form_submissions` table~~ — does not exist; this task creates it
- ~~`FormSubmissionStorage`~~ — does not exist; this task creates it
- ~~`FormSubmission` model~~ — does not exist; this task creates it
- ~~`parrot.formdesigner.services.submissions`~~ — module does not exist; this task creates it

---

## Implementation Notes

### Table Schema
```sql
CREATE TABLE IF NOT EXISTS form_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id VARCHAR(255) NOT NULL UNIQUE,
    form_id VARCHAR(255) NOT NULL,
    form_version VARCHAR(50) NOT NULL,
    data JSONB NOT NULL,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    forwarded BOOLEAN NOT NULL DEFAULT FALSE,
    forward_status INTEGER,
    forward_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id ON form_submissions(form_id);
```

### Key Constraints
- Use `uuid.uuid4()` to generate `submission_id` if not provided
- Store `data` as JSONB via `json.dumps()`
- Follow the exact same pattern as `PostgresFormStorage` for pool management
- Use class-level SQL constants (not inline strings)
- Add `self.logger` with `logging.getLogger(__name__)`

### Pattern to Follow
```python
class FormSubmissionStorage:
    CREATE_TABLE_SQL = """..."""
    INSERT_SQL = """..."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(self.CREATE_TABLE_SQL)

    async def store(self, submission: FormSubmission) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(self.INSERT_SQL, ...)
        return submission.submission_id
```

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py` — exact pattern to follow

---

## Acceptance Criteria

- [ ] `FormSubmission` model created with all fields from spec
- [ ] `FormSubmissionStorage.initialize()` creates the table
- [ ] `FormSubmissionStorage.store()` inserts a record and returns submission_id
- [ ] Classes exported from `services/__init__.py`
- [ ] `from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage` works

---

## Test Specification

```python
# tests/test_submissions.py
import pytest
from datetime import datetime, timezone
from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage


class TestFormSubmission:
    def test_model_creation(self):
        sub = FormSubmission(
            submission_id="sub-001",
            form_id="test-form",
            form_version="1.0",
            data={"name": "John", "email": "john@example.com"},
            is_valid=True,
            created_at=datetime.now(timezone.utc),
        )
        assert sub.submission_id == "sub-001"
        assert sub.forwarded is False
        assert sub.forward_status is None

    def test_model_serialization(self):
        sub = FormSubmission(
            submission_id="sub-001",
            form_id="test-form",
            form_version="1.0",
            data={"key": "value"},
            is_valid=True,
            created_at=datetime.now(timezone.utc),
        )
        d = sub.model_dump()
        restored = FormSubmission.model_validate(d)
        assert restored.submission_id == "sub-001"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md`
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — read `services/storage.py` for the pattern, read `services/__init__.py` for exports
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_submissions.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
