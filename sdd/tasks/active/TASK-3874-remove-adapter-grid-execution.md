# TASK-3874: Delete legacy adapter and grid execution classes

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3865, TASK-3870, TASK-3871
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12** and AC1/AC14. After every type runs the three cycle hooks, two pieces of legacy
execution machinery become dead code:

- `planogram/types/legacy_adapter.py` (`legacy_perceive`) — the ROI-first orchestration that the base-class
  `perceive()` delegated to for unmigrated types. TASK-3870 removes that lazy import (`abstract.py:508`).
- The grid *execution* classes (`GridDetector`, `HorizontalBands`, `AbstractGridStrategy`/`NoGrid`/`get_strategy`,
  `CellResultMerger`) — used only by the legacy half of `ProductOnShelves` (removed by TASK-3865) and
  `AbstractPlanogramType.get_grid_strategy` (removed by TASK-3870).

Spec §6 "Corrections" row *grid directory can be deleted*: **False** — `models.py:9` imports
`DetectionGridConfig` (the `detection_grid` config field is accepted-but-ignored for one release) and
`identification/identify.py:26` imports `_compute_iou`. Therefore keep `grid/models.py` untouched, reduce
`grid/merger.py` to `_compute_iou`, and re-export only the data models from `grid/__init__.py`.
Also delete the adapter-order characterization file `test_legacy_run_orchestration.py` (Module 12:
"Delete only the adapter-order test file").

---

## Scope

- Delete `planogram/types/legacy_adapter.py`, `planogram/grid/detector.py`, `planogram/grid/horizontal_bands.py`,
  `planogram/grid/strategy.py` (whole modules, `git rm`).
- Rewrite `planogram/grid/__init__.py` to re-export only `DetectionGridConfig`, `GridCell`, `GridType` from `grid.models`.
- Reduce `planogram/grid/merger.py` to its module docstring, imports actually used, and the unchanged `_compute_iou`.
- Delete `tests/planogram_cycle/test_legacy_run_orchestration.py` (every test in it pins the legacy adapter; see list below).
- Verify, before deleting, that no importer remains (greps below) — STOP and report if one does.

