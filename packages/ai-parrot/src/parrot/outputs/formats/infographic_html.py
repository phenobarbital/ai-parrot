"""
Infographic HTML Renderer for AI-Parrot.

Renders InfographicResponse structured output as a self-contained HTML5
document with inline CSS and (optionally) inline ECharts JS for charts.

This renderer is a sibling to InfographicRenderer (JSON); content
negotiation in get_infographic() decides which one to use.
"""
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import markdown_it
import orjson
from markupsafe import escape

from .base import BaseRenderer
from ...models.infographic import (
    BlockType,
    BulletListBlock,
    CalloutBlock,
    CalloutLevel,
    ChartBlock,
    ChartDataSeries,
    ChartType,
    DividerBlock,
    HeroCardBlock,
    ImageBlock,
    InfographicResponse,
    ProgressBlock,
    QuoteBlock,
    SummaryBlock,
    TableBlock,
    TimelineBlock,
    TitleBlock,
    TrendDirection,
    ThemeConfig,
    theme_registry,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# ECharts JS lazy-loaded cache
# ──────────────────────────────────────────────
_ECHARTS_JS_PATH = Path(__file__).parent / "assets" / "echarts.min.js"
_echarts_js_cache: Optional[str] = None


def _load_echarts_js() -> str:
    """Lazy-load the ECharts minified JS bundle."""
    global _echarts_js_cache
    if _echarts_js_cache is None:
        try:
            _echarts_js_cache = _ECHARTS_JS_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "ECharts JS not found at %s. Charts will not render.",
                _ECHARTS_JS_PATH,
            )
            _echarts_js_cache = "/* ECharts JS not available */"
    return _echarts_js_cache


# ──────────────────────────────────────────────
# Base CSS (extracted from reference HTML)
# ──────────────────────────────────────────────

