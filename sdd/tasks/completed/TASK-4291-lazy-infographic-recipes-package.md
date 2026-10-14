# TASK-4291: PEP 562 lazy parrot.tools.infographic_recipes package

**Feature**: FEAT-668 — A2UI Lazy Imports
**Spec**: `sdd/specs/a2ui-lazy-imports.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `tools/infographic_recipes/__init__.py:12-18` eagerly imports
`freeze` and `runner`. Importing a leaf submodule therefore runs the package
`__init__` first: `bots/mixins/narrative.py:24` only wants
`figure_guard.figures_are_derivable`, but it ends up importing `runner` →
`artifacts`/`builders` → catalog registration.

---

## Scope

- Replace the eager imports with a PEP 562 `__getattr__` that resolves the six public names on first access. Keep `__all__` unchanged.
- Keep static typing intact with `if TYPE_CHECKING:` imports.

**NOT in scope**: `runner.py`, `freeze.py`, `loader.py`, `figure_guard.py` (unchanged), and the regression tests (TASK-4293).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py` | MODIFY | lazy `__getattr__` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_recipes.freeze import FreezeProvenanceError, FreezeValidationError, freeze_session_envelope  # verified: __init__.py:12-16
from parrot.tools.infographic_recipes.loader import load_transformer_module   # verified: __init__.py:17
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner  # verified: __init__.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py (current, 27 lines)
# lines 1-10: module docstring — KEEP verbatim
# lines 12-18: the three eager imports above — REPLACE
__all__ = [                                  # lines 20-27 — KEEP verbatim
    "RecipeRunException", "RecipeRunner", "FreezeProvenanceError",
    "FreezeValidationError", "freeze_session_envelope", "load_transformer_module",
]
# NOTE: the file has NO `from __future__ import annotations` today.
```
Submodules in the package: `figure_guard.py`, `freeze.py`, `loader.py`, `narrator.py`, `runner.py`.

### Does NOT Exist
- ~~other public names in `parrot.tools.infographic_recipes`~~ — only the six in `__all__`; `figure_guard`/`narrator` are imported by full submodule path.
- ~~a `__dir__` in the package today~~ — add one so `dir()` / tab completion still list the lazy names.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `from parrot.tools.infographic_recipes import RecipeRunner` must keep working. PEP 562 `__getattr__` handles `from pkg import name`.
- Cache each resolved name with `globals()[name] = value`, so `__getattr__` runs at most once per name.
- Unknown names raise `AttributeError(f"module {__name__!r} has no attribute {name!r}")` — *because* `hasattr()` and `importlib` rely on that exact exception type.

---

## Implementation Blueprint

### Steps (in order)
1. Keep the docstring (lines 1-10); replace lines 12-18 with the block below — *why*: spec §3 M3 skeleton.
2. Keep `__all__` verbatim, then append `__getattr__` and `__dir__`.
3. Run the Validation Commands.

### `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.infographic_recipes.freeze import (' __init__.py) — line 12
# REPLACE lines 12-18 with:
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parrot.tools.infographic_recipes.freeze import (
        FreezeProvenanceError,
        FreezeValidationError,
        freeze_session_envelope,
    )
    from parrot.tools.infographic_recipes.loader import load_transformer_module
    from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner

# Public name -> defining submodule. Resolved on first attribute access (PEP 562)
# so importing a leaf submodule (figure_guard, loader) does not import runner/freeze
# and, through them, the A2UI builders and catalog registrations (FEAT-668).
_LAZY: dict[str, str] = {
    "FreezeProvenanceError": "freeze",
    "FreezeValidationError": "freeze",
    "freeze_session_envelope": "freeze",
    "load_transformer_module": "loader",
    "RecipeRunException": "runner",
    "RecipeRunner": "runner",
}
```
```python
# APPEND after the existing `__all__ = [...]` block (lines 20-27, kept verbatim):


def __getattr__(name: str) -> Any:
    """Resolve a public name from its submodule on first access (PEP 562).

    Raises:
        AttributeError: for names not in ``_LAZY``.
    """
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{submodule}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include the lazily resolved public names."""
    return sorted(set(globals()) | set(__all__))
```
**Why**: `from __future__` must be the first statement after the docstring. That is why it replaces line 12 rather than going later in the file.

### FILL IN checklist
- [ ] none — mechanical.

---

## Acceptance Criteria

- [ ] `python -c "import sys, parrot.tools.infographic_recipes.figure_guard; assert 'parrot.tools.infographic_recipes.runner' not in sys.modules"` succeeds.
- [ ] `from parrot.tools.infographic_recipes import <name>` works for all six names in `__all__` (spec AC4).
- [ ] Existing infographic_recipes tests pass.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/infographic_recipes/test_figure_guard.py -q`
- `pytest packages/ai-parrot/tests/tools/infographic_recipes/test_narrator_protocol.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard_transformers.py -q`

---

## Test Specification

Import isolation and name resolution are asserted in TASK-4293 (`test_infographic_recipes_lazy_attrs_resolve`).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug a2ui-lazy-imports --feature-id FEAT-668`).
2. Read the spec. 3. No dependencies. 4. Verify the Codebase Contract.
5. Mark `in-progress`. 6. Implement. 7. Validate with `PYTHONPATH=packages/ai-parrot/src`.
8. Commit only the listed file. 9. `scripts/sdd/close_task.sh TASK-4291 a2ui-lazy-imports verified`. 10. Fill in the Completion Note and commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none


## Completion Note

Delivered by seat glm / zai.glm-4.7-flash (nova), merged by the engine (attempt 1, no retries). Merge-tier validation: touched-scope tests green; the only failures in the sweep are pre-existing/environmental (fakeredis missing, jira oauth, flex_dashboard/finance_reporter e2e — identical on main checkout).
