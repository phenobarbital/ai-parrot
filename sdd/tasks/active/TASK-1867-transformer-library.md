# TASK-1867: Built-in transformer library (budget-variance analytics + generic tabular)

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1866
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-324. Ports the analysis routines of `sdd/artifacts/executive_summary.py`
into registered, golden-file-tested transformers, plus generic tabular helpers. These are the
seed vocabulary recipes use in `TransformStep.transformer`.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py` registering,
  via `@infographic_transformer` (TASK-1866):
  - `day_totals` — per-snapshot totals: rev/ebitda actual, budget, variance, variance_pct
    (port of `executive_summary.day_totals`, adapted from row-lists to DataFrames with columns
    `division, project, rev_actual, rev_budget, ebitda_actual, ebitda_budget`).
  - `division_breakdown` — per-division rollup + per-project variances (port of
    `executive_summary.division_breakdown`).
  - `variance_analysis` — first-vs-latest comparison across N snapshots: pct-point change,
    EBITDA dollar change, direction flags (port of the cross-day logic in
    `executive_summary.analyze`, WITHOUT docx/narrative parts).
  - `top_movers` — worst/best N projects by a metric column with optional day-over-day trend
    (port of the `worst`/`best` selection in `analyze`).
  - Generic: `groupby_aggregate` (group cols + named aggs), `pivot`, `latest_vs_baseline`
    (two frames → joined delta frame).
- Each transformer declares `requires_columns` and a params schema; outputs are
  JSON-serializable dicts/records ready to be placed in an envelope `dataModel`.
- Golden-file tests: fixture frames derived from the reference artifacts' compact-row format;
  expected outputs stored under `tests/outputs/a2ui/recipes/golden/`.

**NOT in scope**: date-file discovery logic of `daily_report.py` (finding first-of-month
files is a data-acquisition concern, not a transform), docx generation, chain execution.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py` | CREATE | 7 registered transformers |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | MODIFY | import library so decorators register |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py` | CREATE | golden-file tests |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/golden/*.json` | CREATE | expected outputs |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer  # TASK-1866
```

### Existing Signatures to Use
```python
# SEMANTIC SOURCE (not imported — port the math): sdd/artifacts/executive_summary.py
def day_totals(rows: list) -> dict:            # line 40 — rev/eb totals + variance + pct
def division_breakdown(rows: list) -> dict:    # line 54 — division rollup + project variances
def analyze(report_data: dict) -> dict:        # line 87 — first/last comparison, worst/best,
                                               #   trend_since_first / trend_day_over_day
# Row format in the artifact: [division, project, rev_actual, rev_budget, eb_actual, eb_budget]
# (see daily_report.py:parse_csv lines 126-152)
```

### Does NOT Exist
- ~~`from sdd.artifacts.executive_summary import ...`~~ — artifacts are NOT a package;
  port the logic, never import it
- ~~docx/narrative helpers in scope~~ — `headline_text`, `build_docx`, `fmt_money` stay out;
  formatting is a renderer/layout concern
- ~~A snapshot/date-discovery transformer~~ — multi-snapshot input arrives as one frame with a
  `snapshot` (date) column or as multiple aliased inputs; document the chosen convention in
  the transformer docstrings (recommended: one frame + `snapshot_col` param)

---

## Implementation Notes

### Pattern to Follow
```python
@infographic_transformer(
    "day_totals",
    requires_columns={"snapshots": ["division", "project", "rev_actual",
                                    "rev_budget", "ebitda_actual", "ebitda_budget"]},
    description="Per-snapshot revenue/EBITDA totals and variances vs budget.",
)
def day_totals(inputs: dict[str, pd.DataFrame], params: dict) -> dict:
    ...
```

### Key Constraints
- Pure functions: no I/O, no datetime.now() (dates come in the data or params) — determinism
  is what makes golden files stable.
- Outputs must be plain JSON types (floats/str/lists/dicts) — they go straight into
  `CreateSurface.dataModel`. Round floats consistently (e.g. 2 decimals) and document it.
- Preserve the artifact's semantics exactly where ported (variance = actual − budget;
  variance_pct guards division-by-zero exactly like `executive_summary.py:48`).
- Golden files are committed JSON; regenerate only deliberately.

### References in Codebase
- `sdd/artifacts/executive_summary.py` — normative math to port
- `sdd/artifacts/daily_report.py` — input row format context
- FEAT-273 golden-file precedent: `packages/ai-parrot/tests/outputs/a2ui/golden/` layout

---

## Acceptance Criteria

- [ ] 7 transformers registered with manifests (`requires_columns` + params schema)
- [ ] Golden tests pass and match `executive_summary.py` semantics
      (`test_library_golden_day_totals` et al.)
- [ ] Outputs JSON-serializable (asserted in tests)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py
import json, pandas as pd
from parrot.outputs.a2ui.recipes.transformers import TransformerRegistry

def test_library_golden_day_totals(budget_variance_frames):
    fn = TransformerRegistry.get("day_totals").func
    out = fn({"snapshots": budget_variance_frames}, {"snapshot_col": "snapshot"})
    assert out == json.load(open(GOLDEN / "day_totals.json"))

def test_outputs_are_json_serializable(): ...
def test_variance_pct_zero_budget_guard(): ...
```

---

## Agent Instructions

1. **Read the spec** and `sdd/artifacts/executive_summary.py` in full before porting
2. **Check dependencies** — TASK-1866 completed; read the real registry API it produced
3. **Verify the Codebase Contract**
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
