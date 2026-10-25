# TASK-4639: Record pending uploads in `/file-upload` (+ thumbnail-cleanup fix)

**Feature**: FEAT-731 — FormDesigner orphan upload cleanup
**Spec**: `sdd/specs/formdesigner-orphan-upload-cleanup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4638
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / §2.2 and §2.7. Every envelope returned by `/file-upload`
must be recorded as pending (when the host configured a store at
`app["form_pending_uploads"]`, TASK-4642). Recording is fail-soft — the upload
always answers 200. A prior-blob replacement also drops the prior's row.
In passing, fix a live leak: the multi-file rejection cleanup passes the
thumbnail URL (not the ref) to `blob_storage.delete()`, which raises inside
`_from_ref` and is logged, so the thumbnail always leaks.

---

## Scope

- `_thumbnail_ref(thumbnail_url)` helper (the `ref` query param, unquoted).
- Record each returned envelope as `PendingUpload(..., tenant=<URL tenant>, public_form=bool(form.is_public))`.
- On a successful prior delete, `delete_rows([prior_blob_ref])`.
- Multi-file rejection cleanup deletes `orphan.blob_ref` and `_thumbnail_ref(orphan.thumbnail_url)`.
- Comment at `:75`: chunk-upload blobs remain out of v1 (Juan).
- Tests.

**NOT in scope**: the `app["form_pending_uploads"]` key wiring (TASK-4642).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py` | MODIFY | record, prior-row clear, thumbnail fix |
| `packages/parrot-formdesigner/tests/unit/api/test_file_upload_pending.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `28b3be0ac`
> (before FEAT-730 TASK-4633, which edits `:210` and `:238` of the same file — re-grep).

### Verified Imports
```python
from urllib.parse import quote, unquote             # api/file_upload.py:51
from .tenant import declared_tenant                 # api/file_upload.py:65
# TASK-4638: from ..services.pending_uploads import PendingUpload
```

### Existing Signatures to Use
```python
# api/file_upload.py
# leaves its entry and chunk blobs orphaned — no expiry/GC in V1.         :75 (comment, count 1)
async def handle_file_upload(request) -> web.Response                     # :169
#   tenant = declared_tenant(request)                                      :204  <- the URL tenant (record under it)
#   form = await registry.get(...); field = found[0]                       :210-218
#   for ref in (orphan.blob_ref, orphan.thumbnail_url):                    :291 (count 1) — BUG: URL passed to delete
#   result = envelopes[0] if single else envelopes                         :321
#   prior_blob_ref = request.headers.get("X-Parrot-Prior-Blob-Ref")       :325
#   if prior_blob_ref and prior_blob_ref not in written:                   :327 (count 1) — try: await blob_storage.delete(prior_blob_ref)
#   if isinstance(result, list):                                           :339 (count 1) — final response
async def _finalize_envelope(...)                                          # :540
#   thumbnail_url = f"{thumbnail_base_path}?ref={quote(thumbnail_ref, safe='')}"   :608
```
Test harness: `tests/unit/test_file_upload_handler.py:34-59` (`mock_blob_storage`, `_make_client`).

### Does NOT Exist
- ~~`FileEnvelope.thumbnail_ref`~~ — only `thumbnail_url`; the ref is its `ref` query param.
- ~~`is_anonymous_caller`~~ — not built; `public_form = form.is_public`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_file_upload_pending.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py#handle_file_upload"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `_thumbnail_ref` — *why*: the envelope carries the thumbnail only as a URL.
2. Fix the rejection cleanup loop — *why*: AC8 (mutation-checked).
3. Drop the prior's row after a successful prior delete — *why*: the replaced blob no longer exists.
4. Record before the final response, in a helper `_record_pending(request, form, field, tenant, result)` — *why*: keeps `handle_file_upload` inside the complexity budget; fail-soft (AC3).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'for ref in (orphan.blob_ref, orphan.thumbnail_url):' api/file_upload.py)
# REPLACE `                    for ref in (orphan.blob_ref, orphan.thumbnail_url):` (verified: :291) with:
                    for ref in (orphan.blob_ref, _thumbnail_ref(orphan.thumbnail_url)):
```
```python
# occurrences: 1 (verified: grep -c 'if prior_blob_ref and prior_blob_ref not in written:' api/file_upload.py)
# Inside that `if` block (verified: :327-337), after `            await blob_storage.delete(prior_blob_ref)`
# (still inside the try) add:
            await _forget_pending(request, [prior_blob_ref], tenant)
```
```python
# occurrences: 1 (verified: grep -c '    if isinstance(result, list):' api/file_upload.py)
# BEFORE — insert above `    if isinstance(result, list):` (verified: :339)
    await _record_pending(request, form, field, tenant, result)
```
```python
# new module-level helpers — insert directly above `async def _process_file_part(` (re-grep, count 1)
def _thumbnail_ref(thumbnail_url: str | None) -> str | None:
    """The `ref` query param of a thumbnail_url built by _finalize_envelope (:608), unquoted."""
    # FILL IN: urlparse + parse_qs; return unquote(ref) or None when absent/None.
    return None


async def _record_pending(request: web.Request, form: FormSchema, field: FormField, tenant: str,
                          result: FileEnvelope | list[FileEnvelope]) -> None:
    """Record every returned envelope as pending (FEAT-731). Fail-soft: never fails the upload."""
    store = request.app.get("form_pending_uploads")
    if store is None:
        return
    from ..services.pending_uploads import PendingUpload

    envelopes = result if isinstance(result, list) else [result]
    try:
        for env in envelopes:
            await store.record(
                PendingUpload(
                    blob_ref=env.blob_ref,
                    thumbnail_ref=_thumbnail_ref(env.thumbnail_url),
                    form_uid=form.form_uid,
                    field_uid=field.field_uid,
                    tenant=tenant,
                    public_form=bool(form.is_public),
                ),
                tenant=tenant,
            )
    except Exception as exc:  # noqa: BLE001 — the blob is merely untracked (today's state)
        logger.warning("Failed to record pending upload for %s: %s", form.form_uid, exc)


async def _forget_pending(request: web.Request, blob_refs: list[str], tenant: str) -> None:
    """Drop pending rows for blobs this request deleted. Fail-soft."""
    # FILL IN: store = request.app.get("form_pending_uploads"); if set: await store.delete_rows(...); log on error.
```
FILL IN: skip envelopes whose `blob_ref` is None (inline-only) when recording.
Update the `:75` comment: "…chunk blobs orphaned — no expiry/GC in V1 (chunk uploads remain out of scope of FEAT-731)."

### `packages/parrot-formdesigner/tests/unit/api/test_file_upload_pending.py` (CREATE)
```python
"""FEAT-731 — /file-upload records pending uploads."""
# FILL IN: harness from tests/unit/test_file_upload_handler.py:34-59 plus app["form_pending_uploads"] = fake store.

async def test_thumbnail_ref_from_url(): ...
async def test_upload_records_pending(): ...              # single + image_dropzone list; URL tenant (NOT X-Parrot-Tenant); public_form == form.is_public, same with/without session
async def test_upload_record_failure_is_soft(): ...       # store raises -> 200, envelope returned
async def test_prior_replacement_clears_prior_row(): ...
async def test_multi_file_rejection_deletes_thumbnail(): ...  # delete called with the THUMBNAIL REF; mutation: restore thumbnail_url -> RED
async def test_no_store_configured_unchanged(): ...
```

### FILL IN checklist
- [ ] `_thumbnail_ref`, `_forget_pending`, None-blob_ref skip
- [ ] Test bodies; mutation check for the thumbnail fix

---

## Acceptance Criteria

- [ ] One pending row per returned envelope under the URL tenant with `public_form` (AC2).
- [ ] Recording failure never fails the upload (AC3).
- [ ] Rejection cleanup deletes the thumbnail by ref (AC8, mutation-checked).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_file_upload_pending.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_file_upload_handler.py -q`

---

## Test Specification

Spec §4 Module 2 rows.

---

## Agent Instructions

1. Feature worktree; TASK-4638 `done`. If FEAT-730 already merged, re-grep (it edits this file).
2. Implement; run Validation Commands; commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4639 formdesigner-orphan-upload-cleanup verified`.

---

## Completion Note

**Completed by**: sdd-worker (direct)
**Date**: 2026-10-22
**Notes**: Implemented per blueprint: `_thumbnail_ref`, `_record_pending` (fail-soft, skips envelopes with no `blob_ref`), `_forget_pending`; rejection cleanup now deletes the thumbnail REF; prior-ref replacement also drops the prior's row (inside the existing try, so it only runs after the delete call returned). Chunk uploads (`_CHUNK_BUFFERS`) still out of scope (comment updated). 7 new tests + 11 existing `test_file_upload_handler.py` green. Mutation-checked (thumbnail URL restored, `public_form=True`, wrong tenant, no prior-row clear, narrowed except) -> each RED. Test harness registers the form under tenant `navigator`, so the URL tenant is `navigator` and `X-Parrot-Tenant: other` proves the URL tenant wins.
**Deviations from spec**: none. FEAT-730 (TASK-4633) edits `:210`/`:238` of this file on its own branch; my edits are confined to the blueprint anchors plus two new helpers above `_process_file_part`, so the merge should be local.
