# TASK-4850: Metric shape emitter — KPI figures, KPICard props, baked and linked envelopes

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4849
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7 (shapes half) and the binding §7 "KPICard prop mapping" and "Linked periods" sections:
aggregate a frame to the KPI scalar, compute delta/trend, and build the TOOL-origin A2UI envelope for each
`default_shape` (KPICard / Chart / DataTable / Map), plus the linked variant for `query_slug`/`transformer` sources.

---

## Scope

- Implement `KPIFigures`, `aggregate`, `figures`, `kpicard_props`, `build_metric_envelope`,
  `build_linked_metric_envelope` in `shapes.py`.
- Write `tests/metrics/test_shapes.py`.

**NOT in scope**: period math (TASK-4849), fetching data (TASK-4851), tool surface/pinning (TASK-4852).
Do NOT edit `parrot_tools/metrics/__init__.py` (TASK-4849 owns it; `shapes` names are already mapped there).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/metrics/shapes.py` | CREATE | Figures + envelope builders |
| `packages/ai-parrot-tools/tests/metrics/test_shapes.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_datatable   # builders.py:83, :134, :197
from parrot.outputs.a2ui.catalog import validate_envelope                             # catalog/__init__.py:763
from parrot.outputs.a2ui.catalog.base import ProducerOrigin                            # catalog/base.py:104 (TOOL L112)
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA                  # kpicard.py:15
from parrot.outputs.a2ui.models import CreateSurface                                   # a2ui/models.py:446
from parrot.outputs.a2ui.linked.models import RefreshPolicy                            # linked/models.py:43
from parrot.metrics.models import (MetricDefinition, KPICardShape, ChartShape, DataTableShape, MapShape,
                                   ShapeSpec, ComparisonPolicy, ResolvedPeriod)        # TASK-4843
from parrot_tools.querysource import QuerysourceToolkit                                # querysource/__init__.py:21
```

### Existing Signatures to Use
```python
# builders.py:83
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root",
                  data_model: dict[str, Any] | None = None, origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata=None, surface_metadata=None) -> CreateSurface
# builders.py:134
def build_chart(*, chart_type: str, x: str, y: Sequence[str], title=None, data_binding=None, show_legend=True,
                surface_id="chart", data_model=None) -> CreateSurface
# builders.py:197
def build_datatable(*, columns: Sequence[dict], data_binding=None, title=None, total_rows=None, truncated=False,
                    surface_id="table", data_model=None) -> CreateSurface
# catalog/__init__.py:763
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None
# kpicard.py:15 — KPICARD_SCHEMA["properties"] keys: label, value, unit, delta, trend{up,down,flat}, icon, color,
#   comparisonPeriod, higherIsBetter {bool,null} (L33-49), format{percent,currency,number}, periods, series, defaultPeriod
# a2ui/models.py:446 — CreateSurface: surface_id (alias surfaceId), components, data_model (alias dataModel)
# linked/models.py:43 — RefreshPolicy(policy: Literal["on_mount","manual","interval"]="on_mount", interval_seconds: int|None)
# parrot_tools/querysource/toolkit.py:351
async def build_linked_surface(self, slug: str, component: dict[str, Any], request: dict | None = None,
                               tenant: str | None = None, snapshot: bool = False, surface_id: str | None = None,
                               target_key: str | None = None, refresh: dict | None = None,
                               transform: dict | None = None) -> dict[str, Any]
```

### Does NOT Exist
- ~~`build_kpicard(series=…, comparison_period=…, higher_is_better=…, format=…)`~~ — `build_kpicard` (L155) takes only
  label/value/unit/delta/trend; always use `build_surface("KPICard", props, origin=ProducerOrigin.TOOL)`.
- ~~`build_map`~~ — use `build_surface("Map", …)`.
- ~~A `periods` KPICard prop in v1~~ — not emitted.
- ~~`LinkedDataSource(kind="recipe")`~~ — recipes are never linked (D4).
- ~~`build_linked_surface(sources=[…])` multi-source call~~ — one slug per call; the comparison `previous` source is a
  second call's source merged by key — see FILL IN.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/metrics/shapes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/metrics/test_shapes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_surface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_chart",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_datatable",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.build_linked_surface"
  ]
}
```

---

## Implementation Notes

- KPICard mapping (spec §7, binding): `label=name`, `value`, `unit`, `format`, `delta = delta_pct` when
  `format != "percent"` and previous ∉ {0, None}, else absolute delta; `trend`; `comparisonPeriod = policy.label or
  derived label`; `higherIsBetter` omitted when True, `False` when False, `None` (JSON null) when None; `icon`/`color`
  from the shape; `series=[{date, value}]` only when provided. Filter every key through
  `KPICARD_SCHEMA["properties"]` and drop `None` values except `higherIsBetter`.