**NOT in scope**:
- `grid/models.py` — untouched (spec Module 12 "retain grid/models.py for accepted detection_grid input").
- `models.py` (`PlanogramConfig.detection_grid` description) — TASK-3872.
- `types/abstract.py` (removing `legacy_perceive` import / `get_grid_strategy`) — TASK-3870, a dependency.
- `types/product_on_shelves.py` (removing grid imports at lines 12-15) — TASK-3865, a dependency.
- `contracts.py` `LegacyPayload` — TASK-3871.
- `planogram/legacy.py`, `detector.py`, export tables and import tests — TASK-3873.
- Characterization / type-suite rewrites — TASK-3875, TASK-3876. `test_type_hooks.py` legacy tests — TASK-3870.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/legacy_adapter.py` | MODIFY | **DELETE the whole file** (`git rm`) — `legacy_perceive` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/detector.py` | MODIFY | **DELETE the whole file** (`git rm`) — `GridDetector` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/horizontal_bands.py` | MODIFY | **DELETE the whole file** (`git rm`) — `HorizontalBands` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/strategy.py` | MODIFY | **DELETE the whole file** (`git rm`) — `AbstractGridStrategy`, `NoGrid`, `get_strategy` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py` | MODIFY | Re-export grid data models only |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py` | MODIFY | Keep only `_compute_iou` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py` | MODIFY | **DELETE the whole file** (`git rm`) — legacy adapter-order tests |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | Remove the now-unread legacy ClassVars (`requires_slots_definition`, `min_usable_shapes`, `uses_enhanced_image`, `identify_strategy`) and `fallback_detection_prompt()` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# surviving imports (verified on dev ff2f90213)
from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridCell, GridType  # grid/models.py:27,72,14
from parrot.models.detections import DetectionBox                                         # grid/merger.py:13 (already imported)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py (177 lines)
import logging                                                                 # line 9  (only CellResultMerger uses it)
from typing import List, Optional, Tuple                                       # line 10 (only CellResultMerger uses it)
from parrot_pipelines.planogram.grid.models import GridCell                    # line 12 (only CellResultMerger uses it)
from parrot.models.detections import DetectionBox, IdentifiedProduct           # line 13 (keep DetectionBox only)
def _compute_iou(box_a: DetectionBox, box_b: DetectionBox) -> float:            # lines 16-46 — KEEP BYTE-IDENTICAL
class CellResultMerger:                                                         # lines 49-177 — DELETE

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py (30 lines)
# lines 6-10 import DetectionGridConfig/GridCell/GridType from grid.models (KEEP);
# lines 11-18 import GridDetector, HorizontalBands, CellResultMerger, AbstractGridStrategy, NoGrid, get_strategy (DELETE)
# lines 20-30 __all__ lists all nine names (REDUCE to the three models)

# Surviving users (must still work after this task)
# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:9
from parrot_pipelines.planogram.grid.models import DetectionGridConfig
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:26 (line may shift after TASK-3858)
from parrot_pipelines.planogram.grid.merger import _compute_iou
#   used at identify.py:297: `if any(_compute_iou(box, other) > DUPLICATE_IOU for other in taken):`

# Files to delete — identifying anchors (grep -Fxc = 1 each, verified)
# types/legacy_adapter.py:1  `"""Legacy cycle adapter: the ROI-first orchestration formerly inlined in ``PlanogramCompliance.run()``.`
#                            async def legacy_perceive(handler, image, image_id, ctx) -> PerceptionResult  (line 21)
# grid/detector.py:27        `class GridDetector:`
# grid/horizontal_bands.py:13 `class HorizontalBands(AbstractGridStrategy):`
# grid/strategy.py:12        `class AbstractGridStrategy(ABC):`   (NoGrid :43, _GRID_STRATEGIES :93, get_strategy :98)
# tests/planogram_cycle/test_legacy_run_orchestration.py:21 `class _LegacyProductOnShelves(ProductOnShelves):`
```

**Importer verification.** Current state on dev (before the dependencies land) — every hit below except
`models.py:9` and `identify.py:26` must be GONE once TASK-3865 and TASK-3870 are done:
```text
$ grep -rn --include='*.py' -E 'grid\.(detector|horizontal_bands|strategy|merger)|GridDetector|HorizontalBands|CellResultMerger|AbstractGridStrategy|NoGrid|get_strategy|legacy_adapter|legacy_perceive' packages/ai-parrot-pipelines packages/ai-parrot/src packages/ai-parrot/tests | grep -v /build/
types/abstract.py:30      from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy   (TYPE_CHECKING) → removed by TASK-3870
types/abstract.py:508-510 from .legacy_adapter import legacy_perceive                                → removed by TASK-3870
types/abstract.py:607-621 def get_grid_strategy(...) / from ...grid.strategy import NoGrid             → removed by TASK-3870
types/product_on_shelves.py:13-15 HorizontalBands / GridDetector / AbstractGridStrategy, NoGrid       → removed by TASK-3865
types/product_on_shelves.py:140-152, 895 get_grid_strategy / GridDetector(...)                         → removed by TASK-3865
tests/planogram_cycle/test_type_hooks.py:176,196,211 test_legacy_perceive_* / test_legacy_adapter_*    → removed by TASK-3870
identification/identify.py:26 from ...grid.merger import _compute_iou                                  → KEEP (survivor)
grid/__init__.py:11-17, grid/merger.py, grid/detector.py, grid/horizontal_bands.py, grid/strategy.py   → edited/deleted here
```
Expected result of the same grep **at execution time** (after dependencies): only `identify.py:<n>` (the
`_compute_iou` import and its call) plus hits inside the files this task edits or deletes. If any other hit
remains — STOP, do not delete, and record it in the Completion Note.

`test_legacy_run_orchestration.py` — every test pins the legacy adapter (class `_LegacyProductOnShelves`
restores the base-class legacy hooks): `test_legacy_run_orchestration_order` (:173),
`test_legacy_promotional_ocr_enrichment` (:207), `test_legacy_promo_ocr_failure_is_swallowed` (:230),
`test_legacy_virtual_shelves_replace_detector_shelves` (:239), `test_legacy_poster_text_and_brand_logo_injection` (:250),
`test_legacy_fact_tag_steps_are_gated_by_config_flag` (:286), `test_legacy_compute_roi_failure_is_swallowed` (:314),
`test_legacy_overall_aggregation` (:341), `test_legacy_empty_results_is_not_compliant` (:365),
`test_legacy_result_keys_and_output_files` (:389). The retained business behaviours (eight result keys,
empty results never compliant) are covered on the cycle by `test_run_template.py`
(`test_run_preserves_eight_keys_for_every_type`, `test_empty_compliance_results_never_compliant`) — no
coverage is lost by deleting this file.

### Does NOT Exist
- ~~Tests importing grid execution classes~~ — `grep -rln 'grid' packages/ai-parrot-pipelines/tests` hits only
  `test_type_hooks.py` (legacy adapter tests, TASK-3870); nothing tests `GridDetector`/`CellResultMerger` directly.
- ~~A replacement for `get_grid_strategy`~~ — none; `detection_grid` is accepted and ignored (spec §2 compatibility policy).
- ~~`_compute_iou` in `grid/models.py`~~ — it lives in `grid/merger.py`; do not move it (identify.py imports that path).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/legacy_adapter.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/detector.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/horizontal_bands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/strategy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py#_compute_iou",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/models.py#DetectionGridConfig",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/models.py#GridCell",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/models.py#GridType"
  ]
}
```
Note: the complexity parser (`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py:193`)
accepts only `CREATE`/`MODIFY`, so deleted files are declared `MODIFY` here and in the Files table.

---

## Implementation Notes

### Planner cross-task notes (added at /sdd-task time)
- Added at /sdd-task time: also edit `types/abstract.py` — delete the legacy ClassVars `requires_slots_definition`, `min_usable_shapes`, `uses_enhanced_image`, `identify_strategy` and the `fallback_detection_prompt()` hook. TASK-3870 had to keep them because plan.py still read them; TASK-3871 (now a dependency) stopped reading them, so they are dead. Verify with `grep -rn` over `packages/ai-parrot-pipelines/src` that no reader remains before deleting; AC1 requires no old hook contract to survive.


### Pattern to Follow
Pure deletion task. `_compute_iou` must remain byte-identical (identify's duplicate-area rejection depends on
its exact semantics: 0.0 for non-overlap and degenerate union).

### Key Constraints
- Run the importer grep first; proceed only if the dependency tasks removed their references.
- `grid/__init__.py` is imported every time `parrot_pipelines.models` is imported (via `grid.models`) — it must
  not import any deleted module, otherwise `PlanogramConfig` itself stops importing.
- Stage deletions with `git rm`; stage edits by path. Never `git add -A`.
- No new test file is owned by this task. Import-level evidence for the removed grid names is the
  `python -c` check in Acceptance Criteria; record its output in the Completion Note.
- Transitional note: this task runs after TASK-3865/3870, so none of the transitional-breakage test files
  should import the removed modules any more; if one still does, it belongs to TASK-3875/3876 — do not edit it here.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the worktree.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py:16-46` — function to keep.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:26,297` — survivor call site.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Run the importer grep — *why*: deletions are only safe when TASK-3865/3870 already removed every caller.
2. `git rm` the four source modules and the test file — *why*: Module 12 deletion list.
3. Rewrite `grid/__init__.py` — *why*: it eagerly imported the deleted modules and is on the import path of `PlanogramConfig`.
4. Reduce `grid/merger.py` — *why*: `_compute_iou` is the one surviving helper (identify.py).
5. Run the Validation Commands and the `python -c` checks — *why*: AC14 (grid models and IoU remain valid).

### Deleted files (DELETE)
```text
git rm packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/legacy_adapter.py \
       packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/detector.py \
       packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/horizontal_bands.py \
       packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/strategy.py \
       packages/ai-parrot-pipelines/tests/planogram_cycle/test_legacy_run_orchestration.py
```
**Why**: each file's only importers are the dependency-removed call sites or the other deleted grid files
(`grid/detector.py` imports `merger.CellResultMerger`; `horizontal_bands.py` imports `strategy`).

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py` (MODIFY — full replacement, 30 → 18 lines)
```python
# occurrences: 1 (verified: grep -Fxc '"""Grid detection package for adaptive planogram compliance.' grid/__init__.py)
# REPLACE lines 1-30 (whole file) with:
"""Detection-grid configuration models (accepted, not executed).

The grid execution classes were removed with the legacy pipeline (FEAT-612). ``DetectionGridConfig`` is kept
because ``PlanogramConfig.detection_grid`` is still accepted — and ignored — for one release.
"""
from parrot_pipelines.planogram.grid.models import (
    DetectionGridConfig,
    GridCell,
    GridType,
)

