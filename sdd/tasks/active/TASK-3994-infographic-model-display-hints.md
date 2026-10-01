# TASK-3994: Infographic model display hints (optional fields)

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The infographic block models cannot carry the display hints
that the A2UI wire already accepts (`DataTable.columns[].type/format`,
`Chart.seriesAxes/yAxisLabels`, `KPICard.format/unit`). This task adds them as
**optional** fields. Every other FEAT-623 task reads these fields: the
adapter (TASK-3995), the HTML lane (TASK-3997), the toolkit (TASK-4000), the
prompts and the walkthrough. So this is the root of the task graph.

---

## Scope

- Add `type` and `format` to `ColumnDef`, both `Optional[str]` using the
  `TableColumn` vocabulary.
- Add `axis: Optional[SeriesAxis]` to `ChartDataSeries`.
- Add `y_axis_labels: Optional[List[Optional[str]]]` to `ChartBlock`.
- Widen `HeroCardBlock.value` to `Union[str, int, float]`, and add
  `format: Optional[Literal["percent", "currency", "number"]]` and
  `unit: Optional[str]`.
- Write unit tests proving that the new fields validate, that old payloads
  are unchanged, and that the record-shape normalizers pass the new keys
  through.

**NOT in scope**:
- The adapter mapping (TASK-3995).
- HTML rendering (TASK-3997).
- The toolkit dtype map (TASK-4000).
- Prompt text (M7 task).
- Changing either normalizer's logic. They already pass `ColumnDef` dicts
  and series dicts through untouched (see Codebase Contract); this task only
  pins that with tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | optional hint fields on `ColumnDef`, `ChartDataSeries`, `ChartBlock`, `HeroCardBlock` |
| `packages/ai-parrot/tests/unit/models/test_infographic_display_hints.py` | CREATE | unit tests for the new fields + old-payload invariance |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import SeriesAxis  # verified: packages/ai-parrot/src/parrot/models/outputs.py:329  (SeriesAxis = Literal["left", "right"])
# No import cycle: models/outputs.py imports only stdlib, pydantic and `.basic` (outputs.py:1-6);
# models/infographic.py already imports it lazily inside ChartBlock.to_chart_config (:659).
from parrot.models.infographic import ColumnDef, ChartDataSeries, ChartBlock, HeroCardBlock, TableBlock, InfographicResponse
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/infographic.py
from typing import (List, Optional, Any, Annotated, ClassVar, Dict, Literal, Tuple, Union)  # :26-35
from pydantic import (AfterValidator, BaseModel, Discriminator, Field, ...)                # :40

class ColumnDef(BaseModel):                                   # :204
    header: str                                               # :207
    width: Optional[str]                                      # :208
    align: Optional[Literal["left", "center", "right"]]       # :209
    color: Optional[str] = Field(None, description="Accent color for the column header")  # :210
    # _validate_color field_validator("color")                # :212-216

class HeroCardBlock(BaseModel):                               # :327
    type: Literal["hero_card"] = "hero_card"
    label: str                                                # :331
    value: str = Field(                                       # :335
        "",
        description="Formatted metric value (e.g., '$1.2M', '98%')",   # :337
    )
    icon; trend; trend_value; comparison_period               # :339-342
    color: Optional[str] = Field(None, description="Accent color for this card (CSS color value)")  # :343

class ChartDataSeries(BaseModel):                             # :497
    name: str                                                 # :500
    values: List[Union[int, float, None]] = Field(..., description="Data values corresponding to labels")  # :501
    color: Optional[str] = Field(None, description="Series color")  # :502

class ChartBlock(BaseModel):                                  # :511
    y_axis_label: Optional[str] = Field(None, description="Y-axis label")  # :521
    # _normalize_chart_data @model_validator(mode="before")   # :583-647 — series dicts are mutated
    #   in place (data→values) and otherwise left alone, so an "axis" key survives.

class TableBlock(BaseModel):                                  # :749
    columns: Union[List[str], List[ColumnDef]]                # :754
    # _normalize_table_data @model_validator(mode="before")   # :767-814 — when cols[0] is a dict
    #   with "header", columns are left AS-IS (:803-807), so "type"/"format" keys survive.
