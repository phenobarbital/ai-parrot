---
id: F004
query_id: Q008+Q015
type: read+tree
intent: Understand the deterministic dashboard refresh mechanism (refresh button).
executed_at: 2026-09-01T00:00:00Z
depth: 0
---

# F004 — Deterministic refresh + inline filtering already exist end-to-end (FEAT-324/326 × FEAT-469)

## Summary

`examples/agents/a2ui/deterministic_refresh_dashboard.py` (764 lines) is a complete worked example of exactly the requested lane, and its docstring names the standalone **Flex Program report** (`documents/flex_program_report.html`) as the pattern it generalizes. Mechanism: (1) `@infographic_transformer` functions with declared filter params (`{window}`/`{plan}` placeholders) so filtered replays stay deterministic; (2) `InfographicAuthoringMixin.publish_recipe()` persists an `InfographicRecipe` (FileRecipeStore) with verbatim `LayoutSpec`; (3) `RecipeRunner.run()` replays byte-identically, params override = filtered variant; (4) `A2UIRuntime` over the agent's `ToolManager` provides the RPC leg — surface pushes filter state via `action`+`dataModel` per `surfaceId`, and `callAgentFunction → refresh_dashboard` re-runs the recipe (the "refresh button"). Output artifacts in `artifacts/a2ui_deterministic_refresh/` (dashboards + capabilities.json + artifacts.db). Rendering needs the `interactive-html` renderer from ai-parrot-visualizations (registers on import; needs HTTP origin, not file://).

## Citations

- path: `examples/agents/a2ui/deterministic_refresh_dashboard.py`
  lines: 1-49
  symbol: module docstring
  excerpt: |
    Lineage: the standalone "Flex Program" report (documents/flex_program_report.html)
    established the pattern this example generalizes ... a deterministic recipe
    replays it forever ... FEAT-469 (A2UI Agent Functions runtime) supplies the
    interactive leg: callAgentFunction -> refresh_dashboard.

- path: `examples/agents/a2ui/deterministic_refresh_dashboard.py`
  lines: 74-113
  symbol: imports
  excerpt: |
    from parrot.outputs.a2ui.recipes.store import FileRecipeStore
    from parrot.outputs.a2ui.recipes.transformers import infographic_transformer
    from parrot.outputs.a2ui.runtime import A2UICallContext, A2UIRuntime, SurfaceState
    from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor
    from parrot.tools.infographic_recipes.runner import RecipeRunner
    from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec

- path: `documents/flex_program_report.html`
  symbol: (standalone Flex Program report — the authored original)

- path: `artifacts/a2ui_deterministic_refresh/`
  excerpt: |
    01_dashboard_default.html, 02_dashboard_h2_enterprise.html,
    03_capabilities.json, refresh_all_enterprise.html, artifacts.db

- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  symbol: interactive-html renderer

## Notes

The ticket's `artifacts/a2ui_live/` paths do NOT exist; the real examples are `docs/flex_program_report (39).html` and `documents/flex_program_report.html`.
