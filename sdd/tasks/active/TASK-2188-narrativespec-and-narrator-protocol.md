# TASK-2188: `NarrativeSpec` recipe field + `Narrator` protocol

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the **contract half of Module 3**. Two small, independent pieces that
everything else depends on, so they land early and separately from the runner
wiring (TASK-2189).

1. **`NarrativeSpec` + `InfographicRecipe.narrative`** — the *declarative*
   narrative step. This is what keeps FEAT-324's **G1** intact: a recipe stores
   a skill **name**, never code, never a prompt blob. Exactly as a transform
   stores a registered transformer name.

2. **`Narrator` protocol** — the injection seam. It must live under
   `parrot/tools/infographic_recipes/`, **not** under `parrot/outputs/a2ui/`,
   because G8 forbids `outputs/a2ui/**` from importing agents or LLM clients
   (`builders.py:11-12`). `parrot/tools/infographic_recipes/` is the sanctioned
   side — it already imports `DatasetManager` for the same reason.

---

## Scope

- Add `NarrativeSpec(BaseModel)` to `parrot/outputs/a2ui/recipes/models.py` with
  fields `skill: str`, `facts_key: str`, `output_key: str = "narrative"`.
- Add `narrative: Optional[NarrativeSpec] = None` to `InfographicRecipe`.
  **Additive only** — `schema_version` stays `1` (criterion G-G).
- Export `NarrativeSpec` from `parrot/outputs/a2ui/recipes/__init__.py` alongside
  the other recipe models.
- Create `parrot/tools/infographic_recipes/narrator.py` defining a
  `@runtime_checkable` `Narrator` protocol with
  `async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]`.
- Write unit tests: the additive field round-trips, `schema_version` is
  untouched, a pre-feature recipe fixture still loads, and the protocol is
  satisfied by a minimal stub.

**NOT in scope**:
- Any runner change — the ctor param and the pipeline step are TASK-2189.
- The `NarrativeMixin` implementation (TASK-2192).
- The figure guard (TASK-2190).
- Populating `narrative` from a descriptor in `publish_recipe` (TASK-2193).
- Importing anything agent-side or LLM-side into these two modules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py` | MODIFY | Add `NarrativeSpec`; add `narrative` field to `InfographicRecipe` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | MODIFY | Export `NarrativeSpec` |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/narrator.py` | CREATE | `Narrator` protocol (G8-safe side) |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_models.py` | MODIFY | Additive-schema tests |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_narrator_protocol.py` | CREATE | Protocol conformance test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already available in models.py (do not re-add):
from pydantic import BaseModel, Field
from typing import Any, Optional
from parrot.tools.infographic_sections import SectionDescriptor  # used by section_descriptor

# For the new narrator.py:
from __future__ import annotations
from typing import Any, Optional, Protocol, runtime_checkable

# For tests:
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, LayoutSpec, NarrativeSpec
from parrot.tools.infographic_recipes.narrator import Narrator
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class RecipeParam(BaseModel): ...        # line 40
class DataSourceSpec(BaseModel): ...     # line 58
class TransformStep(BaseModel):          # line 79
    transformer: str
    inputs: list[str] = Field(default_factory=list)       # line 93
    params: dict[str, Any] = Field(default_factory=dict)  # line 94
    output_key: str
class LayoutSpec(BaseModel):             # line 98
    component: str
    properties: dict[str, Any] = Field(default_factory=dict)   # line 110
class RenderSpec(BaseModel):             # line 113
    profile: str = "interactive-html"    # line 125
    theme: Optional[str] = None          # line 126
    delivery: Optional[dict[str, Any]] = None   # line 127