```

### Does NOT Exist
- ~~`ColumnDef.type` / `ColumnDef.format`~~ — added by this task.
- ~~`ChartDataSeries.axis`~~ — added by this task.
- ~~`ChartBlock.y_axis_labels`~~ — only the singular `y_axis_label` exists today.
- ~~`HeroCardBlock.format` / `HeroCardBlock.unit`~~ — added by this task.
- ~~A `compact` value in any `format` Literal~~ — deliberately not added (spec Non-Goals).
- ~~`parrot.models.infographic.SeriesAxis`~~ — `SeriesAxis` lives in `parrot.models.outputs`. Import it; do not redeclare.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/models/infographic.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/models/test_infographic_display_hints.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/infographic.py#ColumnDef",
    "sym:packages/ai-parrot/src/parrot/models/infographic.py#HeroCardBlock",
    "sym:packages/ai-parrot/src/parrot/models/infographic.py#ChartDataSeries",
    "sym:packages/ai-parrot/src/parrot/models/infographic.py#ChartBlock",
    "sym:packages/ai-parrot/src/parrot/models/infographic.py#TableBlock",
    "sym:packages/ai-parrot/src/parrot/models/outputs.py#SeriesAxis"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Additive only.** Every new field defaults to `None`. Existing payloads
  (str hero values, `List[str]` columns, series without `axis`) must
  validate and `model_dump` to the same dict as before, **apart from**
  the new `None` keys.
- Field descriptions are LLM-facing. State the ratio rule explicitly, as in
  `catalog/parrot/kpicard.py` `format`: "send a ratio as 0.683 with
  format='percent', never as '68.3%'".
- `HeroCardBlock.value` is `Union[str, int, float]`, not the spec's
  `Union[str, float]`. Under pydantic v2 smart unions, `float` alone turns an
  int `1903` into `1903.0`, which renders as "1903.0" wherever no `format`
  is declared. Keeping `int` preserves integers. This is a deliberate,
  documented refinement of spec §2 Data Models.

---

## Implementation Blueprint

### Steps (in order)
1. Add the module-level import of `SeriesAxis` — *why*: the axis Literal must
   be the SAME type the wire model uses, so the two can never drift.
2. Add `type` and `format` after `ColumnDef.color` — *why*: they mirror
   `TableColumn` so the adapter can forward them 1:1 (TASK-3995).
3. Widen `HeroCardBlock.value`, then add `format` and `unit` — *why*: this
   follows FEAT-611's KPICard rule (number plus format, never a
   pre-formatted string).
4. Add `ChartDataSeries.axis` and `ChartBlock.y_axis_labels` — *why*: they
   map to `Chart.seriesAxes` / `yAxisLabels`.
5. Write the tests — *why*: they pin the additive guarantee and the
   normalizer pass-through.

### `packages/ai-parrot/src/parrot/models/infographic.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -cF 'from pydantic import (' packages/ai-parrot/src/parrot/models/infographic.py)
# BEFORE — insert above `from pydantic import (` (verified: packages/ai-parrot/src/parrot/models/infographic.py:40)
from parrot.models.outputs import SeriesAxis
```
**Why**: module-level import is safe because `models/outputs.py` never imports
`models/infographic.py` (outputs.py:1-6).
FILL IN: if `import parrot.models.infographic` then raises an ImportError
cycle, fall back to `SeriesAxis = Literal["left", "right"]  # mirrors
parrot/models/outputs.py:329` — bounded by the spec §7 "Import cycle" note.

### `packages/ai-parrot/src/parrot/models/infographic.py` (MODIFY) — ColumnDef
```python
# occurrences: 1 (verified: grep -cF 'color: Optional[str] = Field(None, description="Accent color for the column header")' packages/ai-parrot/src/parrot/models/infographic.py)
# AFTER — insert below `color: Optional[str] = Field(None, description="Accent color for the column header")` (verified: :210)
    type: Optional[str] = Field(
        None,
        description=(
            "Storage type (TableColumn.type vocabulary): string | integer | number | "
            "boolean | date | datetime | time | duration | any."
        ),
    )
    format: Optional[str] = Field(
        None,
        description=(
            "Display hint (TableColumn.format vocabulary): currency | percent | email | uri | "
            "enum | id | code. percent means a RATIO: send 0.683, never '68.3%'."
        ),
    )
```

### `packages/ai-parrot/src/parrot/models/infographic.py` (MODIFY) — HeroCardBlock
```python
# occurrences: 1 (verified: grep -cF '    value: str = Field(' packages/ai-parrot/src/parrot/models/infographic.py)
# REPLACE the 4-line field starting at `    value: str = Field(` (verified: :335-338) with:
    value: Union[str, int, float] = Field(
        "",
        description=(
            "A formatted string ('$1.2M') renders verbatim; a number is formatted per "
            "`format` (send a ratio as 0.683 with format='percent')."
        ),
    )
# occurrences: 1 (verified: grep -cF 'color: Optional[str] = Field(None, description="Accent color for this card (CSS color value)")' ...)
# AFTER — insert below that `color` line (verified: :343)
    format: Optional[Literal["percent", "currency", "number"]] = Field(
        None, description="Display hint for a NUMERIC value only; percent = ratio (0.683)."
    )
    unit: Optional[str] = Field(None, description="Appended after a space unless format='percent'.")
