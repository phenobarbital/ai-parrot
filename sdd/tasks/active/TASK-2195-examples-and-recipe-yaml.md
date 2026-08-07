# TASK-2195: Update examples + recipe YAML for the narrative path

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2194
**Assigned-to**: unassigned

---

## Context

Implements **Module 8, part 2**. The examples are the executable documentation of
this feature — `examples/budget_variance_infographic.py` currently drives the
data-splice path that TASK-2194 deleted, so it is broken until updated, and
`examples/infographic_recipes/budget-variance-daily.yaml` is the canonical
FEAT-324 recipe that should now demonstrate the narrative step and optional binds.

This task makes the two profiles runnable end-to-end by a human, including the
narrator-vs-no-narrator contrast that is the feature's core safety property.

---

## Scope

- Rewrite `examples/budget_variance_infographic.py` to:
  - use `FinanceReporter.report_descriptor()` / `dashboard_descriptor()`
  - demonstrate **tier 2**: `publish_recipe(...)` returning a saved
    `InfographicRecipe` (the point of criterion G-A), asserting it is not a
    `GapReport`
  - demonstrate a replay **with** an injected narrator and **without** one, so the
    degrade-to-facts behaviour is visible side by side
- Update `examples/infographic_recipes/budget-variance-daily.yaml`:
  - add the `narrative_facts` transform step after its three inputs
  - add the `narrative:` block (skill / facts_key / output_key)
  - add narrative binds carrying `optional: true`
  - set `snapshot_col` explicitly on every step's params
  - keep the existing annotated-comment style, and update the comments that
    describe the transform chain
- Verify the YAML still loads via `InfographicRecipe.from_yaml`
  (`models.py:209`) and that `dry_run` reports no errors.
- Update `examples/seed_finance_projection.py` **only** if TASK-2194's design
  decision requires a schema/column change (it should not).

**NOT in scope**:
- Integration/e2e tests (TASK-2196) and docs prose (TASK-2197).
- Any change to `agents/finance_reporter.py` (TASK-2194) or to the library,
  runner, mixin, or descriptor code.
- Wiring real email delivery — `delivery` stays `null` (resolved: per-deployment).
- Adding a second example file; extend the existing one.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/budget_variance_infographic.py` | MODIFY | Drive the A2UI profiles; show tier 2 + narrator/no-narrator contrast |
| `examples/infographic_recipes/budget-variance-daily.yaml` | MODIFY | Add `narrative_facts` step, `narrative:` block, optional binds, explicit `snapshot_col` |
| `examples/seed_finance_projection.py` | MODIFY (conditional) | Only if TASK-2194 requires a column change |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, NarrativeSpec
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.auth.system_account import run_scheduled_refresh   # optional, for the scheduled demo
from agents.finance_reporter import FinanceReporter
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class InfographicRecipe(BaseModel):
    schema_version: int = 1                                # line 184
    narrative: Optional[NarrativeSpec] = None              # TASK-2188
    def to_yaml(self) -> str: ...                          # line 198
    @classmethod
    def from_yaml(cls, text: str) -> "InfographicRecipe": ...   # line 209
class NarrativeSpec(BaseModel):                            # TASK-2188
    skill: str; facts_key: str; output_key: str = "narrative"

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:
    def __init__(self, store, dataset_manager, *, artifact_store=None,
                 owner=None, narrator=None) -> None: ...    # narrator added by TASK-2189
    async def run(self, name: str, *, params=None, pctx=None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...  # line 208
    async def dry_run(self, recipe: InfographicRecipe) -> list[RecipeRunError]: ...  # line 256

# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
async def publish_recipe(self, name, descriptor, owner=None, delivery=None,
                         overwrite=False) -> Union[InfographicRecipe, GapReport]: ...  # line 280
```

```python
# agents/finance_reporter.py — AFTER TASK-2194 (read its Completion Note for the
# resolved design point; these are the names the task specifies):
class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    narrative_skill = "budget-narrative"
    REPORT_RECIPE_NAME = "budget-variance-report"
    DASHBOARD_RECIPE_NAME = "budget-variance-dashboard"
    @classmethod
    def report_descriptor(cls) -> SectionDescriptor: ...
    @classmethod
    def dashboard_descriptor(cls) -> SectionDescriptor: ...
    async def register_datasets(self) -> None: ...      # line 73 — unchanged
```

