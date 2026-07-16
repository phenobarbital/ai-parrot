---
type: Wiki Overview
title: FEAT-202 — Extraer `parrot/integrations/` a `ai-parrot-integrations`
id: doc:sdd-proposals-ai-parrot-integrations-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 288K, msteams 220K, matrix 180K, whatsapp 116K, zoom 8K) más 5 piezas
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.core
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
---

---
id: FEAT-202
title: Extraer parrot/integrations/ a ai-parrot-integrations con extras por canal; BotManager queda en core
slug: ai-parrot-integrations
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-28
  summary_oneline: "Extraer parrot/integrations/ a paquete ai-parrot-integrations con extras por canal"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-202/
created: 2026-05-28
updated: 2026-05-28
---

# FEAT-202 — Extraer `parrot/integrations/` a `ai-parrot-integrations`

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — solicitud de modularización: sacar wrappers de canales pesados del core
> **Audit**: [`sdd/state/FEAT-202/`](../state/FEAT-202/)

---

## 0. Origin

> `parrot/integrations/` contiene 6 wrappers de canales de mensajería
> (slack, telegram, msteams, whatsapp, matrix, zoom) más piezas
> comunes. Cada canal arrastra dependencias específicas (Slack SDK,
> aiogram, botbuilder, pywa, mautrix, etc.) que terminan instalándose
> con ai-parrot incluso cuando el deployment solo usa CLI o un único
> canal. Objetivo: extraer a `ai-parrot-integrations` con extras
> granulares (`[slack|telegram|msteams|whatsapp|matrix|zoom]`).

**Aclaratoria explícita del usuario (2026-05-28)**:
> "mantengamos a BotManager en ai-parrot, se que se usa en
> ai-parrot-integrations pero también en servidores, servicios,
> autonomous, etc. BotManager (parrot/manager) stays in ai-parrot."

**Dependencias cruzadas con FEAT en curso**:
- **FEAT-199** (remove-parrot-forms-shim): el extra `[msteams]` declara
  `parrot-formdesigner` como dep — resuelve U2 de FEAT-199.
- **FEAT-200** (ai-parrot-visualizations): renderers ligeros
  `slack.py`/`whatsapp.py` probablemente quedan en core.
- **FEAT-201** (ai-parrot-embeddings): no afecta directamente.

---

## 1. Synthesis Summary

`parrot/integrations/` pesa ~1.6MB: 6 canales (telegram 668K, slack
288K, msteams 220K, matrix 180K, whatsapp 116K, zoom 8K) más 5 piezas
comunes (`__init__.py` con lazy PEP 562, `manager.py`/IntegrationBotManager,
`models.py`/IntegrationBotConfig, `parser.py`, `core/state.py`).
Arquitectónicamente **ya está pensado para extracción**: el `__init__.py`
usa `__getattr__` lazy para diferir `aiogram` (~1.5s).

**Hallazgos relevantes**:
- **BotManager** (parrot/manager) y **IntegrationBotManager** (integrations/manager.py)
  son **clases distintas** que conviene no confundir — el primero es el
  lifecycle de agentes/chatbots usado por ~22 sitios del core (queda
  en core por decisión del usuario); el segundo es loader específico
  de `integrations_bots.yaml` y mueve con integrations.
- **`pywa` (WhatsApp) está en BASE deps** (línea 83 de pyproject)
  — fuga directa. `aiogram` viene transitivo vía `async-notify[default]`
  también en BASE. `azure-teambots` está en extra `integrations` y
  `mautrix` en extra `matrix`.
- **oauth2** (116K) es consumido por **5 archivos de producción fuera
  de integrations** (auth/routes, auth/oauth2_routes, handlers/integrations,
  handlers/user_objects, manager/manager). Trasciende canales — decisión
  arquitectónica pendiente (U1).
- **`parrot.voice` tiene cero consumidores fuera de integrations**
  (msteams/voice + telegram). Candidato fuerte a moverse (U2).
- **`parrot/human/channels/telegram.py`** es canal-específico; el
  resto de `parrot.human` (manager, models, events, actions, escalation)
  es genérico (U3).