BASE_CSS = """\
body {
    font-family: var(--font-family);
    background-color: var(--body-bg);
    color: var(--neutral-text);
    line-height: 1.5;
    margin: 0;
    padding: 20px;
}
.container {
    max-width: 900px;
    margin: 0 auto;
    background: white;
    padding: 32px;
    border-radius: 24px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.05);
}
.hero {
    background: linear-gradient(135deg, var(--primary), var(--primary-dark));
    color: #fff;
    padding: 40px 32px;
    border-radius: 16px;
    margin-bottom: 32px;
    text-align: center;
}
.hero h1 {
    margin: 0;
    font-size: 2.5rem;
    font-weight: 800;
    letter-spacing: -0.025em;
}
.hero p {
    margin: 12px 0 0;
    opacity: 0.9;
    font-size: 1.1rem;
}
.hero .meta {
    margin-top: 8px;
    opacity: 0.75;
    font-size: 0.9rem;
}
.section-title {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 40px 0 20px;
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--neutral-text);
}
.section-title::after {
    content: '';
    flex: 1;
    height: 2px;
    background: var(--neutral-border);
}
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
}
.kpi-card {
    background: #fff;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    border: 1px solid var(--neutral-border);
}
.kpi-value {
    font-size: 2rem;
    font-weight: 800;
    color: var(--primary);
    display: block;
}
.kpi-label {
    font-size: 0.875rem;
    color: var(--neutral-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.kpi-trend {
    font-size: 0.85rem;
    margin-top: 4px;
}
.kpi-trend.up { color: var(--accent-green); }
.kpi-trend.down { color: var(--accent-red); }
.kpi-trend.flat { color: var(--neutral-muted); }
.chart-container {
    background: #fff;
    padding: 24px;
    border-radius: 16px;
    border: 1px solid var(--neutral-border);
    margin-bottom: 32px;
}
.chart-container h3 {
    margin: 0 0 16px;
    font-size: 1.1rem;
    color: var(--neutral-text);
}
table {
    width: 100%;
    border-collapse: collapse;
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 32px;
}
th {
    background: var(--primary);
    color: #fff;
    padding: 12px 16px;
    text-align: left;
    font-size: 0.9rem;
}
td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--neutral-border);
    font-size: 0.95rem;
}
tr:nth-child(even) { background: var(--neutral-bg); }
tr:hover { background: #f1f5f9; }
.table-container { margin-bottom: 32px; }
.table-container h3 {
    margin: 0 0 12px;
    font-size: 1.1rem;
}
.summary-block {
    margin-bottom: 24px;
    line-height: 1.7;
}
.summary-block.highlight {
    background: var(--neutral-bg);
    border-left: 4px solid var(--primary);
    padding: 16px 20px;
    border-radius: 0 12px 12px 0;
}
.summary-block h3 {
    margin: 0 0 8px;
    font-size: 1.1rem;
    color: var(--primary-dark);
}
.bullet-list-block {
    margin-bottom: 24px;
}
.bullet-list-block h3 {
    margin: 0 0 12px;
    font-size: 1.1rem;
}
.bullet-list-block ul, .bullet-list-block ol {
    margin: 0;
    padding-left: 24px;
}
.bullet-list-block li {
    margin-bottom: 8px;
    line-height: 1.6;
}
.image-block {
    margin-bottom: 24px;
    text-align: center;
}
.image-block img {
    max-width: 100%;
    border-radius: 12px;
}
.image-block .caption {
    margin-top: 8px;
    font-size: 0.875rem;
    color: var(--neutral-muted);
}
blockquote.quote-block {
    border-left: 4px solid var(--primary);
    margin: 0 0 24px;
    padding: 16px 24px;
    background: var(--neutral-bg);
    border-radius: 0 12px 12px 0;
    font-style: italic;
    font-size: 1.05rem;
    color: var(--neutral-text);
}
blockquote.quote-block .attribution {
    margin-top: 8px;
    font-style: normal;
    font-size: 0.875rem;
    color: var(--neutral-muted);
}
.callout-block {
    padding: 20px;
    border-radius: 0 12px 12px 0;
    margin-bottom: 24px;
}
.callout-block h3 { margin-top: 0; }
.callout-block.info {
    background: #eff6ff;
    border-left: 4px solid var(--primary);
}
.callout-block.info h3 { color: var(--primary-dark); }
.callout-block.success {
    background: #ecfdf5;
    border-left: 4px solid var(--accent-green);
}
.callout-block.success h3 { color: #065f46; }
.callout-block.warning {
    background: #fffbeb;
    border-left: 4px solid var(--accent-amber);
}
.callout-block.warning h3 { color: #92400e; }
.callout-block.error {
    background: #fef2f2;
    border-left: 4px solid var(--accent-red);
}
.callout-block.error h3 { color: #991b1b; }
.callout-block.tip {
    background: #f0fdfa;
    border-left: 4px solid #14b8a6;
}
.callout-block.tip h3 { color: #115e59; }
hr.divider {
    border: none;
    margin: 32px 0;
}
hr.divider.solid { border-top: 2px solid var(--neutral-border); }
hr.divider.dashed { border-top: 2px dashed var(--neutral-border); }
hr.divider.dotted { border-top: 2px dotted var(--neutral-border); }
hr.divider.gradient {
    height: 2px;
    background: linear-gradient(90deg, var(--primary-light), var(--primary), var(--primary-light));
}
.timeline-block { margin-bottom: 32px; }
.timeline-block h3 {
    margin: 0 0 16px;
    font-size: 1.1rem;
}
.timeline-event {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
    position: relative;
    padding-left: 24px;
}
.timeline-event::before {
    content: '';
    position: absolute;
    left: 0;
    top: 6px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--primary);
}
.timeline-event::after {
    content: '';
    position: absolute;
    left: 5px;
    top: 18px;
    width: 2px;
    height: calc(100% + 4px);
    background: var(--neutral-border);
}
.timeline-event:last-child::after { display: none; }
.timeline-date {
    font-weight: 700;
    font-size: 0.875rem;
    color: var(--primary);
    min-width: 80px;
}
.timeline-content { flex: 1; }
.timeline-content .title {
    font-weight: 600;
    margin-bottom: 2px;
}
.timeline-content .desc {
    font-size: 0.9rem;
    color: var(--neutral-muted);
}
.progress-block { margin-bottom: 32px; }
.progress-block h3 {
    margin: 0 0 16px;
    font-size: 1.1rem;
}
.progress-item {
    margin-bottom: 16px;
}
.progress-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 4px;
    font-size: 0.9rem;
}
.progress-label { font-weight: 600; }
.progress-value { color: var(--neutral-muted); }
.progress-track {
    background: var(--neutral-bg);
    border-radius: 6px;
    height: 12px;
    position: relative;
    overflow: hidden;
}
.progress-fill {
    height: 100%;
    border-radius: 6px;
    background: linear-gradient(90deg, var(--primary-light), var(--primary));
    transition: width 0.3s ease;
}
.progress-target {
    position: absolute;
    top: 0;
    height: 100%;
    width: 2px;
    background: var(--neutral-text);
    opacity: 0.4;
}
.empty-message {
    text-align: center;
    padding: 48px 24px;
    color: var(--neutral-muted);
    font-size: 1.1rem;
}
footer.infographic-footer {
    text-align: center;
    margin-top: 40px;
    color: var(--neutral-muted);
    font-size: 0.85rem;
    border-top: 1px solid var(--neutral-border);
    padding-top: 20px;
}
@media (max-width: 600px) {
    .container { padding: 16px; }
    .hero { padding: 24px 16px; }
    .hero h1 { font-size: 1.75rem; }
    .kpi-grid { grid-template-columns: 1fr; }
}
@media print {
    body { background: white; padding: 0; }
    .container { box-shadow: none; max-width: 100%; }
    .hero { background: #eee !important; color: black !important; border: 1px solid #ccc; }
    .progress-fill { background: #6366f1 !important; -webkit-print-color-adjust: exact; }
}
"""


