# TASK-2697: Flex dashboard recipe, LayoutSpec v2 & refresh lane

**Feature**: FEAT-491 — Flex A2UI Dashboard Agent
**Spec**: `sdd/specs/flex-agent-infographic-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2696
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 plus the `refresh_dashboard` agent-function tool from
Module 3 (grouped here because the tool replays the recipe this task
defines). The dashboard descriptor's section names must resolve 1:1 to the
TASK-2694 transformer registry names, aliases frozen per spec §2. The
refresh button = A2UIRuntime `callAgentFunction → refresh_dashboard`,
honoring per-surface filter state, exactly as the FEAT-469 example.

---

## Scope

- Add to `agents/flex_dashboard.py` (extends TASK-2696's class):
  - `@classmethod dashboard_descriptor(cls) -> SectionDescriptor` —
    sections (names = transformer names, in order): `payroll_hero`,
    `worked_hours_by_month`, `payroll_by_month`, `revenue_by_month`,
    `payroll_pct_by_month`, `pay_code_hours`, `pay_code_allocation`,
    `rep_utilization_by_region`, `proximity_staffing`, `narrative_facts`
    (LAST). Each `SectionSpec(name=…, target=/<name>, datasets=[<alias>…],
    shape="mapping")`; `narrative_facts` datasets = prior-step output keys.
  - `LayoutSpec` v2 (`component="Infographic"`): hero row of four `KPICard`s
    (Worked Hours, Payroll, P&L Revenue, Payroll % to Revenue) bound with
    `{"path": "/payroll_hero/<key>"}`; month-series chart sections; pay-code
    sections; utilization section; proximity map + coverage `DataTable`;
    narrative text binding marked optional via
    `metadata.extensions.parrot_optional`.
  - `RecipeParam` declarations for the per-section filters: `month`,
    `flex_type`, `pay_code`, `cost_center`, `radius_miles` (default 50),
    `nearest_n` (default 3).
  - `NarrativeSpec(skill="flex-narrative", facts_key="narrative_facts")`.
  - `RefreshDashboardTool(AbstractTool)` with `name = "refresh_dashboard"`:
    re-runs the recipe via `RecipeRunner.run(cls.DASHBOARD_RECIPE_NAME,
    params=…, pctx=…)`; explicit args win over
    `current_a2ui_surface_state()`; register it in the agent's tools.
- Unit tests: `test_dashboard_descriptor` following the
  `TestFinanceReporterDescriptors` suite shape (every section resolves to a
  registered transformer; narrative facts ordered after its inputs; layout
  satisfies catalog required keys; narrative binds optional; distinct recipe
  name).

**NOT in scope**: publishing/replaying against a real store or rendering
(TASK-2699 integration tests); skills content (TASK-2698).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/flex_dashboard.py` | MODIFY | descriptor classmethod + refresh tool |
| `packages/ai-parrot/tests/unit/bots/test_flex_dashboard_descriptors.py` | CREATE | descriptor validity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec, GapReport
# verified: tools/infographic_sections.py:80,42,196; agents/finance_reporter.py:45
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec, RecipeParam
# verified: recipes/models.py:109,199,51
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException
# verified: examples/agents/a2ui/deterministic_refresh_dashboard.py:102-105
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, current_a2ui_surface_state
# verified: examples/agents/a2ui/deterministic_refresh_dashboard.py:97-101
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
async def publish_recipe(self, name: str, descriptor: "SectionDescriptor | str",
    owner: Optional[str] = None, delivery: Optional[dict] = None,
    overwrite: bool = False) -> Union[InfographicRecipe, GapReport]   # line 279
# section → transformer resolution: section NAME normalized to a python
# identifier is the registry key (lines 297-341); ANY unmapped section →
# GapReport and NOTHING saved.

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:                                                   # line 204
    async def run(self, name: str, *, params: dict | None = None,
                  pctx: Any | None = None, recipe_owner: Optional[str] = None
    ) -> RenderedArtifact                                             # line 242