- **matrix está en desarrollo MUY activo** (matrix-collaborative-crew,
  TASKs 1295-1300 recientes) — faseo obligatorio (U5).
- **zoom no es realmente un bot** (sin SDK, solo aiohttp); su único
  consumer real está en `ai-parrot-tools/zoomtoolkit.py` — ¿debería ir
  ahí? (U4).
- **integrations → bots es solo TYPE_CHECKING** (limpio); integrations
  → human y voice es runtime.

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Símbolo | Líneas | Rol | Evidencia |
|---|------|---------|--------|-----|-----------|
| 1 | `parrot/integrations/` (6 canales + 5 comunes) | — | — | Conjunto a extraer (~1.6MB) | F001 |
| 2 | `parrot/integrations/__init__.py` | `__getattr__` lazy PEP 562 | 14-50 | Re-export lazy que facilita extracción | F002 |
| 3 | `parrot/integrations/manager.py` | `IntegrationBotManager` | 1-25 | Loader de `integrations_bots.yaml` (MUEVE) | F002, F005 |
| 4 | `parrot/integrations/models.py` | `IntegrationBotConfig` | 1-15 | Config raíz agregando configs por canal (MUEVE) | F002 |
| 5 | `parrot/integrations/parser.py` | `ResponseParser` | 1-15 | Parser unificado AIMessage para canales (MUEVE) | F002 |
| 6 | `parrot/integrations/core/state.py` | `InMemoryStateStore` | 12-30 | Utility TTL genérica (DECISIÓN) | F002 |
| 7 | `parrot/integrations/oauth2/` | registry, service, providers | — | OAuth2 infra (DECISIÓN U1) | F002, F004 |
| 8 | `parrot/manager/manager.py` | `BotManager` | — | **QUEDA en ai-parrot** (decisión usuario) | F005 |
| 9 | `parrot/integrations/manager.py` | `from ..human import HumanInteractionManager, TelegramHumanChannel` | 18-21 | Coupling runtime a parrot.human | F002, F006 |
| 10 | `parrot/human/channels/telegram.py` | `TelegramHumanChannel` | — | Channel-específico (MUEVE — U3) | F006 |
| 11 | `parrot/voice/` (handler, server, session, transcriber, ui) | — | — | Cero consumidores fuera de integrations (DECISIÓN U2) | F006 |
| 12 | `packages/ai-parrot/pyproject.toml` | `pywa>=3.8.0` BASE deps | 83 | FUGA — sale con whatsapp | F003 |
| 13 | `packages/ai-parrot/pyproject.toml` | `async-notify[default]` BASE | 82 | Trae transitivos de canales al core | F003 |
| 14 | `packages/ai-parrot/pyproject.toml` | extras `integrations` (azure-teambots) y `matrix` (mautrix, python-olm) | 404, 461 | Mueven al nuevo paquete | F003 |
| 15 | `parrot/core/hooks/matrix.py` | import `MatrixClientWrapper` | — | Coupling inverso core → canal (DECISIÓN U7) | F004 |

### 2.2 Constraints Discovered

- **`BotManager` (parrot/manager) QUEDA en ai-parrot** — decisión
  explícita del usuario. Lo usan ~22 sitios (handlers, autonomous,
  auth, bots, core/hooks). El nuevo paquete declara dep a `ai-parrot`
  e importa BotManager normalmente.
  *Evidencia*: F005

- **Tres FEAT en curso coordinan con este**:
  - FEAT-199 (forms): el extra `[msteams]` declara `parrot-formdesigner`.
    FEAT-199 U2 se resuelve aquí.
  - FEAT-200 (visualizations): renderers slack/whatsapp probablemente
    quedan en core (ligeros).
  - FEAT-201 (embeddings): no afecta.
  *Evidencia*: F003, F006, F007

- **matrix está en desarrollo MUY activo** (matrix-collaborative-crew,
  TASKs 1295-1300 recientes). NO mover en primera fase.
  *Evidencia*: F007

- **OAuth2 (integrations/oauth2/) trasciende canales** — 5 archivos
  de producción fuera de integrations lo consumen (auth/{routes,oauth2_routes},
  handlers/{integrations,user_objects}, manager). Decisión arquitectónica
  pendiente (U1).
  *Evidencia*: F004

