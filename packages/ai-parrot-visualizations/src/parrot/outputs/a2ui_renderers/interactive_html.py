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
(``interactive=False``, fully static), this renderer intercepts ``Chart``,
``DataTable``, and ``Infographic`` BEFORE catalog lowering (``Chart``/
``DataTable``'s ``lower()`` implementations intentionally degrade to a
text/opaque-property summary — real graphics/table rendering is a RENDERER
concern, same precedent as :class:`~parrot.outputs.a2ui_renderers.echarts.EChartsRenderer`;
``Infographic`` is intercepted so its nested section descriptors can
recurse into the SAME Chart/DataTable interception rather than degrading
them via ``InfographicComponent.lower()``). Every other component renders
via the v1.0 lowering pipeline (composite -> ``to_components()`` -> bake ->
reconstruct -> dispatch by primitive), same order as SSR-HTML (FEAT-470
TASK-2543): a composite must be lowered+flattened BEFORE baking, since
template/binding expansion is exclusively ``bake_envelope``'s job.

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
* ``[data-tabs="<id>"]`` nav + ``[data-tab-index]`` buttons paired with
  ``[data-tabs-panes="<id>"]`` + ``[data-pane-index]`` panes (FEAT-470
  TASK-2544) — the generic ``Tabs`` PRIMITIVE's click-to-switch behavior,
  the same active-class-toggle pattern as the Chart day-tabs above.

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
from typing import Any, Optional

# Ensure the v1.0 catalogs (Basic primitives + Parrot composites) are
# registered so lowering/dispatch can resolve every component name.
import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode, TabSpec, to_components
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade

logger = logging.getLogger(__name__)

_SURFACE_NAME = "interactive-html"

#: Components intercepted BEFORE lowering — their real (graphics/nested)
#: rendering is this renderer's own job, not their catalog `lower()`.
_INTERCEPTED = {"Chart", "DataTable", "Infographic"}

#: Vendored Chart.js v4.5.1 UMD bundle (MIT license header preserved in the
#: file itself). Shares the `formats/assets/` placement convention with the
#: vendored ECharts bundle (`echarts.py`'s `_ECHARTS_JS_PATH`).
_CHART_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "chart.umd.min.js"

#: Read ONCE at import time (not per-render) — this is a 200KB+ file and
#: `render()` is an async method; re-reading it synchronously on every call
#: would block the event loop repeatedly for no benefit, since the bundle
#: never changes at runtime.
_CHART_JS_SOURCE = _CHART_JS_PATH.read_text(encoding="utf-8")

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
    ".a2ui-list-vertical{display:flex;flex-direction:column;gap:.25rem}"
    ".a2ui-list-horizontal{display:flex;flex-direction:row;gap:.5rem}"
    ".a2ui-text{margin:.25rem 0}.a2ui-title{font-size:1.4rem;font-weight:700}"
    ".a2ui-heading{font-size:1.15rem;font-weight:600}.a2ui-subtitle{color:#5b6b8c}"
    ".a2ui-section{margin:.5rem 0}.a2ui-notice{color:#a00}"
    ".a2ui-tabs{display:flex;gap:.25rem;margin:.5rem 0}"
    ".daytab{padding:.25rem .75rem;border:1px solid #ccc;border-radius:999px;"
    "background:#fff;cursor:pointer}.daytab.active{background:#1f3864;color:#fff}"
    ".a2ui-metric-toggle{display:flex;gap:.25rem;margin:.5rem 0}"
    ".metricbtn{padding:.2rem .6rem;border:1px solid #ccc;border-radius:4px;"
    "background:#f4f4f4;cursor:pointer}.metricbtn.active{background:#2e8b57;color:#fff}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{border:1px solid #ddd;padding:.35rem .5rem;text-align:left;font-size:.9rem}"
    "th[data-sort-key]{cursor:pointer;user-select:none}"
    ".a2ui-tabs-nav{display:flex;gap:.25rem;border-bottom:1px solid #ddd;margin:.5rem 0}"
    ".tabbtn{padding:.35rem .75rem;border:1px solid #ccc;border-bottom:none;"
    "border-radius:6px 6px 0 0;background:#f4f4f4;cursor:pointer}"
    ".tabbtn.active{background:#fff;font-weight:600}"
    ".a2ui-tab-pane{padding:.5rem 0}"
    ".a2ui-divider-h{border:none;border-top:1px solid #ddd;margin:.5rem 0}"
    ".a2ui-divider-v{border:none;border-left:1px solid #ddd;margin:0 .5rem;height:1em;display:inline-block}"
    ".a2ui-field{margin:.25rem 0}.a2ui-field-label{font-weight:600;display:block}"
    ".a2ui-field-value{color:#333}.a2ui-button{display:inline-block;padding:.25rem .5rem;"
    "border:1px solid #999;border-radius:4px;background:#f5f5f5}"
    ".a2ui-modal{border:2px dashed #999;padding:.5rem;margin:.5rem 0}"
)

