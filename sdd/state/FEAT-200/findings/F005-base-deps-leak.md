---
id: F005
query_id: Q005,Q006
type: read
intent: Estado de extras de visualización + qué deps de viz están en BASE deps
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F005 — `matplotlib` y `seaborn` están en BASE deps (no en extras) — fuga directa al core

## Summary

El bloque `dependencies = [...]` de `packages/ai-parrot/pyproject.toml`
(líneas ~46-99) declara como obligatorias `matplotlib==3.10.0` y
`seaborn==0.13.2`. El resto de libs de viz (`plotly==5.22.0`,
`altair==5.5.0`, `bokeh==3.8.2`, `pandas-bokeh==0.5.5`,
`holoviews==1.21.0`, `streamlit==1.54.0`, `folium==0.20.0`) están en
extras `agents` (l.216-368). El extra `charts` (l.~150) solo declara
`matplotlib`, `cairosvg`, `svglib`, `reportlab`. No existen extras
dedicadas a `plotly`, `altair`, `bokeh` etc. de forma granular —
todo está aglomerado en `agents` o `all`.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 93-94
  excerpt: |
    "matplotlib==3.10.0",
    "seaborn==0.13.2",

- path: `packages/ai-parrot/pyproject.toml`
  lines: 150 area
  excerpt: |
    charts = [
        "matplotlib>=3.7",
        "cairosvg>=2.7",
        "svglib>=1.5",
        "reportlab>=4.0",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 215-367 (extra `agents`)
  excerpt: |
    agents = [
        ...
        "seaborn==0.13.2",          (duplicado con base)
        "streamlit==1.54.0",
        "folium==0.20.0",
        "holoviews==1.21.0",
        "bokeh==3.8.2",
        "pandas-bokeh==0.5.5",
        "plotly==5.22.0",
        "altair==5.5.0",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: ~395
  excerpt: |
    all = [
        "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,scheduler,arango,reddit,embeddings,mcp,charts,docling]"
    ]

## Notes

Conclusiones:

1. **`matplotlib` + `seaborn` se instalan SIEMPRE** con ai-parrot.
   El core acepta ~80MB de transitivas que solo se necesitan si
   alguien usa `OutputMode.MATPLOTLIB` o `OutputMode.SEABORN`.
2. **`plotly`, `altair`, `bokeh`, `holoviews`, `streamlit`, `folium`
   solo entran con `ai-parrot[agents]`** — pero el extra `agents`
   también arrastra `prophet`, `playwright`, `selenium`, `transformers`,
   etc., que no tienen relación con visualización.
3. **No hay extras granulares por renderer** — usuarios que solo
   quieran plotly tienen que pedir `[agents]` y arrastran 30+ libs.
4. La extracción a `ai-parrot-visualizations[plotly|altair|...]`
   resolvería los tres problemas: eliminar `matplotlib/seaborn` del
   core, ofrecer granularidad, y dejar `[agents]` enfocado en bots
   con tools de búsqueda/scraping.
