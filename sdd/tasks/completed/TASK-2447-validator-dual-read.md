# TASK-2447: Validator Dual-Read Coercer

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2442
**Assigned-to**: unassigned

---

## Context

This task updates the form validator to accept both legacy value shapes and the
new FileEnvelope dict for all four upload field types. This is the backward
compatibility layer — existing form submissions with string values for FILE/IMAGE
continue to work alongside new FileEnvelope submissions. Implements **Module 6**
from the spec.

---

## Scope

- Update `_coerce_value` in `services/validators.py` to add dedicated branches for
  FILE, IMAGE, IMAGE_DROPZONE, and MULTI_UPLOAD:
  - **FILE/IMAGE**: accept `str` (legacy, pass through) or `dict` (validate as FileEnvelope)
  - **IMAGE_DROPZONE**: accept legacy `{name,type,size,dataUrl}` (map to FileEnvelope) or FileEnvelope dict
  - **MULTI_UPLOAD**: accept legacy `[{answer,blob_ref,display}]` (map each to FileEnvelope) or `[FileEnvelope]`
- Update `_validate_by_type` for FileEnvelope-aware structural validation where
  IMAGE_DROPZONE (lines 742-754) and MULTI_UPLOAD (lines 756-764) currently validate.
- Keep the MIME side-channel hack (`{field_id}__mime` at line 326-329) for legacy
  string values; skip it for FileEnvelope values (they carry `content_type` directly).
- Write unit tests for all coercion paths.

**NOT in scope**: FileEnvelope model (TASK-2442), upload handler (TASK-2445),
renderer updates (TASK-2448, TASK-2449).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | Add coercion branches + validation |
| `packages/parrot-formdesigner/tests/unit/test_validator_file_envelope.py` | CREATE | Unit tests for dual-read coercer |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.file_envelope import (
    FileEnvelope, UPLOAD_FIELD_TYPES, is_single_cardinality,
)  # created by TASK-2442
from parrot_formdesigner.core.types import FieldType  # core/types.py:16
```

### Existing Signatures to Use
```python
# parrot_formdesigner/services/validators.py
# CORRECTED (contract was stale — verified against the actual file at
# implementation time): the real signature takes (value, field) — NOT
# (field, value, all_data) — and has no all_data parameter. all_data is
# only in scope in the caller, validate_field(), where the MIME
# side-channel check actually lives (lines 326-329).
def _coerce_value(self, value: Any, field: FormField) -> Any:
    ...

# FILE/IMAGE have NO dedicated branch — they fall through to
# `return value` at line 607 (confirmed).
# IMAGE_DROPZONE coerce branch: lines 558-561 (confirmed)
# MULTI_UPLOAD coerce branch: lines 563-566 (confirmed)
# IMAGE_DROPZONE validated at lines 742-754 (confirmed)
# MULTI_UPLOAD validated at lines 756-764 (confirmed)
# MIME side-channel: lines 326-329 in validate_field(), checks
# {field_id}__mime in all_data (confirmed)

# The _validate_by_type method signature (confirmed):
def _validate_by_type(self, value: Any, field: FormField, label: str) -> list[str]:
    ...
```

### Does NOT Exist
- ~~`_validate_file_field`~~ — no such method in validators.py
- ~~`_coerce_file_value`~~ — no such method
- ~~`FormValidator.file_envelope_mode`~~ — not an attribute
- ~~FILE/IMAGE branch in `_coerce_value`~~ — currently no dedicated branch;
  they fall through to string passthrough at line 607

---

## Implementation Notes

### Legacy Shape Mapping

```python
# IMAGE_DROPZONE legacy → FileEnvelope:
# {name: "photo.jpg", type: "image/jpeg", size: 45000, dataUrl: "data:..."}
# →
# FileEnvelope(filename="photo.jpg", content_type="image/jpeg",
#              size=45000, data_url="data:...", blob_ref=None)