_CONTAINER_COMPONENTS = {"Column": "a2ui-col", "Row": "a2ui-row"}

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

  // Generic Tabs primitive (FEAT-470 TASK-2544) — same active-class-toggle
  // pattern as the Chart day-tabs above, generalized to any [data-tabs] nav.
  document.querySelectorAll("[data-tabs]").forEach(function (nav) {
    var tabsId = nav.getAttribute("data-tabs");
    var panesGroup = document.querySelector('[data-tabs-panes="' + tabsId + '"]');
    if (!panesGroup) return;
    nav.querySelectorAll("[data-tab-index]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        nav.querySelectorAll("[data-tab-index]").forEach(function (b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");
        var idx = btn.getAttribute("data-tab-index");
        panesGroup.querySelectorAll("[data-pane-index]").forEach(function (pane) {
          pane.style.display = pane.getAttribute("data-pane-index") === idx ? "" : "none";
        });
      });
    });
  });
})();
"""


def _safe_json(value: Any) -> str:
    """Serialize ``value`` for safe embedding inside an inline ``<script>``."""
    return json.dumps(value, default=str).replace("</", "<\\/")


def _esc(value: Any) -> str:
    """HTML-escape any baked (already-resolved) value as a display string."""
    return html.escape("" if value is None else str(value))


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=True,
        supports_actions=False,
        supports_updates=False,
        output="text/html",
        supported_components={
            "AudioPlayer",
            "Button",
            "Card",
            "CheckBox",
            "ChoicePicker",
            "Column",
            "DateTimeInput",
            "Divider",
            "Icon",
            "Image",
            "List",
            "Modal",
            "Row",
            "Slider",
            "Tabs",
            "Text",
            "TextField",
            "Video",
            "Chart",
            "DataTable",
            "Infographic",
        },
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
        # Lower every composite EXCEPT the ones this renderer intercepts
        # directly (Chart/DataTable/Infographic) BEFORE baking — same
        # lowering-then-bake order as SSR-HTML (FEAT-470 TASK-2543): a
        # composite may lower to a row `ChildTemplate`, and template/binding
        # expansion is exclusively `bake_envelope`'s job.
        lowered_envelope = self._lower_composites(envelope)
        baked_components = bake_envelope(lowered_envelope)
        by_id = {bc["id"]: bc for bc in baked_components}

        # Render every component NOT referenced as someone else's child —
        # i.e. every genuine top-level entry (matches this renderer's
        # existing multi-top-level-block convention: a bare envelope of
        # independent components, not necessarily a single "root").
        referenced = self._referenced_ids(baked_components)
        degradations: list[dict[str, Any]] = []
        body_parts = [
            self._render_top(bc, by_id, degradations) for bc in baked_components if bc["id"] not in referenced
        ]

        data_model_json = _safe_json(envelope.data_model)
        chart_js = _CHART_JS_SOURCE

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
            metadata={"degraded": degradations} if degradations else {},
        )

    # -- lowering (composites -> flat primitives, BEFORE baking) -------------

    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface:
        """Replace every non-primitive composite EXCEPT Chart/DataTable/Infographic
        (this renderer's own intercepted components) with its lowered +
        flattened primitive equivalents, in the envelope's flat component list.
        """
        new_components: list[Component] = []
        for comp in envelope.components:
            if comp.component in _INTERCEPTED:
                new_components.append(comp)
                continue
            try:
                entry = get_component(comp.component)
            except KeyError:
                entry = None
            if entry is not None and not entry.definition.is_primitive:
                tree = entry.component_cls().lower(comp, envelope.data_model)
                new_components.extend(to_components(tree, id_prefix=f"{comp.id}-lc"))
            else:
                new_components.append(comp)
        return envelope.model_copy(update={"components": new_components})

    @staticmethod
    def _referenced_ids(baked_components: list[dict[str, Any]]) -> set[str]:
        """Every id referenced as a `child`/`children`/`tabs[].child` elsewhere."""
        referenced: set[str] = set()
        for bc in baked_components:
            if isinstance(bc.get("child"), str):
                referenced.add(bc["child"])
            if isinstance(bc.get("children"), list):
                referenced.update(c for c in bc["children"] if isinstance(c, str))
            for tab in bc.get("tabs") or []:
                if isinstance(tab, dict) and isinstance(tab.get("child"), str):
                    referenced.add(tab["child"])
        return referenced

    # -- top-level component dispatch ---------------------------------------

    def _render_top(
        self, comp: dict[str, Any], by_id: dict[str, dict[str, Any]], degradations: list[dict[str, Any]]
    ) -> str:
        name = comp["component"]
        if name == "Chart":
            return self._render_chart(comp)
        if name == "DataTable":
            return self._render_datatable(comp)
        if name == "Infographic":
            return self._render_infographic(comp)
        node = self._reconstruct(comp["id"], by_id)
        return self._render_basic(node, degradations)

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
        node_id = f"nested-{uuid.uuid4().hex[:8]}"
        if entry.definition.is_primitive:
            node = BasicNode(id=node_id, component=name, **properties)
        else:
            component = Component(id=node_id, component=name, **properties)
            node = entry.component_cls().lower(component, {})
        return self._render_basic(node, [])

    # -- tree reconstruction (mirrors ssr_html.SSRHTMLRenderer._reconstruct) -

    def _reconstruct(self, node_id: str, by_id: dict[str, dict[str, Any]]) -> BasicNode:
        """Reconstruct a nested :class:`BasicNode` from the flat baked dict list.

        Every node reaching this point is already a Basic Catalog primitive
        (composites — other than Chart/DataTable/Infographic — were lowered
        + flattened by :meth:`_lower_composites` BEFORE baking).
        """
        data = dict(by_id[node_id])
        name = data.pop("component")
        data.pop("id", None)
        child_id = data.pop("child", None)
        children_ids = data.pop("children", None)
        metadata = data.pop("metadata", None)

        tabs: Optional[list[TabSpec]] = None
        if "tabs" in data:
            tabs = [
                TabSpec(title=tab["title"], child=self._reconstruct(tab["child"], by_id)) for tab in data.pop("tabs")
            ]

        if name == "Modal" and isinstance(data.get("content"), str):
            data["content"] = self._reconstruct(data["content"], by_id)

        child = self._reconstruct(child_id, by_id) if isinstance(child_id, str) else None
        children = [self._reconstruct(cid, by_id) for cid in children_ids] if isinstance(children_ids, list) else None
        return BasicNode(
            id=node_id,
            component=name,
            child=child,
            children=children,
            tabs=tabs,
            metadata=metadata,
            **data,
        )

    # -- 18-primitive dispatch (mirrors ssr_html.SSRHTMLRenderer) ------------

    def _render_basic(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        component = node.component
        method = getattr(self, f"_render_prim_{component}", None)
        if method is None:
            degradations.append(degradation_record(node, f"{_SURFACE_NAME} has no renderer for {component}"))
            return self._render_prim_Text(degrade(node, "no renderer available"), degradations)
        return method(node, degradations)

    def _render_children(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        children = node.children if isinstance(node.children, list) else []
        return "".join(self._render_basic(child, degradations) for child in children)

    def _render_prim_Text(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        role = None
        if node.metadata is not None and node.metadata.extensions is not None:
            role = node.metadata.extensions.root.get("parrot_role")
        cls = f"a2ui-text a2ui-{_esc(role)}" if role else "a2ui-text"
        return f'<p class="{cls}">{_esc(props.get("text"))}</p>'

    def _render_prim_Image(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        src = str(props.get("url", ""))
        alt = _esc(props.get("description"))
        if src.startswith("data:"):
            return f'<img src="{html.escape(src, quote=True)}" alt="{alt}">'
        return f'<div class="a2ui-image" data-image-url="{html.escape(src, quote=True)}">{alt or "[image]"}</div>'

    def _render_prim_Icon(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        name = props.get("name")
        if isinstance(name, dict) and "svgPath" in name:
            return f'<span class="a2ui-icon" data-svg-path="{html.escape(str(name["svgPath"]), quote=True)}"></span>'
        return f'<span class="a2ui-icon" data-icon="{_esc(name)}"></span>'

    def _render_prim_Video(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        url = str(props.get("url", ""))
        poster = props.get("posterUrl")
        poster_attr = f' poster="{html.escape(str(poster), quote=True)}"' if poster else ""
        return f'<video controls{poster_attr} data-video-url="{html.escape(url, quote=True)}"></video>'

    def _render_prim_AudioPlayer(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        url = str(props.get("url", ""))
        description = props.get("description")
        parts = [f'<audio controls data-audio-url="{html.escape(url, quote=True)}"></audio>']
        if description:
            parts.append(f'<span class="a2ui-audio-desc">{_esc(description)}</span>')
        return "".join(parts)

    def _render_prim_Row(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        return f'<div class="a2ui-row">{self._render_children(node, degradations)}</div>'

    def _render_prim_Column(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        return f'<div class="a2ui-col">{self._render_children(node, degradations)}</div>'

    def _render_prim_List(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        direction = props.get("direction", "vertical")
        cls = "a2ui-list-horizontal" if direction == "horizontal" else "a2ui-list-vertical"
        return f'<div class="{cls}">{self._render_children(node, degradations)}</div>'

    def _render_prim_Card(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        inner = self._render_basic(node.child, degradations) if node.child is not None else ""
        return f'<div class="a2ui-card">{inner}</div>'

    def _render_prim_Tabs(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        """A ``Tabs`` primitive -> a ``[data-tabs]`` nav + ``[data-tabs-panes]``
        pair, reusing the same click-to-switch behavior pattern as the
        existing Chart day-tabs JS (FEAT-470 TASK-2544 Scope)."""
        tabs_id = f"tabs-{node.id or uuid.uuid4().hex[:8]}"
        buttons = []
        panes = []
        for i, tab in enumerate(node.tabs or []):
            active = " active" if i == 0 else ""
            buttons.append(
                f'<button type="button" class="tabbtn{active}" data-tab-index="{i}">' f"{_esc(tab.title)}</button>"
            )
            display = "" if i == 0 else ' style="display:none"'
            panes.append(
                f'<div class="a2ui-tab-pane" data-pane-index="{i}"{display}>'
                f"{self._render_basic(tab.child, degradations)}</div>"
            )
        nav = f'<div class="a2ui-tabs-nav" data-tabs="{tabs_id}">{"".join(buttons)}</div>'
        panes_html = f'<div data-tabs-panes="{tabs_id}">{"".join(panes)}</div>'
        return nav + panes_html

    def _render_prim_Modal(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        content_node = props.get("content")
        inner = self._render_basic(content_node, degradations) if isinstance(content_node, BasicNode) else ""
        return f'<div class="a2ui-modal">{inner}</div>'

    def _render_prim_Divider(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        axis = props.get("axis", "horizontal")
        if axis == "vertical":
            return '<span class="a2ui-divider-v"></span>'
        return '<hr class="a2ui-divider-h">'

    def _render_prim_Button(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        inner = self._render_basic(node.child, degradations) if node.child is not None else ""
        return f'<span class="a2ui-button">{inner}</span>'

    def _render_prim_TextField(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        return self._render_labeled_value(props.get("label"), props.get("value"))

    def _render_prim_CheckBox(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        checked = "☑" if props.get("value") else "☐"
        return self._render_labeled_value(props.get("label"), checked)

    def _render_prim_ChoicePicker(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        value = props.get("value")
        display = ", ".join(str(v) for v in value) if isinstance(value, list) else value
        return self._render_labeled_value(props.get("label"), display)

    def _render_prim_Slider(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        return self._render_labeled_value(props.get("label"), props.get("value"))

    def _render_prim_DateTimeInput(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        return self._render_labeled_value(props.get("label"), props.get("value"))

    def _render_labeled_value(self, label: Any, value: Any) -> str:
        label_html = f'<span class="a2ui-field-label">{_esc(label)}</span>' if label else ""
        return f'<div class="a2ui-field">{label_html}<span class="a2ui-field-value">{_esc(value)}</span></div>'

    # -- Chart / DataTable / Infographic (graphics-needing, intercepted) ----

    def _render_chart(self, props: dict[str, Any]) -> str:
        """Render a live Chart.js ``<canvas>`` from RESOLVED Chart properties.

        Bypasses catalog lowering entirely (``ChartComponent.lower()``
        intentionally degrades to a text summary — real graphics are a
        renderer concern, same precedent as ``EChartsRenderer``). ``props``
        is the baked component's own top-level dict (v1.0 — never nested
        under a "properties" key).
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
            toggle_html = f'<div class="a2ui-metric-toggle" data-metric-toggle-for="{chart_id}">' f"{buttons}</div>"

        config_attr = html.escape(_safe_json(config), quote=True)
        return (
            f'<div class="a2ui-card a2ui-chart-wrap">{title_html}{tabs_html}{toggle_html}'
            f'<canvas data-chart="{chart_id}" data-chart-config="{config_attr}"></canvas>'
            "</div>"
        )

    def _render_datatable(self, props: dict[str, Any]) -> str:
        """Render a real, sortable ``<table>`` from RESOLVED DataTable properties.

        Bypasses catalog lowering entirely (``DataTableComponent.lower()``
        carries resolved rows via a ``ChildTemplate`` — real tabular
        rendering is a renderer concern here). ``props`` is the baked
        component's own top-level dict (v1.0 — never nested).
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
        (which would degrade nested Charts/DataTables to text summaries).
        ``props`` is the baked component's own top-level dict (v1.0)."""
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
                section_parts.append(f'<p class="a2ui-text a2ui-heading">{html.escape(str(heading))}</p>')
            text = section.get("text")
            if text is not None:
                section_parts.append(f'<p class="a2ui-text a2ui-body">{html.escape(str(text))}</p>')
            for descriptor in section.get("components") or []:
                if isinstance(descriptor, dict):
                    section_parts.append(self._render_descriptor(descriptor))
            parts.append(f'<div class="a2ui-col a2ui-section">{"".join(section_parts)}</div>')

        return f'<div class="a2ui-card" data-variant="infographic">{"".join(parts)}</div>'
