# TASK-4852: MetricsToolkit — list, describe, query and explain metrics

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4847, TASK-4850, TASK-4851
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5: the LLM/MCP-facing `MetricsToolkit(AbstractToolkit)` with exactly four tools
(`list_metrics`, `describe_metric`, `query_metric`, `explain_metric`), tenant resolution per D3, and its result
models. It composes the registry (TASK-4847), the executors (TASK-4851), periods (TASK-4849) and the shape emitter
(TASK-4850). Registration in `TOOL_REGISTRY` is TASK-4856.

---

## Scope

- Implement `MetricSummary`, `MetricExplanation`, `QueryMetricResult` in `models.py`.
- Implement `MetricsToolkit` in `toolkit.py` with the binding tool docstrings from spec M5.
- Write `tests/metrics/test_metrics_toolkit.py` (in-memory registry, stubbed executors / querysource / publish tool).

**NOT in scope**: `parrot_tools/__init__.py` `TOOL_REGISTRY` (TASK-4856); `parrot_tools/metrics/__init__.py` (TASK-4849
owns it); routing mixin (TASK-4853); HTTP (TASK-4855).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/metrics/models.py` | CREATE | Result models |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/toolkit.py` | CREATE | `MetricsToolkit` |
| `packages/ai-parrot-tools/tests/metrics/test_metrics_toolkit.py` | CREATE | Unit/integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                                   # tools/toolkit.py:225
from parrot_tools.querysource import QuerysourceToolkit, SlugDetail                # querysource/__init__.py:11-21
from parrot_tools.ui_surfaces import PublishSurfaceTool                           # parrot_tools/ui_surfaces.py:65
from parrot.tools.infographic_recipes.runner import RecipeRunner                   # runner.py:205
from parrot.metrics.models import MetricDefinition, ResolvedPeriod, PeriodPreset, KPICardShape, ChartShape, DataTableShape   # TASK-4843
from parrot.metrics.errors import MetricNotFound, MetricSourceUnavailable          # TASK-4843
from parrot.metrics.store import InMemoryMetricStore, MetricStore                  # TASK-4844
from parrot.metrics.registry import MetricRegistry                                 # TASK-4847
from parrot.metrics.context import resolve_metric_tenant                           # TASK-4846
from parrot.skills.tenancy import validate_tenant_id                               # skills/tenancy.py:42
from parrot_tools.metrics.periods import resolve_period, comparison_period, series_buckets       # TASK-4849
from parrot_tools.metrics.shapes import KPIFigures, aggregate, figures, build_metric_envelope, build_linked_metric_envelope  # TASK-4850
from parrot_tools.metrics.executors import executor_for, SourceFrame, QuerySlugExecutor, TransformerExecutor  # TASK-4851
```

### Existing Signatures to Use
```python
# tools/toolkit.py:225
class AbstractToolkit(ServerManagedToolkit, ABC):
    exclude_tools: tuple[str, ...] = ()        # L262
    tool_prefix: str | None = None             # L276
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None   # L491 — hook run before every tool
    def get_tools(...)                         # L522
# parrot_tools/querysource/toolkit.py:85 — exclude_tools = ("open", "close"); _pre_execute override pattern L860
# parrot_tools/ui_surfaces.py:65
class PublishSurfaceTool(AbstractTool):       # name "publish_surface"
    def __init__(self, bot=None, surface_store=None, agent_id=None, user_id=None, session_id=None,
                 linked_service=None, guard=None, **kwargs)                                   # L86
    async def _execute(self, *, kind: str, title: str, envelope: dict, recipe_name=None, recipe_owner=None,
                       recipe_params=None, overwrite=False, **kwargs) -> dict[str, Any]       # L127 — returns surface info
# parrot/metrics/registry.py (TASK-4847)
class MetricRegistry:
    async def list(self, *, tenant=None, program=None) -> list[MetricDefinition]
    async def describe(self, metric_id: str, *, tenant=None) -> MetricDefinition   # raises MetricNotFound
