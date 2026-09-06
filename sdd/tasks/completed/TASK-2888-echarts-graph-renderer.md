# TASK-2888: Add native Graph support to the ECharts renderer

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2887
**Assigned-to**: unassigned

## Context

Implements the ECharts portion of Module 6. ECharts already owns a JSON option
renderer; Graph needs a native graph series using server-prepared positions,
without changing legacy Parrot Chart behavior.

## Scope

- Add viz-core to ECharts supported_catalog_ids.
- Add Graph to supported components and catalog-aware dispatch.
- Implement _build_graph_option with layout none, positions, links, arrows, and edge styles.
- Keep Graph data/state mapping consistent with the shared semantic contract.
- Add renderer capability and option tests.

NOT in scope: SVG implementation, interactive/SSR/PDF lanes, Adaptive Cards,
Folium, bundled UI, or changes to legacy Chart options.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py | MODIFY | Graph series option and capabilities |
| packages/ai-parrot-visualizations/tests/a2ui_renderers/test_echarts_graph.py | CREATE | Graph option and capability tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
    from parrot.outputs.a2ui.renderers import RendererCapabilities, register_a2ui_renderer
    from parrot.outputs.a2ui.models import CreateSurface

### Existing Signatures to Use

    # echarts.py:41-70,128+
    _SERIES_TYPE = {...}
    @register_a2ui_renderer(_SURFACE_NAME, RendererCapabilities(
        interactive=False, supports_actions=False, supports_updates=False,
        output="application/json", supported_components={"Chart"}))
    class EChartsRenderer(AbstractA2UIRenderer):
        async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...
        def _build_option(self, props: dict[str, Any]) -> dict[str, Any]: ...

    # renderers/__init__.py:51-75
    class RendererCapabilities(BaseModel):
        supported_catalog_ids: list[str] = Field(default_factory=lambda: [BASIC_CATALOG_ID, DEFAULT_CATALOG_ID])
        supported_components: set[str] = Field(default_factory=set)

### Does NOT Exist

- _build_graph_option - no Graph option builder exists.
- Viz-core in ECharts capabilities - current defaults contain Basic and Parrot only.
- A Mermaid parser in the UI/renderers - use typed props and positions.

## Implementation Notes

- Dispatch Graph before Chart handling and resolve catalog identity through the shell helper.
- Use series[0].type == graph and layout == none whenever positions are present.
- Preserve input node order and map from/to into ECharts links.
- Do not introduce renderer styling into the Graph schema.

## Acceptance Criteria

- [ ] ECharts capabilities include viz-core and Graph.
- [ ] Graph options include positioned node data and all links.
- [ ] Legacy Chart tests and options remain unchanged.
- [ ] Graph dispatch is catalog-aware.

## Test Specification

- test_echarts_graph_option
- test_echarts_capabilities_include_viz_core

## Agent Instructions

1. Verify the shared SVG/status contract and current ECharts option shape before coding.
2. Keep this task limited to the ECharts satellite module and its tests.
3. Run existing visualization ECharts tests alongside the new tests.

### Completion Note

Implemented as specified. Dispatch uses the shared `_intercept.intercepts()`
helper (not a raw `resolve_component_catalog` call) so a malformed/
ambiguous catalog id never raises mid-render — it just fails to intercept,
falling through exactly like "no Graph present." `_build_graph_option`
strips BOTH `data` and the wire Component-level keys (`id`, `component`,
`catalogId`, `action`, `metadata`, ...) before reconstructing a bare
`GraphSpec` — `props` here is a baked WHOLE-COMPONENT dict
(`component.model_dump()`), unlike `catalog/viz_core/graph.py`'s `lower()`
which only ever sees `component.model_extra` (declared fields already
excluded there); this distinction cost one failed test run before the fix.

**One pre-existing legacy test was also fixed**, a direct and foreseeable
casualty of this task's own acceptance criterion ("ECharts capabilities
include viz-core and Graph"): `test_echarts.py::TestTASK2544::
test_echarts_capabilities` asserted `supported_components == {"Chart"}`
exhaustively (not a subset check) — updated to `{"Chart", "Graph"}`.

Verification: `pytest packages/ai-parrot-visualizations/tests -q` → 302
passed (295 pre-existing + 7 new); `pytest packages/ai-parrot/tests/
outputs/a2ui -q` → 726 passed, 1 skipped (core untouched by this
satellite-only task); `ruff check` clean on all three touched/created
files.
