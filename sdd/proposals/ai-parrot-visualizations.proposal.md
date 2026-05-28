---
id: FEAT-200
title: Extraer parrot/outputs/formats a paquete ai-parrot-visualizations con extras granulares
slug: ai-parrot-visualizations
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-28
  summary_oneline: "Extraer parrot/outputs/formats a paquete ai-parrot-visualizations"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-200/
created: 2026-05-28
updated: 2026-05-28
---

# FEAT-200 — Extraer `parrot/outputs/formats` a `ai-parrot-visualizations`

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — solicitud de modularización: sacar visualizaciones pesadas del core
> **Audit**: [`sdd/state/FEAT-200/`](../state/FEAT-200/)

---

## 0. Origin

> `parrot/outputs/formats/` contiene ~29 módulos de renderers
> (plotly, altair, bokeh, holoviews, matplotlib, seaborn, d3, echarts,
> infographic_html, etc.). Cada uno arrastra dependencias pesadas que
> terminan en el core de ai-parrot. Objetivo: extraer a un paquete
> nuevo `ai-parrot-visualizations` dentro del workspace, estructurar
> deps como extras granulares (`[plotly|altair|bokeh|...]`), de modo
> que ai-parrot core no las arrastre.

**Initial signals**:
- Verbos: "extraer", "modularizar", "estructurar como extras".
- Named entities: `parrot/outputs/formats/`, `ai-parrot-visualizations`,
  los 22+ renderers.
- Acceptance criteria implícitos: core sin matplotlib/seaborn/plotly/etc.,
  consumidores actuales siguen funcionando.

---

## 1. Synthesis Summary

La arquitectura ya está **diseñada para extracción**: `formats/__init__.py`
implementa un registry con lazy-loading vía el decorador
`@register_renderer(OutputMode.X)` y la función `get_renderer(mode)`.
Sin embargo el switch de lazy-load tiene 23 ramas hardcoded con
`import_module('.<formato>', 'parrot.outputs.formats')` — hay que
sustituirlo por descubrimiento dinámico (entry-points recomendado).
Solo **3 consumidores de producción** importan renderers directamente,
y los 3 importan el mismo símbolo (`InfographicHTMLRenderer`); el
resto del codebase usa correctamente `OutputFormatter` + registry.
El hallazgo más fuerte: `matplotlib==3.10.0` y `seaborn==0.13.2`
están en las **dependencies BASE** del core, no en extras
(packages/ai-parrot/pyproject.toml:93-94), y `plotly/altair/bokeh/
holoviews/streamlit/folium` están aglomerados en `[agents]` junto
con scraping/finance. La extracción aporta tres beneficios:
sacar matplotlib/seaborn del core, ofrecer granularidad por renderer,
y desacoplar viz de agents.

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Símbolo | Líneas | Rol | Evidencia |
|---|------|---------|--------|-----|-----------|
| 1 | `packages/ai-parrot/src/parrot/outputs/formats/` | 29 archivos | — | Conjunto a extraer | F001 |
| 2 | `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | switch hardcoded `get_renderer` | 33-91 | Reemplazar por descubrimiento dinámico | F002 |
| 3 | `packages/ai-parrot/src/parrot/outputs/formatter.py` | `OutputFormatter`, `OutputRetryConfig`, `DEFAULT_RETRY_PROMPTS` | — | Queda en core | F001, F002 |
| 4 | `packages/ai-parrot/src/parrot/models/outputs.py` | `OutputMode` enum (31 valores) | 37-71 | Queda en core; nuevo paquete depende de él | F006 |
| 5 | `packages/ai-parrot/src/parrot/bots/abstract.py` | `from ..outputs.formats.infographic_html import InfographicHTMLRenderer` | 3877 | Consumidor directo (migrar a registry) | F004 |
| 6 | `packages/ai-parrot/src/parrot/handlers/artifacts.py` | mismo import | — | Consumidor directo (migrar a registry) | F004 |
| 7 | `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | mismo import | — | Consumidor directo (migrar a registry) | F004 |
| 8 | `packages/ai-parrot/pyproject.toml` | `matplotlib==3.10.0`, `seaborn==0.13.2` en BASE deps | 93-94 | Fuga al core — extraer | F005 |
| 9 | `packages/ai-parrot/pyproject.toml` | extra `agents` mezcla viz con scraping/finance | 215-367 | Refactorizar | F005 |
| 10 | `packages/ai-parrot/src/parrot/outputs/formats/assets/echarts.min.js` | 1012K | — | Mover como package-data del extra echarts | F001 |

