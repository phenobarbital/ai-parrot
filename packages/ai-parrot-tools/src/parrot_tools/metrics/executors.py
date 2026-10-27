"""Source executors: MetricDefinition + period → rows (spec §3 M6)."""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import pandas as pd
from pydantic import BaseModel, Field

from parrot.metrics.errors import MetricSourceUnavailable
from parrot.metrics.models import (
    DimensionSpec,
    KPICardShape,
    MetricDefinition,
    MetricSource,
    QuerySlugSource,
    ResolvedPeriod,
)
from parrot.outputs.a2ui.linked.models import PythonTransform
from parrot.outputs.a2ui.linked.pytransform import apply_python_transform, validate_python_transform
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot_tools.querysource import QuerysourceToolkit

logger = logging.getLogger(__name__)

_MISSING = object()


class SourceFrame(BaseModel):
    """Rows fetched for one period, plus the linked request when the source can be linked."""

    rows: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    applied_conditions: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False
    linked_request: dict[str, Any] | None = None


class SourceExecutor(Protocol):
    """Protocol implemented by every per-kind source executor."""

    async def fetch(
        self,
        definition: MetricDefinition,
        *,
        period: ResolvedPeriod,
        dimension: DimensionSpec | None,
        filters: Mapping[str, Any],
        tenant: str | None,
    ) -> SourceFrame:
        """Fetch the rows for one period."""


def _filter_by_date(rows: list[dict[str, Any]], column: str, period: ResolvedPeriod) -> list[dict[str, Any]]:
    """Keep rows whose ``column`` falls within ``[period.start, period.end]``.

    Args:
        rows: Fetched rows.
        column: Date column name.
        period: Resolved period.

    Returns:
        The filtered rows (rows with unparseable/missing dates are dropped).
    """
    if not rows:
        return rows
    start = pd.Timestamp(period.start)
    end = pd.Timestamp(period.end)
    kept: list[dict[str, Any]] = []
    for row in rows:
        value = row.get(column)
        if value is None:
            continue
        try:
            ts = pd.Timestamp(value)
        except (ValueError, TypeError):
            continue
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        if start <= ts.normalize() <= end:
            kept.append(row)
    return kept


class QuerySlugExecutor:
    """``query_slug``: placeholders ← period binding, filters ← filter grammar, grouping ← dimension."""

    def __init__(self, querysource: QuerysourceToolkit) -> None:
        self._qs = querysource

    def _request(
        self,
        definition: MetricDefinition,
        source: QuerySlugSource,
        *,
        period: ResolvedPeriod,
        dimension: DimensionSpec | None,
        filters: Mapping[str, Any],
        use_udf: bool,
    ) -> dict[str, Any]:
        """execute_slug / build_linked_surface request dict for ``source``."""
        binding = definition.time.binding
        placeholders: dict[str, Any] = dict(source.placeholders)
        if binding.start_placeholder and binding.end_placeholder:
            udf = period.udf_keywords if use_udf else None
            if udf and "start" in udf and "end" in udf:
                placeholders[binding.start_placeholder] = udf["start"]
                placeholders[binding.end_placeholder] = udf["end"]
            else:
                placeholders[binding.start_placeholder] = period.start.isoformat()
                placeholders[binding.end_placeholder] = period.end.isoformat()
        merged_filter: dict[str, Any] = {**source.filter, **dict(filters)}
        fields = list(source.fields)
        grouping = list(source.grouping)
        if dimension is not None:
            if dimension.column not in grouping:
                grouping.append(dimension.column)
            if fields and dimension.column not in fields:
                fields.append(dimension.column)
        if fields and binding.date_column and binding.date_column not in fields and not use_udf:
            fields.append(binding.date_column)
        req: dict[str, Any] = {
            "placeholders": placeholders or None,
            "filter": merged_filter or None,
            "fields": fields or None,
            "ordering": list(source.ordering) or None,
            "grouping": grouping or None,
        }
        if source.limit is not None:
            req["limit"] = source.limit
        return req

    async def fetch(
        self,
        definition: MetricDefinition,
        *,
        period: ResolvedPeriod,
        dimension: DimensionSpec | None,
        filters: Mapping[str, Any],
        tenant: str | None,
    ) -> SourceFrame:
        """``execute_slug`` with the built request (QuerySource tenant = ``source.tenant``)."""
        source = definition.source
        req = self._request(definition, source, period=period, dimension=dimension, filters=filters, use_udf=False)
        result = await self._qs.execute_slug(source.slug, tenant=source.tenant, **req)
        rows = list(result.rows or [])
        date_column = definition.time.binding.date_column
        if date_column:
            rows = _filter_by_date(rows, date_column, period)
        return SourceFrame(
            rows=rows,
            columns=list(result.columns or []),
            applied_conditions=dict(result.applied_conditions or {}),
            truncated=bool(result.truncated),
            linked_request=self.linked_request(definition, period=period),
        )

    def linked_request(self, definition: MetricDefinition, *, period: ResolvedPeriod) -> dict[str, Any]:
        """Request dict for ``build_linked_surface`` (UDF keywords when expressible, else ISO dates)."""
        return self._request(definition, definition.source, period=period, dimension=None, filters={}, use_udf=True)


