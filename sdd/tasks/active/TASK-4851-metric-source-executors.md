# TASK-4851: Metric source executors — query_slug, transformer, recipe

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4849
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6: one executor per `MetricSource.kind` turning a definition + `ResolvedPeriod` + optional
dimension/filters into a `SourceFrame`. `semantic_metric` is reserved for FEAT-704 and raises
`MetricSourceUnavailable`.

---

## Scope

- Implement `SourceFrame`, `SourceExecutor` (Protocol), `QuerySlugExecutor`, `TransformerExecutor`, `RecipeExecutor`,
  `executor_for` in `executors.py`.
- Write `tests/metrics/test_executors.py` with a stub `QuerysourceToolkit` (AsyncMock) and stub `RecipeRunner`.

**NOT in scope**: aggregation/envelopes (TASK-4850), the toolkit (TASK-4852). Do NOT edit `parrot_tools/metrics/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/metrics/executors.py` | CREATE | Executors |
| `packages/ai-parrot-tools/tests/metrics/test_executors.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource import QuerysourceToolkit, ExecutionResult, QuerysourceToolkitError   # querysource/__init__.py:3-21
from parrot.outputs.a2ui.linked.models import PythonTransform                                       # linked/models.py:178
from parrot.outputs.a2ui.linked.pytransform import validate_python_transform, apply_python_transform, TransformStageError  # pytransform.py:36, :94, :27
from parrot.tools.infographic_recipes.runner import RecipeRunner                                    # runner.py:205
from parrot.metrics.models import (MetricDefinition, MetricSource, QuerySlugSource, TransformerSource, RecipeSource,
                                   DimensionSpec, ResolvedPeriod)                                   # TASK-4843
from parrot.metrics.errors import MetricSourceUnavailable                                           # TASK-4843
import pandas as pd
```

### Existing Signatures to Use
```python
# parrot_tools/querysource/toolkit.py:253
async def execute_slug(self, slug: str, placeholders: dict | None = None, filter: dict | None = None,
                       fields: list[str] | None = None, ordering: list[str] | None = None,
                       grouping: list[str] | None = None, limit: int | None = None, offset: int | None = None,
                       refresh: bool = False, tenant: str | None = None) -> ExecutionResult
# parrot_tools/querysource/models.py:54
class ExecutionResult(BaseModel): status; slug; rows; returned_rows; total_rows; truncated; columns;
                                  applied_conditions; rejected_inputs; duration_ms
# linked/pytransform.py:36 / :94
def validate_python_transform(spec: PythonTransform) -> list[str]          # [] when valid; multi-input rejected L49-50
async def apply_python_transform(frame: pd.DataFrame, spec: PythonTransform, *, max_rows: int) -> pd.DataFrame
# linked/models.py:178
class PythonTransform(BaseModel): transformer: str; params: dict = {}; input_alias: str = "source"; output: str | None = None
# runner.py:243
async def run(self, name: str, *, params: dict | None = None, pctx: Any | None = None,
              recipe_owner: str | None = None, include_envelope: bool = False) -> RenderedArtifact
#   include_envelope=True → RenderedArtifact.metadata["source_envelope"] = envelope.model_dump(by_alias=True, mode="json")
#   (runner.py:271-284; RenderedArtifact parrot/outputs/a2ui/artifacts.py:53). Fails OPEN on falsy pctx (docstring).
# a2ui/models.py:446 — CreateSurface.data_model has alias "dataModel" (L469) → the dumped dict key is "dataModel"
```

### Does NOT Exist
- ~~`RecipeRunner.run(data_model_path=…)`~~ / a single-value recipe mode — read the pointer yourself from
  `artifact.metadata["source_envelope"]["dataModel"]`.
