---
kind: inline
jira_key: null
fetched_at: 2026-05-28T13:11:03+02:00
summary_oneline: "Extraer parrot/outputs/formats a paquete ai-parrot-visualizations"
---

# Source — ai-parrot-visualizations

Contexto: `parrot/outputs/formats/` contiene ~29 módulos de renderers
de visualización (plotly, altair, bokeh, holoviews, matplotlib,
seaborn, d3, echarts, infographic_html, etc.). Cada uno arrastra
dependencias pesadas de charting/visualization que terminan en el
core de ai-parrot aunque solo se use un puñado en cada deployment.

Objetivo: extraer `parrot/outputs/formats/` (y módulos relacionados
si aplican como `parrot/outputs/templates/`, generadores y mixins)
a un paquete nuevo `ai-parrot-visualizations` dentro del workspace
de monorepo. Estructurar las dependencias pesadas como extras
(`ai-parrot-visualizations[plotly|altair|bokeh|...]`), de modo que
ai-parrot core no las arrastre.

Considerar:
- ¿Qué tan acoplado está `outputs/formats/` al resto de `outputs/`
  (formatter.py, __init__.py)?
- ¿Quién consume los renderers actualmente (handlers, tools,
  generators, bots)?
- ¿Qué deps específicas viven en cada formato y cuáles son las
  pesadas que justifican mover?
- ¿Hay assets (templates, JSS/CSS, fonts) que también deban moverse?
- Diseñar la API pública del nuevo paquete: ¿se mantiene compatibilidad
  con `parrot.outputs.formats.*` vía shim temporal o se migra de golpe?

Resultado esperado: propuesta que liste el contenido a extraer, el
mapa de extras a crear, los consumidores que hay que adaptar, los
riesgos de extracción (deps shared con otros módulos), y una
recomendación de fasing (qué se mueve primero, qué se queda).
