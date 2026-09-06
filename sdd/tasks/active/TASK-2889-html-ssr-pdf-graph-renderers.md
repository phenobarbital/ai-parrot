# TASK-2889: Add Graph support to interactive HTML, SSR HTML, PDF, and degradation lanes

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2887
**Assigned-to**: unassigned

## Context

Completes the static and interactive HTML portions of Module 6. These lanes
must intercept Graph before lowering when viz-core is supported, embed the
shared SVG, and degrade visibly and deterministically when unsupported.

## Scope

- Add viz-core capabilities and catalog-aware Graph interception to interactive HTML, SSR HTML, and PDF.
- Render Graph through the shared SVG helper and include Mermaid source in interactive HTML details.
- Handle force-layout and static node-cap degradation records.
- Make Adaptive Cards and Folium lower unsupported viz-core Graphs with a catalog-named degradation record.
- Preserve all existing renderer behavior and capabilities.
- Add native/degraded output tests for each affected lane.

NOT in scope: ECharts, shared SVG implementation, bundled UI, Graph models,
or live action transport.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py | MODIFY | Catalog-aware interception and SVG/details output |
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py | MODIFY | SVG lowering, capabilities, and degradation |
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py | MODIFY | PDF Graph SVG path and capabilities |
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py | MODIFY | Unsupported-catalog degradation |
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py | MODIFY | Unsupported-catalog degradation |
| packages/ai-parrot-visualizations/tests/a2ui_renderers/test_graph_html.py | CREATE | Native and degradation tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.catalog import resolve_catalog
    from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
    from parrot.outputs.a2ui.renderers.degrade import degrade, degradation_record
    from parrot.outputs.a2ui.models import CreateSurface
    from parrot.outputs.a2ui_renderers._graph_svg import render_graph_svg

### Existing Signatures to Use

    # interactive_html.py:120,606,666,1024,1205
    _INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map", "HtmlDocument"}
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...
    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface: ...
    def _render_chart(self, props: dict[str, Any], degradations: list[dict[str, Any]]) -> str: ...

    # ssr_html.py:118-145,276+
    class SSRHTMLRenderer: ...
    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface: ...

    # pdf.py:50,96,99
    def _chart_svg(props: dict) -> str: ...
    class PDFRenderer(SSRHTMLRenderer): ...

    # renderers/degrade.py:24,46
    def degrade(...): ...
    def degradation_record(...): ...

### Does NOT Exist

- Graph entries in _INTERCEPTED or renderer capability catalog lists - current code is legacy bare-name.
- _render_graph / Graph SVG dispatch - no native Graph path exists.
- Viz-core support in Adaptive Cards or Folium - those lanes must degrade.
- Literal hex color mapping in static renderer output - use shared semantic DesignSystem tokens.

## Implementation Notes

- Existing Parrot entries become (DEFAULT_CATALOG_ID, name) pairs; add only (VIZ_CORE_CATALOG_ID, Graph).
- Use the shell intercepts helper to resolve component catalog versus surface default.
- PDF inherits SSR behavior and retains its current Chart-specific path.
- Force layout degrades to layered on static lanes; oversize graphs lower to a truncated readable edge list.
- Unsupported-catalog degradation names VIZ_CORE_CATALOG_ID.

## Acceptance Criteria

- [ ] Interactive HTML, SSR HTML, and PDF declare viz-core and natively embed Graph SVG.
- [ ] Interactive HTML includes Mermaid source in collapsed details.
- [ ] Force and oversize cases record degradation while preserving readable output.
- [ ] Adaptive Cards and Folium lower Graph with one catalog-specific degradation record.
- [ ] Existing renderer tests and legacy outputs remain unchanged.

## Test Specification

- test_interactive_html_intercepts_graph
- test_ssr_force_layout_degrades_to_layered
- test_ssr_graph_too_large_degrades
- test_adaptive_cards_degrades_unsupported_catalog
- test_pdf_graph_renders_svg
- Capability checks for interactive-html, ssr_html, and pdf.

## Agent Instructions

1. Verify TASK-2887 SVG API and current degradation record shape first.
2. Keep interception before lowering and preserve all legacy non-viz-core dispatch.
3. Run the full visualization renderer test suite after implementation.
