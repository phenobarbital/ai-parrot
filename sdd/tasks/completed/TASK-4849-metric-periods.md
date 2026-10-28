# TASK-4849: Metric periods — preset resolution, comparison window, series buckets

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4843
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7 (periods half) and the binding §7 "Period resolution" table. Creates the
`parrot_tools.metrics` package (lazy export map) that TASK-4850/4851/4852 build on. `ResolvedPeriod`,
`ComparisonPolicy`, `PeriodPreset` and `Grain` come from `parrot.metrics.models` (TASK-4843).

---

## Scope

- Create `parrot_tools/metrics/__init__.py` with a LAZY `__getattr__` export map covering every public name of the
  package (including names later tasks create). Later tasks never edit this file.
- Implement `resolve_period`, `comparison_period`, `series_buckets` in `periods.py`.
- Write `tests/metrics/test_periods.py`.

**NOT in scope**: shapes/KPI figures (TASK-4850), executors (TASK-4851), toolkit (TASK-4852), `TOOL_REGISTRY` (TASK-4856).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/metrics/__init__.py` | CREATE | Lazy export map |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/periods.py` | CREATE | Period resolution |
| `packages/ai-parrot-tools/tests/metrics/test_periods.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.metrics.models import ResolvedPeriod, ComparisonPolicy, PeriodPreset, Grain   # created by TASK-4843 (spec §2 Data Models)
from datetime import date, timedelta
import calendar
```

### Existing Signatures to Use
```python
# parrot/metrics/models.py (TASK-4843)
class ResolvedPeriod(BaseModel):   # extra="forbid"
    preset: PeriodPreset; start: date; end: date; label: str; udf_keywords: dict[str, str] | None = None
class ComparisonPolicy(BaseModel):
    mode: Literal["previous_period", "same_period_last_year", "none"] = "previous_period"; label: str | None = None
PeriodPreset = Literal["today","yesterday","this_week","last_week","this_month","last_month","mtd","qtd","ytd",
                       "last_7d","last_30d","last_90d","this_year","last_year"]
Grain = Literal["day","week","month","quarter","year"]
```
QuerySource UDF vocabulary (closed, `parrot_tools/querysource/toolkit.py:369-370` docstring): TODAY, YESTERDAY,
FDOM, LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR.

