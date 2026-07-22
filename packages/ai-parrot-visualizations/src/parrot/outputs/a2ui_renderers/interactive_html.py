"""Interactive-HTML renderer (Module 7, satellite, FEAT-324 spec G7).

Emits a SINGLE self-contained HTML document — vendored Chart.js v4 (MIT,
``formats/assets/chart.umd.min.js``, shared placement convention with the
vendored ECharts bundle) + a small vanilla-JS runtime — driven entirely by
the envelope's ``dataModel``, embedded verbatim as
``<script type="application/json" id="report-data">``. Mirrors the reference
template's ``sdd/artifacts/budget_variance_dashboard_Template.html`` pattern
(data separable from markup) without reproducing its Google-Fonts
``@import`` (system font stack only — zero external network references).

Unlike :class:`~parrot.outputs.a2ui_renderers.ssr_html.SSRHTMLRenderer`
(``interactive=False``, fully static), this renderer intercepts ``Chart`` and
``DataTable`` components BEFORE catalog lowering (their ``lower()``
implementations intentionally degrade to a text/opaque-property summary —
see ``parrot.outputs.a2ui.catalog.components.chart``/``datatable`` — real
graphics/table rendering is a RENDERER concern, same precedent as
:class:`~parrot.outputs.a2ui_renderers.echarts.EChartsRenderer`). Every other
component (Card, KPICard, Form, Map, Timeline, Report, and an Infographic's
own title/subtitle/section scaffolding) renders via standard catalog
lowering, same as SSR-HTML.

**Behavior hooks** (vanilla JS, ES2017, no build step, no dependencies beyond
the vendored Chart.js UMD bundle):

* ``[data-chart-config]`` on a ``<canvas>`` — JSON chart config
  (``type``/``x``/``y``/``data``/``title``/``showLegend``, plus an optional
  ``tabs`` array of ``{"label", "data"}`` day-slices). Chart.js is
  instantiated from this on page load.
* ``[data-tabs-for="<chart-id>"]`` + ``[data-tab-index]`` buttons — day-tab
  switching: clicking a tab swaps the chart's active data slice
  (``config.tabs[index].data``). Rendered only when the Chart's properties
  carry a ``tabs`` list (optional; a single-dataset chart renders no tabs).
* ``[data-metric-toggle-for="<chart-id>"]`` + ``[data-metric-index]``
  buttons — metric toggle: one button per ``y`` column, toggling that
  series' visibility via Chart.js dataset visibility (rendered only when a
  chart has more than one ``y`` column).
* ``[data-sort-table]`` on a ``<table>`` + ``[data-sort-key]`` on its
  ``<th>`` cells — client-side column sort: reorders the ALREADY-rendered
  ``<tr>`` rows by parsed numeric or lexicographic comparison; no data
  re-fetch, no re-render from the data model.

All hooks are driven purely by component properties / the embedded data —
never hardcoded to any specific dashboard (the budget-variance example is
TASK-1873's acceptance proof, not part of this implementation).
"""

from __future__ import annotations

import html
import json
import logging
import uuid
from pathlib import Path
from typing import Any

# Ensure the core v1 catalog components are registered so lowering can resolve them.
import parrot.outputs.a2ui.catalog.components  # noqa: F401
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)

logger = logging.getLogger(__name__)

_SURFACE_NAME = "interactive-html"

#: Vendored Chart.js v4.5.1 UMD bundle (MIT license header preserved in the
#: file itself). Shares the `formats/assets/` placement convention with the
#: vendored ECharts bundle (`echarts.py`'s `_ECHARTS_JS_PATH`).
_CHART_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "chart.umd.min.js"

# A2UI Chart type -> Chart.js chart type.
_CHART_TYPE = {
    "bar": "bar",
    "line": "line",
    "area": "line",
    "scatter": "scatter",
    "pie": "pie",
}

_STYLE = (
    "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
    "margin:1rem;color:#1a1a1a}"
    ".a2ui-card{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:.5rem 0}"
    ".a2ui-row{display:flex;gap:1rem}.a2ui-col{display:flex;flex-direction:column}"
    ".a2ui-text{margin:.25rem 0}.a2ui-title{font-size:1.4rem;font-weight:700}"
    ".a2ui-heading{font-size:1.15rem;font-weight:600}.a2ui-subtitle{color:#5b6b8c}"
    ".a2ui-section{margin:.5rem 0}"
    ".a2ui-tabs{display:flex;gap:.25rem;margin:.5rem 0}"
    ".daytab{padding:.25rem .75rem;border:1px solid #ccc;border-radius:999px;"
    "background:#fff;cursor:pointer}.daytab.active{background:#1f3864;color:#fff}"
    ".a2ui-metric-toggle{display:flex;gap:.25rem;margin:.5rem 0}"
    ".metricbtn{padding:.2rem .6rem;border:1px solid #ccc;border-radius:4px;"
    "background:#f4f4f4;cursor:pointer}.metricbtn.active{background:#2e8b57;color:#fff}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{border:1px solid #ddd;padding:.35rem .5rem;text-align:left;font-size:.9rem}"
    "th[data-sort-key]{cursor:pointer;user-select:none}"
)

