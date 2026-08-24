# TASK-2448: JSON Schema Renderer Update

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2442
**Assigned-to**: unassigned

---

## Context

The JSON Schema renderer describes the value shapes of each field type for
frontend consumers and schema validators. This task updates it so FILE and
IMAGE emit a `oneOf: [string, FileEnvelope object]` schema (backward-compatible
dual shape), and IMAGE_DROPZONE / MULTI_UPLOAD emit the FileEnvelope-based
object/array shape. Implements **Module 7** from the spec.

---

## Scope

- Update `_TYPE_MAP` in `renderers/jsonschema.py`:
  - `FILE`: change from `"string"` to `"object"`
  - `IMAGE`: change from `"string"` to `"object"`
- Add FILE and IMAGE to `_UNION_SHAPES` with `oneOf: [{"type": "string"}, {FileEnvelope object schema}]`
- Add/update `_STRUCTURAL_EXTRAS` entries for FILE, IMAGE with FileEnvelope properties
- Update IMAGE_DROPZONE in `_STRUCTURAL_EXTRAS` to use FileEnvelope properties
  (replacing legacy `{name, type, size, dataUrl}`)
- Update MULTI_UPLOAD array items to use FileEnvelope shape
- Write unit tests for the updated schema output.

**NOT in scope**: Other renderers (TASK-2449), controls/helpers (TASK-2450),
validator updates (TASK-2447).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | Update _TYPE_MAP, _UNION_SHAPES, _STRUCTURAL_EXTRAS |
| `packages/parrot-formdesigner/tests/unit/test_jsonschema_file_envelope.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.renderers.jsonschema import (
    _TYPE_MAP,               # line 26 — dict mapping FieldType → JSON Schema type string
    _UNION_SHAPES,           # line 92 — dict mapping FieldType → oneOf schema
    _STRUCTURAL_EXTRAS,      # line 156 — dict mapping FieldType → properties/items schema
    type_level_value_shape,  # line 215 — function returning the value shape for a field type
)
from parrot_formdesigner.core.types import FieldType  # core/types.py:16
```

### Existing Signatures to Use
```python
# parrot_formdesigner/renderers/jsonschema.py:26
_TYPE_MAP: dict[FieldType, str] = {
    # ... maps each FieldType to a JSON Schema type string
    # Currently: FILE → "string", IMAGE → "string",
    #   IMAGE_DROPZONE → "object", MULTI_UPLOAD → "array"
}

# parrot_formdesigner/renderers/jsonschema.py:92
_UNION_SHAPES: dict[FieldType, dict] = {
    # Currently includes TREE_SELECT (oneOf: [string, object])
    # FILE and IMAGE are NOT in here yet — this task adds them
}

# parrot_formdesigner/renderers/jsonschema.py:156
_STRUCTURAL_EXTRAS: dict[FieldType, dict] = {
    # Currently includes IMAGE_DROPZONE → {name, type, size, dataUrl}
    # and MULTI_UPLOAD → array items
}

# parrot_formdesigner/renderers/jsonschema.py:215
def type_level_value_shape(field_type: FieldType) -> dict[str, Any]:
    """Return the JSON Schema value shape for a field type.
    Composes _TYPE_MAP, _UNION_SHAPES, and _STRUCTURAL_EXTRAS."""
    ...
```

### Does NOT Exist
- ~~`_FILE_ENVELOPE_SCHEMA`~~ — no predefined schema constant; define inline in `_UNION_SHAPES`
- ~~`JsonSchemaRenderer.render_file_envelope`~~ — not a real method

---

## Implementation Notes

### FileEnvelope JSON Schema Shape
```python
FILE_ENVELOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "filename": {"type": "string"},
        "content_type": {"type": "string"},
        "size": {"type": "integer", "minimum": 0},
        "blob_ref": {"type": ["string", "null"]},
        "data_url": {"type": ["string", "null"]},
        "thumbnail_url": {"type": ["string", "null"]},
        "checksum": {"type": ["string", "null"]},
    },
    "required": ["filename", "content_type", "size"],
    "additionalProperties": False,
}
```