```yaml
# examples/infographic_recipes/budget-variance-daily.yaml — CURRENT verified structure
schema_version: 1                        # line 17
name: budget-variance-daily              # line 18
title: "Daily Budget Variance"           # line 19
params:                                  # lines 33-36
  - {name: month, default: current_month, description: "..."}
data_sources:                            # lines 43-49
  - {dataset: in_month_projections, alias: snapshots, force_refresh: true}
  - {dataset: in_month_projections, alias: df, force_refresh: true}
transforms:                              # lines 53-102
  - {transformer: day_totals,         inputs: [snapshots], params: {snapshot_col: snapshot}, output_key: day_totals}
  - {transformer: division_breakdown, inputs: [snapshots], params: {snapshot_col: snapshot}, output_key: division_breakdown}
  - {transformer: variance_analysis,  inputs: [snapshots], params: {snapshot_col: snapshot}, output_key: variance_analysis}
  - {transformer: top_movers,         inputs: [snapshots], params: {snapshot_col: snapshot, n: 5}, output_key: top_movers}
  - {transformer: groupby_aggregate,  inputs: [df],        params: {by: [snapshot], aggs: {...}}, output_key: chart_data}
layout:                                  # lines 105-153  (Infographic + KPICard/Chart/DataTable)
render: {profile: interactive-html, theme: null, delivery: null}   # lines 158-161
# schedule: commented out                # lines 168-171
updated_at: "2026-07-22T00:00:00+00:00"  # line 175
```

```python
# The optional-bind shape (TASK-2187), in YAML:
#   summary: {$bind: "/narrative/headline", optional: true}
```

### Does NOT Exist

- ~~`FinanceReporter.budget_variance_descriptor()`~~ — removed by TASK-2194. The
  current example calls `generate_infographic(FinanceReporter.TEMPLATE_NAME,
  FinanceReporter.budget_variance_descriptor(), ...)` at
  `examples/budget_variance_infographic.py:77` — that call **must go**.
- ~~a `days` transformer to reference in the YAML~~ — never registered.
- ~~`narrative` as a `transforms` entry~~ — it is a **top-level** recipe field
  (`InfographicRecipe.narrative`), a sibling of `transforms`, not a transform step.
- ~~`NarrativeSpec.llm` / `.model` in the YAML~~ — no such field; the model comes
  from the agent.
