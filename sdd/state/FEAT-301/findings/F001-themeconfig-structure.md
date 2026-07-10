---
id: F001
query: ThemeConfig model structure
type: read
path: packages/ai-parrot/src/parrot/models/infographic.py
lines: 1033-1095
---

ThemeConfig has 13 fields: `name` (required str) + 11 color fields + `font_family`.
No `model_config` (not frozen, no extra="forbid").
`to_css_variables()` at lines 1075-1095 emits `:root { ... }` with 12 CSS vars.
Color validator at lines 1058-1073 uses `_CSS_COLOR_RE` (lines 46-50), raises ValueError.
`_CSS_COLOR_RE` accepts hex, rgb/rgba, hsl/hsla, named colors, and `var(--*)`.
