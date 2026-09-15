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
* ``trendline`` inside that config — a least-squares line over the first y
  column, fitted IN THE BROWSER so it follows the rows a day-tab or a filter
  leaves on screen, drawn dashed and kept out of the hover readout.
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
* ``[data-filterbar]`` (FEAT-493 TASK-2716) — a ``FilterBar``'s rendered
  root: ``[data-filter-column]`` per filter (searchable multiselect —
  ``[data-msf-toggle]``, ``[data-msf-search]``, ``[data-act="all"/"none"]``,
  and its checkboxes), ``[data-filter-reset="<bar-id>"]`` (global reset),
  ``[data-filter-chips="<bar-id>"]`` / ``[data-filter-summary="<bar-id>"]``
  (live selection chips / summary line). Filtering never re-fetches or
  re-renders from scratch: a filtered ``<table>``'s already-formatted
  ``<tr data-row="...">`` rows (TASK-2711) are only shown/hidden, and each
  chart's ORIGINAL embedded rows (``data-chart-config``) are re-filtered
  and handed back to Chart.js. A filter applies only to a section whose
  bound rows carry that filter's column — checked per-row/per-dataset,
  never a hardcoded map.

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

# Ensure the v1.0 catalogs (Basic primitives + Parrot composites) are
# registered so lowering/dispatch can resolve every component name.
import parrot.outputs.a2ui.catalog.basic
import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — ensure registration
import parrot.outputs.a2ui.catalog.viz_core  # noqa: F401 — ensure Graph registration (FEAT-529)
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode, DEFAULT_CATALOG_ID, TabSpec, to_components
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.catalog.viz_core.graph import GraphComponent
from parrot.outputs.a2ui.graph import MAX_STATIC_NODES, GraphSpec, GraphTooLargeError, to_mermaid
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade
from parrot.outputs.formats.assets.design_system import DesignSystem

from ._graph_svg import render_graph_svg
from ._intercept import intercepts
from ._semantics import (
    humanize_key,
    is_kpi_row,
    kpi_comparison_html,
    kpi_unit_html,
    kpi_value_display,
    node_extensions,
    semantic_card_class,
    semantic_text_class,
    trend_attr_html,
)
from ._shell import document_shell
from ._table_format import format_cell_html, is_numeric_column

# NOTE (post-review, FEAT-522): deliberately NOT a top-level `from .folium_map
# import build_map_document`. `folium_map.py` builds its `_OFFLINE_URL_MAP`
# constant eagerly at ITS OWN import time, which requires `folium` to be
# installed — a top-level import here would make `folium` a hard,
# unconditional import-time dependency of the ENTIRE `interactive-html`
# renderer surface (breaking `import interactive_html` for anyone using only
# Chart/DataTable/Infographic rendering without the optional `map` extra).
# `build_map_document` is imported lazily inside `_render_map()` instead, so
# that cost is paid only when a Map component is actually rendered.

logger = logging.getLogger(__name__)

_SURFACE_NAME = "interactive-html"

#: Components intercepted BEFORE lowering — their real (graphics/nested)
#: rendering is this renderer's own job, not their catalog `lower()`. All
#: Parrot catalog, bare-name unambiguous (FEAT-529 Module 0: Graph is
#: viz-core-only and resolved catalog-aware via `_GRAPH_INTERCEPT_TABLE`
#: below, not this set).
_INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map", "HtmlDocument"}

#: Chart types a least-squares line can be drawn over. Cartesian, category
#: x-axis: the fit runs over row ORDER, so a pie, a donut or a radar has no
#: axis for it to mean anything along. Scatter is left out for a different
#: reason -- its x is a value, not a position, so fitting over the index
#: would draw a line that is not the regression a reader would expect.
_TRENDABLE_CHART_TYPES = {"bar", "line", "area"}

#: The one (catalog_id, name) pair intercepted as a native Graph — used
#: with the shared catalog-aware `intercepts()` helper (FEAT-529).
_GRAPH_INTERCEPT_TABLE = frozenset({(VIZ_CORE_CATALOG_ID, "Graph")})


def _propagate_extensions(parent: Component, lowered: list[Component]) -> list[Component]:
    """Union ``parent.metadata.extensions`` onto every component ``lowered``
    into (FEAT-499). The child's own key wins on a collision; ``lowered`` is
    already the FULLY FLATTENED descendant list (:func:`to_components`
    flattens the whole tree, not just direct children), so this single pass
    reaches grandchildren too — not just the immediate lowered children.
    """
    parent_ext = (
        parent.metadata.extensions.root
        if parent.metadata is not None and parent.metadata.extensions is not None
        else {}
    )
    if not parent_ext:
        return lowered
    merged_components: list[Component] = []
    for child in lowered:
        child_ext = (
            dict(child.metadata.extensions.root)
            if child.metadata is not None and child.metadata.extensions is not None
            else {}
        )
        merged = {**parent_ext, **child_ext}  # child's own key wins on collision
        merged_components.append(child.model_copy(update={"metadata": ComponentMetadata(extensions=merged)}))
    return merged_components


#: Wire Component-level keys (never part of GraphSpec) — `data` is
#: deliberately KEPT out of this set: `GraphComponent.lower()` reads it off
#: `Component.model_extra` itself for its `parrot_graph_data` pass-through
#: (FEAT-529).
_GRAPH_COMPONENT_ONLY_KEYS = frozenset(
    {"id", "component", "catalogId", "child", "children", "weight", "accessibility", "checks", "action", "metadata"}
)


def _strip_graph_component_keys(props: dict[str, Any]) -> dict[str, Any]:
    """Strip wire Component-level keys from a baked Graph props dict, keeping ``data``."""
    return {key: value for key, value in props.items() if key not in _GRAPH_COMPONENT_ONLY_KEYS}


def _graph_spec_props(props: dict[str, Any]) -> dict[str, Any]:
    """``_strip_graph_component_keys`` plus ``data`` — a bare GraphSpec's own props."""
    return {key: value for key, value in _strip_graph_component_keys(props).items() if key != "data"}


def _truncate_graph_edge_list(tree: BasicNode) -> None:
    """Truncate a lowered ``Graph``'s edge-list ``Column`` children to
    :data:`~parrot.outputs.a2ui.graph.MAX_STATIC_NODES` rows, in place
    (FEAT-529 oversize-graph fallback)."""
    column = tree.child
    if column is None or not isinstance(column.children, list):
        return
    for child in column.children:
        if isinstance(child, BasicNode) and node_extensions(child).get("parrot_role") == "edge-list":
            if isinstance(child.children, list) and len(child.children) > MAX_STATIC_NODES:
                child.children = child.children[:MAX_STATIC_NODES]
            break


