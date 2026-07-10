---
id: F005
query: InfographicHTMLRenderer structure
type: read
path: packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
lines: 129-766
---

@register_renderer(OutputMode.INFOGRAPHIC) at line 631.
Handles all 15 block types via `_block_renderers` dict (lines 651-667).
BASE_CSS at lines 129-593 (~464 lines).
render() at lines 671-696: async, returns Tuple[str, Optional[Any]],
  default environment='terminal' (NOT 'default' as spec claims).
render_to_html() at lines 700-766: sync, returns str (complete HTML5 doc).

BASE_CSS uses CSS variables predominantly BUT has literal colors:
- `white`, `#fff` for card/container backgrounds
- Literal hex in callout backgrounds (#eff6ff, #ecfdf5, #fffbeb, #fef2f2, #f0fdfa)
- Literal hex in callout text colors (#065f46, #92400e, #991b1b, #115e59)
- Literal colors in @media print block
