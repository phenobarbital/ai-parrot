# TASK-2002: Blob storage keys + upload route on field_uid

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1997
**Assigned-to**: unassigned

---

## Context

Implements Module 8 of FEAT-393 (spec §3, blueprint §9). Blob object keys
stop embedding the editable `field_id` — renames no longer orphan uploads.
The upload endpoint (the only route with a field path param) switches to
`{field_uid}`.

---

## Scope

- `BlobMetadata`: add `field_uid: uuid.UUID`; keep `field_id: str`
  (descriptive metadata). (`form_uid` type handled by TASK-1995.)
- `_build_key`: `{prefix}{form_uid}/{field_uid}/{blob_id}`.
- `_from_ref`: UNCHANGED (parses refs opaquely — old refs stay resolvable).
- Route: `POST {bp}/forms/{form_uid}/fields/{field_uid}/upload`.
- `api/uploads.py`: `extract_uid(request, "field_uid")` (400 invalid),
  `find_field_by_uid` (404 unknown); populate `BlobMetadata.field_uid` and
  `field_id` from the found field; `RestCallbackInput` gains
  `field_uid: uuid.UUID`, keeps `field_id`.
- Add `extract_uid(request, param)` helper beside `extract_form_uid`.
- Update backend docstrings (s3/gs/file/temp key patterns).
- Spec §4 Module 8 tests.

**NOT in scope**: rewriting existing stored object keys (explicitly forbidden
— migration only REPORTS legacy keys, TASK-2008).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py` | MODIFY | BlobMetadata, _build_key, docstrings |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py` | MODIFY | path param, lookups, metadata |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | route path (:261) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/rest_field_resolver.py` | MODIFY | RestCallbackInput.field_uid |
| `packages/parrot-formdesigner/tests/unit/` | MODIFY/CREATE | key + route tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.blob_storage import BlobMetadata  # :55-74
from parrot_formdesigner.core.resolution import find_field_by_uid   # TASK-1997
```

### Existing Signatures to Use
```python
# services/blob_storage.py
class BlobMetadata(BaseModel):        # :55-74 — form_id (:69), field_id (:70), extra="forbid"
class _ManagerBackedBlobStorage(AbstractBlobStorage):   # :180
    def _build_key(self, metadata: BlobMetadata) -> str:  # :211-220
        blob_id = str(uuid.uuid4())
        return f"{self._prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}"  # :220
    def _to_ref(self, key: str) -> str        # :222-230
    def _from_ref(self, blob_ref: str) -> str # :232-254 — DO NOT TOUCH
    async def put(self, stream, *, metadata: BlobMetadata) -> str  # :258; key = self._build_key(metadata) (:274)
# pre_persist_hook / PrePersistContext (:270-272) — unchanged

# api/uploads.py
# field_id: str = request.match_info["field_id"]  (:233)
# field lookup: `if item.field_id == field_id` (:249); 404 (:256); 400 non-REST (:260)
# BlobMetadata(form_id=..., field_id=field_id, ...) (:336-342)
# RestCallbackInput(form_id=..., field_id=field_id, ...) (:390-398)

# api/routes.py:261 — POST {bp}/forms/{form_id}/fields/{field_id}/upload
#   (FEAT-389 changes the form segment to {form_uid}; this task changes the field segment)

# services/rest_field_resolver.py
class RestCallbackInput(BaseModel):   # :207-231; field_id: str (:224) — passthrough payload only
```

### Does NOT Exist
- ~~field_id-based key parsing anywhere~~ — `_from_ref` treats keys opaquely; nothing decomposes `{form}/{field}/` segments back into ids
- ~~`extract_uid` helper~~ — created HERE (generalizes FEAT-389's `extract_form_uid`)
- ~~RestFieldResolver reads of `field_id`~~ — resolver passes payload wholesale; only ADD the field, no logic changes

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 8" blueprint.

### Key Constraints
- Old refs MUST remain resolvable: add an explicit test writing a blob under
  the legacy pattern (construct the key manually), storing its ref, and
  reading it back through `_from_ref` after the change.
- 404 body for unknown `field_uid` mirrors the current "Field not found"
  message shape (:256).
- The non-REST-field 400 check (:260) stays — lookup by uid, then same check.

### References in Codebase
- Backend docstring key patterns: s3 (:336), gs (:411), file (:469), temp (:520)

---

## Acceptance Criteria

- [ ] New uploads keyed `{prefix}{form_uid}/{field_uid}/{blob_id}`
- [ ] Legacy refs still resolve through `_from_ref` (regression test)
- [ ] Route + handler use `{field_uid}`: invalid UUID → 400, unknown → 404, non-REST field → 400
- [ ] `BlobMetadata` carries both `field_uid` and `field_id`
- [ ] `RestCallbackInput` gains `field_uid`, keeps `field_id`
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_blob_uid_keys.py
def test_build_key_uses_uids(): ...
def test_legacy_ref_still_resolvable(): ...
async def test_upload_route_invalid_uuid_400(client): ...
async def test_upload_route_unknown_uid_404(client): ...
async def test_upload_metadata_carries_both_ids(client): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 8; verify TASK-1997 completed.
2. **Verify the contract** — FEAT-389 touches blob_storage/routes; re-check anchors.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
