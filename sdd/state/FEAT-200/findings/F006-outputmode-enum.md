---
id: F006
query_id: Q007
type: read
intent: OutputMode enum — ubicación y valores
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F006 — `OutputMode` vive en `parrot/models/outputs.py` con 31 valores

## Summary

El enum `OutputMode` se define en `packages/ai-parrot/src/parrot/models/outputs.py:37-71`
con 31 valores que cubren formatos de texto (DEFAULT, JSON, MARKDOWN,
YAML, HTML, CODE, JINJA2, TEMPLATE_REPORT), de visualización (CHART,
ALTAIR, PLOTLY, MATPLOTLIB, BOKEH, SEABORN, MAP, D3, ECHARTS, TABLE,
HOLOVIEWS, CARD, INFOGRAPHIC, APPLICATION), y de canal/integración
(TERMINAL, TELEGRAM, MSTEAMS, WHATSAPP, SLACK), más casos especiales
(JUPYTER, NOTEBOOK, IMAGE, SQL_ANALYSIS). El paquete extraído debe
seguir importando este enum desde `parrot.models.outputs` (acoplamiento
mínimo y estable).

## Citations

- path: `packages/ai-parrot/src/parrot/models/outputs.py`
  lines: 37-71
  excerpt: |
    class OutputMode(str, Enum):
        DEFAULT = "default"
        JSON = "json"
        TERMINAL = "terminal"
        MARKDOWN = "markdown"
        YAML = "yaml"
        HTML = "html"
        JINJA2 = "jinja2"
        ...
        CHART = "chart"
        ALTAIR = "altair"
        PLOTLY = "plotly"
        MATPLOTLIB = "matplotlib"
        BOKEH = "bokeh"
        SEABORN = "seaborn"
        ...
        MAP = "map"
        D3 = "d3"
        ECHARTS = "echarts"
        TABLE = "table"
        HOLOVIEWS = "holoviews"
        CARD = "card"
        ...
        INFOGRAPHIC = "infographic"
        SQL_ANALYSIS = "sql_analysis"

## Notes

`OutputMode` es referenciado en ~30+ archivos del codebase
(bots/abstract.py, bots/data.py, bots/database/agent.py,
handlers/llm.py, integrations/slack/*, integrations/telegram/*,
a2a/models.py, tools/infographic_toolkit.py). Mover el enum a
otro paquete sería un cambio masivo. Mantenerlo en `ai-parrot`
core es la decisión correcta — el paquete de visualizaciones
solo añade implementaciones para subconjuntos del enum.
