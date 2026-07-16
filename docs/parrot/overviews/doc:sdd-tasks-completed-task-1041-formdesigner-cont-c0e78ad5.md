---
type: Wiki Overview
title: 'TASK-1041: Build `parrot_formdesigner.controls` package (registry + builtin
  seed)'
id: doc:sdd-tasks-completed-task-1041-formdesigner-controls-package-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wave 1, Step 5 of FEAT-152 introduces an extensible registry of form
---

# TASK-1041: Build `parrot_formdesigner.controls` package (registry + builtin seed)

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1040
**Assigned-to**: unassigned

---

## Context

Wave 1, Step 5 of FEAT-152 introduces an extensible registry of form
controls so a UI can populate a drag-and-drop toolbar. The registry
seeds itself at import time from every `FieldType` enum value, with
metadata sourced from `tools.field_helpers._FIELD_SCHEMA_SNIPPETS` (via
the public accessor `get_form_field_schema_snippets()`).

This task builds the registry first (without any HTTP wiring) so that
TASK-1042 (`api/` package) can wire it into
`GET /api/v1/form-controls`.

Spec sections: §1 Goals (form controls registry); §2 Data Models
(`FieldControlMetadata`); §2 New Public Interfaces
(`register_field_control`, `get_controls`, `iter_controls`); §3 Module
4; §6 Codebase Contract (Verified Imports for `FieldType` and
`get_form_field_schema_snippets`).

---

## Scope

- Create `parrot_formdesigner/controls/__init__.py` exporting
  `register_field_control`, `get_controls`, `iter_controls`,
  `FieldControlMetadata`.
- Create `parrot_formdesigner/controls/registry.py`:
  - `FieldControlMetadata` Pydantic model per spec §2 Data Models.
  - Module-level `_REGISTRY: dict[str, FieldControlMetadata]`.
  - `register_field_control(field_type, *, label, description,
    category, icon, snippet, render_hint, supports_constraints,
    is_container=False)` — builds and stores the metadata. Idempotent:
    re-registering the same `field_type` overwrites the previous entry
    and logs a warning via `logging.getLogger(__name__)`.
  - `get_controls() -> list[FieldControlMetadata]` (stable order: the
    order entries were registered).
  - `iter_controls() -> Iterator[FieldControlMetadata]`.
- Create `parrot_formdesigner/controls/builtin.py` that, at import
  time, calls `register_field_control` once per `FieldType` value.
  Metadata seeded from:
  - `snippet` ← deep copy from `get_form_field_schema_snippets()` keyed
    by `field_type.value`.
  - `category`, `icon`, `render_hint`, `is_container` ← per-type
    constants encoded as a `dict` in `builtin.py` (see categorization
    below).
  - `label`, `description` ← short, English-only strings (the LLM-facing
    snippets are localized later if needed).
  - `supports_constraints` ← `True` for value-bearing types (TEXT,
    NUMBER, INTEGER, DATE, etc.); `False` for container types (GROUP,
    ARRAY).
- Add `tests/unit/test_controls_registry.py` covering: `register_field_control`,
  `get_controls`, idempotent overwrite, builtin import seeds every
  `FieldType` value.

**NOT in scope:**
- The `GET /api/v1/form-controls` HTTP endpoint — that goes in
  TASK-1042 (api package), which calls `get_controls()`.
- Adding new control types beyond the existing `FieldType` enum.
- Localizing label / description strings.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/__init__.py` | CREATE | Package marker + re-exports |
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py` | CREATE | Registry + Pydantic model |
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` | CREATE | Seeds every `FieldType` |
| `packages/parrot-formdesigner/tests/unit/test_controls_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (use these VERBATIM)

```python
from parrot_formdesigner.core.types import FieldType
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
from parrot_formdesigner.tools.field_helpers import get_form_field_schema_snippets
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py:158
from pydantic import BaseModel, Field
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
class FieldType(str, Enum):
    TEXT = "text"; TEXT_AREA = "text_area"; NUMBER = "number"; INTEGER = "integer"
    BOOLEAN = "boolean"; DATE = "date"; DATETIME = "datetime"; TIME = "time"
    SELECT = "select"; MULTI_SELECT = "multi_select"; FILE = "file"; IMAGE = "image"
    COLOR = "color"; URL = "url"; EMAIL = "email"; PHONE = "phone"
    PASSWORD = "password"; HIDDEN = "hidden"; GROUP = "group"; ARRAY = "array"
# `FieldType.value` is the canonical str id used as registry key.

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py:158
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]:
    """Returns a deep copy of `_FIELD_SCHEMA_SNIPPETS`, keyed by FieldType.value."""
```

### `FieldControlMetadata` shape (per spec §2)

```python
class FieldControlMetadata(BaseModel):
    type: str                        # FieldType.value
    label: str
    description: str
    category: str                    # "basic" | "selection" | "media" | "layout" | "advanced"
    icon: str                        # consumer-defined glyph name
    snippet: dict[str, Any]          # JSON Schema snippet seed
    render_hint: str                 # "input" | "select" | "container" | ...
    supports_constraints: bool
    is_container: bool = False
```

### Suggested Categorization

| FieldType | category | render_hint | is_container | supports_constraints |
|---|---|---|---|---|
| TEXT, TEXT_AREA, EMAIL, URL, PHONE, PASSWORD | basic | input | F | T |
| NUMBER, INTEGER | basic | input | F | T |
| BOOLEAN | basic | toggle | F | F |
| DATE, DATETIME, TIME | basic | datetime | F | T |
| SELECT | selection | select | F | T |
| MULTI_SELECT | selection | multiselect | F | T |
| COLOR | advanced | color | F | F |
| FILE | media | upload | F | T |
| IMAGE | media | upload | F | T |
| HIDDEN | advanced | hidden | F | F |
| GROUP | layout | container | T | F |
| ARRAY | layout | repeater | T | F |

