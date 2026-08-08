# TASK-2193: `SectionDescriptor.layout` + `publish_recipe` generalisation

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2188
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec. This is the change that makes criterion
**G-A** reachable at all.

`publish_recipe` currently hardcodes its layout
(`infographic_authoring.py:379-382`):

```python
layout=LayoutSpec(component="Infographic", properties={"template": descriptor.template}),
```

That shape can only ever produce a *template-based* Infographic. It cannot emit a
component tree with `$bind` pointers — which is exactly what the A2UI path
(`examples/infographic_recipes/budget-variance-daily.yaml`) needs, and what
FEAT-420 migrates `FinanceReporter` onto.

This task adds an optional `layout` field to `SectionDescriptor` and teaches
`publish_recipe` to honour it. Absent → today's behaviour, unchanged, so no
existing descriptor is affected (criterion G-G). It also carries a descriptor's
declared `narrative` through into the saved recipe.

---

## Scope

- Add `layout: Optional[LayoutSpec] = None` to `SectionDescriptor`
  (`infographic_sections.py`). **Must be a declared field** — the model is
  `extra="forbid"`, so a passed-through key would be rejected.
- Add `narrative: Optional[NarrativeSpec] = None` to `SectionDescriptor` so an
  author can declare the narrative step alongside the layout.
- Change `publish_recipe` (`infographic_authoring.py:280-392`) to:
  - use `descriptor.layout` verbatim when present
  - otherwise build today's `LayoutSpec(component="Infographic",
    properties={"template": descriptor.template})` exactly as now
  - pass `narrative=descriptor.narrative` into the saved `InfographicRecipe`
- Resolve the import direction carefully: `infographic_sections.py` must import
  `LayoutSpec`/`NarrativeSpec` from `parrot.outputs.a2ui.recipes.models`, which
  already imports `SectionDescriptor` from `infographic_sections` — **this is a
  circular import risk that must be handled** (see Implementation Notes).
- Write unit tests for both branches plus the narrative carry-through.

**NOT in scope**:
- The `NarrativeSpec` model itself (TASK-2188).
- The section→transformer name resolution or the `GapReport` behaviour — the
  gap-report path stays exactly as it is; this task does not change how coverage
  is computed (`infographic_authoring.py:335-363`).
- `_build_section_payload` / `_assemble_section` — tier-1 payload building is
  untouched.
- `FinanceReporter`'s descriptors (TASK-2194).
- Any change to `mode` — the A2UI path is expressed via `layout`, **not** a new
  `mode` value.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_sections.py` | MODIFY | Add `layout` + `narrative` fields to `SectionDescriptor` |
| `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` | MODIFY | `publish_recipe` honours `descriptor.layout` and carries `narrative` |
| `packages/ai-parrot/tests/unit/tools/test_infographic_sections.py` | MODIFY | Descriptor field tests |
| `packages/ai-parrot/tests/unit/bots/test_publish_recipe.py` | MODIFY | Layout + narrative carry-through tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in infographic_authoring.py (lines 32-48) — do not re-add:
from parrot.tools.infographic_sections import (
    GapReport, ProvenanceDescriptor, SectionDescriptor, SectionSpec,
    TransformerGap, validate_descriptor_datasets,
)                                                            # lines 32-39
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec, InfographicRecipe, LayoutSpec, RenderSpec, TransformStep,
)                                                            # lines 40-46
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError   # line 47
from parrot.outputs.a2ui.recipes.transformers import transformer_registry  # line 48
# NarrativeSpec must be ADDED to the line 40-46 import block.

# For tests:
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/infographic_sections.py
class SectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str; target: str
    datasets: List[str] = Field(default_factory=list)
    columns: Dict[str, List[str]] = Field(default_factory=dict)
    shape: Literal["records", "scalar", "mapping", "table"]
    hint: Optional[str] = None

class SectionDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")     # <-- new fields MUST be declared
    template: str
    mode: Literal["jinja", "data-splice"]         # <-- DO NOT add a value here
    splice_marker_id: str = "report-data"
    sections: List[SectionSpec] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    # ADD: layout: Optional[LayoutSpec] = None
    # ADD: narrative: Optional[NarrativeSpec] = None
