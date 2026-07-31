# TASK-1873: End-to-end budget-variance example + documentation

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1870, TASK-1871, TASK-1872
**Assigned-to**: unassigned

---

## Context

Module 9 of FEAT-324 — the proof and the migration story: a hand-written
`budget-variance-daily` recipe reproducing the reference dashboard
(`sdd/artifacts/budget_variance_dashboard_Template.html`) end-to-end through Modules 1–8,
replacing `daily_report.py`'s Task Scheduler + Outlook flow. Also the feature docs.

---

## Scope

- Author `examples/infographic_recipes/budget-variance-daily.yaml`: KPI row (4 KPICards) +
  actual-vs-budget Chart + grouped ledger DataTable, fed by `day_totals`,
  `division_breakdown`, `variance_analysis`, `top_movers` over a `in_month_projections`
  dataset with a `{month}` param defaulting to the `current_month` resolver;
  `render.profile: interactive-html`.
- Author fixture CSVs (3 snapshots, anonymized/synthetic, compact-row columns from
  `daily_report.py:parse_csv`) under the integration-test fixtures dir.
- Implement the three spec integration tests:
  - `test_e2e_budget_variance_recipe` — fixtures → DatasetManager (InMemory/file source) →
    recipe → interactive HTML `RenderedArtifact`; re-run with changed fixture data yields
    updated numbers, identical structure (assert on embedded dataModel, not pixels);
  - `test_e2e_freeze_then_replay` — simulated session envelope → freeze → replay produces an
    equivalent envelope without the LLM;
  - `test_e2e_static_profile_delivery` — same recipe with `render.profile: ssr-html` →
    `deliver_artifact` (mock notification provider).
- Write `docs/outputs/infographic-recipes.md`:
  - concepts (recipe = precise construction instructions; transformers; stores; triggers);
  - the YAML recipe walkthrough annotated line-by-line;
  - replay via chat tool, REST (`POST .../run`), and scheduling via `SchedulerJobsHandler`
    with the `run_infographic_recipe` callback + `schedule.principal`;
  - the migration table: `daily_report.py` concern → FEAT-324 replacement (Task Scheduler →
    AgentSchedulerManager; Outlook COM → deliver_artifact; splice_into_template →
    interactive-html renderer; parse_csv+analyze → DatasetManager + transformers);
  - fail-fast drift diagnostics and how to read `RecipeRunError`.

