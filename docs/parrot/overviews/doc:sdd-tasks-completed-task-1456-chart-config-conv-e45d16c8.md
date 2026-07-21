---
type: Wiki Overview
title: 'TASK-1456: Converge the chart config — one agnostic shape'
id: doc:sdd-tasks-completed-task-1456-chart-config-convergence-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 3**. A "chart" is represented **three** incompatible
  ways today:'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1456: Converge the chart config — one agnostic shape

**Feature**: FEAT-223 — Structured Artifact Contract
**Spec**: `sdd/specs/structured-artifact-contract.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1455
**Assigned-to**: unassigned

---

## Context

Implements **Module 3**. A "chart" is represented **three** incompatible ways today:
`StructuredChartConfig` (FEAT-215, the frontend-agnostic `AppChartConfig` mirror), the `Artifact` CHART
`definition` (echarts-style spec, FEAT-103), and the infographic `ChartBlock` (labels + series shape).
Converge the infographic `ChartBlock` and the `Artifact` CHART `definition` onto the single agnostic
`StructuredChartConfig` / `AppChartConfig` shape, making it the canonical chart contract.

Resolves **Impl-2**: audit whether `ChartBlock` carries any field `StructuredChartConfig` /
`AppChartConfig` lacks; record the answer in the completion note and add the field to the agnostic
config if genuinely needed.

---

## Scope

- Audit `ChartBlock` (`infographic.py:404`) field-by-field against `StructuredChartConfig`
  (`outputs.py:309`). Document gaps (Impl-2).
- Make the infographic `ChartBlock` serialize/consume the agnostic `StructuredChartConfig` shape
  (or embed it) instead of its own `labels` + `series` model — without breaking existing infographic
  rendering.
- Make the `Artifact` CHART `definition` (`storage/models.py:287`, `Optional[Dict[str, Any]]`) carry the
  converged config instead of an ad-hoc echarts spec. The field stays `Dict[str, Any]`; the change is
  WHAT shape is serialized into it (a `StructuredChartConfig.model_dump`).
- Add any genuinely-missing field surfaced by the Impl-2 audit to `StructuredChartConfig`.

**NOT in scope**: removing/deprecating library-specific `OutputMode`s (they stay — spec Non-Goals);
the chart renderer itself (TASK-1455); map (TASK-1457); the parity/serialization tests (TASK-1458,
though keep existing infographic/storage tests green).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | `ChartBlock` adopts/embeds the agnostic `StructuredChartConfig` shape |
| `packages/ai-parrot/src/parrot/storage/models.py` | MODIFY | `Artifact` CHART `definition` carries the converged config |
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | Add a missing field to `StructuredChartConfig` ONLY if the Impl-2 audit requires it |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFY before coding. TASK-1455 must be in `tasks/completed/` first.

### Verified Imports
```python
from parrot.models.outputs import StructuredChartConfig   # outputs.py:309
from parrot.storage.models import Artifact, ArtifactType  # storage/models.py:272 / :244
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/infographic.py
class ChartType(str, Enum): ...                  # :90
class ChartDataSeries(BaseModel): ...            # :388  (name + values[])
class ChartBlock(BaseModel):                     # :404
    # type, chart_type (ChartType), title, description, labels (x-axis array),
    # series (List[ChartDataSeries]), x_axis_label, y_axis_label, stacked,
    # show_legend, layout, color_by_sign, positive_color, negative_color

# packages/ai-parrot/src/parrot/storage/models.py
class Artifact(BaseModel):                        # :272
    definition: Optional[Dict[str, Any]] = None   # :287  (CHART carries echarts-style spec today)
    definition_ref: Optional[str] = None          # :288  (S3 URI on >200KB overflow)
class ArtifactType(str, Enum):                     # :244  (CHART = "chart")

# packages/ai-parrot/src/parrot/models/outputs.py
class StructuredChartConfig(BaseModel):           # :309
    # type, x, y[], stacked, trendline, split_series(alias splitSeries), show_legend(alias showLegend),
    # x_axis_mode(alias xAxisMode), palette, color_by_sign(alias colorBySign), negative_color,
    # map_name(alias mapName), title, description, data[input-only], data_variable(alias dataVariable)
```

### Does NOT Exist
- ~~A formal Pydantic model for the echarts Artifact spec~~ — it is implicit `Dict[str, Any]` today.
- ~~`AppChartConfig` as a Python class in the repo~~ — it is the FRONTEND shape that `StructuredChartConfig`
  mirrors (per the `StructuredChartConfig` docstring). Treat `StructuredChartConfig` as the canonical Python side.

---

## Implementation Notes

### Key Constraints
- `Artifact.definition` keeps type `Optional[Dict[str, Any]]` — only the serialized SHAPE changes.
- Preserve backward compatibility for existing infographic rendering; ChartBlock's data model shift must
  round-trip what infographics already produce (labels/series ↔ x/y+rows).
- Pydantic aliases (`by_alias=True`) must be respected so the frontend receives camelCase.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/outputs.py:309` — the canonical shape.
- Use the same `model_dump(mode="json", by_alias=True)` convention the renderers use.

---

## Acceptance Criteria

- [ ] Impl-2 audit recorded: does `ChartBlock` need a field `StructuredChartConfig` lacks? (yes/no + which)
- [ ] One chart config shape is used by `STRUCTURED_CHART`, infographic `ChartBlock`, and `Artifact` CHART `definition`.
- [ ] Existing infographic + storage/artifact tests pass.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/ packages/ai-parrot/src/parrot/storage/models.py`
- [ ] `from parrot.models.outputs import StructuredChartConfig` round-trips a ChartBlock-sourced config.

---

## Test Specification

```python
# packages/ai-parrot/tests/ ... (infographic / storage suites)
class TestChartConfigConvergence:
    def test_chartblock_serializes_agnostic_config(self):
        """Infographic ChartBlock serializes the StructuredChartConfig shape (camelCase aliases)."""
        ...

    def test_artifact_chart_definition_is_converged_shape(self):
        """Artifact CHART definition carries StructuredChartConfig, not an ad-hoc echarts spec."""
        ...

    def test_roundtrip_chartblock_to_config(self):
        """A ChartBlock round-trips through the converged config without losing presentation fields."""
        ...
```

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-04
**Notes**: Added `positive_color`, `x_axis_label`, `y_axis_label` to `StructuredChartConfig`. Added `ChartBlock.to_chart_config()` (labels+series → x/y/data) and `ChartBlock.from_chart_config()` (classmethod, inverse) to `infographic.py` — existing fields preserved. Added `Artifact.from_chart_config()` and `Artifact.as_chart_config()` to `storage/models.py`. 23 new convergence tests pass; 85 existing chart/table tests unaffected. Linting clean.
**Impl-2 audit result**: ChartBlock has 4 fields absent from StructuredChartConfig: `positive_color` (complement to `negative_color` — **ADDED**), `x_axis_label` / `y_axis_label` (axis display labels — **ADDED**), `layout` (infographic half/full layout hint — **NOT added**; it is infographic-composition concern, not chart-config).
**Deviations from spec**: none
