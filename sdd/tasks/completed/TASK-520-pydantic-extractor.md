# TASK-520: Pydantic Extractor

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 3 from the spec. Creates a schema extractor that introspects Pydantic BaseModel classes to produce `FormSchema`. This is the most important extractor — the Tool Extractor (TASK-521) delegates to it, and it's the foundation for LLM-driven form creation.

---

## Scope

- Create `parrot/forms/extractors/` package with `__init__.py`
- Implement `parrot/forms/extractors/pydantic.py` with `PydanticExtractor`
- Map Python types to FieldType: `str` → TEXT, `int` → INTEGER, `float` → NUMBER, `bool` → BOOLEAN, `datetime` → DATETIME, `date` → DATE
- Handle `Optional[T]` → field with `required=False`
- Handle `Literal["a", "b"]` → SELECT with options
- Handle `Enum` subclass → SELECT with enum values as options
- Handle nested `BaseModel` → GROUP field with children
- Handle `list[T]` → ARRAY field with item_template
- Extract `Field()` metadata: `description`, `title` (as label), `ge`/`le`/`gt`/`lt` (as constraints), `min_length`/`max_length`, `pattern`
- Support `locale` parameter for generated labels
- Write unit tests

**NOT in scope**: Tool-specific extraction logic (TASK-521), YAML parsing (TASK-522), JSON Schema extraction (TASK-523).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/extractors/__init__.py` | CREATE | Package init, export PydanticExtractor |
| `packages/ai-parrot/src/parrot/forms/extractors/pydantic.py` | CREATE | PydanticExtractor implementation |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Export PydanticExtractor |
| `packages/ai-parrot/tests/unit/forms/test_pydantic_extractor.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Migrate and extend the introspection logic from:
- `FormField.from_pydantic_field()` in `parrot/integrations/dialogs/models.py` (lines 93-148)
- `LLMFormGenerator._schema_property_to_field()` and `_determine_field_type()` in `parrot/integrations/dialogs/llm_generator.py`

```python
class PydanticExtractor:
    def extract(
        self,
        model: type[BaseModel],
        *,
        form_id: str | None = None,
        title: str | None = None,
        locale: str = "en",
    ) -> FormSchema:
        """Introspect a Pydantic model and produce a FormSchema."""
```

### Key Constraints
- Must support Pydantic v2 API (`model_fields`, `model_json_schema()`, `FieldInfo`)
- Use `typing.get_origin()` and `typing.get_args()` for type introspection
- Auto-generate `form_id` from model class name if not provided
- Auto-generate `title` from model class name (CamelCase → "Camel Case") if not provided
- Handle `Annotated[T, Field(...)]` types correctly
- Must NOT call the model constructor — only inspect the class

### References in Codebase
- `parrot/integrations/dialogs/models.py:93-148` — `FormField.from_pydantic_field()` existing logic
- `parrot/integrations/dialogs/llm_generator.py` — `_schema_property_to_field()`, `_determine_field_type()`
- `parrot/tools/abstract.py` — `get_schema()` for JSON schema generation pattern

---

## Acceptance Criteria

- [ ] Simple Pydantic model → FormSchema with correct field types
- [ ] Optional fields → `required=False`
- [ ] Literal types → SELECT with options
- [ ] Enum types → SELECT with enum values
- [ ] Nested BaseModel → GROUP field with children
- [ ] `list[T]` → ARRAY field with item_template
- [ ] `Field()` metadata (description, ge/le, min_length, max_length, pattern) extracted as constraints
- [ ] Import works: `from parrot.forms.extractors import PydanticExtractor`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_pydantic_extractor.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_pydantic_extractor.py
import pytest
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field
from parrot.forms import FieldType, FormSchema
from parrot.forms.extractors.pydantic import PydanticExtractor


@pytest.fixture
def extractor():
    return PydanticExtractor()


class TestPydanticExtractor:
    def test_basic_model(self, extractor):
        class User(BaseModel):
            name: str
            age: int
        schema = extractor.extract(User)
        assert schema.form_id == "user"
        fields = schema.sections[0].fields
        assert fields[0].field_type == FieldType.TEXT
        assert fields[1].field_type == FieldType.INTEGER

    def test_optional_field(self, extractor):
        class Form(BaseModel):
            notes: Optional[str] = None
        schema = extractor.extract(Form)
        assert schema.sections[0].fields[0].required is False

    def test_literal_becomes_select(self, extractor):
        class Form(BaseModel):
            color: Literal["red", "green", "blue"]
        schema = extractor.extract(Form)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.SELECT
        assert len(field.options) == 3

    def test_enum_becomes_select(self, extractor):
        class Color(str, Enum):
            RED = "red"
            GREEN = "green"
        class Form(BaseModel):
            color: Color
        schema = extractor.extract(Form)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.SELECT

    def test_nested_model_becomes_group(self, extractor):
        class Address(BaseModel):
            street: str
            city: str
        class User(BaseModel):
            name: str
            address: Address
        schema = extractor.extract(User)
        addr_field = [f for f in schema.sections[0].fields if f.field_id == "address"][0]
        assert addr_field.field_type == FieldType.GROUP
        assert len(addr_field.children) == 2

    def test_list_becomes_array(self, extractor):
        class Form(BaseModel):
            tags: list[str]
        schema = extractor.extract(Form)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.ARRAY

    def test_field_constraints_extracted(self, extractor):
        class Form(BaseModel):
            code: str = Field(..., min_length=3, max_length=10, pattern=r"^[A-Z]+$")
        schema = extractor.extract(Form)
        c = schema.sections[0].fields[0].constraints
        assert c.min_length == 3
        assert c.max_length == 10
        assert c.pattern == r"^[A-Z]+$"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Read** `parrot/integrations/dialogs/models.py` lines 93-148 and `parrot/integrations/dialogs/llm_generator.py` for existing introspection logic
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-520-pydantic-extractor.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: PydanticExtractor implemented with full type mapping (str/int/float/bool/datetime/date/time/Literal/Enum/nested BaseModel/list). Uses Pydantic v2 is_required() API and PydanticUndefinedType check. FieldConstraints extracted from field_info.metadata. 25 unit tests pass.

**Deviations from spec**: none | describe if any