# MULTI_UPLOAD legacy → FileEnvelope:
# {answer: "result", blob_ref: "s3://bucket/key", display: "photo.jpg"}
# →
# FileEnvelope(filename="photo.jpg" or "unknown",
#              content_type="application/octet-stream",  # lossy
#              size=0,  # lossy — legacy shape has no size
#              blob_ref="s3://bucket/key", data_url="result" if looks like data url else None)
```

### Key Constraints
- **Backward compatibility is NON-NEGOTIABLE**: legacy string values for FILE/IMAGE
  must continue to work without any change
- The coercion should detect FileEnvelope-shaped dicts by checking for `"filename"`
  and `"content_type"` keys (both required in FileEnvelope)
- Legacy IMAGE_DROPZONE detection: check for `"dataUrl"` key (camelCase, not snake_case)
- Legacy MULTI_UPLOAD detection: check for `"answer"` key
- MIME side-channel (`{field_id}__mime`): keep for legacy strings, skip when value
  is a dict with `content_type`
- Validation errors should be clear: "Invalid FileEnvelope: missing 'filename'" etc.

### References in Codebase
- `services/validators.py` lines 326-329 — MIME side-channel
- `services/validators.py` lines 742-754 — existing IMAGE_DROPZONE validation
- `services/validators.py` lines 756-764 — existing MULTI_UPLOAD validation

---

## Acceptance Criteria

- [ ] `_coerce_value` handles FILE legacy string → pass through
- [ ] `_coerce_value` handles FILE FileEnvelope dict → validated
- [ ] `_coerce_value` handles IMAGE legacy string → pass through
- [ ] `_coerce_value` handles IMAGE FileEnvelope dict → validated
- [ ] `_coerce_value` handles IMAGE_DROPZONE legacy `{name,type,size,dataUrl}` → mapped to FileEnvelope
- [ ] `_coerce_value` handles IMAGE_DROPZONE FileEnvelope dict → validated
- [ ] `_coerce_value` handles MULTI_UPLOAD legacy `[{answer,blob_ref,display}]` → mapped
- [ ] `_coerce_value` handles MULTI_UPLOAD FileEnvelope list → validated
- [ ] MIME side-channel skipped for FileEnvelope values
- [ ] Missing required FileEnvelope fields → validation error
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_validator_file_envelope.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_validator_file_envelope.py
import pytest
from parrot_formdesigner.core.file_envelope import FileEnvelope


class TestCoerceFileLegacy:
    def test_string_value_accepted(self):
        """Legacy string value for FILE passes through unchanged."""
        ...

    def test_envelope_dict_accepted(self):
        """FileEnvelope dict for FILE is validated and accepted."""
        ...


class TestCoerceImageLegacy:
    def test_string_value_accepted(self):
        """Legacy string value for IMAGE passes through unchanged."""
        ...

    def test_envelope_dict_accepted(self):
        """FileEnvelope dict for IMAGE is validated and accepted."""
        ...


class TestCoerceDropzoneLegacy:
    def test_legacy_shape_mapped(self):
        """Legacy {name,type,size,dataUrl} mapped to FileEnvelope fields."""
        ...

    def test_envelope_dict_accepted(self):
        """FileEnvelope dict for IMAGE_DROPZONE accepted directly."""
        ...


class TestCoerceMultiUploadLegacy:
    def test_legacy_list_mapped(self):
        """Legacy [{answer,blob_ref,display}] mapped to FileEnvelopes."""
        ...

    def test_envelope_list_accepted(self):
        """List of FileEnvelope dicts accepted directly."""
        ...


class TestValidateEnvelope:
    def test_missing_filename_error(self):
        """FileEnvelope dict without 'filename' → validation error."""
        ...

    def test_missing_content_type_error(self):
        """FileEnvelope dict without 'content_type' → validation error."""
        ...

    def test_missing_size_error(self):
        """FileEnvelope dict without 'size' → validation error."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2442 is completed
3. **Verify the Codebase Contract** — read `services/validators.py`, locate `_coerce_value` and `_validate_by_type`
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the dual-read coercion branches
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2447-validator-dual-read.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-25
**Notes**: Codebase Contract was stale for `_coerce_value` (actual signature
is `(self, value, field)`, no `all_data` param — corrected in this file
before implementing). Added FILE/IMAGE branches (str passthrough, dict
passthrough for structural check), and legacy-mapping branches for
IMAGE_DROPZONE/MULTI_UPLOAD that only map a *complete* legacy shape to a
FileEnvelope dict — an incomplete legacy dict (e.g. missing `blob_ref`) is
left unmapped so the pre-existing legacy-key validation still flags it,
preserving `test_feat448_validator_branches.py`'s existing regression
coverage bit-for-bit (`[{"answer": "a1"}]` still errors). `_validate_by_type`
now branches on `_is_file_envelope_shaped()` to check FileEnvelope-required
keys vs. legacy keys. MIME side-channel (validate_field, ~line 326) now
skips when the coerced value is FileEnvelope-shaped. Full regression sweep:
`tests/unit/services/` + all three FEAT-448 validator test files = 362
passed, 0 failed. New `test_validator_file_envelope.py`: 13/13 passed.
No new ruff findings (14 pre-existing BLE001 in validators.py, confirmed
identical count via `git stash` before/after).

**Deviations from spec**: none — the "Does NOT Exist" and most "Existing
Signatures" entries were accurate; only the `_coerce_value` signature shape
was wrong, and it was corrected in the contract above rather than guessed.
