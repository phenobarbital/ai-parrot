---
id: F005
query_id: Q009,Q019
type: read
intent: what A2UI already has for infographics
executed_at: 2026-09-04T19:45:00Z
parent_id: null
depth: 0
---
# F005 — A2UI already owns an Infographic catalog component, a deterministic adapter from InfographicResponse, a builder, and recipes
## Summary
FEAT-470 added `Infographic` as a Parrot composite catalog component (title/subtitle/theme-hint + ordered `sections[]` nesting catalog children; >1 section lowers to `Tabs`, else `Column`). `adapters/infographic.py` (FEAT-470 TASK-2541, first landed 2026-08-14) is a pure function `infographic_response_to_envelope()` mapping the flat 19-block `InfographicResponse` to that component with a documented block→component table and documented LOSSY degradations (7 chart types collapse via `CHART_TYPE_MAP`; presentation-only fields such as `layout`, `color_by_sign`, per-series colours, table `style` are dropped — "A2UI carries data and semantics, the renderer owns presentation"). `builders.build_infographic()` and `recipes/models.InfographicRecipe` (FEAT-324) are the A2UI-native construction paths (deterministic datasets → transforms → LayoutSpec → envelope).
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infographic.py`
  lines: 1-13, 33-63, 65-71, 144-181
  symbol: `INFOGRAPHIC_SCHEMA`, `INFOGRAPHIC_INSTRUCTIONS`, `InfographicComponent`
  excerpt: |
    "theme": {"type": "string", "description": "Theme hint (e.g. palette name)."}
    Vocabulary is inspired by the legacy InfographicHTMLRenderer ... inspiration only, no code reuse.
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py`
  lines: 1-70, 599-640
  symbol: `infographic_response_to_envelope`, `CHART_TYPE_MAP`
  excerpt: |
    Known lossy degradations (spec §8, OQ-C): radar/heatmap/treemap/gauge/funnel/waterfall/donut collapse;
    Presentation-only fields (layout, color_by_sign, per-series colors, table style, bullet columns…) are dropped
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/__init__.py`
  lines: 1-40
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
  lines: 216-242
  symbol: `build_infographic`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py`
  lines: 1-10, 32-39, 235
  symbol: `InfographicRecipe`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py`
  lines: 18-45
  symbol: `finalize_a2ui_response`
