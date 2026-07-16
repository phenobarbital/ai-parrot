---
type: Wiki Overview
title: 'Brainstorm: ai-parrot-integrations'
id: doc:sdd-proposals-ai-parrot-integrations-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: fuente y, vía sus dependencias, arrastra al core de ai-parrot SDKs
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.auth.oauth2.registry
  rel: mentions
- concept: mod:parrot.auth.oauth2.service
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.matrix
  rel: mentions
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.manager
  rel: mentions
- concept: mod:parrot.integrations.matrix.client
  rel: mentions
- concept: mod:parrot.integrations.matrix.hook
  rel: mentions
- concept: mod:parrot.integrations.msteams
  rel: mentions
- concept: mod:parrot.integrations.slack
  rel: mentions
- concept: mod:parrot.integrations.slack.assistant
  rel: mentions
- concept: mod:parrot.integrations.slack.wrapper
  rel: mentions
- concept: mod:parrot.integrations.telegram
  rel: mentions
- concept: mod:parrot.integrations.telegram.combined_callback
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
- concept: mod:parrot.loaders
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot_tools.zoom
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Brainstorm: ai-parrot-integrations

**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`packages/ai-parrot/src/parrot/integrations/` pesa ~1.6MB en código
fuente y, vía sus dependencias, arrastra al core de ai-parrot SDKs
de mensajería pesados que no se necesitan en deployments CLI o de
agentes que solo usan un canal puntual:

- `pywa` (WhatsApp) está declarado en **BASE deps** de `ai-parrot`
  (`packages/ai-parrot/pyproject.toml:83`).
- `aiogram` (Telegram) viene como **transitivo de `async-notify[default]`**
  que también está en BASE deps (`packages/ai-parrot/pyproject.toml:82`).
- `azure-teambots` está en extra `[integrations]` mezclado con
  `querysource` y `async-notify[all]`.
- `mautrix` + `python-olm` viven en extra `[matrix]` separado.

Además, hay tres acoplamientos que cruzan el límite hacia
`parrot.integrations`:

1. **`parrot/core/hooks/matrix.py`** importa `MatrixClientWrapper`
   directamente — coupling inverso del core a un canal.
2. **`parrot/manager/manager.py::BotManager`** y
   **`parrot/autonomous/orchestrator.py`** importan
   `IntegrationBotManager` (lazy, dentro de función).
3. **`parrot/auth/{routes,oauth2_routes}`,
   `parrot/handlers/{integrations,user_objects}`,
   `parrot/manager/manager.py`** consumen `integrations/oauth2/`
   (5 archivos de producción).

**Quién está afectado**:
- Operadores que instalan `ai-parrot` para un agente CLI o un servidor
  sin canales — pagan instalación de `pywa`/`aiogram`/SDKs sin usarlos.
- Quienes solo usan un canal — instalan todos los SDKs.
- El equipo, porque cualquier cambio en `parrot/integrations/` requiere
  publicar versión completa de `ai-parrot` (sin granularidad de
  release).

**Por qué ahora**:
- FEAT-199 (forms) y FEAT-200 (visualizations) ya están en proposal —
  este FEAT cierra el bloque de extracciones de canales.
- FEAT-195 (matrix-collaborative-crew) **ya mergeó a dev**
  (confirmación del usuario), liberando el bloqueo previo que
  identificó F007. La ventana de extracción está abierta.
- El `__init__.py` de integrations YA es lazy (PEP 562 `__getattr__`)
  y `parrot/__init__.py` YA usa `pkgutil.extend_path` — la
  infraestructura de namespace extension está preparada.

---

## Constraints & Requirements

- **PEP 420 (o equivalente vía `pkgutil.extend_path`) — namespace
  extension obligatoria.** Los consumidores siguen importando
  `from parrot.integrations.X import Y` sin cambios. Decisión del
  usuario consistente con FEAT-201.
