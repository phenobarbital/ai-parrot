# TASK-526: JSON Schema Renderer

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 9 from the spec. Renders `FormSchema` as two JSON outputs: (1) a structural JSON Schema with custom extensions for form semantics, and (2) a style JSON from `StyleSchema`. This is the "no-renderer" approach — designed for consumption by custom Svelte form-builder components.

---

## Scope

- Implement `parrot/forms/renderers/jsonschema.py` with `JsonSchemaRenderer`
- Produce structural JSON Schema output:
  - Fields as `properties` with standard JSON Schema types and constraints
  - `x-field-type` extension for the original FieldType value
  - `x-section` extension for section grouping (section_id, title, description)
  - `x-depends-on` extension for conditional visibility rules (serialized DependencyRule)
  - `x-options-source` extension for dynamic options
  - `x-placeholder` extension for placeholder text
  - `x-read-only` extension for read-only fields
  - Standard `required` array at section/root level
- Produce style JSON output: `StyleSchema.model_dump()` as separate dict
- `RenderedForm.content` = structural schema, `RenderedForm.style_output` = style dict
- Write unit tests

**NOT in scope**: JSON Schema extraction/input (TASK-523), Svelte component generation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/renderers/jsonschema.py` | CREATE | JsonSchemaRenderer implementation |
| `packages/ai-parrot/src/parrot/forms/renderers/__init__.py` | MODIFY | Export JsonSchemaRenderer |
| `packages/ai-parrot/tests/unit/forms/test_jsonschema_renderer.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
class JsonSchemaRenderer(AbstractFormRenderer):
    async def render(self, form, style=None, *, locale="en", **kwargs) -> RenderedForm:
        structural = self._build_structural_schema(form, locale)
        style_output = style.model_dump() if style else None
        return RenderedForm(
            content=structural,
            content_type="application/schema+json",
            style_output=style_output,
        )

    def _build_structural_schema(self, form: FormSchema, locale: str) -> dict: ...
    def _field_to_property(self, field: FormField, locale: str) -> dict: ...
    def _field_type_to_json_type(self, field_type: FieldType) -> str: ...
```

### Key Constraints
- Structural output must be a valid JSON Schema (passes `jsonschema` validation of the meta-schema)
- Extensions use `x-` prefix (JSON Schema allows this)
- `LocalizedString` resolved to plain string via locale before embedding
- FieldType → JSON Schema type mapping: TEXT/TEXT_AREA/EMAIL/URL/PHONE/PASSWORD → string, NUMBER → number, INTEGER → integer, BOOLEAN → boolean, SELECT → string+enum, MULTI_SELECT → array+enum, GROUP → object, ARRAY → array, DATE/DATETIME/TIME → string+format
- For GROUP fields, recursively build nested `properties`
- For ARRAY fields, build `items` schema from `item_template`

### References in Codebase
- `parrot/tools/abstract.py:get_schema()` — existing JSON Schema generation from Pydantic models

---

## Acceptance Criteria

- [ ] Produces valid JSON Schema (structural output)
- [ ] Extensions present: `x-field-type`, `x-section`, `x-depends-on`, `x-options-source`
- [ ] Style output matches StyleSchema serialization
- [ ] LocalizedString resolved to correct locale
- [ ] GROUP fields produce nested object schemas
- [ ] ARRAY fields produce array schemas with items
- [ ] `content_type` is `"application/schema+json"`
- [ ] Import works: `from parrot.forms.renderers import JsonSchemaRenderer`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_jsonschema_renderer.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_jsonschema_renderer.py
import pytest
from parrot.forms import (
    FormSchema, FormField, FormSection, FieldType, FieldConstraints,
    StyleSchema, LayoutType, FieldOption, DependencyRule, FieldCondition,
    ConditionOperator,
)
from parrot.forms.renderers.jsonschema import JsonSchemaRenderer


@pytest.fixture
def renderer():
    return JsonSchemaRenderer()


class TestJsonSchemaRenderer:
    async def test_structural_output(self, renderer):
        form = FormSchema(form_id="t", title="Test", sections=[
            FormSection(section_id="s1", fields=[
                FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                FormField(field_id="age", field_type=FieldType.INTEGER, label="Age"),
            ])
        ])
        result = await renderer.render(form)
        schema = result.content
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["age"]["type"] == "integer"
        assert "name" in schema.get("required", [])

    async def test_extensions_present(self, renderer):
        form = FormSchema(form_id="t", title="Test", sections=[
            FormSection(section_id="s1", title="Section 1", fields=[
                FormField(field_id="f", field_type=FieldType.EMAIL, label="Email",
                          depends_on=DependencyRule(
                              conditions=[FieldCondition(field_id="x", operator=ConditionOperator.EQ, value=True)],
                              effect="show")),
            ])
        ])
        result = await renderer.render(form)
        prop = result.content["properties"]["f"]
        assert prop.get("x-field-type") == "email"
        assert "x-depends-on" in prop

    async def test_style_output(self, renderer):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="f", field_type=FieldType.TEXT, label="F")
            ])
        ])
        style = StyleSchema(layout=LayoutType.TWO_COLUMN, submit_label="Send")
        result = await renderer.render(form, style)
        assert result.style_output is not None
        assert result.style_output["layout"] == "two_column"
        assert result.style_output["submit_label"] == "Send"

    async def test_select_with_enum(self, renderer):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="color", field_type=FieldType.SELECT, label="Color",
                          options=[FieldOption(value="red", label="Red"),
                                   FieldOption(value="blue", label="Blue")])
            ])
        ])
        result = await renderer.render(form)
        prop = result.content["properties"]["color"]
        assert "enum" in prop
        assert set(prop["enum"]) == {"red", "blue"}

    async def test_content_type(self, renderer):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="f", field_type=FieldType.TEXT, label="F")
            ])
        ])
        result = await renderer.render(form)
        assert result.content_type == "application/schema+json"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-526-jsonschema-renderer.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: JsonSchemaRenderer producing JSON Schema (draft-07) with x-field-type, x-section, x-depends-on, x-placeholder, x-read-only extensions. FieldType→JSON Schema type mapping including format keyword for email/uri/date/date-time/time. SELECT→enum, MULTI_SELECT→array+items.enum. GROUP→nested properties. ARRAY→items from item_template. Constraints mapped to minLength/maxLength/minimum/maximum/multipleOf/pattern/minItems/maxItems. style_output from StyleSchema.model_dump(). 24 tests pass.

**Deviations from spec**: none