__all__ = [
    "DetectionGridConfig",
    "GridCell",
    "GridType",
]
```
**Why**: keeps `from parrot_pipelines.planogram.grid import DetectionGridConfig` working while dropping every
execution class; the docstring records why the package still exists (spec §2 compatibility policy).

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py` (MODIFY — full replacement, 177 → ~40 lines)
```python
# occurrences: 1 (verified: grep -Fxc 'class CellResultMerger:' grid/merger.py → line 49)
# REPLACE lines 1-15 (docstring + imports) with the header below, KEEP lines 16-46 (`_compute_iou`) byte-identical,
# DELETE lines 47-177 (blank lines + `class CellResultMerger:` to end of file).
"""Bounding-box overlap helper shared by the identification stage.

Only ``_compute_iou`` survives the removal of the grid execution classes (FEAT-612): the identify stage uses it
to reject model-added shapes that duplicate an existing area.
"""
from parrot.models.detections import DetectionBox


# FILL IN: paste lines 16-46 of the current file here unchanged (`def _compute_iou(box_a: DetectionBox,
#   box_b: DetectionBox) -> float:` … `return intersection / union`) — bounded by AC14 (IoU remains valid)
```
**Why**: `logging`, `typing`, `GridCell` and `IdentifiedProduct` were used only by `CellResultMerger`; leaving them
would fail `ruff check` (F401). The helper keeps its module path because `identify.py` imports it from here.

### FILL IN checklist
- [ ] `grid/merger.py::_compute_iou` — copied unchanged from current lines 16-46; bounded by AC14
- [ ] Completion Note records the importer-grep output and the `python -c` check output

---

## Acceptance Criteria

- [ ] Importer grep at execution time shows only `identification/identify.py` (`_compute_iou`) outside the edited files — AC1/AC14.
- [ ] `python -c "from parrot_pipelines.models import PlanogramConfig; from parrot_pipelines.planogram.grid import DetectionGridConfig, GridCell, GridType; from parrot_pipelines.planogram.grid.merger import _compute_iou"` succeeds — AC14.
- [ ] `python -c "import parrot_pipelines.planogram.grid.detector"` (and `.horizontal_bands`, `.strategy`, `parrot_pipelines.planogram.types.legacy_adapter`) each raise `ModuleNotFoundError` — AC14.
- [ ] `from parrot_pipelines.planogram.grid import CellResultMerger` raises `ImportError` — AC14.
- [ ] `grid/models.py` unchanged (`git diff --stat` does not list it).
- [ ] Validation Commands pass; `ruff check` and `black --check` clean on touched files — AC16.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py -q`

---

## Test Specification

No new tests are owned by this task (the Files table lists no test to create). Regression evidence:

```python
# Existing tests that must stay green (they exercise the survivors):
# test_identify.py            — identify's added-shape duplicate rejection calls _compute_iou
# test_type_hooks.py          — strict three-hook contract (TASK-3870) with no legacy adapter
# test_run_template.py        — eight keys / empty results never compliant (replaces the deleted legacy suite)
# test_pos_migrated_perceive_identify.py — ProductOnShelves imports without any grid module
# (test_run_template.py also imports parrot_pipelines.models.PlanogramConfig, which imports grid.models)
#
# Manual AC checks (record output in the Completion Note):
#   python -c "<positive import one-liner from Acceptance Criteria>"
#   python -c "import importlib; [importlib.import_module(m) for m in (
#       'parrot_pipelines.planogram.grid.detector',)]"   → ModuleNotFoundError (repeat per removed module)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3874 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
