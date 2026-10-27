# TASK-4845: Flex kpi-table.md importer

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4843
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (importer half) and §7 "`kpi-table.md` import mapping". The only KPI→shape catalog
today is a prose Markdown table for the Flex `/widget` skill. This one-shot importer turns its 12 rows
into `RecipeSource` definitions. Open question Q5 took the spec default: the Proximity Staffing row is
**kept** (MapShape + description note).

---

## Scope

- Implement `KpiTableRow`, `parse_kpi_table`, `import_kpi_table` in `parrot/metrics/importers.py`.
- Commit a fixture copy of the Flex table at `tests/unit/metrics/fixtures/kpi-table.md`.
- Write `test_importers.py`.

**NOT in scope**: a CLI wrapper, persisting the result (callers use `seed_store`, TASK-4844),
editing `parrot/metrics/__init__.py` (lazy map already lists these names).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/metrics/importers.py` | CREATE | GFM table parser + converter |
| `packages/ai-parrot/tests/unit/metrics/fixtures/kpi-table.md` | CREATE | Verbatim copy of the Flex table |
| `packages/ai-parrot/tests/unit/metrics/test_importers.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.metrics.models import (MetricDefinition, RecipeSource, KPICardShape, ChartShape, DataTableShape,
                                   MapShape, TimeSpec, PeriodBinding, DimensionSpec)   # created by TASK-4843
from pydantic import BaseModel, ConfigDict
```

### Existing Signatures to Use
```text
./agents/flex_dashboard/skills/widget/kpi-table.md   — local, git-ignored (agent dirs are not in git).
Header (verbatim): | KPI | Transformer | Dataset alias(es) | Recipe path | Output mode | Supported filters |
Cells use backticks around identifiers (`payroll_hero`, `/payroll_hero/worked_hours_total`, `KPICard` hero).
```

### Does NOT Exist
- ~~`agents/flex_dashboard/skills/widget/kpi-table.md` in git~~ — git-ignored; tests use the committed fixture.
- ~~A markdown-table parser utility in parrot~~ — write a small one (split on `|`, skip separator row).
- ~~`RecipeRunner` calls here~~ — the importer is pure; no I/O beyond the string it is given.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/metrics/importers.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/fixtures/kpi-table.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/test_importers.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes (spec §7, binding)

- `id` = slugified KPI: lower, non-alnum → `_`, collapse/strip `_`, truncated to 63 (`Worked Hours (total)` → `worked_hours_total`).
- `source = RecipeSource(recipe_name=<arg>, recipe_owner=<arg>, data_model_path=<Recipe path, backticks stripped>, param_map={f: f for f in filters})`.
- Output mode → shape: `KPICard hero` → `KPICardShape(value_column="value", aggregate="none")`;
  `STRUCTURED_CHART` → `ChartShape(chart_type="line", x="month", y=["value"])`;
  `STRUCTURED_TABLE` → `DataTableShape(columns=[])`; `STRUCTURED_MAP` → `MapShape(lat="lat", lon="lon")`.
- `Supported filters` minus `period_param` (default `month`) → `dimensions` (`DimensionSpec(name=f.replace("_"," "), column=f)`);
  when `month` is present → `TimeSpec(binding=PeriodBinding(start_placeholder="month", end_placeholder="month"))`;
  when absent → `TimeSpec(binding=PeriodBinding(date_column="month"))` — FILL IN decision, record in Completion Note.
- `description` records transformer + dataset aliases for lineage ("Imported from kpi-table.md; transformer=…; datasets=…").
- Recipe path with `{…}` (Proximity Staffing): keep, use `/proximity_staffing/coverage` as `data_model_path`, MapShape, and append a description note.
- Never copy any tenant into `QuerySlugSource.tenant` (R6) — not applicable here, recipe source only.
- Unknown output mode → `ValueError` naming the row (fail loud; the table is curated).

---

## Implementation Blueprint

### Steps (in order)
1. Create the fixture: `cp agents/flex_dashboard/skills/widget/kpi-table.md packages/ai-parrot/tests/unit/metrics/fixtures/kpi-table.md` if the local file exists; otherwise write the table text below verbatim — *why*: the agent dir is git-ignored, tests need a committed copy.
2. Write `importers.py`.
3. Write tests; run validation.

### `packages/ai-parrot/tests/unit/metrics/fixtures/kpi-table.md` (CREATE)
```markdown
# Flex KPI → transformer → output mode reference

