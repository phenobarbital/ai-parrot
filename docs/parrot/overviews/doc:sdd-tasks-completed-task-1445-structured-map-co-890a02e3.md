---
type: Wiki Overview
title: 'TASK-1445: Structured map contract models'
id: doc:sdd-tasks-completed-task-1445-structured-map-contract-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundational module (spec §2 Data Models, §3 Module 1). Adds the
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1445: Structured map contract models

**Feature**: FEAT-221 — Structured Map Output Mode (`STRUCTURED_MAP`)
**Spec**: `sdd/specs/structured-map-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundational module (spec §2 Data Models, §3 Module 1). Adds the
`STRUCTURED_MAP` output mode and the framework-agnostic config models that the
renderer (TASK-1449) and `PandasAgent` wiring (TASK-1450) consume. These models
mirror the existing structured family (`StructuredTableConfig` / `TableColumn`)
so the frontend treats chart/table/map uniformly (G1).

---

## Scope

- Add `STRUCTURED_MAP = "structured_map"` to `OutputMode` in
  `packages/ai-parrot/src/parrot/models/outputs.py`.
- Add Pydantic models mirroring `StructuredTableConfig`:
  - `MapColumn` — `name/type/title/format` (same vocabulary as `TableColumn`).
  - `MapLayer` — `layer`, `columns: List[MapColumn]`, `tooltip_template`,
    `label_field`, `data_shape: Literal["geojson","rows"]`, `total_count`,
    `capped`, `geodesic` (`model_config = ConfigDict(populate_by_name=True)`).
  - `MapViewport` — `bbox: Optional[List[float]]`, `center: Optional[Tuple[float,float]]`, `zoom: Optional[int]`.
  - `MapQuery` — `point: Tuple[float,float]`, `radius: float`, `unit: Literal["mi","km","m"]`.
  - `StructuredMapConfig` — `layers: List[MapLayer]`, `data: List[dict]`
    (INPUT-ONLY, `default_factory=list`), `viewport`, `query`, `base_layer`,
    `title`, `description`, `explanation`; `populate_by_name=True`.
- Add a `model_validator(mode="after")` on `StructuredMapConfig` mirroring
  `StructuredTableConfig._validate_column_names`: when `data` is non-empty, every
  `layer.columns[*].name` must exist in `data[0].keys()`.

**NOT in scope**: the renderer (TASK-1449), `spatial_filter` changes (TASK-1446),
profile hints (TASK-1447), agent wiring (TASK-1450). Do NOT add a system prompt
here (it lives with the renderer).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | add `OutputMode.STRUCTURED_MAP` + the 5 models |
| `packages/ai-parrot/tests/models/test_structured_map_config.py` | CREATE | unit tests for the models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported at top of outputs.py — reuse, do not re-import duplicates:
from typing import List, Optional, Tuple, Literal  # outputs.py:2-12
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator  # outputs.py:18
from enum import Enum  # outputs.py:13
```

### Existing Signatures to Use (mirror these)
```python
# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):                       # line 39
    STRUCTURED_CHART = "structured_chart"          # line 72
    STRUCTURED_TABLE = "structured_table"          # line 73
    MAP = "map"                                    # line 59  (Folium — DO NOT reuse/confuse)

class TableColumn(BaseModel):                       # line 472
    name: str                                       # line 492
    type: str = Field(..., description="...")       # line 493  string|integer|number|boolean|date|datetime|time|duration|any
    title: str                                      # line 500
    format: Optional[str] = None                    # line 501  currency|percent|email|uri|enum|id|code

class StructuredTableConfig(BaseModel):             # line 509
    model_config = ConfigDict(populate_by_name=True)  # line 528
    columns: List[TableColumn]                      # line 530
    data: List[dict] = Field(default_factory=list)  # line 533  INPUT-ONLY
    explanation: Optional[str] = None               # line 540
    total_rows: Optional[int] = None                # line 544
    truncated: bool = False                         # line 548
    @model_validator(mode="after")
    def _validate_column_names(self):               # line 553
        if self.data:
            cols = set(self.data[0].keys())
            missing = [c.name for c in self.columns if c.name not in cols]
            if missing:
                raise ValueError(f"column names not present in data rows: {missing}")
        return self
```