class TransformerExecutor:
    """``transformer``: fetch ``source.input`` then ``apply_python_transform`` by registered name."""

    def __init__(self, querysource: QuerysourceToolkit, *, max_rows: int = 5000) -> None:
        self._slug = QuerySlugExecutor(querysource)
        self._max_rows = max_rows

    async def fetch(
        self,
        definition: MetricDefinition,
        *,
        period: ResolvedPeriod,
        dimension: DimensionSpec | None,
        filters: Mapping[str, Any],
        tenant: str | None,
    ) -> SourceFrame:
        """Validate the transform, fetch the input slug, apply the transformer."""
        source = definition.source
        spec = PythonTransform(
            transformer=source.transformer,
            params=source.params,
            input_alias=source.input_alias,
            output=source.output,
        )
        problems = validate_python_transform(spec)
        if problems:
            raise ValueError(f"metric {definition.id!r}: invalid transformer: {'; '.join(problems)}")
        input_def = definition.model_copy(update={"source": source.input})
        raw = await self._slug.fetch(input_def, period=period, dimension=dimension, filters=filters, tenant=tenant)
        frame = pd.DataFrame(raw.rows)
        out = await apply_python_transform(frame, spec, max_rows=self._max_rows)
        out = out.astype(object).where(pd.notna(out), None)
        return SourceFrame(
            rows=out.to_dict(orient="records"),
            columns=[str(c) for c in out.columns],
            applied_conditions=raw.applied_conditions,
            truncated=raw.truncated,
            linked_request=self._slug.linked_request(input_def, period=period),
        )