- ~~`RenderedArtifact.envelope`~~ — the envelope is only in `metadata["source_envelope"]`.
- ~~`execute_slug(period=…)`~~ — periods arrive as placeholders.
- ~~Multi-input transformers~~ — `validate_python_transform` rejects them; surface its messages in a `ValueError`.
- ~~`transformer_registry.get` returning None~~ — it raises `KeyError` (transformers.py:148); `validate_python_transform`
  already reports unknown names, so do not call the registry directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/metrics/executors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/metrics/test_executors.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.execute_slug",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py#validate_python_transform",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py#apply_python_transform",
    "sym:packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py#RecipeRunner.run"
  ]
}
```

---

## Implementation Notes

- Period → placeholders: when `time.binding` has start/end placeholders, set them to ISO dates (`period.start.isoformat()`);
  when it has `date_column`, fetch without date placeholders and filter the frame to `[start, end]` post-fetch.
- Dimension → `grouping=[dimension.column]` (append to `source.grouping`), and add the column to `fields` when `fields`
  is non-empty. Caller `filters` merge over `source.filter` (caller wins).
- `linked_request(definition, period=…)`: `{"placeholders": …}` with UDF keywords from `period.udf_keywords`
  (keys `start`/`end` mapped to the binding placeholders) when set, else ISO dates; plus `filter/fields/ordering/grouping`.
- RecipeExecutor: `pctx = self._pctx_provider()`; `None`/falsy → `PermissionError` (R5). Map filters through
  `source.param_map`; the period is passed as `params[param_map.get("month","month")] = period.start.strftime("%Y-%m")`
  only when `binding.start_placeholder == "month"`. Pointer read with RFC 6901 unescaping (`~1`→`/`, `~0`→`~`).
  Scalar → `[{value_column: scalar}]` (`value_column` from a KPICardShape, else `"value"`); list of dicts → rows;
  dict of lists → columns-to-rows.
- `SourceFrame.linked_request` is set only by `QuerySlugExecutor` and `TransformerExecutor`.

---

## Implementation Blueprint

### Steps (in order)
1. `SourceFrame` + `SourceExecutor` Protocol — *why*: one return type for the toolkit.
2. `QuerySlugExecutor.fetch` + `linked_request` — *why*: core lane; transformer builds on it.
3. `TransformerExecutor` — validate first, then fetch input, then apply.
4. `RecipeExecutor` with pctx refusal and pointer read.
5. `executor_for` dispatch.

### `packages/ai-parrot-tools/src/parrot_tools/metrics/executors.py` (CREATE)
```python
"""Source executors: MetricDefinition + period → rows (spec §3 M6)."""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import pandas as pd
from pydantic import BaseModel, Field

from parrot.metrics.errors import MetricSourceUnavailable
from parrot.metrics.models import DimensionSpec, KPICardShape, MetricDefinition, MetricSource, QuerySlugSource, ResolvedPeriod
from parrot.outputs.a2ui.linked.models import PythonTransform
from parrot.outputs.a2ui.linked.pytransform import apply_python_transform, validate_python_transform
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot_tools.querysource import QuerysourceToolkit

logger = logging.getLogger(__name__)


class SourceFrame(BaseModel):
    """Rows fetched for one period, plus the linked request when the source can be linked."""
    rows: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    applied_conditions: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False
    linked_request: dict[str, Any] | None = None


class SourceExecutor(Protocol):
    async def fetch(self, definition: MetricDefinition, *, period: ResolvedPeriod, dimension: DimensionSpec | None,
                    filters: Mapping[str, Any], tenant: str | None) -> SourceFrame:
        """Fetch the rows for one period."""