### Does NOT Exist
- ~~`OutputMode.STRUCTURED_MAP`~~ — this task adds it.
- ~~`StructuredMapConfig` / `MapLayer` / `MapColumn` / `MapViewport` / `MapQuery`~~ — this task adds them.
- ~~a shared `BaseStructuredConfig`~~ — there is no shared base; each config is standalone. Mirror `StructuredTableConfig` directly.

---

## Implementation Notes

### Pattern to Follow
Copy `StructuredTableConfig` (outputs.py:509) and `TableColumn` (outputs.py:472)
structure verbatim, renaming and extending. Keep `populate_by_name=True` so the
frontend can send camelCase aliases if needed (add `alias=` on multi-word fields
like `data_shape`→`dataShape`, `tooltip_template`→`tooltipTemplate`,
`label_field`→`labelField`, `total_count`→`totalCount`, `base_layer`→`baseLayer`
— mirror how `StructuredChartConfig` uses `alias=` at outputs.py:340-366).

### Key Constraints
- `data` is INPUT-ONLY — the renderer will `model_dump(exclude={"data"})`. Do not
  add output-side logic here; just define the field.
- The column-name validator must use the union of ALL layers' columns against
  `data[0].keys()` ONLY if a single shared `data` list is used; since layers may
  carry their own payload via `response.data`, keep the validator lenient — match
  `StructuredTableConfig`'s behaviour (only validate when `data` non-empty).
- `MapColumn.type` accepts the SAME vocabulary string set as `TableColumn.type`.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/outputs.py:310` — `StructuredChartConfig` (alias usage).
- `packages/ai-parrot/src/parrot/models/outputs.py:472,509` — `TableColumn`, `StructuredTableConfig`.

---

## Acceptance Criteria

- [ ] `from parrot.models.outputs import OutputMode, StructuredMapConfig, MapLayer, MapColumn, MapViewport, MapQuery` works.
- [ ] `OutputMode.STRUCTURED_MAP.value == "structured_map"`.
- [ ] `StructuredMapConfig(...).model_dump(exclude={"data"})` omits `data` and keeps `layers`/`viewport`.
- [ ] Column-name validator raises when a column is absent from non-empty `data[0]`.
- [ ] `pytest packages/ai-parrot/tests/models/test_structured_map_config.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/models/outputs.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/models/test_structured_map_config.py
import pytest
from parrot.models.outputs import (
    OutputMode, StructuredMapConfig, MapLayer, MapColumn, MapViewport, MapQuery,
)


def test_output_mode_value():
    assert OutputMode.STRUCTURED_MAP.value == "structured_map"


def test_config_excludes_data():
    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="schools", columns=[MapColumn(name="name", type="string", title="Name")])],
        data=[{"name": "PS 1"}],
    )
    out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
    assert "data" not in out
    assert out["layers"][0]["layer"] == "schools"


def test_column_vocabulary_matches_table():
    col = MapColumn(name="price", type="number", title="Price", format="currency")
    assert col.format == "currency"


def test_validate_column_names():
    with pytest.raises(ValueError, match="not present in data rows"):
        StructuredMapConfig(
            layers=[MapLayer(layer="x", columns=[MapColumn(name="missing", type="string", title="M")])],
            data=[{"name": "PS 1"}],
        )
```

---

## Agent Instructions

1. Read the spec §2 Data Models and §3 Module 1.
2. Verify the contract anchors above with `grep`/`read` before editing.
3. Update index status → `in-progress`.
4. Implement; run the tests; `ruff check`.
5. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Added `OutputMode.STRUCTURED_MAP`, `MapColumn`, `MapLayer`, `MapViewport`,
`MapQuery`, and `StructuredMapConfig` to `packages/ai-parrot/src/parrot/models/outputs.py`.
Also added `Tuple` to the typing imports. All 18 unit tests pass. Pre-existing ruff
F401 errors (datetime, os, uuid) were NOT introduced by this task.
**Deviations from spec**: none
