# TASK-1885: Tier-2 publication — recipe mapping, gap report, delivery

**Feature**: FEAT-326 — DataAgent Infographic — Infographic Authoring for Data Agents
**Spec**: `sdd/specs/dataagent-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1884
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-326. Tier-2 of the two-tier model (spec G-2): `publish_recipe()` maps the
authored section builds onto **registered transformers** as `TransformStep`s and saves a
FEAT-324 `InfographicRecipe`. FEAT-324 spec G1 is inviolable — recipes never store executable
code. Partial transformer coverage yields a structured `GapReport` (suggested source for HUMAN
registration) and saves nothing. Published recipes carry the `SectionDescriptor` as an
**additive optional field** and their delivery config in `RenderSpec.delivery` (both resolved
brainstorm decisions).

---

## Scope

- Add `section_descriptor: Optional[SectionDescriptor] = None` to `InfographicRecipe`
  (`parrot/outputs/a2ui/recipes/models.py`). **Do NOT bump `schema_version`** — the field is
  additive/optional and the docstring (models.py:156) reserves bumps for BREAKING changes;
  `SUPPORTED_SCHEMA_VERSION` (store.py:56) is a strict-equality gate, so a bump would refuse
  every existing recipe. Old recipes (field absent) must keep loading.
- Implement `InfographicAuthoringMixin.publish_recipe(name, descriptor, owner=None,
  delivery=None, overwrite=False) -> InfographicRecipe | GapReport` in
  `parrot/bots/mixins/infographic_authoring.py`:
  - Resolve each section build to a registered transformer (`transformer_registry.get(name)`
    lookup semantics) → `TransformStep(transformer=..., inputs=..., params=..., output_key=...)`.
  - Full coverage → build `InfographicRecipe` (with `section_descriptor` and
    `RenderSpec(delivery=delivery)`) and `await recipe_store.save(recipe)`.
  - ANY unmapped section → return `GapReport` (per-gap `proposed_name` + `suggested_source`);
    recipe NOT saved, not even partially.
  - `(name, owner)` already exists and `overwrite=False` → raise a clear error.
- Round-trip test through `FileRecipeStore` proving `section_descriptor` survives save/get and
  legacy recipes still load.
- Unit tests.

**NOT in scope**: registering the actual domain transformers (TASK-1887), scheduler/system
account (TASK-1886), `RecipeRunner` changes (none allowed — it stays untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py` | MODIFY | Additive optional `section_descriptor` field |
| `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` | MODIFY | `publish_recipe()` |
| `packages/ai-parrot/tests/unit/bots/test_publish_recipe.py` | CREATE | Unit tests |
| `packages/ai-parrot/tests/unit/outputs/test_recipe_section_descriptor.py` | CREATE | Model/store round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_sections import SectionDescriptor, GapReport, TransformerGap
# created by TASK-1882
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class RenderSpec(BaseModel):                                  # line 108
    profile: str = "interactive-html"
    delivery: Optional[dict[str, Any]] = None                 # line 122
class InfographicRecipe(BaseModel):                           # line 149
    schema_version: int = 1                                   # line 173
    transforms: list[TransformStep] = Field(default_factory=list)  # line 180
class TransformStep(BaseModel):                               # line 74
    transformer: str; inputs: list[str]; params: dict[str, Any]; output_key: str

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
def infographic_transformer(name, ...): ...                   # line 164 (decorator)
# TransformerRegistry.get(name) raises KeyError listing available names (~line 117-134)
# module-level instance: transformer_registry (~line 62) — verify exact export name

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py
SUPPORTED_SCHEMA_VERSION = 1                                  # line 56 (strict equality gate)
def _check_schema_version(recipe) -> InfographicRecipe: ...   # line 108
class AbstractRecipeStore(ABC):                               # line 125
    async def save(self, recipe: InfographicRecipe) -> None: ...          # line 134
    async def get(self, name, owner=None) -> InfographicRecipe: ...       # line 140