```

### `packages/ai-parrot/src/parrot/models/infographic.py` (MODIFY) — ChartDataSeries / ChartBlock
```python
# occurrences: 1 (verified: grep -cF 'color: Optional[str] = Field(None, description="Series color")' ...)
# AFTER — insert below `color: Optional[str] = Field(None, description="Series color")` (verified: :502)
    axis: Optional[SeriesAxis] = Field(
        None, description="'right' puts this series on a second value axis; default left."
    )
# occurrences: 1 (verified: grep -cF 'y_axis_label: Optional[str] = Field(None, description="Y-axis label")' ...)
# AFTER — insert below `y_axis_label: Optional[str] = Field(None, description="Y-axis label")` (verified: :521)
    y_axis_labels: Optional[List[Optional[str]]] = Field(
        None, description="[left, right] axis names when any series sets axis='right'."
    )
```

### `packages/ai-parrot/tests/unit/models/test_infographic_display_hints.py` (CREATE)
```python
"""FEAT-623 TASK-3994: optional display hints on the infographic block models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.models.infographic import (
    ChartBlock,
    ColumnDef,
    HeroCardBlock,
    InfographicResponse,
    TableBlock,
)


def test_columndef_accepts_type_format():
    col = ColumnDef(header="MRR", type="number", format="currency")
    assert (col.type, col.format) == ("number", "currency")


def test_columndef_old_payload_unchanged():
    assert ColumnDef(header="A").model_dump(exclude_none=True) == {"header": "A"}


def test_hero_value_str_or_number():
    assert HeroCardBlock(label="R", value="$1.2M").value == "$1.2M"
    assert HeroCardBlock(label="R", value=1903).value == 1903          # int stays int
    assert isinstance(HeroCardBlock(label="R", value=1903).value, int)
    assert HeroCardBlock(label="R", value=0.683, format="percent").format == "percent"


def test_hero_format_rejects_compact():
    with pytest.raises(ValidationError):
        HeroCardBlock(label="R", value=1, format="compact")


def test_series_axis_literal():
    # FILL IN: build a ChartBlock with series [{"name","values","axis":"right"}] and
    # y_axis_labels=["USD", "USD (new)"]; assert axis=="right" and that axis="middle"
    # raises ValidationError — bounded by SeriesAxis = Literal["left","right"].
    ...


def test_normalizers_pass_new_keys_through():
    # FILL IN: (a) TableBlock(columns=[{"header":"MRR","type":"number","format":"currency"}],
    # rows=[[1.0]]) keeps type/format; (b) ChartBlock from records `data=[{...}]` still
    # validates; (c) series given as {"name","data":[...],"axis":"right"} keeps axis
    # after the data→values rename — bounded by AC-3.
    ...


def test_old_infographic_payload_dump_unchanged():
    # FILL IN: an InfographicResponse with a str hero, List[str] table columns and a
    # series without axis; its model_dump(exclude_none=True) must equal the same dump
    # computed from the identical payload (no new non-None keys appear) — bounded by AC-2.
    ...
```
**Why this shape**: each test pins one guarantee from spec §5 "Additive
models". The `...` bodies are FILL IN stubs: replace every one, and leave
no `...` behind.

### FILL IN checklist
- [ ] `infographic.py` import: cycle fallback, only if the import actually fails.
- [ ] `test_series_axis_literal`: the right-axis case passes and the invalid literal raises.
- [ ] `test_normalizers_pass_new_keys_through`: all three shapes are covered.
- [ ] `test_old_infographic_payload_dump_unchanged`: written and green.

---

## Acceptance Criteria

- [ ] AC-1: `ColumnDef.type/format`, `ChartDataSeries.axis`, `ChartBlock.y_axis_labels`, `HeroCardBlock.format/unit` exist, all default `None`.
- [ ] AC-2: every pre-existing payload validates. Its `model_dump(exclude_none=True)` is unchanged.
- [ ] AC-3: `TableBlock` / `ChartBlock` normalizers keep `type`/`format`/`axis` keys.
- [ ] AC-4: `HeroCardBlock.value` keeps a str verbatim and an int as int. `format` rejects anything outside `percent|currency|number`.
- [ ] AC-5: the existing adapter and build_block suites still pass, with no change to their files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/models/test_infographic_display_hints.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py -q`
- `pytest packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py -q`
- `pytest tests/test_infographic_models.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug infographic-a2ui-display-hints --feature-id FEAT-623`).
2. Read the spec. Re-run every `grep -cF` above before editing.
3. Implement from the blueprint, complete every FILL IN, and run the Validation Commands.
4. Commit only the two listed files. Close with `scripts/sdd/close_task.sh TASK-3994 infographic-a2ui-display-hints verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `HeroCardBlock.value` is `Union[str, int, float]` (spec §2 said `str | float`) to keep integers integral. This was decided at task time.
