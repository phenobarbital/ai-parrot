---
id: F003
query_id: Q008
type: read
intent: block and theme model definitions
executed_at: 2026-09-04T19:45:00Z
parent_id: null
depth: 0
---
# F003 — 19 custom block models + ThemeConfig (CSS token set) live in parrot.models.infographic
## Summary
`parrot/models/infographic.py` (1655 lines) defines `BlockType` and 19 typed block Pydantic models (Title, HeroCard, Summary, Chart, BulletList, Table, Image, Quote, Callout, Divider, Timeline, Progress, Accordion, Checklist, TabView, Chain, Steps, Code, CardGrid), `InfographicResponse` (flat `blocks` list + `template`/`theme` string hints), `JSBundle`, and the theme system. `ThemeConfig` is explicitly "CSS variable configuration for infographic HTML themes" — ~30 colour/font tokens emitted via `to_css_variables()`. Five built-in themes: light, dark, corporate, midnight, petrol. None of this is A2UI vocabulary.
## Citations
- path: `packages/ai-parrot/src/parrot/models/infographic.py`
  lines: 79-101
  symbol: `BlockType`
- path: `packages/ai-parrot/src/parrot/models/infographic.py`
  lines: 316-1004
  symbol: block models (`TitleBlock` … `CardGridBlock`)
- path: `packages/ai-parrot/src/parrot/models/infographic.py`
  lines: 1027-1061
  symbol: `InfographicResponse`
  excerpt: |
    template: Optional[str]  # "Template name used to generate this infographic"
    theme: Optional[str]     # "Color theme hint (e.g., 'light', 'dark', 'corporate', 'vibrant')"
    # layout → template alias
- path: `packages/ai-parrot/src/parrot/models/infographic.py`
  lines: 1290-1330
  symbol: `ThemeConfig`
  excerpt: |
    """CSS variable configuration for infographic HTML themes. ... The to_css_variables() method
    generates the CSS block consumed by InfographicHTMLRenderer."""
- path: `packages/ai-parrot/src/parrot/models/infographic.py`
  lines: 1501-1563
  symbol: `ThemeRegistry`, `theme_registry`
- path: `packages/ai-parrot/src/parrot/models/infographic.py`
  lines: 1569,1586,1603,1620,1638
  symbol: built-in themes light/dark/corporate/midnight/petrol
