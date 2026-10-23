# TASK-4638: `PendingUploadStore`, models, `iter_blob_refs`, TTL constants

**Feature**: FEAT-731 — FormDesigner orphan upload cleanup
**Spec**: `sdd/specs/formdesigner-orphan-upload-cleanup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / §2.1. Blobs uploaded through `/file-upload` that are never
submitted stay in S3 forever (`api/file_upload.py:75` "no expiry/GC in V1").
The fix (Juan, 2026-10-22, Option 3) is a per-tenant registry of pending
uploads, cleared when a submission is stored and swept by a nightly reaper.
This task creates the registry store and its helpers. TTL is decided by the
FORM, never by the caller: 48 h for a public form, 7 days otherwise.

---

## Scope

- Create `services/pending_uploads.py` with `DEFAULT_TABLE`, `DEFAULT_PUBLIC_FORM_TTL`, `DEFAULT_TTL`,
  `PendingUpload`, `ReapResult`, `iter_blob_refs()`, and `PendingUploadStore`
  (`initialize`, `record`, `clear`, `expired`, `delete_rows`).
- Unit tests for `iter_blob_refs` and the SQL the store emits (fake connection).

**NOT in scope**: `PendingUploadReaper` (TASK-4641, same file — added after this task),
recording on upload (TASK-4639), clearing on store (TASK-4640), wiring (TASK-4642).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/pending_uploads.py` | CREATE | store, models, helpers |
| `packages/parrot-formdesigner/tests/unit/services/test_pending_uploads.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `28b3be0ac`.

### Verified Imports
```python
from ._identifiers import qualified_table, validate_identifier   # services/submissions.py:25 (same package)
```

### Existing Signatures to Use
```python
# services/submissions.py — the SQL-style reference to copy
DEFAULT_SCHEMA = "navigator"; DEFAULT_TABLE = "form_data"        # :31-32
class FormSubmissionStorage:                                     # :122
    def __init__(self, pool, *, schema=DEFAULT_SCHEMA, table_name=DEFAULT_TABLE, tenant=None)  # :140 — validate_identifier on schema/table/tenant
    def _resolve_schema(self, tenant) -> str                     # :163
    def _qualified(self, tenant) -> str                          # :170 — qualified_table(schema, table)
    async def initialize(self, *, tenant=None) -> None           # :297 — CREATE ... IF NOT EXISTS via pool.acquire()
