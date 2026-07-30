# TASK-1968: FormAssembler Core Class

**Feature**: FEAT-388 — Deterministic CreateFormTool
**Spec**: `sdd/specs/deterministic-creationformtool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-388. The `FormAssembler` class encapsulates
all deterministic form creation logic: format detection, shortcut expansion,
extractor delegation, and component-level assembly. Both TASK-1969 (CreateFormTool
integration) and TASK-1970 (EditToolkit expansion) depend on this class.

Implements spec Module 1.

---

## Scope

- Create `FormAssembler` class with all public methods
- Implement `detect_format(schema)` — distinguish JSON Schema vs FormSchema-native input
- Implement `expand_shortcuts(data)` — auto-generate IDs, coerce string field_types
- Implement `assemble(schema, *, form_id, title)` — whole-form from a schema dict
- Implement `assemble_from_sections(sections, *, form_id, title)` — from section list
- Implement `assemble_from_fields(fields, *, form_id, title, section_title)` — from flat field list
- Implement `assemble_field(field_dict)` — single field with shortcut expansion
- Implement `assemble_section(section_dict)` — single section with shortcut expansion
- Write unit tests for all methods

**NOT in scope**:
- Modifying `CreateFormTool` or `CreateFormInput` (TASK-1969)
- Modifying `EditToolkit` (TASK-1970)
- Integration/roundtrip tests (TASK-1971)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/assembler.py` | CREATE | FormAssembler class |
| `packages/parrot-formdesigner/tests/unit/test_assembler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.extractors import JsonSchemaExtractor   # extractors/__init__.py:7
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # core/schema.py
from parrot_formdesigner.core.types import FieldType              # core/types.py
from parrot_formdesigner.core.constraints import FieldConstraints  # core/constraints.py
from parrot_formdesigner.core.options import FieldOption           # core/options.py
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py:64
class JsonSchemaExtractor:
    def extract(self, schema: dict[str, Any], *, form_id: str | None = None,
                title: str | None = None) -> FormSchema:  # line 83

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:267
class FormSchema(BaseModel):
    form_id: str
    title: LocalizedString
    sections: list[FormSection]
    # model_validate(data) — Pydantic v2 class method for dict → model

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:127
class FormSection(BaseModel):
    section_id: str
    title: LocalizedString | None
    fields: list[SectionItem]  # SectionItem = Union[FormField, FormSubsection]

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:43
class FormField(BaseModel):
    field_id: str
    field_type: FieldType
    label: LocalizedString
    required: bool = False

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py:189
def _slugify(text: str) -> str:
    # Converts text to slug suitable for form_id (lowercase, hyphens, max 50 chars)
```

### Does NOT Exist
- ~~`FormAssembler`~~ — does not exist yet; this task creates it
- ~~`FormSchema.from_json_schema()`~~ — no such class method; use `JsonSchemaExtractor.extract()`
- ~~`AbstractExtractor` base class~~ — extractors do not share a common base class
- ~~`FormSchema.from_dict()`~~ — use `FormSchema.model_validate()` instead

---

## Implementation Notes

### Pattern to Follow

`FormAssembler` should be a plain class (no inheritance, no async methods). All
operations are synchronous Pydantic validation and dict manipulation.

```python
# Reference: _slugify in tools/create_form.py:189
# Reuse this pattern for auto-generating field_id from label
def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:50] or f"form-{uuid.uuid4().hex[:8]}"
```

### Format Detection Rules
| Criterion | Detected as |
|---|---|
| Has `"type": "object"` AND `"properties"` key | `"jsonschema"` |
| Has `"sections"` or `"fields"` key | `"native"` |
| Neither | Attempt `"native"` (let Pydantic validate and fail fast) |

### Shortcut Expansion Rules
| Shortcut | Expansion |
|---|---|
| Missing `field_id` | Slugify `label` → snake_case (e.g., `"First Name"` → `"first_name"`) |
| Missing `section_id` | Sequential `"section-1"`, `"section-2"` |
| Missing `form_id` | Slugify `title` |
| String `field_type` | Passed to Pydantic as-is (FieldType enum validates strings) |
| Top-level `fields` (no `sections`) | Wrap in `[{"section_id": "main", "fields": [...]}]` |

### Key Constraints
- All methods are synchronous (no async)
- Use Pydantic `model_validate()` for all validation
- Fail fast on invalid input — raise `ValidationError` or `ValueError`, never fallback to LLM
- Handle `field_id` collision by appending numeric suffix (`"name"`, `"name_2"`)
- `LocalizedString` (str or dict[str, str]) should pass through as-is — Pydantic handles the union

### ID Slugification for field_id
Use `_` separator for field IDs (snake_case), not `-` (kebab-case used for form_id/section_id):
```python
def _field_id_from_label(label: str) -> str:
    if isinstance(label, dict):
        label = next(iter(label.values()), "field")
    text = label.lower().strip()
    text = re.sub(r"[^a-z0-9\s_]", "", text)
    text = re.sub(r"[\s]+", "_", text)
    return text[:50] or "field"
```

---

## Acceptance Criteria

