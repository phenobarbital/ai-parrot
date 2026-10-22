# TASK-4631: Guarded submission storage (`count_responses`, `store_guarded`)

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The response cap and "one response per key question" must be
atomic per `form_uid`: concurrent submits can neither exceed `max_responses`
nor store a duplicate key value. `FormSubmissionStorage.store()` is a bare
INSERT today. This task adds a root-only `count_responses` and a
`store_guarded` that, in ONE transaction, takes an advisory lock, counts,
checks the key, then INSERTs exactly like `store()`.

---

## Scope

- Add exceptions `ResponseLimitReached` and `DuplicateResponse(field_id)` to `services/submissions.py`.
- Add `FormSubmissionStorage.count_responses(form_uid, *, tenant=None) -> int` (revision-chain roots only).
- Add `FormSubmissionStorage.store_guarded(submission, *, tenant=None, max_responses=None, unique_key_field=None, unique_value=None) -> str`.
- Refactor `store()`'s parameter tuple into a private helper used by both (no behaviour change).
- Write the Postgres integration tests (skip cleanly without `SCRATCH_DSN`).

**NOT in scope**: calling `store_guarded` from the pipeline (TASK-4632); any
pending-upload clearing (FEAT-731, which hooks the SAME transaction later).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` | MODIFY | exceptions, `count_responses`, `store_guarded`, `_insert_params` |
| `packages/parrot-formdesigner/tests/integration/test_store_guarded.py` | CREATE | concurrency + root-count tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `685e6176c`.

### Verified Imports
```python
from ._identifiers import qualified_table, validate_identifier     # services/submissions.py:25
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage  # :50, :122
```

### Existing Signatures to Use
```python
# services/submissions.py
class FormSubmission(BaseModel):            # line 50 — submission_id, form_uid, form_id, form_version, data,
                                            # tenant (:108), root_submission_id, revision, created_at, ...
class FormSubmissionStorage:                # line 122
    def __init__(self, pool, *, schema=DEFAULT_SCHEMA, table_name=DEFAULT_TABLE, tenant=None)  # :138
    def _resolve_schema(self, tenant: str | None) -> str           # :163
    def _qualified(self, tenant: str | None) -> str                # :170
    def _insert_sql(self, tenant: str | None) -> str               # :260
    async def store(self, submission, *, tenant=None) -> str       # :313
    # store(): effective_tenant = tenant if tenant is not None else submission.tenant (:330);
    # async with self._pool.acquire() as conn: await conn.execute(self._insert_sql(...), <20 params>)  (:333-358)
# table columns: submission_id UNIQUE, form_uid, form_id, data JSONB, root_submission_id, revision, created_at
```
Advisory-lock idiom in the monorepo: `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py:355-359`
(`SELECT pg_advisory_xact_lock(hashtextextended($1, 0))` inside `async with conn.transaction()`).

### Does NOT Exist
- ~~`count_responses`, `store_guarded`, `ResponseLimitReached`, `DuplicateResponse`~~ — added here.
- ~~A transaction inside `store()`~~ — `store()` stays a single execute (FEAT-731 adds its own transaction later).
- ~~A normalized key column~~ — compare in SQL, never add a column.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/integration/test_store_guarded.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage.store",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage._insert_sql",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmission"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Lock key: `pg_advisory_xact_lock(hashtextextended($1::text, 0))` with `str(form_uid)` — transaction-scoped, released on commit/rollback.
- Count rule (roots only): `COALESCE(root_submission_id, submission_id) = submission_id` AND `form_uid = $1`.
- Uniqueness: strings → `lower(btrim(data->>$key)) = lower(btrim($value))`; other JSON → `data->$key = $value::jsonb`. The key name is a bind parameter, never interpolated.
- `unique_value is None` → no uniqueness query.
- Tenant resolution identical to `store()`.

---

## Implementation Blueprint

### Steps (in order)
1. Extract `store()`'s 20-tuple into `_insert_params(submission, effective_tenant)` — *why*: `store_guarded` must INSERT with the exact same parameter order; one source avoids drift.
2. Add the two exceptions near `FormSubmission` — *why*: the pipeline (TASK-4632) maps them to 409 reasons.
3. Add `count_responses` and `store_guarded` after `store()` — *why*: spec §3 M2.
4. Write the integration tests (skip without `SCRATCH_DSN`, the package's existing convention).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class FormSubmissionStorage:' services/submissions.py)
# BEFORE — insert above `class FormSubmissionStorage:` (verified: services/submissions.py:122)
class ResponseLimitReached(Exception):
    """store_guarded refused: the form already has >= max_responses root responses (FEAT-730)."""


class DuplicateResponse(Exception):
    """store_guarded refused: another response of the form has the same key value (FEAT-730)."""

    def __init__(self, field_id: str) -> None:
        super().__init__(f"duplicate response for key field {field_id!r}")
        self.field_id = field_id
```
```python
# occurrences: 1 (verified: grep -c '    async def store(' services/submissions.py)
# occurrences: 1 (verified: grep -c '        return submission.submission_id' services/submissions.py)
# AFTER — insert below `        return submission.submission_id`, the last line of store() (verified: services/submissions.py:365)
    def _insert_params(self, submission: FormSubmission, effective_tenant: str | None) -> tuple:
        """The INSERT parameter tuple, in `_insert_sql` order (shared by store/store_guarded)."""
        # FILL IN: move the exact 20 arguments store() passes today (lines 334-357), same order;
        # then make store() call `conn.execute(self._insert_sql(t), *self._insert_params(submission, t))`.
        raise NotImplementedError

    async def count_responses(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> int:
        """Count revision-chain roots of ``form_uid`` in the tenant's table."""
        sql = (
            f"SELECT count(*) FROM {self._qualified(tenant)} "
            "WHERE form_uid = $1 AND COALESCE(root_submission_id, submission_id) = submission_id"
        )
        async with self._pool.acquire() as conn:
            return int(await conn.fetchval(sql, form_uid))

    async def store_guarded(
        self,
        submission: FormSubmission,
        *,
        tenant: str | None = None,
        max_responses: int | None = None,
        unique_key_field: str | None = None,
        unique_value: Any | None = None,
    ) -> str:
        """Lock, count, key-check and INSERT in one transaction. Raises ResponseLimitReached /
        DuplicateResponse. Returns submission_id."""
        effective_tenant = tenant if tenant is not None else submission.tenant
        qt = self._qualified(effective_tenant)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))", str(submission.form_uid)
                )
                # FILL IN: when max_responses: same root count as count_responses() on `conn`;
                # >= max_responses -> raise ResponseLimitReached.
                # FILL IN: when unique_key_field and unique_value is not None: str -> lower(btrim(data->>$2))
                # = lower(btrim($3)); else data->$2 = $3::jsonb (json.dumps(value)); match -> DuplicateResponse.
                await conn.execute(self._insert_sql(effective_tenant), *self._insert_params(submission, effective_tenant))
        self.logger.debug("Stored guarded submission %s in %s", submission.submission_id, qt)
        return submission.submission_id
```
**Why**: the lock + checks + INSERT share one connection and one transaction so two
concurrent submits serialize per form. `store()` keeps its single-statement shape (AC1).