| KPI | Transformer | Dataset alias(es) | Recipe path | Output mode | Supported filters |
|---|---|---|---|---|---|
| Worked Hours (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/worked_hours_total` | `KPICard` hero | month, pay_code, cost_center |
| Payroll (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/payroll_total` | `KPICard` hero | month, pay_code, cost_center |
| P&L Revenue (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/revenue_total` | `KPICard` hero | month |
| Payroll % to Revenue (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/payroll_pct` | `KPICard` hero | month |
| Worked Hours by Month | `worked_hours_by_month` | `hours` | `/worked_hours_by_month/series` | `STRUCTURED_CHART` | month, pay_code, cost_center |
| Payroll by Month | `payroll_by_month` | `finance` | `/payroll_by_month/series` | `STRUCTURED_CHART` | month |
| P&L Revenue by Month | `revenue_by_month` | `finance` | `/revenue_by_month/series` | `STRUCTURED_CHART` | month |
| Payroll % to Revenue by Month | `payroll_pct_by_month` | `finance` | `/payroll_pct_by_month/series` | `STRUCTURED_CHART` | month |
| Pay Code Hours | `pay_code_hours` | `hours` | `/pay_code_hours/records` | `STRUCTURED_TABLE` | month, pay_code, cost_center |
| Worked Hours by Pay Code Allocation | `pay_code_allocation` | `hours` | `/pay_code_allocation/records` | `STRUCTURED_TABLE` | month, pay_code, cost_center |
| Rep Utilization by Region | `rep_utilization_by_region` | `rep_utilization`, `region_utilization` | `/rep_utilization_by_region/records` | `STRUCTURED_TABLE` | month, category |
| Proximity Staffing | `proximity_staffing` | `msl`, `employees` | `/proximity_staffing/{store_layer,employee_layer,coverage}` | `STRUCTURED_MAP` | flex_type, radius_miles, nearest_n |
```
(When copying the real file, keep its full text — header notes included — the parser must ignore non-table lines.)

### `packages/ai-parrot/src/parrot/metrics/importers.py` (CREATE)
```python
"""Flex ``kpi-table.md`` → recipe-sourced ``MetricDefinition`` importer (FEAT-756 M2)."""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from parrot.metrics.models import (ChartShape, DataTableShape, DimensionSpec, KPICardShape, MapShape,
                                   MetricDefinition, PeriodBinding, RecipeSource, TimeSpec)

KPI_TABLE_HEADER = ["KPI", "Transformer", "Dataset alias(es)", "Recipe path", "Output mode", "Supported filters"]


class KpiTableRow(BaseModel):
    """One row of the Flex ``kpi-table.md`` table: kpi, transformer, dataset_aliases, recipe_path, output_mode, filters."""
    model_config = ConfigDict(extra="forbid")
    kpi: str
    transformer: str
    dataset_aliases: list[str]
    recipe_path: str
    output_mode: str
    filters: list[str]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _unquote(cell: str) -> str:
    return cell.replace("`", "").strip()


def _slugify(text: str) -> str:
    # FILL IN: lower; re.sub(r"[^a-z0-9]+", "_"); strip "_"; [:63]; must match MetricId pattern
    raise NotImplementedError


def parse_kpi_table(markdown: str) -> list[KpiTableRow]:
    """Parse the 6-column GFM table (header ``| KPI | Transformer | Dataset alias(es) | Recipe path | Output mode | Supported filters |``)."""
    # FILL IN: locate the header line whose _cells == KPI_TABLE_HEADER (ValueError if absent); skip the
    #          separator row; consume subsequent "|"-lines until a non-table line; aliases/filters split on ",";
    #          strip backticks in every cell; output_mode keeps the words ("KPICard hero").
    raise NotImplementedError


def _shape_for(mode: str):
    # FILL IN: map per Implementation Notes; normalise via mode.replace("`","").strip(); unknown → ValueError
    raise NotImplementedError


def import_kpi_table(markdown: str, *, recipe_name: str, recipe_owner: str | None, tenant: str | None,
                     program: str | None = None, period_param: str = "month") -> list[MetricDefinition]:
    """Convert rows to ``RecipeSource`` definitions: ``KPICard hero`` → ``KPICardShape``, ``STRUCTURED_CHART`` →
    ``ChartShape(line)``, ``STRUCTURED_TABLE`` → ``DataTableShape``, ``STRUCTURED_MAP`` → ``MapShape``; the
    ``Supported filters`` cell becomes ``dimensions`` (minus the period filter, which becomes ``TimeSpec``)."""
    # FILL IN: per row build MetricDefinition(id=_slugify(kpi), name=kpi, tenant=tenant, program=program,
    #          description=lineage text, aliases=[] , time=..., default_shape=_shape_for(...),
    #          source=RecipeSource(...), visibility="tenant" if tenant else "public")
    #          — "{…}" recipe paths handled per Implementation Notes.
    raise NotImplementedError
```
**Why**: spec §7 fixes the mapping; only parsing robustness and the "no month filter" binding are judgement.
`visibility`: a global (tenant=None) import must not be `"tenant"` (the Postgres CHECK in TASK-4848 forbids it).

### FILL IN checklist
- [ ] `_slugify`, `parse_kpi_table`, `_shape_for`, `import_kpi_table`
- [ ] binding when `month` is absent (record choice)
- [ ] tests

---

## Acceptance Criteria

- [ ] `parse_kpi_table(fixture)` → 12 rows; backticks stripped.
- [ ] `import_kpi_table` → 12 definitions; ids unique and pattern-valid; KPICard rows → `KPICardShape`, map row → `MapShape`, chart rows → `ChartShape(line)`, table rows → `DataTableShape`.
- [ ] `worked_hours_total` has dimensions `pay_code`, `cost_center` (no `month`) and a `month` placeholder binding.
- [ ] Every definition round-trips `model_dump(mode="json")`.
- [ ] Missing header → `ValueError`.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/metrics/test_importers.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/metrics/test_importers.py
from pathlib import Path
import pytest
from parrot.metrics.importers import import_kpi_table, parse_kpi_table
from parrot.metrics.models import KPICardShape, MapShape

FIXTURE = Path(__file__).parent / "fixtures" / "kpi-table.md"

@pytest.fixture
def kpi_table_markdown() -> str:
    return FIXTURE.read_text()

def test_parse_kpi_table_twelve_rows(kpi_table_markdown): ...      # FILL IN
def test_import_kpi_table_twelve_rows(kpi_table_markdown): ...     # FILL IN shapes + dimensions minus month
def test_proximity_row_kept_as_map(kpi_table_markdown): ...        # FILL IN
def test_missing_header_raises(): ...                              # FILL IN
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4843 is `done`.
2. Verify contract; mark in-progress; implement; validate with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only listed files; `scripts/sdd/close_task.sh TASK-4845 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