- **`BotManager` (`parrot/manager`) NO se mueve.** Decisión explícita
  del usuario (lo consumen ~22 sitios en handlers/autonomous/auth/bots).
- **Big-bang en un PR.** Decisión del usuario — todos los canales
  mueven en un solo PR, no faseado por estabilidad.
- **Sin cambios funcionales en wrappers.** La extracción es puramente
  de packaging. Lógica de canales se mueve byte-idéntica.
- **Extras granulares por canal**:
  `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`.
- **`zoom/` no es bot** — mueve a `ai-parrot-tools` (decisión usuario).
- **`oauth2/` queda en core** — mueve a `parrot/auth/oauth2/` (decisión
  usuario; trasciende canales).
- **`parrot.voice` mueve completo** al nuevo paquete (decisión usuario;
  cero consumidores fuera de integrations).
- **`parrot/human/channels/` mueve al nuevo paquete con registry**
  (decisión usuario).
- **`parrot/core/hooks/matrix.py` se refactoriza a hook pluggable**
  (decisión usuario; limpia coupling inverso).
- **Sin breaking changes para consumidores que ya usan
  `pip install ai-parrot[integrations]`**. Mitigar via CHANGELOG +
  meta-extra `[messaging]` que aliasa al nuevo paquete.

---

## Options Explored

### Option A: Big-bang con namespace extension (`parrot.integrations.*`)

Estructura: nuevo paquete `packages/ai-parrot-integrations/` que
contribuye submódulos bajo el namespace existente `parrot.integrations.*`
vía `pkgutil.extend_path` (la convención que ya está en
`parrot/__init__.py:11`). Un solo PR mueve los 5 canales restantes
(slack, telegram, msteams, whatsapp, matrix) + voice + human/channels
+ refactor del hook matrix + traslado de oauth2 a `parrot/auth/oauth2/`
+ traslado de zoom a `ai-parrot-tools`.

**Implementación**:
- Layout `packages/ai-parrot-integrations/src/parrot/integrations/...`
  (sin `parrot/__init__.py` propio para que `pkgutil.extend_path`
  funcione).
- Extras en `pyproject.toml`: `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`.
- `ai-parrot` declara dep al nuevo paquete con extras lazy mediante
  un nuevo meta-extra `[messaging]` que aliasa `ai-parrot-integrations[messaging]`.
- `parrot/integrations/oauth2/` → `parrot/auth/oauth2/` (en el mismo
  PR, con imports actualizados en los 5 consumers de core).
- `parrot/core/hooks/matrix.py` → refactor a interface `MessagingHook`
  + registry; matrix se registra desde el nuevo paquete vía
  decorador/entry-point.
- `parrot/integrations/zoom/` → `packages/ai-parrot-tools/src/parrot_tools/zoom/`
  (el único consumer real `zoomtoolkit.py` ya vive ahí).
- Eliminar del core: `pywa`, ajustar `async-notify[default]` →
  `async-notify` minimal si es posible, mover `azure-teambots` y
  `mautrix`/`python-olm` del core al nuevo paquete.

✅ **Pros:**
- **Cero cambios en imports de consumidores externos** — sigue
  funcionando `from parrot.integrations.slack.wrapper import SlackWrapper`.
- **Un solo PR** = atomicidad: ningún estado intermedio donde matrix
  vive en dos sitios.
- **Limpia los 3 acoplamientos** (hooks/matrix.py, BotManager lazy,
  oauth2) en el mismo PR.
- Aprovecha `pkgutil.extend_path` que YA está en
  `parrot/__init__.py:11` (no requiere refactor del core para
  habilitar PEP 420).
- Consistente con FEAT-201 que adoptó la misma estrategia.

❌ **Cons:**
- PR grande (~1.6MB de código movido + edits en core).
- Riesgo de un único punto de fallo — si el PR introduce un bug, hay
  que revertir todo el bundle.
