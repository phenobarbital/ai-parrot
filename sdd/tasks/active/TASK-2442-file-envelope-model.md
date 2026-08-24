# TASK-2442: FileEnvelope Model & UPLOAD_FIELD_TYPES Constant

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-460. Every other task in this feature
imports or depends on the `FileEnvelope` Pydantic model and the
`UPLOAD_FIELD_TYPES` constant defined here. This task implements **Module 1**
from the spec.

---

## Scope

- Create `parrot_formdesigner/core/file_envelope.py` with:
  - `FileEnvelope` Pydantic model (`filename`, `content_type`, `size` required;
    `blob_ref`, `data_url`, `thumbnail_url`, `checksum` optional/nullable).
  - `UPLOAD_FIELD_TYPES: frozenset` containing `{FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD}`.
  - `is_single_cardinality(field_type: FieldType) -> bool` helper — returns `True`
    for FILE/IMAGE, `False` for IMAGE_DROPZONE/MULTI_UPLOAD.
- Write unit tests for the model, constant, and helper.

**NOT in scope**: FieldConstraints changes (TASK-2443), upload handler (TASK-2445),
validator updates (TASK-2447).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py` | CREATE | FileEnvelope model, UPLOAD_FIELD_TYPES, is_single_cardinality |
| `packages/parrot-formdesigner/tests/unit/test_file_envelope.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType  # core/types.py:16
```

### Existing Signatures to Use
```python
# parrot_formdesigner/core/types.py:16-66
class FieldType(str, Enum):
    FILE = "file"                      # line 29
    IMAGE = "image"                    # line 30
    IMAGE_DROPZONE = "image_dropzone"  # line 65
    MULTI_UPLOAD = "multi_upload"      # line 66
```

### Does NOT Exist
- ~~`parrot_formdesigner/core/file_envelope.py`~~ — does not exist yet; this task creates it
- ~~`FileEnvelope`~~ — does not exist anywhere in the codebase
- ~~`UPLOAD_FIELD_TYPES`~~ — does not exist anywhere
- ~~`FieldType.DOCUMENT`~~ — not a real enum member
- ~~`FieldType.MEDIA_UPLOAD`~~ — not a real enum member

---

## Implementation Notes

### Pattern to Follow
```python
# Follow BlobMetadata pattern from services/blob_storage.py:55-87
from pydantic import BaseModel, ConfigDict, Field

class FileEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(..., description="Original filename with extension")
    content_type: str = Field(..., description="MIME type of the file")
    size: int = Field(..., ge=0, description="File size in bytes")
    blob_ref: str | None = Field(default=None, description="Server storage reference")
    data_url: str | None = Field(default=None, description="Inline base64 data URL")
    thumbnail_url: str | None = Field(default=None, description="Thumbnail URL (images)")
    checksum: str | None = Field(default=None, description="SHA-256 hash")
```

### Key Constraints
- `extra="forbid"` — reject unexpected fields
- `size` must have `ge=0` constraint
- All optional fields default to `None`
- Google-style docstrings on the class and all public functions

---

## Acceptance Criteria

- [ ] `FileEnvelope` model created with all 7 fields
- [ ] `UPLOAD_FIELD_TYPES` is a `frozenset` of exactly `{FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD}`
- [ ] `is_single_cardinality()` returns `True` for FILE/IMAGE, `False` for DROPZONE/MULTI_UPLOAD
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_file_envelope.py -v`
- [ ] Import works: `from parrot_formdesigner.core.file_envelope import FileEnvelope, UPLOAD_FIELD_TYPES, is_single_cardinality`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_file_envelope.py
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.file_envelope import (
    FileEnvelope, UPLOAD_FIELD_TYPES, is_single_cardinality,
)
from parrot_formdesigner.core.types import FieldType


class TestFileEnvelope:
    def test_required_fields(self):
        env = FileEnvelope(filename="report.pdf", content_type="application/pdf", size=1024)
        assert env.filename == "report.pdf"
        assert env.content_type == "application/pdf"
        assert env.size == 1024

    def test_optional_fields_default_none(self):
        env = FileEnvelope(filename="x.txt", content_type="text/plain", size=0)
        assert env.blob_ref is None
        assert env.data_url is None
        assert env.thumbnail_url is None
        assert env.checksum is None

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            FileEnvelope(filename="x", content_type="text/plain", size=0, unknown="bad")

    def test_size_ge_zero(self):
        with pytest.raises(ValidationError):
            FileEnvelope(filename="x", content_type="text/plain", size=-1)

    def test_full_envelope(self):
        env = FileEnvelope(
            filename="photo.jpg", content_type="image/jpeg", size=45000,
            blob_ref="s3://bucket/key", data_url="data:image/jpeg;base64,/9j/...",
            thumbnail_url="/thumb/abc", checksum="sha256:abc123",
        )
        assert env.blob_ref == "s3://bucket/key"


class TestUploadFieldTypes:
    def test_contains_exactly_four(self):
        assert UPLOAD_FIELD_TYPES == frozenset({
            FieldType.FILE, FieldType.IMAGE,
            FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD,
        })

    def test_is_frozenset(self):
        assert isinstance(UPLOAD_FIELD_TYPES, frozenset)


class TestIsSingleCardinality:
    @pytest.mark.parametrize("ft", [FieldType.FILE, FieldType.IMAGE])
    def test_single(self, ft):
        assert is_single_cardinality(ft) is True

    @pytest.mark.parametrize("ft", [FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD])
    def test_multi(self, ft):
        assert is_single_cardinality(ft) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `FieldType` still has FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD at the stated lines
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the FileEnvelope model, UPLOAD_FIELD_TYPES, and is_single_cardinality
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2442-file-envelope-model.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