- **Acoplamiento integrations → bots es TYPE_CHECKING (clean);
  integrations → human y voice es RUNTIME.** El nuevo paquete puede
  importar AbstractBot solo bajo TYPE_CHECKING; para human/voice hay
  que decidir si mueven parcialmente.
  *Evidencia*: F004, F006

- **`parrot.voice` tiene cero consumidores fuera de integrations**.
  Candidato fuerte a moverse al nuevo paquete (U2).
  *Evidencia*: F006

- **`parrot/human/channels/telegram.py` es inherentemente
  canal-específico**; el resto de `parrot.human` (manager, models,
  events, actions, escalation, node, cli_companion) es genérico/core.
  *Evidencia*: F006

- **El `__init__.py` de integrations YA es lazy** (PEP 562 `__getattr__`).
  Con PEP 420 (namespace package, como FEAT-201 decidió) los imports
  `from parrot.integrations import …` siguen funcionando sin cambios.
  *Evidencia*: F002

- **`pywa` (WhatsApp) está en BASE deps**; `aiogram` viene transitivo
  vía `async-notify[default]` en BASE.
  *Evidencia*: F003

- **zoom (8K) no es un bot** — es integración API sin SDK propio
  (solo aiohttp). Su único consumer real está en
  `ai-parrot-tools/zoomtoolkit.py`. ¿Debería ir ahí? (U4).
  *Evidencia*: F001, F003

### 2.3 Recent History

| Canal | Actividad reciente |
|-------|---------------------|
| matrix | **MUY ACTIVO** — matrix-collaborative-crew, TASKs 1295-1300 |
| telegram | Fixes recientes (validation, webhooks, OAuth2 generic) |
| msteams | TASK-532 (MS Teams Integration Rewrite — form-abstraction-layer) |
| slack | Dormante desde monorepo-migration (TASK-398) |
| whatsapp | Dormante desde monorepo-migration |
| zoom | Dormante desde monorepo-migration |

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **Paquete `packages/ai-parrot-integrations/`** (workspace member),
  con su propio `pyproject.toml` y extras granulares por canal.
- **PEP 420 namespace package** (consistente con FEAT-201): el nuevo
  paquete contribuye submódulos bajo `parrot.integrations.*` sin
  tocar imports de consumidores.

### What Moves

- **Todos los 6 canales** (slack, telegram, msteams, whatsapp, matrix,
  zoom) — con caveat de matrix en fase final.
- **Piezas comunes**: `__init__.py` lazy, `manager.py`
  (IntegrationBotManager), `models.py` (IntegrationBotConfig),
  `parser.py`, `core/state.py` (interno).
- **`parrot/human/channels/*`** (channel-específico HITL) — sujeto a U3.
- **`parrot/voice/*`** (recomendado mover todo) — sujeto a U2.
- **Extras pyproject**: `azure-teambots` (de `integrations`), `mautrix`
  + `python-olm` (de `matrix`).

### What Stays in Core

- **`BotManager`** (parrot/manager/manager.py) — decisión usuario.
- **`parrot.human` top-level** (manager, models, events, actions,
  escalation, node, cli_companion, tool) — HITL es concepto core.
- **`parrot.bots.*`** — integrations solo usa type hints.
- **`parrot.conf`, `parrot.core`, `parrot.models`** — infra core.

### What Changes in Core

- **`packages/ai-parrot/pyproject.toml`**:
  - eliminar `pywa>=3.8.0` de BASE deps (l.83).
  - evaluar reducir `async-notify[default]` (l.82).
  - eliminar extras `matrix` y partes de `integrations` ya provistas
    por el nuevo paquete.
  - añadir extra meta `messaging = ["ai-parrot-integrations[messaging]"]`.
- **`parrot/manager/manager.py` + `parrot/autonomous/orchestrator.py`**:
  import lazy de `IntegrationBotManager` sigue funcionando vía PEP 420.
- **`parrot/core/hooks/matrix.py`**: decisión U7 (refactor a hook
  pluggable o seguir importando vía PEP 420).