class ScheduleSpec(BaseModel): ...       # line 130
class InfographicRecipe(BaseModel):      # line 154
    schema_version: int = 1                                       # line 184  <-- MUST STAY 1
    name: str
    title: str
    description: Optional[str] = None                             # line 187
    owner: Optional[str] = None                                   # line 188
    params: list[RecipeParam] = Field(default_factory=list)       # line 189
    data_sources: list[DataSourceSpec] = Field(default_factory=list)  # line 190
    transforms: list[TransformStep] = Field(default_factory=list) # line 191
    layout: LayoutSpec
    render: RenderSpec = Field(default_factory=RenderSpec)        # line 193
    schedule: Optional[ScheduleSpec] = None                       # line 194
    section_descriptor: Optional[SectionDescriptor] = None        # line 196
    # ^^^ THE ADDITIVE PRECEDENT to copy: added by FEAT-326 without bumping
    #     schema_version. The docstring at line 174 documents it. Follow the
    #     same approach (field + Attributes docstring entry) for `narrative`.
    updated_at: ...   # overwritten by AbstractRecipeStore.save() per spec G5

    def to_yaml(self) -> str: ...                              # line 198
    @classmethod
    def from_yaml(cls, text: str) -> "InfographicRecipe": ...   # line 209
    # ^^^ lossless round-trip pair; the additive `narrative` field must survive both
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py
# Module docstring: "parrot.outputs.a2ui.recipes — recipe models + param resolution"
# Exports the recipe models AND imports library.py for its registration side effect.
from parrot.outputs.a2ui.recipes.transformers import (
    infographic_transformer,   # line 30
    ...
)
__all__ = [..., "infographic_transformer", ...]   # line 66 area
# Add "NarrativeSpec" to both the import block and __all__.
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py — THE G8 RULE, verbatim:
"""
One-way import rule (G8): this module imports only the a2ui core; never agents,
DatasetManager, LLM clients, or the satellite renderers.
"""                                            # lines 11-12
# => The Narrator protocol CANNOT live under parrot/outputs/a2ui/.

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py — module docstring:
"""
Lives OUTSIDE ``parrot.outputs.a2ui`` (in ``parrot.tools.infographic_recipes``)
precisely so it may import ``DatasetManager`` (spec G8 one-way import rule).
"""
# => parrot/tools/infographic_recipes/ IS the correct home for narrator.py.
```

### Does NOT Exist

- ~~`NarrativeSpec`~~ / ~~`InfographicRecipe.narrative`~~ — this task creates them.
- ~~`parrot.tools.infographic_recipes.narrator`~~ — this task creates the module.
- ~~`Narrator` anywhere in the tree~~ — does not exist.
- ~~`parrot.outputs.a2ui.recipes.narrator`~~ — **must NOT be created there** (G8).
- ~~`InfographicRecipe.schema_version == 2`~~ — it is `1` and must stay `1`.
  Bumping it is a spec violation (criterion G-G).
- ~~`RecipeRunner(narrator=...)`~~ — the ctor param is TASK-2189, not this task.
- ~~a `prompt` or `template` field on `NarrativeSpec`~~ — storing a prompt blob
  would reopen the G1 "stored code" hole. **Only a skill name.**
- ~~`NarrativeSpec.llm` / `.model` / `.provider`~~ — the narrator uses the
  agent's configured client (resolved: default `google:gemini-3.5-flash` or
  `amazon.nova-lite-v1:0`), so the recipe must NOT pin a model.

---

## Implementation Notes

### Pattern to Follow

```python
# models.py — mirror the section_descriptor precedent exactly (additive + documented).
class NarrativeSpec(BaseModel):
    """Declarative narrative step: a REFERENCE to a skill, never code (spec G1).

    Attributes:
        skill: Registered skill name that teaches an LLM to render the facts.
        facts_key: ``data_model`` key holding the deterministic facts to render.
        output_key: ``data_model`` key the generated prose is written to.
    """

    skill: str = Field(..., description="Skill name resolvable in the skill registry.")
    facts_key: str = Field(..., description="data_model key holding the facts.")
    output_key: str = Field(default="narrative", description="data_model key for the prose.")


# narrator.py — G8-safe: stdlib typing only, no parrot imports at all.
@runtime_checkable
class Narrator(Protocol):
    """Renders deterministic facts as prose. Implementations may call an LLM.

    Implementations MUST NOT raise into the caller: return ``None`` on any
    failure so a replay degrades to facts-without-prose (spec criterion G-E).
    """

    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        """Render ``facts`` as prose using the named skill, or None on failure."""
        ...
```

### Key Constraints

- `narrative` must be `Optional` with a `None` default so every existing recipe
  and every existing test fixture keeps validating (criterion G-G).
- Add a matching entry to `InfographicRecipe`'s `Attributes:` docstring block —
  the model documents its fields there (see the `section_descriptor` entry at
  line 174).
- `narrator.py` must import **nothing** from `parrot` — keep it a pure typing
  module so it can never become a G8 violation vector.
- Document in the `Narrator` docstring that implementations return `None` rather
  than raising; TASK-2189's runner step relies on that and TASK-2192 implements it.
- Do not add validation that `skill` resolves — the registry is not reachable
  from the models layer. Resolution is checked in `dry_run` (TASK-2189).

### References in Codebase

- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py:154-196` — the
  model to extend, and the `section_descriptor` additive precedent
