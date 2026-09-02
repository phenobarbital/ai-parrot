# TASK-2680: JSON Schema Renderer — Emit content_type Extension Keys

**Feature**: FEAT-488 — FormField Content-Type
**Spec**: `sdd/specs/formfield-content-type.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2677
**Assigned-to**: unassigned

---

## Context

The JSON Schema renderer is the primary consumer-facing artifact for form
schemas. This task adds `x-content-type` and `x-accept-content-types`
extension keys to the per-field property dict it emits, following the
existing `x-field-type`, `x-depends-on`, etc. convention.

This is the highest-priority renderer (spec §3 Module 4, proposal §What Changes).

Implements spec §3 Module 4.

---

## Scope

- In `renderers/jsonschema.py`, in `_field_to_property()` (line 472), after
  the existing `"x-field-type": ft.value` entry (line 493), add:
  - `"x-content-type": field.content_type` when `field.content_type is not None`
  - `"x-accept-content-types": field.accept_content_types` when `field.accept_content_types is not None`
- Both keys are omitted entirely (not set to `null`) when the field attributes are `None`.

**NOT in scope**: changes to any other renderer, validator, or schema model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | Emit `x-content-type` / `x-accept-content-types` in `_field_to_property()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# renderers/jsonschema.py — no new imports required
# FormField is already imported from ..core.schema
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py

class JsonSchemaRenderer:
    def _field_to_property(self, field: FormField, ...) -> dict[str, Any]:  # line 472
        """..."""
        ft = field.field_type
        prop = {
            "type": ...,
            "title": ...,
            "x-field-type": ft.value,   # line 493 — existing x- key
            # ... other keys added conditionally
        }
        # x-depends-on, x-post-depends, x-options-source, x-placeholder,
        # x-read-only, x-section, x-subsection added at lines ~495-555
        # ← add x-content-type and x-accept-content-types here, same pattern
        return prop

# Existing x- extension keys for reference:
# "x-field-type": ft.value            (line 493, always present)
# "x-depends-on": ...                  (conditional)
# "x-options-source": ...              (conditional, line ~552)
# "x-placeholder": ...                 (conditional)
# "x-read-only": ...                   (conditional)
```

### Does NOT Exist

- ~~`JsonSchemaRenderer._emit_content_type()`~~ — no such helper method; add inline in `_field_to_property()`.
- ~~`x-mime-type`~~ — the correct key name is `x-content-type` (not `x-mime-type`).
- ~~`field.content_type` as a required field~~ — it is `str | None`; always guard with `is not None`.

---

## Implementation Notes

### Pattern to Follow

Follow the conditional-key pattern already used for `x-options-source` (line ~552):

```python
# Inside _field_to_property(), after existing x- keys:
if field.content_type is not None:
    prop["x-content-type"] = field.content_type
if field.accept_content_types is not None:
    prop["x-accept-content-types"] = field.accept_content_types
```

Both keys are omitted (not included as `null`) when the field attributes
are `None` — this is consistent with all other conditional x- extension keys.

### Key Constraints

- Use exactly the key names `x-content-type` and `x-accept-content-types`
  (hyphenated, lowercase) — matches JSON Schema extension convention.
- Do NOT set the keys to `null` when the field attributes are `None`; omit
  them entirely.
- Find the exact insertion point by reading the actual file — the line
  numbers in this contract are approximate; the real file is authoritative.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` — target file
- `packages/parrot-formdesigner/tests/unit/test_jsonschema_file_envelope.py` — test style reference

---

## Acceptance Criteria

- [ ] `_field_to_property()` includes `"x-content-type"` when `field.content_type` is set.
- [ ] `_field_to_property()` includes `"x-accept-content-types"` when `field.accept_content_types` is set.
- [ ] Neither key appears in the output when the corresponding `FormField` attribute is `None`.
- [ ] Existing JSON Schema output for fields without `content_type` is unchanged.
- [ ] All existing renderer tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_renderers.py (or new file)
# Add to the existing test file or create test_jsonschema_content_type.py:

import pytest
from parrot_formdesigner.core.schema import FormField, FormSection, FormSchema
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer


@pytest.fixture
def renderer():
    return JsonSchemaRenderer()


def _simple_schema(field: FormField) -> FormSchema:
    """Wrap a single field in a minimal FormSchema for rendering."""
    # Check existing tests for the exact FormSchema constructor pattern
    ...


def test_jsonschema_emits_x_content_type(renderer):
    field = FormField(
        field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes",
        content_type="text/markdown",
    )
    schema = _simple_schema(field)
    rendered = renderer.render_sync(schema)  # verify method name in existing tests
    prop = rendered.content["properties"]["notes"]
    assert prop.get("x-content-type") == "text/markdown"


def test_jsonschema_omits_x_content_type_when_none(renderer):
    field = FormField(field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes")
    schema = _simple_schema(field)
    rendered = renderer.render_sync(schema)
    prop = rendered.content["properties"]["notes"]
    assert "x-content-type" not in prop


def test_jsonschema_emits_x_accept_content_types(renderer):
    field = FormField(
        field_id="answer", field_type=FieldType.TEXT_AREA, label="Answer",
        accept_content_types=["text/plain", "application/json"],
    )
    schema = _simple_schema(field)
    rendered = renderer.render_sync(schema)
    prop = rendered.content["properties"]["answer"]
    assert prop.get("x-accept-content-types") == ["text/plain", "application/json"]


def test_jsonschema_omits_x_accept_content_types_when_none(renderer):
    field = FormField(field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes")
    schema = _simple_schema(field)
    rendered = renderer.render_sync(schema)
    prop = rendered.content["properties"]["notes"]
    assert "x-accept-content-types" not in prop
```

---

## Completion Note

Implemented as specified. Added `x-content-type` and `x-accept-content-types` extension keys to `_field_to_property()` in `renderers/jsonschema.py`, following the existing conditional-key pattern. All 47 existing renderer tests pass.

## Agent Instructions

1. **Read the spec** at `sdd/specs/formfield-content-type.spec.md`.
2. **Check dependencies** — verify TASK-2677 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `renderers/jsonschema.py` around line 472 to find `_field_to_property()` and the conditional x- key block.
4. **Update status** → `"in_progress"`.
5. **Implement** the two conditional key additions.
6. **Verify** all acceptance criteria.
7. **Move** to `sdd/tasks/completed/TASK-2680-jsonschema-renderer-content-type.md`.
8. **Update index** → `"completed"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
