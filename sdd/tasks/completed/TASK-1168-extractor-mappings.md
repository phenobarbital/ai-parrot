# TASK-1168: Extractor reverse-mappings for `FieldType.REST`

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 9)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1163
**Assigned-to**: unassigned

---

## Context

The YAML and JSON-Schema extractors translate external definitions
into `FormField`s and back. Each needs the new `"rest"` ↔
`FieldType.REST` mapping plus round-trip preservation of
`meta["rest"]`.

---

## Scope

- In `extractors/yaml.py`: add `"rest" -> FieldType.REST` in the
  forward map and the reverse direction; ensure `meta.rest` survives
  a round-trip.
- In `extractors/jsonschema.py`: detect a REST field via the
  `x-parrot-rest` extension (emitted by TASK-1167's JSON-Schema
  renderer) and translate to `FieldType.REST` with `meta.rest`
  populated. Reverse direction round-trips the extension.
- Unit tests for both directions in both extractors.

**NOT in scope**: any new extractor backends.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py` | MODIFY | +mapping |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | +mapping (x-parrot-rest) |
| `packages/parrot-formdesigner/tests/unit/extractors/test_yaml_rest.py` | CREATE | Round-trip |
| `packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_rest.py` | CREATE | Round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified

Each extractor has a `_TYPE_MAP` (yaml) or a structural recogniser
(jsonschema). FEAT-167 added 10 new types; copy that pattern.

### Does NOT Exist

- ~~`"rest"` key in `extractors/yaml.py`~~ — added.
- ~~`x-parrot-rest` detection in `extractors/jsonschema.py`~~ — added.

---

## Acceptance Criteria

- [ ] YAML key `rest: {...}` extracts to a `FormField` with
      `field_type == FieldType.REST` and `meta.rest` preserved.
- [ ] JSON Schema fragment with `x-parrot-rest` extracts to the same.
- [ ] Both directions round-trip (`extract` ∘ `emit` == identity).

---

## Test Specification

```python
def test_yaml_rest_roundtrip():
    yaml_text = """
    field_id: x
    type: rest
    meta:
      rest:
        mode: callback
        callback_ref: cb
    """
    field = extract_from_yaml(yaml_text)
    assert field.field_type.value == "rest"
    assert field.meta["rest"]["mode"] == "callback"
    assert dump_to_yaml(field) ...  # round-trip
```

---

## Completion Note

*(Agent fills this in when done)*

### Completion Note

Added `"rest": FieldType.REST` to `_LEGACY_FIELD_TYPE_MAP` in `extractors/yaml.py`.
Detects `x-parrot-rest` JSON Schema extension in `JsonSchemaExtractor._property_to_field`,
overrides `field_type` to `FieldType.REST` and sets `meta["rest"]` from the extension value.
Created `tests/unit/extractors/test_yaml_rest.py` and `test_jsonschema_rest.py` with 7 tests
covering forward mapping, meta preservation, and round-trips. All 7 pass.
