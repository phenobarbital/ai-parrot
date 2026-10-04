# TASK-3843: ECharts pie/donut slices carry {name, value}

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (FEAT-610). `EChartsRenderer._build_option` emits pie series `data` as bare values
(`echarts.py:276-283`), so slices are unnamed. Funnel/treemap already use `{name, value}` (`echarts.py:537-543`).

---

## Scope

- For `chart_type in {"pie", "donut"}`, series `data` becomes `[{"name": row.get(x), "value": row.get(col)}]`,
  with a `None` name rendered as `"Unassigned"`. Keep the donut radius. Other chart types unchanged.
- New `test_echarts_pie_names.py`.

**NOT in scope**: the JS renderer in the example (TASK-3851); the admin-UI chart adapter.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py` | MODIFY | pie/donut slice data |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_pie_names.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified Imports
```python
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer   # echarts.py:107 (check sibling test_echarts.py for how it is instantiated)
```
### Existing Signatures to Use
```python
class EChartsRenderer(AbstractA2UIRenderer):                     # line 107
    def _build_option(self, props: dict[str, Any]) -> dict[str, Any]:   # line 192
        for index, col in enumerate(y_cols):                     # line 275
            values = [row.get(col) for row in rows if isinstance(row, dict)]   # line 276
            series_entry: dict[str, Any] = {                     # line 279
                "data": values,                                  # line 282
            if chart_type == "donut":                            # line 286
# funnel pattern, line 537:
            data = [{"value": row.get(first_col), "name": row.get(x)} for row in rows if isinstance(row, dict)]
```
### Does NOT Exist
- ~~A separate pie series builder~~ — pie goes through the generic series loop at :275.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_pie_names.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py#EChartsRenderer"
  ]
}
```

---

## Implementation Notes

- Parallelism: no dependency; only task touching a2ui_renderers/echarts.py.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Read `_build_option` from :192 to :300 to confirm `x`, `chart_type` and `rows` names.
2. In the loop, after `values = ...` (line 276), replace `values` for pie/donut — because ECharts shows slice labels from `name`.
3. Write the test (bar output unchanged, pie named, NULL → "Unassigned").

```python
# echarts.py — AFTER — insert below `            values = [row.get(col) for row in rows if isinstance(row, dict)]` (verified: echarts.py:276)
# occurrences: FILL IN: disambiguate — grep -c this line; if > 1 anchor on the next line
#   `            mark = series_types[index] if index < len(series_types) and series_types[index] else chart_type`
            if chart_type in {"pie", "donut"}:
                values = [
                    {"name": "Unassigned" if row.get(x) is None else row.get(x), "value": row.get(col)}
                    for row in rows
                    if isinstance(row, dict)
                ]
```
**Why**: mirrors the funnel/treemap `{name, value}` shape; the NULL label matches spec §7 "NULL buckets".

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_pie_names.py — CREATE
"""FEAT-610 TASK-3843 — pie/donut slices carry names (AC4)."""

from __future__ import annotations

import pytest

from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer


@pytest.mark.parametrize("chart_type", ["pie", "donut"])
def test_pie_slices_have_names(chart_type: str) -> None:
    # FILL IN: build props with type=chart_type, x="course", y=["graduates"], data rows incl. a None course
    #   — follow the props shape used in test_echarts.py; assert series[0]["data"] == [{name, value}, ...]
    #   and the None row is named "Unassigned".
    ...


def test_bar_series_unchanged() -> None:
    # FILL IN: bar chart data stays a plain value list.
    ...
```
**FILL IN checklist**
- [ ] anchor occurrence count.
- [ ] renderer construction + props shape copied from `test_echarts.py`.

---

## Acceptance Criteria

- [ ] pie/donut series data is `{name, value}`; `None` → `"Unassigned"` (AC4).
- [ ] bar/line output unchanged; existing echarts tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_pie_names.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_props.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_pie_slices_have_names[pie|donut]` | AC4 |
| `test_bar_series_unchanged` | regression |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3843 — ECharts pie/donut slices carry {name, value}`.
5. Close with `scripts/sdd/close_task.sh TASK-3843 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Tokens: n/a

Pie/donut series now {name,value}; None -> 'Unassigned'. echarts tests 38 passed. Lint residual B905 zip() at echarts.py:502 is pre-existing style debt (left for /sdd-done). Merge-tier sweep skipped (env-red, see TASK-3842).
