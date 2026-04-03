# TASK-551: Services Migration (Validator, Registry, Cache, Storage)

**Feature**: formdesigner-package
**Feature ID**: FEAT-079
**Spec**: `sdd/specs/formdesigner-package.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-548
**Assigned-to**: unassigned

---

## Context

Implements Module 4 of FEAT-079. Moves the service modules (validator, registry,
cache, storage) from `packages/ai-parrot/src/parrot/forms/` into the new package
under `parrot/formdesigner/services/`.

These services depend only on core models (TASK-548). The tools (TASK-552) and
handlers (TASK-553) depend on these services.

---

## Scope

- Move service files, updating all imports:
  - `parrot/forms/validators.py` → `parrot/formdesigner/services/validators.py`
  - `parrot/forms/registry.py` → `parrot/formdesigner/services/registry.py`
  - `parrot/forms/cache.py` → `parrot/formdesigner/services/cache.py`
  - `parrot/forms/storage.py` → `parrot/formdesigner/services/storage.py`
- Create `parrot/formdesigner/services/__init__.py` exporting all public service classes
- Update all intra-module imports in moved files
- Create unit tests in `packages/parrot-formdesigner/tests/unit/test_services.py`

**NOT in scope**: extractors, renderers, tools, handlers, or re-export shim.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/__init__.py` | CREATE | Exports FormValidator, FormRegistry, FormCache, PostgresFormStorage |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py` | CREATE | Moved from `parrot/forms/validators.py`, imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py` | CREATE | Moved from `parrot/forms/registry.py`, imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/cache.py` | CREATE | Moved from `parrot/forms/cache.py`, imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py` | CREATE | Moved from `parrot/forms/storage.py`, imports updated |
| `packages/parrot-formdesigner/tests/unit/test_services.py` | CREATE | Unit tests |

---

## Implementation Notes

### Import Update Pattern
Replace in all moved files:
- `from parrot.forms.schema import` → `from parrot.formdesigner.core.schema import`
- `from parrot.forms.types import` → `from parrot.formdesigner.core.types import`
- `from parrot.forms.constraints import` → `from parrot.formdesigner.core.constraints import`
- `from parrot.forms.options import` → `from parrot.formdesigner.core.options import`
- `from parrot.forms.style import` → `from parrot.formdesigner.core.style import`

### Key Constraints
- `PostgresFormStorage` uses `asyncdb` — keep async throughout
- `FormRegistry` is likely a singleton/dict store — verify thread-safety pattern
- Use `self.logger = logging.getLogger(__name__)` in all classes that log

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner.services import FormValidator` works
- [ ] `from parrot.formdesigner.services import FormRegistry` works
- [ ] `from parrot.formdesigner.services import FormCache` works
- [ ] `from parrot.formdesigner.services import PostgresFormStorage` works
- [ ] `FormRegistry` can register and retrieve a `FormSchema`
- [ ] `FormValidator` validates a form submission dict against a `FormSchema`
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_services.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_services.py
import pytest
from parrot.formdesigner.core import FormSchema, FormField, FieldType
from parrot.formdesigner.services import FormValidator, FormRegistry


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        fields=[
            FormField(name="name", field_type=FieldType.TEXT, label="Name", required=True),
            FormField(name="email", field_type=FieldType.EMAIL, label="Email"),
        ],
    )


class TestFormRegistry:
    def test_register_and_retrieve(self, sample_schema):
        registry = FormRegistry()
        registry.register(sample_schema)
        retrieved = registry.get("test-form")
        assert retrieved is not None
        assert retrieved.form_id == "test-form"

    def test_list_forms(self, sample_schema):
        registry = FormRegistry()
        registry.register(sample_schema)
        forms = registry.list()
        assert len(forms) >= 1

    def test_get_nonexistent_form(self):
        registry = FormRegistry()
        result = registry.get("nonexistent")
        assert result is None


class TestFormValidator:
    def test_valid_submission(self, sample_schema):
        validator = FormValidator()
        errors = validator.validate(sample_schema, {"name": "John", "email": "john@example.com"})
        assert errors == [] or errors == {}

    def test_missing_required_field(self, sample_schema):
        validator = FormValidator()
        errors = validator.validate(sample_schema, {"email": "john@example.com"})
        assert errors  # should have errors for missing 'name'
```

---

## Agent Instructions

1. **Verify** TASK-548 is in `sdd/tasks/completed/` before starting
2. **Read source files** in `packages/ai-parrot/src/parrot/forms/` (validators.py, registry.py, cache.py, storage.py)
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** scope above
5. **Verify** acceptance criteria
6. **Move** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
8. **Commit**: `sdd: implement TASK-551 services migration for parrot-formdesigner`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