```

### Does NOT Exist
- ~~`PendingUploadStore`, `pending_uploads` table, `iter_blob_refs`~~ — created here.
- ~~An `anonymous` column / caller check~~ — NOT built; the column is `public_form` (form.is_public).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/pending_uploads.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_pending_uploads.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with constants, models and `iter_blob_refs` — *why*: every other FEAT-731 task imports them.
2. Implement `PendingUploadStore` mirroring `FormSubmissionStorage`'s identifier handling — *why*: hosts pass `table_name="fs_pending_uploads"` (FieldSync, FEAT-455 naming).
3. Unit tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/pending_uploads.py` (CREATE)
```python
"""Pending-upload registry (FEAT-731).

One row per blob returned by ``/file-upload`` that no stored submission references yet.
Cleared by ``FormSubmissionStorage.store()`` in the INSERT's transaction; swept by
``PendingUploadReaper`` (TTL by form: 48 h public / 7 days otherwise).
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from ._identifiers import qualified_table, validate_identifier

DEFAULT_SCHEMA = "navigator"
DEFAULT_TABLE = "pending_uploads"          # FieldSync passes table_name="fs_pending_uploads"
DEFAULT_PUBLIC_FORM_TTL = timedelta(hours=48)
DEFAULT_TTL = timedelta(days=7)


class PendingUpload(BaseModel):
    """One pending (not yet submitted) uploaded blob."""

    blob_ref: str
    thumbnail_ref: str | None = None
    form_uid: uuid.UUID
    field_uid: uuid.UUID
    tenant: str
    public_form: bool                      # form.is_public at upload time
    uploaded_at: datetime | None = None    # None on record -> DB default now()


class ReapResult(BaseModel):
    """Outcome of one ``reap_once`` run."""

    deleted: int = 0
    failed: int = 0
    still_referenced: int = 0


def iter_blob_refs(data: Any) -> set[str]:
    """Every ``str`` value under a ``blob_ref`` key, walking dicts/lists recursively."""
    # FILL IN: recursive walk; covers FileEnvelope dicts, lists of envelopes and the legacy
    # {answer, blob_ref, display} item; non-str blob_ref values ignored — bounded by spec §2.3.
    return set()


class PendingUploadStore:
    """CRUD over ``<tenant>.<table>`` (default ``pending_uploads``)."""

    def __init__(self, pool: Any, *, schema: str = DEFAULT_SCHEMA, table_name: str = DEFAULT_TABLE) -> None:
        validate_identifier(schema, kind="schema")
        validate_identifier(table_name, kind="table")
        self._pool = pool
        self._schema = schema
        self._table = table_name
        self.logger = logging.getLogger(__name__)

    def _qualified(self, tenant: str | None) -> str:
        schema = validate_identifier(tenant, kind="tenant") if tenant is not None else self._schema
        return qualified_table(schema, self._table)

    async def initialize(self, *, tenant: str | None = None) -> None:
        """CREATE TABLE / INDEX IF NOT EXISTS in <tenant or schema> (DDL: spec §2.1)."""
        # FILL IN: blob_ref TEXT PK, thumbnail_ref TEXT, form_uid UUID NOT NULL, field_uid UUID NOT NULL,
        # tenant TEXT NOT NULL, public_form BOOLEAN NOT NULL, uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now();
        # index "idx_<table>_uploaded_at" on (uploaded_at). Index name via validate_identifier.

    async def record(self, entry: PendingUpload, *, tenant: str) -> None:
        """INSERT … ON CONFLICT (blob_ref) DO UPDATE SET uploaded_at = now(), thumbnail_ref = EXCLUDED.thumbnail_ref."""
        # FILL IN

    async def clear(self, blob_refs: Iterable[str], *, tenant: str | None, conn: Any | None = None) -> int:
        """DELETE … WHERE blob_ref = ANY($1); uses ``conn`` when given (caller's transaction). No-op on empty."""
        # FILL IN: refs = list(blob_refs); if not refs: return 0; run on conn or a pooled connection;
        # return the deleted row count parsed from the status string ("DELETE n").
        return 0

    async def expired(self, *, tenant: str, public_form_ttl: timedelta, ttl: timedelta, limit: int,
                      conn: Any | None = None) -> list[PendingUpload]:
        """Rows with (public_form AND uploaded_at < now()-public_form_ttl) OR
        (NOT public_form AND uploaded_at < now()-ttl), oldest first, FOR UPDATE SKIP LOCKED
        when ``conn`` is given (caller holds a transaction)."""
        # FILL IN
        return []

    async def delete_rows(self, blob_refs: Iterable[str], *, tenant: str) -> int:
        """Delete rows by blob_ref (pooled connection)."""
        return await self.clear(blob_refs, tenant=tenant)
```
**Why this shape**: names/defaults are fixed by the cross-repo contract with FieldSync
FEAT-801 (which calls `PendingUploadStore(pool, table_name="fs_pending_uploads")`).

### `packages/parrot-formdesigner/tests/unit/services/test_pending_uploads.py` (CREATE)
```python
"""FEAT-731 — PendingUploadStore + iter_blob_refs (fake connection; real SQL in TASK-4640's PG tests)."""
from parrot_formdesigner.services.pending_uploads import PendingUploadStore, iter_blob_refs

def test_iter_blob_refs_shapes(): ...   # single, list, nested group/array, legacy item, non-str ignored, none -> empty
def test_store_rejects_bad_identifiers(): ...
async def test_record_is_upsert(): ...  # SQL contains ON CONFLICT (blob_ref) DO UPDATE
async def test_clear_empty_is_noop(): ...
async def test_clear_uses_given_conn(): ...
async def test_expired_query_uses_both_ttls(): ...
```

### FILL IN checklist
- [ ] `iter_blob_refs`
- [ ] `initialize` DDL, `record`, `clear`, `expired`
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] Module importable; constants 48 h / 7 days.
- [ ] `record` is an upsert (AC2 idempotent re-upload).
- [ ] `clear` honours a caller connection (needed by AC4).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_pending_uploads.py -q`

---

## Test Specification

Spec §4 row `test_iter_blob_refs_shapes` plus the store-SQL rows above.

---

## Agent Instructions

1. Feature worktree (`python -m scripts.sdd.ensure_worktree --slug formdesigner-orphan-upload-cleanup --feature-id FEAT-731`).
2. Implement; run Validation Commands; commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4638 formdesigner-orphan-upload-cleanup verified`.

---

## Completion Note

**Completed by**: sdd-worker (direct, no coder pool)
**Date**: 2026-10-22
**Notes**: Implemented as blueprinted. `PendingUploadStore.record` upserts with `COALESCE($7, now())` so `uploaded_at=None` falls to the DB default; `expired()` passes the two TTLs as `timedelta` -> `interval`; `FOR UPDATE SKIP LOCKED` only when a `conn` is supplied. Unit tests (8) pass; mutation-checked (upsert, walker, SKIP LOCKED). `ruff` is not installed in this venv, so only `black -l 120` was run.
**Deviations from spec**: none.