# WARNING from its docstring: falsy pctx → DatasetManager PBAC guards fail
# OPEN. Always thread a real PermissionContext.
```

### Pattern anchors (read BEFORE implementing)
- `agents/finance_reporter.py:258-326` — `dashboard_descriptor()` with
  LayoutSpec v2: props top-level, `{"path"}` bindings, nested Infographic
  section components keep their own `"properties"` wrapper, optional marker
  in `metadata.extensions.parrot_optional` (FEAT-470 TASK-2542 comments).
- `examples/agents/a2ui/deterministic_refresh_dashboard.py:356-435` —
  `RefreshDashboardArgs(AbstractToolArgsSchema)` + `RefreshDashboardTool
  (AbstractTool)` with `name = "refresh_dashboard"` (line 376), args-win-
  over-surface-state logic, and the `a2ui_hidden = True` opt-out example
  (line 435) for tools that must NOT appear in the A2UI catalog.
- `packages/ai-parrot/tests/unit/bots/test_finance_reporter_descriptors.py`
  — the descriptor test suite to mirror (registry resolution, ordering,
  catalog required keys, optional binds).

### Does NOT Exist
- ~~tier-1 `generate_infographic` / data-splice template path on this
  agent~~ — FEAT-420 removed it; `publish_recipe` (tier 2) only.
- ~~an inline `"optional": true` sibling key in LayoutSpec bindings~~ —
  v2 moved it to the layout's `metadata.extensions.parrot_optional` list
  (finance_reporter.py:239-242 comment).
- ~~`RecipeRunner.run(recipe=...)` kwarg~~ — the first positional is `name`;
  owner scope is `recipe_owner=`.
- ~~a `HeroCard` component name~~ — the verified catalog component used by
  the precedent is `KPICard` (finance_reporter.py:283-301); verify any other
  component name against the catalog before use.

---

## Implementation Notes

### Key Constraints
- Section order in `sections=[…]` is preserved into TransformStep order —
  `narrative_facts` LAST (it consumes the other steps' outputs).
- `publish_recipe` forces `TransformStep.inputs` == section's declared
  dataset alias — datasets lists must use the frozen aliases verbatim.
- Determinism: descriptor must be a pure classmethod (no I/O), so tests can
  validate it without a store.
- Per-section filters: only wire a param into sections whose transformer
  declares it (per-section rule, proposal U1).
- A2UI v1 dialect is hot — re-verify LayoutSpec field names against
  `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py:109-199`
  at implementation time.

---

## Acceptance Criteria

- [ ] Every descriptor section resolves to a registered transformer
      (publishing would yield an `InfographicRecipe`, not a `GapReport`).
- [ ] Hero row binds the four KPIs from `/payroll_hero/*` paths.
- [ ] `narrative_facts` is last and its datasets are prior-step output keys.
- [ ] Narrative binding is optional (recipe replays with no narrator).
- [ ] `refresh_dashboard` tool exists, args win over surface state, and
      passes a real pctx through to `RecipeRunner.run`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard_descriptors.py -v`
- [ ] `ruff check agents/flex_dashboard.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_flex_dashboard_descriptors.py
# Mirror TestFinanceReporterDescriptors (same file-path import technique).

def test_every_section_resolves_to_a_transformer(descriptor):
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry
    for section in descriptor.sections:
        assert transformer_registry.get(normalize(section.name))

def test_narrative_facts_last_and_inputs_are_output_keys(descriptor): ...
def test_hero_bindings(descriptor): ...
def test_refresh_tool_args_win_over_surface_state(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2696 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/flex-agent-infographic-a2ui.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-01
**Notes**: Added `dashboard_descriptor()`, `_transform_sections()`,
`_narrative_spec()`, `recipe_params()`, `build_refresh_tool()`, plus
module-level `RefreshDashboardArgs`/`RefreshDashboardTool` to
`agents/flex_dashboard.py`. 14 new descriptor/refresh-tool tests pass (58
total across the feature's test files); `ruff check` is clean.

Two things discovered while implementing, both documented in-line as code
comments:

1. **Narrative section name is `flex_narrative_facts`**, not
   `narrative_facts` (TASK-2694's deviation) — the section's `name` MUST
   equal the transformer registry key `publish_recipe` resolves against,
   so this task's `_transform_sections()`/`NarrativeSpec(facts_key=...)`
   use `flex_narrative_facts` throughout, not the generic name this task's
   Scope text used.
2. **`resolve_params()` (`parrot.outputs.a2ui.recipes.params`) raises when
   a declared `RecipeParam` has no default AND no run-time override** —
   there is no built-in "optional filter" concept at the recipe-params
   layer. To keep the per-section filters (`month`, `flex_type`, `pay_code`,
   `cost_center`, `category`) truly optional (unfiltered default replay),
   `recipe_params()` declares `default=""` for each, and
   `agents/flex_dashboard/transformers.py`'s `_apply_filters` helper
   (TASK-2694) was changed from an `is not None` check to a truthy check
   (`if value:`) so `""` is ALSO treated as "no filter" — a one-line,
   additive, backward-compatible change (all TASK-2694 tests still pass
   unchanged; no filter value used anywhere is legitimately falsy other
   than the new empty-string sentinel).

**Deviations from spec**: `flex_narrative_facts` section/facts_key name
(see #1 above, same root cause as TASK-2694's already-recorded deviation);
`agents/flex_dashboard/transformers.py::_apply_filters` truthy-check change
(see #2 above) — required for the recipe to be replayable with no filter
overrides at all, which the spec's own "narrative step stays optional so
replay works with no narrator" principle implies should also hold for the
per-section filters.
