# TASK-4641: Strict blob delete + `PendingUploadReaper`

**Feature**: FEAT-731 — FormDesigner orphan upload cleanup
**Spec**: `sdd/specs/formdesigner-orphan-upload-cleanup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4638, TASK-4640
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / §2.5–2.6. The host (FieldSync FEAT-801) runs `reap_once`
nightly per tenant. Expired rows (48 h for a public form, 7 days otherwise —
by FORM, Juan 2026-10-22) are deleted with their blob and thumbnail, unless a
stored submission still references the blob (then only the row goes). Today
`delete()` swallows every backend error, so the reaper could never see a
failure: add `strict=True`.

---

## Scope

- `AbstractBlobStorage.delete(blob_ref, *, strict: bool = False)` and the manager-backed impl: `strict=True` re-raises non-"missing" errors; default path byte-identical.
- `PendingUploadReaper(pending, blob_storage, submissions).reap_once(*, tenant, public_form_ttl=DEFAULT_PUBLIC_FORM_TTL, ttl=DEFAULT_TTL, batch=500) -> ReapResult` in `services/pending_uploads.py`.
- Unit tests + one Postgres concurrency test.

**NOT in scope**: scheduling (host), wiring (TASK-4642).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py` | MODIFY | `strict` kwarg on both `delete` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/pending_uploads.py` | MODIFY | add `PendingUploadReaper` |
| `packages/parrot-formdesigner/tests/unit/services/test_pending_upload_reaper.py` | CREATE | reaper + strict delete tests |
| `packages/parrot-formdesigner/tests/integration/test_pending_upload_reaper_pg.py` | CREATE | SKIP LOCKED concurrency |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `28b3be0ac`.

### Existing Signatures to Use
```python
# services/blob_storage.py
class AbstractBlobStorage(ABC):                                  # :119
    @abstractmethod
    async def delete(self, blob_ref: str) -> None:               # :169 (1st of 2) — "Idempotent — no error if missing"
class _ManagerBackedBlobStorage(AbstractBlobStorage):            # :199
    def _from_ref(self, blob_ref) -> str                         # :254 — raises ValueError on scheme mismatch
    async def delete(self, blob_ref: str) -> None:               # :323 (2nd of 2)
    #   key = self._from_ref(blob_ref); try: await self._manager.delete_file(key)
    #   except FileNotFoundError: return
    #   except Exception as exc: err_code in ("NoSuchKey","404") -> return; else logger.warning (swallowed)   :324-341
# Only these two delete implementations exist in packages/ (verified grep); test fakes may define their own.

