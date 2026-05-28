---
id: F001
queries: [Q001, Q002, Q003, Q004, Q024]
confidence: high
---

# OutputMode.INFOGRAPHIC + InfographicRenderer + InfographicHTMLRenderer all exist

`OutputMode.INFOGRAPHIC = "infographic"` is a first-class member of the
`OutputMode` string enum (packages/ai-parrot/src/parrot/models/outputs.py:70).
Sibling modes include `APPLICATION` (line 51 — Streamlit/Panel/Terminal code
gen), `CHART`, `ECHARTS`, `D3`, `TABLE`, `CARD`. Adding a new OutputMode is
just an enum addition.

**InfographicRenderer** (outputs/formats/infographic.py:49-78) is registered
via `@register_renderer(OutputMode.INFOGRAPHIC, system_prompt=...)`. It
extracts an `InfographicResponse` from the AIMessage and serializes it to
JSON. The `INFOGRAPHIC_SYSTEM_PROMPT` (lines 16-46) is the LLM-facing
instructions describing every block type (`hero_card`, `chart`,
`bullet_list`, `summary`, etc.) and the JSON-only constraint.

**InfographicHTMLRenderer** (outputs/formats/infographic_html.py:582-1573) is
a sibling renderer that converts the same `InfographicResponse` to a
self-contained HTML5 document with inline CSS, inline ECharts JS,
themed via CSS custom properties, and vanilla JS hooks for `tab_view` and
`accordion` interactivity. It is NOT registered via `@register_renderer`
— it is invoked imperatively by `get_infographic()` after content
negotiation.

**Format registry**: `outputs/formats/__init__.py` has lazy-import dispatch
keyed by `OutputMode`. INFOGRAPHIC lazy-loads both `.infographic` and
`.infographic_html` modules (lines 82-84).

## Citations
- packages/ai-parrot/src/parrot/models/outputs.py:39-72 — OutputMode enum
- packages/ai-parrot/src/parrot/outputs/formats/infographic.py:16-46 —
  INFOGRAPHIC_SYSTEM_PROMPT (system prompt registered to the mode)
- packages/ai-parrot/src/parrot/outputs/formats/infographic.py:49 —
  `@register_renderer(OutputMode.INFOGRAPHIC, system_prompt=...)`
- packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:647-711 —
  `render_to_html()` public entry point
- packages/ai-parrot/src/parrot/outputs/formats/__init__.py:82-84 — INFOGRAPHIC
  lazy-loads infographic + infographic_html