- [ ] `FormAssembler` class created at `parrot_formdesigner/assembler.py`
- [ ] `detect_format()` correctly identifies JSON Schema vs native format
- [ ] `expand_shortcuts()` auto-generates `field_id` from `label` when omitted
- [ ] `expand_shortcuts()` auto-generates `section_id` sequentially when omitted
- [ ] `expand_shortcuts()` auto-generates `form_id` from `title` when omitted
- [ ] `assemble()` with JSON Schema input delegates to `JsonSchemaExtractor`
- [ ] `assemble()` with native input validates via `FormSchema.model_validate()`
- [ ] `assemble_from_sections()` produces valid FormSchema from section list
- [ ] `assemble_from_fields()` wraps flat fields in a single default section
- [ ] `assemble_field()` produces a valid FormField with shortcut expansion
- [ ] `assemble_section()` produces a valid FormSection with shortcut expansion
- [ ] Invalid input raises `ValidationError` immediately (no LLM fallback)
- [ ] Unknown `field_type` string raises `ValidationError`
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_assembler.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/assembler.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_assembler.py
import pytest
from pydantic import ValidationError
from parrot_formdesigner.assembler import FormAssembler
from parrot_formdesigner.core.types import FieldType


@pytest.fixture
def assembler():
    return FormAssembler()


class TestDetectFormat:
    def test_jsonschema_detected(self, assembler):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        assert assembler.detect_format(schema) == "jsonschema"

    def test_native_with_sections(self, assembler):
        schema = {"title": "Test", "sections": []}
        assert assembler.detect_format(schema) == "native"

    def test_native_with_fields(self, assembler):
        schema = {"title": "Test", "fields": []}
        assert assembler.detect_format(schema) == "native"


class TestExpandShortcuts:
    def test_field_id_from_label(self, assembler):
        field = {"label": "First Name", "field_type": "text"}
        expanded = assembler.expand_shortcuts({"sections": [{"fields": [field]}]})
        assert expanded["sections"][0]["fields"][0]["field_id"] == "first_name"

    def test_section_id_auto_generated(self, assembler):
        section = {"title": "Info", "fields": []}
        expanded = assembler.expand_shortcuts({"sections": [section]})
        assert expanded["sections"][0]["section_id"] == "section-1"

    def test_string_field_type_accepted(self, assembler):
        field = {"field_id": "x", "label": "X", "field_type": "email"}
        result = assembler.assemble_field(field)
        assert result.field_type == FieldType.EMAIL


class TestAssemble:
    def test_from_jsonschema(self, assembler):
        schema = {
            "type": "object",
            "title": "Test",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        form = assembler.assemble(schema, form_id="test-form")
        assert form.form_id == "test-form"
        assert len(form.sections) >= 1

    def test_from_native(self, assembler):
        schema = {
            "form_id": "native-form",
            "title": "Native",
            "sections": [{
                "section_id": "s1",
                "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name"},
                ],
            }],
        }
        form = assembler.assemble(schema)
        assert form.form_id == "native-form"

    def test_invalid_schema_fails_fast(self, assembler):
        with pytest.raises((ValidationError, ValueError)):
            assembler.assemble({"invalid": "data"})

    def test_unknown_field_type_fails(self, assembler):
        schema = {
            "form_id": "f",
            "title": "T",
            "sections": [{"section_id": "s", "fields": [
                {"field_id": "x", "field_type": "nonexistent_type", "label": "X"}
            ]}],
        }
        with pytest.raises(ValidationError):
            assembler.assemble(schema)


class TestAssembleFromSections:
    def test_basic(self, assembler):
        sections = [{"title": "Info", "fields": [
            {"label": "Name", "field_type": "text"},
        ]}]
        form = assembler.assemble_from_sections(sections, title="Test")
        assert len(form.sections) == 1
        assert form.sections[0].fields[0].field_type == FieldType.TEXT


class TestAssembleFromFields:
    def test_wraps_in_default_section(self, assembler):
        fields = [
            {"label": "Name", "field_type": "text", "required": True},
            {"label": "Age", "field_type": "integer"},
        ]
        form = assembler.assemble_from_fields(fields, title="Test")
        assert len(form.sections) == 1
        assert len(form.sections[0].fields) == 2


class TestAssembleField:
    def test_basic(self, assembler):
        field = assembler.assemble_field({"label": "Email", "field_type": "email"})
        assert field.field_id == "email"
        assert field.field_type == FieldType.EMAIL

    def test_invalid_field_raises(self, assembler):
        with pytest.raises((ValidationError, ValueError)):
            assembler.assemble_field({})


class TestAssembleSection:
    def test_basic(self, assembler):
        section = assembler.assemble_section({
            "title": "Contact",
            "fields": [{"label": "Phone", "field_type": "phone"}],
        })
        assert section.section_id is not None
        assert len(section.fields) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-creationformtool.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm all imports and signatures still exist
4. **Create** `packages/parrot-formdesigner/src/parrot_formdesigner/assembler.py`
5. **Create** `packages/parrot-formdesigner/tests/unit/test_assembler.py`
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/unit/test_assembler.py -v`
7. **Run lint**: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/assembler.py`
8. **Update status** in per-spec index → `"in-progress"`, then `"done"`
9. **Move** this file to `sdd/tasks/completed/`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