- ~~`delivery` populated with real recipients~~ — stays `null`.
- ~~`RecipeRunner(narrator=...)` before TASK-2189~~ — verify the dependency landed.
- ~~`snapshot_col: snapshot` being correct for `troc.finance_projection`~~ — the
  table exposes `snapshot_date` (`finance_reporter.py:44`). The YAML's current
  `snapshot` value is correct **for its own in-memory example dataset**
  (`in_month_projections`, per the file's comment at lines 28-32) — decide
  deliberately whether to keep the example dataset or point it at the real table,
  and be consistent. Do not blindly change one and not the other.

---

## Implementation Notes

### Pattern to Follow

```python
# examples/budget_variance_infographic.py — show the contrast explicitly.
async def main() -> None:
    agent = FinanceReporter(name="finance-reporter", artifact_store=store,
                            recipe_store=recipe_store)
    await agent.configure()

    # --- Tier 2: publishing now SUCCEEDS (criterion G-A) -------------------
    recipe = await agent.publish_recipe(
        FinanceReporter.REPORT_RECIPE_NAME, FinanceReporter.report_descriptor(),
    )
    assert not isinstance(recipe, GapReport), "publish_recipe returned a GapReport"
    print(f"published {recipe.name} with {len(recipe.transforms)} transform(s)")

    # --- Replay WITHOUT a narrator: facts, no prose (criterion G-E) --------
    plain = RecipeRunner(recipe_store, agent._dataset_manager)
    artifact_plain = await plain.run(recipe.name, pctx=pctx)

    # --- Replay WITH a narrator: same numbers, plus prose ------------------
    narrated = RecipeRunner(recipe_store, agent._dataset_manager, narrator=agent)
    artifact_narrated = await narrated.run(recipe.name, pctx=pctx)

    print("no narrator :", len(artifact_plain.content))
    print("narrated    :", len(artifact_narrated.content))
```

### Key Constraints

- **Examples must actually run.** This is not a doc snippet — if it cannot be
  executed against a seeded `troc.finance_projection`, the task is not done.
  Note the project memory: data-querying scripts need `ENV=prod`.
- Always pass a real `pctx` to `RecipeRunner.run()`. A falsy `pctx` makes
  `DatasetManager`'s PBAC guards **fail open** (`runner.py:221-228`) — the example
  must model the correct practice, not the convenient one.
- Preserve the YAML's heavily-annotated comment style; it is referenced by
  `docs/outputs/infographic-recipes.md` as the line-by-line guide. Update the
  comments you invalidate.
- `narrative_facts` must appear **after** `variance_analysis`, `top_movers` and
  `division_breakdown` in `transforms` — order is execution order.
- Keep `schema_version: 1`.
- If you point the YAML at `troc.finance_projection`, every step's `snapshot_col`
  becomes `snapshot_date`. Be consistent across all five steps or
  `variance_analysis` raises (`library.py:215-216`).

### References in Codebase

- `examples/budget_variance_infographic.py` — the file to rewrite (currently
  calls `generate_infographic` at line 77)
- `examples/infographic_recipes/budget-variance-daily.yaml` — the recipe to extend
- `examples/seed_finance_projection.py` — the table seeder
- `packages/ai-parrot/tests/integration/infographic_recipes/test_e2e.py` — the
  load → dry_run → run walkthrough this example should mirror

---

## Acceptance Criteria

- [ ] `examples/budget_variance_infographic.py` no longer references
      `budget_variance_descriptor` or `TEMPLATE_NAME`-based data-splice rendering
- [ ] The example publishes a recipe and asserts it is **not** a `GapReport`
- [ ] The example runs the same recipe with and without a narrator and prints both
- [ ] The example passes a real `pctx` to `run()`
- [ ] `budget-variance-daily.yaml` contains a `narrative_facts` transform step
- [ ] `narrative_facts` is ordered after `variance_analysis`, `top_movers`, `division_breakdown`
- [ ] The YAML has a top-level `narrative:` block with `skill`, `facts_key`, `output_key`
- [ ] At least one layout bind carries `optional: true`
- [ ] Every transform step sets `snapshot_col` explicitly and consistently
- [ ] `InfographicRecipe.from_yaml(<file>)` loads with `schema_version == 1`
- [ ] `RecipeRunner.dry_run(<loaded recipe>)` returns an empty error list
- [ ] The YAML's annotated comments describing the transform chain are updated
- [ ] `delivery` is still `null`
- [ ] `ruff check examples/budget_variance_infographic.py` clean
- [ ] The example executes successfully against a seeded table (record the command used)

---

## Test Specification

```python
# Verification is primarily by execution, plus a lightweight YAML contract test.
# Add to: packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py or a new
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_example_recipe_yaml.py

from pathlib import Path

from parrot.outputs.a2ui.recipes.models import InfographicRecipe

YAML = Path("examples/infographic_recipes/budget-variance-daily.yaml")


class TestExampleRecipeYaml:
    def test_loads_at_schema_v1(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        assert recipe.schema_version == 1

    def test_declares_narrative(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        assert recipe.narrative is not None
        assert recipe.narrative.skill == "budget-narrative"

    def test_narrative_facts_ordered_after_inputs(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        names = [t.transformer for t in recipe.transforms]
        i = names.index("narrative_facts")
        for dep in ("variance_analysis", "top_movers", "division_breakdown"):
            assert names.index(dep) < i

    def test_snapshot_col_set_on_every_finance_step(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())
        finance = {"day_totals", "division_breakdown", "variance_analysis", "top_movers"}
        cols = {t.params.get("snapshot_col") for t in recipe.transforms
                if t.transformer in finance}
        assert len(cols) == 1 and None not in cols, f"inconsistent snapshot_col: {cols}"

    def test_has_an_optional_narrative_bind(self):
        recipe = InfographicRecipe.from_yaml(YAML.read_text())

        found = []

        def walk(v):
            if isinstance(v, dict):
                if "$bind" in v and "/narrative" in str(v["$bind"]):
                    found.append(v.get("optional"))
                for i in v.values():
                    walk(i)
            elif isinstance(v, list):
                for i in v:
                    walk(i)

        walk(recipe.layout.properties)
        assert found and all(f is True for f in found)

    def test_delivery_still_null(self):
        assert InfographicRecipe.from_yaml(YAML.read_text()).render.delivery is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§1 Non-Goals on delivery, §7 on the
   `snapshot_col` trap)
2. **Check dependencies** — TASK-2194 must be in `sdd/tasks/completed/`, and
   **read its Completion Note**: the resolved design point determines how the
   descriptors declare inputs and what the example can call
3. **Verify the Codebase Contract** — confirm the descriptor classmethod names and
   recipe-name constants TASK-2194 actually shipped
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Actually run the example** (`ENV=prod` for data access per project
   convention) — an example that only type-checks is not done
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2195-examples-and-recipe-yaml.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Example execution evidence** (required): the exact command run and its outcome.
**Dataset decision**: kept the in-memory `in_month_projections` example dataset |
pointed the YAML at `troc.finance_projection` (and the `snapshot_col` value used).

**Deviations from spec**: none | describe if any
