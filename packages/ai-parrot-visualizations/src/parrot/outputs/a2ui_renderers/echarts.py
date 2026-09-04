"""ECharts payload renderer (Module 5, satellite).

Deterministic replacement for the legacy ``formats/echarts.py`` (which loaded ECharts
from a CDN). This renderer emits the ECharts **option JSON** as its primary output from
a baked ``Chart`` component's data; an optional HTML wrap inlines the *vendored*
``formats/assets/echarts.min.js`` bundle (never a CDN ``<script src>``).

Security (G1): no code strings, no ``exec``; the option payload is a plain dict built
from validated component data.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any

import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog.base import BasicNode
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degradation_record

logger = logging.getLogger(__name__)

_SURFACE_NAME = "echarts"

# Vendored ECharts bundle (shared with the legacy infographic HTML renderer).
_ECHARTS_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "echarts.min.js"

# A2UI Chart type → ECharts series type.
_SERIES_TYPE = {
    "bar": "bar",
    "line": "line",
    "area": "line",
    "scatter": "scatter",
    "pie": "pie",
    "donut": "pie",
    "radar": "radar",
    "gauge": "gauge",
    "funnel": "funnel",
    "treemap": "treemap",
    "heatmap": "heatmap",
}

#: Chart types with a fundamentally different ECharts series shape than the
#: standard "one series per y column, values = column values" loop — built by
#: their own dedicated methods below (FEAT-527).
_ROW_NATIVE_TYPES = frozenset({"gauge", "funnel", "treemap", "heatmap", "waterfall", "radar"})


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output="application/json",
        supported_components={"Chart"},
    ),
)
class EChartsRenderer(AbstractA2UIRenderer):
    """Chart-component → ECharts option JSON renderer (+ optional vendored HTML wrap)."""

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
        wrap_html: bool = False,
    ) -> RenderedArtifact:
        """Render the first Chart component to an ECharts option (JSON or HTML wrap).

        Args:
            envelope: The validated envelope containing a ``Chart`` component.
            bake: Bindings are always resolved (static output).
            wrap_html: When ``True``, emit a self-contained HTML document inlining the
                vendored ECharts bundle instead of raw option JSON.

        Returns:
            A ``RenderedArtifact`` (``application/json`` or ``text/html``); any
            sibling component this renderer does not render is recorded in
            ``metadata["degraded"]`` (AC-G3 — degradation must be visible,
            never silent).

        Raises:
            ValueError: If the envelope contains no ``Chart`` component.
        """
        baked = bake_envelope(envelope)
        chart = next((c for c in baked if c["component"] == "Chart"), None)
        if chart is None:
            raise ValueError("echarts renderer requires a 'Chart' component in the envelope.")

        degradations = [
            degradation_record(
                BasicNode(id=item["id"], component=item["component"]),
                f"{_SURFACE_NAME} renderer only renders a single Chart component per surface",
            )
            for item in baked
            if item is not chart
        ]

        option = self._build_option(chart)

        if wrap_html:
            document = self._wrap_html(option, chart.get("title", ""))
            return RenderedArtifact(
                artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
                mime_type="text/html",
                content=document.encode("utf-8"),
                filename=f"{envelope.surface_id}.html",
                title=envelope.surface_id,
                surface=_SURFACE_NAME,
                metadata={"degraded": degradations} if degradations else {},
            )

        content = json.dumps(option, sort_keys=True).encode("utf-8")
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="application/json",
            content=content,
            filename=f"{envelope.surface_id}.json",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
            metadata={"degraded": degradations} if degradations else {},
        )

    # -- internal -----------------------------------------------------------

    def _build_option(self, props: dict[str, Any]) -> dict[str, Any]:
        """Build a deterministic ECharts option dict from Chart component data.

        FEAT-473 (G7): additionally honours ``stacked`` (``series.stack``),
        ``splitSeries`` (one grid/axis pair per y series), ``trendline`` (an
        extra linear-regression series per y column), ``colorBySign`` +
        ``negativeColor``/``positiveColor`` (a piecewise ``visualMap``),
        ``xAxisLabel``/``yAxisLabel`` (axis ``name``), and ``palette``
        (top-level ``color``). Every new prop is read with a default that
        preserves the pre-FEAT-473 option shape when absent (regression
        safety — envelopes without these props render exactly as before).

        FEAT-527: ``gauge``/``funnel``/``treemap``/``heatmap``/``waterfall``/
        ``radar`` have a fundamentally different ECharts series shape than
        the standard per-y-column loop below and are built by their own
        dedicated ``_build_*`` methods (early return); ``donut`` reuses the
        standard ``pie`` loop with a ``radius`` tweak.
        """
        chart_type = props.get("type", "bar")
        series_type = _SERIES_TYPE.get(chart_type, "bar")
        x = props.get("x")
        y_cols = props.get("y") or []
        rows = props.get("data") or []
        if not isinstance(rows, list):
            rows = []
        stacked = bool(props.get("stacked"))
        trendline = bool(props.get("trendline"))

        categories = [row.get(x) for row in rows if isinstance(row, dict)] if x else []

        base_option: dict[str, Any] = {
            "title": {"text": props.get("title", "")},
            "legend": {"show": bool(props.get("showLegend", True))},
        }

        if chart_type in _ROW_NATIVE_TYPES:
            base_option["series"] = self._build_row_native_series(chart_type, x, y_cols, rows, categories)
            if chart_type == "heatmap":
                base_option["visualMap"] = self._heatmap_visual_map(base_option["series"])
                base_option["xAxis"] = {"type": "category", "data": categories}
                base_option["yAxis"] = {"type": "category", "data": list(y_cols)}
            elif chart_type == "radar":
                base_option["radar"] = {"indicator": [{"name": str(c)} for c in categories]}
            return base_option

        series = []
        for col in y_cols:
            values = [row.get(col) for row in rows if isinstance(row, dict)]
            series_entry: dict[str, Any] = {"name": col, "type": series_type, "data": values}
            if chart_type == "area":
                series_entry["areaStyle"] = {}
            if chart_type == "donut":
                series_entry["radius"] = ["40%", "70%"]
            if stacked:
                series_entry["stack"] = "total"
            series.append(series_entry)

        if trendline and series:
            first_col = y_cols[0]
            first_values = [row.get(first_col) for row in rows if isinstance(row, dict)]
            trend_values = self._linear_trend(first_values)
            if trend_values:
                series.append(
                    {
                        "name": f"{first_col} Trend",
                        "type": "line",
                        "data": trend_values,
                        "smooth": True,
                        "symbol": "none",
                    }
                )

        option: dict[str, Any] = {
            "title": {"text": props.get("title", "")},
            "legend": {"show": bool(props.get("showLegend", True))},
            "series": series,
        }

        palette = props.get("palette")
        if palette:
            option["color"] = list(palette)

        if props.get("colorBySign"):
            # Bug fix (post-review): series.data here is a flat scalar array
            # (e.g. [10, -5, 20]) built above, not [x, y] pairs — the value
            # to colour by is dimension 0, not 1. `dimension: 1` targeted a
            # nonexistent second dimension, so colorBySign silently had no
            # effect (no error, just no coloring).
            option["visualMap"] = {
                "type": "piecewise",
                "show": False,
                "dimension": 0,
                "pieces": [
                    {"max": 0, "color": props.get("negativeColor") or "#d62728"},
                    {"min": 0, "color": props.get("positiveColor") or "#2ca02c"},
                ],
            }

        if series_type != "pie":
            split_series = bool(props.get("splitSeries")) and len(series) > 1
            x_axis_label = props.get("xAxisLabel")
            y_axis_label = props.get("yAxisLabel")
            if split_series:
                n = len(series)
                option["grid"] = [{"top": f"{int(i * 100 / n)}%", "height": f"{int(100 / n) - 5}%"} for i in range(n)]
                option["xAxis"] = [
                    {"type": "category", "data": categories, "gridIndex": i, "name": x_axis_label} for i in range(n)
                ]
                option["yAxis"] = [{"type": "value", "gridIndex": i, "name": y_axis_label} for i in range(n)]
                for i, series_entry in enumerate(series):
                    series_entry["xAxisIndex"] = i
                    series_entry["yAxisIndex"] = i
            else:
                x_axis: dict[str, Any] = {"type": "category", "data": categories}
                y_axis: dict[str, Any] = {"type": "value"}
                if x_axis_label:
                    x_axis["name"] = x_axis_label
                if y_axis_label:
                    y_axis["name"] = y_axis_label
                option["xAxis"] = x_axis
                option["yAxis"] = y_axis
        return option

    @staticmethod
    def _linear_trend(values: list[Any]) -> list[float]:
        """Compute a simple linear-regression trend line over ``values``.

        Args:
            values: The series' numeric values (non-numeric entries treated as 0).

        Returns:
            One fitted value per input point, or ``[]`` if ``values`` is empty.
        """
        numeric = [v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0 for v in values]
        n = len(numeric)
        if n == 0:
            return []
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(numeric) / n
        denom = sum((x - mean_x) ** 2 for x in xs) or 1
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, numeric)) / denom
        intercept = mean_y - slope * mean_x
        return [slope * x + intercept for x in xs]

    def _build_row_native_series(
        self,
        chart_type: str,
        x: str | None,
        y_cols: list[str],
        rows: list[dict[str, Any]],
        categories: list[Any],
    ) -> list[dict[str, Any]]:
        """Build the ``series`` list for a chart type with a native, non-
        per-y-column ECharts shape (FEAT-527).

        Args:
            chart_type: One of ``gauge``/``funnel``/``treemap``/``heatmap``/
                ``waterfall``/``radar``.
            x: The x/category column name.
            y_cols: Value column names.
            rows: Bound data rows.
            categories: Pre-extracted ``row[x]`` values (row order).

        Returns:
            The ECharts ``series`` array for this chart type.
        """
        if chart_type == "gauge":
            # One data point per y column — gauge ignores x entirely.
            return [
                {
                    "name": col,
                    "type": "gauge",
                    "data": [{"value": next((row.get(col) for row in rows if isinstance(row, dict)), None), "name": col}],
                }
                for col in y_cols
            ]

        if chart_type == "funnel":
            first_col = y_cols[0] if y_cols else None
            data = [
                {"value": row.get(first_col), "name": row.get(x)}
                for row in rows
                if isinstance(row, dict)
            ]
            return [{"name": first_col, "type": "funnel", "data": data}]

        if chart_type == "treemap":
            first_col = y_cols[0] if y_cols else None
            data = [
                {"name": row.get(x), "value": row.get(first_col)}
                for row in rows
                if isinstance(row, dict)
            ]
            return [{"name": first_col, "type": "treemap", "data": data}]

        if chart_type == "heatmap":
            # One [xIdx, yIdx, value] triple per (row, y column) combination —
            # the y-axis category dimension is the series (y_cols), not `x`.
            data: list[list[Any]] = []
            for x_idx, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                for y_idx, col in enumerate(y_cols):
                    data.append([x_idx, y_idx, row.get(col)])
            return [{"name": "heatmap", "type": "heatmap", "data": data}]

        if chart_type == "waterfall":
            # Stacked-bar technique: a transparent "placeholder" series holds
            # each bar's running base, and a visible "delta" series holds the
            # signed magnitude — both stacked so the visible bar floats at
            # the correct height (ECharts has no native waterfall type).
            first_col = y_cols[0] if y_cols else None
            values = [row.get(first_col) for row in rows if isinstance(row, dict)]
            placeholder_data: list[float] = []
            delta_data: list[float] = []
            base = 0.0
            for v in values:
                v = v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
                if v >= 0:
                    placeholder_data.append(base)
                    delta_data.append(v)
                    base += v
                else:
                    base += v
                    placeholder_data.append(base)
                    delta_data.append(-v)
            return [
                {
                    "name": "placeholder",
                    "type": "bar",
                    "stack": "total",
                    "itemStyle": {"color": "transparent"},
                    "data": placeholder_data,
                },
                {"name": first_col or "delta", "type": "bar", "stack": "total", "data": delta_data},
            ]

        if chart_type == "radar":
            # One radar trace per y column; each trace's values are that
            # column across all rows, with the x/category values (already
            # extracted into `categories`) as the radar indicator dimensions.
            return [
                {
                    "type": "radar",
                    "data": [
                        {
                            "name": col,
                            "value": [row.get(col) for row in rows if isinstance(row, dict)],
                        }
                        for col in y_cols
                    ],
                }
            ]

        return []  # pragma: no cover — chart_type is always one of the above

    @staticmethod
    def _heatmap_visual_map(series: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a ``visualMap`` spanning the min/max value in a heatmap series."""
        values = [
            triple[2]
            for entry in series
            for triple in entry.get("data", [])
            if isinstance(triple[2], (int, float)) and not isinstance(triple[2], bool)
        ]
        return {
            "min": min(values) if values else 0,
            "max": max(values) if values else 1,
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
        }

    def _wrap_html(self, option: dict[str, Any], title: str) -> str:
        """Wrap an option in a self-contained HTML doc inlining the vendored bundle."""
        js = _ECHARTS_JS_PATH.read_text(encoding="utf-8")
        # Safe JSON embedding inside <script>: neutralize any '<' (e.g. "</script>").
        option_json = json.dumps(option).replace("<", "\\u003c")
        return (
            "<!DOCTYPE html>"
            '<html lang="en"><head><meta charset="utf-8">'
            f"<title>{html.escape(title)}</title>"
            f"<script>{js}</script></head>"
            '<body><div id="chart" style="width:100%;height:480px"></div>'
            "<script>"
            'var chart=echarts.init(document.getElementById("chart"));'
            f"chart.setOption({option_json});"
            "</script></body></html>"
        )
