# TASK-2443: FieldConstraints max_inline_size_bytes Extension

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task adds the `max_inline_size_bytes` field to `FieldConstraints`, which
controls the size threshold for including inline `data_url` in FileEnvelope
responses. Files at or below this size get an inline base64 data URL; larger
files get only a `blob_ref`. Implements **Module 2** from the spec.

---

## Scope

- Add `max_inline_size_bytes: int | None` field to `FieldConstraints` in
  `core/constraints.py` (default `None` → system uses `DEFAULT_MAX_INLINE_SIZE`).
- Define module-level constant `DEFAULT_MAX_INLINE_SIZE = 10_485_760` (10 MB).
- Write unit test for the new field.

**NOT in scope**: FileEnvelope model (TASK-2442), upload handler logic (TASK-2445).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` | MODIFY | Add `max_inline_size_bytes` + constant |
| `packages/parrot-formdesigner/tests/unit/test_constraints_inline.py` | CREATE | Unit test for new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.constraints import FieldConstraints  # core/constraints.py
```

### Existing Signatures to Use
```python
# parrot_formdesigner/core/constraints.py:36-50
class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")        # line 36
    # ... many existing fields ...
    allowed_mime_types: list[str] | None = None       # line 47
    max_file_size_bytes: int | None = Field(          # line 48
        default=None, ge=0
    )
```

### Does NOT Exist
- ~~`FieldConstraints.max_inline_size_bytes`~~ — does not exist yet; this task adds it
- ~~`DEFAULT_MAX_INLINE_SIZE`~~ — does not exist yet; this task defines it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the max_file_size_bytes pattern at line 48:
max_inline_size_bytes: int | None = Field(
    default=None, ge=0,
    description="Maximum file size (bytes) for inline data_url inclusion. "
                "Files above this get blob_ref only. "
                "None → system default (DEFAULT_MAX_INLINE_SIZE)."
)
```

### Key Constraints
- Place `DEFAULT_MAX_INLINE_SIZE = 10_485_760` as a module-level constant ABOVE the class
- Place `max_inline_size_bytes` field right after `max_file_size_bytes` for logical grouping
- `ge=0` constraint like `max_file_size_bytes`
- `extra="forbid"` is already on the class — no extra fields allowed, so the test must verify the new field is accepted

---

## Acceptance Criteria

- [ ] `DEFAULT_MAX_INLINE_SIZE = 10_485_760` constant defined
- [ ] `FieldConstraints.max_inline_size_bytes` field added (int | None, default None, ge=0)
- [ ] Existing constraints still work (no regression)
- [ ] Test passes: `pytest packages/parrot-formdesigner/tests/unit/test_constraints_inline.py -v`
- [ ] Import works: `from parrot_formdesigner.core.constraints import FieldConstraints, DEFAULT_MAX_INLINE_SIZE`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_constraints_inline.py
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.constraints import (
    FieldConstraints, DEFAULT_MAX_INLINE_SIZE,
)


class TestMaxInlineSizeBytes:
    def test_default_is_none(self):
        c = FieldConstraints()
        assert c.max_inline_size_bytes is None

    def test_accepts_valid_value(self):
        c = FieldConstraints(max_inline_size_bytes=5_242_880)
        assert c.max_inline_size_bytes == 5_242_880

    def test_accepts_zero(self):
        c = FieldConstraints(max_inline_size_bytes=0)
        assert c.max_inline_size_bytes == 0

    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            FieldConstraints(max_inline_size_bytes=-1)

    def test_default_constant_value(self):
        assert DEFAULT_MAX_INLINE_SIZE == 10_485_760

    def test_existing_constraints_unaffected(self):
        c = FieldConstraints(
            allowed_mime_types=["image/png"],
            max_file_size_bytes=1024,
            max_inline_size_bytes=2048,
        )
        assert c.allowed_mime_types == ["image/png"]
        assert c.max_file_size_bytes == 1024
        assert c.max_inline_size_bytes == 2048
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — read `core/constraints.py` and confirm `max_inline_size_bytes` still does not exist
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the constant and field addition
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2443-field-constraints-extension.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-25
**Notes**: Added `DEFAULT_MAX_INLINE_SIZE = 10_485_760` module-level constant
and `max_inline_size_bytes: int | None` field (default None, ge=0) to
`FieldConstraints`, placed right after `max_file_size_bytes`. Added
`test_constraints_inline.py` per the task's Test Specification verbatim.
Ran the new tests plus the full `tests/unit/core/` suite (170 passed) to
confirm no regression to existing constraints.

**Deviations from spec**: none
