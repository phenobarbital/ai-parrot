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
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import BasicNode, TabSpec, to_components
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade
from parrot.outputs.formats.assets.design_system import DesignSystem

from ._semantics import (
    is_kpi_row,
    kpi_unit_html,
    node_extensions,
    semantic_card_class,
    semantic_text_class,
    trend_attr_html,
)
from ._shell import document_shell
from ._table_format import format_cell_html

logger = logging.getLogger(__name__)

_SURFACE_NAME = "interactive-html"

#: Components intercepted BEFORE lowering — their real (graphics/nested)
#: rendering is this renderer's own job, not their catalog `lower()`.
_INTERCEPTED = {"Chart", "DataTable", "Infographic"}


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

  function buildDatasets(cfg, rows) {
    return (cfg.y || []).map(function (col) {
      return { label: col, data: rows.map(function (r) { return r[col]; }) };
    });
  }

  var chartTypeMap = { bar: "bar", line: "line", area: "line", scatter: "scatter", pie: "pie" };

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
      options: { plugins: { legend: { display: !!cfg.showLegend } } },
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
        return f'<p class="{cls}"{attrs}>{_esc(props.get("text"))}{extra}</p>'

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
        return f'<div class="{cls}">{inner}</div>'

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
