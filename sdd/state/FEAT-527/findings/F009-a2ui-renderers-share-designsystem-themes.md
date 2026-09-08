---
id: F009
query_id: Q009 follow-up
type: read
intent: do A2UI HTML renderers support the infographic themes?
executed_at: 
parent_id: F005
depth: 1
---
# F009 — Themes already bridge both lanes: DesignSystem (FEAT-493) resolves ThemeConfig for the legacy HTML renderer AND for the A2UI ssr-html / interactive-html / pdf renderers
## Summary
Core ships only the renderer contract (`parrot.outputs.a2ui.renderers`); concrete A2UI renderers live in the satellite `parrot.outputs.a2ui_renderers` (ssr_html, interactive_html, pdf, echarts, folium_map, adaptive_cards). `DesignSystem` (FEAT-493, satellite `formats/assets/design_system`) composes CSS from `theme_registry` + `ThemeConfig.to_css_variables()` and is explicitly shared by "every backend-rendered HTML lane (interactive-html, ssr-html, pdf, formats/infographic_html)". A2UI renderers call `DesignSystem.resolve(envelope, theme_default, layout_default)` reading the theme hint from the envelope. `interactive_html` intercepts the `Infographic` component before lowering to render nested Chart/DataTable natively. So the theme registry is NOT legacy-only; what remains legacy-only is the *template* registry and the 19 block models.
## Citations
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py`
  lines: 1-20, 26, 79-145
  symbol: `DesignSystem`, `DesignSystem.stylesheet`, `DesignSystem.resolve`
  excerpt: |
    Every backend-rendered HTML lane (interactive-html, ssr-html, pdf, formats/infographic_html) shares this single composer
    * theme — palette, resolved via theme_registry (light, dark, corporate, midnight, petrol).
    * layout — density/structure (report, analytics, print).
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py`
  lines: 1-12
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py`
  lines: 150-164, 225-231
  excerpt: |
    theme, layout = DesignSystem.resolve(envelope, theme_default=self.theme, layout_default=self.layout)
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  lines: 1-25, 576-588, 625
  excerpt: |
    this renderer intercepts Chart, DataTable, and Infographic BEFORE catalog lowering
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py`
  lines: 113-126
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_shell.py`
  lines: 8, 23-57
