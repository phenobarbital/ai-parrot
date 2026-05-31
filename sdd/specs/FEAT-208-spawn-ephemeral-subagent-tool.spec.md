---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Spawn Ephemeral Sub-Agent Tool

**Feature ID**: FEAT-208
**Date**: 2026-05-31
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Para construir un *agent harness* autónomo (inspirado en el proyecto Go
**aphelion**), un agente always-on necesita poder **delegar trabajo acotado a
sub-agentes efímeros**: crear en caliente un agente con un subconjunto reducido
de herramientas, ejecutar UNA tarea aislada, devolver el resultado y
**destruirlo** sin dejar estado.

Tras auditar el codebase encontramos que **el ciclo de vida efímero ya existe**
y NO debe reimplementarse:

- `packages/ai-parrot-server/src/parrot/manager/ephemeral.py` — modelo
  `EphemeralAgentStatus` (fases `creating→warming→ready→error`, TTL),
  `EphemeralRegistry` (store in-memory con lock + ownership), corrutina
  `_warm_up` (fire-and-forget con teardown automático en error).
- `packages/ai-parrot-server/src/parrot/manager/manager.py` — métodos
  `create_ephemeral_user_bot` / `get_ephemeral_status` /
  `discard_ephemeral_user_bot` / `promote_user_bot` (FEAT-149).
- `packages/ai-parrot-server/src/parrot/handlers/agents/ephemeral.py` —
  `EphemeralUserAgentHandler`, un adaptador HTTP **delgado** sobre esos métodos,
  que demuestra que la lógica de negocio es reutilizable sin HTTP.

La **brecha** es estrecha: hoy ese flujo solo se dispara por HTTP, con ownership
cableado a un `user_id: int` humano. Falta (a) generalizar el ownership para que
un **agente** sea dueño de su sub-agente, y (b) un **tool de primera clase** que
un agente invoque en proceso para spawnear→ejecutar→descartar.

### Goals

- **G1**: Generalizar el ownership del subsistema efímero para soportar dueño
  `user` (humano) **o** `agent`, sin romper el handler HTTP ni los tests de
  FEAT-149 (compatibilidad retro con `user_id: int`).
- **G2**: Nuevo `SpawnSubAgentTool(AbstractTool)` en
  `packages/ai-parrot/src/parrot/tools/spawn.py` que, con **config explícita**
  (task, subset de tools, modelo, system_prompt, timeout, ttl corto), spawnea un
  sub-agente efímero, ejecuta la tarea con timeout y lo **descarta** (nunca
  `promote`).
- **G3**: Acotar las tools del sub-agente al **subset autorizado** (intersección
  con una allowlist provista por el padre — defensa en profundidad).
- **G4**: Garantizar **teardown**: tras terminar (éxito, error o timeout), ni
  `BotManager._bots` ni `EphemeralRegistry` conservan referencia al sub-agente.
- **G5**: Tests verdes nuevos + cero regresiones en los tests del subsistema
  efímero existente.

### Non-Goals (explicitly out of scope)

- **Gating por grants / aprobación HITL** de tools mutantes (`requires_grant`):
  es la feature #5 (grants acotados) del plan; aquí solo se deja el `routing_meta`
  preparado, sin enforcement.
- **Modo "describe y crea" vía `AgentFactoryOrchestrator`** (router LLM + gates):
  diferido a una fase 2. Este spec implementa SOLO el modo de **config explícita**.
- **Sub-agentes durables** (persistir reinicios, `promote_user_bot`): fuera de
  alcance — el tool siempre descarta.
- **Comando `/thread` de Telegram**: lo consumirá la feature #6 más adelante;
  no se implementa aquí.
- **Despliegue remoto** (estilo Tailscale de aphelion): explícitamente descartado.

---

## 2. Architectural Design

### Overview

Se añade un tool `SpawnSubAgentTool` en el paquete core `ai-parrot` que orquesta
los métodos ya existentes de `BotManager` (en `ai-parrot-server`). El tool recibe
una referencia al `BotManager` (vía `app["bot_manager"]` o inyección directa) y
un `owner` que identifica al agente padre.

Para que el agente sea owner, se **generaliza** `EphemeralAgentStatus` y los
métodos de `BotManager`/`EphemeralRegistry` para aceptar un ownership tipado
(`owner_id: str` + `owner_kind: Literal["user","agent"]`), conservando
`user_id: int` como **alias compatible** para no romper el handler HTTP ni los
tests de FEAT-149.

