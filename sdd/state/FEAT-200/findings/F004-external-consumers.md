---
id: F004
query_id: Q004
type: grep
intent: Consumidores externos a outputs/
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F004 — Solo 3 consumidores en código de producción, todos importan `InfographicHTMLRenderer`

## Summary

`grep -rln "parrot\.outputs\.formats" packages/` retorna 5 archivos —
3 de producción y 2 de tests. Los 3 de producción
(`bots/abstract.py`, `handlers/artifacts.py`, `tools/infographic_toolkit.py`)
importan **exactamente** `InfographicHTMLRenderer` desde
`parrot.outputs.formats.infographic_html`. Ningún consumidor de
producción importa otros renderers directamente — todos usan el
`OutputFormatter` y el registry, lo cual es esperado.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 3877
  excerpt: |
    from ..outputs.formats.infographic_html import InfographicHTMLRenderer

- path: `packages/ai-parrot/src/parrot/handlers/artifacts.py`
  excerpt: |
    from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer

- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  excerpt: |
    from ..outputs.formats.infographic_html import InfographicHTMLRenderer

- path: `packages/ai-parrot/tests/outputs/test_formatter_retry.py`
  excerpt: |
    (test del formatter — usa OutputMode + RENDERERS)

- path: `packages/ai-parrot/tests/outputs/formats/test_echarts.py`
  excerpt: |
    (test directo del renderer ECharts)

## Notes

`OutputMode` y `OutputFormatter` SÍ se usan en todo el codebase
(grep adicional muestra cientos de referencias en `bots/data.py`,
`bots/abstract.py`, `bots/database/agent.py`, `handlers/llm.py`,
`integrations/slack/assistant.py`, `integrations/telegram/wrapper.py`,
`a2a/models.py`, etc.) — por eso `OutputMode` y `OutputFormatter`
**deben quedarse en el core**.

Implicación de extracción: solo necesitamos
(a) reemplazar el switch hardcoded en `formats/__init__.py:33-91`
por descubrimiento dinámico, (b) reemplazar los 3 imports directos
de `InfographicHTMLRenderer` por una llamada al registry
(`get_renderer(OutputMode.INFOGRAPHIC)`), o (c) re-exportar
`InfographicHTMLRenderer` desde el shim.
