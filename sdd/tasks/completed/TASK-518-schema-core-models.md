# TASK-518: Schema Core Models

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-076. Every other task depends on these models. Implements Module 1 from the spec — the canonical Pydantic models that define what a form is (structure, fields, constraints, options, conditional visibility) and how it looks (style, layout).

---

## Scope

- Create `parrot/forms/` package with `__init__.py`
- Implement `parrot/forms/types.py` — `LocalizedString` type alias, `FieldType` enum
- Implement `parrot/forms/constraints.py` — `FieldConstraints`, `ConditionOperator`, `FieldCondition`, `DependencyRule`
- Implement `parrot/forms/options.py` — `FieldOption`, `OptionsSource`
- Implement `parrot/forms/schema.py` — `FormField`, `FormSection`, `SubmitAction`, `FormSchema`, `RenderedForm`
- Implement `parrot/forms/style.py` — `LayoutType`, `FieldSizeHint`, `FieldStyleHint`, `StyleSchema`
- Export all public models from `parrot/forms/__init__.py`
- Write unit tests for all models

**NOT in scope**: Validators, extractors, renderers, registry, storage, tools — those are separate tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/__init__.py` | CREATE | Package init with public exports |
| `packages/ai-parrot/src/parrot/forms/types.py` | CREATE | LocalizedString, FieldType enum |
| `packages/ai-parrot/src/parrot/forms/constraints.py` | CREATE | FieldConstraints, ConditionOperator, FieldCondition, DependencyRule |
| `packages/ai-parrot/src/parrot/forms/options.py` | CREATE | FieldOption, OptionsSource |
| `packages/ai-parrot/src/parrot/forms/schema.py` | CREATE | FormField, FormSection, SubmitAction, FormSchema, RenderedForm |
| `packages/ai-parrot/src/parrot/forms/style.py` | CREATE | LayoutType, FieldSizeHint, FieldStyleHint, StyleSchema |
| `packages/ai-parrot/tests/unit/forms/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/unit/forms/test_schema.py` | CREATE | Unit tests for schema models |
| `packages/ai-parrot/tests/unit/forms/test_style.py` | CREATE | Unit tests for style models |
| `packages/ai-parrot/tests/unit/forms/test_constraints.py` | CREATE | Unit tests for constraints and dependency rules |

---

## Implementation Notes

### Pattern to Follow

Use the same Pydantic BaseModel patterns used throughout the project. Reference the data models section in the spec for exact field definitions.

```python
from pydantic import BaseModel, ConfigDict
from typing import Any, Literal

# LocalizedString supports both simple and i18n usage:
LocalizedString = str | dict[str, str]
# Simple: "Enter your name"
# i18n:   {"en": "Enter your name", "es": "Ingrese su nombre"}
```

### Key Constraints
- All models must use `ConfigDict(extra="forbid")` where specified in the spec (FormField, FieldConstraints)
- `FormField` is self-referential (`children: list["FormField"]`) — use `model_rebuild()` after class definition
- `LocalizedString` is a type alias, not a class — it must work with Pydantic's JSON Schema export
- All enums inherit from `(str, Enum)` for JSON serialization
- `SubmitAction.action_type` uses `Literal["tool_call", "endpoint", "event", "callback"]`
- `DependencyRule.logic` uses `Literal["and", "or"]`
- `DependencyRule.effect` uses `Literal["show", "hide", "require", "disable"]`

### References in Codebase
- `parrot/integrations/dialogs/models.py` — existing FieldType enum and FormField/FormSection (dataclass-based, being replaced)
- `parrot/tools/abstract.py` — AbstractToolArgsSchema pattern for Pydantic BaseModel usage

---

## Acceptance Criteria

- [ ] All models importable: `from parrot.forms import FormSchema, FormField, FormSection, StyleSchema, FieldType, ...`
- [ ] FormSchema round-trips through JSON: `model_dump_json()` → `model_validate_json()` produces identical schema
- [ ] LocalizedString works as plain `str` and as `dict[str, str]`
- [ ] Self-referential FormField (children, item_template) serializes correctly
- [ ] All FieldType enum values can be used in FormField
- [ ] StyleSchema defaults to SINGLE_COLUMN layout
- [ ] DependencyRule serializes with nested FieldCondition list
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_schema.py
import pytest
from parrot.forms import (
    FormSchema, FormField, FormSection, FieldType, FieldConstraints,
    FieldOption, SubmitAction, DependencyRule, FieldCondition,
    ConditionOperator, StyleSchema, LayoutType,
)


class TestFormField:
    def test_basic_field(self):
        field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
        assert field.field_id == "name"
        assert field.required is False

    def test_localized_label_str(self):
        field = FormField(field_id="x", field_type=FieldType.TEXT, label="Name")
        assert field.label == "Name"

    def test_localized_label_dict(self):
        field = FormField(field_id="x", field_type=FieldType.TEXT,
                          label={"en": "Name", "es": "Nombre"})
        assert field.label["en"] == "Name"

    def test_self_referential_children(self):
        child = FormField(field_id="street", field_type=FieldType.TEXT, label="Street")
        parent = FormField(field_id="address", field_type=FieldType.GROUP,
                           label="Address", children=[child])
        assert len(parent.children) == 1

    def test_field_with_constraints(self):
        field = FormField(field_id="email", field_type=FieldType.EMAIL, label="Email",
                          constraints=FieldConstraints(pattern=r".+@.+\..+"))
        assert field.constraints.pattern is not None


class TestFormSchema:
    def test_json_roundtrip(self):
        schema = FormSchema(
            form_id="test", title="Test",
            sections=[FormSection(section_id="s1", fields=[
                FormField(field_id="f1", field_type=FieldType.TEXT, label="F1")
            ])]
        )
        json_str = schema.model_dump_json()
        restored = FormSchema.model_validate_json(json_str)
        assert restored.form_id == schema.form_id
        assert len(restored.sections) == 1

    def test_all_field_types(self):
        for ft in FieldType:
            field = FormField(field_id=f"f_{ft.value}", field_type=ft, label=ft.value)
            assert field.field_type == ft


class TestDependencyRule:
    def test_serialization(self):
        rule = DependencyRule(
            conditions=[FieldCondition(field_id="toggle", operator=ConditionOperator.EQ, value=True)],
            effect="show",
        )
        data = rule.model_dump()
        assert len(data["conditions"]) == 1
        restored = DependencyRule.model_validate(data)
        assert restored.effect == "show"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — this task has no dependencies (it's the foundation)
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-518-schema-core-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: All 6 source files and 4 test files created. 54 unit tests pass. Package installed editable into venv. Self-referential FormField.model_rebuild() applied. All models use Pydantic v2 ConfigDict. LocalizedString type alias works as str | dict[str,str] in all field positions.

**Deviations from spec**: none