- `figures`: delta = current − previous; `delta_pct=None` when previous in {0, None}; trend from sign with a 0.5 %
  flat band (|delta_pct| < 0.5 → "flat"; when delta_pct is None use sign of delta, 0 → flat).
- `aggregate`: sum/avg/min/max/count/first/last over `shape.value_column`; `none` requires exactly one row (else
  `ValueError`); empty rows → `None` (count → 0).
- Linked: `refresh` defaults to `RefreshPolicy(policy="manual")` (spec §7); KPICard `value` binds the live source;
  the comparison value is a second linked source keyed `previous` with `locked` ISO dates.
- Envelope surface ids: caller-provided; use `f"metric-{definition.id}"` default in the toolkit (TASK-4852).

---

## Implementation Blueprint

### Steps (in order)
1. Write `KPIFigures`, `aggregate`, `figures` — *why*: pure math, test first.
2. Write `kpicard_props` with the schema allowlist — *why*: AC requires only schema keys.
3. Write `build_metric_envelope` dispatching on `shape.component` — *why*: one TOOL-origin envelope per shape.
4. Write `build_linked_metric_envelope` — *why*: refreshable pins for query_slug/transformer sources.
5. Tests: every envelope passes `validate_envelope(env, origin=ProducerOrigin.TOOL)`.

### `packages/ai-parrot-tools/src/parrot_tools/metrics/shapes.py` (CREATE)
```python
"""KPI figures and A2UI envelopes for metric results (spec §3 M7, §7 KPICard mapping / Linked periods)."""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

from parrot.metrics.models import (
    ChartShape, ComparisonPolicy, DataTableShape, KPICardShape, MapShape, MetricDefinition, ResolvedPeriod, ShapeSpec,
)
from parrot.outputs.a2ui.builders import build_chart, build_datatable, build_surface
from parrot.outputs.a2ui.catalog.base import ProducerOrigin
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA
from parrot.outputs.a2ui.linked.models import RefreshPolicy
from parrot.outputs.a2ui.models import CreateSurface
from parrot_tools.querysource import QuerysourceToolkit

logger = logging.getLogger(__name__)
_FLAT_BAND_PCT = 0.5


class KPIFigures(BaseModel):
    """Scalar KPI figures for one period plus its comparison."""
    value: Any = None
    previous: Any = None
    delta: float | None = None
    delta_pct: float | None = None
    trend: Literal["up", "down", "flat"] | None = None
    comparison_label: str | None = None
    series: list[dict[str, Any]] | None = None


def aggregate(frame_rows: Sequence[Mapping[str, Any]], shape: KPICardShape) -> Any:
    """Apply ``shape.aggregate`` to ``shape.value_column``; ``none`` requires exactly one row."""
    # FILL IN: 8 aggregate modes — bounded by Implementation Notes; missing column → KeyError with the column name
    raise NotImplementedError


def figures(current: Any, previous: Any | None, *, policy: ComparisonPolicy, period: ResolvedPeriod,
            comparison: ResolvedPeriod | None, series: list[dict] | None) -> KPIFigures:
    """delta / delta_pct (zero-guarded) / trend (0.5 % flat band) / comparison label."""
    # FILL IN: math + label (policy.label or comparison.label or None) — bounded by test_figures_delta_and_trend
    raise NotImplementedError


def kpicard_props(definition: MetricDefinition, fig: KPIFigures) -> dict[str, Any]:
    """KPICard properties restricted to ``KPICARD_SCHEMA['properties']`` keys (tri-state ``higherIsBetter``)."""
    allowed = set(KPICARD_SCHEMA["properties"])
    # FILL IN: build props per §7 mapping; omit higherIsBetter when True; keep explicit None; drop other None values
    props: dict[str, Any] = {}
    return {k: v for k, v in props.items() if k in allowed}


def build_metric_envelope(definition: MetricDefinition, *, shape: ShapeSpec, fig: KPIFigures | None,
                          rows: Sequence[Mapping[str, Any]], surface_id: str, title: str | None) -> CreateSurface:
    """Baked TOOL-origin envelope for the requested shape."""
    if isinstance(shape, KPICardShape):
        if fig is None:
            raise ValueError("KPICard shape requires KPI figures")
        return build_surface("KPICard", kpicard_props(definition, fig), surface_id=surface_id,
                             origin=ProducerOrigin.TOOL)
    if isinstance(shape, ChartShape):
        return build_chart(chart_type=shape.chart_type, x=shape.x, y=shape.y, title=title or shape.title,
                           data_binding="/rows", surface_id=surface_id, data_model={"rows": list(rows)})
    if isinstance(shape, DataTableShape):
        # FILL IN: columns = shape.columns or derived [{key, label}] from rows[0] — bounded by DataTable catalog schema
        raise NotImplementedError
    if isinstance(shape, MapShape):
        # FILL IN: build_surface("Map", props, data_model={"rows": rows}, origin=TOOL) — read the Map schema in
        #   parrot/outputs/a2ui/catalog/ for the exact prop names (lat/lon/label binding) before writing it
        raise NotImplementedError
    raise ValueError(f"unsupported shape {shape!r}")


async def build_linked_metric_envelope(querysource: QuerysourceToolkit, definition: MetricDefinition, *,
                                       shape: ShapeSpec, request: dict[str, Any],
                                       comparison_request: dict[str, Any] | None, refresh: RefreshPolicy | None,
                                       snapshot: bool, surface_id: str | None) -> dict[str, Any]:
    """Linked envelope (query_slug / transformer sources only) via ``QuerysourceToolkit.build_linked_surface``."""
    source = definition.source
    if source.kind not in ("query_slug", "transformer"):
        raise ValueError(f"metric {definition.id!r}: source kind {source.kind!r} cannot be linked")
    slug_source = source if source.kind == "query_slug" else source.input
    refresh = refresh or RefreshPolicy(policy="manual")
    # FILL IN: component dict (KPICard props w/o value binding, or Chart/DataTable config), transform dict for the
    #   transformer kind ({"python": {transformer, params, input_alias, output}}), call build_linked_surface(
    #   slug_source.slug, component, request=request, tenant=slug_source.tenant, snapshot=snapshot,
    #   surface_id=surface_id, refresh=refresh.model_dump(), transform=…); when comparison_request is set, build a second
    #   linked surface and merge its source into the first envelope's sources under key "previous" — inspect the
    #   returned dict shape in tests/querysource/test_build_linked_surface_tool.py before merging (bounded by AC-3)
    raise NotImplementedError
```
**Why this shape**: signatures are fixed by spec M7; KPICard always goes through `build_surface` because
`build_kpicard` lacks series/comparisonPeriod/higherIsBetter/format.

