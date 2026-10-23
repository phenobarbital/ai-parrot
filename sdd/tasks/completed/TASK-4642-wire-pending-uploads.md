# TASK-4642: Wire `setup_form_api(pending_uploads=…)`, sink-path clear, exports

**Feature**: FEAT-731 — FormDesigner orphan upload cleanup
**Spec**: `sdd/specs/formdesigner-orphan-upload-cleanup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4638, TASK-4640
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The host (FieldSync FEAT-801) passes a pool-backed
`PendingUploadStore(pool, table_name="fs_pending_uploads")` to
`setup_form_api(pending_uploads=…)`. That must (a) publish it at
`app["form_pending_uploads"]` for the upload handler (TASK-4639) and (b) attach
it to the `submission_storage` it receives so `store()` clears (TASK-4640).
Forms with `persistence` (FEAT-457 sinks) never call the generic storage, so the
pipeline clears after a successful `sink.write` (best-effort, not transactional).

---

## Scope

- `setup_form_api`: kwarg `pending_uploads: "PendingUploadStore | None" = None`; ONE call to a new helper `_wire_pending_uploads(app, submission_storage, pending_uploads)` (setup_form_api is already over the complexity budget).
- Pipeline: after `await sink.write(submission, payload)`, best-effort clear when the generic storage has a store attached.
- Export `PendingUploadStore`, `PendingUploadReaper`, `PendingUpload`, `ReapResult`, `iter_blob_refs`, `DEFAULT_PUBLIC_FORM_TTL`, `DEFAULT_TTL` from `parrot_formdesigner.services`.
- Tests.

**NOT in scope**: docs/version (TASK-4643).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | kwarg + `_wire_pending_uploads` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | clear after sink write |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | MODIFY | exports |
| `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api_pending.py` | CREATE | wiring + sink-path tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `28b3be0ac`
> (FEAT-730 TASK-4634/4635 also add kwargs to `setup_form_api` — re-grep the signature tail).

### Existing Signatures to Use
```python
# api/routes.py
def _stash_without_clobbering(app, key, value) -> None                    # :167-189 (explicit wins; None only ensures the key)
def setup_form_api(app, registry, *, client=None, submission_storage=None, ..., teams_renderer=None,
                   llm_quota: "LLMQuota | None" = None) -> None           # :192-216 (last kwarg today: llm_quota)
#   _stash_without_clobbering(app, "rest_resolver", resolver)              :310 (count 1)
# if TYPE_CHECKING:                                                        :57

# services/submission_pipeline.py
#   await sink.write(submission, payload)                                  :379 (count 1, inside the persistence branch)
#   self.submission_storage                                                (pipeline attribute)
# FormSubmissionStorage._pending — attached store (TASK-4640)

# services/__init__.py
from .submissions import (                                                 # :26 (count 1)
    CORE_METADATA_COLUMNS, FormSubmission, FormSubmissionStorage,
)
__all__ = [ ..., "FormSubmissionStorage", ... ]                            # :42
```

### Does NOT Exist
- ~~`app["form_pending_uploads"]`~~ — published here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_setup_form_api_pending.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#_stash_without_clobbering",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline.submit"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Signature kwarg + one helper call after the `rest_resolver` stash — *why*: keep setup_form_api's complexity flat.
2. Sink-path best-effort clear — *why*: sink forms never reach `store()`.
3. Exports; tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# Signature: AFTER the last kwarg of setup_form_api (today `    llm_quota: "LLMQuota | None" = None,` :216 —
# FILL IN: after FEAT-730 it may be `on_submitted`/`tenant_scoped_submissions`; append after whatever is last):
    pending_uploads: "PendingUploadStore | None" = None,
```
```python
# occurrences: 1 (verified: grep -c '    _stash_without_clobbering(app, "rest_resolver", resolver)' api/routes.py)
# AFTER — insert below that line (verified: :310)
    _wire_pending_uploads(app, submission_storage, pending_uploads)
```
```python
# new helper — insert directly above `def setup_form_api(` (count 1)
def _wire_pending_uploads(app: web.Application, submission_storage: Any, pending_uploads: Any) -> None:
    """FEAT-731: publish the pending-upload store for /file-upload and attach it to the generic storage."""
    _stash_without_clobbering(app, "form_pending_uploads", pending_uploads)
    if pending_uploads is not None and submission_storage is not None:
        submission_storage.attach_pending_uploads(pending_uploads)
```
Add `from ..services.pending_uploads import PendingUploadStore` under `if TYPE_CHECKING:` (:57).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                    await sink.write(submission, payload)' services/submission_pipeline.py)
# AFTER — insert below that line (verified: :379)
                    await self._clear_pending_after_sink(submission, tenant)
```
```python
# new private method — insert directly above `    def attach_verdicts(` (count 1)
    async def _clear_pending_after_sink(self, submission: FormSubmission, tenant: str | None) -> None:
        """FEAT-731: best-effort pending-upload clear for sink forms (not transactional with the sink)."""
        pending = getattr(self.submission_storage, "_pending", None)
        if pending is None:
            return
        from .pending_uploads import iter_blob_refs

        try:
            await pending.clear(iter_blob_refs(submission.data), tenant=tenant)
        except Exception as exc:  # noqa: BLE001 — the sink write already succeeded
            self.logger.warning("pending-upload clear after sink write failed for %s: %s", submission.submission_id, exc)
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .submissions import (' services/__init__.py)
# BEFORE — insert above `from .submissions import (` (verified: :26)
from .pending_uploads import (
    DEFAULT_PUBLIC_FORM_TTL,
    DEFAULT_TTL,
    PendingUpload,
    PendingUploadReaper,
    PendingUploadStore,
    ReapResult,
    iter_blob_refs,
)
# and add the seven names to __all__ (keep its existing ordering style).
```

### `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api_pending.py` (CREATE)
```python
"""FEAT-731 — setup_form_api wiring + sink-path clear."""
def test_setup_form_api_wires_pending(): ...       # kwarg -> app["form_pending_uploads"] + attach_pending_uploads called; absent -> key None, nothing attached
async def test_sink_path_clears_after_write(): ... # persistence form -> clear after sink.write; sink error -> no clear
def test_services_exports(): ...
```

### FILL IN checklist
- [ ] Signature tail after FEAT-730
- [ ] `__all__` additions
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] With `pending_uploads`, the upload handler records and `store()` clears (end-to-end with TASK-4639/4640).
- [ ] Without it, nothing changes (AC1).
- [ ] Sink forms clear best-effort after the write.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api_pending.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`

---

## Test Specification

Spec §4 rows `test_setup_form_api_wires_pending`, `test_sink_path_clears_after_write`.

---

## Agent Instructions

1. Feature worktree; TASK-4638 and TASK-4640 `done`.
2. Re-grep `setup_form_api`'s signature (FEAT-730 adds kwargs); implement; commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4642 formdesigner-orphan-upload-cleanup verified`.

---

## Completion Note

Done. `setup_form_api(pending_uploads=)` via `_wire_pending_uploads`; sink-path best-effort clear after `sink.write`; services exports. Tests: 3 new + test_setup_form_api (baseline 3 passed) + test_submit_path_branch pass (15 total). Mutations RED: wiring removed (test_setup_form_api_wires_pending), sink clear removed (test_sink_path_clears_after_write).