- **`parrot/bots/jira_specialist.py`**: import `TelegramOAuthNotifier`
  sigue funcionando vía PEP 420.
- **`parrot/handlers/agent.py`**: import telegram.combined_callback
  vía PEP 420.
- **`ai-parrot-tools/zoomtoolkit.py`**: declarar dep a
  `ai-parrot-integrations[zoom]` o (si U4=A) self-import.

### Non-Goals

- No mover `BotManager` (decisión usuario explícita).
- No reescribir wrappers de canales (extracción puramente de packaging).
- No bloquear matrix-collaborative-crew (matrix se difiere a fase final).
- No tocar `parrot.bots` ni `parrot.conf`.

### Patterns to Follow

- **PEP 420 namespace package** (consistente con FEAT-201) — preserva
  imports `parrot.integrations.*` sin cambios.
- **Extras granulares por canal** (consistente con FEAT-200 y FEAT-201).
- **Lazy registration de HumanChannels** desde el nuevo paquete
  (similar al patrón de renderers propuesto en FEAT-200).

### Integration Risks

- Consumidores externos al repo que dependan de `pywa`/`aiogram`
  transitivamente tras `pip install ai-parrot` se rompen.
  *Mitigar*: CHANGELOG + guía `pip install ai-parrot-integrations[whatsapp]`.
- FEAT-199 secuencial: msteams no se extrae limpio hasta cerrar forms.
  *Mitigar*: faseo (msteams en fase 2, después de FEAT-199).
- matrix-collaborative-crew sigue abriendo tasks.
  *Mitigar*: coordinar con `/sdd-status`; matrix en fase final.
- `parrot/core/hooks/matrix.py` es coupling inverso core → canal
  específico. *Mitigar*: U7.
- Decisión OAuth2 (U1) afecta auth — coordinar con dueño del componente.

---

## 4. Confidence Map

| ID | Claim | Evidencia | Confianza |
|----|-------|-----------|-----------|
| C1 | 6 canales + 5 archivos/dir comunes = ~1.6MB | F001 | high |
| C2 | `__init__.py` ya es lazy PEP 562 (split-friendly) | F002 | high |
| C3 | BotManager queda en core (decisión usuario) | F005 | high |
| C4 | IntegrationBotManager mueve; sus 2 callers ya son lazy | F005 | high |
| C5 | OAuth2 lo consumen 5 archivos de prod fuera de integrations | F004 | high |
| C6 | Coupling a bots es TYPE_CHECKING; a human/voice es runtime | F004, F006 | high |
| C7 | parrot.voice tiene cero consumidores fuera de integrations | F006 | high |
| C8 | TelegramHumanChannel es canal-específico (channels/ mueve) | F006 | high |
| C9 | `pywa` en BASE deps; `aiogram` transitivo en BASE vía async-notify | F003 | high |
| C10 | matrix en desarrollo activo; resto estable | F007 | high |
| C11 | zoom no es bot; único consumer real en ai-parrot-tools | F001, F003 | medium |
| C12 | FEAT-199, FEAT-200, FEAT-201 tienen deps temporales con este | F003 | high |

Distribución: **11** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **BotManager (parrot/manager): ¿se mueve o se queda?**
  — *Resuelto por el usuario*: **QUEDA en ai-parrot** porque también
  lo usan servidores, services, autonomous, etc., no solo integrations.
  El nuevo paquete declara dep a `ai-parrot` e importa BotManager
  normalmente.

### Unresolved (defer to brainstorm / spec)

- [ ] **U1: ¿Dónde queda `integrations/oauth2/`?**
  *Bloquea*: C5
  *Respuestas plausibles*:
  a) Mover a `parrot/oauth2/` o `parrot/auth/oauth2/` en core
     (recomendado: trasciende canales de mensajería).
  b) Oauth2 mueve con integrations; auth/handlers usan PEP 420
     para seguir importando.
  c) Crear paquete propio `ai-parrot-oauth2`.