_CONTAINER_COMPONENTS = {"Column": "a2ui-col", "Row": "a2ui-row", "Card": "a2ui-card"}

_BEHAVIOR_JS = r"""
(function () {
  "use strict";

  function reportData() {
    var el = document.getElementById("report-data");
    if (!el) return {};
    try { return JSON.parse(el.textContent); } catch (e) { return {}; }
  }
  reportData(); // parsed for validation / future generic $bind use; charts embed their own config.

  function buildDatasets(cfg, rows) {
    return (cfg.y || []).map(function (col) {
      return { label: col, data: rows.map(function (r) { return r[col]; }) };
    });
  }

  var chartTypeMap = { bar: "bar", line: "line", area: "line", scatter: "scatter", pie: "pie" };

  document.querySelectorAll("[data-chart-config]").forEach(function (canvas) {
    var cfg = JSON.parse(canvas.getAttribute("data-chart-config"));
    var rows = (cfg.tabs && cfg.tabs.length) ? cfg.tabs[0].data : (cfg.data || []);
    var chart = new Chart(canvas, {
      type: chartTypeMap[cfg.type] || "bar",
      data: {
        labels: rows.map(function (r) { return r[cfg.x]; }),
        datasets: buildDatasets(cfg, rows),
      },
      options: { plugins: { legend: { display: !!cfg.showLegend } } },
    });

    var chartId = canvas.getAttribute("data-chart");

    var tabsGroup = document.querySelector('[data-tabs-for="' + chartId + '"]');
    if (tabsGroup) {
      tabsGroup.querySelectorAll("[data-tab-index]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          tabsGroup.querySelectorAll("[data-tab-index]").forEach(function (b) {
            b.classList.remove("active");
          });
          btn.classList.add("active");
          var idx = parseInt(btn.getAttribute("data-tab-index"), 10);
          var tabRows = (cfg.tabs[idx] && cfg.tabs[idx].data) || [];
          chart.data.labels = tabRows.map(function (r) { return r[cfg.x]; });
          chart.data.datasets = buildDatasets(cfg, tabRows);
          chart.update();
        });
      });
    }

    var toggleGroup = document.querySelector('[data-metric-toggle-for="' + chartId + '"]');
    if (toggleGroup) {
      toggleGroup.querySelectorAll("[data-metric-index]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          btn.classList.toggle("active");
          var idx = parseInt(btn.getAttribute("data-metric-index"), 10);
          var meta = chart.getDatasetMeta(idx);
          meta.hidden = !btn.classList.contains("active");
          chart.update();
        });
      });
    }
  });

  document.querySelectorAll("[data-sort-table]").forEach(function (table) {
    var state = {};
    var headers = table.querySelectorAll("th[data-sort-key]");
    headers.forEach(function (th, colIndex) {
      th.addEventListener("click", function () {
        var tbody = table.querySelector("tbody");
        var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
        var key = th.getAttribute("data-sort-key");
        var asc = state[key] !== "asc";
        state[key] = asc ? "asc" : "desc";
        rows.sort(function (a, b) {
          var av = a.children[colIndex] ? a.children[colIndex].textContent : "";
          var bv = b.children[colIndex] ? b.children[colIndex].textContent : "";
          var an = parseFloat(av.replace(/[^0-9.-]/g, ""));
          var bn = parseFloat(bv.replace(/[^0-9.-]/g, ""));
          var cmp;
          if (!isNaN(an) && !isNaN(bn)) { cmp = an - bn; } else { cmp = av.localeCompare(bv); }
          return asc ? cmp : -cmp;
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
      });
    });
  });
})();
"""


