# TASK-548: Package Scaffold + Core Models

**Feature**: formdesigner-package
**Feature ID**: FEAT-079
**Spec**: `sdd/specs/formdesigner-package.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-079. It creates the `parrot-formdesigner` package
scaffold following the monorepo layout of `packages/ai-parrot/`, then migrates the core
schema models from `packages/ai-parrot/src/parrot/forms/` into the new package under
`parrot/formdesigner/core/`.

All subsequent tasks (TASK-549 through TASK-555) depend on this scaffold existing.

---

## Scope

- Create the full directory scaffold for `packages/parrot-formdesigner/`
- Write `packages/parrot-formdesigner/pyproject.toml` with correct metadata and dependencies
- Create namespace package layout (NO `__init__.py` at `parrot/` level — implicit namespace)
- Move core form files into `parrot/formdesigner/core/`:
  - `parrot/forms/schema.py` → `parrot/formdesigner/core/schema.py`
  - `parrot/forms/types.py` → `parrot/formdesigner/core/types.py`
  - `parrot/forms/constraints.py` → `parrot/formdesigner/core/constraints.py`
  - `parrot/forms/options.py` → `parrot/formdesigner/core/options.py`
  - `parrot/forms/style.py` → `parrot/formdesigner/core/style.py`
- Update intra-module imports in moved files from `parrot.forms.*` to `parrot.formdesigner.core.*`
- Create `parrot/formdesigner/core/__init__.py` exporting all public symbols
- Create stub `parrot/formdesigner/__init__.py` (will be completed in TASK-554)
- Create `packages/parrot-formdesigner/tests/__init__.py` and `tests/unit/__init__.py`

**NOT in scope**: extractors, renderers, services, tools, handlers, or re-export shim
(those are TASK-549 through TASK-555).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/pyproject.toml` | CREATE | Package metadata, dependencies: pydantic>=2.0, aiohttp>=3.9, asyncdb>=2.0 |
| `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` | CREATE | Stub, will be filled in TASK-554 |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/__init__.py` | CREATE | Export all public core symbols |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` | CREATE | Moved from `parrot/forms/schema.py`, imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/types.py` | CREATE | Moved from `parrot/forms/types.py`, imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/constraints.py` | CREATE | Moved from `parrot/forms/constraints.py`, imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/options.py` | CREATE | Moved from `parrot/forms/options.py`, imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/style.py` | CREATE | Moved from `parrot/forms/style.py`, imports updated |
| `packages/parrot-formdesigner/tests/__init__.py` | CREATE | Empty |
| `packages/parrot-formdesigner/tests/unit/__init__.py` | CREATE | Empty |

---

## Implementation Notes

### Package Layout Pattern
Follow `packages/ai-parrot/` exactly:
```
packages/parrot-formdesigner/
├── pyproject.toml
├── src/
│   └── parrot/            ← NO __init__.py here (namespace package)
│       └── formdesigner/
│           ├── __init__.py
│           └── core/
│               ├── __init__.py
│               ├── schema.py
│               ├── types.py
│               ├── constraints.py
│               ├── options.py
│               └── style.py
└── tests/
    ├── __init__.py
    └── unit/
        └── __init__.py
```

### pyproject.toml Pattern
Base on `packages/ai-parrot/pyproject.toml`. Key differences:
- `name = "parrot-formdesigner"`
- `packages = [{include = "parrot", from = "src"}]`
- Dependencies: `pydantic>=2.0`, `aiohttp>=3.9`, `asyncdb>=2.0`
- Optional dependency: `ai-parrot>=0.9` (for tools subpackage)

### Import Update Pattern
When moving files, replace all occurrences:
- `from parrot.forms.schema import` → `from parrot.formdesigner.core.schema import`
- `from parrot.forms.types import` → `from parrot.formdesigner.core.types import`
- `from parrot.forms.constraints import` → `from parrot.formdesigner.core.constraints import`
- `from parrot.forms.options import` → `from parrot.formdesigner.core.options import`
- `from parrot.forms.style import` → `from parrot.formdesigner.core.style import`
- `from .schema import` / `from .types import` etc. within core files → keep as relative

### Key Constraints
- NO `__init__.py` at `packages/parrot-formdesigner/src/parrot/` — implicit namespace package
- All moved files must preserve original docstrings and type hints
- Use `self.logger = logging.getLogger(__name__)` pattern where classes exist

---

## Acceptance Criteria

- [ ] `packages/parrot-formdesigner/` directory exists with correct layout
- [ ] `uv pip install -e packages/parrot-formdesigner` succeeds
- [ ] `from parrot.formdesigner.core import FormSchema, FormField, FieldType` works
- [ ] `from parrot.formdesigner.core.style import FormStyle` works
- [ ] No `parrot/__init__.py` at the namespace level
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/ -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_core_models.py
import pytest
from parrot.formdesigner.core import FormSchema, FormField, FieldType
from parrot.formdesigner.core.style import FormStyle
from parrot.formdesigner.core.constraints import FieldConstraint
from parrot.formdesigner.core.options import FieldOption


@pytest.fixture
def sample_form_schema() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        fields=[
            FormField(name="name", field_type=FieldType.TEXT, label="Name"),
            FormField(name="email", field_type=FieldType.EMAIL, label="Email"),
        ],
    )


class TestFormSchema:
    def test_initialization(self, sample_form_schema):
        assert sample_form_schema.form_id == "test-form"
        assert len(sample_form_schema.fields) == 2

    def test_field_types(self, sample_form_schema):
        assert sample_form_schema.fields[0].field_type == FieldType.TEXT
        assert sample_form_schema.fields[1].field_type == FieldType.EMAIL

    def test_style_default(self, sample_form_schema):
        # FormStyle should have defaults
        style = FormStyle()
        assert style is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-package.spec.md` for full context
2. **Read the source files** in `packages/ai-parrot/src/parrot/forms/` before copying
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-548-formdesigner-package-scaffold.md`
7. **Update index** → `"done"`
8. **Commit** with message: `sdd: implement TASK-548 package scaffold for parrot-formdesigner`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