- Requiere coordinar varios sub-cambios (oauth2 relocation, hook
  refactor, zoom move) que de otro modo serían PRs independientes.
- El layout sin `parrot/__init__.py` en el nuevo paquete es
  contra-intuitivo y futuros mantenedores pueden añadir uno por error
  (rompiendo namespace extension).

📊 **Effort:** High (~80-120h estimado, distribuido en ~10 tasks).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram>=3.12` | Telegram SDK | mueve a extra `[telegram]` |
| `azure-teambots>=0.1.1` | MS Teams botbuilder integration | mueve a extra `[msteams]` |
| `botbuilder-core>=4.16` | MS Teams base | transitive de azure-teambots |
| `botbuilder-dialogs` | MS Teams dialogs | transitive |
| `botbuilder-integration-aiohttp` | MS Teams aiohttp adapter | transitive |
| `pywa>=3.8.0` | WhatsApp Business API | mueve a extra `[whatsapp]` |
| `slack-sdk>=3.0` | Slack SDK | mueve a extra `[slack]` (era transitive de async-notify) |
| `slack-bolt>=1.18` | Slack Bolt framework | opt, en extra `[slack]` |
| `mautrix>=0.20` | Matrix client | mueve a extra `[matrix]` |
| `python-olm>=3.2.16` | Matrix E2E encryption | mueve a extra `[matrix]` |
| `parrot-formdesigner` | Form schemas (FEAT-199) | mueve a extra `[msteams]` |
| `faster-whisper` (transitivo) | Voice transcription | mueve a extra `[voice]` |
| `openai` (transitivo) | OpenAI Whisper backend | mueve a extra `[voice]` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/integrations/__init__.py` — lazy PEP
  562 `__getattr__` ya implementado (`F002`).
- `packages/ai-parrot/src/parrot/__init__.py:11` — `__path__ = extend_path(__path__, __name__)` ya en sitio para namespace extension.
- `packages/ai-parrot/pyproject.toml` (líneas 461 `[matrix]`, 404
  `[integrations]`, 82-83 BASE deps) — punto de modificación.
- `packages/ai-parrot/src/parrot/core/hooks/base.py::BaseHook` y
  `HookManager` — pattern existente para hooks (refactor objetivo).
- `packages/ai-parrot/src/parrot/auth/oauth2_base.py` — patrón
  OAuth2 base que conviene revisar al reubicar `integrations/oauth2/`.
- `packages/ai-parrot/src/parrot/human/__init__.py` —
  `HumanInteractionManager` + interface base para `channels/`.

---

### Option B: Top-level naming (`parrot_integrations.*`) con faseo

Estructura como `ai-parrot-loaders` / `ai-parrot-tools` /
`ai-parrot-pipelines`: el paquete tiene su propio top-level
`parrot_integrations.*` y NO contribuye a `parrot.integrations.*`.
Esto requiere migrar todos los `from parrot.integrations.X import Y`
a `from parrot_integrations.X import Y`. Faseo: un canal por PR.

**Implementación**:
- Layout `packages/ai-parrot-integrations/src/parrot_integrations/...`
  (top-level explícito).
- Migración progresiva: PR1 = paquete vacío + slack; PR2 = telegram;
  etc. Cada PR migra los imports de los consumers de ese canal.
- `parrot/integrations/` se va vaciando hasta poder borrar el
  directorio.

✅ **Pros:**
- **Consistente** con `ai-parrot-loaders`, `-tools`, `-pipelines`,
  `parrot-formdesigner`.
- Naming explícito — al ver `parrot_integrations.X` queda claro que
  viene del paquete satélite.
- PRs más pequeños y revisables; rollback fácil por canal.
- Permite continuar matrix-collaborative-crew y otros features en
  flight en paralelo (mueve un canal a la vez).

❌ **Cons:**
- **Migración masiva de imports** en consumers: ~10 archivos en core
  + tests + `ai-parrot-tools/zoomtoolkit.py` + repos externos no
  visibles desde este workspace.