```

```python
# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
async def publish_recipe(self, name, descriptor, owner=None, delivery=None,
                         overwrite=False) -> Union[InfographicRecipe, GapReport]:  # line 280
    descriptor = self._coerce_descriptor(descriptor)                # line 318
    store = self._require_recipe_store()                            # line 319
    if not overwrite:                                               # line 321
        try:
            await store.get(name, owner)                            # line 323
        except RecipeNotFoundError:
            pass
        else:
            raise ValueError(...)                                   # lines 327-330
    transforms: List[TransformStep] = []                            # line 332
    gaps: List[TransformerGap] = []                                 # line 333
    covered: List[str] = []                                         # line 334
    for section in descriptor.sections:                             # line 335
        tname = self._transformer_name(section)                     # line 336
        try:
            transformer_registry.get(tname)                         # line 338
        except KeyError:
            gaps.append(TransformerGap(...))                        # lines 340-346
            continue                                                # line 347
        transforms.append(TransformStep(                            # lines 348-355
            transformer=tname, inputs=list(section.datasets),
            params=dict(descriptor.params),
            output_key=section.target.lstrip("/"),
        ))
        covered.append(section.name)                                # line 356
    if gaps:                                                        # line 358
        self.logger.info(...)                                       # lines 359-362
        return GapReport(gaps=gaps, covered=covered)                # line 363
    # --- full coverage path ---
    aliases: List[str] = []                                         # line 366
    for section in descriptor.sections:                             # line 367
        for alias in section.datasets:
            if alias not in aliases:
                aliases.append(alias)
    data_sources = [DataSourceSpec(dataset=a, alias=a) for a in aliases]   # line 371
    recipe = InfographicRecipe(                                     # line 373
        name=name, title=name, owner=owner,
        data_sources=data_sources,
        transforms=transforms,
        layout=LayoutSpec(                                          # lines 379-382  <-- CHANGE HERE
            component="Infographic",
            properties={"template": descriptor.template},
        ),
        render=RenderSpec(delivery=delivery),                       # line 383
        section_descriptor=descriptor,                               # line 384
        updated_at=datetime.now(timezone.utc),                      # line 385
    )
    await store.save(recipe)                                        # line 387
    return recipe                                                   # line 392

@staticmethod
def _transformer_name(section: SectionSpec) -> str:                  # line 394
    return re.sub(r"\W+", "_", section.name).strip("_")              # line 397
@staticmethod
def _coerce_descriptor(descriptor) -> SectionDescriptor: ...          # line 421
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class LayoutSpec(BaseModel):        # line 98
    component: str
    properties: dict[str, Any] = Field(default_factory=dict)   # line 110
class NarrativeSpec(BaseModel):     # added by TASK-2188
    skill: str; facts_key: str; output_key: str = "narrative"
class InfographicRecipe(BaseModel): # line 154
    schema_version: int = 1                                    # line 184
    narrative: Optional[NarrativeSpec] = None                  # added by TASK-2188
    section_descriptor: Optional[SectionDescriptor] = None     # line 196
    # ^^^ models.py ALREADY imports SectionDescriptor from infographic_sections.
    #     => adding a LayoutSpec import to infographic_sections creates a CYCLE.