# parrot/metrics/context.py (TASK-4846)
def resolve_metric_tenant(explicit=None, ctx=None, default=None) -> str | None     # validates; ValueError on invalid
```

### Does NOT Exist
- ~~`parrot_tools.metrics.MetricsToolkit` in `TOOL_REGISTRY`~~ — added by TASK-4856, not here.
- ~~`parrot.tests…MetricsToolkit`~~ — a test-local class of that name exists only in
  `packages/ai-parrot/tests/tools/test_nested_model_args.py:29`; unrelated, never import it.
- ~~`PublishSurfaceTool.publish(...)` / `.run(...)`~~ — call `_execute(kind=…, title=…, envelope=…)` (or the bot's
  `publish_surface` via the tool); read `surface_id` from the returned dict (inspect `_execute` body L127-200 first).
- ~~`AbstractToolkit.tenant`~~ — tenant is resolved per call in `_pre_execute`.
- ~~An LLM call in `explain_metric`~~ — deterministic text only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/metrics/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/metrics/toolkit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/metrics/test_metrics_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit"
  ]
}
```

---

## Implementation Notes

- Tool set is exactly the four public async methods; `exclude_tools = ("open", "close")`. Every helper is `_`-prefixed.
- Tenant (D3): `_pre_execute` resolves `resolve_metric_tenant(kwargs.get("tenant"), current ctx, self.default_tenant)`
  and stashes it on `self._call_tenant`; an explicit invalid tenant raises `ValueError` before the tool runs.
- `query_metric` flow: describe → pick shape (`shape` override, else `by` → Chart (line, x=dimension column, y=[value])
  for KPICard defaults, else default_shape) → `period = resolve_period(period or definition.time.default_period,
  single_placeholder=<binding has exactly one placeholder>)` → executor fetch current → if `compare` (default: policy ≠
  none and shape is KPICard) fetch comparison window → `aggregate` → `figures` → series (when `series_grain` and a date
  column exist) → envelope (`build_metric_envelope`, or `build_linked_metric_envelope` when `linked=True`) → optional
  pin → `QueryMetricResult`. `rows` capped at `max_rows`.
- `by=<unknown>` → `ValueError` naming the declared dimensions; `linked=True` on recipe/semantic → `ValueError`
  ("only query_slug/transformer metrics can be linked"); semantic → `MetricSourceUnavailable` surfaced as-is.
- `pin=True` requires `allow_pin`; uses the injected `publish_tool` (`kind="widget"`); recipe sources pass
  `recipe_name`/`recipe_owner`/`recipe_params` for FEAT-492 refresh.
- Empty registry (no store/registry passed) → `list_metrics` returns `[]`, other tools raise `MetricNotFound`.
- `explain_metric` lineage text: source line (slug / transformer over slug / recipe + pointer), filters, default period
  + binding, comparison policy, unit/format, default shape and reason ("declared default_shape"). `source_detail` =
  `await querysource.describe_slug(slug)` for slug-backed sources when a querysource is available, else `None`
  (never fail explain on describe errors — log and continue).

---

## Implementation Blueprint

### Steps (in order)
1. Write `models.py` — *why*: tool return types appear in the LLM schema.
2. Write `MetricsToolkit.__init__`, `_pre_execute`, `_querysource` lazy builder.
3. Implement `list_metrics`, `describe_metric`, `explain_metric`.
4. Implement `query_metric` per Implementation Notes.
5. Tests with `InMemoryMetricStore` + monkeypatched `executor_for`.

### `packages/ai-parrot-tools/src/parrot_tools/metrics/models.py` (CREATE)
```python
"""Result models of MetricsToolkit (spec §3 M5)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.metrics.models import MetricDefinition, ResolvedPeriod


class MetricSummary(BaseModel):
    """One row of ``list_metrics``."""
    id: str
    name: str
    unit: str | None = None
    default_component: str
    tenant: str | None = None
    program: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    source_kind: str


class MetricExplanation(BaseModel):
    """Deterministic explanation of how a metric is computed."""
    definition: MetricDefinition
    lineage: str
    source_detail: Any = None


class QueryMetricResult(BaseModel):
    """Value, comparison and ready A2UI envelope of one metric query."""
    metric_id: str
    period: ResolvedPeriod
    comparison_period: ResolvedPeriod | None = None
    value: Any = None
    previous: Any = None
    delta: float | None = None
    delta_pct: float | None = None
    trend: Literal["up", "down", "flat"] | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    envelope: dict[str, Any]
    linked: bool = False
    surface_id: str | None = None
    duration_ms: int = 0
```