- [ ] **U2: ¿Qué hacer con `parrot.voice`?**
  *Bloquea*: C7
  *Respuestas plausibles*:
  a) Mover todo `parrot.voice` al nuevo paquete (recomendado: cero
     consumidores fuera).
  b) Mover solo `voice/transcriber/` (parte pesada con whisper).
  c) Dejar `parrot.voice` en core.

- [ ] **U3: ¿Mover `parrot/human/channels/` al nuevo paquete?**
  *Bloquea*: C8
  *Respuestas plausibles*:
  a) Sí, mover `channels/` (telegram.py y futuros) — registry para
     auto-discovery.
  b) Dejar `channels/` en core pero hacer cada implementación
     opcional (try/except import).
  c) Mover `parrot.human` completo (no recomendado: HITL es core).

- [ ] **U4: ¿zoom va a `ai-parrot-integrations` o a `ai-parrot-tools`?**
  *Bloquea*: C11
  *Respuestas plausibles*:
  a) Mover `zoom/` a `ai-parrot-tools` (zoom es API integration,
     no bot de mensajería; su único consumer real es `zoomtoolkit.py`).
  b) Dejar en `ai-parrot-integrations[zoom]` y `ai-parrot-tools`
     declara dep.
  c) Mantener copia mínima en ambos (mala práctica).

- [ ] **U5: ¿Cómo fasear la extracción de canales?**
  *Bloquea*: C10
  *Respuestas plausibles*:
  a) **Recomendado**: Fase 1 slack+whatsapp+zoom (dormantes). Fase 2
     telegram+msteams (estables, msteams después de FEAT-199).
     Fase 3 matrix (cuando matrix-collaborative-crew cierre).
  b) Big-bang: todos en un PR (rápido, alto riesgo por matrix).
  c) Paquete vacío + PEP 420 + migración 1-a-1 (seguro, muchos PRs).

- [ ] **U6: ¿Estrategia de import-stability?**
  *Plausibles*:
  a) PEP 420 (consistente con FEAT-201; cero cambios en imports).
  b) `parrot_integrations.*` top-level (consistente con
     `ai-parrot-loaders/-tools/-pipelines`; explícito; requiere
     migrar imports).

- [ ] **U7: ¿Qué hacer con `parrot/core/hooks/matrix.py`?**
  *Plausibles*:
  a) Refactorizar a hook pluggable: core declara interface, matrix
     se registra desde el nuevo paquete.
  b) Dejar el import; sigue funcionando vía PEP 420 (acoplamiento
     persiste pero compila).
  c) Mover el hook completo al nuevo paquete.

---

## 6. Recommended Next Step

**`/sdd-brainstorm FEAT-202`** — *Rationale*: 7 unknowns
arquitectónicos importantes (oauth2, voice, human/channels, zoom,
faseo, namespace, hook matrix). Cada uno tiene 2-3 caminos legítimos
y varios interactúan. Brainstorm permite ventilar opciones, traer
aprendizajes de **FEAT-200** y **FEAT-201** (extracciones similares
en el mismo workspace) — especialmente sobre namespace strategy,
descubrimiento de plugins, y faseo — y producir un mapa de decisiones
coherente antes de comprometerse con un spec.

### Alternatives

- **`/sdd-spec FEAT-202`** — viable si las decisiones ya están claras:
  e.g. PEP 420 (consistencia FEAT-201), faseo A (minimizar riesgo),
  oauth2 a core (trasciende canales), voice mueve todo (cero consumers
  fuera), human/channels mueven, zoom va a tools.
- **Esperar a que FEAT-199 cierre** antes de empezar la fase 2
  (msteams).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State | `sdd/state/FEAT-202/state.json` |
| Source | `sdd/state/FEAT-202/source.md` |
| Plan | `sdd/state/FEAT-202/research_plan.json` |
| Findings | `sdd/state/FEAT-202/findings/F001..F007-*.md` |
| Synthesis | `sdd/state/FEAT-202/synthesis.json` |

**Budget consumed** (perfil `default`):
- Files read: 8 / 40
- Grep calls: 10 / 25
- Git calls: 2 / 10
- Wall time: ~280s / 300s
- Truncated: **no**

**Mode determination**: `auto` → `enrichment`.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Opus 4.7 (1M context) |