### Changes to Apply
```python
# _TYPE_MAP updates:
# FILE: "string" → "object"  (but _UNION_SHAPES will override to oneOf)
# IMAGE: "string" → "object" (same)

# _UNION_SHAPES additions:
FieldType.FILE: {"oneOf": [{"type": "string"}, FILE_ENVELOPE_SCHEMA]},
FieldType.IMAGE: {"oneOf": [{"type": "string"}, FILE_ENVELOPE_SCHEMA]},

# _STRUCTURAL_EXTRAS updates:
# IMAGE_DROPZONE: replace legacy {name,type,size,dataUrl} with FileEnvelope properties
# MULTI_UPLOAD: update items schema to FileEnvelope shape
```

### Key Constraints
- The `oneOf` for FILE/IMAGE is critical for backward compatibility: frontends
  that still send strings will validate against the schema
- Follow the existing TREE_SELECT pattern in `_UNION_SHAPES` (lines 93-96)
- Keep `type_level_value_shape()` working correctly — it composes these dicts
- Define `FILE_ENVELOPE_SCHEMA` as a module-level constant to avoid duplication

---

## Acceptance Criteria

- [ ] `_TYPE_MAP[FILE]` and `_TYPE_MAP[IMAGE]` changed to `"object"`
- [ ] `_UNION_SHAPES` includes FILE and IMAGE with `oneOf: [string, FileEnvelope]`
- [ ] `_STRUCTURAL_EXTRAS` updated for IMAGE_DROPZONE and MULTI_UPLOAD
- [ ] `type_level_value_shape(FieldType.FILE)` returns the correct oneOf schema
- [ ] `type_level_value_shape(FieldType.IMAGE)` returns the correct oneOf schema
- [ ] `type_level_value_shape(FieldType.IMAGE_DROPZONE)` returns FileEnvelope object schema
- [ ] `type_level_value_shape(FieldType.MULTI_UPLOAD)` returns array of FileEnvelope
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_jsonschema_file_envelope.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_jsonschema_file_envelope.py
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.jsonschema import type_level_value_shape


class TestFileEnvelopeJsonSchema:
    def test_file_union_shape(self):
        schema = type_level_value_shape(FieldType.FILE)
        assert "oneOf" in schema
        types = [s.get("type") for s in schema["oneOf"]]
        assert "string" in types
        assert "object" in types

    def test_image_union_shape(self):
        schema = type_level_value_shape(FieldType.IMAGE)
        assert "oneOf" in schema
        types = [s.get("type") for s in schema["oneOf"]]
        assert "string" in types
        assert "object" in types

    def test_file_envelope_properties(self):
        schema = type_level_value_shape(FieldType.FILE)
        obj_schema = [s for s in schema["oneOf"] if s.get("type") == "object"][0]
        props = obj_schema["properties"]
        assert "filename" in props
        assert "content_type" in props
        assert "size" in props
        assert "blob_ref" in props
        assert "data_url" in props

    def test_dropzone_envelope_shape(self):
        schema = type_level_value_shape(FieldType.IMAGE_DROPZONE)
        assert schema.get("type") == "object"
        assert "filename" in schema.get("properties", {})

    def test_multi_upload_envelope_shape(self):
        schema = type_level_value_shape(FieldType.MULTI_UPLOAD)
        assert schema.get("type") == "array"
        items = schema.get("items", {})
        assert "filename" in items.get("properties", {})

    def test_rest_unchanged(self):
        """REST field type schema should NOT change."""
        schema = type_level_value_shape(FieldType.REST)
        # REST should remain as-is, no FileEnvelope involvement
        assert "oneOf" not in schema or "filename" not in str(schema)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2442 is completed
3. **Verify the Codebase Contract** — read `renderers/jsonschema.py`, locate `_TYPE_MAP`, `_UNION_SHAPES`, `_STRUCTURAL_EXTRAS`
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the schema changes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2448-jsonschema-renderer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