Flujo del tool (config explícita):

1. Construir `config` (forma `UserBotModel`) con el `system_prompt`, modelo, y el
   **subset de tools** inyectado vía `tools_config_plain` (intersección con la
   allowlist del padre).
2. `await bot_manager.create_ephemeral_user_bot(owner=..., config=..., ttl_seconds=<corto>)`.
3. Esperar `phase == "ready"` (poll de `get_ephemeral_status`; en entornos sin
   `app` el warm-up se salta y queda `ready` inmediato).
4. Resolver la instancia del sub-agente desde `BotManager` por `chatbot_id` y
   `await sub.invoke(question=task)` envuelto en `asyncio.wait_for(timeout)`.
5. `finally`: `await bot_manager.discard_ephemeral_user_bot(chatbot_id, owner)` —
   **siempre**, también en timeout/error. Devolver solo el resultado serializado.

### Component Diagram

```
ParentAgent
   │  (LLM tool call)
   ▼
SpawnSubAgentTool._execute()
   │
   ├─→ BotManager.create_ephemeral_user_bot(owner, config, ttl_seconds)
   │        └─→ EphemeralRegistry.register(EphemeralAgentStatus)
   │        └─→ asyncio.create_task(_warm_up(...))   # ready / error + auto-teardown
   │
   ├─→ poll BotManager.get_ephemeral_status(chatbot_id, owner) → phase=="ready"
   │
   ├─→ sub = BotManager.get_bots()[chatbot_id]
   │        await asyncio.wait_for(sub.invoke(question=task), timeout)
   │
   └─→ finally: BotManager.discard_ephemeral_user_bot(chatbot_id, owner)
            └─→ EphemeralRegistry.remove() + _bots.pop()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractTool` (`tools/abstract.py`) | extends | `SpawnSubAgentTool` implementa `_execute`; usa `args_schema` Pydantic + `routing_meta`. |
| `BotManager` (`ai-parrot-server`) | uses (refactor) | Llama create/get_status/discard; estos se generalizan para ownership tipado. |
| `EphemeralAgentStatus` / `EphemeralRegistry` (`manager/ephemeral.py`) | modifies | Añadir `owner_id`/`owner_kind` con compat `user_id`. |
| `EphemeralUserAgentHandler` (handler HTTP) | unchanged (compat) | Debe seguir funcionando vía el alias `user_id`. |
| `BasicBot.invoke()` (`bots/base.py:492`) | uses | Ejecuta la tarea del sub-agente (`question=task`). |
| `UserBotModel.set_tools_config` / `to_bot_kwargs` | uses | Inyección del subset de tools vía `tools_config_plain`. |

### Data Models

```python
# packages/ai-parrot/src/parrot/tools/spawn.py
class SpawnSubAgentInput(BaseModel):
    """Args schema for SpawnSubAgentTool."""
    task: str = Field(..., description="The task/question for the ephemeral sub-agent.")
    tools: list[str] = Field(
        default_factory=list,
        description="Allowed tool names for the sub-agent (subset of parent's allowlist).",
    )
    model: Optional[str] = Field(default=None, description="LLM model override.")
    system_prompt: Optional[str] = Field(default=None, description="System prompt for the sub-agent.")
    timeout: int = Field(default=120, ge=1, le=900, description="Max seconds for the sub-agent task.")
    ttl_seconds: int = Field(default=300, ge=10, description="Ephemeral TTL (short — minutes, not hours).")
```

```python
# packages/ai-parrot-server/src/parrot/manager/ephemeral.py  (MODIFIED)
OwnerKind = Literal["user", "agent"]

class EphemeralAgentStatus(BaseModel):
    chatbot_id: str
    owner_id: str                      # NEW canonical owner (str form)
    owner_kind: OwnerKind = "user"     # NEW
    # Backward-compat: user_id stays as an int alias for owner_kind == "user".
    # Implemented via a computed/aliased property — see §6 gotchas.
    phase: EphemeralPhase = "creating"
    progress: Dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    rag_mode: Optional[Literal["pageindex", "vector"]] = None
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/tools/spawn.py
class SpawnSubAgentTool(AbstractTool):
    args_schema = SpawnSubAgentInput

    def __init__(self, bot_manager, owner_id: str, *,
                 allowed_tools: Optional[list[str]] = None,
                 name: str = "spawn_sub_agent",
                 description: Optional[str] = None,
                 routing_meta: Optional[dict] = None) -> None: ...

    async def _execute(self, **kwargs) -> Any: ...
```

