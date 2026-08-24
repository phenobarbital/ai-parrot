# TASK-2450: Controls & Helpers Update

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2442, TASK-2448
**Assigned-to**: unassigned

---

## Context

The form-controls catalog (`_BUILTIN_METADATA`) and the LLM field-helper
snippets (`_FIELD_SCHEMA_SNIPPETS`) describe the value shape of each field
type. Both must be updated to reflect the new FileEnvelope shape for upload
fields so that UI tooling and LLM agents produce correct form schemas.
Implements **Module 9** from the spec.

---

## Scope

- Update `_BUILTIN_METADATA` entries in `controls/builtin.py` for FILE, IMAGE,
  IMAGE_DROPZONE, MULTI_UPLOAD:
  - Update `value_shape` key to reflect FileEnvelope structure
  - Keep `category: "media"` and `render_hint: "upload"` unchanged
- Update `_FIELD_SCHEMA_SNIPPETS` in `tools/field_helpers.py` for FILE, IMAGE,
  IMAGE_DROPZONE, MULTI_UPLOAD:
  - Update example JSON to show FileEnvelope shape
  - Add note about dual-read backward compatibility for FILE/IMAGE
- Write unit tests verifying the updated catalog entries.

**NOT in scope**: FileEnvelope model (TASK-2442), JSON Schema renderer (TASK-2448),
validators (TASK-2447).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` | MODIFY | Update _BUILTIN_METADATA value entries |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` | MODIFY | Update _FIELD_SCHEMA_SNIPPETS |
| `packages/parrot-formdesigner/tests/unit/test_controls_helpers_envelope.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA  # line 66
from parrot_formdesigner.tools.field_helpers import _FIELD_SCHEMA_SNIPPETS  # line 16
from parrot_formdesigner.core.types import FieldType  # core/types.py:16
from parrot_formdesigner.renderers.jsonschema import type_level_value_shape  # line 215
```

### Existing Signatures to Use
```python
# parrot_formdesigner/controls/builtin.py:66
_BUILTIN_METADATA: dict[FieldType, dict[str, Any]] = {
    # Each entry has: category, render_hint, value_shape, ...
    # FILE: category="media", render_hint="upload"
    # IMAGE: category="media", render_hint="upload"
}

# parrot_formdesigner/tools/field_helpers.py:16
_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {
    # Each entry has example JSON for a field type
}
```

### Does NOT Exist
- ~~`_BUILTIN_METADATA[FieldType.FILE]["envelope"]`~~ — no such key yet
- ~~`controls/registry.py`~~ — no separate controls registry module

---

## Implementation Notes

### _BUILTIN_METADATA Update Pattern
```python
# For FILE and IMAGE:
FieldType.FILE: {
    "category": "media",
    "render_hint": "upload",
    "value_shape": type_level_value_shape(FieldType.FILE),
    # ... keep other existing keys
}
```

### _FIELD_SCHEMA_SNIPPETS Update
```python
# Update the FILE snippet example:
"file": {
    "field_type": "file",
    "value_example": {
        "filename": "document.pdf",
        "content_type": "application/pdf",
        "size": 183204,
        "blob_ref": "s3://bucket/form-uid/field-uid/uuid",
        "data_url": None,
        "thumbnail_url": None,
        "checksum": "sha256:e3b0c44..."
    },
    "note": "Also accepts plain string (legacy). See FileEnvelope model.",
}
```

### Key Constraints
- `_BUILTIN_METADATA` uses `type_level_value_shape()` to derive value_shape —
  TASK-2448 must be completed first so that function returns the correct schema
- Keep all existing keys in each entry; only update `value_shape` and related
- `_FIELD_SCHEMA_SNIPPETS` keys are lowercase strings (e.g., `"file"`, `"image"`),
  not FieldType enum values

---

## Acceptance Criteria

- [ ] `_BUILTIN_METADATA` value_shape updated for FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD
- [ ] `_FIELD_SCHEMA_SNIPPETS` examples updated to show FileEnvelope shape
- [ ] Existing metadata keys (category, render_hint) preserved
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_controls_helpers_envelope.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_controls_helpers_envelope.py
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA
from parrot_formdesigner.tools.field_helpers import _FIELD_SCHEMA_SNIPPETS


class TestBuiltinMetadataEnvelope:
    @pytest.mark.parametrize("ft", [
        FieldType.FILE, FieldType.IMAGE,
        FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD,
    ])
    def test_value_shape_includes_filename(self, ft):
        meta = _BUILTIN_METADATA[ft]
        shape = meta["value_shape"]
        # The shape should reference FileEnvelope properties
        shape_str = str(shape)
        assert "filename" in shape_str

    @pytest.mark.parametrize("ft", [FieldType.FILE, FieldType.IMAGE])
    def test_file_image_still_media_category(self, ft):
        assert _BUILTIN_METADATA[ft]["category"] == "media"


class TestFieldHelperSnippets:
    @pytest.mark.parametrize("key", ["file", "image", "image_dropzone", "multi_upload"])
    def test_snippet_has_envelope_example(self, key):
        snippet = _FIELD_SCHEMA_SNIPPETS[key]
        example = snippet.get("value_example", {})
        if isinstance(example, dict):
            assert "filename" in example
        elif isinstance(example, list):
            assert "filename" in example[0]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2442 and TASK-2448 are completed
3. **Verify the Codebase Contract** — read `controls/builtin.py` and `tools/field_helpers.py`
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the metadata and snippet updates
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2450-controls-helpers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
