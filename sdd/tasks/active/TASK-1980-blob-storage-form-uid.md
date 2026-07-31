# TASK-1980: BlobStorage key pattern update

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1972
**Assigned-to**: unassigned

---

## Context

The BlobStorage service uses `form_id` (mutable slug) in object keys for
storing file uploads attached to form fields. If a form is renamed, existing
blob keys become orphaned. By keying on `form_uid` (immutable UUID) instead,
blobs remain accessible regardless of slug renames. Implements Module 8 from
the spec.

---

## Scope

- Add `form_uid: str` field to `BlobMetadata` Pydantic model:
  - Required field (no default).
  - Positioned before `form_id` in field order.
- Update `_build_key()` method in `_ManagerBackedBlobStorage`:
  - Change key construction from `f"{self._prefix}{metadata.form_id}/..."` to
    `f"{self._prefix}{metadata.form_uid}/..."`.
- Keep `form_id` on `BlobMetadata` for human-readable reference / logging,
  but it is no longer used in key construction.

**NOT in scope**: Storage layer (TASK-1974), migration of existing blob keys
(would require a separate data migration), submissions (TASK-1979).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py` | MODIFY | Add `form_uid` to `BlobMetadata`, update `_build_key()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # verified: used in blob_storage.py
```

### Existing Signatures to Use
```python
# services/blob_storage.py:55
class BlobMetadata(BaseModel):
    form_id: str                         # line 69
    field_id: str                        # line 70
    # ... other fields

# services/blob_storage.py:180
class _ManagerBackedBlobStorage:
    # _build_key: line 211
    def _build_key(self, metadata: BlobMetadata, blob_id: str) -> str: ...
        # Returns: f"{self._prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}"
        # at line 220
```

### Does NOT Exist
- ~~`BlobMetadata.form_uid`~~ — does not exist. This task adds it.
- ~~Any UUID-based key construction in blob_storage.py~~ — all keys use `form_id`.

---

## Implementation Notes

### Model change
```python
class BlobMetadata(BaseModel):
    form_uid: str = Field(..., description="Immutable UUID of the parent form")
    form_id: str = Field(..., description="Human-readable form slug (for logging)")
    field_id: str
    # ... rest unchanged
```

### Key construction change
```python
def _build_key(self, metadata: BlobMetadata, blob_id: str) -> str:
    # BEFORE:
    # return f"{self._prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}"
    # AFTER:
    return f"{self._prefix}{metadata.form_uid}/{metadata.field_id}/{blob_id}"
```

### Callers of `BlobMetadata`
Grep for all instantiations of `BlobMetadata` across the codebase. Each caller
must be updated to pass `form_uid`. Likely callers:
- `FormAPIHandler` (handlers.py) — when handling file uploads.
- Any test fixtures that construct `BlobMetadata`.

### Key Constraints
- Existing blob keys (using `form_id`) will NOT be migrated by this task.
  A separate data migration would be needed for production. Document this
  in the completion note.
- `form_id` remains on `BlobMetadata` — it is just no longer used in keys.

---

## Acceptance Criteria

- [ ] `BlobMetadata` has `form_uid: str` field
- [ ] `_build_key()` uses `metadata.form_uid` instead of `metadata.form_id`
- [ ] All callers of `BlobMetadata(...)` updated to pass `form_uid`
- [ ] `form_id` retained on `BlobMetadata` for backward compatibility
- [ ] Key format is `{prefix}{form_uid}/{field_id}/{blob_id}`

---

## Test Specification
```python
import pytest
from parrot_formdesigner.services.blob_storage import BlobMetadata

def test_blob_metadata_has_form_uid():
    """BlobMetadata includes form_uid field."""
    meta = BlobMetadata(
        form_uid="550e8400-e29b-41d4-a716-446655440000",
        form_id="my-form",
        field_id="photo"
    )
    assert meta.form_uid == "550e8400-e29b-41d4-a716-446655440000"

def test_build_key_uses_form_uid():
    """_build_key constructs key using form_uid, not form_id."""
    meta = BlobMetadata(
        form_uid="550e8400-e29b-41d4-a716-446655440000",
        form_id="my-form",
        field_id="photo"
    )
    # Mock or instantiate storage to test _build_key
    # Expected key: "{prefix}550e8400-e29b-41d4-a716-446655440000/photo/{blob_id}"
    pass

def test_blob_metadata_requires_form_uid():
    """BlobMetadata raises validation error without form_uid."""
    with pytest.raises(Exception):
        BlobMetadata(form_id="my-form", field_id="photo")

def test_key_stability_across_form_rename():
    """Changing form_id does not change the blob key."""
    meta1 = BlobMetadata(form_uid="uid-123", form_id="old-name", field_id="photo")
    meta2 = BlobMetadata(form_uid="uid-123", form_id="new-name", field_id="photo")
    # Both should produce the same key since form_uid is the same
    # key1 = storage._build_key(meta1, "blob-1")
    # key2 = storage._build_key(meta2, "blob-1")
    # assert key1 == key2
    pass
```

---

## Agent Instructions

1. Read this task file and the spec (Module 8).
2. Read `services/blob_storage.py` in full.
3. Verify TASK-1972 is complete (`FormSchema.form_uid` exists).
4. Grep for all instantiations of `BlobMetadata` across the codebase.
5. Implement all scope items, including updating callers.
6. Run existing tests: `pytest packages/parrot-formdesigner/tests/ -v -k blob`
7. Add new tests per test specification.
8. Commit with message: `sdd: TASK-1980 — BlobStorage key pattern to form_uid`
9. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