### 2.2 Constraints Discovered

- **`OutputMode` es central a todo el codebase y NO puede moverse.**
  Lo importan 30+ archivos (bots, handlers, integrations, a2a).
  *Implicación*: `ai-parrot-visualizations` debe depender de `ai-parrot`
  (al menos para el enum) y para acceder al registry.
  *Evidencia*: F006

- **`OutputFormatter` es el orquestador (usado en `bots/abstract.py:477`).**
  Consulta el registry vía `get_renderer`. Debe quedar en core.
  *Implicación*: solo extraemos los renderers concretos; el formatter
  y el registry quedan en ai-parrot.
  *Evidencia*: F002, F004

- **El switch hardcoded de `formats/__init__.py:33-91` lista 23 ramas
  con `import_module()` apuntando a submódulos locales.**
  *Implicación*: hay que reemplazarlo por descubrimiento (entry-points
  group `parrot.renderers` recomendado) que tolere renderers en
  paquetes externos.
  *Evidencia*: F002

- **Solo 3 archivos de producción importan renderers directamente
  (todos `InfographicHTMLRenderer`).**
  *Implicación*: migración trivial. Reemplazar por
  `get_renderer(OutputMode.INFOGRAPHIC)` o re-exportar desde un shim
  en `parrot.outputs.formats.infographic_html` temporalmente.
  *Evidencia*: F004

- **`matplotlib` + `seaborn` están en BASE deps;
  `plotly/altair/bokeh/holoviews/streamlit/folium` en `[agents]`.**
  *Implicación*: la extracción aporta (a) sacar matplotlib/seaborn
  del core, (b) granularidad real por renderer, (c) desacoplar viz
  de scraping/finance.
  *Evidencia*: F005

- **`infographic_html` está en desarrollo activo (multi-tab-infographic,
  infographic-html-output); el resto está dormante.**
  *Implicación*: fasear — extraer renderers estables primero, dejar
  `infographic_html` para la última fase para no chocar con features
  en curso.
  *Evidencia*: F007

- **Asset `echarts.min.js` (1MB) es el peso principal del módulo.**
  *Implicación*: mover junto con `echarts.py` como package-data del
  extra `echarts` en el nuevo paquete.
  *Evidencia*: F001

### 2.3 Recent History

| Commit | When | Author | Message |
|--------|------|--------|---------|
| `34cbef04` | reciente | (sdd) | feat(multi-tab-infographic): TASK-661/662/663/664 — Renderer updates |
| `a3d59542` | reciente | (sdd) | feat(infographic-html-output): TASK-646 — ECharts Chart Rendering |
| `03b13eae` | reciente | (sdd) | feat(infographic-html-output): TASK-645 — HTML Block Renderers |
| `ec5449ee` | hace meses | — | feat: add structured infographic output |
| `49536110` | hace meses | — | feat(monorepo-migration): TASK-398 — Workspace Scaffolding |

Solo `infographic_html` tiene actividad reciente. plotly/altair/bokeh/
matplotlib/seaborn/holoviews/d3/echarts/map están dormantes.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **Paquete `packages/ai-parrot-visualizations/`** (workspace member),
  con su propio `pyproject.toml` declarando extras granulares.
- **Mecanismo de descubrimiento de renderers** en `ai-parrot`
  (entry-points recomendado): reemplaza el switch hardcoded de
  `formats/__init__.py:33-91`.

### What Changes

- **`packages/ai-parrot/src/parrot/outputs/formats/__init__.py`** —
  reemplazar lazy-switch hardcoded por descubrimiento dinámico.
  *Evidencia*: F002
- **`packages/ai-parrot/src/parrot/bots/abstract.py:3877`**,
  **`handlers/artifacts.py`**, **`tools/infographic_toolkit.py`** —
  reemplazar import directo de `InfographicHTMLRenderer` por
  `get_renderer(OutputMode.INFOGRAPHIC)`. *Evidencia*: F004
