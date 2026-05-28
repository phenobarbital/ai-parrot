---
id: F003
query_id: Q003
type: grep
intent: Mapear deps de terceros por archivo de formato
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F003 — Deps de terceros por formato (~12 libs pesadas, ~8 formatos ligeros)

## Summary

Auditoría módulo por módulo: ~12 renderers requieren libs pesadas
(plotly, altair, bokeh, holoviews, matplotlib, seaborn, folium,
markdown_it, markupsafe, pygments, markdown, pandas, jinja2);
~8 son ligeros (json, yaml, markdown, html, table, card, slack,
whatsapp, application, template_report). `generators/streamlit.py`
embebe `import streamlit as st`; `generators/panel.py` solo necesita
`pandas` (genera código Panel como string, no lo importa).

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/formats/plotly.py`
  excerpt: |
    import plotly.graph_objects as go

- path: `packages/ai-parrot/src/parrot/outputs/formats/altair.py`
  excerpt: |
    import altair as alt
    import pandas as pd

- path: `packages/ai-parrot/src/parrot/outputs/formats/bokeh.py`
  excerpt: |
    from bokeh.plotting import figure
    from bokeh.models import HoverTool

- path: `packages/ai-parrot/src/parrot/outputs/formats/holoviews.py`
  excerpt: |
    import pandas as pd
    import holoviews as hv
    from holoviews import opts

- path: `packages/ai-parrot/src/parrot/outputs/formats/matplotlib.py`
  excerpt: |
    import matplotlib.pyplot as plt
    import numpy as np

- path: `packages/ai-parrot/src/parrot/outputs/formats/seaborn.py`
  excerpt: |
    import seaborn as sns

- path: `packages/ai-parrot/src/parrot/outputs/formats/map.py`
  excerpt: |
    import folium
    import pandas as pd

- path: `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py`
  excerpt: |
    import markdown_it
    import orjson
    from markupsafe import escape

- path: `packages/ai-parrot/src/parrot/outputs/formats/markdown.py`
  excerpt: |
    import markdown
    from markdown.extensions.codehilite import CodeHiliteExtension

- path: `packages/ai-parrot/src/parrot/outputs/formats/chart.py`
  excerpt: |
    from pygments import highlight
    from pygments.lexers.python import PythonLexer
    from pygments.formatters.html import HtmlFormatter

- path: `packages/ai-parrot/src/parrot/outputs/formats/application.py`
  excerpt: |
    import json
    import pandas as pd
    import plotly.express as px

- path: `packages/ai-parrot/src/parrot/outputs/formats/yaml.py`, `table.py`
  excerpt: |
    import pandas as pd
    from datamodel.parsers.json import json_encoder

- path: `packages/ai-parrot/src/parrot/outputs/formats/generators/streamlit.py`
  excerpt: |
    import streamlit as st

## Notes

Mapa de extras tentativos para el nuevo paquete
`ai-parrot-visualizations`:

| Extra              | Deps                                        | Formatos |
|--------------------|---------------------------------------------|----------|
| `plotly`           | `plotly>=5.22`                              | plotly, application |
| `altair`           | `altair>=5.5`                               | altair |
| `bokeh`            | `bokeh>=3.8`, `pandas-bokeh>=0.5`           | bokeh |
| `holoviews`        | `holoviews>=1.21`                           | holoviews |
| `matplotlib`       | `matplotlib>=3.10`                          | matplotlib, seaborn |
| `seaborn`          | `seaborn>=0.13` (+ extra matplotlib)        | seaborn |
| `map`              | `folium>=0.20`                              | map |
| `echarts`          | (sin pip dep; asset JS)                     | echarts |
| `d3`               | (sin pip dep)                               | d3 |
| `infographic`      | `markdown-it-py`, `markupsafe`, `orjson`    | infographic, infographic_html |
| `markdown`         | `markdown>=3`, `pygments`                   | markdown, chart |
| `apps`             | `streamlit>=1.54`, `panel`                  | generators/* |
| `charts` (combo)   | matplotlib + plotly + altair                | combo cómodo |
| `all`              | (todos los anteriores)                      | todo |

Núcleo (sin deps adicionales): json, yaml, html, table, card, slack,
whatsapp, jinja2, template_report, markdown (si se considera ligero).
