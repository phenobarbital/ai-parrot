# TASK-2194: `FinanceReporter` migration to A2UI layouts (Report + Infographic)

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2186, TASK-2189, TASK-2192, TASK-2193
**Assigned-to**: unassigned

---

## Context

Implements **Module 8, part 1** — the task where the whole feature becomes real,
and the only one that changes user-visible agent behaviour.

`FinanceReporter` today is tier-1-only and hand-rolls its aggregation. This task
**replaces** its data-splice descriptor and its `_build_section_payload` override
with two A2UI descriptors built on the registered transformers:

- a **`Report`** profile — narrative-first, the executive-summary deliverable
- an **`Infographic`** profile — visual-first, the dashboard

This satisfies criteria **G-A** (publish succeeds), **G-B** (no hand-rolled
aggregation) and, together with the earlier tasks, **G-C**/**G-D**.

The "replace" decision was made deliberately (brainstorm + spec §1 Non-Goals):
FEAT-326's e2e example and tests assert the data-splice path for this agent and
**will fail by design**. Rewriting them is TASK-2196, not a regression to route
around. The data-splice *render mode* itself (TASK-1883) stays available for
other callers.

---

## Scope

- Compose `NarrativeMixin` onto `FinanceReporter` (before the other mixins, per
  cooperative-MRO discipline).
- **Remove** `budget_variance_descriptor()` (`finance_reporter.py:108-129`) and
  the `_build_section_payload` override (`finance_reporter.py:131-185`).
- Add `report_descriptor()` and `dashboard_descriptor()` classmethods, each
  declaring:
  - sections whose **names are registered transformer names** (see the critical
    note below — this is how coverage is achieved)
  - a `layout` (`LayoutSpec`) with `$bind` pointers into the transform outputs
  - `optional: True` on every narrative bind
  - a `narrative` (`NarrativeSpec`) naming `budget-narrative`
- Put `snapshot_col: "snapshot_date"` in `descriptor.params` so it reaches
  **every** generated `TransformStep` (resolved question: explicit params).
- Leave `RenderSpec.delivery` unset — deployment-configured (resolved question).
- Give the two profiles **distinct recipe names** so publishing both does not
  collide.
- Resolve the tier-1/tier-2 descriptor tension described below.
- Unit tests for descriptor validity and the params propagation.

**NOT in scope**:
- The transformer, guard, mixin, runner step, or descriptor `layout` field —
  all delivered by dependencies. Use them; do not modify them.
- `examples/` updates (TASK-2195) and the e2e rewrite (TASK-2196).
- Docs (TASK-2197).
- Registering a `days` transformer — explicitly not the chosen approach.
- Changing `register_datasets()` or the `troc.finance_projection` schema.

---

## ⚠️ Critical design point — resolve BEFORE writing descriptors

Two verified facts collide, and how you reconcile them determines the descriptor
design. **Do not start coding until you have decided and recorded the approach.**

1. **`publish_recipe` maps a section to a transformer by the section's *name***
   (`infographic_authoring.py:336`, `_transformer_name` at 394-397), and sets
   `TransformStep.inputs = list(section.datasets)` (line 351) and
   `TransformStep.params = dict(descriptor.params)` (line 352).
   → So section names must be `variance_analysis`, `top_movers`,
   `division_breakdown`, `day_totals`, `narrative_facts`, `groupby_aggregate`.

2. **`validate_descriptor_datasets(descriptor, dm)` requires every
   `section.datasets` entry to be a registered `DatasetManager` alias** — and it
   is called by `generate_infographic` (`infographic_authoring.py:151`), the
   tier-1 path.
   → But `narrative_facts` takes prior-step `output_key`s as inputs
   (`variance_analysis`, `top_movers`, `division_breakdown`), which are **not**
   dataset aliases and will fail that gate.

Also note `descriptor.params` is shared by **all** steps (line 352), which is
convenient for `snapshot_col` but means a per-step param (e.g. `top_movers`' `n`)
cannot be expressed per-section through this path.

Candidate resolutions to evaluate (pick one, justify it):

- **(a) Tier-2-only descriptors.** The two new descriptors are for
  `publish_recipe`; tier-1 `generate_infographic` is not used with them. Cleanest
  given the feature's goal is tier 2, but leaves the agent without a working
  one-shot path — check whether anything (examples, tests, handlers) still calls
  `generate_infographic` on this agent.
- **(b) Separate tier-1 and tier-2 descriptors.** Keep a tier-1-valid descriptor
  (dataset-backed sections only, no `narrative_facts`) plus tier-2 descriptors
  with the full chain. More surface, but both paths work.
- **(c) Declare `narrative_facts` with `datasets=[]`** and confirm the empty list
  passes the tier-1 gate and yields `TransformStep.inputs=[]` — then the runner
  would fail at transform time (`runner.py:463-473`) because the inputs are
  missing. Only viable if inputs can be supplied another way; **verify before
  choosing**.

Whatever you choose, the per-step-params limitation must also be handled — e.g.
accept the shared-params default for `n`, or note it as a follow-up.

Record the decision and evidence in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/finance_reporter.py` | MODIFY | Compose `NarrativeMixin`; remove data-splice descriptor + payload override; add two A2UI descriptors |
| `packages/ai-parrot/tests/unit/bots/test_finance_reporter_descriptors.py` | CREATE | Descriptor validity + params propagation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Currently in agents/finance_reporter.py (lines 23-35):
from datetime import datetime, timezone          # line 25  <-- may become unused after removal
from pathlib import Path                         # line 26  <-- may become unused
from typing import Any, Dict, List, Optional, Tuple, Union   # line 27
import pandas as pd                              # line 29  <-- likely unused after removal
from aiohttp import web                          # line 30
from parrot.bots.data import PandasAgent         # line 32
from parrot.bots.mixins import InfographicAuthoringMixin   # line 33
from parrot.registry import register_agent       # line 34
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec  # line 35

# ADD:
from parrot.bots.mixins import NarrativeMixin              # TASK-2192
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec  # TASK-2188

# Remove now-unused imports after deleting the override (ruff will flag them).
```

### Existing Signatures to Use

```python
# agents/finance_reporter.py — CURRENT STATE
DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "sdd" / "artifacts"  # line 41
FINANCE_DATASET = "finance_projection"                                            # line 43
FINANCE_COLUMNS = ["snapshot_date", "division", "project", "rev_actual",
                   "rev_budget", "ebitda_actual", "ebitda_budget"]                # lines 44-52

@register_agent(name="finance_reporter")                                          # line 55
class FinanceReporter(InfographicAuthoringMixin, PandasAgent):                     # line 56
    agent_id: str = "finance_reporter"                                            # line 59
    llm = "google:gemini-3.5-flash"                                               # line 60
    TEMPLATE_NAME = "budget_variance_dashboard_Template.html"                     # line 62
    def __init__(self, *args, **kwargs) -> None:                                  # line 64
        kwargs.setdefault("template_dirs", [str(DEFAULT_TEMPLATE_DIR)])           # line 66
        super().__init__(*args, llm=kwargs.pop("llm", None) or self.llm, **kwargs)  # lines 67-71
    async def register_datasets(self) -> None: ...                                 # line 73
        # add_table_source(name=FINANCE_DATASET, table="troc.finance_projection",
        #                  driver="pg", description=..., usage_guidance=...)       # lines 79-97
    async def configure(self, app=None, queries=None) -> None:                     # line 99
        await self.register_datasets()                                             # line 105
        await super().configure(app=app, queries=queries)                          # line 106
    @classmethod
    def budget_variance_descriptor(cls) -> SectionDescriptor: ...                  # line 108  <-- REMOVE
    async def _build_section_payload(self, descriptor, params): ...                # line 131  <-- REMOVE
```

```python
# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
async def publish_recipe(self, name, descriptor, owner=None, delivery=None,
                         overwrite=False) -> Union[InfographicRecipe, GapReport]:  # line 280
    # collision: (name, owner) requires overwrite=True                  lines 321-330
    tname = self._transformer_name(section)                              # line 336
    transformer_registry.get(tname)   # KeyError -> gap                 # line 338
    transforms.append(TransformStep(
        transformer=tname,
        inputs=list(section.datasets),                                  # line 351
        params=dict(descriptor.params),   # SHARED BY ALL STEPS         # line 352
        output_key=section.target.lstrip("/"),                          # line 353
    ))
    layout = descriptor.layout or LayoutSpec(...)   # TASK-2193         # lines 379-382
    narrative=descriptor.narrative                  # TASK-2193
@staticmethod
def _transformer_name(section) -> str:
    return re.sub(r"\W+", "_", section.name).strip("_")                 # line 397
async def generate_infographic(self, template, descriptor, params=None): # line ~120
    validate_descriptor_datasets(descriptor, dm)                         # line 151  <-- the tier-1 gate
```

```python
# REGISTERED TRANSFORMER NAMES (library.py) — section names must match these:
#   day_totals (105) | division_breakdown (132) | variance_analysis (191)
#   top_movers (253) | groupby_aggregate (318) | pivot (346)
#   latest_vs_baseline (375) | narrative_facts (TASK-2186)
#
# Input alias conventions (library.py:38-49 of the example YAML + docstrings):
#   finance transformers expect an input keyed "snapshots"
#   groupby_aggregate / pivot expect an input keyed "df"
#   latest_vs_baseline expects "baseline" and "latest"
#   narrative_facts expects "variance_analysis" / "top_movers" / "division_breakdown"
#
# snapshot_col: default "snapshot" (library.py:13); troc.finance_projection
#   exposes "snapshot_date" (finance_reporter.py:44) -> MUST be passed explicitly.
#   variance_analysis RAISES without the column (library.py:215-216).
```

```yaml
# examples/infographic_recipes/budget-variance-daily.yaml — the reference layout
# to model both profiles on. Verified structure:
data_sources:                       # lines 43-49
  - {dataset: in_month_projections, alias: snapshots, force_refresh: true}
  - {dataset: in_month_projections, alias: df, force_refresh: true}
transforms:                         # lines 53-102 (day_totals, division_breakdown,
                                    #  variance_analysis, top_movers, groupby_aggregate)
layout:                             # lines 105-153
  component: Infographic
  properties:
    title: ...
    sections:
      - heading: Snapshot
        components: [{component: KPICard, properties: {value: {$bind: "/variance_analysis/last_totals/rev_actual"}}}]
      - heading: ...
        components: [{component: Chart, properties: {data: {$bind: "/chart_data/rows"}}}]
      - heading: ...
        components: [{component: DataTable, properties: {data: {$bind: "/top_movers/worst"}}}]
render: {profile: interactive-html, theme: null, delivery: null}   # lines 158-161
```

```python
# Report layout shape (verified against REPORT_SCHEMA, report.py:31-63):
#   required: ["title", "sections"]; section requires ["heading"]
#   supported: title, metadata, summary, sections[].text, sections[].components
# Infographic layout shape (INFOGRAPHIC_SCHEMA):
#   required: ["title", "sections"]; supported: subtitle, theme,
#   sections[].heading, sections[].text, sections[].components
```

### Does NOT Exist

- ~~`FinanceReporter.budget_variance_descriptor`~~ **after this task** — it is removed.
  Anything still calling it must be updated (examples in TASK-2195, tests in TASK-2196).
- ~~a `days` transformer~~ — not registered, and this task must not add one.
- ~~`SectionDescriptor.mode == "a2ui"`~~ — `mode` stays `Literal["jinja","data-splice"]`.
  The A2UI path is expressed via `layout`, so `mode` keeps whatever value is
  needed for the descriptor to validate; it is not what selects the layout.
- ~~per-section `params` on `SectionSpec`~~ — params are descriptor-level and
  shared across all generated steps (line 352).
- ~~`RenderSpec.delivery` populated with `daily_report.py`'s recipient list~~ —
  deployment-configured; leaving it `None` is the resolved decision.
- ~~`NarrativeSpec.llm` / `.model`~~ — absent by design. The model comes from
  `FinanceReporter.llm` (`google:gemini-3.5-flash`, or `amazon.nova-lite-v1:0`
  per the resolved question) via the agent's client.
- ~~`_build_section_payload` on `FinanceReporter`~~ **after this task** — removed;
  the mixin's default (`infographic_authoring.py:182`) applies if tier 1 is used.
- ~~`sdd/artifacts/budget_variance_dashboard_Template.html` being needed~~ — the
  A2UI profiles do not use it. Decide whether `template_dirs` /
  `DEFAULT_TEMPLATE_DIR` / `TEMPLATE_NAME` remain meaningful and say so in the
  Completion Note; do not delete the template file itself.

---

## Implementation Notes

### Pattern to Follow

```python
@register_agent(name="finance_reporter")
class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    """Budget-variance reporting agent over ``troc.finance_projection``."""

    agent_id: str = "finance_reporter"
    llm = "google:gemini-3.5-flash"
    narrative_skill = "budget-narrative"

    REPORT_RECIPE_NAME = "budget-variance-report"
    DASHBOARD_RECIPE_NAME = "budget-variance-dashboard"

    _SNAPSHOT_PARAMS = {"snapshot_col": "snapshot_date"}   # resolved: explicit

    @classmethod
    def _transform_sections(cls) -> list[SectionSpec]:
        """Sections whose NAMES are registered transformer names."""
        return [
            SectionSpec(name="variance_analysis", target="/variance_analysis",
                        datasets=["snapshots"], shape="mapping"),
            SectionSpec(name="top_movers", target="/top_movers",
                        datasets=["snapshots"], shape="mapping"),
            SectionSpec(name="division_breakdown", target="/division_breakdown",
                        datasets=["snapshots"], shape="mapping"),
            SectionSpec(name="narrative_facts", target="/narrative_facts",
                        datasets=[...],  # <-- per the resolved design point above
                        shape="mapping"),
        ]
```

### Key Constraints

- **MRO order**: `NarrativeMixin` first, then `InfographicAuthoringMixin`, then
  `PandasAgent`. Both mixins are cooperative and chain `super()`.
- **Transform order matters**: `narrative_facts` must come *after* the three
  steps it consumes — `publish_recipe` preserves `descriptor.sections` order into
  `transforms` (line 335 loop), so section order is the execution order.
- `variance_analysis` **raises** without the snapshot column
  (`library.py:215-216`), so `snapshot_col` must be right or every run fails loudly.
- Every narrative bind carries `optional: True`, or a no-narrator replay aborts
  at the drift check.
- Two distinct recipe names; publishing both must not need `overwrite=True`.
- After removing the override, run `ruff` and delete the imports it orphans
  (`pandas`, `datetime`, possibly `Path`).
- Keep `register_datasets()` and `configure()` behaviour unchanged.

### References in Codebase

- `examples/infographic_recipes/budget-variance-daily.yaml` — the layout to model
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/report.py:31-63` — `REPORT_SCHEMA`
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/infographic.py` — `INFOGRAPHIC_SCHEMA`
- `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py:280-392` — `publish_recipe`
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py` — transformer names + input aliases

---

## Acceptance Criteria

- [ ] `FinanceReporter` composes `NarrativeMixin` before `InfographicAuthoringMixin`
- [ ] `budget_variance_descriptor` and `_build_section_payload` are **gone** from the file
- [ ] No hand-rolled aggregation remains in `agents/finance_reporter.py` (**G-B**) — no `groupby`, `itertuples`, or manual summing
- [ ] `report_descriptor()` returns a descriptor with a `Report` `layout` and a `narrative`
- [ ] `dashboard_descriptor()` returns a descriptor with an `Infographic` `layout`
- [ ] Every section name resolves via `transformer_registry.get(_transformer_name(section))`
- [ ] `descriptor.params` contains `snapshot_col == "snapshot_date"`
- [ ] Every narrative `$bind` in both layouts carries `optional: True`
- [ ] `narrative.skill == "budget-narrative"`
- [ ] Section order places `narrative_facts` after its three inputs
- [ ] `REPORT_RECIPE_NAME != DASHBOARD_RECIPE_NAME`
- [ ] Both layouts satisfy their catalog schemas (`title` + `sections` present)
- [ ] `RenderSpec.delivery` is left `None`
- [ ] `ruff check agents/finance_reporter.py` clean (no orphaned imports)
- [ ] `mypy` clean on the changed file
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_finance_reporter_descriptors.py -v`
- [ ] The resolved design point is recorded in the Completion Note

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_finance_reporter_descriptors.py  (create)
import re

import pytest

from parrot.outputs.a2ui.recipes.transformers import transformer_registry


@pytest.fixture(scope="module")
def descriptors():
    from agents.finance_reporter import FinanceReporter
    return {
        "report": FinanceReporter.report_descriptor(),
        "dashboard": FinanceReporter.dashboard_descriptor(),
    }


class TestFinanceReporterDescriptors:
    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_every_section_resolves_to_a_transformer(self, descriptors, key):
        """G-A: this is what makes publish_recipe return a recipe, not a GapReport."""
        for section in descriptors[key].sections:
            name = re.sub(r"\W+", "_", section.name).strip("_")
            transformer_registry.get(name)   # raises KeyError if unmapped

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_snapshot_col_passed_explicitly(self, descriptors, key):
        """Resolved question: explicit params, not the 'snapshot' default."""
        assert descriptors[key].params["snapshot_col"] == "snapshot_date"

    def test_report_layout_is_report_component(self, descriptors):
        assert descriptors["report"].layout.component == "Report"

    def test_dashboard_layout_is_infographic(self, descriptors):
        assert descriptors["dashboard"].layout.component == "Infographic"

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_layout_satisfies_catalog_required_keys(self, descriptors, key):
        props = descriptors[key].layout.properties
        assert "title" in props and "sections" in props

    def test_report_declares_narrative(self, descriptors):
        assert descriptors["report"].narrative.skill == "budget-narrative"

    @pytest.mark.parametrize("key", ["report", "dashboard"])
    def test_narrative_binds_are_optional(self, descriptors, key):
        """G-E: a no-narrator replay must not abort at the drift check."""
        def walk(v):
            if isinstance(v, dict):
                if "$bind" in v and "/narrative" in str(v["$bind"]):
                    assert v.get("optional") is True, f"non-optional narrative bind: {v}"
                for i in v.values():
                    walk(i)
            elif isinstance(v, list):
                for i in v:
                    walk(i)

        walk(descriptors[key].layout.properties)

    def test_narrative_facts_ordered_after_its_inputs(self, descriptors):
        names = [s.name for s in descriptors["report"].sections]
        if "narrative_facts" in names:
            i = names.index("narrative_facts")
            for dep in ("variance_analysis", "top_movers", "division_breakdown"):
                assert names.index(dep) < i

    def test_distinct_recipe_names(self):
        from agents.finance_reporter import FinanceReporter
        assert FinanceReporter.REPORT_RECIPE_NAME != FinanceReporter.DASHBOARD_RECIPE_NAME

    def test_no_handrolled_aggregation(self):
        """G-B: every number must come from a registered transformer."""
        from pathlib import Path
        src = Path("agents/finance_reporter.py").read_text()
        for banned in ("groupby", "itertuples", "_build_section_payload",
                       "budget_variance_descriptor"):
            assert banned not in src, f"{banned} should be gone"

    def test_narrative_mixin_composed_first(self):
        from agents.finance_reporter import FinanceReporter
        from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin
        mro = FinanceReporter.__mro__
        assert mro.index(NarrativeMixin) < mro.index(InfographicAuthoringMixin)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above — §3 Module 8, §7 Known Risks (the
   `snapshot_col` silent-failure trap), and §1 Non-Goals (why replacing is correct)
2. **Check dependencies** — TASK-2186, TASK-2189, TASK-2192 and TASK-2193 must all
   be in `sdd/tasks/completed/`. **Read TASK-2192's and TASK-2193's Completion
   Notes** — they record the LLM seam and the descriptor field types you depend on.
3. **Resolve the "Critical design point" FIRST.** Decide how `narrative_facts`
   declares its inputs given the tier-1 dataset gate, gather the evidence, and
   record it. Do not write descriptors before this is settled.
4. **Verify the Codebase Contract** — confirm the registered transformer names and
   their input-alias conventions in the shipped `library.py`
5. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met. Expect FEAT-326's e2e tests to fail
   at this point — that is by design; TASK-2196 rewrites them. Do **not** patch
   them here and do **not** revert this task to make them pass.
8. **Move this file** to `sdd/tasks/completed/TASK-2194-finance-reporter-a2ui-migration.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-07
**Notes**: Removed `budget_variance_descriptor()` and `_build_section_payload`
entirely. Composed `NarrativeMixin` first in the MRO
(`class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin,
PandasAgent)`). Added `report_descriptor()` (Report layout, one section
bound to `/narrative` with `optional: True`) and `dashboard_descriptor()`
(Infographic layout, KPICard + DataTable components bound to
`variance_analysis`/`top_movers` outputs). Both descriptors share
`_transform_sections()` (4 `SectionSpec`s: `variance_analysis`, `top_movers`,
`division_breakdown`, then `narrative_facts` last — order matters, see
below) and `_SNAPSHOT_PARAMS = {"snapshot_col": "snapshot_date"}` via
`descriptor.params`. `REPORT_RECIPE_NAME`/`DASHBOARD_RECIPE_NAME` are
distinct. `RenderSpec.delivery` is never touched (left to `publish_recipe`'s
`delivery=` param, deployment-configured). 18 tests pass; broader regression
(a2ui + infographic_recipes + infographic_sections): 308 passed, 4 skipped
(pre-existing). `ruff check` clean on all NEW code (one genuine finding —
`RUF012` mutable class-attr default for `_SNAPSHOT_PARAMS` — fixed with
`ClassVar[dict]`); remaining findings are unchanged pre-existing style
(`UP006`/`UP007`/`RUF013`/`I001` on lines untouched from the original file).
`mypy`: 5 findings — 2 (`_active_skill`/`conversation` MRO conflicts) are
the SAME category already present on `agents/security_advisor.py` (an
existing `SkillRegistryMixin` composer, verified via a direct mypy run on
it) — an accepted, pre-existing limitation of this mixin architecture, not
a new regression; the other 3 are unchanged from the original file
(implicit-Optional `configure()` params).

**Resolved design point**:
- **How `narrative_facts` declares its inputs vs. the tier-1 dataset gate**:
  verified by direct source inspection that `validate_descriptor_datasets`
  (the tier-1 gate that would reject `narrative_facts`'s prior-step-alias
  inputs) is called ONLY from `generate_infographic` — `publish_recipe`
  never calls it. Since `report_descriptor()`/`dashboard_descriptor()` are
  designed exclusively for `publish_recipe` (tier 2), and no handler/example/
  production code calls `generate_infographic` on `FinanceReporter` (only
  the FEAT-326 e2e test does, which fails by design — TASK-2196 rewrites
  it), the tier-1 gate concern is moot.
- **Approach chosen**: **(a) Tier-2-only descriptors**, per the evidence
  above.
- **A SECOND, deeper problem discovered beyond the task's own framing** (the
  task's "Critical design point" section only discussed the tier-1 gate and
  the shared-params limitation — it did not anticipate this): `publish_recipe`
  builds `data_sources` by taking the UNION of every section's `datasets`
  list and creating `DataSourceSpec(dataset=alias, alias=alias)` for EACH —
  with NO distinction between "a real DatasetManager alias" and "a prior
  TransformStep's output_key". This means:
  1. `narrative_facts`'s three inputs (`variance_analysis`/`top_movers`/
     `division_breakdown`) ALSO get a bogus `DataSourceSpec` each. At replay
     time `_fetch_frames` would try `fetch_dataset("variance_analysis", ...)`,
     get `{"error": "Dataset ... not found."}` back (verified against
     `DatasetManager.fetch_dataset`'s actual body), and abort with
     `RecipeRunException(stage="data")` — BEFORE transforms ever run. This
     is a genuine, previously-unflagged gap in `publish_recipe` (already-
     shipped, out of THIS task's file scope: `infographic_authoring.py` is
     not in the Files to Create/Modify table and the task explicitly says
     not to modify the runner/mixin dependencies).
  2. Separately: because `publish_recipe` forces `dataset == alias`
     (no "fetch X, call it Y" the way hand-authored YAML recipes allow via
     separate `DataSourceSpec.dataset`/`.alias` fields), and every finance
     transformer in `library.py` hard-codes its frame input key as literally
     `"snapshots"` (`df = inputs["snapshots"]`), the DatasetManager alias
     MUST be `"snapshots"` for `variance_analysis`/`top_movers`/
     `division_breakdown` to resolve at all via this descriptor path. This
     is WHY `FINANCE_DATASET` was renamed from `"finance_projection"` to
     `"snapshots"` (see below) — the task's own descriptor sketch already
     assumed `datasets=["snapshots"]`, confirming this was the intended shape.
  - **Not fixed in this task** (deliberately, per file-scope discipline):
    issue (1) above. Flagged prominently here for TASK-2196 (the e2e task,
    which will empirically exercise `publish_recipe` → `RecipeRunner.run()`
    and hit this) to resolve with real test evidence, in whichever file that
    evidence points to — rather than guessing a fix now against a file this
    task is not scoped to touch.
- **Per-step params limitation**: not needed — only `snapshot_col` must be
  shared across all four steps; `top_movers`'s `n` param simply uses its
  default (3). No follow-up required.
- **Fate of `TEMPLATE_NAME` / `DEFAULT_TEMPLATE_DIR` / `template_dirs`**: kept.
  `SectionDescriptor.template` is a required field regardless of whether the
  tier-1 render path is used, so both descriptors still set
  `template=cls.TEMPLATE_NAME` for schema-completeness; `template_dirs`/
  `DEFAULT_TEMPLATE_DIR` remain wired in `__init__` (harmless — never
  consulted since `generate_infographic` is not called on this agent
  anymore). The reference `.html` template file itself is untouched.

**Deviations from spec**: one, load-bearing —
`FINANCE_DATASET` was renamed from `"finance_projection"` to `"snapshots"`.
The "NOT in scope" list says "changing `register_datasets()` ... behaviour
unchanged" — interpreted as: don't change the SQL/table schema or the
registration MECHANISM (still `add_table_source(name=FINANCE_DATASET,
table="troc.finance_projection", driver="pg", ...)`, verbatim, same real
table). The method's CODE is byte-for-byte unchanged; only the module-level
alias constant's VALUE changes, and this is required for the feature to be
reachable at all via `publish_recipe` (see design-point analysis above).
Verified via repo-wide grep that no other tracked file references
`FINANCE_DATASET`. Also note: `agents/finance_reporter.py` had **zero git
history** (`/agents/` is gitignored repo-wide) — copied from the main
checkout into this worktree and `git add -f`'d, mirroring the precedent
`.gitignore` already documents for `agents/odoo_agent/`.