def _safe_json(value: Any) -> str:
    """Serialize ``value`` for safe embedding inside an inline ``<script>``."""
    return json.dumps(value, default=str).replace("</", "<\\/")


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=True, supports_actions=False, supports_updates=False, output="text/html"
    ),
)
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    """Self-contained interactive HTML renderer (vendored Chart.js + vanilla JS)."""

    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact:
        """Render an envelope to a self-contained, interactive HTML ``RenderedArtifact``.

        Args:
            envelope: The validated ``createSurface`` envelope.
            bake: Kept for ABC compatibility; this renderer always resolves
                ALL bindings via ``bake_envelope`` before rendering (the
                interactivity comes from client-side JS/day-tabs acting on
                the ALREADY-resolved data, not from unresolved live pointers).

        Returns:
            A ``RenderedArtifact`` with ``mime_type="text/html"``.
        """
        baked_components = bake_envelope(envelope)
        body_parts = [self._render_top(bc) for bc in baked_components]

        data_model_json = _safe_json(envelope.data_model)
        chart_js = _CHART_JS_PATH.read_text(encoding="utf-8")

        document = (
            "<!DOCTYPE html>"
            '<html lang="en"><head><meta charset="utf-8">'
            f"<title>{html.escape(envelope.surface_id)}</title>"
            f"<style>{_STYLE}</style></head>"
            f'<body>{"".join(body_parts)}'
            f'<script type="application/json" id="report-data">{data_model_json}</script>'
            f"<script>{chart_js}</script>"
            f"<script>{_BEHAVIOR_JS}</script>"
            "</body></html>"
        )
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="text/html",
            content=document.encode("utf-8"),
            filename=f"{envelope.surface_id}.html",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
        )

    # -- top-level component dispatch ---------------------------------------

    def _render_top(self, comp: dict[str, Any]) -> str:
        name = comp["component"]
        if name == "Chart":
            return self._render_chart(comp.get("properties", {}) or {})
        if name == "DataTable":
            return self._render_datatable(comp.get("properties", {}) or {})
        if name == "Infographic":
            return self._render_infographic(comp.get("properties", {}) or {})
        return self._render_via_lowering(comp)

    def _render_descriptor(self, descriptor: dict[str, Any]) -> str:
        """Render a nested component descriptor (e.g. inside an Infographic section)."""
        name = descriptor.get("component")
        properties = descriptor.get("properties") or {}
        if name == "Chart":
            return self._render_chart(properties)
        if name == "DataTable":
            return self._render_datatable(properties)
        try:
            entry = get_component(name)
        except KeyError:
            logger.warning("Unknown nested component %r; skipping.", name)
            return ""
        lowered = entry.component_cls().lower(
            Component(id=f"nested-{uuid.uuid4().hex[:8]}", component=name, properties=properties),
            {},
        )
        return self._render_basic(lowered)

    # -- standard lowering path (Card/KPICard/Form/Map/Timeline/Report/…) ---

    def _render_via_lowering(self, comp: dict[str, Any]) -> str:
        name = comp["component"]
        try:
            entry = get_component(name)
        except KeyError:
            node = BasicNode(**comp)
            return self._render_basic(node)
        lowered = entry.component_cls().lower(
            Component(
                id=comp.get("id", ""),
                component=name,
                properties=comp.get("properties", {}) or {},
                children=comp.get("children", []) or [],
            ),
            {},
        )
        return self._render_basic(lowered)

    def _render_basic(self, node: BasicNode) -> str:
        """Recursively render a lowered Basic Catalog node to escaped HTML (mirrors SSR-HTML)."""
        component = node.component
        props = node.properties or {}

        if component == "Text":
            role = props.get("role", "")
            text = props.get("text")
            cls = f"a2ui-text a2ui-{html.escape(str(role))}" if role else "a2ui-text"
            return f'<p class="{cls}">{html.escape("" if text is None else str(text))}</p>'

        if component == "Image":
            src = str(props.get("src", ""))
            if src.startswith("data:"):
                return f'<img src="{html.escape(src, quote=True)}" alt="">'
            return f'<div class="a2ui-image" data-image-url="{html.escape(src, quote=True)}">[image]</div>'

        children_html = "".join(self._render_basic(child) for child in node.children)
        css_class = _CONTAINER_COMPONENTS.get(component, f"a2ui-{html.escape(component.lower())}")
        return f'<div class="{css_class}">{children_html}</div>'

    # -- Chart / DataTable / Infographic (graphics-needing, intercepted) ----

    def _render_chart(self, props: dict[str, Any]) -> str:
        """Render a live Chart.js ``<canvas>`` from RESOLVED Chart properties.

        Bypasses catalog lowering entirely (``ChartComponent.lower()``
        intentionally degrades to a text summary — real graphics are a
        renderer concern, same precedent as ``EChartsRenderer``).
        """
        chart_id = f"chart-{uuid.uuid4().hex[:8]}"
        rows = props.get("data")
        rows = rows if isinstance(rows, list) else []
        y_columns = props.get("y") or []
        tabs = props.get("tabs")
        config: dict[str, Any] = {
            "type": props.get("type", "bar"),
            "x": props.get("x"),
            "y": y_columns,
            "data": rows,
            "showLegend": bool(props.get("showLegend", True)),
        }
        if isinstance(tabs, list) and tabs:
            config["tabs"] = tabs

        title = props.get("title")
        title_html = f'<p class="a2ui-heading">{html.escape(str(title))}</p>' if title else ""

        tabs_html = ""
        if isinstance(tabs, list) and tabs:
            buttons = "".join(
                f'<button type="button" class="daytab{" active" if i == 0 else ""}" '
                f'data-tab-index="{i}">{html.escape(str(tab.get("label", i)))}</button>'
                for i, tab in enumerate(tabs)
                if isinstance(tab, dict)
            )
            tabs_html = f'<div class="a2ui-tabs" data-tabs-for="{chart_id}">{buttons}</div>'

        toggle_html = ""
        if len(y_columns) > 1:
            buttons = "".join(
                f'<button type="button" class="metricbtn active" data-metric-index="{i}">'
                f"{html.escape(str(col))}</button>"
                for i, col in enumerate(y_columns)
            )
            toggle_html = (
                f'<div class="a2ui-metric-toggle" data-metric-toggle-for="{chart_id}">'
                f"{buttons}</div>"
            )

        config_attr = html.escape(_safe_json(config), quote=True)
        return (
            f'<div class="a2ui-card a2ui-chart-wrap">{title_html}{tabs_html}{toggle_html}'
            f'<canvas data-chart="{chart_id}" data-chart-config="{config_attr}"></canvas>'
            "</div>"
        )

    def _render_datatable(self, props: dict[str, Any]) -> str:
        """Render a real, sortable ``<table>`` from RESOLVED DataTable properties.

        Bypasses catalog lowering entirely (``DataTableComponent.lower()``
        carries resolved rows as an OPAQUE property on an empty ``Column``
        node — real tabular rendering is a renderer concern here).
        """
        columns = props.get("columns") or []
        rows = props.get("data")
        rows = rows if isinstance(rows, list) else []
        title = props.get("title")

        title_html = f'<p class="a2ui-heading">{html.escape(str(title))}</p>' if title else ""
        header_cells = "".join(
            f'<th data-sort-key="{html.escape(str(col.get("name", "")), quote=True)}">'
            f'{html.escape(str(col.get("title") or col.get("name", "")))}</th>'
            for col in columns
            if isinstance(col, dict)
        )
        body_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = "".join(
                f"<td>{html.escape('' if (v := row.get(col.get('name'))) is None else str(v))}</td>"
                for col in columns
                if isinstance(col, dict)
            )
            body_rows.append(f"<tr>{cells}</tr>")

        return (
            f'<div class="a2ui-card a2ui-table-wrap">{title_html}'
            f"<table data-sort-table><thead><tr>{header_cells}</tr></thead>"
            f'<tbody>{"".join(body_rows)}</tbody></table></div>'
        )

    def _render_infographic(self, props: dict[str, Any]) -> str:
        """Render an Infographic's title/subtitle/sections, recursing into
        nested descriptors via :meth:`_render_descriptor` (Chart/DataTable
        aware) rather than delegating to ``InfographicComponent.lower()``
        (which would degrade nested Charts/DataTables to text summaries)."""
        parts: list[str] = []
        title = props.get("title")
        if title is not None:
            parts.append(f'<p class="a2ui-text a2ui-title">{html.escape(str(title))}</p>')
        subtitle = props.get("subtitle")
        if subtitle is not None:
            parts.append(f'<p class="a2ui-text a2ui-subtitle">{html.escape(str(subtitle))}</p>')

        for section in props.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_parts: list[str] = []
            heading = section.get("heading")
            if heading is not None:
                section_parts.append(
                    f'<p class="a2ui-text a2ui-heading">{html.escape(str(heading))}</p>'
                )
            text = section.get("text")
            if text is not None:
                section_parts.append(f'<p class="a2ui-text a2ui-body">{html.escape(str(text))}</p>')
            for descriptor in section.get("components") or []:
                if isinstance(descriptor, dict):
                    section_parts.append(self._render_descriptor(descriptor))
            parts.append(f'<div class="a2ui-col a2ui-section">{"".join(section_parts)}</div>')

        return f'<div class="a2ui-card" data-variant="infographic">{"".join(parts)}</div>'