- **`packages/ai-parrot/pyproject.toml`** —
  - eliminar `matplotlib==3.10.0` y `seaborn==0.13.2` de BASE deps (l.93-94).
  - eliminar `plotly/altair/bokeh/holoviews/streamlit/folium/pandas-bokeh`
    del extra `agents`.
  - añadir nuevo extra `visualizations = ["ai-parrot-visualizations[charts]"]`
    (o agrupación a definir en U2).
  *Evidencia*: F005

### What's Moved

- **Renderers pesados** → `packages/ai-parrot-visualizations/src/parrot_visualizations/renderers/`:
  `altair.py`, `bokeh.py`, `holoviews.py`, `matplotlib.py`, `seaborn.py`,
  `plotly.py`, `d3.py`, `echarts.py`, `map.py`, `infographic.py`,
  `infographic_html.py`, `application.py`, `markdown.py`, `chart.py`.
- **Asset** `echarts.min.js` (1MB) → package-data del extra `echarts`.
- **Generators** (`panel.py`, `streamlit.py`, `terminal.py`, `abstract.py`)
  → `packages/ai-parrot-visualizations/src/parrot_visualizations/generators/`.
- **Mixins** (`emaps.py`) →
  `packages/ai-parrot-visualizations/src/parrot_visualizations/mixins/`.

### What Stays in Core

- **`OutputMode` + `OutputType` enums** (`parrot/models/outputs.py`).
- **`OutputFormatter`**, **`OutputRetryConfig`**, **`DEFAULT_RETRY_PROMPTS`**
  (`parrot/outputs/formatter.py`).
- **Registry**: `Renderer` Protocol, `RENDERERS` dict,
  `register_renderer`, `get_renderer`, `get_output_prompt`,
  `has_system_prompt` (`parrot/outputs/formats/__init__.py` reescrito
  para descubrimiento).
- **`RenderResult`, `RenderError`** (`parrot/outputs/formats/base.py`).
- **Renderers ligeros** sin deps adicionales: `json`, `yaml`, `html`,
  `table`, `card`, `slack`, `whatsapp` (`jinja2`, `template_report`,
  `markdown` a discutir en U2).

### Non-Goals

- No reescribir la API de `OutputFormatter` ni cambiar la firma de los
  renderers.
- No tocar el enum `OutputMode` (estable y central).
- No bloquear el feature en curso `infographic-html-output` /
  `multi-tab-infographic` (faseado: extraer `infographic*` última fase).

### Patterns to Follow

- Mismo modelo de extras granulares ya planteado para
  `ai-parrot-embeddings` (ver propuesta de modularización general).
- Descubrimiento de renderers vía entry-points
  (`[project.entry-points."parrot.renderers"]`) — patrón estándar para
  plugin discovery en Python.

### Integration Risks

- **Usuarios externos** que dependían transitivamente de
  `matplotlib`/`seaborn` tras `pip install ai-parrot` se romperán al
  extraer. *Mitigar*: nota explícita en `CHANGELOG.md` con instrucción
  `pip install ai-parrot[visualizations]` o el extra granular correspondiente.
- **Bug en descubrimiento dinámico** haría que `get_renderer` devuelva
  `None` para modos antes funcionales. *Mitigar*: test de integración
  por cada `OutputMode` (ya hay scaffold en `tests/outputs/`).
- **`infographic_html` en desarrollo activo** — coordinar con
  `/sdd-status` y `/sdd-next` antes de mover; idealmente extraer
  después de cerrar los tasks abiertos.
- **`DEFAULT_RETRY_PROMPTS` en formatter.py** referencia
  `OutputMode.ECHARTS` y otros modos — verificar que
  `get_output_prompt` sigue funcionando tras el desacople (test
  específico recomendado).

---

## 4. Confidence Map

