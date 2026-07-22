# TASK-1866: Transformer registry + fail-fast validation gate

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1865
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-324. Recipes reference transformations by registered name (spec G1 — never
stored code). This task builds the registry (`@infographic_transformer` decorator +
`TransformerRegistry`) and the fail-fast gate that checks each transformer's declared
`requires_columns` against real DataFrames BEFORE anything executes (spec G4).

---

## Scope

- Implement `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py`:
  - `@infographic_transformer(name, *, requires_columns=None, description="")` decorator
    registering pure functions `(inputs: dict[str, Any], params: dict[str, Any]) -> dict`.
  - `RegisteredTransformer` (function + manifest wrapper) and module-level
    `TransformerRegistry` with `get(name)`, `manifest(name)`, `list()` returning
    `TransformerManifest` objects (model from TASK-1865). Unknown name → error listing
    registered names.
  - `params_schema` in the manifest derived from the function signature (typed kwargs) or an
    explicit `params_model: type[BaseModel]` decorator argument — pick ONE mechanism and
    document it.
  - Gate helper `validate_inputs(step: TransformStep, frames: dict[str, pd.DataFrame])
    -> list[RecipeRunError]`: missing required columns (per input alias) and empty DataFrames
    produce `RecipeRunError(stage="gate", ...)` diagnostics naming transformer, dataset alias
    and exact missing columns.
- Unit tests: registration/manifest, duplicate-name rejection, unknown-name error,
  missing-column gate, empty-frame gate.

**NOT in scope**: concrete transformers (TASK-1867), running chains (TASK-1869).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | CREATE | decorator + registry + gate |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | MODIFY | export decorator/registry/gate |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_transformers.py` | CREATE | registry + gate tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd                                       # existing dependency
from parrot.outputs.a2ui.recipes.models import (          # created by TASK-1865
    TransformStep, TransformerManifest, RecipeRunError,
)
```

### Existing Signatures to Use
```python
# From TASK-1865 (verify it is completed and read the actual file first):
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class TransformStep(BaseModel):
    transformer: str; inputs: list[str]; params: dict[str, Any]; output_key: str
class TransformerManifest(BaseModel):
    name: str; description: str
    requires_columns: dict[str, list[str]]   # input alias → required columns
    params_schema: dict[str, Any]
class RecipeRunError(BaseModel):
    recipe: str; stage: Literal[...]; transformer; dataset; missing_columns; detail
```

### Does NOT Exist
- ~~`TransformerRegistry` anywhere in parrot~~ — THIS task creates the only one; grep-verified
  no `register_transform`/`transformer_registry` exists in `parrot/`
- ~~A parrot-wide plugin/entry-point loading system for transformers~~ — registration is by
  import side effect (decorator at module import), like `register_component` in
  `parrot/outputs/a2ui/catalog/__init__.py:57`
- ~~pandas imports inside `parrot.outputs.a2ui.models`~~ — keep pandas OUT of models.py;
  it is allowed here in transformers.py (pandas is not on the G8 forbidden list)

---

## Implementation Notes

### Pattern to Follow
```python
# Registration-by-decorator pattern: copy the shape of
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:57 (register_component) —
# module-level dict registry + decorator + explicit KeyError with available names.
```

### Key Constraints
- Transformers must be treated as pure: the registry stores plain callables; no `exec`/`eval`,
  no dynamic import of user-supplied dotted paths (that would reopen the G1 hole).
- `requires_columns` keys are INPUT ALIASES (matching `TransformStep.inputs` order/names),
  not dataset names — the runner maps aliases to frames.
- Gate returns a LIST of `RecipeRunError` (collect all problems, do not stop at first) so a
  `dry_run` can report everything at once; the runner decides to abort if non-empty.
- Registry must be import-safe under pytest re-imports (idempotent duplicate check: same
  function re-registered under same name is a no-op; different function → error).

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` — registry precedent
- `sdd/specs/infographic-builder.spec.md` §2 New Public Interfaces — normative API shapes

---

## Acceptance Criteria

- [ ] Decorator + registry + manifests implemented per spec §2
- [ ] Gate produces `RecipeRunError(stage="gate")` for missing columns AND empty frames,
      naming transformer/alias/columns (`test_gate_missing_columns_fail_fast`,
      `test_gate_empty_dataset_fail_fast`)
- [ ] Unknown transformer error lists registered names
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/test_transformers.py -v`
- [ ] `ruff check` clean; `from parrot.outputs.a2ui.recipes import infographic_transformer` works

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_transformers.py
import pandas as pd
import pytest
from parrot.outputs.a2ui.recipes import infographic_transformer
from parrot.outputs.a2ui.recipes.transformers import TransformerRegistry, validate_inputs
from parrot.outputs.a2ui.recipes.models import TransformStep

def test_register_and_manifest(): ...
def test_unknown_transformer_lists_available(): ...

def test_gate_missing_columns_fail_fast():
    df = pd.DataFrame({"division": ["A"], "rev_actual": [1.0]})  # rev_budget missing
    errors = validate_inputs(step, {"snap": df})
    assert errors[0].stage == "gate" and "rev_budget" in errors[0].missing_columns

def test_gate_empty_dataset_fail_fast(): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/infographic-builder.spec.md`
2. **Check dependencies** — TASK-1865 must be in `sdd/tasks/completed/`; READ the real
   `models.py` it produced before coding
3. **Verify the Codebase Contract**; update it first if drifted
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