class InfographicHTMLRenderer(BaseRenderer):
    """Renders InfographicResponse as a self-contained HTML5 document.

    Produces a complete HTML page with inline CSS (themed via CSS custom
    properties) and optional inline ECharts JS for chart blocks.

    Usage::

        renderer = InfographicHTMLRenderer()
        html = renderer.render_to_html(infographic_response, theme="dark")
    """

    def __init__(self) -> None:
        self._md = markdown_it.MarkdownIt()  # html=False by default (safe)
        self._block_renderers: Dict[str, Any] = {
            "title": self._render_title,
            "hero_card": self._render_hero_card,
            "summary": self._render_summary,
            "chart": self._render_chart,
            "bullet_list": self._render_bullet_list,
            "table": self._render_table,
            "image": self._render_image,
            "quote": self._render_quote,
            "callout": self._render_callout,
            "divider": self._render_divider,
            "timeline": self._render_timeline,
            "progress": self._render_progress,
        }

    # ── BaseRenderer interface ──────────────────

    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        export_format: str = 'html',
        include_code: bool = False,
        **kwargs,
    ) -> Tuple[str, Optional[Any]]:
        """Render an AIMessage containing InfographicResponse as HTML.

        Args:
            response: AIMessage with structured_output or output.
            environment: Ignored (always produces HTML).
            export_format: Ignored.
            include_code: Ignored.
            **kwargs: May include ``theme`` (str).

        Returns:
            Tuple of (html_string, html_string).
        """
        from .infographic import InfographicRenderer

        extractor = InfographicRenderer()
        data = extractor._extract_infographic_data(response)
        theme = kwargs.get("theme")
        html = self.render_to_html(data, theme=theme)
        return html, html

    # ── Public standalone method ────────────────

    def render_to_html(
        self,
        data: Union[InfographicResponse, dict],
        theme: Optional[str] = None,
    ) -> str:
        """Convert InfographicResponse to a complete HTML document.

        This method is usable outside the renderer pipeline (e.g. for
        PDF export, email embedding, file saving).

        Args:
            data: An ``InfographicResponse`` model or a raw dict.
            theme: Theme name (falls back to response.theme, then ``"light"``).

        Returns:
            Complete HTML5 string with inline CSS.
        """
        # Normalise to InfographicResponse
        if isinstance(data, str):
            import json as _json
            try:
                data = _json.loads(data)
            except (ValueError, TypeError):
                raise ValueError(
                    "render_to_html received a plain string that is not valid JSON"
                )
        if isinstance(data, dict):
            data = InfographicResponse.model_validate(data)

        # Resolve theme
        theme_name = theme or data.theme or "light"
        try:
            theme_cfg = theme_registry.get(theme_name)
        except KeyError:
            logger.warning("Unknown theme '%s', falling back to 'light'", theme_name)
            theme_cfg = theme_registry.get("light")

        # Render blocks
        blocks_html = self._render_blocks(data)

        # Extract page title from the first TitleBlock (if any)
        page_title = "Infographic"
        for block in data.blocks:
            if getattr(block, "type", None) == "title":
                page_title = str(escape(block.title))
                break

        # Check if charts exist (ECharts JS needed)
        has_charts = any(
            getattr(b, "type", None) == "chart" for b in data.blocks
        )
        echarts_script = self._get_echarts_script() if has_charts else ""

        return self._assemble_document(
            page_title=page_title,
            theme_css=theme_cfg.to_css_variables(),
            blocks_html=blocks_html,
            echarts_script=echarts_script,
        )

    # ── Document assembly ───────────────────────

    def _assemble_document(
        self,
        page_title: str,
        theme_css: str,
        blocks_html: str,
        echarts_script: str = "",
    ) -> str:
        """Assemble the full HTML5 document."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <style>
{theme_css}
{BASE_CSS}
    </style>
{echarts_script}
</head>
<body>
    <div class="container">
{blocks_html}
    </div>
</body>
</html>"""

    # ── Block rendering ─────────────────────────

    def _render_blocks(self, data: InfographicResponse) -> str:
        """Render all blocks, grouping consecutive hero_cards."""
        if not data.blocks:
            return '        <div class="empty-message">No data available.</div>'

        parts: list[str] = []
        i = 0
        blocks = data.blocks
        while i < len(blocks):
            block = blocks[i]
            block_type = getattr(block, "type", None)

            # Group consecutive hero_card blocks
            if block_type == "hero_card":
                cards: list[str] = []
                while i < len(blocks) and getattr(blocks[i], "type", None) == "hero_card":
                    cards.append(self._render_hero_card(blocks[i]))
                    i += 1
                parts.append(
                    '        <div class="kpi-grid">\n'
                    + "\n".join(cards)
                    + "\n        </div>"
                )
                continue

            renderer = self._block_renderers.get(block_type)
            if renderer is None:
                logger.warning(
                    "Unknown block type '%s' — skipping.", block_type
                )
                i += 1
                continue

            parts.append(renderer(block))
            i += 1

        return "\n".join(parts)

    # ── Individual block renderers ──────────────

    def _render_title(self, block: TitleBlock) -> str:
        """Render TitleBlock as hero header."""
        title = escape(block.title)
        subtitle_html = ""
        if block.subtitle:
            subtitle_html = f"\n            <p>{escape(block.subtitle)}</p>"
        meta_parts = []
        if block.author:
            meta_parts.append(str(escape(block.author)))
        if block.date:
            meta_parts.append(str(escape(block.date)))
        meta_html = ""
        if meta_parts:
            meta_html = f'\n            <p class="meta">{" | ".join(meta_parts)}</p>'
        return (
            f'        <header class="hero">\n'
            f"            <h1>{title}</h1>"
            f"{subtitle_html}{meta_html}\n"
            f"        </header>"
        )

    def _render_hero_card(self, block: HeroCardBlock) -> str:
        """Render HeroCardBlock as a KPI card."""
        value = escape(block.value)
        label = escape(block.label)
        color_style = ""
        if block.color:
            color_style = f' style="color: {escape(block.color)}"'
        trend_html = ""
        if block.trend:
            arrow = {"up": "&#9650;", "down": "&#9660;", "flat": "&#9654;"}.get(
                block.trend.value, ""
            )
            trend_val = escape(block.trend_value) if block.trend_value else ""
            trend_html = (
                f'\n            <div class="kpi-trend {escape(block.trend.value)}">'
                f"{arrow} {trend_val}</div>"
            )
        return (
            f'            <div class="kpi-card">\n'
            f'                <span class="kpi-value"{color_style}>{value}</span>\n'
            f'                <span class="kpi-label">{label}</span>'
            f"{trend_html}\n"
            f"            </div>"
        )

    def _render_summary(self, block: SummaryBlock) -> str:
        """Render SummaryBlock as markdown-rendered paragraph."""
        highlight_cls = " highlight" if block.highlight else ""
        title_html = ""
        if block.title:
            title_html = f'\n            <h3>{escape(block.title)}</h3>'
        # markdown_it renders safe HTML (html=False by default)
        content_html = self._md.render(block.content)
        return (
            f'        <div class="summary-block{highlight_cls}">'
            f"{title_html}\n"
            f"            {content_html}"
            f"        </div>"
        )

    def _render_chart(self, block: ChartBlock) -> str:
        """Render ChartBlock as ECharts-initialized container."""
        chart_id = f"chart-{uuid.uuid4().hex[:8]}"
        title_html = ""
        if block.title:
            title_html = f"<h3>{escape(block.title)}</h3>\n            "

        option = self._build_echarts_option(block)
        option_json = orjson.dumps(option).decode("utf-8")

        return (
            f'        <div class="chart-container">\n'
            f"            {title_html}"
            f'<div id="{chart_id}" style="width:100%;height:400px;"></div>\n'
            f"            <script>\n"
            f"            (function() {{\n"
            f"                var dom = document.getElementById('{chart_id}');\n"
            f"                var chart = echarts.init(dom);\n"
            f"                chart.setOption({option_json});\n"
            f"                window.addEventListener('resize', function() {{ chart.resize(); }});\n"
            f"            }})();\n"
            f"            </script>\n"
            f"        </div>"
        )

    def _build_echarts_option(self, block: ChartBlock) -> dict:
        """Map a ChartBlock to an ECharts option dict.

        Args:
            block: ChartBlock with chart_type, labels, series, etc.

        Returns:
            dict suitable for ``chart.setOption()``.
        """
        option: Dict[str, Any] = {
            "tooltip": {},
            "grid": {"containLabel": True},
        }

        if block.title:
            option["title"] = {"text": str(escape(block.title))}

        if block.show_legend is not False:
            option["legend"] = {"data": [s.name for s in block.series]}

        ct = block.chart_type

        # ── Cartesian charts (bar, line, area) ──
        if ct in (ChartType.BAR, ChartType.LINE, ChartType.AREA):
            option["tooltip"]["trigger"] = "axis"
            option["xAxis"] = {"type": "category", "data": block.labels}
            if block.x_axis_label:
                option["xAxis"]["name"] = str(escape(block.x_axis_label))
            option["yAxis"] = {"type": "value"}
            if block.y_axis_label:
                option["yAxis"]["name"] = str(escape(block.y_axis_label))
            option["series"] = []
            for s in block.series:
                item: Dict[str, Any] = {
                    "name": s.name,
                    "data": s.values,
                    "type": ct.value,
                }
                if ct == ChartType.AREA:
                    item["type"] = "line"
                    item["areaStyle"] = {}
                if s.color:
                    item["itemStyle"] = {"color": s.color}
                if block.stacked:
                    item["stack"] = "total"
                option["series"].append(item)

        # ── Pie / donut ─────────────────────────
        elif ct in (ChartType.PIE, ChartType.DONUT):
            option["tooltip"]["trigger"] = "item"
            pie_data = []
            if block.series:
                series = block.series[0]
                for label, val in zip(block.labels, series.values):
                    pie_data.append({"name": label, "value": val})
            series_item: Dict[str, Any] = {
                "type": "pie",
                "data": pie_data,
            }
            if ct == ChartType.DONUT:
                series_item["radius"] = ["40%", "70%"]
            if block.series and block.series[0].color:
                series_item["itemStyle"] = {"color": block.series[0].color}
            option["series"] = [series_item]

        # ── Scatter ─────────────────────────────
        elif ct == ChartType.SCATTER:
            option["tooltip"]["trigger"] = "item"
            option["xAxis"] = {"type": "value"}
            option["yAxis"] = {"type": "value"}
            option["series"] = []
            for s in block.series:
                item = {"name": s.name, "type": "scatter", "data": s.values}
                if s.color:
                    item["itemStyle"] = {"color": s.color}
                option["series"].append(item)

        # ── Radar ───────────────────────────────
        elif ct == ChartType.RADAR:
            max_val = 0
            for s in block.series:
                for v in s.values:
                    if v is not None and v > max_val:
                        max_val = v
            indicator = [
                {"name": label, "max": max_val * 1.2 or 100}
                for label in block.labels
            ]
            option["radar"] = {"indicator": indicator}
            option["series"] = [{
                "type": "radar",
                "data": [
                    {"name": s.name, "value": s.values}
                    for s in block.series
                ],
            }]

        # ── Gauge ───────────────────────────────
        elif ct == ChartType.GAUGE:
            gauge_val = 0
            if block.series and block.series[0].values:
                gauge_val = block.series[0].values[0]
            option["series"] = [{
                "type": "gauge",
                "data": [{"value": gauge_val, "name": block.series[0].name if block.series else ""}],
            }]

        # ── Funnel ──────────────────────────────
        elif ct == ChartType.FUNNEL:
            funnel_data = []
            if block.series:
                series = block.series[0]
                for label, val in zip(block.labels, series.values):
                    funnel_data.append({"name": label, "value": val})
            option["series"] = [{"type": "funnel", "data": funnel_data}]

        # ── Treemap ─────────────────────────────
        elif ct == ChartType.TREEMAP:
            treemap_data = []
            if block.series:
                series = block.series[0]
                for label, val in zip(block.labels, series.values):
                    treemap_data.append({"name": label, "value": val})
            option["series"] = [{"type": "treemap", "data": treemap_data}]

        # ── Heatmap ─────────────────────────────
        elif ct == ChartType.HEATMAP:
            option["tooltip"]["trigger"] = "item"
            option["xAxis"] = {"type": "category", "data": block.labels}
            option["yAxis"] = {"type": "category"}
            option["visualMap"] = {"min": 0, "max": 100, "calculable": True}
            heatmap_data = []
            if block.series:
                for si, s in enumerate(block.series):
                    for li, val in enumerate(s.values):
                        heatmap_data.append([li, si, val])
            option["series"] = [{"type": "heatmap", "data": heatmap_data}]

        # ── Waterfall (custom bar) ──────────────
        elif ct == ChartType.WATERFALL:
            option["tooltip"]["trigger"] = "axis"
            option["xAxis"] = {"type": "category", "data": block.labels}
            option["yAxis"] = {"type": "value"}
            if block.series:
                values = block.series[0].values
                # Calculate running totals for waterfall
                base: List[float] = []
                bar: List[float] = []
                running = 0.0
                for v in values:
                    actual_v = v if v is not None else 0
                    if actual_v >= 0:
                        base.append(running)
                        bar.append(actual_v)
                    else:
                        base.append(running + actual_v)
                        bar.append(abs(actual_v))
                    running += actual_v
                option["series"] = [
                    {
                        "type": "bar",
                        "stack": "waterfall",
                        "data": base,
                        "itemStyle": {"opacity": 0},
                    },
                    {
                        "type": "bar",
                        "stack": "waterfall",
                        "data": bar,
                        "name": block.series[0].name if block.series else "Value",
                    },
                ]

        return option

    def _render_bullet_list(self, block: BulletListBlock) -> str:
        """Render BulletListBlock as ul or ol."""
        title_html = ""
        if block.title:
            title_html = f'\n            <h3>{escape(block.title)}</h3>'
        tag = "ol" if block.ordered else "ul"
        items = "\n".join(
            f"                <li>{escape(item)}</li>" for item in block.items
        )
        return (
            f'        <div class="bullet-list-block">'
            f"{title_html}\n"
            f"            <{tag}>\n{items}\n            </{tag}>\n"
            f"        </div>"
        )

    def _render_table(self, block: TableBlock) -> str:
        """Render TableBlock as HTML table."""
        title_html = ""
        if block.title:
            title_html = f'            <h3>{escape(block.title)}</h3>\n'
        headers = "\n".join(
            f"                    <th>{escape(str(col))}</th>"
            for col in block.columns
        )
        rows_html = ""
        for row in block.rows:
            cells = "\n".join(
                f"                    <td>{escape(str(cell))}</td>"
                for cell in row
            )
            rows_html += f"                <tr>\n{cells}\n                </tr>\n"
        return (
            f'        <div class="table-container">\n'
            f"{title_html}"
            f"            <table>\n"
            f"                <thead>\n                <tr>\n{headers}\n                </tr>\n                </thead>\n"
            f"                <tbody>\n{rows_html}                </tbody>\n"
            f"            </table>\n"
            f"        </div>"
        )

    def _render_image(self, block: ImageBlock) -> str:
        """Render ImageBlock as img tag."""
        src = ""
        if block.url:
            src = str(escape(block.url))
        elif block.base64:
            src = f"data:image/png;base64,{block.base64}"
        alt = escape(block.alt) if block.alt else ""
        width_attr = f' style="width:{escape(block.width)}"' if block.width else ""
        caption_html = ""
        if block.caption:
            caption_html = f'\n            <p class="caption">{escape(block.caption)}</p>'
        return (
            f'        <div class="image-block">\n'
            f'            <img src="{src}" alt="{alt}"{width_attr}>'
            f"{caption_html}\n"
            f"        </div>"
        )

    def _render_quote(self, block: QuoteBlock) -> str:
        """Render QuoteBlock as blockquote."""
        text = escape(block.text)
        attr_parts = []
        if block.author:
            attr_parts.append(str(escape(block.author)))
        if block.source:
            attr_parts.append(str(escape(block.source)))
        attr_html = ""
        if attr_parts:
            attr_html = (
                f'\n            <div class="attribution">'
                f'&mdash; {", ".join(attr_parts)}</div>'
            )
        return (
            f'        <blockquote class="quote-block">\n'
            f"            {text}"
            f"{attr_html}\n"
            f"        </blockquote>"
        )

    def _render_callout(self, block: CalloutBlock) -> str:
        """Render CalloutBlock as alert box."""
        level = block.level.value if block.level else "info"
        title_html = ""
        if block.title:
            title_html = f"\n            <h3>{escape(block.title)}</h3>"
        content = escape(block.content)
        return (
            f'        <div class="callout-block {escape(level)}">'
            f"{title_html}\n"
            f"            <p>{content}</p>\n"
            f"        </div>"
        )

    def _render_divider(self, block: DividerBlock) -> str:
        """Render DividerBlock as styled hr."""
        style = block.style or "solid"
        return f'        <hr class="divider {escape(style)}">'

    def _render_timeline(self, block: TimelineBlock) -> str:
        """Render TimelineBlock as chronological event list."""
        title_html = ""
        if block.title:
            title_html = f'\n            <h3>{escape(block.title)}</h3>'
        events_html = ""
        for evt in block.events:
            desc_html = ""
            if evt.description:
                desc_html = f'\n                    <div class="desc">{escape(evt.description)}</div>'
            color_style = ""
            if evt.color:
                color_style = f' style="--event-color: {escape(evt.color)}"'
            events_html += (
                f'            <div class="timeline-event"{color_style}>\n'
                f'                <div class="timeline-date">{escape(evt.date)}</div>\n'
                f'                <div class="timeline-content">\n'
                f'                    <div class="title">{escape(evt.title)}</div>'
                f"{desc_html}\n"
                f"                </div>\n"
                f"            </div>\n"
            )
        return (
            f'        <div class="timeline-block">'
            f"{title_html}\n{events_html}"
            f"        </div>"
        )

    def _render_progress(self, block: ProgressBlock) -> str:
        """Render ProgressBlock as progress bars."""
        title_html = ""
        if block.title:
            title_html = f'\n            <h3>{escape(block.title)}</h3>'
        items_html = ""
        for item in block.items:
            fill_style = f"width: {item.value}%"
            if item.color:
                fill_style += f"; background: linear-gradient(90deg, {item.color}, {item.color})"
            target_html = ""
            if item.target is not None:
                target_html = (
                    f'\n                <div class="progress-target"'
                    f' style="left: {item.target}%"></div>'
                )
            items_html += (
                f'            <div class="progress-item">\n'
                f'                <div class="progress-header">\n'
                f'                    <span class="progress-label">{escape(item.label)}</span>\n'
                f'                    <span class="progress-value">{item.value:.0f}%</span>\n'
                f"                </div>\n"
                f'                <div class="progress-track">\n'
                f'                    <div class="progress-fill"'
                f' style="{fill_style}"></div>'
                f"{target_html}\n"
                f"                </div>\n"
                f"            </div>\n"
            )
        return (
            f'        <div class="progress-block">'
            f"{title_html}\n{items_html}"
            f"        </div>"
        )

    # ── ECharts JS injection ───────────────────

    def _get_echarts_script(self) -> str:
        """Return a ``<script>`` tag containing the inline ECharts JS bundle.

        The bundle is loaded lazily from ``assets/echarts.min.js`` on first
        call and cached for subsequent renders.
        """
        js = _load_echarts_js()
        return f"    <script>{js}</script>"
