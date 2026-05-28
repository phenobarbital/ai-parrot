---
id: F007
query_id: Q008
type: git_log
intent: Historial reciente de outputs/formats — actividad de desarrollo
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F007 — Actividad reciente concentrada en `infographic_html` (multi-tab, blocks, ECharts)

## Summary

Los últimos commits que tocan `outputs/formats/` corresponden al feature
`infographic-html-output` (TASKs 645-664) y a `multi-tab-infographic`
(TASKs 661-664), todos centrados en el renderer `infographic_html.py`
y bloques HTML asociados. No hay actividad reciente en plotly/altair/
bokeh/etc. — los formatos clásicos están estables.

## Citations

- excerpt: |
    822eb063 info changes
    34cbef04 feat(multi-tab-infographic): TASK-661/662/663/664 — Renderer updates
    cc0078c2 infographic fixes
    a3d59542 feat(infographic-html-output): TASK-646 — ECharts Chart Rendering
    03b13eae feat(infographic-html-output): TASK-645 — HTML Block Renderers
    ec5449ee feat: add structured infographic output with block-based templates
    e554d441 fix of markdown tables
    2b50bcd9 fixes on dataset manager and database query
    49536110 feat(monorepo-migration): TASK-398 — Workspace Scaffolding

## Notes

Implicación de timing:
- **`infographic_html` está en desarrollo activo** — extraerlo requiere
  coordinar con el feature en curso (verificar que no haya tasks
  abiertos vía `/sdd-status`).
- **El resto de renderers están dormantes** — bajo riesgo de conflicto
  al extraer plotly/altair/bokeh/etc.
- Recomendación: fasear la extracción dejando `infographic_html` para
  última fase (cuando los features en curso cierren) y arrancando con
  los renderers estables.