---

## 3. Module Breakdown

> Estos módulos mapean directamente a Task Artifacts en /sdd-task.

### Module 1: Ephemeral ownership generalization
- **Path**: `packages/ai-parrot-server/src/parrot/manager/ephemeral.py`
- **Responsibility**: Añadir `owner_id: str` + `owner_kind: Literal["user","agent"]`
  a `EphemeralAgentStatus`, manteniendo `user_id: int` como alias retrocompatible.
  Actualizar `EphemeralRegistry.get()/get_all_for_user()/remove()` para resolver
  por `owner_id` (no solo `user_id`).
- **Depends on**: existing FEAT-149 code.

### Module 2: BotManager ownership-aware methods
- **Path**: `packages/ai-parrot-server/src/parrot/manager/manager.py`
- **Responsibility**: Generalizar `create_ephemeral_user_bot`,
  `get_ephemeral_status`, `discard_ephemeral_user_bot` para aceptar owner tipado,
  conservando las firmas `user_id: int` existentes (sobrecarga/normalización
  interna). El handler HTTP no debe cambiar.
- **Depends on**: Module 1.

### Module 3: SpawnSubAgentTool
- **Path**: `packages/ai-parrot/src/parrot/tools/spawn.py`
- **Responsibility**: El tool `AbstractTool` que orquesta create→poll-ready→
  invoke(timeout)→discard, con subset de tools acotado y teardown garantizado.
- **Depends on**: Module 2.

### Module 4: Export & registration
- **Path**: `packages/ai-parrot/src/parrot/tools/__init__.py` (+ `tools/registry.py` si aplica lazy)
- **Responsibility**: Exportar `SpawnSubAgentTool` / `SpawnSubAgentInput`.
- **Depends on**: Module 3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ephemeral_status_owner_agent` | M1 | `EphemeralAgentStatus` acepta `owner_kind="agent"` + `owner_id` string. |
| `test_ephemeral_status_user_compat` | M1 | Crear con `user_id:int` sigue funcionando (alias → `owner_kind="user"`). |
| `test_registry_get_by_owner` | M1 | `EphemeralRegistry.get` resuelve por `owner_id` agente y por `user_id` humano. |
| `test_create_ephemeral_owner_agent` | M2 | `create_ephemeral_user_bot` con owner agente registra status y bot. |
| `test_spawn_subagent_runs_with_subset` | M3 | El hijo solo ve las tools del subset; ejecuta y devuelve resultado. |
| `test_spawn_subagent_timeout` | M3 | Tarea que excede `timeout` → cancela y descarta; error controlado. |
| `test_spawn_subagent_teardown` | M3/M4 | Tras terminar, `_bots` y `EphemeralRegistry` no contienen el `chatbot_id`. |

### Integration Tests
| Test | Description |
|---|---|
| `test_ephemeral_http_handler_still_works` | El `EphemeralUserAgentHandler` (user_id) sigue verde tras el refactor de ownership. |
| `test_parent_agent_spawns_and_discards` | Un agente con `SpawnSubAgentTool` spawnea un hijo, obtiene resultado y no deja referencias. |

### Test Data / Fixtures
```python
@pytest.fixture
def bot_manager_no_app():
    # self.app is None → _warm_up se salta, phase pasa a "ready" inmediato.
    # Permite testear el tool sin app aiohttp completa.
    ...

@pytest.fixture
def parent_owner():
    return {"owner_id": "agent:parent-123", "owner_kind": "agent"}
