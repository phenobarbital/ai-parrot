# TASK-604: Package Exports

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-597, TASK-599, TASK-600
**Assigned-to**: unassigned

---

## Context

Ensures all new public classes are properly exported from package `__init__.py` files at every level: `core/__init__.py`, `services/__init__.py`, and the top-level `parrot.formdesigner.__init__.py`. This enables clean imports like `from parrot.formdesigner import AuthConfig, FormSubmissionStorage`.

Implements Spec Module 8.

---

## Scope

- Update `core/__init__.py` to export `AuthConfig`, `NoAuth`, `BearerAuth`, `ApiKeyAuth`
- Update `services/__init__.py` to export `FormSubmissionStorage`, `FormSubmission`, `SubmissionForwarder`, `ForwardResult`
- Update top-level `__init__.py` to import and export all new public types
- Update `__all__` list in top-level `__init__.py`

**NOT in scope**: Creating the modules (done by TASK-597, 599, 600)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/__init__.py` | MODIFY | Export auth types |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/__init__.py` | MODIFY | Export submission + forwarder types |
| `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` | MODIFY | Export all new public types + update `__all__` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py
# Current imports from core (line 13-32):
from .core import (
    ConditionOperator, DependencyRule, FieldCondition, FieldConstraints,
    FieldOption, FieldSizeHint, FieldStyleHint, FieldType, FormField,
    FormSchema, FormSection, FormStyle, LayoutType, LocalizedString,
    OptionsSource, RenderedForm, StyleSchema, SubmitAction,
)
# Current imports from services (line 41-48):
from .services import (
    FormCache, FormRegistry, FormStorage, FormValidator,
    PostgresFormStorage, ValidationResult,
)
```

### Existing Signatures to Use
```python
# __all__ list starts at line 51 of __init__.py
# Must add new types to this list
```

### Does NOT Exist
- ~~`AuthConfig` in core/__init__.py exports~~ — not exported yet
- ~~`FormSubmissionStorage` in services/__init__.py exports~~ — not exported yet
- ~~`SubmissionForwarder` in services/__init__.py exports~~ — not exported yet

---

## Implementation Notes

### New exports to add:

**core/__init__.py** — add:
```python
from .auth import AuthConfig, NoAuth, BearerAuth, ApiKeyAuth
```

**services/__init__.py** — add:
```python
from .submissions import FormSubmission, FormSubmissionStorage
from .forwarder import SubmissionForwarder, ForwardResult
```

**Top-level __init__.py** — add to core import block:
```python
AuthConfig, NoAuth, BearerAuth, ApiKeyAuth,
```

Add to services import block:
```python
FormSubmission, FormSubmissionStorage, SubmissionForwarder, ForwardResult,
```

Add to `__all__`:
```python
# core — auth
"AuthConfig",
"NoAuth",
"BearerAuth",
"ApiKeyAuth",
# services — submissions
"FormSubmission",
"FormSubmissionStorage",
# services — forwarder
"SubmissionForwarder",
"ForwardResult",
```

### Key Constraints
- Follow existing alphabetical/grouped ordering in `__all__`
- Do not reorder existing exports
- All new classes must be importable via `from parrot.formdesigner import ClassName`

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner import AuthConfig, NoAuth, BearerAuth, ApiKeyAuth` works
- [ ] `from parrot.formdesigner import FormSubmission, FormSubmissionStorage` works
- [ ] `from parrot.formdesigner import SubmissionForwarder, ForwardResult` works
- [ ] `__all__` includes all new types
- [ ] Existing imports unaffected

---

## Test Specification

```python
# tests/test_exports.py
def test_auth_exports():
    from parrot.formdesigner import AuthConfig, NoAuth, BearerAuth, ApiKeyAuth
    assert NoAuth is not None
    assert BearerAuth is not None
    assert ApiKeyAuth is not None

def test_submission_exports():
    from parrot.formdesigner import FormSubmission, FormSubmissionStorage
    assert FormSubmission is not None

def test_forwarder_exports():
    from parrot.formdesigner import SubmissionForwarder, ForwardResult
    assert SubmissionForwarder is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — verify TASK-597, TASK-599, TASK-600 are in `tasks/completed/`
2. **Read all three `__init__.py` files** before modifying
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** the export additions
5. **Verify**: `python -c "from parrot.formdesigner import AuthConfig, FormSubmissionStorage, SubmissionForwarder"`
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
