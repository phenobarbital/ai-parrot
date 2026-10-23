# TASK-4640: Clear pending rows inside `store()`'s transaction + `references_blob`

**Feature**: FEAT-731 — FormDesigner orphan upload cleanup
**Spec**: `sdd/specs/formdesigner-orphan-upload-cleanup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4638
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / §2.3. When a submission referencing an uploaded blob is
stored, its pending row must disappear in the SAME transaction as the INSERT
(both commit or neither). Because the clear lives in `FormSubmissionStorage.store()`,
hosts that call `store()` directly (FieldSync execution `services.py:645`,
visits `services.py:1189`) are covered with zero host code (AC5). The reaper
(TASK-4641) also needs `references_blob` as its safety check.
FEAT-730's `store_guarded()` must call the same helper in its own transaction
(AC9) — wire it here if `store_guarded` already exists on `dev` when this task
runs; otherwise FEAT-730's TASK-4631 owner wires it (record which in the Completion Note).

---

## Scope

- `attach_pending_uploads(store)` late binding; `self._pending = None` in `__init__`.
- `_clear_pending(conn, submission, tenant)`: SAVEPOINT + `pending.clear(iter_blob_refs(submission.data), tenant=…, conn=conn)`; an undefined-table error (SQLSTATE `42P01`) → roll back to the savepoint, debug log.
- Add `is_undefined_table(exc)` to `services/_db_utils.py`, next to `is_unique_violation` (same driver-agnostic shape — no asyncpg import; asyncpg is not a declared dependency of this package).
- `store()`: unchanged single execute when nothing is attached; with a store attached, `async with conn.transaction()`: INSERT then `_clear_pending`.
- `references_blob(form_uid, blob_ref, *, tenant) -> bool` (jsonpath, filtered by `form_uid`).
- If present: `store_guarded()` calls `_clear_pending` inside its transaction (AC9).
- Postgres integration tests.

**NOT in scope**: attaching the store from `setup_form_api` (TASK-4642).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` | MODIFY | attach, transactional clear, references_blob |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py` | MODIFY | `is_undefined_table` |
| `packages/parrot-formdesigner/tests/integration/test_pending_uploads_pg.py` | CREATE | real-Postgres tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `28b3be0ac`
> (before FEAT-730 TASK-4631, which also edits this file — re-grep).

### Verified Imports
```python
# TASK-4638: from .pending_uploads import PendingUploadStore, iter_blob_refs   (import lazily or under TYPE_CHECKING to avoid a cycle)
from ._db_utils import is_unique_violation   # services/_db_utils.py:8 — pattern for the new is_undefined_table
# NOTE: asyncpg is NOT a declared dependency of parrot-formdesigner (only lazily imported elsewhere) — never import it here.
```

### Existing Signatures to Use
```python
# services/submissions.py
class FormSubmissionStorage:                                     # :122
    def __init__(self, pool, *, schema=DEFAULT_SCHEMA, table_name=DEFAULT_TABLE, tenant=None) -> None   # :140 (count 1 for `    def __init__(`)
    #   self.logger = logging.getLogger(__name__)                 # last line of __init__
    def _qualified(self, tenant) -> str                          # :170
    async def store(self, submission, *, tenant=None) -> str     # :313 — `async with self._pool.acquire() as conn: await conn.execute(self._insert_sql(...), ...)` :333-358