| ID | Claim | Evidencia | Confianza | Razonamiento |
|----|-------|-----------|-----------|--------------|
| C1 | `formats/` contiene 29 archivos extraíbles + asset de 1MB | F001 | high | Inventario directo |
| C2 | El registry está diseñado para extracción (lazy import + decorator) | F002 | high | Lectura del código + sin acoplamientos rígidos |
| C3 | Solo 3 consumidores de producción importan renderers directamente | F004 | high | grep exhaustivo |
| C4 | matplotlib y seaborn están en BASE deps del core | F005 | high | Lectura directa pyproject.toml:93-94 |
| C5 | plotly/altair/bokeh/holoviews/streamlit/folium están solo en `[agents]` | F005 | high | Lectura directa |
| C6 | `OutputMode` es estable y central — debe quedar en core | F006 | high | Lectura + referencias en 30+ archivos |
| C7 | `OutputFormatter` debe quedar en core | F002, F004 | high | Usado en `bots/abstract.py:477` |
| C8 | `infographic_html` activo; resto dormante (faseable) | F007 | high | git log directo |
| C9 | Descubrimiento vía entry-points es el patrón estándar | F002 | medium | Inferido — no verifiqué si el equipo prefiere otro mecanismo |
| C10 | Renderers ligeros (json/yaml/html/table/card/slack/whatsapp) pueden quedarse en core | F003 | medium | Decisión a confirmar — depende de filosofía de extras |

Distribución: **8** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

*(ninguna)*

### Unresolved (defer to brainstorm / spec)

- [ ] **U1: ¿Mecanismo de descubrimiento de renderers?**
  *Bloquea*: C9
  *Respuestas plausibles*:
  a) Entry-points de setuptools (estándar; soporta múltiples paquetes).
  b) Side-effect en import-time (más simple; requiere que el paquete se importe explícitamente).
  c) Registro explícito desde la app del usuario (más control).

- [ ] **U2: ¿Qué renderers ligeros dejar en core?**
  *Bloquea*: C10
  *Respuestas plausibles*:
  a) Solo los sin deps (json, yaml, html, table, card, slack, whatsapp);
     mover markdown/jinja2/template_report.
  b) Dejar todos los ligeros + jinja2/template_report; mover solo los
     pesados.
  c) Mover TODOS los renderers; core solo tiene registry.

- [ ] **U3: ¿Cómo fasear la extracción?**
  *Bloquea*: C8
  *Respuestas plausibles*:
  a) Big-bang en un PR (rápido; arriesgado por `infographic_html` activo).
  b) Por renderer en PRs separados (auditado pero lento).
  c) Paquete vacío + descubrimiento + migración 1-a-1 (**recomendado**:
     permite usar el descubrimiento mientras los renderers viejos siguen
     funcionando — migración progresiva).

- [ ] **U4: ¿Nombre del paquete y namespace Python?**
  *Bloquea*: ninguno
  *Respuestas plausibles*:
  a) `ai-parrot-visualizations` / `parrot_visualizations`
     (descriptivo; alineado con la solicitud).
  b) `ai-parrot-viz` / `parrot_viz` (corto).
  c) `ai-parrot-charts` / `parrot_charts` (impreciso — incluye map e
     infographic que no son charts).
  d) `ai-parrot-renderers` / `parrot_renderers` (técnico — describe el rol).

---

## 6. Recommended Next Step

**`/sdd-brainstorm FEAT-200`** — *Rationale*: cuatro unknowns que
afectan **arquitectura del nuevo paquete** (descubrimiento de plugins,
scope de extracción, faseo, naming). Un brainstorm permite ventilar
opciones (entry-points vs side-effect vs registro explícito; big-bang
vs faseado) antes de comprometerse con un spec rígido. Conviene
explorar ejemplos de otros paquetes Python con esta arquitectura
(e.g. `pytest` plugins, `setuptools` entry-points groups).

### Alternatives

- **`/sdd-spec FEAT-200`** — si el equipo prefiere ir directo y
  resolver U1-U4 en una conversación de spec (todos son decisiones
  resolubles sin gran investigación adicional).
- **`/sdd-task FEAT-200`** — no recomendado, hay demasiado diseño
  pendiente para descomponer en tasks.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-200/state.json` |
| Source (raw) | `sdd/state/FEAT-200/source.md` |
| Research plan | `sdd/state/FEAT-200/research_plan.json` |
| Findings | `sdd/state/FEAT-200/findings/F001..F007-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-200/synthesis.json` |

**Budget consumed** (perfil `default`):
- Files read: 6 / 40
- Grep calls: 7 / 25
- Git calls: 1 / 10
- Wall time: ~220s / 300s
- Truncated: **no**

**Mode determination**: `auto` → `enrichment` (la solicitud nombra
target y áreas afectadas; el trabajo es estructurar, no investigar
una causa).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Opus 4.7 (1M context) |