class QuerySlugExecutor:
    """``query_slug``: placeholders ← period binding, filters ← filter grammar, grouping ← dimension."""

    def __init__(self, querysource: QuerysourceToolkit) -> None:
        self._qs = querysource

    def _request(self, definition: MetricDefinition, source: QuerySlugSource, *, period: ResolvedPeriod,
                 dimension: DimensionSpec | None, filters: Mapping[str, Any], use_udf: bool) -> dict[str, Any]:
        """execute_slug / build_linked_surface request dict for ``source``."""
        # FILL IN: placeholders/filter/fields/ordering/grouping/limit per Implementation Notes
        raise NotImplementedError

    async def fetch(self, definition: MetricDefinition, *, period: ResolvedPeriod, dimension: DimensionSpec | None,
                    filters: Mapping[str, Any], tenant: str | None) -> SourceFrame:
        """``execute_slug`` with the built request (QuerySource tenant = ``source.tenant``)."""
        source = definition.source
        req = self._request(definition, source, period=period, dimension=dimension, filters=filters, use_udf=False)
        result = await self._qs.execute_slug(source.slug, tenant=source.tenant, **req)
        # FILL IN: date_column post-filter; SourceFrame(rows, columns, applied_conditions, truncated, linked_request)
        raise NotImplementedError

    def linked_request(self, definition: MetricDefinition, *, period: ResolvedPeriod) -> dict[str, Any]:
        """Request dict for ``build_linked_surface`` (UDF keywords when expressible, else ISO dates)."""
        return self._request(definition, definition.source, period=period, dimension=None, filters={}, use_udf=True)


class TransformerExecutor:
    """``transformer``: fetch ``source.input`` then ``apply_python_transform`` by registered name."""

    def __init__(self, querysource: QuerysourceToolkit, *, max_rows: int = 5000) -> None:
        self._slug = QuerySlugExecutor(querysource)
        self._max_rows = max_rows

    async def fetch(self, definition: MetricDefinition, *, period: ResolvedPeriod, dimension: DimensionSpec | None,
                    filters: Mapping[str, Any], tenant: str | None) -> SourceFrame:
        """Validate the transform, fetch the input slug, apply the transformer."""
        source = definition.source
        spec = PythonTransform(transformer=source.transformer, params=source.params,
                               input_alias=source.input_alias, output=source.output)
        problems = validate_python_transform(spec)
        if problems:
            raise ValueError(f"metric {definition.id!r}: invalid transformer: {'; '.join(problems)}")
        # FILL IN: fetch via a definition copy whose source is source.input (model_copy(update={"source": source.input})),
        #   DataFrame(rows) → apply_python_transform(frame, spec, max_rows=self._max_rows) → SourceFrame; linked_request
        #   = self._slug.linked_request(input-copy, period=period)
        raise NotImplementedError


class RecipeExecutor:
    """``recipe``: replay a published recipe and read ``source.data_model_path`` from its envelope."""

    def __init__(self, runner: RecipeRunner, *, pctx_provider: Callable[[], Any]) -> None:
        self._runner = runner
        self._pctx_provider = pctx_provider

    async def fetch(self, definition: MetricDefinition, *, period: ResolvedPeriod, dimension: DimensionSpec | None,
                    filters: Mapping[str, Any], tenant: str | None) -> SourceFrame:
        """Run the recipe with a real pctx (fail closed) and convert the pointer value to rows."""
        pctx = self._pctx_provider()
        if not pctx:
            raise PermissionError("recipe metrics require a PermissionContext (RecipeRunner fails open without one)")
        source = definition.source
        # FILL IN: params (source.params + mapped filters + period), artifact = await self._runner.run(
        #   source.recipe_name, params=…, pctx=pctx, recipe_owner=source.recipe_owner, include_envelope=True);
        #   envelope = artifact.metadata["source_envelope"]; data_model = envelope.get("dataModel") (if absent, try the
        #   single nested message dict's "dataModel"); RFC 6901 pointer read; shape value → rows per Implementation Notes
        raise NotImplementedError