### `packages/ai-parrot-tools/src/parrot_tools/metrics/toolkit.py` (CREATE)
```python
"""MetricsToolkit — tenant-scoped metric registry tools (FEAT-756, spec §3 M5)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Literal

from parrot.metrics.context import resolve_metric_tenant
from parrot.metrics.errors import MetricNotFound
from parrot.metrics.models import MetricDefinition, PeriodPreset
from parrot.metrics.registry import MetricRegistry
from parrot.metrics.store import InMemoryMetricStore, MetricStore
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.querysource import QuerysourceToolkit
from parrot_tools.ui_surfaces import PublishSurfaceTool

from .models import MetricExplanation, MetricSummary, QueryMetricResult


class MetricsToolkit(AbstractToolkit):
    """Tenant-scoped metric registry tools: list, describe, query (default-shape A2UI envelope) and explain."""

    exclude_tools: tuple[str, ...] = ("open", "close")

    def __init__(self, registry: MetricRegistry | None = None, *, store: MetricStore | None = None,
                 querysource: QuerysourceToolkit | None = None, recipe_runner: RecipeRunner | None = None,
                 pctx_provider: Callable[[], Any] | None = None, default_tenant: str | None = None,
                 max_rows: int = 200, allow_pin: bool = True, publish_tool: PublishSurfaceTool | None = None,
                 **kwargs: Any) -> None:
        self._querysource_kwargs: dict[str, Any] = kwargs.pop("querysource_kwargs", {})
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        self.registry = registry or MetricRegistry(store or InMemoryMetricStore(), default_tenant=default_tenant)
        self._querysource = querysource
        self._recipe_runner = recipe_runner
        self._pctx_provider = pctx_provider
        self.default_tenant = default_tenant
        self.max_rows = max_rows
        self.allow_pin = allow_pin
        self._publish_tool = publish_tool
        self._call_tenant: str | None = None

    def _get_querysource(self) -> QuerysourceToolkit:
        """Lazily build the QuerySource toolkit from ``querysource_kwargs``."""
        if self._querysource is None:
            self._querysource = QuerysourceToolkit(**self._querysource_kwargs)
        return self._querysource

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Resolve the effective tenant (D3) and stash it for the call; reject an invalid explicit tenant."""
        await super()._pre_execute(tool_name, **kwargs)
        # FILL IN: self._call_tenant = resolve_metric_tenant(kwargs.get("tenant"), <current RequestContext via
        #   parrot.utils.helpers.current_context() — verify import>, self.default_tenant); ValueError propagates
        raise NotImplementedError

    async def list_metrics(self, search: str | None = None, program: str | None = None,
                           tenant: str | None = None) -> list[MetricSummary]:
        """List the metrics visible in this tenant. `search` filters name/aliases/description (case-insensitive).
        `tenant` is routing only; omit it to use the request's tenant."""
        # FILL IN: registry.list(tenant=self._call_tenant, program=program) → search filter → MetricSummary
        raise NotImplementedError

    async def describe_metric(self, metric_id: str, tenant: str | None = None) -> MetricDefinition:
        """Return the full definition of one metric (source, unit, dimensions, default period and shape)."""
        return await self.registry.describe(metric_id, tenant=self._call_tenant)

    async def query_metric(self, metric_id: str, period: PeriodPreset | None = None, by: str | None = None,
                           filters: dict[str, Any] | None = None, compare: bool | None = None,
                           shape: Literal["KPICard", "Chart", "DataTable", "Map"] | None = None,
                           linked: bool = False, pin: bool = False, title: str | None = None,
                           tenant: str | None = None) -> QueryMetricResult:
        """Execute a metric from its declared source and return its value plus a ready A2UI envelope in the
        metric's default shape (override with `shape`). `period` defaults to the metric's default period;
        `by` breaks the metric down by one declared dimension (switches the shape to Chart/DataTable);
        `compare` applies the comparison policy (delta/trend vs the previous period); `linked=True`
        emits a refreshable linked surface (query_slug/transformer sources only); `pin=True` persists it
        to the ui_surfaces plane and returns `surface_id`."""
        started = time.monotonic()
        definition = await self.registry.describe(metric_id, tenant=self._call_tenant)
        # FILL IN: full flow per Implementation Notes — bounded by AC-2..AC-5; duration_ms from `started`
        raise NotImplementedError

    async def explain_metric(self, metric_id: str, tenant: str | None = None) -> MetricExplanation:
        """Explain how a metric is computed: its source (slug / transformer / recipe), filters, period and
        comparison policy, unit and why the default shape was chosen. Deterministic — no LLM call."""
        definition = await self.registry.describe(metric_id, tenant=self._call_tenant)
        # FILL IN: lineage text + optional describe_slug detail (errors logged, not raised)
        raise NotImplementedError
```
**Why this shape**: signatures and docstrings are binding (spec M5); `_pre_execute` mirrors the QuerysourceToolkit
hook (toolkit.py:860) so tenant validation happens before any tool body.