### FILL IN checklist
- [ ] `aggregate` — 8 modes
- [ ] `figures` — zero guard, flat band
- [ ] `kpicard_props` — §7 mapping, tri-state
- [ ] DataTable / Map branches
- [ ] `build_linked_metric_envelope` — component, transform, `previous` merge

---

## Acceptance Criteria

- [ ] `kpicard_props` emits only `KPICARD_SCHEMA["properties"]` keys; `higherIsBetter` omitted / False / null as specified.
- [ ] `build_metric_envelope` output passes `validate_envelope(env, origin=ProducerOrigin.TOOL)` for all four shapes.
- [ ] `build_linked_metric_envelope` rejects `recipe`/`semantic_metric`, defaults `refresh` to `manual`, and calls
      `build_linked_surface` with the slug's tenant (stubbed querysource in tests).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/metrics/shapes.py` clean.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/metrics/test_shapes.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/metrics/test_shapes.py
from datetime import date
from unittest.mock import AsyncMock
import pytest
from parrot.metrics.models import ComparisonPolicy, KPICardShape, MetricDefinition, ResolvedPeriod
from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import ProducerOrigin
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA
from parrot_tools.metrics.shapes import aggregate, build_metric_envelope, figures, kpicard_props

@pytest.fixture
def worked_hours() -> MetricDefinition:
    return MetricDefinition.model_validate({
        "id": "worked_hours", "name": "Worked Hours", "unit": "h", "format": "number", "higher_is_better": None,
        "time": {"binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"}},
        "default_shape": {"component": "KPICard", "value_column": "hours"},
        "source": {"kind": "query_slug", "slug": "flex_hours"},
    })

def test_aggregate_sum():
    assert aggregate([{"hours": 2}, {"hours": 3}], KPICardShape(value_column="hours")) == 5

def test_figures_delta_and_trend():
    p = ResolvedPeriod(preset="this_month", start=date(2026, 10, 1), end=date(2026, 10, 31), label="October 2026")
    f = figures(110, 100, policy=ComparisonPolicy(), period=p, comparison=None, series=None)
    assert f.delta == 10 and f.trend == "up"
    assert figures(5, 0, policy=ComparisonPolicy(), period=p, comparison=None, series=None).delta_pct is None

def test_kpicard_props_schema_keys_only(worked_hours):
    # FILL IN: build KPIFigures, assert set(props) <= set(KPICARD_SCHEMA["properties"]) and props["higherIsBetter"] is None
    ...

def test_build_metric_envelope_validates_tool_origin(worked_hours):
    # FILL IN: one case per shape; validate_envelope(env, origin=ProducerOrigin.TOOL) must not raise
    ...

async def test_linked_rejects_recipe():
    # FILL IN: recipe-sourced definition → ValueError; querysource = AsyncMock()
    ...
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4849 is `done`.
2. Verify every contract line (builders, validate_envelope, KPICARD_SCHEMA) before coding.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4850 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
