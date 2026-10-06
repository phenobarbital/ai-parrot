# TASK-4109: QuerysourceToolkit — build-time python-transform gate in `_build_linked_source`

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4105
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 + codex S8. Agents author linked surfaces through `qs_build_linked_surface` /
`qs_build_linked_dashboard`. Once TASK-4104 lands, `TransformSpec.model_validate` already PARSES a `python` member;
this task adds the registry/manifest gate so an agent naming an unregistered transformer (or the wrong input alias)
gets a correcting `InvalidConditionsError` at build time instead of a surface that 422s later.

**Edit-site correction vs spec §6**: the spec lists two toolkit anchors (`toolkit.py:489` and `:637`). Only `:637`
(`_build_linked_source`) needs the gate. The `:489` widget lane builds a `DerivedDataSource`, which TASK-4104 makes
reject `python`; that `ValueError` is already wrapped into `InvalidConditionsError` at `toolkit.py:498-499`. Both the
single-surface tool (`build_linked_surface(..., transform=...)` → `DashboardSource`, `toolkit.py:384`) and dashboard
sources flow through `_build_linked_source`.

---

## Scope

- After the `LinkedDataSource` is built in `_build_linked_source`, run `validate_python_transform` when
  `transform.python` is set; raise `InvalidConditionsError` listing the problems.
- Document the `python` member in the `build_linked_surface` / `build_linked_dashboard` docstrings (LLM-facing).
- Write tests.

**NOT in scope**: running the transformer (the existing build-time probe already executes through `execute_sources`,
which applies it after TASK-4106); widget-lane changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | gate in `_build_linked_source` + docstrings |
| `packages/ai-parrot-tools/tests/querysource/test_build_linked_python_transform.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource.errors import InvalidConditionsError     # verified: toolkit.py:41-42
from parrot.outputs.a2ui.linked.pytransform import validate_python_transform  # created by TASK-4105 (import function-locally, like toolkit.py:620)
from parrot_tools.querysource.toolkit import QuerysourceToolkit         # verified: test_build_linked_surface_tool.py:13
from parrot.outputs.a2ui.recipes.transformers import transformer_registry  # verified: recipes/transformers.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
async def build_linked_surface(self, slug, component, *, ..., transform: dict[str, Any] | None = None) -> dict  # line ~350-362; DashboardSource(... transform=transform) at 384
def _build_linked_source(self, spec, detail, *, key: str) -> LinkedDataSource:   # body 616-640
    # line 620: from parrot.outputs.a2ui.linked.models import LinkedDataSource, RefreshPolicy, SourceRequest, TransformSpec
    # line 628: transform = spec.transform if isinstance(spec, DashboardSource) else None
    # line 629-640: return LinkedDataSource(..., transform=TransformSpec.model_validate(transform) if transform else None, ...)
# widget lane: toolkit.py:487-499 — DerivedDataSource.model_validate inside try/except ValueError → InvalidConditionsError

# tests: fake_core_qs fixture (test_build_linked_surface_tool.py:16-50, depends on conftest `patched_qs`);
#        toolkit = QuerysourceToolkit(dsn="postgres://fake"); await toolkit.build_linked_surface(slug, component, ...)
```

### Does NOT Exist
- ~~a toolkit-level transformer registry~~ — use `transformer_registry` via the shared gate only.
- ~~`validate_inputs` here~~ — recipe-only API; use `validate_python_transform`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_build_linked_python_transform.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit._build_linked_source",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.build_linked_surface"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Turn the `return LinkedDataSource(...)` at `toolkit.py:629` into `source = LinkedDataSource(...)` — *why*: the gate needs the parsed source before returning.
2. Add the gate, then `return source` — *why*: S8/AC9 build-time rejection.
3. Update the two tool docstrings — *why*: docstrings are the LLM's tool description (codebase conventions).
4. Write tests; run the Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'transform=TransformSpec.model_validate(transform) if transform else None,' querysource/toolkit.py)
# REPLACE `return LinkedDataSource(` (toolkit.py:629) with `source = LinkedDataSource(` and, AFTER the closing `)`
# of that constructor (toolkit.py:640), insert:
        if source.transform is not None and source.transform.python is not None:
            from parrot.outputs.a2ui.linked.pytransform import validate_python_transform

            problems = validate_python_transform(source.transform.python)
            if problems:
                raise InvalidConditionsError(f"source '{key}': invalid python transform — {'; '.join(problems)}")
        return source
```
**Why**: `key` is the source key already passed in; the message names it so the agent can fix the right source.

### Docstrings (MODIFY)
```python
# FILL IN: in build_linked_surface's docstring (sentence "``transform`` accepts the linked transform DSL.", ~toolkit.py:377)
#   and build_linked_dashboard's source-level transform sentence (~toolkit.py:617), add: a source may instead declare
#   {"python": {"transformer": "<registered name>", "params": {...}, "input_alias": "source", "output": null}} — a
#   server-side registered transformer; it is terminal (no derived views/joins may consume that source) and the
#   renderer fetches it through the server — bounded by: two sentences max, no other docstring edits.
```

### `packages/ai-parrot-tools/tests/querysource/test_build_linked_python_transform.py` (CREATE)
```python
"""FEAT-636 TASK-4109 — build-time python-transform gate."""

from __future__ import annotations

import pytest

from parrot.outputs.a2ui.recipes.transformers import transformer_registry
from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.toolkit import QuerysourceToolkit

from .test_build_linked_surface_tool import fake_core_qs  # noqa: F401 — established fixture

COMPONENT = {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]}


@pytest.fixture
def py_registry(monkeypatch):
    monkeypatch.setattr(transformer_registry, "_transformers", {})
    transformer_registry.register("t636_identity", lambda inputs, params: {"result": inputs["source"]})
    return transformer_registry


async def test_unregistered_transformer_rejected(fake_core_qs, py_registry):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError, match="invalid python transform"):
        await toolkit.build_linked_surface("epson_field_activity", COMPONENT, transform={"python": {"transformer": "nope"}})


# FILL IN: test_registered_transformer_accepted → descriptor carries transform.python.transformer == "t636_identity"
# FILL IN: test_alias_mismatch_rejected → register with requires_columns={"df": ["day"]}, default alias → rejected
# FILL IN: test_derived_widget_python_rejected → dashboard widget with source + python transform → InvalidConditionsError
```

### FILL IN checklist
- [ ] two docstring sentences
- [ ] three remaining tests

---

## Acceptance Criteria

- [ ] AC9 (spec, toolkit half): `qs_build_linked_surface` / dashboard sources reject unregistered transformers and alias mismatches with `InvalidConditionsError`.
- [ ] Existing toolkit tests pass unchanged (`test_build_linked_surface_tool.py`, `test_build_linked_dashboard_tool.py`).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_build_linked_python_transform.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_build_linked_dashboard_tool.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`), with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
2. Confirm TASK-4105 is `done` (TASK-4104 transitively) in the per-spec index.
3. Verify the Codebase Contract; start from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4109 linked-a2ui-recipes-transforms verified` and fill the Completion Note
   (record the edit-site correction under "Deviations from spec").

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: single gate at `_build_linked_source` (toolkit.py:637); the widget lane (toolkit.py:489) is covered by TASK-4104's derived-source rejection.
