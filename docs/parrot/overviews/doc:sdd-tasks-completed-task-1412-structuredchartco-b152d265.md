---
type: Wiki Overview
title: 'TASK-1412: `StructuredChartConfig` pydantic model + validators'
id: doc:sdd-tasks-completed-task-1412-structuredchartconfig-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Data Models + §3 Module 2. The agnostic chart contract that mirrors
  the frontend
relates_to:
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1412: `StructuredChartConfig` pydantic model + validators

**Feature**: FEAT-215 — Structured Chart Output Mode
**Spec**: `sdd/specs/structured-chart-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1411
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models + §3 Module 2. The agnostic chart contract that mirrors the frontend
`AppChartConfig` 1:1. The renderer (TASK-1413) validates the LLM JSON into this model and dumps
it for `response.output`. **Critical data-placement rule**: the model *accepts* `data` on input,
but `data` is **excluded from `output`** — rows are routed to `response.data` by the renderer.

---

## Scope

- Implement `StructuredChartConfig` (+ `ChartType`, `XAxisMode` Literals) in `models/outputs.py`,
  alongside the other output models (`ObjectDetectionResult`, `ImageGenerationPrompt`, …).
- camelCase serialization via per-field `alias` + `model_config = ConfigDict(populate_by_name=True)`.
- Model-level validators:
  - `type == "map"` requires `map_name` (else `ValidationError`).
  - every name in `y` (and `x`) must be a key present in `data` rows **when `data` is non-empty**.
- Unit tests for alias round-trip + validators.

**NOT in scope**: the enum (TASK-1411, dependency), the renderer/dump/`exclude={"data"}` wiring
and system prompt (TASK-1413), integration tests (TASK-1414). Do NOT add ISO-8601 *enforcement* as a
hard validator — date format is prompt-guidance, not a model constraint (see Implementation Notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | Add `ChartType`, `XAxisMode`, `StructuredChartConfig` |
| `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` | MODIFY | Add model tests (file created in TASK-1411) |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` 2026-06-02.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredChartConfig  # outputs.py (StructuredChartConfig added here)
from pydantic import BaseModel, Field, ConfigDict, model_validator    # pydantic v2 (already a core dep)
from typing import Literal, Optional, List
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/outputs.py
# Top of file already imports: from typing import (... Literal ...)  # lines 2-12
# from pydantic import BaseModel, Field  # line 18  → ADD ConfigDict, model_validator
# Existing output models follow the same home, e.g.:
class ObjectDetectionResult(BaseModel):   # line 208 (reference for placement & style)
class ImageGenerationPrompt(BaseModel):   # line 220
class SentimentAnalysis(BaseModel):       # line 267 (uses Literal[...] fields — pattern to copy)
```

### Frontend contract being mirrored (from spec §1 / brainstorm — NOT a code import)
```text
type: "bar"|"horizontalBar"|"line"|"area"|"scatter"|"pie"|"donut"|"radar"|"map"
x: str ; y: list[str]
stacked? trendline? splitSeries? showLegend? : bool
xAxisMode?: "category"|"time" ; palette?: list[str]
colorBySign?: bool ; negativeColor?: str ; mapName?: str   (camelCase = the alias names)
```

### Does NOT Exist
- ~~`ChartConfig` / `SeriesConfig` / `AppChartConfig`~~ — no prior structured-chart model in ai-parrot.
- ~~`parrot.models.chart` / a separate chart module~~ — the model lives in `models/outputs.py`.
- ~~a hard ISO-8601 validator~~ — date format is enforced via the system prompt (TASK-1413), not the model.

---

## Implementation Notes

### Pattern to Follow
```python
ChartType = Literal["bar", "horizontalBar", "line", "area", "scatter",
                    "pie", "donut", "radar", "map"]
XAxisMode = Literal["category", "time"]