def executor_for(source: MetricSource, *, querysource: QuerysourceToolkit | None, runner: RecipeRunner | None,
                 pctx_provider: Callable[[], Any] | None) -> SourceExecutor:
    """Dispatch on ``source.kind``; ``semantic_metric`` raises ``MetricSourceUnavailable`` (FEAT-704)."""
    if source.kind == "semantic_metric":
        raise MetricSourceUnavailable("semantic_metric sources are reserved for FEAT-704 and cannot run here")
    # FILL IN: query_slug/transformer need querysource; recipe needs runner AND pctx_provider — missing → ValueError
    raise NotImplementedError
```
**Why this shape**: signatures fixed by spec M6; validation before fetch keeps a bad transformer from costing a query.

### FILL IN checklist
- [ ] `_request` and date_column post-filter
- [ ] TransformerExecutor fetch/apply
- [ ] RecipeExecutor params, envelope read, pointer conversion
- [ ] `executor_for` dispatch

---

## Acceptance Criteria

- [ ] `QuerySlugExecutor` passes ISO period placeholders, merged filter, dimension grouping to `execute_slug`.
- [ ] `linked_request` uses UDF keywords when `period.udf_keywords` is set.
- [ ] Single-input transformer accepted; a transformer failing `validate_python_transform` → `ValueError`.
- [ ] `RecipeExecutor` reads scalar / list / dict pointers from `metadata["source_envelope"]["dataModel"]`; refuses falsy pctx.
- [ ] `executor_for(semantic_metric)` raises `MetricSourceUnavailable`.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/metrics/test_executors.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/metrics/test_executors.py
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from parrot.metrics.errors import MetricSourceUnavailable
from parrot.metrics.models import MetricDefinition, ResolvedPeriod
from parrot_tools.metrics.executors import QuerySlugExecutor, RecipeExecutor, executor_for

PERIOD = ResolvedPeriod(preset="this_month", start=date(2026, 10, 1), end=date(2026, 10, 31), label="October 2026",
                        udf_keywords={"start": "FDOM", "end": "LDOM"})

def _def(source: dict) -> MetricDefinition:
    return MetricDefinition.model_validate({
        "id": "worked_hours", "name": "Worked Hours",
        "time": {"binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"}},
        "default_shape": {"component": "KPICard", "value_column": "hours"}, "source": source})

async def test_query_slug_executor_request():
    qs = SimpleNamespace(execute_slug=AsyncMock(return_value=SimpleNamespace(
        rows=[{"hours": 5}], columns=["hours"], applied_conditions={}, truncated=False)))
    frame = await QuerySlugExecutor(qs).fetch(_def({"kind": "query_slug", "slug": "flex_hours"}),
                                              period=PERIOD, dimension=None, filters={}, tenant=None)
    kwargs = qs.execute_slug.await_args.kwargs
    assert kwargs["placeholders"] == {"firstdate": "2026-10-01", "lastdate": "2026-10-31"}
    assert frame.rows == [{"hours": 5}]

async def test_recipe_executor_refuses_none_pctx():
    ex = RecipeExecutor(AsyncMock(), pctx_provider=lambda: None)
    d = _def({"kind": "recipe", "recipe_name": "flex", "data_model_path": "/payroll_hero/worked_hours_total"})
    with pytest.raises(PermissionError):
        await ex.fetch(d, period=PERIOD, dimension=None, filters={}, tenant=None)

def test_semantic_metric_unavailable():
    d = _def({"kind": "semantic_metric", "model": "m", "metric": "x"})
    with pytest.raises(MetricSourceUnavailable):
        executor_for(d.source, querysource=None, runner=None, pctx_provider=None)

# FILL IN: test_recipe_executor_pointer_read (scalar/list/dict via stub run() returning
#   SimpleNamespace(metadata={"source_envelope": {"dataModel": {...}}})); test_transformer_executor_single_input
#   (monkeypatch validate_python_transform → [] / ["multi-input"]); test_linked_request_uses_udf
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4849 is `done`.
2. Re-verify `runner.py:243-284` (envelope location) and `pytransform.py:36-52` before coding.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4851 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
