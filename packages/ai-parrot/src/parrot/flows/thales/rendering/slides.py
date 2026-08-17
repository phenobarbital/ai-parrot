"""Slide rendering for the "Thales" deck renderer (FEAT-425 Module 4).

Pure, deterministic rendering: a :class:`~parrot.flows.thales.models.SlideSpec`
always renders to byte-identical HTML for the same input. No LLM anywhere in
this module (spec G4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.flows.thales.models import SlideSpec
from parrot.flows.thales.rendering.charts import echarts_option_block, static_svg_chart
from parrot.template.engine import TemplateEngine

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_engine: TemplateEngine | None = None


def _get_engine() -> TemplateEngine:
    """Lazily construct the module-level :class:`TemplateEngine` singleton."""
    global _engine
    if _engine is None:
        _engine = TemplateEngine(template_dirs=_TEMPLATES_DIR)
    return _engine


def _normalize_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guarantee every table dict carries ``headers``/``rows`` keys.

    Avoids Jinja ``StrictUndefined`` errors on arbitrary LLM-authored table
    payloads while keeping the template itself simple.
    """
    return [
        {
            "headers": list(table.get("headers", [])),
            "rows": [list(row) for row in table.get("rows", [])],
        }
        for table in tables
    ]


def _normalize_quotes(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guarantee every quote dict carries ``text``/``source`` keys."""
    return [
        {"text": quote.get("text", ""), "source": quote.get("source")}
        for quote in quotes
    ]


def _render_chart_html(chart: dict[str, Any]) -> str:
    """Combine the browser (ECharts) and print (static SVG) paths for one chart.

    Both are always emitted; CSS (`@media print`) toggles which one is
    visible — weasyprint executes no JavaScript, so the static SVG is the
    only one that survives the PDF path (FEAT-273/SPK-1 constraint).
    """
    return (
        '<div class="thales-chart-pair">'
        f'<div class="thales-chart-screen">{echarts_option_block(chart)}</div>'
        f'<div class="thales-chart-print">{static_svg_chart(chart)}</div>'
        "</div>"
    )


async def render_slide(spec: SlideSpec) -> str:
    """Render one :class:`SlideSpec` into deterministic HTML.

    Charts are only emitted when ``spec.charts`` is non-empty; the template
    falls back to the table/quote regions otherwise.

    Args:
        spec: The slide's structured content (LLM-filled, never HTML).

    Returns:
        Deterministic HTML for one slide — the same ``spec`` always
        renders to byte-identical output.
    """
    charts_html = [_render_chart_html(chart) for chart in spec.charts]
    return await _get_engine().render(
        "slide.html.j2",
        {
            "spec": spec,
            "charts_html": charts_html,
            "tables": _normalize_tables(spec.tables),
            "quotes": _normalize_quotes(spec.quotes),
        },
    )