- Contradice la decisión del usuario (PEP 420).
- Más PRs = más overhead de coordinación.
- Estado intermedio donde algunos canales viven en core y otros en el
  paquete satélite — posible confusión.

📊 **Effort:** High (más PRs, más imports a migrar, ~120-160h
distribuidos en 6-8 PRs).

📦 **Libraries / Tools:** (idénticas a Option A — el cambio es de
naming, no de deps).

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-loaders/pyproject.toml` — patrón de
  `[tool.setuptools.packages.find] include = ["parrot_loaders*"]` y
  layout `src/parrot_loaders/`.
- `packages/parrot-formdesigner/src/parrot_formdesigner/__init__.py`
  — patrón de top-level minimalista con submódulos explícitos.

---

### Option C: Split mínimo — solo SDKs pesados

Conservar `parrot/integrations/__init__.py`, `models.py`, `parser.py`,
`core/state.py`, `oauth2/`, manager.py, slack, telegram y zoom EN
EL CORE. Mover SOLO los canales con SDKs más pesados o con deps
problemáticas: `msteams/` (forms + botbuilder), `matrix/` (mautrix +
python-olm + E2E encryption), `whatsapp/` (pywa). Voice mueve solo
si msteams mueve.

**Implementación**:
- Nuevo paquete con 3 canales pesados + voice; resto del directorio
  `integrations/` se queda en core.
- Extras pyproject mínimas: `[msteams|matrix|whatsapp]`.
- No se toca el namespace; oauth2 sigue donde está; hooks/matrix.py
  se queda.

✅ **Pros:**
- **Cambio quirúrgico** — alcance pequeño, menos riesgo.
- Preserva slack/telegram en core (los más usados y más estables).
- No requiere refactor de hooks/matrix.py ni relocation de oauth2.
- Menos PRs, menos archivos tocados.

❌ **Cons:**
- **Solo mitiga el problema** — `aiogram` (transitive vía
  async-notify[default]) sigue en BASE deps; matrix-related coupling
  en core sigue.
- Resultado inconsistente: `parrot.integrations.slack.*` vive en
  core mientras `parrot.integrations.msteams.*` vive en paquete
  satélite. Confunde a futuros mantenedores.
- Contradice la decisión del usuario de big-bang y de modularización
  completa expresada en el thread original.
- No cubre la decisión de mover `parrot.voice` (que tiene cero
  consumers fuera de integrations).

📊 **Effort:** Medium (~40-60h).

📦 **Libraries / Tools:** subset de Option A (solo msteams + matrix +
whatsapp + voice).

🔗 **Existing Code to Reuse:** Idem Option A para los canales que sí
mueven.

---

## Recommendation

**Option A** es la recomendada. Razones:

1. **Alinea con todas las decisiones del usuario**: PEP 420 (Round 1),
   big-bang (Round 1), oauth2 a core (Round 1), voice mueve todo
   (Round 1), human/channels mueve con registry (Round 2), zoom a
   tools (Round 2), refactor hook matrix (Round 2).

2. **Cero ruptura para consumidores externos**: la combinación
   `parrot/__init__.py` con `pkgutil.extend_path` + namespace
   extension preserva todos los imports `from parrot.integrations.X
   import Y` byte-idénticos. Lo único que cambia es de dónde se
   instala el código.

3. **Atomicidad**: el big-bang elimina estados intermedios. No hay
   ventanas donde matrix existe en dos sitios o donde los hooks
   importan algo que ya no está.

4. **Aprovecha infraestructura ya en sitio**: el lazy `__getattr__`
   en `integrations/__init__.py` y el `extend_path` en
   `parrot/__init__.py:11` ya fueron diseñados para este escenario.

5. **Resuelve los 3 acoplamientos** (hooks/matrix.py, BotManager,
   oauth2) en el mismo PR — coordinación local en lugar de PRs
   secuenciales acoplados.

**Tradeoff explícito**: aceptamos un PR grande (alto esfuerzo de
review, riesgo de un único punto de fallo) a cambio de atomicidad y
de minimizar la ventana de estado inconsistente. El plan de mitigación
es descomponer el PR en commits muy granulares (uno por canal + uno
por refactor estructural) para facilitar review incremental.

---

## Feature Description

### User-Facing Behavior

Operadores e integradores ven cuatro cambios:

- **Instalación granular**:
  ```bash
  pip install ai-parrot                              # core agentes/CLI, ~80MB menos
  pip install ai-parrot-integrations[slack]          # solo Slack
  pip install ai-parrot-integrations[telegram,msteams] # selectivo
  pip install ai-parrot-integrations[messaging]      # combo: slack+telegram+msteams+whatsapp
  pip install ai-parrot-integrations[all]            # todos los canales
  ```
- **Imports sin cambios**: cualquier código existente que haga
  `from parrot.integrations.telegram.wrapper import TelegramWrapper`
  sigue funcionando si `ai-parrot-integrations[telegram]` está
  instalado.
- **Imports actualizados para zoom**: pasan de
  `from parrot.integrations.zoom.client import ZoomUsInterface` a
  `from parrot_tools.zoom import ZoomUsInterface` (o equivalente
  según el layout final de `ai-parrot-tools`).
- **Imports actualizados para oauth2**: pasan de
  `from parrot.integrations.oauth2.X import Y` a
  `from parrot.auth.oauth2.X import Y`. Afecta 5 archivos de core.
- **CHANGELOG.md** documenta los breaks: `pywa`/`aiogram` ya no se
  instalan por defecto; consumidores deben pedir el extra que les
  corresponda.

### Internal Behavior

Flujo de alto nivel del PR de big-bang:

1. **Crear el paquete `packages/ai-parrot-integrations/`** con
   `pyproject.toml`, `src/parrot/integrations/`, `tests/`, `README.md`.
   Sin `parrot/__init__.py` en `src/` (para que la extensión via
   `extend_path` funcione).
2. **Mover archivos por canal** (cinco subdirectorios + comunes):
   `slack/`, `telegram/`, `msteams/`, `whatsapp/`, `matrix/` →
   `packages/ai-parrot-integrations/src/parrot/integrations/*`. Más
   `__init__.py`, `manager.py`, `models.py`, `parser.py`,
   `core/state.py`.
3. **Mover `parrot/voice/`** al nuevo paquete bajo
   `parrot/voice/` (sub-dir bajo el namespace `parrot.*`). Ubicación
   sugerida: `packages/ai-parrot-integrations/src/parrot/voice/`.
4. **Mover `parrot/human/channels/`** al nuevo paquete bajo
   `parrot/human/channels/`; añadir registry en `parrot/human/`
   core que descubra canales por entry-point o por import explícito.
5. **Mover `parrot/integrations/zoom/`** a
   `packages/ai-parrot-tools/src/parrot_tools/zoom/`; actualizar
   `zoomtoolkit.py` para importar localmente.
6. **Reubicar `integrations/oauth2/`** a `parrot/auth/oauth2/` en
   core; actualizar imports en los 5 consumers
   (`auth/{routes,oauth2_routes}`, `handlers/{integrations,user_objects}`,
   `manager/manager.py`).
7. **Refactor `parrot/core/hooks/matrix.py`** a interface pluggable:
   - Definir `MessagingHook(Protocol)` o `BaseMessagingHook` en
     `parrot/core/hooks/base.py`.
   - Hook registry (decorador `@register_hook` o entry-point group
     `parrot.core.hooks`).
   - El `MatrixHook` concreto se redefine en
     `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py`
     y se auto-registra en import.
8. **Actualizar `packages/ai-parrot/pyproject.toml`**:
   - Eliminar `pywa>=3.8.0` de BASE deps (línea 83).
   - Evaluar reemplazar `async-notify[default]` por algo más
     minimalista (TBD — ver Open Questions).
   - Eliminar `azure-teambots` de extra `[integrations]`.
   - Eliminar extra `[matrix]` completo (mautrix + python-olm).
   - Eliminar package-data entries de `parrot.integrations.telegram`
     y `parrot.voice`.
   - Añadir meta-extra `messaging = ["ai-parrot-integrations[messaging]"]`.
9. **Actualizar `pyproject.toml` raíz**: añadir
   `ai-parrot-integrations` a `dependencies` y a
   `[tool.uv.sources]`.
10. **Tests**: mover los tests bajo
    `packages/ai-parrot/tests/integrations/`,
    `tests/test_telegram_integration.py`,
    `tests/test_matrix_*.py`, etc., al nuevo paquete.
11. **CHANGELOG**: documentar el break y la migración.

### Edge Cases & Error Handling

- **Consumer importa `parrot.integrations.slack` sin instalar el
  extra `[slack]`** → `ModuleNotFoundError` claro. Mitigar con un
  re-export en `parrot/integrations/__init__.py` (que vive en core)
  que detecte la ausencia y dé un mensaje de error guía:
  `"Install ai-parrot-integrations[slack] to use Slack integration"`.
- **Hook matrix registrado dos veces** (si por error queda el
  hook viejo en core + el nuevo del paquete satélite): la
  registry debe loggear warning y mantener la última registrada.
  Mitigar borrando estrictamente el archivo viejo en el mismo PR.
- **Voice transcriber sin backend disponible** (whisper, faster-whisper):
  el código actual ya usa `lazy_import("pydub", extra="audio")` —
  preservar ese patrón pero apuntar al extra del nuevo paquete.
- **OAuth2 callbacks externos** (Jira, O365) — verificar que las URLs
  registradas no incluyan rutas que dependan del namespace anterior.
- **CI/CD**: los pipelines que asumían `ai-parrot` con todos los
  canales deben actualizar `pip install` a usar el extra correcto.
  Mitigar con docs en `CHANGELOG.md` + grep en repos del workspace.
- **Tests existentes en `packages/ai-parrot/tests/`** (test_matrix_*,
  test_slack_*, test_telegram_*, test_integration_wrappers.py): mover
  al paquete satélite con sus fixtures; verificar que no rompan
  `pytest` del core.

---

## Capabilities

### New Capabilities

- `ai-parrot-integrations-package`: nuevo workspace member con extras
  granulares por canal.
- `human-channel-registry`: mecanismo en `parrot/human/` para
  descubrir/registrar `HumanChannel` implementations desde paquetes
  satélite (entry-point o decorador).
- `pluggable-core-hooks`: refactor de `parrot/core/hooks/` para
  permitir registro de hooks externos sin que core los conozca a priori.
- `oauth2-relocation`: `integrations/oauth2/` mueve a
  `parrot/auth/oauth2/` (relocation explícita; el módulo ya existe
  pero cambia de ubicación).

### Modified Capabilities

- `parrot.integrations` (extracción completa al nuevo paquete via
  namespace extension; el directorio actual se vacía o queda con un
  `__init__.py` mínimo que da mensaje de error si el extra correcto
  no está instalado).
- `parrot.voice` (mueve completo al nuevo paquete; cero consumers en
  core).
- `parrot.human.channels` (mueve a nuevo paquete; core mantiene
  interface + registry).
- `parrot/core/hooks/matrix.py` (eliminado del core; reemplazado por
  interface en `base.py` + implementación en el nuevo paquete).
- `ai-parrot-tools` (gana `zoom/` proveniente de
  `parrot/integrations/zoom/`).
- `ai-parrot` pyproject (deps BASE limpiadas; extras reorganizadas).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | modifies | quita `pywa`, ajusta `async-notify`, elimina extra `[matrix]`, mueve azure-teambots; añade meta-extra `[messaging]` |
| `packages/ai-parrot/src/parrot/integrations/` | moves | 5 canales + comunes salen al nuevo paquete; el directorio queda con stub `__init__.py` que tira error guía si no está el extra |
| `packages/ai-parrot/src/parrot/voice/` | moves | el directorio sale completo al nuevo paquete |
| `packages/ai-parrot/src/parrot/human/channels/` | moves | sale al nuevo paquete; core mantiene interface en `parrot/human/channels/__init__.py` (registry) |
| `packages/ai-parrot/src/parrot/auth/` | extends | gana subpaquete `oauth2/` (relocation desde integrations) |
| `packages/ai-parrot/src/parrot/core/hooks/matrix.py` | removes | reemplazado por interface en `base.py` + impl en nuevo paquete |
| `packages/ai-parrot/src/parrot/manager/manager.py` | modifies | actualiza import de oauth2 a `parrot.auth.oauth2`; sigue importando `IntegrationBotManager` (PEP 420 lo resuelve) |
| `packages/ai-parrot/src/parrot/autonomous/orchestrator.py` | modifies | misma actualización de oauth2 (lazy import sigue) |
| `packages/ai-parrot/src/parrot/auth/{routes,oauth2_routes}.py` | modifies | imports de oauth2 actualizados |
| `packages/ai-parrot/src/parrot/handlers/{integrations,user_objects,agent}.py` | modifies | imports de oauth2 y de canales actualizados |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | depends on | TelegramOAuthNotifier sigue funcionando via namespace extension |
| `packages/ai-parrot-tools/src/parrot_tools/zoomtoolkit.py` | modifies | import local a `parrot_tools.zoom` en lugar de `parrot.integrations.zoom` |
| `packages/ai-parrot-tools/pyproject.toml` | extends | añade `zoom/` como subpaquete |
| `packages/ai-parrot/tests/` | moves | tests de canales/integrations/matrix mueven al nuevo paquete |
| `pyproject.toml` (raíz workspace) | extends | añade `ai-parrot-integrations` a deps y `[tool.uv.sources]` |
| CHANGELOG.md | extends | documenta breaking changes y guía de migración |

---

## Code Context

### User-Provided Code

*Sin snippets pegados; las decisiones del usuario fueron en
respuestas estructuradas.*

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/__init__.py:11
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
# Comment in file: "Allow other packages (e.g. parrot-formdesigner)
# to extend the parrot namespace"

# From packages/ai-parrot/src/parrot/integrations/__init__.py:14-50
_LAZY_EXPORTS = {
    "IntegrationBotConfig": ".models",
    "TelegramAgentConfig": ".models",
    "MSTeamsAgentConfig": ".models",
    "WhatsAppAgentConfig": ".models",
    "SlackAgentConfig": ".models",
    "IntegrationBotManager": ".manager",
}
def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value

# From packages/ai-parrot/src/parrot/integrations/manager.py:1-25
"""Integration Bot Manager."""
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from ..conf import AGENTS_DIR, REDIS_URL
from ..human import (
    HumanInteractionManager,
    TelegramHumanChannel,
)
if TYPE_CHECKING:
    from ..bots.abstract import AbstractBot

# From packages/ai-parrot/src/parrot/manager/__init__.py
from .manager import BotManager
__all__ = ["BotManager"]
# DECISION: BotManager stays in ai-parrot per user.

# From packages/ai-parrot/src/parrot/core/hooks/matrix.py:1-25
"""Matrix protocol hook for AutonomousOrchestrator."""
from .base import BaseHook
from .models import HookType, MatrixHookConfig

class MatrixHook(BaseHook):
    """Matrix message listener via mautrix-python."""

# From packages/ai-parrot/src/parrot/integrations/__init__.py module docstring

…(truncated)…