### Does NOT Exist

- ~~`tools.field_helpers._FIELD_SCHEMA_SNIPPETS` includes `render_hint`
  metadata~~ — it does NOT. `render_hint` is part of THIS new metadata
  layer, not in the existing snippets dict. Use the table above.
- ~~`FieldType.SECTION`~~ — sections are a separate model (`FormSection`),
  not a `FieldType`.
- ~~A `controls/` decorator import~~ — `register_field_control` is a
  plain function, not a decorator. Callers invoke it imperatively in
  `controls/builtin.py`.

---

## Implementation Notes

### Pattern to Follow

Module-level dict + a `register_*` function is the canonical
"registry" pattern in this codebase. See
`packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py`
for the existing renderer registration shape (this task does NOT modify
that file; it just shows the same idiom is welcome).

### Key Constraints

- **`builtin.py` runs once at import time.** It MUST be imported
  exactly once — by TASK-1042's `api/__init__.py` (or `api/routes.py`)
  before `setup_form_api` returns. Re-importing is harmless because
  `register_field_control` is idempotent, but it should not happen on
  every request.
- **Use `get_form_field_schema_snippets()`** (the public accessor),
  NOT `_FIELD_SCHEMA_SNIPPETS` (the private dict).
- **Pydantic v2 syntax** (`BaseModel`, `model_config = ConfigDict(...)`).
- Logger: `logger = logging.getLogger(__name__)` at module level in
  `registry.py`.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.controls import register_field_control,
      get_controls, iter_controls, FieldControlMetadata` succeeds.
- [ ] `register_field_control(FieldType.TEXT, label="Text", ...)` adds
      an entry retrievable by `get_controls()`.
- [ ] `register_field_control(FieldType.TEXT, label="Other", ...)`
      called twice overwrites the first entry; `get_controls()` returns
      one TEXT entry.
- [ ] `import parrot_formdesigner.controls.builtin` registers an entry
      for every `FieldType` value; `len(get_controls()) == len(FieldType)`.
- [ ] Each builtin entry's `category`, `render_hint`, `is_container`,
      `supports_constraints` matches the table in this task.
- [ ] Each builtin entry's `snippet` is a deep copy from
      `get_form_field_schema_snippets()` for that key (when the key is
      present in the snippets dict; otherwise `{}`).
- [ ] `FieldControlMetadata` is a Pydantic v2 model with the listed
      fields.
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_controls_registry.py -v`.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/controls/`.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_controls_registry.py
import pytest
from parrot_formdesigner.controls.registry import (
    register_field_control, get_controls, iter_controls, FieldControlMetadata,
    _REGISTRY,
)
from parrot_formdesigner.core.types import FieldType


@pytest.fixture(autouse=True)
def _clear_registry():
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()


def test_register_basic():
    register_field_control(
        FieldType.TEXT,
        label="Text", description="Single-line text",
        category="basic", icon="text", snippet={"type": "string"},
        render_hint="input", supports_constraints=True,
    )
    controls = get_controls()
    assert len(controls) == 1
    assert controls[0].type == "text"
    assert isinstance(controls[0], FieldControlMetadata)


def test_register_idempotent_overwrite():
    register_field_control(
        FieldType.TEXT, label="A", description="d", category="basic",
        icon="t", snippet={}, render_hint="input", supports_constraints=True,
    )
    register_field_control(
        FieldType.TEXT, label="B", description="d", category="basic",
        icon="t", snippet={}, render_hint="input", supports_constraints=True,
    )
    controls = get_controls()
    assert len(controls) == 1
    assert controls[0].label == "B"


def test_builtin_seeds_every_field_type():
    import parrot_formdesigner.controls.builtin  # noqa: F401 — side-effect import
    controls = get_controls()
    types_seeded = {c.type for c in controls}
    assert types_seeded == {ft.value for ft in FieldType}


def test_builtin_categories_known():
    import parrot_formdesigner.controls.builtin  # noqa: F401
    allowed = {"basic", "selection", "media", "layout", "advanced"}
    for c in get_controls():
        assert c.category in allowed


def test_iter_controls_yields_in_registration_order():
    register_field_control(FieldType.TEXT, label="t", description="d",
        category="basic", icon="t", snippet={}, render_hint="input",
        supports_constraints=True)
    register_field_control(FieldType.NUMBER, label="n", description="d",
        category="basic", icon="n", snippet={}, render_hint="input",
        supports_constraints=True)
    seq = [c.type for c in iter_controls()]
    assert seq == ["text", "number"]
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec sections cited under Context.
2. Verify the imports in §Codebase Contract still resolve (`grep` for
   `class FieldType` in `core/types.py` and
   `def get_form_field_schema_snippets` in `tools/field_helpers.py`).
3. Implement the three files. Run the tests.
4. Move this task to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**: Created `parrot_formdesigner/controls/` package with `FieldControlMetadata` Pydantic v2 model, module-level `_REGISTRY` dict, and idempotent `register_field_control` (logs warning on overwrite). `builtin.py` seeds all 20 `FieldType` values via `_seed()` at import-time using `get_form_field_schema_snippets()` (deep copy). All 9 unit tests pass; `len(get_controls()) == len(FieldType)` after `import builtin`.