# table: form_uid UUID, data JSONB NOT NULL; index on form_uid
# FEAT-730 TASK-4631 adds (if merged): store_guarded(...) with `async with conn.transaction():` and _insert_params(...)
```
Integration-test convention: skip without `SCRATCH_DSN` (`tests/integration/test_unknown_fields_e2e.py:72-77`).

### Does NOT Exist
- ~~A transaction in `store()`~~ — added here only when a store is attached (G5: unchanged otherwise).
- ~~`references_blob` / any jsonpath query~~ — added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/integration/test_pending_uploads_pg.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage.store"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `self._pending = None` at the end of `__init__` and `attach_pending_uploads` — *why*: hosts build the storage before `setup_form_api`.
2. Add `_clear_pending` — *why*: one helper for `store()` and `store_guarded()` (AC9).
3. Branch `store()` on `self._pending` — *why*: G5 (no transaction when unattached) vs AC4 (same transaction when attached).
4. Add `references_blob` — *why*: the reaper's safety check (TASK-4641).
5. Integration tests with mutation checks.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self.logger = logging.getLogger(__name__)' services/submissions.py)
# AFTER — insert below `        self.logger = logging.getLogger(__name__)` (last line of __init__, verified: :157):
        self._pending: Any = None  # FEAT-731 PendingUploadStore, attached late

    def attach_pending_uploads(self, store: Any) -> None:
        """Late-bind the pending-upload registry (FEAT-731). None detaches."""
        self._pending = store

    async def _clear_pending(self, conn: Any, submission: FormSubmission, tenant: str | None) -> None:
        """Delete pending rows for the submission's blob_refs on ``conn`` (inside the caller's
        transaction), under a SAVEPOINT so a missing pending table never aborts the INSERT."""
        if self._pending is None:
            return
        from .pending_uploads import iter_blob_refs

        refs = iter_blob_refs(submission.data)
        if not refs:
            return
        # FILL IN: async with conn.transaction():  (nested = SAVEPOINT in asyncpg)
        #              await self._pending.clear(refs, tenant=tenant, conn=conn)
        #          except Exception as exc: if not is_undefined_table(exc): raise; self.logger.debug(...)
        #          — bounded by AC4 / spec §2.3 (a missing pending table must never abort the submission)
```
```python
# occurrences: 1 (verified: grep -c '    async def store(' services/submissions.py)
# Inside store() (:313), REPLACE the body's `async with self._pool.acquire() as conn:` + single execute with:
        async with self._pool.acquire() as conn:
            if self._pending is None:
                await conn.execute(self._insert_sql(effective_tenant), <the existing 20 params>)   # unchanged (G5)
            else:
                async with conn.transaction():
                    await conn.execute(self._insert_sql(effective_tenant), <the existing 20 params>)
                    await self._clear_pending(conn, submission, effective_tenant)
# FILL IN: if FEAT-730's `_insert_params` exists, use `*self._insert_params(submission, effective_tenant)`
# for both; otherwise keep the literal parameter list (do not duplicate it — extract a local tuple).
```
```python
# AFTER store() — new method
    async def references_blob(self, form_uid: uuid.UUID, blob_ref: str, *, tenant: str | None) -> bool:
        """True when any stored submission of form_uid references blob_ref anywhere in data."""
        sql = (
            f"SELECT EXISTS (SELECT 1 FROM {self._qualified(tenant)} WHERE form_uid = $1 "
            "AND jsonb_path_exists(data, '$.** ? (@.blob_ref == $ref)', jsonb_build_object('ref', $2::text)))"
        )
        async with self._pool.acquire() as conn:
            return bool(await conn.fetchval(sql, form_uid, blob_ref))
```
FILL IN (AC9): if `store_guarded` exists, call `await self._clear_pending(conn, submission, effective_tenant)`
right after its INSERT, inside its `conn.transaction()`; add a test that pins it.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def is_unique_violation(exc: Exception) -> bool:' services/_db_utils.py)
# AFTER the end of is_unique_violation (file end) append:
_UNDEFINED_TABLE_CODE = "42P01"


def is_undefined_table(exc: Exception) -> bool:
    """True when ``exc`` is a Postgres undefined-table error (driver-agnostic, FEAT-731)."""
    # FILL IN: mirror is_unique_violation: type name "UndefinedTableError", sqlstate/pgcode == 42P01,
    # or "does not exist" + "relation" in the lowered text.
    return False
```

### `packages/parrot-formdesigner/tests/integration/test_pending_uploads_pg.py` (CREATE)
```python
"""FEAT-731 — clear-on-store and references_blob against real Postgres (skips without SCRATCH_DSN)."""
import os
import pytest

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")
pytestmark = pytest.mark.skipif(not _SCRATCH_DSN, reason="SCRATCH_DSN not set (scratch Postgres required)")

# FILL IN: fixture with a scratch schema, FormSubmissionStorage + PendingUploadStore initialized there.

async def test_store_clears_pending_in_same_transaction(): ...   # mutation: drop the clear / move it outside -> RED
async def test_store_rolls_back_clear_on_insert_failure(): ...   # duplicate submission_id -> pending row still present
async def test_store_with_missing_pending_table(): ...           # attached store, table absent -> submission committed
async def test_store_without_pending_unchanged(): ...            # nothing attached -> no transaction, no clear (G5)
async def test_references_blob_jsonpath(): ...                   # nested list in a group -> True; other form_uid -> False; prefix ref -> False
```

### FILL IN checklist
- [ ] `is_undefined_table` in `_db_utils.py` (SQLSTATE 42P01 / `UndefinedTableError` name / "does not exist" text)
- [ ] SAVEPOINT + undefined-table handling
- [ ] `store()` branching without duplicating the params
- [ ] AC9 wiring if `store_guarded` exists (note the outcome in the Completion Note)
- [ ] Integration tests (run with SCRATCH_DSN; a skip is not acceptance)

---

## Acceptance Criteria

- [ ] Unattached `store()` issues the same single statement (AC1/G5).
- [ ] Attached: clear in the INSERT's transaction; failed INSERT leaves rows (AC4).
- [ ] Direct `store()` callers get the clear with no host code (AC5).
- [ ] `references_blob` correct for nested envelopes (reaper safety check).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/integration/test_pending_uploads_pg.py -q`
- `pytest packages/parrot-formdesigner/tests/test_submission_jsonb_shape.py -q`

---

## Test Specification

Spec §4 Integration rows (minus the reaper concurrency test, which is TASK-4641's).

---

## Agent Instructions

1. Feature worktree; TASK-4638 `done`. Check whether FEAT-730 is merged (store_guarded / _insert_params).
2. Implement; run Validation Commands WITH `SCRATCH_DSN`; commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4640 formdesigner-orphan-upload-cleanup verified`.

---

## Completion Note

*(Agent fills this in when done — state whether AC9 was wired here or left to FEAT-730)*