### Does NOT Exist
- ~~`parrot_tools.metrics`~~ — created by this task.
- ~~A UDF keyword for "previous month", "last 30 days", quarters or weeks~~ — not in the vocabulary.
- ~~`dateutil.relativedelta` usage elsewhere in this package~~ — use stdlib `calendar`/`timedelta`; do not add deps.
- ~~`parrot_tools/metrics/conftest.py` / `tests/metrics/conftest.py`~~ — deliberately none; each test file owns fixtures.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/metrics/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/metrics/periods.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/metrics/test_periods.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Pure, synchronous, deterministic functions; `today` injectable for tests (default `date.today()`).
- `udf_keywords` keys are the binding roles `"start"` / `"end"` (the executor maps them onto the binding's placeholders).
- Spec §7 table is binding:
  - `today`/`yesterday` → that day; `{start: TODAY, end: TODAY}` / `{start: YESTERDAY, end: YESTERDAY}`.
  - `this_month` → first..last day; `{start: FDOM, end: LDOM}`.
  - `mtd` → first day..today; `{start: FDOM, end: TODAY}`.
  - `ytd` → Jan 1..today; `this_year` → Jan 1..Dec 31; `{start: CURRENT_YEAR}` ONLY when `single_placeholder=True`, else `None`.
  - `last_year` → previous Jan 1..Dec 31; `{start: LAST_YEAR}` only when `single_placeholder=True`, else `None`.
  - every other preset → ISO dates only, `udf_keywords=None`. Weeks are ISO (Monday start).
- `comparison_period`: previous_period = same length ending the day before `start`; same_period_last_year = both
  bounds minus one year (Feb 29 → Feb 28); none → `None`. Result `udf_keywords=None` always (comparison is locked ISO).
- Labels: "October 2026", "last 30 days", "2026 YTD", ISO range "2026-09-01 – 2026-09-30" for comparison windows.

---

## Implementation Blueprint

### Steps (in order)
1. Create `__init__.py` with the lazy map — *why*: importing `parrot_tools.metrics` must not pull the a2ui/querysource chain.
2. Implement `periods.py` — *why*: every executor and the toolkit need concrete dates.
3. Write tests at `frozen_today = date(2026, 10, 27)` for every preset.

### `packages/ai-parrot-tools/src/parrot_tools/metrics/__init__.py` (CREATE)
```python
"""Metric registry tools (FEAT-756): periods, shape emitter, source executors and MetricsToolkit."""
from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "MetricsToolkit": ".toolkit",
    "QueryMetricResult": ".models",
    "MetricSummary": ".models",
    "MetricExplanation": ".models",
    "resolve_period": ".periods",
    "comparison_period": ".periods",
    "series_buckets": ".periods",
    "KPIFigures": ".shapes",
    "aggregate": ".shapes",
    "figures": ".shapes",
    "kpicard_props": ".shapes",
    "build_metric_envelope": ".shapes",
    "build_linked_metric_envelope": ".shapes",
    "SourceFrame": ".executors",
    "executor_for": ".executors",
    "QuerySlugExecutor": ".executors",
    "TransformerExecutor": ".executors",
    "RecipeExecutor": ".executors",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Resolve public names lazily from their submodule."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value
```
**Why this shape**: one file owned by this task, so TASK-4850/4851/4852 never overlap on it (no file-overlap edges).

### `packages/ai-parrot-tools/src/parrot_tools/metrics/periods.py` (CREATE)
```python
"""Period presets → concrete date windows (spec §7 'Period resolution', binding)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from parrot.metrics.models import ComparisonPolicy, Grain, PeriodPreset, ResolvedPeriod


def resolve_period(
    preset: PeriodPreset, *, today: date | None = None, grain: Grain = "month", single_placeholder: bool = False
) -> ResolvedPeriod:
    """Concrete inclusive ``start``/``end`` for ``preset``; ``udf_keywords`` only for expressible presets."""
    today = today or date.today()
    # FILL IN: one branch per PeriodPreset — bounded by the §7 table in Implementation Notes; unknown → ValueError
    raise NotImplementedError


def comparison_period(period: ResolvedPeriod, policy: ComparisonPolicy) -> ResolvedPeriod | None:
    """previous_period → same length right before; same_period_last_year → shifted one year; none → ``None``."""
    # FILL IN: three modes — bounded by Implementation Notes; udf_keywords always None; label = policy.label or ISO range
    raise NotImplementedError


def series_buckets(period: ResolvedPeriod, grain: Grain) -> list[date]:
    """Sorted bucket start dates covering ``period`` at ``grain`` (zero-fill skeleton for KPICard ``series``)."""
    # FILL IN: day/week(ISO Monday)/month/quarter/year starts within [start, end] — bounded by test_series_buckets
    raise NotImplementedError
```
**Why this shape**: signatures fixed by spec M7 skeleton; `single_placeholder` is the one addition needed to honour
the §7 ytd/this_year/last_year rule (single-placeholder bindings only).

### FILL IN checklist
- [ ] `resolve_period` — 14 presets; bounded by §7 table
- [ ] `comparison_period` — 3 modes; leap-day safe
- [ ] `series_buckets` — 5 grains

---

## Acceptance Criteria

- [ ] Every preset resolves at `date(2026, 10, 27)` to the expected window.
- [ ] `udf_keywords` set only for today, yesterday, this_month, mtd, and (single placeholder) ytd/this_year/last_year.
- [ ] `comparison_period` handles all three modes; `None` for `none`.
- [ ] `import parrot_tools.metrics` imports no a2ui / querysource module (`sys.modules` check).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/metrics/` clean.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/metrics/test_periods.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/metrics/test_periods.py
from datetime import date
import pytest
from parrot.metrics.models import ComparisonPolicy
from parrot_tools.metrics.periods import comparison_period, resolve_period, series_buckets

TODAY = date(2026, 10, 27)

@pytest.mark.parametrize("preset,start,end", [
    ("this_month", date(2026, 10, 1), date(2026, 10, 31)),
    ("last_month", date(2026, 9, 1), date(2026, 9, 30)),
    ("mtd", date(2026, 10, 1), TODAY),
    ("last_7d", date(2026, 10, 21), TODAY),
    # FILL IN: remaining presets
])
def test_resolve_period_presets(preset, start, end):
    p = resolve_period(preset, today=TODAY)
    assert (p.start, p.end) == (start, end)

def test_udf_keywords_only_expressible():
    assert resolve_period("this_month", today=TODAY).udf_keywords == {"start": "FDOM", "end": "LDOM"}
    assert resolve_period("last_month", today=TODAY).udf_keywords is None
    assert resolve_period("ytd", today=TODAY).udf_keywords is None
    assert resolve_period("ytd", today=TODAY, single_placeholder=True).udf_keywords == {"start": "CURRENT_YEAR"}

def test_comparison_period_modes():
    cur = resolve_period("this_month", today=TODAY)
    prev = comparison_period(cur, ComparisonPolicy(mode="previous_period"))
    assert prev.end == date(2026, 9, 30)
    assert comparison_period(cur, ComparisonPolicy(mode="none")) is None
    # FILL IN: same_period_last_year

def test_series_buckets_day():
    p = resolve_period("last_7d", today=TODAY)
    assert len(series_buckets(p, "day")) == 7
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug metric-definition-registry --feature-id FEAT-756`).
2. Confirm TASK-4843 is `done` in `sdd/tasks/index/metric-definition-registry.json`.
3. Verify the contract (`parrot/metrics/models.py` field names) before coding.
4. Mark in-progress, implement the blueprint, run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
5. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4849 metric-definition-registry verified`.

---

## Completion Note

Seat qwen (nova), 1 attempt. Ledger hook had swept sdd/ledger/events.jsonl into the coder commit; reverted on the attempt branch. Engine task-tier validation was unavailable (attempt had no execution_id), so the branch was merged manually (--no-ff) and validated at merge tier: green (test_periods 24 passed).
