# TASK-1870: InfographicToolkit recipe tools + freeze path

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1869
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-324 — the chat trigger (spec G6) and the LLM half of dual authorship (G2):
an agent composes an infographic in-session, then "freezes" the exact construction into a
persisted recipe replayable without the LLM.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/infographic_recipes/freeze.py`:
  `freeze_session_envelope(envelope, *, dataset_names, transform_steps, name, title, ...)
  -> InfographicRecipe` — normalize a live `CreateSurface` + provenance into a recipe,
  `dry_run` it (TASK-1869), raise with the collected `RecipeRunError`s if not clean.
  Envelopes whose data provenance CANNOT be expressed as recipe steps (e.g. dataModel values
  produced by ad-hoc REPL pandas, not registry transformers) must be rejected with a clear
  message — this is the documented boundary of G2, not a bug (spec §7).
- Extend `InfographicToolkit` (`parrot/tools/infographic_toolkit.py`) with four async tool
  methods (AbstractToolkit auto-exposure; LLM-grade Google-style docstrings):
  - `infographic_save_recipe(...)` — freeze + persist to the configured store.
  - `infographic_list_recipes()` — store `list()` passthrough (lightweight dicts).
  - `infographic_run_recipe(name, params=None)` — `RecipeRunner.run()`; on
    `RecipeRunException` return the structured `RecipeRunError` as tool output (agent
    explains it; no raw traceback).
  - `infographic_get_recipe_contract(name)` — datasets + required columns + declared params
    a recipe needs (from recipe + transformer manifests), so users/operators can verify
    replayability.
- Toolkit `__init__` accepts optional `recipe_store` + `recipe_runner` (or the pieces to
  build one); recipe tools are exposed ONLY when a store is configured (follow the
  `learned_dir`-style conditional-tool precedent in skills tooling).
- Unit tests with mocked store/runner: freeze normalization, dirty-dry-run rejection,
  ad-hoc-provenance rejection, tool output shapes.

**NOT in scope**: REST/scheduler (TASK-1872), renderer (TASK-1871), modifying the existing
template tools (`infographic_render` et al. stay untouched — regression-asserted).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/freeze.py` | CREATE | envelope→recipe normalization + dry-run gate |
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | 4 new tool methods + optional store/runner wiring |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_freeze.py` | CREATE | freeze tests |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_toolkit_tools.py` | CREATE | tool tests (mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                        # infographic_toolkit.py:26 uses it
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, RecipeRunError  # TASK-1865
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore       # TASK-1868
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException  # TASK-1869
from parrot.outputs.a2ui.models import CreateSurface                    # a2ui models
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py — READ BEFORE MODIFYING
class InfographicToolkit(AbstractToolkit):     # line 111
    def __init__(self, ...):                   # line 135 — extend kwargs here (keep defaults back-compat)
    def get_tools(self, **kwargs):             # line 189 — conditional tool exposure happens here
    async def render(self, ...):               # line 245 — DO NOT TOUCH (legacy template path)
    def _build_a2ui_envelope(self, ...):       # line 494 — session envelope source for freeze
    def _snapshot_bot_message(self) -> Dict[str, Any]:  # line 533 — session provenance helper
    async def list_templates(self) -> List[Dict[str, str]]:  # line 611 — naming style to mirror
# Toolkit exposes tools as methods; exclude_tools/tool_prefix conventions visible at
# DatasetManager (tool.py:501, tool_prefix="dataset", exclude_tools tuple near line 522).
```

### Does NOT Exist
- ~~Recipe/replay awareness in today's InfographicToolkit~~ — it has TEMPLATES (FEAT-197
  positional block contracts), not recipes; do not conflate: recipe tools are NEW methods
- ~~`InfographicToolkit.recipe_store` attribute~~ — does not exist yet; THIS task adds it
- ~~Automatic transform-provenance capture from the REPL~~ — freeze receives explicit
  `transform_steps` provenance from the caller; if callers can't provide it, freeze rejects
  (do NOT try to reverse-engineer pandas history)
- ~~`return_direct` requirements for the new tools~~ — the `return_direct=True` machinery
  (toolkit docstring lines 1-13) applies to the legacy `infographic_render` flow; new recipe
  tools return normal structured dicts

---

## Implementation Notes

### Key Constraints
- Tool docstrings ARE the LLM interface — describe purpose, params, returns, and when to use
  each tool (framework rule: every tool MUST have a clear docstring).
- `infographic_run_recipe` catches ONLY `RecipeRunException` → returns
  `{"status": "error", "error": RecipeRunError.model_dump()}`; other exceptions propagate.
- Freeze sets `owner` from the toolkit's resolved scope (see `_resolve_scope`, toolkit line
  1196) so recipes are user/agent-scoped by default.
- Keep the existing toolkit constructor signature backwards-compatible (new kwargs optional,
  default None).

### References in Codebase
- `packages/ai-parrot/src/parrot/skills/tools.py` — conditional write-tool exposure precedent
  (`include_write_tools`) for gating recipe tools on store presence
- `sdd/specs/infographic-builder.spec.md` §2 New Public Interfaces — normative tool names

---

## Acceptance Criteria

- [ ] Four tools exposed only when a recipe store is configured; absent otherwise
- [ ] `test_freeze_normalizes_and_dry_runs` — frozen recipe passes `dry_run`; dirty dry-run
      rejects with all collected errors
- [ ] Ad-hoc provenance (no expressible transform steps) rejected with actionable message
- [ ] `infographic_run_recipe` returns structured `RecipeRunError` on failure (no traceback)
- [ ] Existing template tools unchanged (regression test: tool list without store matches
      pre-task list)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/infographic_recipes/ -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/infographic_recipes/test_toolkit_tools.py
class TestRecipeTools:
    def test_tools_absent_without_store(self): ...
    def test_tools_present_with_store(self): ...
    async def test_run_recipe_returns_structured_error(self, mocked_runner): ...
    async def test_get_recipe_contract_lists_datasets_columns_params(self, ...): ...

# packages/ai-parrot/tests/tools/infographic_recipes/test_freeze.py
class TestFreeze:
    async def test_freeze_normalizes_and_dry_runs(self, ...): ...
    async def test_freeze_rejects_adhoc_provenance(self, ...): ...
```

---

## Agent Instructions

1. **Read the spec** and READ `infographic_toolkit.py` lines 1-260 + 1180-1260 before touching it
2. **Check dependencies** — TASK-1869 completed; read the real runner API
3. **Verify the Codebase Contract**
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-22
**Notes**: Read `infographic_toolkit.py` lines 1-260 + 1180-1294 before
touching it; `render()` (legacy template path) is untouched, regression-
verified via the pre-existing 34-test suite in
`tests/unit/tools/test_infographic_toolkit*.py` (all still pass). Added
`freeze.py` (`freeze_session_envelope`, explicit-provenance-only, rejects
empty `dataset_names`/`transform_steps` and multi-component envelopes,
dry-runs the normalized recipe via the injected `RecipeRunner`). Extended
`InfographicToolkit.__init__` with optional `recipe_store`/`recipe_runner`/
`dataset_manager` kwargs (all default `None`, backward-compatible); when no
`recipe_store` is given, the 4 recipe tool names are appended to
`self.exclude_tools` (mirroring the `skills/tools.py` `include_write_tools`
precedent) so they're absent from `get_tools()` entirely rather than merely
erroring at call time. Four tool methods added right after `build_block`
(`infographic_save_recipe`, `infographic_list_recipes`,
`infographic_run_recipe`, `infographic_get_recipe_contract`) with LLM-grade
docstrings; `infographic_run_recipe` catches ONLY `RecipeRunException` and
returns the structured `RecipeRunError`, letting other exceptions propagate
per spec. 96 tests pass (18 new + 78 pre-existing recipes/runner suites);
`ruff check` clean (pre-existing unused `OutputMode` import at line 39 left
untouched — out of scope, present before this task).

**Deviations from spec**: `infographic_save_recipe`'s tool signature accepts
`layout_component`/`layout_properties` (the two fields `LayoutSpec` actually
needs) rather than a full serialized envelope object — there is no existing
"current session envelope" accessor on the toolkit to reuse (the task's own
contract confirms no automatic provenance capture exists), and `render()`
(the only place that builds an envelope) is explicitly off-limits to modify.
The tool method constructs a throwaway `CreateSurface` via the verified
`build_surface()` and passes THAT to `freeze_session_envelope(envelope,
...)`, honoring the task's literal `freeze_session_envelope(envelope: ...)`
signature while keeping the LLM-facing tool args to what the LLM can
actually supply — consistent with the explicit-provenance principle already
established for `transform_steps`/`dataset_names`.