```

---

## 5. Acceptance Criteria

> Esta feature está completa cuando TODO lo siguiente es cierto:

- [ ] `EphemeralAgentStatus` soporta `owner_id`/`owner_kind`, y crear por
  `user_id:int` sigue funcionando (alias) — `pytest` M1 verde.
- [ ] `create_ephemeral_user_bot` / `get_ephemeral_status` /
  `discard_ephemeral_user_bot` aceptan owner agente sin romper la firma
  `user_id:int` existente.
- [ ] `EphemeralUserAgentHandler` y los tests existentes de FEAT-149 siguen
  pasando (cero regresiones).
- [ ] `SpawnSubAgentTool._execute` spawnea un sub-agente con tools restringidas
  al subset (intersección con allowlist del padre).
- [ ] El sub-agente respeta `timeout` (`asyncio.wait_for`) y `ttl_seconds` corto.
- [ ] Teardown garantizado: tras éxito/error/timeout, `BotManager._bots` y
  `EphemeralRegistry` no conservan el `chatbot_id` (assert explícito).
- [ ] El tool **nunca** llama `promote_user_bot`.
- [ ] `routing_meta` del tool queda preparado para `requires_grant` (sin
  enforcement — eso es FEAT de grants).
- [ ] Todos los tests nuevos pasan: `pytest packages/ai-parrot/tests/ -k spawn -v`
  y `pytest packages/ai-parrot-server/tests/ -k ephemeral -v`.
- [ ] Sin breaking changes en la API pública existente.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool          # verified: tools/abstract.py:81
# Subclass pattern reference (wraps an agent as a tool):
from parrot.tools.agent import AgentTool                 # verified: tools/agent.py:52
# Ephemeral subsystem (ai-parrot-server):
from parrot.manager.ephemeral import (                   # verified: manager/ephemeral.py
    EphemeralAgentStatus,                                # :75
    EphemeralRegistry,                                   # :106
    _warm_up,                                            # :232
)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):              # line 81
    args_schema: Type[BaseModel] = AbstractToolArgsSchema  # line 98
    routing_meta: Dict = None                            # line 100 (per-instance in __init__, line 140)
    async def _execute(self, **kwargs) -> Any: ...       # line 239 (ABSTRACT — subclasses implement)
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # line 473 (public wrapper)

# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot:
    async def invoke(self, question: str, session_id=None, user_id=None,
                     use_conversation_history=True, memory=None, ctx=None,
                     response_model=None, **kwargs) -> AIMessage:  # line 492
    async def ask(self, ...) -> ...                      # line 718

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                        # line 95
    def _ephemeral_registry(self)                        # line 879 (lazy singleton; no return annotation — returns EphemeralRegistry)
    async def create_ephemeral_user_bot(self, user_id: int,
        config: Dict[str, Any], uploaded_paths: List[dict], *,
        ttl_seconds: int = 86400)                        # line 888 (no return annotation — returns EphemeralAgentStatus)
    async def promote_user_bot(self, ...)                # line 1042  (NOT used by this feature)
    def get_ephemeral_status(self, chatbot_id: str, user_id: int)  # line 1147 (SYNC; no return annotation — returns Optional[EphemeralAgentStatus])
    async def discard_ephemeral_user_bot(self, chatbot_id: str, user_id: int) -> bool  # line 1163
    def get_bots(self) -> Dict[str, AbstractBot]         # line 857
    def add_agent(self, agent: AbstractBot) -> None       # line 866 (called at manager.py:965)

# packages/ai-parrot-server/src/parrot/manager/ephemeral.py
EphemeralPhase = Literal["creating", "warming", "ready", "error"]   # line 43
class EphemeralAgentStatus(BaseModel):                   # line 75
    chatbot_id: str; user_id: int                        # line 91-92  (← user_id to generalize)
    phase: EphemeralPhase = "creating"; progress: Dict[str,str]
    created_at: datetime; expires_at: datetime
class EphemeralRegistry:                                 # line 106
    async def register(self, status) -> None             # line 135
    def get(self, chatbot_id: str, user_id: int) -> Optional[...]  # line 150 (← generalize owner)
    def get_all_for_user(self, user_id: int) -> List[...]  # line 175
    async def remove(self, chatbot_id: str) -> bool      # line 186
    def get_expired(self) -> List[str]                   # line 202
async def _warm_up(bot, status, app, remove_bot_callback=None) -> None  # line 232 (auto-teardown on error: line 324-327)

# packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py
class UserBotModel(Model):                               # line 26
    def set_tools_config(self, value) -> None            # line 152
    def get_tools_config(self) -> List[dict]             # line 142
    def to_bot_kwargs(self) -> dict                      # line 165
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SpawnSubAgentTool._execute` | `BotManager.create_ephemeral_user_bot` | method call | `manager/manager.py:888` |
| `SpawnSubAgentTool._execute` | `BotManager.get_ephemeral_status` (poll) | method call | `manager/manager.py:1147` |
| `SpawnSubAgentTool._execute` | `BotManager.get_bots()[chatbot_id].invoke` | method call | `manager.py:857` + `base.py:492` |
| `SpawnSubAgentTool._execute` | `BotManager.discard_ephemeral_user_bot` (finally) | method call | `manager/manager.py:1163` |
| ownership generalization | `EphemeralRegistry.get/remove` | param change | `ephemeral.py:150,186` |

