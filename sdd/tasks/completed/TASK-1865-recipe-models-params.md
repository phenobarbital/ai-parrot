# TASK-1865: Recipe models + param resolution (`parrot.outputs.a2ui.recipes`)

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-324. The `InfographicRecipe` Pydantic model IS the persisted "precise
construction instructions": dataset bindings, transform chain, catalog-component layout and
render profile — pure data, no code (spec G1). This task creates the new
`parrot/outputs/a2ui/recipes/` subpackage with the models and the `{param}` resolution engine.
Everything downstream (registry, stores, runner, tools, handler) depends on these shapes.

---

## Scope

- Create subpackage `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/` with
  `__init__.py`, `models.py`, `params.py`.
- Implement models per spec §2 Data Models: `RecipeParam`, `DataSourceSpec`, `TransformStep`,
  `LayoutSpec`, `RenderSpec`, `ScheduleSpec`, `InfographicRecipe`, `TransformerManifest`,
  `RecipeRunError` (all Pydantic v2, Google-style docstrings, strict type hints).
- JSON and YAML round-trip helpers on `InfographicRecipe` (`to_yaml()/from_yaml()`,
  `model_dump_json`/`model_validate_json` suffice for JSON).
- Implement `params.py`: plain `{param}` substitution over strings inside
  `DataSourceSpec.sql`, `DataSourceSpec.conditions` values and `TransformStep.params` values;
  the five built-in relative-date resolvers `current_month`, `previous_month`, `today`,
  `yesterday`, `first_of_month` (configurable timezone, default UTC); rejection of override
  params not declared in `recipe.params` (raise with the offending names).
- Unit tests: round-trip, substitution, all five resolvers, undeclared-override rejection,
  timezone handling.
- A test asserting the G8 import rule: importing `parrot.outputs.a2ui.recipes` must not
  (transitively) import `parrot.tools.dataset_manager`, `parrot.bots`, or `parrot.clients`.

**NOT in scope**: transformer registry/gate (TASK-1866), stores (TASK-1868), runner
(TASK-1869), any DatasetManager interaction.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | CREATE | Public exports of models + param API |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py` | CREATE | All recipe Pydantic models |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py` | CREATE | `{param}` substitution + date resolvers |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/__init__.py` | CREATE | test package |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_models.py` | CREATE | round-trip + validation tests |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_params.py` | CREATE | substitution/resolver tests |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_import_rule.py` | CREATE | G8 one-way import-rule test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, model_validator, ConfigDict  # pydantic v2, used across a2ui
from parrot.outputs.a2ui.models import CreateSurface, Component     # a2ui/__init__.py:12 re-exports models
import yaml                                                          # PyYAML, already a dependency
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class Component(BaseModel):        # line 123 — id, component, properties ($bind-validated)
class CreateSurface(A2UIMessageBase):  # line 167 — surfaceId, catalogId, components, dataModel

# Model shapes to implement — spec §2 "Data Models" (sdd/specs/infographic-builder.spec.md).
# Follow that section verbatim; key fields:
#   InfographicRecipe: schema_version:int=1, name, title, description, owner,
#     params: list[RecipeParam], data_sources: list[DataSourceSpec],
#     transforms: list[TransformStep], layout: LayoutSpec, render: RenderSpec,
#     schedule: Optional[ScheduleSpec], updated_at: datetime
#   RecipeRunError: recipe, stage: Literal["params","data","gate","transform","layout","render"],
#     transformer, dataset, missing_columns, detail
```

### Does NOT Exist
- ~~`parrot/outputs/a2ui/recipes/`~~ — does not exist yet; THIS task creates it
- ~~`InfographicRecipe` / `RecipeParam` / `RecipeRunError`~~ — nothing pre-exists; do not import from elsewhere
- ~~A generic params/templating engine in parrot~~ — `parrot.template.engine.TemplateEngine` exists for Jinja HTML templates (used by legacy InfographicToolkit) but is NOT what this task needs; implement plain `{param}` string substitution (`str.format_map`-style over a validated dict), no Jinja
- ~~`Date.now`-style helpers~~ — use `datetime.now(tz)` with an explicit `zoneinfo.ZoneInfo` timezone argument

---

## Implementation Notes

### Pattern to Follow
```python
# Docstring + model style: copy packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py
# (RenderedArtifact, line 41) — ConfigDict, attribute-documented class docstring,
# @model_validator(mode="after") for cross-field rules.
```

### Key Constraints
- **G8 one-way import rule**: nothing in this subpackage imports DatasetManager, agents,
  or LLM clients. The import-rule test makes this permanent.
- Substitution must be non-eval: only exact `{name}` placeholders replaced from a dict;
  unknown placeholders raise (this doubles as the undeclared-override rejection at the
  data-source level).
- Resolver output is a plain string (ISO date `YYYY-MM-DD`, or `YYYY-MM` for month
  resolvers — document the exact formats in the resolver docstrings).
- Timezone: resolvers accept `tz: str = "UTC"`; resolve via `zoneinfo.ZoneInfo`.
- `updated_at` is set by stores (TASK-1868), not auto-set in the model.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` — binding validation vocabulary (`$bind`)
- `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` — model style to imitate

---

## Acceptance Criteria

- [ ] All models from spec §2 implemented with docstrings + type hints
- [ ] YAML/JSON round-trip lossless (`test_recipe_roundtrip_json_yaml`)
- [ ] `{param}` substitution + 5 resolvers pass tests, undeclared overrides rejected
- [ ] Import-rule test proves no DatasetManager/agents/clients import
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/recipes/`
- [ ] `from parrot.outputs.a2ui.recipes import InfographicRecipe` works

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_params.py
import pytest
from parrot.outputs.a2ui.recipes.params import resolve_params, substitute

def test_resolver_current_month():
    ...  # freeze time or inject "now"; expect "YYYY-MM" format

def test_undeclared_override_rejected():
    with pytest.raises(ValueError, match="not declared"):
        resolve_params(declared=[...], overrides={"typo_param": "x"})

def test_substitute_leaves_no_placeholders():
    assert substitute("WHERE month = '{month}'", {"month": "2026-07"}) == "WHERE month = '2026-07'"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/infographic-builder.spec.md` (§2 Data Models is normative)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing code
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-22
**Notes**: Implemented all models from spec §2 verbatim (`RecipeParam`,
`DataSourceSpec`, `TransformStep`, `LayoutSpec`, `RenderSpec`, `ScheduleSpec`,
`InfographicRecipe`, `TransformerManifest`, `RecipeRunError`) plus
`InfographicRecipe.to_yaml()/from_yaml()` round-trip helpers. `params.py`
implements plain `{name}` substitution (regex-based, non-eval) and the five
built-in relative-date resolvers via `zoneinfo.ZoneInfo`. 21 tests pass
(`pytest packages/ai-parrot/tests/outputs/a2ui/recipes/ -v`); `ruff check`
clean. The G8 import-rule test has both a static AST-free grep-style scan and
a subprocess-isolated dynamic import check (mirrors
`packages/ai-parrot/conftest.py`'s src-path insertion so it resolves against
this worktree, not a stale editable-install path).

**Deviations from spec**: None.