class FileRecipeStore(AbstractRecipeStore): ...               # line 165 — keyed by (name, owner)
```

### Does NOT Exist
- ~~`InfographicRecipe.section_descriptor`~~ — created HERE (optional, no schema bump).
- ~~`publish_recipe` anywhere~~ — created HERE on the mixin.
- ~~partial-recipe persistence~~ — forbidden by design: gap ⇒ nothing saved.
- ~~any mechanism to store/execute python code in a recipe~~ — G1: `GapReport.suggested_source`
  is text for a HUMAN; nothing in this task may ever `exec`/`eval` it.
- ~~`AbstractRecipeStore.exists()`~~ — check collisions via `get()` +
  `RecipeNotFoundError` (store.py:61) `(verify exact exception name before use)`.

---

## Implementation Notes

### Key Constraints
- The transformer registry raises on re-registering a DIFFERENT function under an existing
  name — publication only READS the registry, never writes it.
- `GapReport.suggested_source` should be derived from the section build's recorded
  inputs/outputs (a readable function skeleton), clearly commented as requiring human review
  and registration. It is never executed (assert in a test that publish never calls exec/eval —
  structurally, by code review of scope, and behaviorally by the no-save guarantee).
- Import direction: `parrot/bots/mixins/` may import from `parrot/outputs/a2ui/recipes/`;
  respect FEAT-324's one-way import rule (`parrot.outputs.a2ui` must NOT import
  DatasetManager — that is why `RecipeRunner` lives in `parrot/tools/infographic_recipes/`).

### References in Codebase
- `parrot/outputs/a2ui/recipes/library.py` — existing recipe-construction helpers (read first)
- `parrot/tools/infographic_toolkit.py` — the 4 existing recipe tools (save/list/run/contract)
  exposed when `recipe_store` is set; `publish_recipe` complements (not duplicates) them.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_publish_recipe.py packages/ai-parrot/tests/unit/outputs/test_recipe_section_descriptor.py -v`
- [ ] No linting errors on modified files (`ruff check`)
- [ ] Full coverage → recipe saved with `section_descriptor` + `RenderSpec.delivery` populated
- [ ] Any gap → `GapReport` returned AND `recipe_store.save` never called
- [ ] `(name, owner)` collision without `overwrite=True` → error
- [ ] `schema_version` still 1; a legacy recipe JSON (no `section_descriptor`) loads via
  `FileRecipeStore.get()` unchanged
- [ ] `RecipeRunner` untouched (git diff shows no changes under `parrot/tools/infographic_recipes/`)

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_publish_recipe.py
class TestPublishRecipe:
    async def test_full_coverage_saves_recipe(self, mixin_agent, file_recipe_store): ...
    async def test_recipe_carries_descriptor_and_delivery(self, ...): ...
    async def test_gap_report_blocks_save(self, ...): ...
    async def test_gap_report_lists_proposed_names_and_source(self, ...): ...
    async def test_name_collision_requires_overwrite(self, ...): ...

# packages/ai-parrot/tests/unit/outputs/test_recipe_section_descriptor.py
class TestRecipeSchema:
    def test_section_descriptor_optional_default_none(self): ...
    async def test_roundtrip_through_file_store(self, tmp_path): ...
    async def test_legacy_recipe_without_field_loads(self, tmp_path): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** (TASK-1884 in `completed/`); 3. **Verify the
Codebase Contract** (registry export name, RecipeNotFoundError); 4. **Update index** →
`"in-progress"`; 5. **Implement**; 6. **Verify criteria**; 7. **Move file to completed/**;
8. **Update index** → `"done"`; 9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-24
**Notes**: Added the additive optional `section_descriptor: Optional[SectionDescriptor]
= None` field to `InfographicRecipe` (models.py) — NO schema-version bump
(kept at 1; the store gate is strict-equality on `SUPPORTED_SCHEMA_VERSION`).
Imported `SectionDescriptor` from `parrot.tools.infographic_sections` (pydantic-only,
no DatasetManager import → respects the recipes-core layering rule). Implemented
`InfographicAuthoringMixin.publish_recipe(name, descriptor, owner=None,
delivery=None, overwrite=False) -> InfographicRecipe | GapReport`: collision
check via `store.get` + `RecipeNotFoundError`; section→transformer resolution
by normalised section name via `transformer_registry.get` (read-only); full
coverage builds + saves an `InfographicRecipe` with `data_sources`, `transforms`,
`section_descriptor`, and `RenderSpec(delivery=...)`; ANY gap returns a
`GapReport` (per-gap `suggested_source` skeleton for HUMAN registration — never
executed) and saves nothing. 9 new tests pass; 110 existing recipe tests pass;
`parrot/tools/infographic_recipes/` (RecipeRunner) confirmed untouched via git;
ruff clean.

**Deviations from spec**: none. Design note: the section→transformer mapping key
is the section's `name` (normalised to a Python identifier); a data-splice
recipe's authoritative replay instructions live in `section_descriptor`, while
`layout` carries a minimal `Infographic` component referencing the template.
Whether `RecipeRunner` can reproduce a data-splice artifact end-to-end is
exercised by TASK-1887 (which owns e2e replay); RecipeRunner stays untouched here
per spec.