#: Vendored Chart.js v4.5.1 UMD bundle (MIT license header preserved in the
#: file itself). Shares the `formats/assets/` placement convention with the
#: vendored ECharts bundle (`echarts.py`'s `_ECHARTS_JS_PATH`).
_CHART_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "chart.umd.min.js"

#: Read ONCE at import time (not per-render) — this is a 200KB+ file and
#: `render()` is an async method; re-reading it synchronously on every call
#: would block the event loop repeatedly for no benefit, since the bundle
#: never changes at runtime.
_CHART_JS_SOURCE = _CHART_JS_PATH.read_text(encoding="utf-8")

# A2UI Chart type -> Chart.js chart type. FEAT-527: donut/radar are Chart.js
# natives (doughnut/radar); the 5 new types (gauge/funnel/waterfall/heatmap/
# treemap) have no Chart.js equivalent and degrade to "bar" — see
# `_UNSUPPORTED_CHART_TYPES` and `_render_chart()`.
_CHART_TYPE = {
    "bar": "bar",
    "line": "line",
    "area": "line",
    "scatter": "scatter",
    "pie": "pie",
    "donut": "doughnut",
    "radar": "radar",
}

#: Chart types with no Chart.js native equivalent — degrade to "bar" with a
#: recorded, visible degradation (never silent). FEAT-527.
_UNSUPPORTED_CHART_TYPES = frozenset({"gauge", "funnel", "waterfall", "heatmap", "treemap"})

_CONTAINER_COMPONENTS = {"Column": "a2ui-col", "Row": "a2ui-row"}

#: A pager over a handful of rows is worse UX than none (spec §8 leaves this
#: constant's final home open — a renderer constant unless a caller asks for
#: per-table control). Search + pagination render only above this threshold.
_PAGINATION_ROW_THRESHOLD = 100

