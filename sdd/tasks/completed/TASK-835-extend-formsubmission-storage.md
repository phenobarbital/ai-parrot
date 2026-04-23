# TASK-835: Extend `FormSubmission` + `FormSubmissionStorage` (metadata columns, DLQ, `conn=`)

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-834
**Assigned-to**: unassigned

---

## Context

`FormSubmissionStorage` is the canonical Postgres-backed submission store. This task evolves it
into an implementation of the new `FormResultStorage` ABC (from TASK-834), adds the hybrid
metadata columns to `form_submissions`, creates the sibling `form_submissions_dlq` table, and
allows callers to share an asyncpg transaction via a new `conn=` kwarg on `store()`. Spec §3
Module 2, §2 DDL block, §2 Data Models.

---

## Scope

- Extend `FormSubmission` (Pydantic model) with optional fields: `user_id: int | None = None`,
  `org_id: int | None = None`, `program: str | None = None`, `client: str | None = None`,
  `status: str | None = None`, `enrichment: dict[str, Any] | None = None`.
- Make `FormSubmissionStorage` subclass `FormResultStorage` (from TASK-834).
- Extend `FormSubmissionStorage.initialize()` with **idempotent** `ALTER TABLE … ADD COLUMN IF NOT EXISTS`
  statements for the new columns, matching indexes, and `CREATE TABLE IF NOT EXISTS form_submissions_dlq`.