```

### Does NOT Exist

- ~~`SectionDescriptor.layout`~~ / ~~`SectionDescriptor.narrative`~~ — this task adds them.
- ~~`InfographicAuthoringMixin._build_layout_spec`~~ — no such hook. The layout is
  inline at lines 379-382. The spec chose the **descriptor field** approach, not
  a hook; do not add a hook.
- ~~`SectionDescriptor.mode == "a2ui"` / `"component"`~~ — `mode` stays
  `Literal["jinja", "data-splice"]`. Adding a value is explicitly out of scope
  and listed in the spec's "Does NOT Exist".
- ~~a `layout` field on `SectionSpec`~~ — the layout is descriptor-level, not
  per-section.
- ~~`LayoutSpec` importable from `parrot.tools.infographic_sections`~~ — it lives
  in `parrot.outputs.a2ui.recipes.models`.
- ~~`transformer_registry.get("days")`~~ — still no `days` transformer; this task
  does not add one and `FinanceReporter`'s coverage is fixed in TASK-2194 by
  changing its **section names** to registered transformer names, not by
  registering `days`.
- ~~`extra="allow"` on `SectionDescriptor`~~ — it is `extra="forbid"`. Do not
  loosen it to sneak fields in.

---

## Implementation Notes

### Circular import — resolve this first

`parrot/outputs/a2ui/recipes/models.py` already imports `SectionDescriptor` from
`parrot/tools/infographic_sections.py` (for the `section_descriptor` field).
Importing `LayoutSpec`/`NarrativeSpec` the other way creates a cycle.

Verify the actual current import direction, then pick the least invasive fix:

- **Preferred**: use a `TYPE_CHECKING` import plus a string forward reference in
  the annotation, and call `SectionDescriptor.model_rebuild()` where the concrete
  types are available. Confirm Pydantic v2 resolves it at validation time.
- **Alternative**: type the fields structurally (e.g. `Optional[Dict[str, Any]]`
  validated into a `LayoutSpec` at the `publish_recipe` boundary). Simpler
  import-wise, weaker typing — only if the forward reference genuinely fails.
- **Do NOT** move `LayoutSpec` into `infographic_sections.py` or duplicate it.
  One definition, in the recipes models module.

Record which approach you used, and why, in the Completion Note.

### Pattern to Follow

```python
# infographic_authoring.py — the minimal, behaviour-preserving change:
layout = descriptor.layout or LayoutSpec(
    component="Infographic",
    properties={"template": descriptor.template},
)
recipe = InfographicRecipe(
    name=name, title=name, owner=owner,
    data_sources=data_sources,
    transforms=transforms,
    layout=layout,                          # was the inline hardcoded LayoutSpec
    render=RenderSpec(delivery=delivery),
    section_descriptor=descriptor,
    narrative=descriptor.narrative,         # NEW: carry the declared narrative
    updated_at=datetime.now(timezone.utc),
)
```

### Key Constraints

- **Behaviour-preserving default.** A descriptor without `layout` must produce a
  byte-identical `LayoutSpec` to today's. There are existing tests
  (`test_publish_recipe.py`) that depend on it — they must pass unchanged.
- Both new fields `Optional` with `None` defaults, so every existing descriptor
  keeps validating (criterion G-G).
- Do not touch the gap-report logic. A descriptor whose sections do not resolve
  to registered transformers must still return a `GapReport` and save nothing,
  even if it declares a `layout`.
- `descriptor.layout` is used **verbatim** — no merging, no injecting the
  template name into its properties.
- Update `SectionDescriptor`'s docstring `Attributes:` block for both new fields.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py:365-392` —
  the full-coverage path to change
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py:98-110,196` —
  `LayoutSpec` and the existing reverse import
- `examples/infographic_recipes/budget-variance-daily.yaml:104-153` — the
  component-tree layout shape this unlocks
- `packages/ai-parrot/tests/unit/bots/test_publish_recipe.py` — existing tests
  that must keep passing

---

## Acceptance Criteria

- [ ] `SectionDescriptor(layout=LayoutSpec(...))` validates
- [ ] `SectionDescriptor(narrative=NarrativeSpec(...))` validates
- [ ] A descriptor **without** `layout` still validates (default `None`)
- [ ] `publish_recipe` with `descriptor.layout` set → saved recipe carries it verbatim
- [ ] `publish_recipe` without `layout` → produces today's template-based `LayoutSpec`, unchanged
- [ ] `publish_recipe` carries `descriptor.narrative` into the saved recipe
- [ ] A descriptor with unmapped sections still returns a `GapReport` and saves nothing, even with `layout` set
- [ ] No circular-import error: `import parrot.tools.infographic_sections` and `import parrot.outputs.a2ui.recipes.models` both work in either order
- [ ] `SectionDescriptor.model_config` is still `extra="forbid"`
- [ ] `SectionDescriptor.mode` is still `Literal["jinja", "data-splice"]`
- [ ] `InfographicRecipe.schema_version == 1`
- [ ] Existing `test_publish_recipe.py` tests pass **unmodified**
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_publish_recipe.py packages/ai-parrot/tests/unit/tools/test_infographic_sections.py -v`
- [ ] No linting errors: `ruff check` on both changed source files
- [ ] `mypy` clean on both changed files

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_publish_recipe.py  (append)
import pytest

from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec

# NOTE: this module already registers feat326_totals / feat326_breakdown
# transformers (lines 28-35) — reuse them so sections resolve to full coverage.

REPORT_LAYOUT = LayoutSpec(
    component="Report",
    properties={
        "title": "Budget Variance",
        "summary": {"$bind": "/narrative/headline", "optional": True},
        "sections": [{"heading": "Snapshot", "components": []}],
    },
)


class TestPublishRecipeLayout:
    async def test_descriptor_layout_used_verbatim(self, agent_with_store):
        descriptor = SectionDescriptor(
            template="t.html", mode="data-splice",
            sections=[SectionSpec(name="feat326_totals", target="/totals",
                                  datasets=["ds"], shape="mapping")],
            layout=REPORT_LAYOUT,
        )
        recipe = await agent_with_store.publish_recipe("r-layout", descriptor)
        assert recipe.layout == REPORT_LAYOUT

    async def test_absent_layout_preserves_legacy_shape(self, agent_with_store):
        """Regression: identical to pre-feature behaviour."""
        descriptor = SectionDescriptor(
            template="t.html", mode="data-splice",
            sections=[SectionSpec(name="feat326_totals", target="/totals",
                                  datasets=["ds"], shape="mapping")],
        )
        recipe = await agent_with_store.publish_recipe("r-legacy", descriptor)
        assert recipe.layout.component == "Infographic"
        assert recipe.layout.properties == {"template": "t.html"}

    async def test_narrative_carried_through(self, agent_with_store):
        descriptor = SectionDescriptor(
            template="t.html", mode="data-splice",
            sections=[SectionSpec(name="feat326_totals", target="/totals",
                                  datasets=["ds"], shape="mapping")],
            layout=REPORT_LAYOUT,
            narrative=NarrativeSpec(skill="budget-narrative", facts_key="narrative_facts"),
        )
        recipe = await agent_with_store.publish_recipe("r-narr", descriptor)
        assert recipe.narrative.skill == "budget-narrative"

    async def test_gap_report_still_wins_over_layout(self, agent_with_store):
        """An unmapped section must still block the save, layout notwithstanding."""
        descriptor = SectionDescriptor(
            template="t.html", mode="data-splice",
            sections=[SectionSpec(name="not_registered_anywhere", target="/x",
                                  datasets=["ds"], shape="mapping")],
            layout=REPORT_LAYOUT,
        )
        result = await agent_with_store.publish_recipe("r-gap", descriptor)
        assert result.__class__.__name__ == "GapReport"