class StructuredChartConfig(BaseModel):
    """Library-agnostic chart configuration mirroring the frontend AppChartConfig."""
    model_config = ConfigDict(populate_by_name=True)   # accept snake_case OR camelCase alias

    type: ChartType = Field(..., description="Chart type")
    x: str = Field(..., description="Categorical/label column name")
    y: List[str] = Field(..., description="One or more value column names (multi-series)")
    stacked: Optional[bool] = Field(default=None)
    trendline: Optional[bool] = Field(default=None)
    split_series: Optional[bool] = Field(default=None, alias="splitSeries")
    show_legend: Optional[bool] = Field(default=None, alias="showLegend")
    x_axis_mode: Optional[XAxisMode] = Field(default=None, alias="xAxisMode")
    palette: Optional[List[str]] = Field(default=None)
    color_by_sign: Optional[bool] = Field(default=None, alias="colorBySign")
    negative_color: Optional[str] = Field(default=None, alias="negativeColor")
    map_name: Optional[str] = Field(default=None, alias="mapName",
                                    description="GeoJSON map name (frontend-validated, free-form)")
    data: list[dict] = Field(default_factory=list,
                             description="Flat data rows; INPUT-ONLY — excluded from `output`, "
                                         "routed to response.data by the renderer.")

    @model_validator(mode="after")
    def _check(self):
        if self.type == "map" and not self.map_name:
            raise ValueError("type='map' requires 'mapName'")
        if self.data:
            cols = set(self.data[0].keys())
            missing = [c for c in [self.x, *self.y] if c not in cols]
            if missing:
                raise ValueError(f"columns not present in data rows: {missing}")
        return self
```

### Key Constraints
- Pydantic v2; camelCase aliases; `populate_by_name=True` (accept either casing on input).
- `data` stays a normal field here — the **`exclude={"data"}` on dump happens in the renderer**
  (TASK-1413), NOT in the model. Do not override `model_dump`.
- Google-style docstring; strict type hints.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/outputs.py:267` (`SentimentAnalysis`) — `Literal` field style.
- `packages/ai-parrot/src/parrot/models/outputs.py:208,220` — placement among output models.

---

## Acceptance Criteria

- [ ] `from parrot.models.outputs import StructuredChartConfig` works.
- [ ] `model_dump(by_alias=True)` emits camelCase keys (`splitSeries`, `xAxisMode`, `colorBySign`,
      `negativeColor`, `mapName`); the model accepts BOTH snake_case and camelCase on input.
- [ ] `type="map"` without `mapName` → `ValidationError`.
- [ ] `y`/`x` referencing a column absent from non-empty `data` → `ValidationError`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_chart.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/models/outputs.py` clean.

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot.models.outputs import StructuredChartConfig


def test_structured_chart_config_alias_roundtrip():
    cfg = StructuredChartConfig(type="bar", x="m", y=["v"], splitSeries=True, xAxisMode="time")
    dumped = cfg.model_dump(by_alias=True)
    assert "splitSeries" in dumped and "xAxisMode" in dumped
    assert "split_series" not in dumped
    # snake_case input also accepted
    cfg2 = StructuredChartConfig(type="bar", x="m", y=["v"], split_series=True)
    assert cfg2.split_series is True


def test_structured_chart_config_map_requires_mapname():
    with pytest.raises(ValidationError):
        StructuredChartConfig(type="map", x="country", y=["sales"])


def test_structured_chart_config_y_columns_present():
    with pytest.raises(ValidationError):
        StructuredChartConfig(type="bar", x="m", y=["missing"],
                              data=[{"m": "Jan", "v": 1}])
```

---

## Agent Instructions

1. **Read the spec** §2 Data Models.
2. **Check** TASK-1411 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** (re-`grep` outputs.py imports/line numbers).
4. **Update index** → `in-progress`.
5. **Implement** the model + validators + tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`, update index → `done`.
8. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-02
**Notes**: Added ChartType, XAxisMode Literals and StructuredChartConfig model to models/outputs.py. Updated pydantic import to include ConfigDict, model_validator. All model tests pass.
**Deviations from spec**: none
