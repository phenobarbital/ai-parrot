# TASK-523: JSON Schema Extractor

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 6 from the spec. Converts a standard JSON Schema dict into `FormSchema`. This is the passthrough extractor for pre-existing JSON Schemas — useful when consuming external API schemas or when a Pydantic model's `model_json_schema()` output is the starting point.

---

## Scope

- Implement `parrot/forms/extractors/jsonschema.py` with `JsonSchemaExtractor`
- Map JSON Schema types to FieldType: `string` → TEXT, `number` → NUMBER, `integer` → INTEGER, `boolean` → BOOLEAN, `array` → ARRAY, `object` → GROUP
- Extract constraints: `minLength`, `maxLength`, `minimum`, `maximum`, `pattern`, `enum`, `minItems`, `maxItems`
- Handle `$ref` and `definitions`/`$defs` resolution
- Handle `format` keyword: `email` → EMAIL, `uri`/`url` → URL, `date` → DATE, `date-time` → DATETIME, `time` → TIME
- Handle `oneOf`/`anyOf` for union types (best-effort: pick first non-null)
- Auto-generate form_id and title if not provided
- Write unit tests

**NOT in scope**: Pydantic extraction (TASK-520), JSON Schema rendering output (TASK-526).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/extractors/jsonschema.py` | CREATE | JsonSchemaExtractor implementation |
| `packages/ai-parrot/src/parrot/forms/extractors/__init__.py` | MODIFY | Export JsonSchemaExtractor |
| `packages/ai-parrot/tests/unit/forms/test_jsonschema_extractor.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
class JsonSchemaExtractor:
    def extract(
        self,
        schema: dict[str, Any],
        *,
        form_id: str | None = None,
        title: str | None = None,
    ) -> FormSchema:
        """Convert a JSON Schema dict into a FormSchema."""

    def _resolve_ref(self, ref: str, root_schema: dict) -> dict: ...
    def _property_to_field(self, name: str, prop: dict, required: bool, root_schema: dict) -> FormField: ...
    def _map_type(self, prop: dict) -> FieldType: ...
    def _extract_constraints(self, prop: dict) -> FieldConstraints | None: ...
```

### Key Constraints
- Must handle nested `$ref` references (recursive resolution)
- `enum` values in JSON Schema become `FieldOption` list
- `required` array in JSON Schema → field `required=True`
- Must not fail on unknown types — default to TEXT with warning log

### References in Codebase
- `parrot/tools/abstract.py` — `get_schema()` produces JSON Schema from Pydantic models
- `parrot/integrations/dialogs/llm_generator.py` — `_schema_property_to_field()` has similar JSON Schema → field mapping

---

## Acceptance Criteria

- [ ] JSON Schema types map to correct FieldType
- [ ] JSON Schema constraints map to FieldConstraints
- [ ] `$ref` and `definitions`/`$defs` resolved correctly
- [ ] `format` keyword maps to semantic FieldTypes (email, url, date, etc.)
- [ ] `enum` values become FieldOption list
- [ ] `required` array respected
- [ ] Unknown types default to TEXT (no crash)
- [ ] Import works: `from parrot.forms.extractors import JsonSchemaExtractor`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_jsonschema_extractor.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_jsonschema_extractor.py
import pytest
from parrot.forms import FieldType
from parrot.forms.extractors.jsonschema import JsonSchemaExtractor


@pytest.fixture
def extractor():
    return JsonSchemaExtractor()


class TestJsonSchemaExtractor:
    def test_basic_types(self, extractor):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
            },
            "required": ["name"],
        }
        form = extractor.extract(schema)
        fields = {f.field_id: f for f in form.sections[0].fields}
        assert fields["name"].field_type == FieldType.TEXT
        assert fields["name"].required is True
        assert fields["age"].field_type == FieldType.INTEGER
        assert fields["score"].field_type == FieldType.NUMBER
        assert fields["active"].field_type == FieldType.BOOLEAN

    def test_constraints(self, extractor):
        schema = {
            "type": "object",
            "properties": {
                "code": {"type": "string", "minLength": 3, "maxLength": 10, "pattern": "^[A-Z]+$"},
            },
        }
        form = extractor.extract(schema)
        c = form.sections[0].fields[0].constraints
        assert c.min_length == 3
        assert c.max_length == 10

    def test_enum_to_select(self, extractor):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive", "pending"]},
            },
        }
        form = extractor.extract(schema)
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.SELECT
        assert len(field.options) == 3

    def test_ref_resolution(self, extractor):
        schema = {
            "type": "object",
            "properties": {
                "address": {"$ref": "#/$defs/Address"},
            },
            "$defs": {
                "Address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                        "city": {"type": "string"},
                    },
                },
            },
        }
        form = extractor.extract(schema)
        addr = form.sections[0].fields[0]
        assert addr.field_type == FieldType.GROUP
        assert len(addr.children) == 2

    def test_format_mapping(self, extractor):
        schema = {
            "type": "object",
            "properties": {
                "email": {"type": "string", "format": "email"},
                "website": {"type": "string", "format": "uri"},
                "birthday": {"type": "string", "format": "date"},
            },
        }
        form = extractor.extract(schema)
        fields = {f.field_id: f for f in form.sections[0].fields}
        assert fields["email"].field_type == FieldType.EMAIL
        assert fields["website"].field_type == FieldType.URL
        assert fields["birthday"].field_type == FieldType.DATE
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Read** `parrot/integrations/dialogs/llm_generator.py` for existing JSON Schema → field mapping
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-523-jsonschema-extractor.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**:

**Deviations from spec**: none | describe if any