# packages/ai-parrot/tests/unit/tools/test_infographic_sections.py  (append)
class TestSectionDescriptorLayoutField:
    def test_layout_optional(self):
        d = SectionDescriptor(template="t.html", mode="jinja")
        assert d.layout is None and d.narrative is None

    def test_extra_still_forbidden(self):
        with pytest.raises(Exception):
            SectionDescriptor(template="t.html", mode="jinja", bogus=1)

    def test_mode_literal_unchanged(self):
        with pytest.raises(Exception):
            SectionDescriptor(template="t.html", mode="a2ui")

    def test_no_circular_import(self):
        """Both modules must import cleanly in either order."""
        import importlib
        for order in (["parrot.tools.infographic_sections",
                       "parrot.outputs.a2ui.recipes.models"],
                      ["parrot.outputs.a2ui.recipes.models",
                       "parrot.tools.infographic_sections"]):
            for mod in order:
                importlib.import_module(mod)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 7, and §6 for why
   `extra="forbid"` forces a declared field)
2. **Check dependencies** — TASK-2188 must be in `sdd/tasks/completed/` so
   `NarrativeSpec` exists
3. **Resolve the circular import FIRST** — before writing the fields, confirm the
   current import direction in `models.py` and choose the forward-reference or
   structural approach. Prove it with the `test_no_circular_import` test.
4. **Verify the Codebase Contract** — re-read
   `infographic_authoring.py:365-392` and confirm lines 379-382 still hold the
   hardcoded `LayoutSpec`
5. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met — especially that existing
   `test_publish_recipe.py` tests pass **unmodified**
8. **Move this file** to `sdd/tasks/completed/TASK-2193-descriptor-layout-publish-recipe.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-07
**Notes**: Added `layout: Optional[LayoutSpec] = None` and
`narrative: Optional[NarrativeSpec] = None` to `SectionDescriptor`
(`infographic_sections.py`, `extra="forbid"` so both had to be declared
fields). Changed `publish_recipe` to `layout = descriptor.layout or
LayoutSpec(component="Infographic", properties={"template": descriptor.template})`
and pass `narrative=descriptor.narrative` into the saved `InfographicRecipe` —
the gap-report path (returned BEFORE the layout/recipe construction) is
completely untouched, so an unmapped section still blocks the save
regardless of `layout`. 30 tests pass across both test files (9 new:
5 `TestPublishRecipeLayout` + 4 `TestSectionDescriptorLayoutField`,
including a dedicated circular-import round-trip test in both directions).
Broader regression check (`tests/outputs/a2ui/`,
`tests/tools/infographic_recipes/`, both modified test files): 301 passed,
4 skipped (pre-existing, unrelated). `ruff check` adds only 2 `UP045`
findings for the 2 new `Optional[...]` fields (same established style as
every other field in this file); `mypy` shows the same 4 pre-existing
unrelated errors, unchanged.

**Circular-import approach used**: forward reference + `model_rebuild()`.
`infographic_sections.py` gained a `TYPE_CHECKING`-only import of
`LayoutSpec`/`NarrativeSpec` from `parrot.outputs.a2ui.recipes.models` (the
module already has `from __future__ import annotations`, so the field
annotations are deferred strings at runtime). `recipes/models.py` calls
`SectionDescriptor.model_rebuild()` once, right after `RecipeRunError`
(i.e. after every class `models.py` defines, including `LayoutSpec` and
`NarrativeSpec`, is in that module's globals) — `model_rebuild()`'s default
namespace resolution walks the caller's frame, which at that call site is
`models.py` itself, so both forward refs resolve. Verified both import
orders work cleanly (`test_no_circular_import`) and that validation/defaults
behave correctly in both directions via a standalone repro before writing
any tests.

**Deviations from spec**: none. One test-fixture-naming note: the task's own
Test Specification assumed a fixture named `agent_with_store`, but the
actual existing fixture in `test_publish_recipe.py` is named `agent` — used
the real fixture name (it already wires a `FileRecipeStore`).
