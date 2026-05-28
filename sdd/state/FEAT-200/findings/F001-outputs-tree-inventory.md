---
id: F001
query_id: Q001
type: tree
intent: Inventario completo de parrot/outputs/
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F001 — `parrot/outputs/` se divide en formatter (core) + formats/ (renderers extraíbles)

## Summary

`parrot/outputs/` contiene: `formatter.py` (orquestador con `OutputFormatter`,
`OutputRetryConfig`, `DEFAULT_RETRY_PROMPTS`), `__init__.py` (re-exports
`OutputMode`, `OutputType`, `OutputFormatter`), `templates/` (vacío — solo
`__init__.py`), y `formats/` (29 archivos: 22 renderers, registry
`__init__.py`, `base.py`, subpaquetes `generators/`, `mixins/`, `assets/`).
El asset `assets/echarts.min.js` pesa 1012K — la mayor parte del peso del
módulo. `formats/__init__.py` (120 líneas) implementa el registry con
lazy-loading: cada renderer se importa solo cuando `get_renderer(OutputMode.X)`
lo pide.

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/`
  excerpt: |
    formatter.py             (orquestador OutputFormatter — core)
    __init__.py              (re-export OutputMode, OutputFormatter)
    templates/__init__.py    (vacío)
    formats/
      __init__.py            (registry lazy)
      base.py                (RenderResult, RenderError)
      altair.py    bokeh.py  card.py  chart.py  d3.py  echarts.py
      holoviews.py html.py   infographic.py  infographic_html.py
      jinja2.py    json.py   map.py   markdown.py  matplotlib.py
      plotly.py    seaborn.py  slack.py  table.py  template_report.py
      whatsapp.py  yaml.py   application.py
      generators/
        abstract.py  panel.py  streamlit.py  terminal.py
      mixins/emaps.py
      assets/echarts.min.js  (1012K)

## Notes

`templates/` está vacío — no hay assets jinja2 propios. Los assets pesados
son `echarts.min.js` (1MB) en formats/. `generators/` produce **apps
completas** (Streamlit/Panel) — distinto de los renderers que producen
HTML/JSON.
