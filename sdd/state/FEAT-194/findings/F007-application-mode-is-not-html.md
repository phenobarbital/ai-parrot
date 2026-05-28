---
id: F007
queries: [Q024]
confidence: high
---

# `OutputMode.APPLICATION` is a Streamlit/Panel/Terminal code generator — not the right vehicle

`OutputMode.APPLICATION` (`outputs/formats/application.py:54`,
`OUTPUT_APPLICATION_PROMPT` lines 19-50) instructs the LLM to return a
`PandasAgentResponse`-shaped object with three fields:

- `explanation: str` — narrative text
- `data: <subset>` — relevant rows/columns
- `code: str` — a Python snippet that generates plotly/altair/matplotlib
  visualisations using `df` as the data variable

The `ApplicationRenderer.render()` (lines 56-87) routes to one of three
generators:
- `StreamlitGenerator` — wraps the code in a Streamlit app
- `PanelGenerator` — wraps for Panel/HoloViz
- `TerminalGenerator` — Rich-based TUI

**This is not HTML output.** It produces *code* (or, for terminal, a Rich
renderable). The user's "HTML artifact with potential JavaScript
interaction" is precisely what `OutputMode.INFOGRAPHIC` already produces
via `InfographicHTMLRenderer` — inline ECharts JS + vanilla JS for
`tab_view` and `accordion`.

So APPLICATION is **not** a candidate hook for FEAT-194. INFOGRAPHIC is.

## Citations
- packages/ai-parrot/src/parrot/outputs/formats/application.py:19-87 —
  ApplicationRenderer + system prompt
- packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:551-579 —
  TAB_JS / ACCORDION_JS interactive snippets (existing JS interaction)