_BEHAVIOR_JS = r"""
(function () {
  "use strict";

  function reportData() {
    var el = document.getElementById("report-data");
    if (!el) return {};
    try { return JSON.parse(el.textContent); } catch (e) { return {}; }
  }
  reportData(); // parsed for validation / future generic $bind use; charts embed their own config.

  // A mid-tone grey, so the fitted line holds up against either a light or a
  // dark card without ever borrowing a colour that means something.
  var TREND_COLOR = "#94a3b8";

  // Series colours, chosen rather than left to Chart.js. Its default plugin
  // fills with alpha, which survives a screen and washes out on paper —
  // printed, the bars read as ghosts of themselves. These are solid and at a
  // weight that holds on white.
  //
  // No red and no green in the set, on purpose: those two belong to the
  // deltas, where they mean good news and bad. Here colour is identity — the
  // reader gets the series from the legend, not from the hue — and a chart
  // borrowing the verdict colours would make "Missed" look like a judgement
  // the chart is not making.
  var SERIES_COLORS = [
    "#2563eb", "#d97706", "#0d9488", "#7c3aed", "#db2777", "#475569",
    "#0891b2", "#a16207",
  ];

  function seriesColor(cfg, i) {
    var palette = (cfg.palette && cfg.palette.length) ? cfg.palette : SERIES_COLORS;
    return palette[i % palette.length];
  }

  // Chart.js sizes its text for a screen. The canvas is then rasterised and
  // scaled down to the page width, taking the type with it — axis labels and
  // the legend came out at around seven points. Bigger here so they land
  // legible on paper, and darker so they are read as labels rather than as
  // grid furniture.
  Chart.defaults.font.size = 14;
  Chart.defaults.color = "#334155";

  // Least squares over the first y column, drawn dashed and without markers
  // so nobody reads the fitted line as measured data. Returns null when
  // there is nothing to fit: fewer than two numbers, or every x the same.
  function trendData(rows, col) {
    var n = 0, sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
    rows.forEach(function (r, i) {
      var y = Number(r[col]);
      if (r[col] === null || r[col] === undefined || isNaN(y)) return;
      n += 1; sumX += i; sumY += y; sumXY += i * y; sumXX += i * i;
    });
    if (n < 2) return null;
    var denominator = n * sumXX - sumX * sumX;
    if (denominator === 0) return null;
    var slope = (n * sumXY - sumX * sumY) / denominator;
    var intercept = (sumY - slope * sumX) / n;
    return rows.map(function (_, i) { return slope * i + intercept; });
  }

  // A regression over whichever rows are on screen. It is computed HERE and
  // not once in Python because this function runs again on every day-tab
  // switch and every FilterBar change: a line baked server-side would keep
  // the slope of data the reader is no longer looking at.
  function buildDatasets(cfg, rows) {
    var names = cfg.yLabels || [];
    var datasets = (cfg.y || []).map(function (col, i) {
      var color = seriesColor(cfg, i);
      return {
        label: names[i] || col,
        data: rows.map(function (r) { return r[col]; }),
        backgroundColor: color,
        borderColor: color,
        borderWidth: cfg.type === "line" || cfg.type === "area" ? 2.5 : 0,
        pointRadius: cfg.type === "line" || cfg.type === "area" ? 2.5 : undefined,
      };
    });
    // Whether a fit makes sense for this chart type was decided once, in
    // Python, where the FINAL type is known (an unsupported type arrives here
    // already degraded to bar). Re-deciding it here would be a second copy of
    // the same rule, free to drift.
    if (cfg.trendline && datasets.length) {
      var col = (cfg.y || [])[0];
      var fitted = trendData(rows, col);
      if (fitted) {
        datasets.push({
          label: (names[0] || col) + " trend",
          data: fitted,
          type: "line",
          // Grey on purpose, not the next colour off the palette. In this
          // report a colour is a judgement -- green is good news, red is bad
          // -- and a regression is geometry, not a verdict. Left to Chart.js
          // the line came out red, which reads as an alarm nobody raised.
          borderColor: TREND_COLOR,
          backgroundColor: TREND_COLOR,
          borderDash: [6, 4],
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
          isTrend: true,
        });
      }
    }
    return datasets;
  }

  // FEAT-527: donut/radar are Chart.js natives; the 5 new types with no
  // Chart.js equivalent already arrive here pre-degraded to "bar" by
  // _render_chart() (Python side) — this map only needs the natives.
  var chartTypeMap = {
    bar: "bar", line: "line", area: "line", scatter: "scatter", pie: "pie",
    donut: "doughnut", radar: "radar",
  };

  // Populated as each chart is created below; consulted by the FilterBar
  // runtime (TASK-2716) to re-render a chart's ALREADY-embedded rows
  // in place — never a data re-fetch.
  var chartRegistry = {};
  var chartOriginalData = {};

  document.querySelectorAll("[data-chart-config]").forEach(function (canvas) {
    var cfg = JSON.parse(canvas.getAttribute("data-chart-config"));
    var rows = (cfg.tabs && cfg.tabs.length) ? cfg.tabs[0].data : (cfg.data || []);
    var chart = new Chart(canvas, {
      type: chartTypeMap[cfg.type] || "bar",
      data: {
        labels: rows.map(function (r) { return r[cfg.x]; }),
        datasets: buildDatasets(cfg, rows),
      },
      // Bottom, like the pill key a multi-series chart gets: which side the
      // key sits on should not depend on how many series there happen to be.
      options: {
        // The PROPORTION is the thing to declare; the width comes from the
        // page. Sized against a box instead, a chart inherits whatever that
        // box happens to measure — a wrapper with no definite height gave a
        // bitmap of 1063x292, which printed as a strip too flat to read a
        // bar in. `SCREEN_ASPECT`/`PRINT_ASPECT` are the two numbers, and
        // `resizeCharts` swaps them when the medium changes.
        maintainAspectRatio: true,
        aspectRatio: SCREEN_ASPECT,
        plugins: {
          legend: { display: !!cfg.showLegend, position: "bottom" },
          // The fitted line has no value AT a point -- it is the shape of the
          // whole series -- so it stays out of the hover readout.
          tooltip: { filter: function (item) { return !(item.dataset || {}).isTrend; } },
        },
      },
    });

    var chartId = canvas.getAttribute("data-chart");
    chartRegistry[chartId] = chart;
    chartOriginalData[chartId] = rows;

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
        // The buttons ARE the key now (the built-in legend is off whenever
        // they render), so each one carries its series' colour. Chart.js
        // resolves those itself, and the accessor has moved between major
        // versions — a swatch that cannot be coloured simply stays blank
        // rather than throwing and killing the click handler below.
        var dot = btn.querySelector("[data-metric-dot]");
        if (dot) {
          try {
            var meta = chart.getDatasetMeta(parseInt(btn.getAttribute("data-metric-index"), 10));
            var style = meta && meta.controller && meta.controller.getStyle
              ? meta.controller.getStyle(0, false) : null;
            var colour = style && (style.backgroundColor || style.borderColor);
            if (colour) dot.style.background = colour;
          } catch (e) { /* no swatch, still a working toggle */ }
        }
        btn.addEventListener("click", function () {
          btn.classList.toggle("active");
          // The class paints it; aria-pressed is what says it out loud.
          btn.setAttribute("aria-pressed", btn.classList.contains("active") ? "true" : "false");
          var idx = parseInt(btn.getAttribute("data-metric-index"), 10);
          var meta = chart.getDatasetMeta(idx);
          meta.hidden = !btn.classList.contains("active");
          chart.update();
        });
      });
    }
  });

  // A chart is drawn at the width of the screen and then rasterised; the
  // printer scales that bitmap down to the page, taking the type with it, so
  // a 14px axis label lands near six. Re-measuring on `beforeprint` makes
  // Chart.js redraw the canvas at the PAGE's width instead — the type comes
  // out the size it was asked for, and the shorter panel leaves room for
  // what follows it on the sheet. `afterprint` puts the screen back.
  // Wider than tall on a screen, where there is width to spare; closer to
  // square on paper, where the page is a fixed budget and a flat strip wastes
  // the width without showing the shape of anything.
  var SCREEN_ASPECT = 3.2;
  var PRINT_ASPECT = 2.2;

  function resizeCharts(aspect) {
    Object.keys(chartRegistry).forEach(function (id) {
      try {
        var chart = chartRegistry[id];
        chart.options.aspectRatio = aspect;
        chart.resize();
      } catch (e) {
        /* a chart that is already gone is not a print failure */
      }
    });
  }

  function chartsForPrint() {
    resizeCharts(PRINT_ASPECT);
  }

  function chartsForScreen() {
    resizeCharts(SCREEN_ASPECT);
  }

  if (window.matchMedia) {
    var printQuery = window.matchMedia("print");
    if (printQuery.addEventListener) {
      printQuery.addEventListener("change", function (event) {
        if (event.matches) {
          chartsForPrint();
        } else {
          chartsForScreen();
        }
      });
    }
  }
  window.addEventListener("beforeprint", chartsForPrint);
  window.addEventListener("afterprint", chartsForScreen);

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
          var aCell = a.children[colIndex];
          var bCell = b.children[colIndex];
          var av = aCell ? aCell.textContent : "";
          var bv = bCell ? bCell.textContent : "";
          var an, bn;
          // Prefer the raw, unformatted value carried in data-v (TASK-2711)
          // over the rendered text — the rendered text may carry thousands
          // separators / currency formatting that mis-parses as a number.
          if (aCell && aCell.hasAttribute("data-v") && bCell && bCell.hasAttribute("data-v")) {
            an = parseFloat(aCell.getAttribute("data-v"));
            bn = parseFloat(bCell.getAttribute("data-v"));
          } else {
            an = parseFloat(av.replace(/[^0-9.-]/g, ""));
            bn = parseFloat(bv.replace(/[^0-9.-]/g, ""));
          }
          var cmp;
          if (!isNaN(an) && !isNaN(bn)) { cmp = an - bn; } else { cmp = av.localeCompare(bv); }
          return asc ? cmp : -cmp;
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
      });
    });
  });

  // DataTable search + pagination (TASK-2711) — rendered only above
  // _PAGINATION_ROW_THRESHOLD rows; purely client-side over the
  // already-baked rows, no data re-fetch. Registers a per-table hook in
  // `tablePaginators` (keyed by table id) so the FilterBar runtime
  // (TASK-2716) can narrow the paginated set to filtered rows instead of
  // both features fighting over the same `<tr>.style.display` — without
  // this hook, FilterBar's initial no-op `applyFilters()` call would
  // force every row's display back to "", silently undoing pagination's
  // page-1-only visibility on any surface that has both.
  var tablePaginators = {};
  document.querySelectorAll("[data-table-search]").forEach(function (input) {
    var tableId = input.getAttribute("data-table-search");
    var table = document.querySelector('table[data-table="' + tableId + '"]');
    if (!table) return;
    var tbody = table.querySelector("tbody");
    var allRows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    var pager = document.querySelector('[data-table-pager="' + tableId + '"]');
    var pageSize = 50;
    var page = 0;
    var rowFilter = null; // set via tablePaginators[tableId](predicate) by FilterBar

    function matches() {
      var base = rowFilter ? allRows.filter(rowFilter) : allRows;
      var q = input.value.trim().toLowerCase();
      if (!q) return base;
      return base.filter(function (r) { return r.textContent.toLowerCase().indexOf(q) !== -1; });
    }

    function render() {
      var visible = matches();
      var start = page * pageSize;
      var pageRows = visible.slice(start, start + pageSize);
      allRows.forEach(function (r) { r.style.display = "none"; });
      pageRows.forEach(function (r) { r.style.display = ""; });
      if (pager) {
        var totalPages = Math.max(1, Math.ceil(visible.length / pageSize));
        pager.textContent = "Page " + (page + 1) + " of " + totalPages + " (" + visible.length + " rows)";
      }
    }

    input.addEventListener("input", function () {
      page = 0;
      render();
    });
    render();

    tablePaginators[tableId] = function (predicate) {
      rowFilter = predicate;
      page = 0;
      render();
    };
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

  // FilterBar interactive multiselect + client-side dataModel filtering
  // (TASK-2716). A filter applies ONLY to a chart/table whose bound rows
  // carry that filter's column (checked per-row/per-chart-dataset, never a
  // hardcoded map) — a section without the column is left untouched.
  document.querySelectorAll("[data-filterbar]").forEach(function (bar) {
    var barId = bar.getAttribute("data-filterbar");
    var msfs = Array.prototype.slice.call(bar.querySelectorAll("[data-filter-column]"));

    function closeAllPanels() {
      msfs.forEach(function (m) { m.classList.remove("open"); });
    }

    function rowMatches(row, filters) {
      for (var column in filters) {
        if (!(column in row)) continue; // section doesn't carry this column -> untouched
        if (filters[column].indexOf(String(row[column])) === -1) return false;
      }
      return true;
    }

    function activeFilters() {
      var filters = {};
      msfs.forEach(function (msf) {
        var column = msf.getAttribute("data-filter-column");
        var checked = Array.prototype.slice
          .call(msf.querySelectorAll('input[type="checkbox"]:checked'))
          .map(function (cb) { return cb.value; });
        if (checked.length) filters[column] = checked;
      });
      return filters;
    }

    function optionLabel(msf, value) {
      var input = msf.querySelector('input[type="checkbox"][value="' + value.replace(/"/g, '\\"') + '"]');
      return input ? input.closest(".msf-opt").textContent.trim() : value;
    }

    function updateChipsAndSummary(filters) {
      var chipsEl = document.querySelector('[data-filter-chips="' + barId + '"]');
      var summaryEl = document.querySelector('[data-filter-summary="' + barId + '"]');
      var chips = [];
      var summaryParts = [];
      msfs.forEach(function (msf) {
        var column = msf.getAttribute("data-filter-column");
        var label = msf.querySelector(".msf-label").textContent;
        var checked = filters[column];
        if (!checked || !checked.length) {
          summaryParts.push(label + " = all");
          return;
        }
        var labels = checked.map(function (v) { return optionLabel(msf, v); });
        summaryParts.push(label + " = " + labels.join(", "));
        labels.forEach(function (l) {
          chips.push('<span class="msf-chip">' + label + ": " + l + "</span>");
        });
      });
      if (chipsEl) chipsEl.innerHTML = chips.join("");
      if (summaryEl) summaryEl.textContent = "Filters: " + summaryParts.join("; ");
    }

    function showEmptyState(el, show) {
      var notice = el.nextElementSibling;
      var hasNotice = notice && notice.classList && notice.classList.contains("a2ui-filter-empty");
      if (show && !hasNotice) {
        notice = document.createElement("p");
        // Deliberately its own class, distinct from TASK-2711's
        // truncation-notice class: that class's ABSENCE is asserted by
        // test_rich_datatable.py as "table was not truncated", so reusing
        // it here would make that assertion false whenever this runtime
        // is simply present in the page, truncated or not.
        notice.className = "a2ui-filter-empty";
        notice.textContent = "No rows match the current filters.";
        el.insertAdjacentElement("afterend", notice);
        el.style.display = "none";
      } else if (!show && hasNotice) {
        notice.remove();
        el.style.display = "";
      }
    }

    function applyFilters() {
      var filters = activeFilters();
      updateChipsAndSummary(filters);

      // Tables: toggle pre-rendered <tr> visibility — same, already-
      // formatted cells either way (TASK-2711), never a from-scratch
      // client-side re-render. A table with search/pagination (TASK-2711,
      // registered in tablePaginators) delegates through it instead of
      // setting `display` directly, so filtering narrows the paginated
      // set rather than fighting it over the same attribute.
      document.querySelectorAll("table[data-table]").forEach(function (table) {
        var tableId = table.getAttribute("data-table");
        var trs = Array.prototype.slice.call(table.querySelectorAll("tbody tr[data-row]"));
        if (trs.length === 0) return;
        function rowPasses(tr) {
          var row;
          try { row = JSON.parse(tr.getAttribute("data-row")); } catch (e) { row = {}; }
          return rowMatches(row, filters);
        }
        var visibleCount = trs.filter(rowPasses).length;
        if (tablePaginators[tableId]) {
          tablePaginators[tableId](rowPasses);
        } else {
          trs.forEach(function (tr) { tr.style.display = rowPasses(tr) ? "" : "none"; });
        }
        showEmptyState(table, visibleCount === 0);
      });

      // Charts: filter each chart's ORIGINAL embedded rows and redraw.
      Object.keys(chartRegistry).forEach(function (chartId) {
        var chart = chartRegistry[chartId];
        var original = chartOriginalData[chartId] || [];
        var canvas = document.querySelector('canvas[data-chart="' + chartId + '"]');
        if (!canvas) return;
        var cfg = JSON.parse(canvas.getAttribute("data-chart-config"));
        var filtered = original.filter(function (row) { return rowMatches(row, filters); });
        if (original.length > 0) showEmptyState(canvas, filtered.length === 0);
        if (filtered.length === 0) return;
        chart.data.labels = filtered.map(function (r) { return r[cfg.x]; });
        chart.data.datasets = buildDatasets(cfg, filtered);
        chart.update();
      });
    }

    msfs.forEach(function (msf) {
      var toggleBtn = msf.querySelector("[data-msf-toggle]");
      if (toggleBtn) {
        toggleBtn.addEventListener("click", function (evt) {
          evt.stopPropagation();
          var wasOpen = msf.classList.contains("open");
          closeAllPanels();
          if (!wasOpen) msf.classList.add("open");
        });
      }
      var searchInput = msf.querySelector("[data-msf-search]");
      if (searchInput) {
        searchInput.addEventListener("input", function () {
          var q = searchInput.value.trim().toLowerCase();
          msf.querySelectorAll(".msf-opt").forEach(function (opt) {
            opt.style.display = opt.textContent.toLowerCase().indexOf(q) !== -1 ? "" : "none";
          });
        });
      }
      msf.querySelectorAll("[data-act]").forEach(function (actBtn) {
        actBtn.addEventListener("click", function () {
          var checkAll = actBtn.getAttribute("data-act") === "all";
          msf.querySelectorAll(".msf-opt").forEach(function (opt) {
            if (opt.style.display !== "none") opt.querySelector('input[type="checkbox"]').checked = checkAll;
          });
          applyFilters();
        });
      });
      msf.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        cb.addEventListener("change", applyFilters);
      });
    });

    var resetBtn = document.querySelector('[data-filter-reset="' + barId + '"]');
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        msfs.forEach(function (msf) {
          msf.querySelectorAll('input[type="checkbox"]').forEach(function (cb) { cb.checked = false; });
        });
        applyFilters();
      });
    }

    document.addEventListener("click", closeAllPanels);
    applyFilters(); // render the initial chips/summary from lower()'s pre-selected values.
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
        supported_catalog_ids=[BASIC_CATALOG_ID, DEFAULT_CATALOG_ID, VIZ_CORE_CATALOG_ID],
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
            "Map",
            "Graph",
        },
    ),
)
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    """Self-contained interactive HTML renderer (vendored Chart.js + vanilla JS)."""

    def __init__(self, *, theme: str = "light", layout: str = "analytics") -> None:
        """Initialize the renderer with a default ``(theme, layout)`` pair.

        Args:
            theme: Default theme name resolved by
                :class:`~parrot.outputs.formats.assets.design_system.DesignSystem`.
            layout: Default layout name.

        Both keyword arguments MUST default — ``RecipeRunner`` calls
        ``renderer_cls()`` with no arguments (``runner.py``); a required
        parameter here would break every existing recipe run.
        """
        self.theme = theme
        self.layout = layout

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
        theme, layout = DesignSystem.resolve(envelope, theme_default=self.theme, layout_default=self.layout)
        style = DesignSystem.stylesheet(theme, layout)

        document = document_shell(
            title=envelope.surface_id,
            style=style,
            body="".join(body_parts),
            theme=theme,
            layout=layout,
            scripts=(
                f'<script type="application/json" id="report-data">{data_model_json}</script>',
                f"<script>{chart_js}</script>",
                f"<script>{_BEHAVIOR_JS}</script>",
            ),
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
            if comp.component == "Graph" and intercepts(_GRAPH_INTERCEPT_TABLE, comp, envelope.catalog_id):
                new_components.append(comp)
                continue
            try:
                entry = get_component(comp.component)
            except KeyError:
                entry = None
            if entry is not None and not entry.definition.is_primitive:
                tree = entry.component_cls().lower(comp, envelope.data_model)
                lowered = to_components(tree, id_prefix=f"{comp.id}-lc")
                new_components.extend(_propagate_extensions(comp, lowered))
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
            return self._render_chart(comp, degradations)
        if name == "DataTable":
            return self._render_datatable(comp)
        if name == "Infographic":
            return self._render_infographic(comp, degradations)
        if name == "Map":
            return self._render_map(comp)
        if name == "HtmlDocument":
            return self._render_htmldocument(comp)
        if name == "Graph":
            return self._render_graph(comp, degradations)
        node = self._reconstruct(comp["id"], by_id)
        return self._render_basic(node, degradations)

    def _render_descriptor(self, descriptor: dict[str, Any], degradations: list[dict[str, Any]]) -> str:
        """Render a nested component descriptor (e.g. inside an Infographic section)."""
        name = descriptor.get("component")
        properties = descriptor.get("properties") or {}
        if name == "Chart":
            return self._render_chart(properties, degradations)
        if name == "DataTable":
            return self._render_datatable(properties)
        if name == "Map":
            return self._render_map(properties)
        if name == "HtmlDocument":
            return self._render_htmldocument(properties)
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

        tabs: list[TabSpec] | None = None
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
        if "text" not in props:
            # FEAT-499: baking drops the "text" key entirely (never an
            # empty string) when an OPTIONAL binding failed to resolve —
            # omit the whole element, matching _render_infographic's own
            # `if text is not None` precedent, instead of leaving a
            # visible-but-blank <p class="a2ui-...">.
            return ""
        role = None
        if node.metadata is not None and node.metadata.extensions is not None:
            role = node.metadata.extensions.root.get("parrot_role")
        cls = f"a2ui-text a2ui-{_esc(role)}" if role else "a2ui-text"
        semantic_cls = semantic_text_class(node)
        if semantic_cls:
            cls = f"{cls} {semantic_cls}"
        extra = kpi_unit_html(node) if role == "value" else ""
        attrs = trend_attr_html(node) if role == "delta" else ""
        if role == "value":
            display = html.escape(kpi_value_display(node, props.get("text")))
        else:
            display = _esc(props.get("text"))
        return f'<p class="{cls}"{attrs}>{display}{extra}</p>'

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
        if node_extensions(node).get("parrot_variant") == "filter-bar":
            return self._render_filterbar_interactive(node)
        cls = "a2ui-row kpi-grid" if is_kpi_row(node) else "a2ui-row"
        return f'<div class="{cls}">{self._render_children(node, degradations)}</div>'

    def _render_filterbar_interactive(self, node: BasicNode) -> str:
        """Render a ``FilterBar`` (``parrot_variant: "filter-bar"`` Row) as the
        reference interactive control (TASK-2716): a searchable multiselect
        per filter, selection chips, a live filter-state summary, and a
        global reset — matching ``docs/flex_program_report (39).html``'s
        ``.filter-bar``/``.msf-*``/``.reset-btn``/``.filter-summary`` markup,
        which ``components.css`` (TASK-2707) already styles.

        Each child is a ``ChoicePicker`` primitive (TASK-2715's ``lower()``)
        carrying ``label``/``options``/``value`` (pre-selected values) and
        ``parrot_filter_column``. The client-side filtering runtime lives in
        ``_BEHAVIOR_JS`` and hooks purely off the ``data-*`` attributes
        emitted here — never hardcoded to a specific dashboard.
        """
        bar_id = f"filterbar-{node.id or uuid.uuid4().hex[:8]}"
        children = node.children if isinstance(node.children, list) else []
        controls = []
        for child in children:
            if not isinstance(child, BasicNode):
                continue
            props = child.model_extra or {}
            column = node_extensions(child).get("parrot_filter_column", "")
            label = props.get("label") or column
            options = props.get("options") or []
            selected = {o.get("value") for o in options if isinstance(o, dict)} & set(props.get("value") or [])
            opts_html = "".join(
                f'<label class="msf-opt"><input type="checkbox" '
                f'value="{html.escape(str(o.get("value", "")), quote=True)}"'
                f'{" checked" if o.get("value") in selected else ""}> {_esc(o.get("label", o.get("value", "")))}'
                f"</label>"
                for o in options
                if isinstance(o, dict)
            )
            controls.append(
                f'<div class="msf" data-filter-column="{html.escape(str(column), quote=True)}">'
                f'<button class="msf-btn" type="button" data-msf-toggle>'
                f'<span class="msf-label">{_esc(label)}</span><span class="chev">&#9662;</span></button>'
                '<div class="msf-panel">'
                '<input type="text" class="msf-search" placeholder="Search..." data-msf-search>'
                '<div class="msf-actions">'
                '<button type="button" data-act="all">Select all</button>'
                '<button type="button" data-act="none">Clear</button>'
                "</div>"
                f"<div>{opts_html}</div>"
                "</div></div>"
            )
        return (
            f'<div class="filter-bar" data-filterbar="{bar_id}">'
            f'<span class="filter-label">Filters</span>'
            + "".join(controls)
            + f'<button class="reset-btn" type="button" data-filter-reset="{bar_id}">Reset filters</button>'
            "</div>"
            f'<div class="msf-chips" data-filter-chips="{bar_id}"></div>'
            f'<p class="filter-summary" data-filter-summary="{bar_id}"></p>'
        )

    def _render_prim_Column(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        return f'<div class="a2ui-col">{self._render_children(node, degradations)}</div>'

    def _render_prim_List(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        props = node.model_extra or {}
        direction = props.get("direction", "vertical")
        cls = "a2ui-list-horizontal" if direction == "horizontal" else "a2ui-list-vertical"
        return f'<div class="{cls}">{self._render_children(node, degradations)}</div>'

    def _render_prim_Card(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:
        inner = self._render_basic(node.child, degradations) if node.child is not None else ""
        cls = "a2ui-card"
        variant_cls = semantic_card_class(node)
        if variant_cls:
            cls = f"{cls} {variant_cls}"
        # See `ssr_html._render_Card`: the baseline label qualifies the delta,
        # so it follows it.
        return f'<div class="{cls}">{inner}{kpi_comparison_html(node)}</div>'

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

    # -- Chart / DataTable / Infographic / Map (graphics-needing, intercepted) -

    def _render_map(self, props: dict[str, Any]) -> str:
        """Render a live, offline-safe Leaflet map ``<iframe>`` from RESOLVED
        Map properties (FEAT-522).

        Bypasses catalog lowering entirely (``MapComponent.lower()``
        intentionally degrades to a text layer-summary — real map rendering
        is a renderer concern, same precedent as ``_render_chart``/
        ``_render_datatable``). ``props`` is the baked component's own
        top-level dict (v1.0 — never nested under a "properties" key),
        mirroring :meth:`_render_chart`'s exact shape.

        Calls the shared, synchronous
        :func:`~parrot.outputs.a2ui_renderers.folium_map.build_map_document`
        directly — never ``await FoliumMapRenderer().render(...)``, since
        this class's entire internal render chain
        (``_render_top``/``_render_descriptor``) is synchronous (spec §2).
        By this point the document is already offline-safe (every folium
        default CDN resource swapped for an inlined ``data:`` URI —
        TASK-2787), so embedding it in an ``iframe srcdoc`` leaks nothing.

        Imports ``folium_map`` lazily (here, not at module top level) — see
        the note above the module's imports for why.
        """
        from .folium_map import build_map_document

        document, _ = build_map_document(props, cluster_threshold=500)
        escaped = html.escape(document.decode("utf-8"))
        return f'<iframe sandbox="allow-scripts allow-popups" srcdoc="{escaped}"></iframe>'

    def _render_chart(self, props: dict[str, Any], degradations: list[dict[str, Any]]) -> str:
        """Render a live Chart.js ``<canvas>`` from RESOLVED Chart properties.

        Bypasses catalog lowering entirely (``ChartComponent.lower()``
        intentionally degrades to a text summary — real graphics are a
        renderer concern, same precedent as ``EChartsRenderer``). ``props``
        is the baked component's own top-level dict (v1.0 — never nested
        under a "properties" key).

        FEAT-527: ``gauge``/``funnel``/``waterfall``/``heatmap``/``treemap``
        have no Chart.js equivalent — they render as ``"bar"`` AND append a
        record to ``degradations`` (never a silent substitution), plus a
        visible caption naming the original type.
        """
        chart_id = f"chart-{uuid.uuid4().hex[:8]}"
        rows = props.get("data")
        rows = rows if isinstance(rows, list) else []
        y_columns = props.get("y") or []
        tabs = props.get("tabs")
        original_type = props.get("type", "bar")
        degraded_caption = ""
        if original_type in _UNSUPPORTED_CHART_TYPES:
            degradations.append(
                degradation_record(
                    BasicNode(id=props.get("id", chart_id), component="Chart"),
                    f"{_SURFACE_NAME} renders '{original_type}' as bar (no {original_type} support in this surface)",
                )
            )
            degraded_caption = (
                '<p class="a2ui-notice">'
                f"rendered as bar (no {html.escape(str(original_type))} support in this surface)</p>"
            )
        # More than one y column means the metric toggles render, and those
        # carry the colours and the names — so Chart.js' own legend would be
        # a SECOND key saying the same six words. One key, and it is the one
        # you can click.
        has_toggles = len(y_columns) > 1
        config: dict[str, Any] = {
            "type": "bar" if original_type in _UNSUPPORTED_CHART_TYPES else original_type,
            "x": props.get("x"),
            "y": y_columns,
            # Parallel to `y`: the readable name for each series, so the
            # legend and the toggles never disagree about what a series is
            # called.
            "yLabels": [humanize_key(col) for col in y_columns],
            "data": rows,
            "showLegend": bool(props.get("showLegend", True)) and not has_toggles,
        }
        # An author-chosen palette wins over the built-in one, the same
        # precedent the static ECharts surface already set.
        palette = props.get("palette")
        if isinstance(palette, (list, tuple)) and palette:
            config["palette"] = [str(colour) for colour in palette]
        if isinstance(tabs, list) and tabs:
            config["tabs"] = tabs
        # Only when asked for AND only where a straight line means something:
        # a regression through a pie or a radar is nonsense. The type tested
        # is the FINAL one -- a degraded chart is a bar by the time it gets
        # here, and a bar can carry a trend. The flag rides in the embedded
        # config; the line itself is fitted in the browser, over whichever
        # rows a day-tab or a FilterBar leaves on screen.
        if props.get("trendline") and config["type"] in _TRENDABLE_CHART_TYPES:
            config["trendline"] = True

        title = props.get("title")
        title_html = f'<p class="a2ui-heading">{html.escape(str(title))}</p>' if title else ""
        title_html += degraded_caption

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
        if has_toggles:
            buttons = "".join(
                f'<button type="button" class="metricbtn active" aria-pressed="true" '
                f'data-metric-index="{i}">'
                f'<span class="metricbtn-dot" data-metric-dot></span>'
                f"{html.escape(humanize_key(col))}</button>"
                for i, col in enumerate(y_columns)
            )
            toggle_html = f'<div class="a2ui-metric-toggle" data-metric-toggle-for="{chart_id}">' f"{buttons}</div>"

        config_attr = html.escape(_safe_json(config), quote=True)
        # The key goes UNDER the chart: it explains what was just drawn, and
        # above the canvas it pushed the plot down and read as a toolbar.
        return (
            f'<div class="a2ui-card a2ui-chart-wrap">{title_html}{tabs_html}'
            f'<div class="a2ui-chart-canvas">'
            f'<canvas data-chart="{chart_id}" data-chart-config="{config_attr}"></canvas>'
            f"</div>"
            f"{toggle_html}</div>"
        )

    def _render_datatable(self, props: dict[str, Any]) -> str:
        """Render a real, sortable ``<table>`` from RESOLVED DataTable properties.

        Bypasses catalog lowering entirely (``DataTableComponent.lower()``
        carries resolved rows via a ``ChildTemplate`` — real tabular
        rendering is a renderer concern here). ``props`` is the baked
        component's own top-level dict (v1.0 — never nested). Cells are
        formatted per ``TableColumn.type``/``.format`` in Python
        (:func:`~parrot.outputs.a2ui_renderers._table_format.format_cell_html`,
        TASK-2711) — no client-side JS is needed to display a formatted
        value, only to sort/search/paginate the already-rendered rows.
        """
        columns = props.get("columns") or []
        rows = props.get("data")
        rows = rows if isinstance(rows, list) else []
        title = props.get("title")
        total_rows = props.get("totalRows")
        truncated = bool(props.get("truncated"))
        table_id = f"table-{uuid.uuid4().hex[:8]}"

        title_html = f'<p class="a2ui-heading">{html.escape(str(title))}</p>' if title else ""
        # Two things a header row has to get right, and neither was free.
        #
        # A column with no `title` printed its DATA KEY: a report handed to a
        # client read `store_id | store_name | rate` across the top. The key
        # is the fallback of last resort now, humanised on the way out, the
        # same treatment a chart's series names already got.
        #
        # And a numeric header carries `num`, so it right-aligns with the
        # figures beneath it. Left-aligned over right-aligned numbers, a
        # header labels the white space next to its column rather than the
        # column.
        header_parts: list[str] = []
        for col in columns:
            if not isinstance(col, dict):
                continue
            name = str(col.get("name", ""))
            label = str(col.get("title") or humanize_key(name))
            numeric = ' class="num"' if is_numeric_column(col.get("type")) else ""
            header_parts.append(
                f'<th data-sort-key="{html.escape(name, quote=True)}"{numeric}>'
                f"{html.escape(label)}</th>"
            )
        header_cells = "".join(header_parts)

        body_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = "".join(
                format_cell_html(row.get(col.get("name")), col_type=col.get("type"), col_format=col.get("format"))
                for col in columns
                if isinstance(col, dict)
            )
            # Optional, additive row-kind marker: a row may carry a reserved
            # "_rowType" key ("total"/"group") alongside its column values —
            # no such row-level field exists on StructuredTableConfig today,
            # and DataTableComponent.lower()'s row template cannot express
            # per-row metadata without breaking the pinned lowering golden,
            # so this convention is scoped to THIS interception path only
            # (see TASK-2711 Completion Note).
            row_kind = row.get("_rowType")
            row_cls = ""
            if row_kind == "total":
                row_cls = ' class="total-row"'
            elif row_kind == "group":
                row_cls = ' class="group-row"'
            # Raw row values, for client-side FilterBar filtering (TASK-2716):
            # toggling a pre-rendered <tr>'s visibility reuses this row's
            # ALREADY-formatted cells verbatim — never a from-scratch
            # client-side re-render, so filtered rows are guaranteed to look
            # identical to unfiltered ones (TASK-2711's formatting).
            row_attr = html.escape(_safe_json({k: v for k, v in row.items() if k != "_rowType"}), quote=True)
            body_rows.append(f'<tr{row_cls} data-row="{row_attr}">{cells}</tr>')

        notice_html = ""
        if truncated and total_rows is not None:
            notice_html = (
                f'<p class="a2ui-table-notice">showing {len(rows)} of ' f"{html.escape(str(total_rows))} rows</p>"
            )

        search_html = ""
        pager_html = ""
        if len(rows) > _PAGINATION_ROW_THRESHOLD:
            search_html = (
                f'<input type="search" class="a2ui-table-search" '
                f'data-table-search="{table_id}" placeholder="Search...">'
            )
            pager_html = f'<div class="a2ui-table-pager" data-table-pager="{table_id}"></div>'

        return (
            f'<div class="a2ui-card a2ui-table-wrap">{title_html}{search_html}'
            f'<table data-sort-table data-table="{table_id}"><thead><tr>{header_cells}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table>{pager_html}{notice_html}</div>'
        )

    def _render_infographic(self, props: dict[str, Any], degradations: list[dict[str, Any]]) -> str:
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
            # Consecutive KPI cards are a grid, the rest render in place. The
            # stylesheet has always carried `.kpi-grid` (four columns, down to
            # two on a phone) but nothing here ever applied it: the class was
            # only attached to a Row of kpi Cards, and a section is a COLUMN
            # whose first child is its heading -- so eight KPIs came out as
            # eight full-width blocks, three screens of scrolling for what the
            # app shows in two rows. Grouping by RUN, not by container, is the
            # rule the Svelte canvas already uses (`Infographic.svelte`).
            run: list[str] = []

            def _flush() -> None:
                if not run:
                    return
                section_parts.append(f'<div class="kpi-grid">{"".join(run)}</div>')
                run.clear()

            for descriptor in section.get("components") or []:
                if not isinstance(descriptor, dict):
                    continue
                fragment = self._render_descriptor(descriptor, degradations)
                if descriptor.get("component") == "KPICard":
                    run.append(fragment)
                    continue
                _flush()
                section_parts.append(fragment)
            _flush()
            parts.append(f'<div class="a2ui-col a2ui-section">{"".join(section_parts)}</div>')

        return f'<div class="a2ui-card" data-variant="infographic">{"".join(parts)}</div>'

    def _render_htmldocument(self, props: dict[str, Any]) -> str:
        """Render an ``HtmlDocument`` as a sandboxed ``<iframe>`` (FEAT-527).

        Bypasses catalog lowering entirely (``HtmlDocumentComponent.lower()``
        intentionally degrades to a text placeholder and never carries the
        raw HTML — real embedding is a renderer concern, same precedent as
        ``EChartsRenderer``/``_render_chart``). ``props`` is the baked
        component's own top-level dict (v1.0 — never nested under a
        "properties" key), so ``html``/``srcUrl`` are read directly here,
        pre-lowering.

        Security: ``sandbox="allow-scripts"`` WITHOUT ``allow-same-origin``
        — the embedded document cannot reach the host DOM/storage. The raw
        ``html`` is escaped into the ``srcdoc`` attribute (never evaluated by
        the host page itself); inline style only (FEAT-493 self-contained
        invariant — no external CSS/JS).
        """
        title = props.get("title") or ""
        title_html = f'<h3 class="a2ui-heading">{html.escape(str(title))}</h3>' if title else ""
        iframe_style = "width:100%;min-height:480px;border:1px solid #ccc"

        raw_html = props.get("html")
        if raw_html is not None:
            iframe = (
                f'<iframe sandbox="allow-scripts" style="{iframe_style}" '
                f'srcdoc="{html.escape(str(raw_html), quote=True)}"></iframe>'
            )
        else:
            src_url = props.get("srcUrl") or ""
            iframe = (
                f'<iframe sandbox="allow-scripts" style="{iframe_style}" '
                f'src="{html.escape(str(src_url), quote=True)}"></iframe>'
            )

        return f'<section class="a2ui-html-document">{title_html}{iframe}</section>'

    # -- Graph (FEAT-529) ----------------------------------------------------

    def _render_graph(self, props: dict[str, Any], degradations: list[dict[str, Any]]) -> str:
        """Render a viz-core ``Graph`` as an inline SVG plus its mermaid source.

        Bypasses catalog lowering entirely (``GraphComponent.lower()``
        intentionally degrades to a text/edge-list summary — real graphics
        are a renderer concern, same precedent as ``_render_chart``).
        ``props`` is the baked component's own top-level dict.

        ``layout.engine == "force"`` has no interactive-renderer-specific
        force-directed drawing here either (spec: force is a hint for
        interactive renderers "only" in general, but THIS static-SVG path
        has none) — it degrades to the deterministic layered layout, same
        as every other static lane. A graph above
        :data:`~parrot.outputs.a2ui.graph.MAX_STATIC_NODES` degrades to
        ``GraphComponent``'s own lowered edge list, truncated to the cap.
        """
        node_id = props.get("id", "graph")
        working_props = dict(props)
        layout = working_props.get("layout") or {}
        if layout.get("engine") == "force":
            degradations.append(
                degradation_record(
                    BasicNode(id=node_id, component="Graph"),
                    f"{_SURFACE_NAME} has no force layout; rendered with the deterministic layered layout instead",
                )
            )
            working_props = {key: value for key, value in working_props.items() if key != "layout"}

        try:
            svg = render_graph_svg(working_props)
        except GraphTooLargeError:
            degradations.append(
                degradation_record(
                    BasicNode(id=node_id, component="Graph"),
                    f"{_SURFACE_NAME}: graph exceeds the static node cap ({MAX_STATIC_NODES}); "
                    "rendered as a truncated edge list",
                )
            )
            return self._render_graph_truncated_fallback(working_props, degradations)

        mermaid_source = to_mermaid(GraphSpec.model_validate(_graph_spec_props(working_props)))
        return (
            '<div class="a2ui-card a2ui-graph-wrap">'
            f"{svg}"
            '<details class="a2ui-graph-source"><summary>Mermaid source</summary>'
            f"<pre>{html.escape(mermaid_source)}</pre></details></div>"
        )

    def _render_graph_truncated_fallback(self, props: dict[str, Any], degradations: list[dict[str, Any]]) -> str:
        """Oversize-graph fallback: ``GraphComponent``'s own lowered tree,
        with its edge-list Column truncated to :data:`MAX_STATIC_NODES` rows.

        ``GraphComponent.lower()`` returns an already self-contained
        ``BasicNode`` tree (no external id references left to resolve), so
        it is handed straight to ``_render_basic`` — unlike the flat baked-
        dict trees ``_reconstruct`` rebuilds elsewhere in this module.
        """
        node_id = props.get("id", "graph")
        component = Component(id=node_id, component="Graph", **_strip_graph_component_keys(props))
        tree = GraphComponent().lower(component, {})
        _truncate_graph_edge_list(tree)
        return self._render_basic(tree, degradations)
