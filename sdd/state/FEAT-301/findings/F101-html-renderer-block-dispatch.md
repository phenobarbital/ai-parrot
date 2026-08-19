---
id: F101
query: Q102, Q103
type: code_analysis
confidence: high
---
# F101: InfographicHTMLRenderer Block Dispatch + CSS State

**File**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`

## Block Dispatch
`_block_renderers` dict (line 675-691) maps 15 block types, one per BlockType
enum member. `_BLOCK_MODEL_MAP` (lines 69-85) mirrors this for dict→model coercion.
Adding new block types requires: (1) model in infographic.py, (2) entry in
_BLOCK_MODEL_MAP, (3) renderer method, (4) entry in _block_renderers.

## CSS Literal Colors (still present)
~20 literal hex colors remain in BASE_CSS:
- `#fff` (white) × 4 occurrences (container, kpi-card, chart-container, th)
- `#f1f5f9` (tr:hover)
- Callout backgrounds: `#eff6ff` (info), `#ecfdf5` (success), `#fffbeb` (warning),
  `#fef2f2` (error), `#f0fdfa` (tip)
- Callout h3 colors: `#065f46`, `#92400e`, `#991b1b`, `#115e59`
- Callout tip border: `#14b8a6`
- Print stylesheet: `#eee`, `#ccc`, `#6366f1`

**Prior Q&A decision (U2)**: migrate these to CSS variables. Still valid.
Callout variants need `--callout-info-bg`, `--callout-success-bg`, etc. tokens
in ThemeConfig v2. The `#fff` references should become `--surface-bg` or similar.

## Dependencies
`markdown_it` and `markupsafe` are imported at lines 15-16 but **not declared**
in `ai-parrot-visualizations/pyproject.toml`. `nh3` is optional (try/except).
`orjson` is also imported but undeclared. All are transitive via ai-parrot core.