- Update `INSERT_SQL` to include the new columns (all nullable — legacy callers pass None).
- Modify `store(submission, *, conn=None)` so:
  - If `conn` is provided, use it (share caller's transaction) — do NOT acquire a new one.
  - If `conn` is None, keep the current `async with self._pool.acquire() as conn:` behavior.
- Add `store_dlq(form_id, form_version, raw_payload, stage, error, traceback, correlation_id)`
  method — runs in its own **separate** acquire/transaction (isolated from any caller txn per
  spec §2 flow: DLQ write happens after the main rollback).
- Unit tests: model new-field defaults, idempotent `initialize()`, `store()` legacy and `conn=`
  paths, `store_dlq()` row shape.

**NOT in scope**:
- Handler rewrite (TASK-839).
- Pydantic resolver, operators, UserDetails (separate tasks).
- Read/query API on the storage class.
- Row backfill or data migration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py` | MODIFY | Extend `FormSubmission`, subclass `FormResultStorage`, DDL + DLQ + `conn=` support |
| `packages/parrot-formdesigner/tests/unit/test_submissions_extended.py` | CREATE | Unit tests for new fields, DDL idempotency, `conn=` behavior, `store_dlq` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py (existing header)
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import asyncpg

# NEW import added by this task:
from .result_storage import FormResultStorage  # from TASK-834
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:23-51 (FormSubmission — extend)
class FormSubmission(BaseModel):
    submission_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique submission identifier",
    )
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:54-136 (FormSubmissionStorage — extend)
class FormSubmissionStorage:
    CREATE_TABLE_SQL = """
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
    """
    INSERT_SQL = """
        INSERT INTO form_submissions (
            submission_id, form_id, form_version, data,
            is_valid, forwarded, forward_status, forward_error, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    """
    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)
    async def initialize(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(self.CREATE_TABLE_SQL)
    async def store(self, submission: FormSubmission) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(self.INSERT_SQL, submission.submission_id, ...)
        return submission.submission_id
```

```python
# From TASK-834 — packages/parrot-formdesigner/src/parrot/formdesigner/services/result_storage.py
class FormResultStorage(ABC):
    @abstractmethod
    async def store(
        self,
        submission: "FormSubmission",
        *,
        conn: "asyncpg.Connection | None" = None,
    ) -> str: ...

    @abstractmethod
    async def store_dlq(
        self,
        form_id: str,
        form_version: str,
        raw_payload: dict[str, Any],
        stage: str,
        error: str,
        traceback: str,
        correlation_id: str,
    ) -> str: ...
```

### Does NOT Exist (before this task)
- ~~`FormSubmission.user_id`, `.org_id`, `.program`, `.client`, `.status`, `.enrichment`~~ — added here.
- ~~`form_submissions_dlq` table~~ — DDL added in `initialize()` here.
- ~~`FormSubmissionStorage.store_dlq(...)`~~ — method added here.
- ~~`store(..., conn=...)` kwarg~~ — signature extended here.
- ~~Columns `user_id`, `org_id`, `program`, `client`, `status`, `enrichment` on `form_submissions`~~
  — added via `ALTER TABLE ADD COLUMN IF NOT EXISTS`.

---

## Implementation Notes

### Pattern to Follow

Keep the class-level SQL-constant style. Add three new constants:
- `ALTER_TABLE_SQL` — series of `ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS …` +
  matching `CREATE INDEX IF NOT EXISTS`.
- `CREATE_DLQ_TABLE_SQL` — `CREATE TABLE IF NOT EXISTS form_submissions_dlq (…)` + index on `form_id`.
- `INSERT_DLQ_SQL` — parameterized INSERT for the DLQ row.

Update `CREATE_TABLE_SQL` to include the new columns for fresh installs (still nullable for
backward compat).

Update `INSERT_SQL` to the new column order (append new columns at the end so parameter indexes
for existing callers stay stable if they were already matching positionally).

```sql
-- Extend existing form_submissions (all new columns nullable — no backfill required)
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS user_id INTEGER;
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS org_id INTEGER;
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS program VARCHAR(255);
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS client VARCHAR(255);
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS status VARCHAR(50);
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS enrichment JSONB;
CREATE INDEX IF NOT EXISTS idx_form_submissions_user_id ON form_submissions(user_id);
CREATE INDEX IF NOT EXISTS idx_form_submissions_org_id  ON form_submissions(org_id);
CREATE INDEX IF NOT EXISTS idx_form_submissions_program ON form_submissions(program);

CREATE TABLE IF NOT EXISTS form_submissions_dlq (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id VARCHAR(255) NOT NULL UNIQUE,
    form_id VARCHAR(255) NOT NULL,
    form_version VARCHAR(50) NOT NULL,
    raw_payload JSONB NOT NULL,
    stage VARCHAR(50) NOT NULL,
    error TEXT NOT NULL,
    traceback TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_form_submissions_dlq_form_id ON form_submissions_dlq(form_id);
```

### `store()` branch

```python
async def store(self, submission, *, conn=None) -> str:
    if conn is not None:
        await conn.execute(self.INSERT_SQL, ...)
    else:
        async with self._pool.acquire() as c:
            await c.execute(self.INSERT_SQL, ...)
    return submission.submission_id
```

### `store_dlq()`

Always acquires its own connection + transaction. Never shares the caller's conn — because DLQ
must survive a caller rollback (the whole point of DLQ per spec §2).

### Key Constraints
- All new `FormSubmission` fields default to `None` / empty so legacy callers are unaffected.
- DDL must be idempotent (`IF NOT EXISTS` everywhere).
- Use `json.dumps(...)` to serialize `data` and `enrichment` dicts to JSONB (matches existing style).
- `self.logger` for all logging — no `print`.
- Preserve the existing `INSERT_SQL` parameter ordering principle: add new params at the end to
  minimize risk of index drift in tests.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39-244` —
  `PostgresFormStorage` uses the same class-level SQL + asyncpg pool pattern.
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:23-136` —
  the file you are editing.

---

## Acceptance Criteria

- [ ] `FormSubmission` has six new optional fields, all defaulting to `None`/empty.
- [ ] `FormSubmissionStorage` subclasses `FormResultStorage`
      (`issubclass(FormSubmissionStorage, FormResultStorage) is True`).
- [ ] `initialize()` runs without error on (a) a brand-new DB and (b) an existing DB with the
      old `form_submissions` schema; the result is the same final schema.
- [ ] `form_submissions_dlq` table exists after `initialize()` and has the spec columns.
- [ ] `store(sub, conn=conn)` uses the provided connection (no `pool.acquire` call).
- [ ] `store(sub)` (no kwargs) behaves exactly as today.
- [ ] `store_dlq(...)` inserts a row with the expected columns and returns the DLQ row's UUID.
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_submissions_extended.py -v`.
- [ ] Existing tests for `FormSubmissionStorage` still pass (regression).
- [ ] `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_submissions_extended.py
import pytest

from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot.formdesigner.services.result_storage import FormResultStorage


class TestFormSubmissionExtendedFields:
    def test_new_fields_default_none(self):
        sub = FormSubmission(
            form_id="db-form-test-01",
            form_version="1.0",
            data={"k": "v"},
            is_valid=True,
        )
        for attr in ("user_id", "org_id", "program", "client", "status", "enrichment"):
            assert getattr(sub, attr) is None, f"{attr} must default to None"

    def test_new_fields_accepted(self):
        sub = FormSubmission(
            form_id="db-form-test-01",
            form_version="1.0",
            data={"k": "v"},
            is_valid=True,
            user_id=42,
            org_id=7,
            program="alpha",
            client="acme",
            status="submitted",
            enrichment={"source": "web"},
        )
        assert sub.user_id == 42


class TestFormSubmissionStorageSubclassing:
    def test_is_form_result_storage(self):
        assert issubclass(FormSubmissionStorage, FormResultStorage)


# The following use a fake asyncpg pool/connection via MagicMock-style doubles.
# A real-DB integration test lives in TASK-841.
class TestStoreConnKwarg:
    async def test_store_uses_provided_conn(self, monkeypatch):
        """When conn= is passed, pool.acquire must NOT be called."""
        ...

    async def test_store_without_conn_acquires(self, monkeypatch):
        """When no conn=, legacy pool.acquire() path runs."""
        ...


class TestStoreDLQ:
    async def test_store_dlq_inserts_row(self, monkeypatch):
        """store_dlq writes a row with the expected columns and returns a UUID string."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§2 Data Models, §2 DDL block, §3 Module 2, §5 AC).
2. **Check dependencies** — `TASK-834` must be completed.
3. **Verify the Codebase Contract** — re-read `submissions.py` and the newly-created
   `result_storage.py` to confirm signatures match.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the model extension, ABC subclassing, DDL, DLQ, and `conn=` branch.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-835-extend-formsubmission-storage.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