def _read_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON pointer against ``document``.

    Args:
        document: The root object.
        pointer: The pointer (``""`` or ``"/a/b"``).

    Returns:
        The referenced value.

    Raises:
        KeyError: When the pointer does not resolve.
    """
    if pointer in ("", "/"):
        return document
    if not pointer.startswith("/"):
        pointer = "/" + pointer
    current = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(f"data_model_path segment {token!r} not found")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"data_model_path index {token!r} invalid") from exc
        else:
            raise KeyError(f"data_model_path segment {token!r} not traversable")
    return current


class RecipeExecutor:
    """``recipe``: replay a published recipe and read ``source.data_model_path`` from its envelope."""

    def __init__(self, runner: RecipeRunner, *, pctx_provider: Callable[[], Any]) -> None:
        self._runner = runner
        self._pctx_provider = pctx_provider

    async def fetch(
        self,
        definition: MetricDefinition,
        *,
        period: ResolvedPeriod,
        dimension: DimensionSpec | None,
        filters: Mapping[str, Any],
        tenant: str | None,
    ) -> SourceFrame:
        """Run the recipe with a real pctx (fail closed) and convert the pointer value to rows."""
        pctx = self._pctx_provider()
        if not pctx:
            raise PermissionError("recipe metrics require a PermissionContext (RecipeRunner fails open without one)")
        source = definition.source
        params: dict[str, Any] = dict(source.params)
        for key, value in filters.items():
            params[source.param_map.get(key, key)] = value
        if definition.time.binding.start_placeholder == "month":
            params[source.param_map.get("month", "month")] = period.start.strftime("%Y-%m")
        artifact = await self._runner.run(
            source.recipe_name,
            params=params,
            pctx=pctx,
            recipe_owner=source.recipe_owner,
            include_envelope=True,
        )
        metadata = getattr(artifact, "metadata", None) or {}
        envelope = metadata.get("source_envelope")
        if not isinstance(envelope, Mapping):
            raise ValueError(f"metric {definition.id!r}: recipe {source.recipe_name!r} returned no source envelope")
        data_model = envelope.get("dataModel", _MISSING)
        if data_model is _MISSING:
            nested = [v for v in envelope.values() if isinstance(v, Mapping) and "dataModel" in v]
            if len(nested) == 1:
                data_model = nested[0]["dataModel"]
            else:
                raise ValueError(f"metric {definition.id!r}: recipe envelope has no dataModel")
        try:
            value = _read_pointer(data_model, source.data_model_path)
        except KeyError as exc:
            raise ValueError(f"metric {definition.id!r}: {exc}") from exc
        rows = self._to_rows(definition, value)
        columns: list[str] = []
        for row in rows:
            for col in row:
                if col not in columns:
                    columns.append(col)
        return SourceFrame(rows=rows, columns=columns)

    @staticmethod
    def _to_rows(definition: MetricDefinition, value: Any) -> list[dict[str, Any]]:
        """Convert a pointer value to rows (scalar / list of dicts / dict of lists)."""
        if isinstance(value, list):
            if all(isinstance(v, Mapping) for v in value):
                return [dict(v) for v in value]
            raise ValueError(f"metric {definition.id!r}: data_model_path list must contain objects")
        if isinstance(value, Mapping):
            if value and all(isinstance(v, list) for v in value.values()):
                keys = list(value.keys())
                length = max(len(v) for v in value.values())
                return [
                    {k: (value[k][i] if i < len(value[k]) else None) for k in keys} for i in range(length)
                ]
            return [dict(value)]
        shape = definition.default_shape
        column = shape.value_column if isinstance(shape, KPICardShape) else "value"
        return [{column: value}]


def executor_for(
    source: MetricSource,
    *,
    querysource: QuerysourceToolkit | None,
    runner: RecipeRunner | None,
    pctx_provider: Callable[[], Any] | None,
) -> SourceExecutor:
    """Dispatch on ``source.kind``; ``semantic_metric`` raises ``MetricSourceUnavailable`` (FEAT-704)."""
    if source.kind == "semantic_metric":
        raise MetricSourceUnavailable("semantic_metric sources are reserved for FEAT-704 and cannot run here")
    if source.kind == "query_slug":
        if querysource is None:
            raise ValueError("query_slug metric sources require a QuerysourceToolkit")
        return QuerySlugExecutor(querysource)
    if source.kind == "transformer":
        if querysource is None:
            raise ValueError("transformer metric sources require a QuerysourceToolkit")
        return TransformerExecutor(querysource)
    if source.kind == "recipe":
        if runner is None or pctx_provider is None:
            raise ValueError("recipe metric sources require a RecipeRunner and a pctx_provider")
        return RecipeExecutor(runner, pctx_provider=pctx_provider)
    raise ValueError(f"unknown metric source kind {source.kind!r}")
