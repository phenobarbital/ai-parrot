# TASK-519: Form Validators

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 2 from the spec. Migrates the existing `FormValidator` from `parrot/integrations/msteams/dialogs/validator.py` to the new `parrot/forms/` package and enhances it with new validation types. The validator is platform-agnostic — it validates form submissions against `FormSchema` constraints without any rendering knowledge.

---

## Scope

- Implement `parrot/forms/validators.py` with `FormValidator` and `ValidationResult`
- Migrate existing validation logic (required, min/max length, pattern, min/max value, email, URL)
- Add new validation types:
  - `CROSS_FIELD` — validation rules referencing other fields (e.g., end_date > start_date)
  - `ASYNC_REMOTE` — server-side async validation via callback
  - `FILE_TYPE` — MIME type validation for file uploads
  - `UNIQUE` — uniqueness check via callback
- Validate `DependencyRule` for circular references (build directed graph, detect cycles)
- Support i18n error messages (locale parameter)
- Write unit tests

**NOT in scope**: Renderer-specific validation, LLM validation, storage. Moving/deleting the old validator file (that's TASK-532/533).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/validators.py` | CREATE | FormValidator, ValidationResult |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Export FormValidator, ValidationResult |
| `packages/ai-parrot/tests/unit/forms/test_validators.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Reference the existing validator at `parrot/integrations/msteams/dialogs/validator.py` for the core validation logic (required, length, pattern, numeric range, email regex, URL regex). Extend with new types.

```python
class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]  # field_id -> error messages
    sanitized_data: dict[str, Any]

class FormValidator:
    async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str = "en") -> ValidationResult: ...
    async def validate_field(self, field: FormField, value: Any, *, all_data: dict[str, Any] | None = None, locale: str = "en") -> list[str]: ...
```

For circular dependency detection:
```python
def _detect_circular_dependencies(self, form: FormSchema) -> list[str]:
    """Build directed graph of field depends_on references, detect cycles via DFS."""
```

### Key Constraints
- Must be async (`validate` and `validate_field` are async for ASYNC_REMOTE support)
- Cross-field validation needs access to `all_data` dict
- ASYNC_REMOTE and UNIQUE use callback functions passed via `FormField.meta` dict
- Error messages should respect locale via `LocalizedString` resolution
- Circular dependency detection runs at validation time, not schema creation time

### References in Codebase
- `parrot/integrations/msteams/dialogs/validator.py` — existing FormValidator with ValidationResult, EMAIL_PATTERN, URL_PATTERN

---

## Acceptance Criteria

- [ ] `FormValidator.validate()` returns `ValidationResult` with field-level errors
- [ ] Required field validation works
- [ ] min_length, max_length, pattern, min_value, max_value constraints enforced
- [ ] Cross-field validation works (e.g., end_date > start_date)
- [ ] Circular dependency detection catches cycles and raises clear error
- [ ] i18n error messages work with locale parameter
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_validators.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_validators.py
import pytest
from parrot.forms import FormSchema, FormField, FormSection, FieldType, FieldConstraints
from parrot.forms.validators import FormValidator, ValidationResult


@pytest.fixture
def validator():
    return FormValidator()


class TestFormValidator:
    async def test_required_field_missing(self, validator):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)
            ])
        ])
        result = await validator.validate(form, {})
        assert not result.is_valid
        assert "name" in result.errors

    async def test_min_max_length(self, validator):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="code", field_type=FieldType.TEXT, label="Code",
                          constraints=FieldConstraints(min_length=3, max_length=10))
            ])
        ])
        result = await validator.validate(form, {"code": "ab"})
        assert not result.is_valid

    async def test_pattern_validation(self, validator):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="zip", field_type=FieldType.TEXT, label="ZIP",
                          constraints=FieldConstraints(pattern=r"^\d{5}$"))
            ])
        ])
        result = await validator.validate(form, {"zip": "abc"})
        assert not result.is_valid

    async def test_valid_submission(self, validator):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)
            ])
        ])
        result = await validator.validate(form, {"name": "Alice"})
        assert result.is_valid

    async def test_circular_dependency_detected(self, validator):
        """DependencyRule with circular reference is caught."""
        from parrot.forms import DependencyRule, FieldCondition, ConditionOperator
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="a", field_type=FieldType.TEXT, label="A",
                          depends_on=DependencyRule(
                              conditions=[FieldCondition(field_id="b", operator=ConditionOperator.EQ, value="x")])),
                FormField(field_id="b", field_type=FieldType.TEXT, label="B",
                          depends_on=DependencyRule(
                              conditions=[FieldCondition(field_id="a", operator=ConditionOperator.EQ, value="y")])),
            ])
        ])
        result = await validator.validate(form, {"a": "x", "b": "y"})
        # Should detect cycle and report it
        assert not result.is_valid or "circular" in str(result.errors).lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Read** `parrot/integrations/msteams/dialogs/validator.py` for existing logic to migrate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-519-form-validators.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: validators.py created with async FormValidator and Pydantic ValidationResult. Migrated all validation logic from old validator.py (required, min/max length, pattern, numeric bounds, email, URL, phone). Added cross-field validation (meta callbacks), async_validator callbacks. Circular dependency detection uses DFS over directed graph. 22 unit tests pass.

**Deviations from spec**: none