- `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py:11-12` — the G8 rule
- `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` (docstring)
  — why `tools/infographic_recipes/` is the correct home
- `packages/ai-parrot/tests/outputs/a2ui/recipes/test_models.py` — existing model
  test style
- `packages/ai-parrot/tests/outputs/a2ui/recipes/test_import_rule.py` — the
  existing G8 import-rule test; check whether it should also cover `narrator.py`

---

## Acceptance Criteria

- [ ] `from parrot.outputs.a2ui.recipes.models import NarrativeSpec` works
- [ ] `from parrot.outputs.a2ui.recipes import NarrativeSpec` works (exported)
- [ ] `from parrot.tools.infographic_recipes.narrator import Narrator` works
- [ ] `InfographicRecipe(...)` without `narrative` still validates (default `None`)
- [ ] `InfographicRecipe(...).schema_version == 1` — unchanged
- [ ] A recipe carrying `narrative` round-trips through `model_dump()` / `model_validate()`
- [ ] `NarrativeSpec.output_key` defaults to `"narrative"`
- [ ] `narrator.py` imports nothing from `parrot` (verified by inspection/test)
- [ ] `isinstance(stub, Narrator)` is `True` for a minimal async stub (runtime_checkable)
- [ ] `NarrativeSpec` has no `prompt`, `template`, `llm`, `model` or `provider` field
- [ ] The existing `budget-variance-daily.yaml` still loads via `InfographicRecipe.from_yaml`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/ packages/ai-parrot/tests/tools/infographic_recipes/ -v`
- [ ] No linting errors: `ruff check` on both changed/created source files

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_models.py  (append)
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, LayoutSpec, NarrativeSpec


class TestNarrativeSpecAdditive:
    def test_recipe_without_narrative_still_validates(self):
        r = InfographicRecipe(name="n", title="T", layout=LayoutSpec(component="Report"))
        assert r.narrative is None
        assert r.schema_version == 1

    def test_recipe_with_narrative_roundtrips(self):
        r = InfographicRecipe(
            name="n", title="T", layout=LayoutSpec(component="Report"),
            narrative=NarrativeSpec(skill="budget-narrative", facts_key="narrative_facts"),
        )
        again = InfographicRecipe.model_validate(r.model_dump())
        assert again.narrative.skill == "budget-narrative"
        assert again.narrative.output_key == "narrative"
        assert again.schema_version == 1

    def test_narrative_spec_stores_no_code(self):
        """G1: only a skill name — no prompt/template/model fields."""
        forbidden = {"prompt", "template", "source", "code", "llm", "model", "provider"}
        assert not (forbidden & set(NarrativeSpec.model_fields))

    def test_existing_example_recipe_still_loads(self):
        """Regression: the pre-feature YAML example must keep validating."""
        from pathlib import Path
        y = Path("examples/infographic_recipes/budget-variance-daily.yaml").read_text()
        assert InfographicRecipe.from_yaml(y).schema_version == 1


# packages/ai-parrot/tests/tools/infographic_recipes/test_narrator_protocol.py  (create)
from typing import Any, Optional

from parrot.tools.infographic_recipes.narrator import Narrator


class _Stub:
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        return "prose"


class TestNarratorProtocol:
    def test_stub_satisfies_protocol(self):
        assert isinstance(_Stub(), Narrator)

    def test_non_conforming_object_does_not(self):
        assert not isinstance(object(), Narrator)

    def test_narrator_module_imports_nothing_from_parrot(self):
        """G8 hygiene: keep this a pure typing module."""
        import inspect

        from parrot.tools.infographic_recipes import narrator

        src = inspect.getsource(narrator)
        assert "from parrot" not in src and "import parrot" not in src
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 New Public Interfaces gives the
   exact shapes; §7 Patterns to Follow covers the G8 placement rule)
2. **Check dependencies** — none; can start immediately
3. **Verify the Codebase Contract** — confirm `models.py:184` still has
   `schema_version: int = 1` and `models.py:196` still has `section_descriptor`
   before mirroring the pattern
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2188-narrativespec-and-narrator-protocol.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
