---
type: Wiki Overview
title: 'Feature Specification: Telegram Operator Commands'
id: doc:sdd-specs-feat-210-telegram-operator-commands-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Un *agent harness* autónomo de servicio (inspirado en el proyecto Go
relates_to:
- concept: mod:parrot.autonomous.heartbeat
  rel: mentions
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Telegram Operator Commands

**Feature ID**: FEAT-210
**Date**: 2026-05-31
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Un *agent harness* autónomo de servicio (inspirado en el proyecto Go
**aphelion**) necesita una **superficie de operador** sobre Telegram para
observar y controlar al agente always-on sin entrar al servidor. Aphelion
expone `/health`, `/status`, `/thread`, `/context`, `/memory`, `/mission`,
`/model`. ai-parrot **no** tiene estos comandos de operador.

Tras auditar el codebase, la base para añadirlos es sólida y madura:

- `TelegramAgentWrapper`
  (`packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`,
  3700+ líneas) ya tiene un patrón de comandos completo: handlers
  `async def handle_X(self, message)` registrados con `Command("x")` en
  `_register_handlers()` (wrapper.py:162), gate `_is_authorized(chat_id)`,
  envío seguro `_send_safe_message()`, y estado consultable en
  `self.conversations` (memoria por chat), `self.agent`, `self.config`,
  `self.app`.
- Comandos existentes: `/start /help /whoami /commands /clear /skill
  /function /question /call /login /logout` + `@telegram_command` (decorador)
  + `config.commands` (YAML).

La **brecha** son los 7 comandos de operador y un gate de autorización más
estricto (no todo usuario autorizado debería ver el control del harness).

Este spec **se acopla deliberadamente** a las features hermanas del harness:
`/status` y `/thread` consumen los sub-agentes efímeros (FEAT-208); `/health`,
`/status`, `/mission` consumen el heartbeat (FEAT-209). Donde la dependencia no
esté wired en runtime, el comando **degrada con elegancia** ("no configurado").

### Goals

- **G1**: Añadir 7 comandos de operador a `TelegramAgentWrapper`:
  `/health`, `/status`, `/context`, `/memory`, `/mission`, `/model`, `/thread`.
- **G2**: **Gate de operador** — restringir estos comandos a una allowlist
  `operator_chat_ids` (subconjunto configurable de `allowed_chat_ids`). Usuarios
  no-operadores no los ven ni los pueden ejecutar.
- **G3**: `/model` y `/mission` son **solo lectura** (muestran el modelo del
  agente y la misión del heartbeat; sin mutación en runtime).
- **G4**: `/health` y `/status` proyectan estado del **heartbeat** (FEAT-209) y
  de los **sub-agentes activos** (FEAT-208); `/context` y `/memory` proyectan
  `ConversationMemory` por chat (solo lectura).
- **G5**: `/thread <task>` bifurca trabajo paralelo lanzando un **sub-agente
  efímero** (FEAT-208) y devuelve su resultado.
- **G6**: **Degradación elegante**: si heartbeat/orchestrator/spawn no están
  configurados, el comando responde "no disponible/no configurado" sin romper.
- **G7**: Tests verdes (mock aiogram) por comando + el gate de operador.

### Non-Goals (explicitly out of scope)

- **Mutación de modelo/misión en runtime** (`/model <id>`, `/mission <texto>`):
  diferido — en este spec son solo lectura (decisión del usuario).
- **Implementar el heartbeat o los sub-agentes**: son FEAT-209 y FEAT-208; este
  spec solo los **consume** (con degradación si faltan).
- **UI web / dashboard**: la superficie de operador aquí es solo Telegram.
- **Comandos de operador en otras integraciones** (MS Teams, Slack): solo
  Telegram en este spec.
- **Persistencia del estado de operador**: lo que se proyecta es estado vivo
  in-memory; la durabilidad la dará el ledger (feature #4).

---

## 2. Architectural Design

### Overview

Se añade un módulo `operator_commands.py` junto al wrapper que agrupa los 7
handlers como un mixin (`OperatorCommandsMixin`) o un set de métodos registrados
por un helper `_register_operator_commands(self)` invocado desde
`_register_handlers()`. Cada handler:

1. Verifica `_is_operator(chat_id)` (nuevo gate, más estricto que
   `_is_authorized`).
2. Resuelve la fuente de datos (heartbeat manager, orchestrator, spawn tool,
   `self.conversations`, `self.agent`) desde `self.app` / `self.agent`.
3. Si la fuente no está disponible → responde degradado.
4. Proyecta una respuesta de solo-lectura (o, para `/thread`, lanza el
   sub-agente) vía `_send_safe_message`.

El gate de operador se basa en una nueva opción de config
`operator_chat_ids: list[int] | None` en el modelo de config de Telegram. Si es
`None`, **ningún** chat es operador (fail-closed) salvo que se decida heredar de
`allowed_chat_ids` (ver Open Questions).

### Component Diagram

```
TelegramAgentWrapper._register_handlers()
        │
        ├─ _register_operator_commands()   (NEW)
        │     ├─ Command("health")   → handle_health
        │     ├─ Command("status")   → handle_status
        │     ├─ Command("context")  → handle_context
        │     ├─ Command("memory")   → handle_memory
        │     ├─ Command("mission")  → handle_mission   (read-only)
        │     ├─ Command("model")    → handle_model     (read-only)
        │     └─ Command("thread")   → handle_thread    (spawns sub-agent)
        │
   each handler ─→ _is_operator(chat_id)   (NEW gate)
        │
        ├─ /health,/status,/mission ─→ HeartbeatManager state (FEAT-209)  ─┐
        ├─ /status,/thread         ─→ ephemeral sub-agents (FEAT-208)     ─┤ degrade
        ├─ /context,/memory        ─→ self.conversations[chat_id]          │ if absent
        └─ /model                  ─→ self.agent (model/use_llm)          ─┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TelegramAgentWrapper._register_handlers` | extends | Llama `_register_operator_commands()` (wrapper.py:162). |
| `TelegramAgentWrapper._is_authorized` | mirrors | Nuevo `_is_operator` con allowlist más estricta. |
| `TelegramAgentWrapper._send_safe_message` | uses | Render de las proyecciones. |
| `self.conversations` / `ConversationMemory` | reads | `/context`, `/memory` (wrapper.py:96,906). |
| `self.agent` (model/use_llm) | reads | `/model` (solo lectura). |
| `HeartbeatManager.get_all_states` (FEAT-209) | consumes | `/health`, `/status`, `/mission`. Degrada si ausente. |
| Ephemeral sub-agents (FEAT-208) | consumes | `/status` (listar), `/thread` (spawnear). Degrada si ausente. |
| Telegram config model (`models.py`) | modifies | Añadir `operator_chat_ids`. |
| `_build_command_entries` / `setMyCommands` | extends | Exponer comandos de operador solo en el menú de operadores (si la API lo permite) o documentar. |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py  (MODIFIED)
class TelegramAgentConfig(...):   # existing
    ...
    operator_chat_ids: Optional[list[int]] = None   # NEW — operator allowlist (fail-closed if None)
    enable_operator_commands: bool = True           # NEW — feature toggle
```

```python
# Projection helpers (internal, not persisted)
def _format_heartbeat_health(states: list["HeartbeatState"]) -> str: ...
def _format_status(heartbeat_states, ephemeral_statuses) -> str: ...
def _format_memory(conv: "ConversationMemory", limit: int = 10) -> str: ...
```

### New Public Interfaces

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/operator_commands.py
class OperatorCommandsMixin:
    """Operator-only Telegram commands for the autonomous harness."""

    def _register_operator_commands(self) -> None: ...
    def _is_operator(self, chat_id: int) -> bool: ...

    async def handle_health(self, message: Message) -> None: ...   # heartbeat liveness
    async def handle_status(self, message: Message) -> None: ...   # tasks + sub-agents + jobs
    async def handle_context(self, message: Message) -> None: ...  # conversation shaping (read)
    async def handle_memory(self, message: Message) -> None: ...   # recent turns (read)
    async def handle_mission(self, message: Message) -> None: ...  # heartbeat mission (read)
    async def handle_model(self, message: Message) -> None: ...    # agent model (read)
    async def handle_thread(self, message: Message) -> None: ...   # fork → ephemeral sub-agent
```

---

## 3. Module Breakdown

### Module 1: Operator config + gate
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py`
  (+ `wrapper.py` para `_is_operator`)
- **Responsibility**: Añadir `operator_chat_ids` / `enable_operator_commands`;
  implementar `_is_operator(chat_id)` (fail-closed si `operator_chat_ids is None`).
- **Depends on**: nada nuevo.

### Module 2: Read-only operator commands
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/operator_commands.py`
- **Responsibility**: `handle_context`, `handle_memory`, `handle_model`,
  `handle_mission` (lectura) + helpers de formato. Degradación elegante.
- **Depends on**: Module 1.

### Module 3: Harness-state commands (heartbeat + sub-agents)
- **Path**: `operator_commands.py` (continuación)
- **Responsibility**: `handle_health`, `handle_status` proyectando
  `HeartbeatManager` (FEAT-209) y sub-agentes efímeros (FEAT-208), con
  degradación si no están wired.
- **Depends on**: Module 1; consume FEAT-208/FEAT-209.

### Module 4: /thread (fork → ephemeral sub-agent)
- **Path**: `operator_commands.py` (continuación)
- **Responsibility**: `handle_thread <task>` lanza un sub-agente efímero
  (SpawnSubAgentTool / BotManager, FEAT-208) y devuelve el resultado.
- **Depends on**: Module 1; consume FEAT-208.

### Module 5: Wiring + registration
- **Path**: `wrapper.py` (`_register_handlers`, mixin) + `_build_command_entries`
- **Responsibility**: Mezclar `OperatorCommandsMixin` en `TelegramAgentWrapper`,
  invocar `_register_operator_commands()` cuando `enable_operator_commands`, y
  reflejar los comandos en `/help`/menú solo para operadores.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_is_operator_failclosed` | M1 | `operator_chat_ids=None` → `_is_operator` False para todos. |
| `test_is_operator_allowlist` | M1 | Solo los chat_ids en la lista son operadores. |
| `test_non_operator_blocked` | M1/M5 | Un no-operador recibe rechazo en `/health` (no se ejecuta la proyección). |
| `test_handle_memory_readonly` | M2 | `/memory` proyecta turnos recientes desde `self.conversations`; no muta. |
| `test_handle_model_readonly` | M2 | `/model` muestra modelo/use_llm del agente; no cambia nada. |
| `test_handle_health_degrades` | M3 | Sin HeartbeatManager → respuesta "heartbeat no configurado". |
| `test_handle_status_with_heartbeat` | M3 | Con HeartbeatManager fake → proyecta ticks/acciones y sub-agentes. |
| `test_handle_thread_spawns` | M4 | `/thread <task>` invoca el spawn (fake) y responde con el resultado. |
| `test_handle_thread_degrades` | M4 | Sin spawn/BotManager → "sub-agentes no disponibles". |

### Integration Tests
| Test | Description |
|---|---|
| `test_operator_commands_registered` | Con `enable_operator_commands=True`, los 7 `Command(...)` quedan registrados en el router. |
| `test_existing_commands_unaffected` | Los comandos previos (`/help`, `/clear`, …) siguen verdes (cero regresión). |

### Test Data / Fixtures
```python
@pytest.fixture
def op_wrapper():
    w = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    w.logger = MagicMock()
    w.conversations = {}
    w.agent = MagicMock(name="agent", model="gemini-2.5", use_llm="google")
    w.config = MagicMock(operator_chat_ids=[111], enable_operator_commands=True)
    w.app = {}   # no heartbeat/bot_manager → degrade paths
    return w

@pytest.fixture
def fake_heartbeat_manager():
    # get_all_states() -> [HeartbeatState(agent_name=..., tick_count=3, ...)]
    ...
```

---

## 5. Acceptance Criteria

> Esta feature está completa cuando TODO lo siguiente es cierto:

- [ ] Los 7 comandos (`/health /status /context /memory /mission /model /thread`)
  están registrados cuando `enable_operator_commands=True`.
- [ ] **Gate de operador**: `_is_operator` es fail-closed (`operator_chat_ids=None`
  → nadie); solo los chat_ids de la allowlist ejecutan estos comandos.
- [ ] `/model` y `/mission` son **solo lectura** (no mutan modelo ni misión).
- [ ] `/health`/`/status` proyectan estado del heartbeat (FEAT-209) y sub-agentes
  activos (FEAT-208); `/context`/`/memory` proyectan `ConversationMemory`.
- [ ] `/thread <task>` lanza un sub-agente efímero (FEAT-208) y devuelve resultado.
- [ ] **Degradación elegante**: sin heartbeat/orchestrator/spawn, cada comando
  responde "no configurado/no disponible" sin lanzar excepción.
- [ ] Cero regresiones: los comandos existentes siguen funcionando.
- [ ] Tests: `pytest packages/ai-parrot-integrations/tests/ -k operator -v` verde.
- [ ] Sin breaking changes en la config existente (campos nuevos son opcionales).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from aiogram.filters import Command, CommandStart   # verified: wrapper.py:32
from aiogram.types import Message, BotCommand        # verified: wrapper.py:26 (BotCommand)
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper  # verified: tests import it
# Heartbeat (FEAT-209 — may not be installed/wired at runtime → guard imports):
# from parrot.autonomous.heartbeat import HeartbeatManager, HeartbeatState  (NEW in FEAT-209)
# Ephemeral sub-agents (FEAT-208):
# BotManager.get_ephemeral_status / create_ephemeral_user_bot / discard_ephemeral_user_bot
```

### Existing Class Signatures
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    self.agent; self.bot; self.config; self.app          # __init__ lines 87-94
    self.conversations: Dict[int, "ConversationMemory"]  # line 96
    def _register_handlers(self) -> None:                # line 162
    def _is_authorized(self, chat_id) -> bool:           # line ~900 (returns chat_id in allowed_chat_ids; None→all)
    def _get_conversation(self, chat_id):                # line ~906 (creates InMemoryConversation if absent)
    async def _send_safe_message(self, message, text):   # used at line 1465
    async def handle_help(self, message) -> None:        # line 1426 (pattern to mirror)
    async def handle_whoami(self, message) -> None:      # line 1505
    async def handle_clear(self, message) -> None:       # line 1413 (deletes self.conversations[chat_id])
    def _register_custom_command(self, cmd_name, method_name): # line 285 (registration pattern)
    # Registration pattern: self.router.message.register(self.handle_X, Command("x"))  # lines 165-194

# Command registration helper pattern (verified wrapper.py:285-292):
#   async def custom_handler(message): ...
#   self.router.message.register(custom_handler, Command(cmd_name))
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_register_operator_commands` | `self.router.message.register(..., Command("x"))` | aiogram registration | `wrapper.py:165-194,291` |
| `handle_context/handle_memory` | `self.conversations[chat_id]` | dict read | `wrapper.py:96,906` |
| `handle_model` | `self.agent` (model/use_llm attrs) | attribute read | `wrapper.py:87` |
| `handle_health/status/mission` | `HeartbeatManager.get_all_states()` | method call (FEAT-209) | `FEAT-209 §6` |
| `handle_status/thread` | ephemeral sub-agent APIs | method call (FEAT-208) | `FEAT-208 §6` |
| operator gate | `self.config.operator_chat_ids` | config read | NEW (models.py) |

### Does NOT Exist (Anti-Hallucination)
- ~~`/health`, `/status`, `/context`, `/memory`, `/mission`, `/model`, `/thread`~~ — **NO existen** hoy; los crea esta feature.
- ~~`TelegramAgentWrapper._is_operator`~~ / ~~`operator_chat_ids`~~ — no existen; los añade M1.
- ~~`HeartbeatManager`~~ — lo crea FEAT-209 (aún no mergeado); importarlo de forma **guardada** (try/except → degradar).
- ~~`TelegramAgentConfig.model` mutable en runtime~~ — `/model` es solo lectura en este spec; no hay setter.
- ~~`self.memory`~~ — el estado de conversación es `self.conversations: Dict[int, ConversationMemory]` (wrapper.py:96), no un atributo `memory`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Espejar `handle_help`/`handle_whoami` (wrapper.py:1426,1505): firma
  `async def handle_X(self, message)`, gate al inicio, `_send_safe_message`.
- Registro en `_register_handlers` via
  `self.router.message.register(self.handle_X, Command("x"))` (wrapper.py:165).
- Imports de FEAT-208/FEAT-209 **guardados** (try/except ImportError o
  `self.app.get(...)`), para que el wrapper no falle si no están wired → degradar.
- async/await; Pydantic para los campos de config nuevos; `self.logger`.
- Fail-closed en `_is_operator`.

### Known Risks / Gotchas
- **Acoplamiento a features no mergeadas (FEAT-208/FEAT-209)**: este spec las
  consume. Mitigación: degradación elegante + imports guardados; los tests usan
  fakes. NO bloquear el merge de FEAT-210 en el de #208/#209 — los comandos
  dependientes responden "no configurado" hasta que aquellas aterricen y se
  wireen en `app.py`.
- **Visibilidad de comandos**: `setMyCommands` de Telegram es global por bot
  (o por scope de chat). Exponer los de operador solo a operadores requiere
  command scopes por chat; si es complejo, documentar que el menú los muestra
  pero el gate los bloquea. (Open Question.)
- **`_is_authorized` permite todos si `allowed_chat_ids is None`** (wrapper.py:900)
  — `_is_operator` NO debe heredar ese comportamiento permisivo (fail-closed).
- **`/thread` puede tardar**: usar el patrón de typing indicator existente y el
  `timeout` del spawn (FEAT-208) para no colgar el chat.
- **/memory puede ser grande**: limitar a N turnos recientes y truncar.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (ninguno nuevo) | — | Reutiliza aiogram/pydantic ya presentes. |

---

## 8. Open Questions

> Resueltas por el usuario antes de redactar este spec:

- [x] ¿Quién puede usar los comandos de operador? — *Resuelto*: **solo operadores**
  vía allowlist `operator_chat_ids` (fail-closed). Reflejado en G2/M1 y §5.
- [x] ¿`/model` y `/mission` leen o mutan? — *Resuelto*: **solo lectura** en este
  spec. Reflejado en G3, Non-Goals y §5.
- [x] ¿Cómo manejar dependencias no mergeadas (#208/#209)? — *Resuelto*:
  **implementar los 7 completos** consumiendo #208/#209, con **degradación
  elegante** + imports guardados. Reflejado en G6, §2 y Risks.

> Pendientes (decidibles en implementación):

- [ ] ¿Exponer los comandos de operador en el menú vía Telegram *command scopes*
  por chat, o solo gatearlos en el handler? — *Owner: implementador M5*.
- [ ] ¿`operator_chat_ids=None` significa "nadie" (fail-closed) o "heredar
  `allowed_chat_ids`"? — *Owner: usuario* (preferencia del spec: fail-closed).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — M1→M5 son secuenciales y comparten
  `wrapper.py`/`operator_commands.py`/`models.py`; sin paralelismo útil.
- **Cross-feature dependencies**: **soft** sobre FEAT-208 (sub-agentes) y
  FEAT-209 (heartbeat). No son merge-blockers gracias a la degradación elegante,
  pero el valor completo de `/health`,`/status`,`/thread` requiere que ambas
  estén mergeadas y wired en `app.py`. Recomendado mergear FEAT-210 **después**
  de #208/#209 para una demo end-to-end, o antes con los comandos degradados.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-31 | jesuslarag (via Claude) | Initial draft — 7 operator commands sobre TelegramAgentWrapper, gate de operador fail-closed, /model+/mission solo lectura, consume FEAT-208/209 con degradación elegante. |