### `packages/parrot-formdesigner/tests/integration/test_store_guarded.py` (CREATE)
```python
"""FEAT-730 — store_guarded atomicity against a real Postgres (skips without SCRATCH_DSN)."""
import asyncio
import os
import uuid

import pytest

from parrot_formdesigner.services.submissions import (
    DuplicateResponse, FormSubmission, FormSubmissionStorage, ResponseLimitReached,
)

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")
pytestmark = pytest.mark.skipif(not _SCRATCH_DSN, reason="SCRATCH_DSN not set (scratch Postgres required)")


@pytest.fixture
async def storage():
    # FILL IN: asyncpg pool on SCRATCH_DSN, unique scratch schema, FormSubmissionStorage(pool, schema=...),
    # await initialize(); drop the schema on teardown. Mirror tests/integration/test_unknown_fields_e2e.py.
    ...


async def test_store_guarded_cap_concurrent(storage):
    # FILL IN: 20 concurrent store_guarded(max_responses=5) -> exactly 5 rows, 15 ResponseLimitReached.
    ...


async def test_store_guarded_unique_concurrent(storage):
    # FILL IN: concurrent "A@x.com " vs "a@X.com" on key "email" -> exactly 1 row, 1 DuplicateResponse.
    ...


async def test_count_responses_roots_only(storage):
    # FILL IN: a root + a revision (root_submission_id = root id, revision 2) -> count == 1.
    ...
```

### FILL IN checklist
- [ ] `_insert_params` — exact parameter order of today's `store()`; `store()` rewritten to use it
- [ ] cap check inside the transaction — AC3
- [ ] key check (str vs JSON) inside the transaction — AC4
- [ ] integration fixtures and test bodies

---

## Acceptance Criteria

- [ ] `store()` behaviour and statement unchanged (existing storage tests green).
- [ ] 20 concurrent guarded stores with cap 5 → exactly 5 rows (AC3).
- [ ] Case/whitespace-insensitive duplicate detection for strings (AC4).
- [ ] Revisions never count toward the cap.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/integration/test_store_guarded.py -q`
- `pytest packages/parrot-formdesigner/tests/test_submission_jsonb_shape.py -q`

---

## Test Specification

See the CREATE block (spec §4 Integration Tests). Run with `SCRATCH_DSN` set —
a skip is not a pass for this task's acceptance.

---

## Agent Instructions

1. Feature worktree (`python -m scripts.sdd.ensure_worktree --slug formdesigner-public-form-controls --feature-id FEAT-730`).
2. Re-run every `grep -c` in the Codebase Contract before editing.
3. Index → `in-progress`; implement; run Validation Commands with `SCRATCH_DSN`.
4. Commit only the listed files; `scripts/sdd/close_task.sh TASK-4631 formdesigner-public-form-controls verified`.

---

## Completion Note

*(Agent fills this in when done)*
