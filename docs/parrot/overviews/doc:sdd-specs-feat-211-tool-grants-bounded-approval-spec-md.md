---
type: Wiki Overview
title: 'Feature Specification: Tool Grants & Bounded Approval Windows'
id: doc:sdd-specs-feat-211-tool-grants-bounded-approval-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Un *agent harness* autónomo (inspirado en **aphelion**) separa la **persona
relates_to:
- concept: mod:parrot.auth.grants
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.human.manager
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Tool Grants & Bounded Approval Windows

**Feature ID**: FEAT-211
**Date**: 2026-05-31
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Un *agent harness* autónomo (inspirado en **aphelion**) separa la **persona
conversacional** (Face) del **árbitro de autoridad** (Governor): las acciones
sensibles requieren **consentimiento explícito**, y una aprobación abre una
**ventana acotada de automatización** (p. ej. 15 min) durante la cual la acción
puede repetirse sin re-preguntar. El pipeline es
`request → review → grant → observe → revoke`.

Tras auditar el codebase, lo necesario para **reutilizar** existe, pero el grant
en sí **no**:

- **HITL maduro**: `HumanInteractionManager`
  (`packages/ai-parrot/src/parrot/human/manager.py:51`) — `request_human_input(interaction, channel)`
  bloquea con `asyncio.Future` y devuelve `InteractionResult`; `InteractionType.APPROVAL`
  (models.py:66) da decisión booleana; el canal Telegram ya renderiza
  **✅ Approve / ❌ Reject** inline (`integrations/.../human/channels/telegram.py:290`).
- **Punto de gating central**: `ToolManager.execute_tool(tool_name, parameters,
  permission_context)` (`tools/manager.py:1126`) es el dispatch por el que pasa
  **toda** ejecución de tool del loop del agente; ya propaga
  `_permission_context`/`_resolver` y ya sabe devolver `ToolResult(status="forbidden")`
  (manager.py:1178-1180).
- **Identidad/roles**: `PermissionContext`/`UserSession`
  (`auth/permission.py:80,20`) ya fluyen a las tools.
- **Marcado de tool**: `routing_meta` (`tools/abstract.py:100,140`) puede marcar
  una tool como `requires_grant`.

**La brecha** (confirmada repo-wide): **no existe ningún concepto de Grant,
ventana de aprobación acotada, ni automation window**. Los lifecycle events
(`BeforeToolCallEvent`) son **observacionales y NO permiten veto** (error
isolation), así que el guardia debe vivir en el dispatch, no en un subscriber.

### Goals

- **G1**: Modelo `Grant` (Pydantic) con `scope`, `owner`, `granted_by`,
  `expires_at` / ventana acotada, y `revoked`.
- **G2**: `GrantStore` (ABC) + `InMemoryGrantStore` con expiración por TTL y
  limpieza periódica; diseñado para un backend Redis futuro (no implementado aquí).
- **G3**: **Guardia bloqueante en `ToolManager.execute_tool`**: si la tool está
  marcada `requires_grant` (vía `routing_meta`) y NO hay grant vigente para el
  `(owner, scope)`, **pausar** y pedir aprobación vía `HumanInteractionManager`.
- **G4**: Al **aprobar**, crear un `Grant` con **ventana acotada** (p. ej. 15 min,
  configurable); subsiguientes llamadas dentro de la ventana pasan **sin
  re-preguntar**. Al expirar/revocar, vuelve a pedirse.
- **G5**: **Fail-closed**: si `requires_grant` y no hay grant vigente NI canal
  HITL para pedir aprobación → **denegar** (`ToolResult(status="forbidden")`).
- **G6**: Mínima invasión del core: NO modificar `AbstractTool.execute`
  (foundational); el gating va en `ToolManager`. Inyección estilo `set_resolver`.
- **G7**: Tests verdes; cero regresiones en el flujo de tools existente.

### Non-Goals (explicitly out of scope)

