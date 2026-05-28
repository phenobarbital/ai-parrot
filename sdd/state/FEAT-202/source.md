---
kind: inline
jira_key: null
fetched_at: 2026-05-28T13:40:35+02:00
summary_oneline: "Extraer parrot/integrations/ a paquete ai-parrot-integrations con extras por canal"
---

# Source — ai-parrot-integrations

Contexto: `parrot/integrations/` contiene los wrappers de canales de
mensajería (slack, telegram, msteams, whatsapp, matrix, zoom) más
piezas comunes (`core/`, `oauth2/`, `manager.py`, `models.py`,
`parser.py`). Cada canal arrastra dependencias específicas (Slack SDK,
Telegram Bot API, Microsoft Bot Framework, WhatsApp, Matrix Nio,
Zoom SDK, OAuth2) que terminan instalándose con ai-parrot incluso
cuando el deployment solo usa CLI o un único canal.

Objetivo: extraer `parrot/integrations/` a un paquete nuevo
`ai-parrot-integrations` dentro del workspace, estructurar las
dependencias como extras (`ai-parrot-integrations[slack|telegram|msteams|whatsapp|matrix|zoom]`),
y dejar al core de ai-parrot enfocado en agentes/bots/tools.

Considerar:
- ¿Qué tan acoplado está cada wrapper con el resto de ai-parrot
  (handlers, bots, scheduler, memory, registry, OutputMode)?
- ¿Qué hay en `integrations/core/`, `oauth2/`, `manager.py`,
  `parser.py`, `models.py` que sea común a TODOS los canales? ¿Debe
  quedarse en ai-parrot o moverse al nuevo paquete?
- ¿Quién consume `parrot.integrations.*` desde el resto del codebase?
  (bots, handlers, services, tools).
- msteams trae acoplamiento adicional: usa `parrot.forms` (FEAT-199)
  y `parrot.voice` (subsistema de voice). ¿Voice también se mueve?
  ¿Forms entra como dep del extra `[msteams]`?
- ¿Cómo se hace el descubrimiento/registro de canales en runtime?
  ¿Hay un registry similar al de outputs (FEAT-200)?
- ¿Qué assets (templates, traducciones, static) deben moverse?
- Mapa de extras: granular por canal (`[slack]`, `[telegram]`, ...) +
  combos (`[messaging]`, `[all]`).
- Faseo: ¿extraer todos los canales de golpe o uno por uno?

Dependencias cruzadas con otros FEAT en curso:
- **FEAT-199** (remove-parrot-forms-shim): el extra `[msteams]` debe
  declarar `parrot-formdesigner` como dep. FEAT-199 resuelve U2 en
  base a esta extracción.
- **FEAT-201** (ai-parrot-embeddings, en research_complete, no
  commiteado): si embeddings se extrae primero, integrations debe
  declarar dep al nuevo paquete si usa stores/embeddings/rerankers.
- **FEAT-200** (ai-parrot-visualizations): integraciones de slack
  y whatsapp tienen renderers propios (`outputs/formats/slack.py`,
  `whatsapp.py`); FEAT-200 dejará esos renderers ligeros en core
  (probable) o los moverá al paquete de viz.

Resultado esperado: propuesta que liste el contenido a extraer por
canal, identifique qué piezas comunes quedan en ai-parrot vs se mueven,
mapee dependencias por extra, documente los consumidores que hay que
adaptar, los riesgos de extracción (especialmente acoplamiento con
voice y forms), y recomiende un faseo.
