---
id: F004
query_id: Q011
type: read
intent: legacy INFOGRAPHIC renderers and their deprecation status
executed_at: 2026-09-04T19:45:00Z
parent_id: null
depth: 0
---
# F004 — Two OutputMode.INFOGRAPHIC renderers in ai-parrot-visualizations; the HTML one is formally deprecated by FEAT-273 G7
## Summary
`OutputMode.INFOGRAPHIC` maps to two modules in the satellite: `formats/infographic.py` (`InfographicRenderer`, JSON — "the frontend handles all visual rendering", carries `INFOGRAPHIC_SYSTEM_PROMPT` listing all 19 block types) and `formats/infographic_html.py` (`InfographicHTMLRenderer`, 70 KB, self-contained HTML5 + inline CSS via `DesignSystem.stylesheet(theme_cfg, layout)` + inline ECharts; per-block `_render_*` methods, markdown-it, nh3 sanitising). Core `formats/__init__.py` keeps INFOGRAPHIC out of the `_A2UI_REPLACEMENTS` deprecation table ("infographic-JSON is kept") but `get_infographic_html_renderer()` unconditionally emits a DeprecationWarning: "use OutputMode.A2UI with the Infographic catalog component and the SSR-HTML renderer".
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
  lines: 12-27
  symbol: `_A2UI_REPLACEMENTS`
  excerpt: |
    # Kept modes (JSON/YAML/MARKDOWN/SLACK/WHATSAPP/TERMINAL, infographic-JSON) are ABSENT.
- path: `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
  lines: 69
  excerpt: |
    OutputMode.INFOGRAPHIC: (".infographic", ".infographic_html"),
- path: `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
  lines: 119-156
  symbol: `get_infographic_html_renderer`
  excerpt: |
    # FEAT-273 (G7): the infographic-HTML path is superseded; the JSON path is kept.
    warnings.warn("The infographic-HTML renderer path is deprecated (FEAT-273): use OutputMode.A2UI with the
    Infographic catalog component and the SSR-HTML renderer. The infographic-JSON path is unaffected.", DeprecationWarning)
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py`
  lines: 1-7, 16-60, 138-175
  symbol: `INFOGRAPHIC_SYSTEM_PROMPT`, `InfographicRenderer`
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`
  lines: 1-9, 223-260, 296-349, 377-394
  symbol: `InfographicHTMLRenderer`, `render_to_html`
  excerpt: |
    theme_name = theme or data.theme or "light"; theme_cfg = theme_registry.get(theme_name)
    style = DesignSystem.stylesheet(theme_cfg, layout_name)
