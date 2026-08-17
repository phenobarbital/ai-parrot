"""Chart rendering for the "Thales" deck renderer (FEAT-425 Module 4).

Two deterministic, dependency-free rendering paths, per the FEAT-273/SPK-1
convention (``artifacts/spikes/spk1-rasterization/results.md``):

- :func:`echarts_option_block` — an ECharts option-JSON container for the
  interactive browser path.
- :func:`static_svg_chart` — a bar/line SVG builder for the print/PDF path
  (weasyprint executes no JavaScript, so ECharts cannot render there).

Both accept the same ``chart`` payload shape produced by ``SlideSpec.charts``
(e.g. ``{"type": "bar", "labels": [...], "series": [{"name": ..., "data": [...]}]}``).
No timestamps, no ``uuid``s — element ids are derived deterministically from
the chart's own content so identical input always renders identical output.
"""

from __future__ import annotations

import html
import json
from hashlib import sha256
from typing import Any


def _chart_id(chart: dict[str, Any]) -> str:
    """Derive a deterministic element id from the chart payload's content."""
    digest = sha256(json.dumps(chart, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"thales-chart-{digest[:12]}"


def echarts_option_block(chart: dict[str, Any]) -> str:
    """Build an ECharts option-JSON container for the interactive browser path.

    Args:
        chart: A chart payload (e.g. ``{"type": "bar", "labels": [...],
            "series": [{"name": ..., "data": [...]}]}``).

    Returns:
        A self-contained HTML fragment: a chart ``<div>`` plus an inline
        ``<script>`` that initializes ECharts against it. Deterministic —
        the element id is derived from the chart's own (sorted) content.
    """
    chart_id = _chart_id(chart)
    option = _to_echarts_option(chart)
    option_json = json.dumps(option, sort_keys=True)
    return (
        f'<div class="thales-chart thales-chart--browser">'
        f'<div id="{chart_id}" class="thales-chart-canvas" '
        f'style="width:100%;height:320px;"></div>'
        f"<script>"
        f"(function() {{"
        f'var dom = document.getElementById("{chart_id}");'
        f"if (dom && window.echarts) {{"
        f"var chart = echarts.init(dom);"
        f"chart.setOption({option_json});"
        f'window.addEventListener("resize", function() {{ chart.resize(); }});'
        f"}}"
        f"}})();"
        f"</script>"
        f"</div>"
    )


def _to_echarts_option(chart: dict[str, Any]) -> dict[str, Any]:
    """Map the Thales chart payload shape onto a minimal ECharts option dict."""
    chart_type = chart.get("type", "bar")
    echarts_type = "line" if chart_type == "line" else "bar"
    labels = list(chart.get("labels", []))
    series = chart.get("series", [])
    return {
        "title": {"text": chart.get("title", "")} if chart.get("title") else {},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value"},
        "series": [
            {
                "name": s.get("name", ""),
                "type": echarts_type,
                "data": list(s.get("data", [])),
            }
            for s in series
        ],
    }


def static_svg_chart(chart: dict[str, Any]) -> str:
    """Build a deterministic, dependency-free static SVG chart (bar or line).

    Used on the print/PDF path (weasyprint runs no JavaScript, so ECharts'
    interactive rendering is unavailable there).

    Args:
        chart: A chart payload, same shape as :func:`echarts_option_block`.

    Returns:
        An inline ``<svg>...</svg>`` fragment.
    """
    chart_type = chart.get("type", "bar")
    labels = [str(item) for item in chart.get("labels", [])]
    series = chart.get("series", [])

    width, height, pad = 480, 240, 32
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad

    all_values: list[float] = []
    for s in series:
        for v in s.get("data", []):
            if isinstance(v, (int, float)):
                all_values.append(float(v))
    max_v = max(all_values) if all_values else 1.0
    max_v = max_v or 1.0

    n_labels = max(len(labels), 1)
    n_series = max(len(series), 1)

    palette = ["#3b7dd8", "#d8823b", "#3bd894", "#a13bd8", "#d83b5c"]

    parts: list[str] = []
    if chart_type == "line":
        for s_idx, s in enumerate(series):
            data = [v for v in s.get("data", []) if isinstance(v, (int, float))]
            points = []
            for i, value in enumerate(data):
                x = pad + (plot_w * i / max(n_labels - 1, 1)) if n_labels > 1 else pad
                y = height - pad - (plot_h * value / max_v)
                points.append(f"{x:.1f},{y:.1f}")
            color = palette[s_idx % len(palette)]
            parts.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="2" '
                f'points="{" ".join(points)}"/>'
            )
    else:
        group_w = plot_w / n_labels
        bar_w = group_w / (n_series + 1)
        for s_idx, s in enumerate(series):
            data = s.get("data", [])
            color = palette[s_idx % len(palette)]
            for i, value in enumerate(data):
                value = value if isinstance(value, (int, float)) else 0
                bar_h = plot_h * value / max_v
                bx = pad + i * group_w + s_idx * bar_w
                by = height - pad - bar_h
                parts.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w * 0.8:.1f}" '
                    f'height="{bar_h:.1f}" fill="{color}"/>'
                )

    for i, label in enumerate(labels):
        x = pad + (plot_w * i / max(n_labels - 1, 1)) if n_labels > 1 else pad + plot_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="{height - pad + 14:.1f}" font-size="10" '
            f'text-anchor="middle">{html.escape(label)}</text>'
        )

    title = html.escape(str(chart.get("title", "")))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
        + "".join(parts)
        + "</svg>"
    )