**NOT in scope**: new runtime code (docs + example + tests only; if an e2e test exposes a
bug, file it in the completion note and fix in the owning task's module with a minimal patch).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/infographic_recipes/budget-variance-daily.yaml` | CREATE | canonical example recipe |
| `packages/ai-parrot/tests/integration/infographic_recipes/test_e2e.py` | CREATE | 3 integration tests |
| `packages/ai-parrot/tests/integration/infographic_recipes/fixtures/*.csv` | CREATE | 3 synthetic snapshots |
| `docs/outputs/infographic-recipes.md` | CREATE | feature documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All produced by prior FEAT-324 tasks — READ their completed implementations first:
from parrot.outputs.a2ui.recipes import InfographicRecipe            # TASK-1865
from parrot.outputs.a2ui.recipes.store import FileRecipeStore        # TASK-1868
from parrot.tools.infographic_recipes.runner import RecipeRunner     # TASK-1869
from parrot.tools.infographic_recipes.freeze import freeze_session_envelope  # TASK-1870
from parrot.tools.dataset_manager.tool import DatasetManager         # tool.py:501 (existing)
from parrot.outputs.a2ui.delivery import deliver_artifact            # delivery.py:86 (existing)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):        # line 501
    async def add_dataset(self, ...):         # line 962 — read full signature to register the
                                              #   fixture CSVs (or use an InMemorySource — see
                                              #   parrot/tools/dataset_manager/sources/memory.py)
    async def fetch_dataset(...):             # line 3266

# Fixture column contract (from daily_report.py:parse_csv, lines 126-152):
# division, project, rev_actual, rev_budget, ebitda_actual, ebitda_budget (+ snapshot date)

# Reference visual semantics: sdd/artifacts/budget_variance_dashboard_Template.html
# (KPI row, day ribbon, chart w/ metric toggle, division-rollup ledger).
```

### Does NOT Exist
- ~~`sdd/artifacts/*` as importable code~~ — reference only; never import
- ~~Pixel/screenshot assertions~~ — no browser in CI; assert on embedded dataModel JSON and
  structural HTML markers instead
- ~~A real SMTP/Outlook in tests~~ — delivery test mocks the notification provider
  (deliver_artifact's `owner.send_notification`)
- ~~`docs/outputs/` directory~~ — may not exist yet; create it (verify with `ls docs/`)

---

## Implementation Notes

### Key Constraints
- The YAML recipe is the CANONICAL example users copy — every field commented, param usage
  shown, and it must load + `dry_run` clean in a test.
- Fixture data must be synthetic (no real TROC figures) but shaped to exercise: negative and
  positive variances, a division with offsetting projects, an empty-ish division (edge cases
  the transformers handle).
- The "updated data, identical structure" assertion is the core promise of the feature —
  compare component tree (ids/types/bindings) equality + dataModel value inequality.
- Docs follow the existing docs/ tone; link the spec and the brainstorm as design records.

### References in Codebase
- `docs/migration/feat-201-ai-parrot-embeddings.md` — migration-doc precedent/tone
- `sdd/specs/infographic-builder.spec.md` §4 Integration Tests — normative test list

---

## Acceptance Criteria

- [ ] `budget-variance-daily.yaml` loads, `dry_run`s clean, and renders via interactive-html
- [ ] `test_e2e_budget_variance_recipe` passes incl. the re-run structure/values assertion
- [ ] `test_e2e_freeze_then_replay` passes (equivalent envelope, no LLM)
- [ ] `test_e2e_static_profile_delivery` passes (mock provider receives the artifact)
- [ ] `docs/outputs/infographic-recipes.md` complete with migration table + scheduling walkthrough
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integration/infographic_recipes/ -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/infographic_recipes/test_e2e.py
class TestBudgetVarianceE2E:
    async def test_e2e_budget_variance_recipe(self, dataset_manager_with_fixtures): ...
    async def test_rerun_updates_values_keeps_structure(self, ...): ...
    async def test_e2e_freeze_then_replay(self, ...): ...
    async def test_e2e_static_profile_delivery(self, mock_notification_owner): ...
```

---

## Agent Instructions

1. **Read the spec**, the reference artifacts, and ALL completed FEAT-324 task Completion
   Notes (deviations may have shifted APIs)
2. **Check dependencies** — TASK-1870, TASK-1871, TASK-1872 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** against the actually-merged implementations
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-22
**Notes**: Read all prior FEAT-324 Completion Notes before starting (per
instructions) — none of the noted deviations changed public APIs used here.
Built 3 synthetic fixture CSVs (`snapshot_2026-07-01/21/22.csv`, compact-row
format matching `daily_report.py:parse_csv`) covering negative variance
(Beta/Delta), positive (Alpha/Gamma), and a flat/no-variance edge case
(Epsilon). Verified the full pipeline manually (`add_dataset` → recipe
`from_yaml` → `dry_run` → `run`) before writing formal pytest, catching two
real integration issues early: (1) each built-in transformer hard-codes its
own expected input-alias name (`day_totals`/etc. expect `"snapshots"`,
`groupby_aggregate` expects `"df"`) — the example recipe therefore declares
TWO `data_sources` aliasing the SAME dataset; (2) `day_totals`'s per-snapshot
keys are dynamic (today's date changes daily) and unsuitable for a fixed
`$bind` pointer — the layout binds to `variance_analysis`'s stable
`first_totals`/`last_totals` keys instead, with `day_totals`/
`division_breakdown` still included as transform steps (satisfying "fed by"
literally) even though the curated layout doesn't bind directly into them.
All 4 integration tests pass + the example recipe's own `dry_run`; `ruff
check` clean; no regressions across the full recipes/toolkit/runner/
visualizations/server test suites (100 + 49 + 15 = 164 tests, run
separately due to a pre-existing `tests.conftest` module-name collision
between the ai-parrot and ai-parrot-server packages when combined in one
pytest invocation — unrelated to this feature).

**Deviations from spec**: (1) `render.profile: ssr-html` (hyphen) in the
task text does not match the ACTUALLY REGISTERED renderer name — verified
`ssr_html.py`'s `_SURFACE_NAME = "ssr_html"` (underscore); used the correct
registered name throughout. (2) The "grouped ledger DataTable" binds to
`top_movers.worst` (flat rows) rather than `division_breakdown`'s nested
per-division dict, since `DataTable` needs a flat rows array and writing a
NEW flattening transformer was explicitly out of scope for this
docs-and-example-only task; documented as a deliberate adaptation using only
the 7 existing transformers. (3) Both `packages/ai-parrot/conftest.py`
(closer `pyproject.toml` rootdir) and the ai-parrot-visualizations namespace
merge required a LOCAL, test-file-scoped `sys.path`/`parrot.outputs.__path__`
fix (inserted, not appended — `a2ui_renderers` is a regular, non-namespace
subpackage that resolves to the FIRST matching directory) since this e2e
test is the first ai-parrot-core test to need the visualizations satellite;
scoped to `test_e2e.py` only, no shared conftest touched for this task.