### FILL IN checklist
- [ ] `_pre_execute` tenant resolution (verify `current_context` import, `parrot/utils/helpers.py:62`)
- [ ] `list_metrics` search filter
- [ ] `query_metric` full flow (shape selection, compare, series, linked, pin)
- [ ] `explain_metric` lineage

---

## Acceptance Criteria

- [ ] `[t.name for t in MetricsToolkit().get_tools()]` is exactly the four tools (no `open`/`close`).
- [ ] `query_metric` on a query_slug KPI returns value/previous/delta/trend and a KPICard envelope passing
      `validate_envelope(origin=TOOL)` (stubbed executor).
- [ ] `by=<dimension>` switches shape to Chart/DataTable; unknown dimension → `ValueError`.
- [ ] `linked=True` on a recipe source → clear `ValueError`; on query_slug calls `build_linked_metric_envelope`.
- [ ] `pin=True` forwards the envelope to the publish tool and returns `surface_id`.
- [ ] Explicit invalid tenant is rejected in `_pre_execute`; omitted tenant uses the request tenant.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/metrics/test_metrics_toolkit.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/metrics/test_metrics_toolkit.py
from unittest.mock import AsyncMock
import pytest
from parrot.metrics.models import MetricDefinition
from parrot.metrics.store import InMemoryMetricStore
from parrot_tools.metrics.executors import SourceFrame
from parrot_tools.metrics.toolkit import MetricsToolkit

@pytest.fixture
def worked_hours() -> MetricDefinition:
    return MetricDefinition.model_validate({
        "id": "worked_hours", "name": "Worked Hours", "unit": "h", "higher_is_better": None,
        "dimensions": [{"name": "cost center", "column": "cost_center"}],
        "time": {"binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"}, "series_grain": None},
        "default_shape": {"component": "KPICard", "value_column": "hours"},
        "source": {"kind": "query_slug", "slug": "flex_hours"},
    })

@pytest.fixture
def toolkit(worked_hours, monkeypatch):
    frames = iter([SourceFrame(rows=[{"hours": 110}]), SourceFrame(rows=[{"hours": 100}])])
    stub = AsyncMock()
    stub.fetch = AsyncMock(side_effect=lambda *a, **k: next(frames))
    monkeypatch.setattr("parrot_tools.metrics.toolkit.executor_for", lambda *a, **k: stub, raising=False)
    return MetricsToolkit(store=InMemoryMetricStore([worked_hours]), querysource=AsyncMock())

def test_exactly_four_tools():
    names = {t.name for t in MetricsToolkit().get_tools()}
    assert names == {"list_metrics", "describe_metric", "query_metric", "explain_metric"}

async def test_query_metric_kpicard_end_to_end_stubbed(toolkit):
    res = await toolkit.query_metric("worked_hours")
    assert res.value == 110 and res.previous == 100 and res.trend == "up"

# FILL IN: test_query_metric_by_dimension_switches_shape, test_query_metric_linked_only_for_query_slug,
#   test_query_metric_pin_returns_surface_id (publish_tool=AsyncMock with _execute returning {"surface_id": "s1"}),
#   test_list_metrics_uses_request_tenant (explicit "../x" → ValueError via _pre_execute)
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4847, TASK-4850, TASK-4851 are `done`.
2. Verify the sibling-task symbols (`MetricRegistry`, `resolve_metric_tenant`, `executor_for`, `build_*_envelope`) in the
   worktree before coding; how the toolkit names its tools (`get_tools` prefix rule L557-570) — keep `tool_prefix=None`.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4852 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