### Does NOT Exist (Anti-Hallucination)
- ~~`BotManager.spawn_sub_agent()`~~ — no existe; el tool lo orquesta.
- ~~`EphemeralAgentStatus.owner_id` / `owner_kind`~~ — NO existen aún; los añade M1.
- ~~`parrot.tools.spawn`~~ — módulo nuevo de esta feature (no existe todavía).
- ~~`BasicBot.run()` / `BasicBot.execute_task()`~~ — no existen; el método es `invoke(question=...)` (`base.py:492`) o `ask(...)` (`base.py:718`).
- ~~`tools_config` como lista de nombres de tools~~ — es una lista de **dicts de configuración** de tool (ver `get_tools_config -> List[dict]`, `users_bots.py:142`). El subset por nombres debe traducirse a esos dicts (ver gotcha).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `AbstractTool` con `args_schema` Pydantic; implementar `_execute(**kwargs)`
  (no `execute`, que es el wrapper público). Ref: `tools/agent.py::AgentTool`.
- async/await en todo; sin I/O bloqueante. `asyncio.wait_for` para el timeout.
- Logging con `self.logger` (no print).
- Compatibilidad retro: el refactor de ownership debe ser **aditivo**. Mantener
  `user_id` operativo (alias) — los tests de FEAT-149 son la red de seguridad.
- TTL corto por defecto para efímeros de agente (`ttl_seconds=300`), no 24h.

### Known Risks / Gotchas
- **`tools_config` ≠ lista de nombres**: es `List[dict]` de configs (con cifrado
  vía `seal`/`unseal`). El `tools[]` del tool (nombres) debe mapearse a los dicts
  de config correspondientes (resolver desde el `ToolManager`/registry del padre).
  Marcar como decisión de implementación en M3.
- **`get_ephemeral_status` es síncrono** (`manager.py:1147`) — el poll de `ready`
  es un bucle `await asyncio.sleep(...)` que llama al método sync. Considerar
  añadir un `asyncio.Event` opcional al status para evitar polling (mejora menor
  en `ephemeral.py`, opcional).
- **Atajo sin app**: si `BotManager.app is None`, `_warm_up` se salta y `phase`
  queda `"ready"` inmediato (`manager.py:994-995`) — usar en tests del tool.
- **Ownership en `_warm_up` callback**: el `remove_bot_callback`
  (`manager.py:991`) ya limpia `_bots` en fallo; el tool solo añade `discard` en
  `finally` para el camino feliz/timeout.
- **No `promote`**: asegurar que ninguna ruta del tool llama `promote_user_bot`
  (criterio de aceptación explícito).
- **Aislamiento del padre**: el subset de tools es intersección con una
  *allowlist* del padre — nunca ampliar privilegios.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (ninguno nuevo) | — | Reutiliza pydantic/asyncio ya presentes. |

---

## 8. Open Questions

> Resueltas por el usuario antes de redactar este spec:

- [x] ¿Cómo modelar el owner del efímero para un agente? — *Resuelto*: añadir
  `owner_kind`/`owner_id` a `EphemeralAgentStatus` (con `user_id` como alias
  retrocompatible). Reflejado en M1/M2 y §2.
- [x] ¿Cómo construye el sub-agente el tool en este spec? — *Resuelto*: **tool
  directo con config explícita** (NO `AgentFactoryOrchestrator` en esta feature;
  diferido a fase 2). Reflejado en Non-Goals y M3.

> Pendientes (decidibles en implementación):

- [ ] Mapear `tools[]` (nombres) → `tools_config` dicts: ¿resolver desde el
  `ToolManager` del padre o desde el registry global? — *Owner: implementador M3*.
- [ ] ¿Inyectar `BotManager` al tool vía `app["bot_manager"]` o por constructor
  explícito? — *Owner: implementador M3* (preferencia: constructor, testeable).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — las tareas son secuencialmente
  dependientes (M1 → M2 → M3 → M4) y tocan archivos que se encadenan; no hay
  paralelismo real que justifique múltiples worktrees.
- **Cross-feature dependencies**: ninguna obligatoria. El gating por grants
  (feature #5) y el comando `/thread` (feature #6) **consumirán** este tool más
  tarde, pero no son prerequisitos de esta feature.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-31 | jesuslarag (via Claude) | Initial draft — ephemeral lifecycle already exists (FEAT-149); this adds ownership generalization + SpawnSubAgentTool. |