- **Backend Redis/persistente de grants**: solo in-memory ahora (abstracción
  lista para Redis). La durabilidad/replay de grants se atará al **ledger
  (FEAT-212 / feature #4)**.
- **Reescritura de PBAC/ABAC**: los grants son una capa **complementaria** al
  PBAC existente (no lo sustituyen). PBAC sigue siendo el check de roles base.
- **Gating en tools fuera del `ToolManager`**: una tool ejecutada directamente
  por `.execute()` sin pasar por el manager NO queda gateada (aceptado; el loop
  del agente siempre pasa por `ToolManager`). Documentado en Risks.
- **Separación física Face/Governor en dos procesos/LLMs**: aquí "Governor" es el
  guardia lógico de grants; el bot sigue siendo una sola persona (Face).
- **UI de gestión de grants** más allá del flujo de aprobación HITL existente.
- **Auto-marcado de tools sensibles**: marcar `requires_grant` es responsabilidad
  de quien configura la tool/toolkit (este spec define el mecanismo, no la
  política de qué tools son sensibles — aunque sí da ejemplos).

---

## 2. Architectural Design

### Overview

Se añade un subsistema `grants` en core (`parrot/auth/grants.py`) y un **guardia**
en `ToolManager.execute_tool`. El `ToolManager` recibe (vía setters, como
`set_resolver`) un `GrantStore` y un `HumanInteractionManager` opcional + la
config de la ventana.

Flujo del guardia (Governor), dentro de `execute_tool`, **antes** del dispatch a
`tool.execute()`:

```
if tool.routing_meta.get("requires_grant"):
    scope = grant_scope(tool, parameters)         # p.ej. "tool:pulumi_apply"
    owner = permission_context.user_id (o agent)  # quién actúa
    if grant_store.is_allowed(owner, scope):      # grant vigente?
        pass                                       # ✅ dentro de la ventana
    elif human_manager is not None:
        approved = await human_manager.request_human_input(
            HumanInteraction(interaction_type=APPROVAL, ...), channel)
        if approved:
            grant_store.grant(owner, scope, window=15min)   # abre ventana
        else:
            return ToolResult(status="forbidden", ...)      # denegado
    else:
        return ToolResult(status="forbidden", ...)          # FAIL-CLOSED
# ...continúa el dispatch normal a tool.execute()
```

### Component Diagram

```
Agent loop → ToolManager.execute_tool(tool, params, pctx)
                     │
                     ├─ tool.routing_meta["requires_grant"]?  ── no ──► dispatch normal
                     │                                              │
                     yes                                            ▼
                     ▼                                       tool.execute()
              GrantStore.is_allowed(owner, scope)?
                     │
            ┌── yes ─┴─ no ──┐
            ▼                 ▼
         dispatch    HumanInteractionManager.request_human_input(APPROVAL)
                              │
                     ┌─ approve ─┴─ reject / no-channel ─┐
                     ▼                                     ▼
            GrantStore.grant(owner, scope, 15min)   ToolResult(forbidden)  ← fail-closed
                     │
                     ▼
                 dispatch
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ToolManager.execute_tool` (`tools/manager.py:1126`) | modifies | Inserta el guardia antes del dispatch a `AbstractTool` (1167-1175). |
| `ToolManager.set_resolver` pattern (`manager.py:59`) | mirrors | Nuevos `set_grant_store()` / `set_human_manager()`. |
| `routing_meta` (`tools/abstract.py:100,140`) | reads | Marca `requires_grant` + opcional `grant_window_seconds`/`grant_scope`. |
| `HumanInteractionManager.request_human_input` (`human/manager.py`) | uses | Pide aprobación bloqueante (APPROVAL) y espera el `InteractionResult`. |
| `InteractionType.APPROVAL` / `HumanInteraction` (`human/models.py:66,380`) | uses | Payload de la aprobación (question, timeout, severity, default_response). |
| `PermissionContext`/`UserSession` (`auth/permission.py:80,20`) | reads | `owner` del grant (user_id; o agent_id para sub-agentes FEAT-208). |
| `ToolResult(status="forbidden")` (`tools/abstract.py`) | reuses | Resultado de denegación (manager ya lo maneja, 1178-1180). |
| Ledger (FEAT-212, feature #4) | future | `grant`/`revoke` se registrarán como eventos cuando exista. |

### Data Models

```python
# packages/ai-parrot/src/parrot/auth/grants.py
class Grant(BaseModel):
    grant_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str                      # who acts (user_id or agent_id)
    scope: str                         # e.g. "tool:pulumi_apply" or "tool:*"
    granted_by: str                    # who approved (human respondent id)
    created_at: datetime
    expires_at: datetime               # bounded window end
    revoked: bool = False

    def is_active(self, now: datetime) -> bool:
        return (not self.revoked) and now < self.expires_at

    def covers(self, scope: str) -> bool:
        return self.scope == scope or self.scope == "tool:*"

class GrantConfig(BaseModel):
    window_seconds: int = Field(900, gt=0)   # default 15 min
    approval_timeout: float = Field(120.0, gt=0)
    default_channel: str = "telegram"
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/auth/grants.py
class GrantStore(ABC):
    @abstractmethod
    async def grant(self, owner_id: str, scope: str, *, granted_by: str,
                    window_seconds: int) -> Grant: ...
    @abstractmethod
    async def is_allowed(self, owner_id: str, scope: str) -> bool: ...
    @abstractmethod
    async def revoke(self, grant_id: str) -> bool: ...
    @abstractmethod
    async def list_active(self, owner_id: str) -> list[Grant]: ...

class InMemoryGrantStore(GrantStore):
    """Dict-backed, TTL expiry + periodic cleanup (pattern from _periodic_cleanup)."""
    ...

class GrantGuard:
    """The 'Governor': decides allow / approve / deny for a tool call."""
    def __init__(self, store: GrantStore, human_manager=None,
                 config: GrantConfig | None = None) -> None: ...
    async def authorize(self, *, tool, parameters: dict,
                        permission_context) -> "GuardDecision": ...
    # GuardDecision: allowed: bool, reason: str, grant: Optional[Grant]
```

```python
# packages/ai-parrot/src/parrot/tools/manager.py  (MODIFIED — additive)
class ToolManager:
    def set_grant_guard(self, guard: "GrantGuard") -> None: ...   # NEW (mirror of set_resolver)
    # execute_tool(): if guard set and tool requires_grant → guard.authorize() before dispatch
```

---

## 3. Module Breakdown

### Module 1: Grant models + store
- **Path**: `packages/ai-parrot/src/parrot/auth/grants.py`
- **Responsibility**: `Grant`, `GrantConfig`, `GrantStore` (ABC),
  `InMemoryGrantStore` (TTL + cleanup).
- **Depends on**: nada nuevo.

### Module 2: GrantGuard (the Governor)
- **Path**: `packages/ai-parrot/src/parrot/auth/grants.py` (continuación)
- **Responsibility**: `GrantGuard.authorize(tool, parameters, permission_context)`:
  resuelve scope/owner, consulta el store, dispara HITL approval, abre ventana o
  deniega (fail-closed). Devuelve `GuardDecision`.
- **Depends on**: Module 1; `HumanInteractionManager` (opcional).

### Module 3: ToolManager integration
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py`
- **Responsibility**: `set_grant_guard()`; en `execute_tool`, antes del dispatch a
  `AbstractTool`, si `tool.routing_meta.get("requires_grant")` y hay guard →
  `guard.authorize(...)`; si no permitido, devolver `ToolResult(status="forbidden")`.
  Cambio **aditivo** (sin guard → comportamiento idéntico al actual).
- **Depends on**: Modules 1-2.

### Module 4: Wiring + exports
- **Path**: `packages/ai-parrot/src/parrot/auth/__init__.py` (+ doc de wiring en
  bot/app: crear store, guard con human_manager y `tool_manager.set_grant_guard`)
- **Responsibility**: exportar `Grant`/`GrantStore`/`InMemoryGrantStore`/`GrantGuard`/`GrantConfig`.
- **Depends on**: Modules 1-3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_grant_is_active_expiry` | M1 | `Grant.is_active` False tras `expires_at`; True dentro de ventana. |
| `test_grant_covers_wildcard` | M1 | `scope="tool:*"` cubre cualquier scope. |
| `test_inmemory_grant_and_isallowed` | M1 | `grant()` → `is_allowed` True; tras expiry → False. |
| `test_inmemory_revoke` | M1 | `revoke()` invalida el grant inmediatamente. |
| `test_guard_allows_with_active_grant` | M2 | Con grant vigente, `authorize` permite sin llamar HITL. |
| `test_guard_requests_approval_then_grants` | M2 | Sin grant + human_manager fake aprueba → crea grant y permite; 2ª llamada NO re-pregunta. |
| `test_guard_denied_on_reject` | M2 | HITL rechaza → `authorize` deniega (no crea grant). |
| `test_guard_failclosed_no_channel` | M2 | `requires_grant` sin grant y sin human_manager → deniega. |

### Integration Tests
| Test | Description |
|---|---|
| `test_toolmanager_gates_requires_grant` | Tool con `routing_meta={"requires_grant": True}` vía `execute_tool` con guard fake-approve → ejecuta; 2ª vez dentro de ventana ejecuta sin re-aprobar. |
| `test_toolmanager_no_guard_unaffected` | Sin guard configurado, las tools (incl. `requires_grant`) ejecutan como hoy (cero regresión). |
| `test_toolmanager_denied_returns_forbidden` | Guard deniega → `execute_tool` devuelve `ToolResult(status="forbidden")`. |

### Test Data / Fixtures
```python
@pytest.fixture
def approve_manager():
    m = MagicMock()
    async def _req(interaction, channel="telegram"):
        return InteractionResult(interaction_id=interaction.interaction_id,
                                 status=InteractionStatus.COMPLETED,
                                 consolidated_value=True)
    m.request_human_input = AsyncMock(side_effect=_req)
    return m

@pytest.fixture
def sensitive_tool():
    t = MagicMock(spec=AbstractTool)
    t.name = "pulumi_apply"
    t.routing_meta = {"requires_grant": True, "grant_window_seconds": 900}
    t.execute = AsyncMock(return_value=ToolResult(status="success", result="ok"))
    return t
```

---

## 5. Acceptance Criteria

> Esta feature está completa cuando TODO lo siguiente es cierto:

- [ ] `Grant`/`GrantStore`/`InMemoryGrantStore` con expiración por ventana y
  limpieza de expirados.
- [ ] `GrantGuard.authorize` permite si hay grant vigente; pide aprobación HITL si
  no; abre ventana acotada al aprobar; deniega al rechazar.
- [ ] **Guardia en `ToolManager.execute_tool`**: tools `requires_grant` se gatean
  **antes** del dispatch; el resto pasa sin cambios.
- [ ] **Ventana acotada**: dos llamadas dentro de la ventana → solo 1 aprobación;
  tras expirar → vuelve a pedir.
- [ ] **Fail-closed**: `requires_grant` sin grant y sin canal HITL → `forbidden`.
- [ ] **Aditivo**: sin `GrantGuard` configurado, `execute_tool` se comporta
  idéntico al actual (cero regresión; `AbstractTool.execute` SIN tocar).
- [ ] Reutiliza `HumanInteractionManager` + `InteractionType.APPROVAL` (no
  reimplementa HITL).
- [ ] Tests: `pytest packages/ai-parrot/tests/ -k grant -v` verde.
- [ ] Sin breaking changes en la API pública existente.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.tools.manager import ToolManager           # verified: tools/manager.py
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: tools/abstract.py:81,46
from parrot.auth.permission import PermissionContext, UserSession  # verified: auth/permission.py:80,20
from parrot.human.manager import HumanInteractionManager   # verified: human/manager.py:51
from parrot.human.models import (                       # verified: human/models.py
    HumanInteraction,         # :380
    InteractionType,          # :60  (APPROVAL = "approval" :66)
    InteractionResult,        # :498
    InteractionStatus,        # :71
)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    self._resolver = None                                # init
    def set_resolver(self, resolver) -> None:            # line 59 (injection pattern to mirror)
    async def execute_tool(self, tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None) -> Any:  # line 1126
        # dispatch: AbstractTool branch lines 1167-1190
        #   exec_kwargs['_permission_context']=permission_context (1172)
        #   exec_kwargs['_resolver']=self._resolver (1174)
        #   result = await tool.execute(**exec_kwargs) (1175)
        #   if result.status == 'forbidden': return result (1179-1180)

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):              # line 81
    routing_meta: Dict                                   # line 100 (per-instance, line 140)
    async def execute(self, *args, **kwargs) -> ToolResult:  # line 473
        # Layer-2 check uses _permission_context + _resolver (488-510)
        # BeforeToolCallEvent is emit_nowait → OBSERVATIONAL, NO veto (531)
class ToolResult(BaseModel): ...                         # line 46 (status field incl. "forbidden")

# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:
    def __init__(self, channels=None, redis_url=None,
                 reject_detector=None, on_event=None) -> None:   # line 73
    async def request_human_input(self, interaction: HumanInteraction,
                 channel: str = "telegram") -> InteractionResult:  # BLOCKING (asyncio.Future)
    async def startup(self) -> None:                     # line 256

# packages/ai-parrot/src/parrot/human/models.py
class InteractionType(str, Enum): APPROVAL = "approval"  # line 66
class HumanInteraction(BaseModel):                       # line 380
    interaction_type; question; timeout=7200.0; default_response; severity; policy_id
class InteractionResult(BaseModel):                      # line 498
    interaction_id; status: InteractionStatus; consolidated_value: Any  # bool for APPROVAL

# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen=True)
class UserSession: user_id; tenant_id; roles: frozenset[str]   # line 20
@dataclass
class PermissionContext:                                 # line 80
    session: UserSession; channel: Optional[str]; extra: dict
    @property user_id -> str
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ToolManager.set_grant_guard` | mirror of `set_resolver` | new setter | `manager.py:59` |
| guard call | `ToolManager.execute_tool` before dispatch | inline check | `manager.py:1167-1175` |
| `GrantGuard.authorize` | `HumanInteractionManager.request_human_input` | method call | `human/manager.py` |
| denial | `ToolResult(status="forbidden")` | return value | `manager.py:1178-1180` |
| `requires_grant` flag | `tool.routing_meta` | dict read | `abstract.py:100,140` |

### Does NOT Exist (Anti-Hallucination)
- ~~`Grant`, `GrantStore`, `GrantGuard`, `parrot.auth.grants`~~ — **NO existen** (confirmado repo-wide). Los crea esta feature.
- ~~ventana de aprobación / automation window / bounded grant~~ — NO existe. `BusinessHours` (human/models.py) es para horarios de escalación, NO grants.
- ~~veto vía `BeforeToolCallEvent`~~ — los lifecycle subscribers NO pueden abortar (error isolation). Por eso el guardia va en `execute_tool`, no en un subscriber.
- ~~`routing_meta["requires_grant"]` con consumidores~~ — `routing_meta` hoy solo lo lee `CapabilityRegistry` (keys `description`/`not_for`); `requires_grant` es nuevo.
- ~~modificar `AbstractTool.execute`~~ — NO se toca (decisión: gating en `ToolManager`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Inyección estilo `set_resolver` (`manager.py:59`): `set_grant_guard(guard)`.
- Cambio **aditivo** en `execute_tool`: sin guard → ruta actual intacta.
- `InMemoryGrantStore` con limpieza periódica (patrón `_periodic_cleanup` de los
  stores de cache existentes).
- Reusar `HumanInteractionManager.request_human_input` + `InteractionType.APPROVAL`;
  el `consolidated_value` booleano es la decisión.
- Pydantic para `Grant`/`GrantConfig`; `self.logger`.
- `owner_id` = `permission_context.user_id`; para sub-agentes (FEAT-208) será el
  `agent_id` (compatible — es `str`).

### Known Risks / Gotchas
- **Tools fuera del ToolManager**: una tool llamada directamente por `.execute()`
  NO queda gateada. Aceptado: el loop del agente siempre pasa por `ToolManager`.
  Documentar; si en el futuro se requiere cobertura total, mover a `AbstractTool`.
- **Aprobación bloqueante**: `request_human_input` bloquea hasta respuesta/timeout.
  Usar el `timeout` de `HumanInteraction` y un `default_response` seguro
  (deny) ante timeout (fail-closed).
- **Scope del grant**: definir `grant_scope` por defecto = `f"tool:{tool.name}"`;
  permitir override vía `routing_meta["grant_scope"]` (p.ej. agrupar
  `pulumi_apply`+`pulumi_destroy` bajo `tool:pulumi:write`).
- **Concurrencia**: el store usa lock para evitar TOCTOU entre check y grant
  (patrón de `EphemeralRegistry`).
- **No persistente**: grants in-memory se pierden al reiniciar (aceptado; el
  resume llegará con el ledger #4). Documentar.
- **PBAC vs grants**: complementarios. El grant NO reemplaza el check de roles;
  si la tool además tiene `_required_permissions`, ambos aplican.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (ninguno nuevo) | — | Reutiliza pydantic/asyncio y el HITL existente. |

---

## 8. Open Questions

> Resueltas por el usuario antes de redactar este spec:

- [x] ¿Dónde insertar el guardia bloqueante? — *Resuelto*: en
  **`ToolManager.execute_tool`** (no en `AbstractTool.execute`). Reflejado en
  G6/M3 y §2.
- [x] ¿Qué pasa sin grant ni canal HITL? — *Resuelto*: **fail-closed** (denegar).
  Reflejado en G5 y §5.
- [x] ¿Backend del GrantStore? — *Resuelto*: **in-memory ahora, abstracto para
  Redis** después (resume vía ledger #4). Reflejado en G2/M1 y Non-Goals.

> Pendientes (decidibles en implementación):

- [ ] Scope por defecto del grant: `tool:{name}` vs agrupaciones declaradas en
  `routing_meta["grant_scope"]` — *Owner: implementador M2* (preferencia: default
  `tool:{name}` + override opcional).
- [ ] ¿La ventana se **renueva** en cada uso (sliding) o es fija desde la
  aprobación? — *Owner: usuario* (preferencia del spec: **fija** desde la
  aprobación, estilo aphelion 15-min window).: pudiera renovarse sliding en cada uso.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — M1→M4 secuenciales; M1/M2 comparten
  `grants.py`, M3 toca `manager.py`. Sin paralelismo útil.
- **Cross-feature dependencies**: ninguna **dura**. **Sinergia** con FEAT-208
  (sub-agentes: `owner_id` = agent_id; tools mutantes con `requires_grant`),
  FEAT-210 (`/thread` y tools de operador) y FEAT-212/#4 (ledger registra
  grant/revoke y habilita resume). Mergeable de forma independiente.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-31 | jesuslarag (via Claude) | Initial draft — Grant model + InMemoryGrantStore + GrantGuard, gating en ToolManager.execute_tool (fail-closed), reutiliza HumanInteractionManager (APPROVAL). |