# services/pending_uploads.py — from TASK-4638: PendingUploadStore.expired(..., conn=), delete_rows, ReapResult,
#   DEFAULT_PUBLIC_FORM_TTL, DEFAULT_TTL
# services/submissions.py — from TASK-4640: FormSubmissionStorage.references_blob(form_uid, blob_ref, *, tenant) -> bool
```

### Does NOT Exist
- ~~`delete(..., strict=)`~~ — added here.
- ~~A scheduler in parrot-formdesigner~~ — the host schedules `reap_once`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/pending_uploads.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_pending_upload_reaper.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/integration/test_pending_upload_reaper_pg.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py#AbstractBlobStorage.delete",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py#_ManagerBackedBlobStorage.delete"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `strict` kwarg on both `delete` signatures — *why*: AC7; default unchanged for every caller.
2. `PendingUploadReaper` appended to `pending_uploads.py` — *why*: spec §2.5 algorithm.
3. Tests (fake blob storage; one PG concurrency test).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '    async def delete(self, blob_ref: str) -> None:' services/blob_storage.py)
# Both occurrences (abstract :169 under @abstractmethod; manager-backed :323 followed by
# `        key = self._from_ref(blob_ref)`) become:
    async def delete(self, blob_ref: str, *, strict: bool = False) -> None:
# Abstract docstring: add "strict: re-raise backend errors other than 'missing' (FEAT-731 reaper)."
# Manager-backed: in the final `except Exception` branch, after the NoSuchKey/404 return:
            if strict:
                raise
# (keep the existing logger.warning for the non-strict path, byte-identical)
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/pending_uploads.py` (MODIFY)
```python
# APPEND at end of module (after PendingUploadStore from TASK-4638)
class PendingUploadReaper:
    """Delete expired, unreferenced pending uploads for one tenant (FEAT-731). Host-scheduled."""

    def __init__(self, pending: PendingUploadStore, blob_storage: Any, submissions: Any) -> None:
        self._pending = pending
        self._blobs = blob_storage          # AbstractBlobStorage
        self._submissions = submissions     # FormSubmissionStorage (references_blob)
        self.logger = logging.getLogger(__name__)

    async def reap_once(self, *, tenant: str, public_form_ttl: timedelta = DEFAULT_PUBLIC_FORM_TTL,
                        ttl: timedelta = DEFAULT_TTL, batch: int = 500) -> ReapResult:
        """Spec §2.5: select expired rows (SKIP LOCKED), safety-check, delete blob+thumbnail, drop row."""
        result = ReapResult()
        # FILL IN: rows = expired(...) inside a short read transaction with FOR UPDATE SKIP LOCKED;
        # per row: if await self._submissions.references_blob(row.form_uid, row.blob_ref, tenant=tenant):
        #   delete_rows([row.blob_ref]); still_referenced += 1; continue
        # try: await self._blobs.delete(row.blob_ref, strict=True); thumbnail likewise when set;
        #   delete_rows([row.blob_ref]); deleted += 1
        # except ValueError (scheme mismatch, e.g. temp://) or any Exception: failed += 1, logger.warning,
        #   row KEPT for the next run. Never raise — bounded by AC6.
        return result
```

### `packages/parrot-formdesigner/tests/unit/services/test_pending_upload_reaper.py` (CREATE)
```python
"""FEAT-731 — strict delete + reaper outcomes (fake blob storage / fake stores)."""
async def test_delete_strict(): ...                 # strict re-raises a 500-type error; NoSuchKey/FileNotFound silent; non-strict unchanged
async def test_reaper_ttls_and_outcomes(): ...      # public-form row 49 h deleted, 47 h kept; non-public 6 d kept / 8 d deleted;
                                                    # referenced -> still_referenced, blob untouched; delete failure -> row kept, failed
async def test_reaper_bad_scheme_counts_failed(): ...
async def test_reaper_deletes_thumbnail_too(): ...
```

### `packages/parrot-formdesigner/tests/integration/test_pending_upload_reaper_pg.py` (CREATE)
```python
"""FEAT-731 — two concurrent reap_once process each row once (skips without SCRATCH_DSN)."""
async def test_reaper_skip_locked_concurrent(): ...
```

### FILL IN checklist
- [ ] `reap_once` body — AC6
- [ ] TTL fixtures without sleeping (insert rows with explicit `uploaded_at`)
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] `reap_once` deletes blob + thumbnail + row for expired unreferenced rows; 48 h public / 7 d otherwise (AC6).
- [ ] Referenced blob → only the row dropped (AC6).
- [ ] Delete failure keeps the row (AC6, AC7).
- [ ] Non-strict `delete()` unchanged (AC7).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_pending_upload_reaper.py -q`
- `pytest packages/parrot-formdesigner/tests/integration/test_pending_upload_reaper_pg.py -q`

---

## Test Specification

Spec §4 rows `test_delete_strict`, `test_reaper_ttls_and_outcomes`, `test_reaper_bad_scheme_counts_failed`, `test_reaper_skip_locked_concurrent`.

---

## Agent Instructions

1. Feature worktree; TASK-4638 and TASK-4640 `done`.
2. Implement; run Validation Commands (PG test with `SCRATCH_DSN`); commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4641 formdesigner-orphan-upload-cleanup verified`.

---

## Completion Note

*(Agent fills this in when done)*
