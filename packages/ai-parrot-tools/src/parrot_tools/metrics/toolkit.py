"""MetricsToolkit — tenant-scoped metric registry tools (FEAT-756, spec §3 M5)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import date
from typing import Any, Literal

from parrot.metrics.context import resolve_metric_tenant
from parrot.metrics.models import (
    ChartShape,
    DataTableShape,
    KPICardShape,
    MetricDefinition,
    PeriodPreset,
    ResolvedPeriod,
    ShapeSpec,
)
from parrot.metrics.registry import MetricRegistry
from parrot.metrics.store import InMemoryMetricStore, MetricStore
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.tools.toolkit import AbstractToolkit
from parrot.utils.helpers import current_context
from parrot_tools.querysource import QuerysourceToolkit
from parrot_tools.ui_surfaces import PublishSurfaceTool

from .executors import executor_for
from .models import MetricExplanation, MetricSummary, QueryMetricResult
from .periods import comparison_period, resolve_period, series_buckets
from .shapes import KPIFigures, aggregate, build_linked_metric_envelope, build_metric_envelope, figures

_CALL_TENANT: ContextVar[str | None] = ContextVar("parrot_metrics_call_tenant", default=None)


class MetricsToolkit(AbstractToolkit):
    """Tenant-scoped metric registry tools: list, describe, query (default-shape A2UI envelope) and explain."""

    exclude_tools: tuple[str, ...] = ("open", "close")

    def __init__(
        self,
        registry: MetricRegistry | None = None,
        *,
        store: MetricStore | None = None,
        querysource: QuerysourceToolkit | None = None,
        recipe_runner: RecipeRunner | None = None,
        pctx_provider: Callable[[], Any] | None = None,
        default_tenant: str | None = None,
        max_rows: int = 200,
        allow_pin: bool = True,
        publish_tool: PublishSurfaceTool | None = None,
        **kwargs: Any,
    ) -> None:
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

    def _get_querysource(self) -> QuerysourceToolkit:
        """Lazily build the QuerySource toolkit from ``querysource_kwargs``."""
        if self._querysource is None:
            self._querysource = QuerysourceToolkit(**self._querysource_kwargs)
        return self._querysource

    @property
    def _call_tenant(self) -> str | None:
        """Tenant bound to the current task's tool call (never shared across concurrent calls)."""
        return _CALL_TENANT.get()

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Resolve the effective tenant (D3) for this call and bind it to the current task.

        A tenant argument supplied by the model is never honoured: the tenant comes only from
        the request context, the request-local skill tenant, or the toolkit default.
        """
        await super()._pre_execute(tool_name, **kwargs)
        _CALL_TENANT.set(resolve_metric_tenant(None, current_context(), self.default_tenant))

    @staticmethod
    def _caller_id() -> str | None:
        """Return the calling user's id from the request context, when one is bound."""
        ctx = current_context()
        if ctx is None:
            return None
        user_id = getattr(ctx, "user_id", None)
        kwargs = getattr(ctx, "kwargs", None)
        if not user_id and isinstance(kwargs, dict):
            user_id = kwargs.get("user_id")
        return str(user_id) if user_id else None

    async def _describe(self, metric_id: str) -> MetricDefinition:
        """Return one effective, caller-visible metric or raise ``MetricNotFound``.

        The registry hides ``private`` definitions from everyone but their owner.
        """
        return await self.registry.describe(metric_id, tenant=self._call_tenant, user_id=self._caller_id())

    async def list_metrics(self, search: str | None = None, program: str | None = None) -> list[MetricSummary]:
        """List the metrics visible in this tenant.

        ``search`` filters name, aliases, and description case-insensitively.
        """
        definitions = await self.registry.list(tenant=self._call_tenant, program=program, user_id=self._caller_id())
        needle = search.casefold().strip() if search else ""
        if needle:
            definitions = [
                definition
                for definition in definitions
                if needle in " ".join([definition.name, definition.description, *definition.aliases]).casefold()
            ]
        return [
            MetricSummary(
                id=definition.id,
                name=definition.name,
                unit=definition.unit,
                default_component=definition.default_shape.component,
                tenant=definition.tenant,
                program=definition.program,
                dimensions=[dimension.name for dimension in definition.dimensions],
                source_kind=definition.source.kind,
            )
            for definition in definitions
        ]

    async def describe_metric(self, metric_id: str) -> MetricDefinition:
        """Return the full definition of one metric (source, unit, dimensions, default period and shape)."""
        return await self._describe(metric_id)

    def _shape_for_query(self, definition: MetricDefinition, requested: str | None, dimension: Any | None) -> ShapeSpec:
        """Return the declared or safely derived display shape for this request."""
        default = definition.default_shape
        value_column = default.value_column if isinstance(default, KPICardShape) else "value"
        if requested is None and dimension is not None and isinstance(default, KPICardShape):
            return ChartShape(chart_type="line", x=dimension.column, y=[value_column])
        if requested is None or requested == default.component:
            return default
        if requested == "KPICard":
            return KPICardShape(value_column=value_column)
        if requested == "Chart":
            x = dimension.column if dimension is not None else definition.time.binding.date_column or value_column
            return ChartShape(chart_type="line", x=x, y=[value_column])
        if requested == "DataTable":
            return DataTableShape(columns=[])
        raise ValueError(f"metric {definition.id!r}: cannot derive {requested} shape from its declared definition")

    @staticmethod
    def _single_placeholder(definition: MetricDefinition) -> bool:
        """Return whether the source expresses its period through one placeholder."""
        binding = definition.time.binding
        return bool(binding.start_placeholder and binding.start_placeholder == binding.end_placeholder)

    @staticmethod
    def _series(
        definition: MetricDefinition, period: ResolvedPeriod, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        """Build a KPI series when a declared date column and grain are available."""
        date_column = definition.time.binding.date_column
        shape = definition.default_shape
        if not date_column or not definition.time.series_grain or not isinstance(shape, KPICardShape):
            return None
        totals: dict[date, Any] = {}
        for row in rows:
            raw_date = row.get(date_column)
            if isinstance(raw_date, str):
                try:
                    raw_date = date.fromisoformat(raw_date[:10])
                except ValueError:
                    continue
            if not isinstance(raw_date, date):
                continue
            totals[raw_date] = (totals.get(raw_date, 0) or 0) + (row.get(shape.value_column, 0) or 0)
        return [
            {"date": bucket.isoformat(), "value": totals.get(bucket, 0)}
            for bucket in series_buckets(period, definition.time.series_grain)
        ]

    async def query_metric(
        self,
        metric_id: str,
        period: PeriodPreset | None = None,
        by: str | None = None,
        filters: dict[str, Any] | None = None,
        compare: bool | None = None,
        shape: Literal["KPICard", "Chart", "DataTable", "Map"] | None = None,
        linked: bool = False,
        pin: bool = False,
        title: str | None = None,
    ) -> QueryMetricResult:
        """Execute a metric and return its value plus a ready A2UI envelope.

        The metric's default shape is used unless overridden; ``by`` uses a
        declared dimension and derives a chart from a KPI metric.
        """
        started = time.monotonic()
        definition = await self._describe(metric_id)
        dimension = definition.dimension(by) if by else None
        if by and dimension is None:
            declared = ", ".join(dimension.name for dimension in definition.dimensions) or "none"
            raise ValueError(f"metric {metric_id!r} has no dimension {by!r}; declared dimensions: {declared}")
        selected_shape = self._shape_for_query(definition, shape, dimension)
        resolved_period = resolve_period(
            period or definition.time.default_period,
            grain=definition.time.grain,
            single_placeholder=self._single_placeholder(definition),
        )
        if linked and definition.source.kind not in ("query_slug", "transformer"):
            raise ValueError("only query_slug/transformer metrics can be linked")
        needs_querysource = definition.source.kind in ("query_slug", "transformer")
        executor = executor_for(
            definition.source,
            querysource=self._get_querysource() if needs_querysource else None,
            runner=self._recipe_runner,
            pctx_provider=self._pctx_provider,
        )
        current_frame = await executor.fetch(
            definition,
            period=resolved_period,
            dimension=dimension,
            filters=filters or {},
            tenant=self._call_tenant,
        )
        do_compare = (
            compare
            if compare is not None
            else definition.comparison.mode != "none" and isinstance(selected_shape, KPICardShape)
        )
        previous_period = comparison_period(resolved_period, definition.comparison) if do_compare else None
        previous_frame = None
        if previous_period is not None:
            previous_frame = await executor.fetch(
                definition,
                period=previous_period,
                dimension=dimension,
                filters=filters or {},
                tenant=self._call_tenant,
            )
        current_rows = current_frame.rows[: self.max_rows]
        previous_rows = previous_frame.rows[: self.max_rows] if previous_frame else []
        fig: KPIFigures | None = None
        if isinstance(selected_shape, KPICardShape):
            current_value = aggregate(current_rows, selected_shape)
            previous_value = aggregate(previous_rows, selected_shape) if previous_frame else None
            fig = figures(
                current_value,
                previous_value,
                policy=definition.comparison,
                period=resolved_period,
                comparison=previous_period,
                series=self._series(definition, resolved_period, current_rows),
            )
        if linked:
            if current_frame.linked_request is None:
                raise ValueError(f"metric {metric_id!r} cannot build a linked request")
            comparison_request = previous_frame.linked_request if previous_frame else None
            envelope: dict[str, Any] = await build_linked_metric_envelope(
                self._get_querysource(),
                definition,
                shape=selected_shape,
                request=current_frame.linked_request,
                comparison_request=comparison_request,
                refresh=None,
                snapshot=False,
                surface_id=f"metric-{definition.id}",
            )
        else:
            built = build_metric_envelope(
                definition,
                shape=selected_shape,
                fig=fig,
                rows=current_rows,
                surface_id=f"metric-{definition.id}",
                title=title,
            )
            envelope = built.model_dump(mode="json")
        surface_id = None
        if pin:
            if not self.allow_pin:
                raise PermissionError("pinning metric surfaces is disabled")
            if self._publish_tool is None:
                raise ValueError("pin=True requires a publish_tool")
            publish_kwargs: dict[str, Any] = {"kind": "widget", "title": title or definition.name, "envelope": envelope}
            if definition.source.kind == "recipe":
                publish_kwargs.update(
                    recipe_name=definition.source.recipe_name,
                    recipe_owner=definition.source.recipe_owner,
                    recipe_params=definition.source.params,
                )
            surface_id = (await self._publish_tool._execute(**publish_kwargs)).get("surface_id")
        return QueryMetricResult(
            metric_id=definition.id,
            period=resolved_period,
            comparison_period=previous_period,
            value=fig.value if fig else None,
            previous=fig.previous if fig else None,
            delta=fig.delta if fig else None,
            delta_pct=fig.delta_pct if fig else None,
            trend=fig.trend if fig else None,
            rows=current_rows,
            envelope=envelope,
            linked=linked,
            surface_id=surface_id,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def explain_metric(self, metric_id: str) -> MetricExplanation:
        """Explain how a metric is computed without calling an LLM."""
        definition = await self._describe(metric_id)
        source = definition.source
        slug = None
        if source.kind == "query_slug":
            source_line = f"Source: query slug {source.slug}."
            slug = source.slug
        elif source.kind == "transformer":
            source_line = f"Source: transformer {source.transformer} over query slug {source.input.slug}."
            slug = source.input.slug
        elif source.kind == "recipe":
            source_line = f"Source: recipe {source.recipe_name}, data pointer {source.data_model_path}."
        else:
            source_line = f"Source: semantic metric {source.model}.{source.metric}."
        binding = definition.time.binding
        filters = getattr(source, "filter", {})
        lineage = " ".join(
            [
                source_line,
                f"Filters: {filters or 'none'}.",
                f"Default period: {definition.time.default_period}; binding: {binding.model_dump(exclude_none=True)}.",
                f"Comparison policy: {definition.comparison.mode}.",
                f"Unit/format: {definition.unit or 'none'}/{definition.format or 'none'}.",
                f"Default shape: {definition.default_shape.component} (declared default_shape).",
            ]
        )
        source_detail = None
        if slug is not None and self._querysource is not None:
            try:
                source_detail = await self._querysource.describe_slug(slug)
            except Exception as exc:
                self.logger.warning("metric %s source detail unavailable: %s", metric_id, exc)
        return MetricExplanation(definition=definition, lineage=lineage, source_detail=source_detail)
