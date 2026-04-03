# TASK-552: Tools Migration

**Feature**: formdesigner-package
**Feature ID**: FEAT-079
**Spec**: `sdd/specs/formdesigner-package.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-548, TASK-551
**Assigned-to**: unassigned

---

## Context

Implements Module 5 of FEAT-079. Moves the form creation tools from
`packages/ai-parrot/src/parrot/forms/tools/` into the new package under
`parrot/formdesigner/tools/`.

Per the spec (Open Questions resolution): The core form creation *methods* move to
`parrot-formdesigner`, while the `AbstractTool`-based thin-client wrappers remain in
`ai-parrot`. This task moves the implementation logic; the thin-client tools in
`parrot/forms/tools/` will be updated in TASK-554 (re-export shim).

---

## Scope

- Move tool implementation files, updating all imports:
  - `parrot/forms/tools/__init__.py` → `parrot/formdesigner/tools/__init__.py`
  - `parrot/forms/tools/create_form.py` → `parrot/formdesigner/tools/create_form.py`
  - `parrot/forms/tools/database_form.py` → `parrot/formdesigner/tools/database_form.py`
  - `parrot/forms/tools/request_form.py` → `parrot/formdesigner/tools/request_form.py`
- Update all intra-module imports from `parrot.forms.*` to `parrot.formdesigner.*`
- `ai-parrot` dependency in `pyproject.toml` is optional (for `AbstractTool` base)
- Create unit tests in `packages/parrot-formdesigner/tests/unit/test_tools.py`
- Move existing tests from `packages/ai-parrot/tests/unit/forms/` to
  `packages/parrot-formdesigner/tests/unit/`

**NOT in scope**: HTTP handlers, re-export shim.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/tools/__init__.py` | CREATE | Exports CreateFormTool, DatabaseFormTool, RequestFormTool |
| `packages/parrot-formdesigner/src/parrot/formdesigner/tools/create_form.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/tools/database_form.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/tools/request_form.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/tests/unit/test_create_form_tool.py` | CREATE | Moved from `packages/ai-parrot/tests/unit/forms/test_create_form_tool.py`, imports updated |
| `packages/parrot-formdesigner/tests/unit/test_request_form_tool.py` | CREATE | Moved from `packages/ai-parrot/tests/unit/forms/test_request_form_tool.py`, imports updated |
| `packages/parrot-formdesigner/tests/unit/test_tools.py` | CREATE | Additional tool tests |

---

## Implementation Notes

### Import Update Pattern
Replace in moved files:
- `from parrot.forms.schema import` → `from parrot.formdesigner.core.schema import`
- `from parrot.forms.types import` → `from parrot.formdesigner.core.types import`
- `from parrot.forms.registry import` → `from parrot.formdesigner.services.registry import`
- `from parrot.forms.storage import` → `from parrot.formdesigner.services.storage import`
- `from parrot.forms.cache import` → `from parrot.formdesigner.services.cache import`

### AbstractTool Dependency
These tools inherit from `AbstractTool` in `ai-parrot`. This is an optional dependency
in `pyproject.toml`. The import should be:
```python
try:
    from parrot.tools import AbstractTool
except ImportError:
    AbstractTool = object  # fallback for standalone use
```

### Key Constraints
- All tool methods must remain async
- Preserve `@tool` decorator usage and docstrings (these become LLM tool descriptions)

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner.tools import CreateFormTool` works
- [ ] `from parrot.formdesigner.tools import DatabaseFormTool` works
- [ ] `from parrot.formdesigner.tools import RequestFormTool` works
- [ ] Existing tests (migrated from ai-parrot) still pass
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_tools.py -v`
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_create_form_tool.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_tools.py
import pytest
from parrot.formdesigner.tools import CreateFormTool, DatabaseFormTool, RequestFormTool
from parrot.formdesigner.core import FormSchema


class TestCreateFormTool:
    def test_initialization(self):
        tool = CreateFormTool()
        assert tool is not None

    def test_has_docstring(self):
        """Tool docstring is used as LLM description — must not be empty."""
        assert CreateFormTool.__doc__ is not None
        assert len(CreateFormTool.__doc__) > 10


class TestDatabaseFormTool:
    def test_initialization(self):
        tool = DatabaseFormTool()
        assert tool is not None


class TestRequestFormTool:
    def test_initialization(self):
        tool = RequestFormTool()
        assert tool is not None
```

---

## Agent Instructions

1. **Verify** TASK-548 and TASK-551 are in `sdd/tasks/completed/` before starting
2. **Read source files** in `packages/ai-parrot/src/parrot/forms/tools/`
3. **Read existing tests** in `packages/ai-parrot/tests/unit/forms/`
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** scope above
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Commit**: `sdd: implement TASK-552 tools migration for parrot-formdesigner`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
