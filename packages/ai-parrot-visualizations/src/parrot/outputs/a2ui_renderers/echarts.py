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

import parrot.outputs.a2ui.catalog.components  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)

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
}


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output="application/json",
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
            A ``RenderedArtifact`` (``application/json`` or ``text/html``).

        Raises:
            ValueError: If the envelope contains no ``Chart`` component.
        """
        baked = bake_envelope(envelope)
        chart = next((c for c in baked if c["component"] == "Chart"), None)
        if chart is None:
            raise ValueError("echarts renderer requires a 'Chart' component in the envelope.")

        option = self._build_option(chart["properties"])

        if wrap_html:
            document = self._wrap_html(option, chart["properties"].get("title", ""))
            return RenderedArtifact(
                artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
                mime_type="text/html",
                content=document.encode("utf-8"),
                filename=f"{envelope.surface_id}.html",
                title=envelope.surface_id,
                surface=_SURFACE_NAME,
            )

        content = json.dumps(option, sort_keys=True).encode("utf-8")
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="application/json",
            content=content,
            filename=f"{envelope.surface_id}.json",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
        )

    # -- internal -----------------------------------------------------------

    def _build_option(self, props: dict[str, Any]) -> dict[str, Any]:
        """Build a deterministic ECharts option dict from Chart component data."""
        chart_type = props.get("type", "bar")
        series_type = _SERIES_TYPE.get(chart_type, "bar")
        x = props.get("x")
        y_cols = props.get("y") or []
        rows = props.get("data") or []
        if not isinstance(rows, list):
            rows = []

        categories = [row.get(x) for row in rows if isinstance(row, dict)] if x else []
        series = []
        for col in y_cols:
            values = [row.get(col) for row in rows if isinstance(row, dict)]
            series_entry: dict[str, Any] = {"name": col, "type": series_type, "data": values}
            if chart_type == "area":
                series_entry["areaStyle"] = {}
            series.append(series_entry)

        option: dict[str, Any] = {
            "title": {"text": props.get("title", "")},
            "legend": {"show": bool(props.get("showLegend", True))},
            "series": series,
        }
        if series_type != "pie":
            option["xAxis"] = {"type": "category", "data": categories}
            option["yAxis"] = {"type": "value"}
        return option

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
