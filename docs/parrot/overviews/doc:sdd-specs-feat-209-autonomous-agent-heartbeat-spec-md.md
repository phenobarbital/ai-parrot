---
type: Wiki Overview
title: 'Feature Specification: Autonomous Agent Heartbeat'
id: doc:sdd-specs-feat-209-autonomous-agent-heartbeat-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Para un *agent harness* autónomo de servicio (inspirado en el proyecto Go
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.heartbeat
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Autonomous Agent Heartbeat

**Feature ID**: FEAT-209
**Date**: 2026-05-31
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Para un *agent harness* autónomo de servicio (inspirado en el proyecto Go
**aphelion**), un agente always-on no debe limitarse a **reaccionar** a mensajes
o a correr **jobs fijos** (cron). Necesita un **heartbeat**: un latido periódico
en el que el agente *despierta*, *evalúa* su estado/señales y *decide* si actuar
— el patrón "daily review recipes" de aphelion.

Tras auditar el codebase:

- `AutonomousOrchestrator`
  (`packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py`) ya ofrece
  `start()`/`stop()`, `execute_agent(...)`, `execute_crew(...)`, `inject_job(...)`
  y triggers (event-bus, webhooks, redis-jobs). Pero **no tiene un heartbeat
  por-agente**.
- `AgentSchedulerManager`
  (`packages/ai-parrot-server/src/parrot/scheduler/manager.py`) cubre
  scheduling APScheduler (cron/interval/reportes) — eso es un **cron**, no un
  heartbeat con paso de decisión.
- `autonomous/scheduler.py` define `TriggerMode` (incluye `REACTIVE`) +
  dataclasses `AgentTriggerConfig`/`AutonomousJob`, pero **están huérfanas**
  (solo se reexportan en `parrot/autonomous/__init__.py`; nadie las usa).
- El único loop tipo heartbeat real es `_presence_loop`
  (`autonomous/transport/filesystem/transport.py:296`) — un `while True:
  asyncio.sleep + heartbeat + gc` que sirve de **patrón de referencia**.

### Goals

- **G1**: Nuevo `HeartbeatManager` (loop asyncio propio) que registra agentes
  con un intervalo y, en cada tick, ejecuta un ciclo **wake → assess → maybe
  act**: evalúa señales, y SOLO si el paso de decisión lo amerita, dispara
  `AutonomousOrchestrator.execute_agent(...)`.
- **G2**: Control fino del loop, espejo de `_presence_loop`: `jitter` opcional,
  backoff ante errores consecutivos, y **lock por-agente "skip si ocupado"**
  (no solapar ticks de un mismo agente).
- **G3**: Lifecycle limpio: `start()/stop()` con `asyncio.create_task` y
  cancelación segura (manejo de `asyncio.CancelledError`), integrable en
  `on_startup`/`on_shutdown` de la app.
- **G4**: El paso *assess* es **pluggable**: una función/estrategia de decisión
  (`should_act(ctx) -> bool` + construcción del prompt-misión) inyectable, con un
  default razonable. Sin acoplar el heartbeat a un agente concreto.
- **G5**: Observabilidad: estado por-agente (último tick, nº ticks, nº acciones,
  últimos errores) consultable — base para `/health` y `/status` (feature #6) y
  para el ledger (feature #4).
- **G6**: Tests verdes con intervalos cortos y un orchestrator/agent fake.

### Non-Goals (explicitly out of scope)

- **Persistencia/replay del heartbeat** tras crash: lo aporta el **ledger**
  (feature #4). Aquí el estado es in-memory.
- **Scheduling cron/interval de reportes**: ya cubierto por
  `AgentSchedulerManager`; el heartbeat NO lo reemplaza.
- **Comandos de operador** (`/health`,`/status`): feature #6; este spec solo
  expone el estado consultable, no la UI de Telegram.
- **Notificación proactiva del resultado** (voz/Telegram): el heartbeat dispara
  `execute_agent`; el envío proactivo es de las features #2/#6.
- **Refactor de las dataclasses huérfanas** de `autonomous/scheduler.py` más allá
  de reutilizar `TriggerMode.REACTIVE`/`AgentTriggerConfig` si encaja
  naturalmente (no es obligatorio).

---

## 2. Architectural Design

### Overview

Se añade un `HeartbeatManager` en `ai-parrot-server` que mantiene un
`asyncio.Task` por agente registrado. Cada task corre un bucle:

```
while running:
    await asyncio.sleep(interval ± jitter)
    if lock_held(agent): continue            # skip si ocupado
    with per-agent lock:
        ctx = build_context(agent)           # señales: memoria/cola/estado
        if strategy.should_act(ctx):         # paso de decisión (assess)
            prompt = strategy.build_prompt(ctx)
            result = await orchestrator.execute_agent(agent, prompt)
            record(agent, result)            # observabilidad
    # backoff ante errores consecutivos
```

El paso *assess* (`should_act` + `build_prompt`) vive en una estrategia
inyectable (`HeartbeatStrategy`), con un default que actúa siempre que haya
"trabajo pendiente" según un callable provisto (o cada N ticks). Esto distingue
el heartbeat de un cron job.

### Component Diagram

```
app on_startup
   │
   ▼
HeartbeatManager.start()
   │  (one asyncio.Task per agent)
   ▼
_heartbeat_loop(agent)  ──sleep+jitter──┐
   │                                     │
   ├─ per-agent lock (skip if busy)      │ loop
   ├─ ctx = strategy.build_context()     │
   ├─ if strategy.should_act(ctx):       │
   │     orchestrator.execute_agent(...) ─┘
   └─ record(HeartbeatState)  ──→ get_state() (for /health, ledger)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AutonomousOrchestrator.execute_agent` | uses | El tick actúa vía este método (`orchestrator.py:358`). |
| `AutonomousOrchestrator.start/stop` | composes | `HeartbeatManager` se inicia junto al orchestrator. |
| `_presence_loop` pattern (`transport.py:296`) | mirrors | Mismo patrón sleep+try/except `CancelledError`. |
| `autonomous/scheduler.py::TriggerMode.REACTIVE` | reuses (optional) | Modo conceptual del heartbeat; reutilizar si encaja. |
| `app.py` startup wiring | integrates | Arranque/parada en `on_startup`/`on_shutdown` (opcional, fase de wiring). |
| `AgentSchedulerManager` | coexists | Cron de reportes; el heartbeat es complementario, no lo toca. |

### Data Models

```python
# packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py
class HeartbeatConfig(BaseModel):
    agent_name: str
    interval: float = Field(60.0, gt=0, description="Seconds between ticks.")
    jitter: float = Field(0.0, ge=0, description="Max random seconds added to interval.")
    enabled: bool = True
    max_consecutive_errors: int = Field(5, ge=1)
    mission: Optional[str] = Field(default=None, description="Default prompt seed for act step.")

class HeartbeatState(BaseModel):
    agent_name: str
    running: bool = False
    tick_count: int = 0
    action_count: int = 0
    last_tick_at: Optional[datetime] = None
    last_action_at: Optional[datetime] = None
    consecutive_errors: int = 0
    last_error: Optional[str] = None
```

### New Public Interfaces

```python
# packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py

class HeartbeatStrategy(ABC):
    """Pluggable assess step (wake → assess → maybe act)."""
    @abstractmethod
    async def build_context(self, cfg: HeartbeatConfig) -> dict: ...
    @abstractmethod
    async def should_act(self, ctx: dict) -> bool: ...
    @abstractmethod
    async def build_prompt(self, ctx: dict) -> str: ...

class DefaultHeartbeatStrategy(HeartbeatStrategy):
    """Acts when a `has_pending_work` callable returns True, else every N ticks."""
    ...

class HeartbeatManager:
    def __init__(self, orchestrator: "AutonomousOrchestrator", *,
                 strategy: Optional[HeartbeatStrategy] = None) -> None: ...
    def register(self, cfg: HeartbeatConfig) -> None: ...
    async def start(self) -> None: ...           # spawn tasks
    async def stop(self) -> None: ...            # cancel tasks cleanly
    def get_state(self, agent_name: str) -> Optional[HeartbeatState]: ...
    def get_all_states(self) -> list[HeartbeatState]: ...
```

---

## 3. Module Breakdown

### Module 1: Heartbeat models & strategy
- **Path**: `packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py` (parte 1)
- **Responsibility**: `HeartbeatConfig`, `HeartbeatState` (Pydantic),
  `HeartbeatStrategy` (ABC) + `DefaultHeartbeatStrategy`.
- **Depends on**: nada nuevo.

### Module 2: HeartbeatManager (loop + lifecycle)
- **Path**: `packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py` (parte 2)
- **Responsibility**: `register`, `start/stop`, `_heartbeat_loop` (sleep+jitter,
  per-agent lock "skip si ocupado", backoff, manejo `CancelledError`),
  `get_state`/`get_all_states`. Actúa vía `orchestrator.execute_agent`.
- **Depends on**: Module 1; `AutonomousOrchestrator`.

### Module 3: Export & optional app wiring
- **Path**: `packages/ai-parrot-server/src/parrot/autonomous/__init__.py` (+ `app.py` opcional)
- **Responsibility**: Exportar `HeartbeatManager`/`HeartbeatConfig`/etc. Wiring
  opcional en `on_startup`/`on_shutdown` documentado (no obligatorio para tests).
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_heartbeat_config_defaults` | M1 | Defaults válidos; `interval>0`, `jitter>=0`. |
| `test_default_strategy_should_act` | M1 | `should_act` True cuando `has_pending_work`; False si no. |
| `test_manager_register_and_state` | M2 | `register` crea `HeartbeatState` con `running=False`. |
| `test_loop_ticks_and_acts` | M2 | Con `interval=0.05` y strategy que siempre actúa, tras X s hay N ticks y N acciones (orchestrator fake). |
| `test_loop_skips_when_busy` | M2 | Si un tick sigue corriendo, el siguiente se **salta** (lock); no se solapan. |
| `test_loop_backoff_on_error` | M2 | `execute_agent` que lanza → `consecutive_errors` sube; tras `max_consecutive_errors` se pausa el agente. |
| `test_stop_cancels_cleanly` | M2 | `stop()` cancela tasks sin excepción colgada (`CancelledError` manejado). |

### Integration Tests
| Test | Description |
|---|---|
| `test_heartbeat_drives_orchestrator` | `HeartbeatManager` real + `AutonomousOrchestrator` con un agent fake registrado → un tick llama `execute_agent` y registra acción. |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_orchestrator():
    class _Fake:
        def __init__(self): self.calls = []
        async def execute_agent(self, agent_name, task, **kw):
            self.calls.append((agent_name, task))
            return ExecutionResult(request_id="x", target_type=ExecutionTarget.AGENT,
                                   target_id=agent_name, success=True, result="ok")
    return _Fake()

@pytest.fixture
def always_act_strategy():
    # should_act -> True, build_prompt -> cfg.mission
    ...
```

---

## 5. Acceptance Criteria

> Esta feature está completa cuando TODO lo siguiente es cierto:

- [ ] `HeartbeatManager` corre un loop asyncio por agente con
  `interval`/`jitter`, y `stop()` cancela limpio (sin `CancelledError` colgado).
- [ ] El tick implementa **wake → assess → maybe act**: solo llama
  `execute_agent` cuando `strategy.should_act(ctx)` es True.
- [ ] **Skip si ocupado**: dos ticks de un mismo agente no se solapan (lock).
- [ ] Backoff: tras `max_consecutive_errors`, el agente se pausa y queda
  reflejado en `HeartbeatState.last_error`.
- [ ] `get_state`/`get_all_states` exponen tick/action counts y timestamps
  (base para `/health` y ledger).
- [ ] El heartbeat actúa vía `AutonomousOrchestrator.execute_agent`
  (no reimplementa ejecución de agentes).
- [ ] No interfiere con `AgentSchedulerManager` (cron) — coexisten.
- [ ] Tests: `pytest packages/ai-parrot-server/tests/ -k heartbeat -v` verde.
- [ ] Sin breaking changes en la API pública existente.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# Orchestrator (ai-parrot-server) — actuar en el tick:
from parrot.autonomous.orchestrator import (        # verified: autonomous/orchestrator.py
    AutonomousOrchestrator,                          # :112
    ExecutionResult,                                 # :98 (dataclass)
    ExecutionRequest,                                # :47 (dataclass)
    ExecutionTarget,                                 # :39 (Enum: AGENT/CREW/FLOW)
)
# Trigger primitives (core) — opcional, reusar TriggerMode.REACTIVE si encaja:
from parrot.autonomous import TriggerMode, AgentTriggerConfig  # verified: autonomous/__init__.py:7,13
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:                        # line 112
    def __init__(self, *, bot_manager=None, agent_registry=None,
                 scheduler_manager=None, redis_url=None, use_event_bus=True,
                 use_webhooks=True, default_user_id="autonomy_system",
                 default_session_prefix="auto_"):    # line 148
    async def start(self): ...                       # line 202
    async def stop(self): ...                        # line 239
    async def execute_agent(self, agent_name: str, task: str, *,
                            method_name=None, user_id=None, session_id=None,
                            **kwargs) -> ExecutionResult:   # line 358
    async def execute_crew(self, crew_id: str, task: str, *, ...) -> ExecutionResult  # line 393
    async def inject_job(self, ...) -> ...           # line 620

@dataclass
class ExecutionResult:                               # line 98
    request_id: str; target_type: ExecutionTarget; target_id: str
    success: bool; result: Any = None; error: Optional[str] = None
    execution_time_ms: float = 0.0; metadata: Dict = {}; completed_at: datetime

# packages/ai-parrot-server/src/parrot/autonomous/transport/filesystem/transport.py
async def _presence_loop(self) -> None:              # line 296  (REFERENCE PATTERN)
    while True:
        try:
            await asyncio.sleep(self._config.presence_interval)   # :300
            await self._registry.heartbeat(self._agent_id)        # :301
            await self._registry.gc_stale()                       # :302
        except asyncio.CancelledError:
            raise                                                 # :303-304
        except Exception as exc:
            logger.warning("Presence loop error: %s", exc)        # :305-306

# packages/ai-parrot/src/parrot/autonomous/scheduler.py
class TriggerMode(Enum):                             # line 9 — SCHEDULED/EVENT/WEBHOOK/REACTIVE/MANUAL
@dataclass
class AgentTriggerConfig:                            # line 19 (currently orphan — no real consumers)
@dataclass
class AutonomousJob:                                 # line 41 (currently orphan)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `HeartbeatManager._heartbeat_loop` | `AutonomousOrchestrator.execute_agent` | method call | `orchestrator.py:358` |
| `HeartbeatManager.start/stop` | `asyncio.create_task` + cancel | pattern | `transport.py:94,296` |
| `HeartbeatManager` | `ExecutionResult` | return inspection | `orchestrator.py:98` |

### Does NOT Exist (Anti-Hallucination)
- ~~`HeartbeatMonitor`, `AutonomousManager`, `CooldownManager`, `ReactiveExecutor`~~ — **NO existen** en el codebase (búsqueda repo-wide vacía). No referenciarlos.
- ~~`AutonomousOrchestrator.heartbeat()` / `.schedule_heartbeat()`~~ — no existen; el heartbeat es un manager nuevo y separado.
- ~~`parrot.autonomous.heartbeat`~~ — módulo nuevo de esta feature (no existe aún).
- ~~`AgentTriggerConfig`/`AutonomousJob` con consumidores~~ — existen como dataclasses pero **huérfanas** (solo reexport en `__init__.py`); no asumir que ya las usa el orchestrator.
- ~~`execute_agent(..., prompt=...)`~~ — el parámetro es `task: str` (posicional), no `prompt` (`orchestrator.py:358`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Espejar `_presence_loop` (`transport.py:296`): `while running: try/ sleep /
  work / except CancelledError: raise / except Exception: log+backoff`.
- async/await en todo; un `asyncio.Task` por agente; cancelación en `stop()`.
- Pydantic para `HeartbeatConfig`/`HeartbeatState`; estrategia como ABC inyectable.
- Logging con `self.logger`.
- "Skip si ocupado": `asyncio.Lock` por agente; `if lock.locked(): continue`.

### Known Risks / Gotchas
- **Heartbeat ≠ cron**: el valor está en el paso *assess* (`should_act`). Si la
  estrategia siempre actúa, degenera en cron (ya cubierto por
  `AgentSchedulerManager`). El default debe traer una condición real
  (`has_pending_work` o cada N ticks), no actuar incondicionalmente.
- **`execute_agent` toma `task` posicional**, no `prompt`.
- **Estado in-memory**: se pierde al reiniciar — aceptable aquí; la durabilidad la
  da el ledger (feature #4). Documentarlo.
- **No solapar con AgentSchedulerManager**: el heartbeat no registra jobs
  APScheduler; es un loop independiente.
- **Errores del tick no deben matar el loop**: capturar `Exception` (no
  `CancelledError`) y aplicar backoff.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (ninguno nuevo) | — | Reutiliza asyncio/pydantic ya presentes. |

---

## 8. Open Questions

> Resueltas por el usuario antes de redactar este spec:

- [x] ¿Qué hace el tick? — *Resuelto*: **wake → assess → maybe act** (paso de
  decisión `should_act`; solo actúa si lo amerita). Reflejado en §2 y G1/G4.
- [x] ¿Mecanismo del loop? — *Resuelto*: **loop asyncio propio
  (`HeartbeatManager`)**, espejo de `_presence_loop` — NO reusar APScheduler.
  Reflejado en §2/M2 y §6.

> Pendientes (decidibles en implementación):

- [ ] Default de `HeartbeatStrategy`: ¿condición `has_pending_work` (callable
  inyectado) o "actuar cada N ticks"? — *Owner: implementador M1* (preferencia:
  soportar ambos, callable opcional con fallback a N).
- [ ] ¿Wiring en `app.py` ahora o diferido a la feature #6 (operador)? — *Owner:
  usuario* (preferencia: exportar el manager ahora; wiring real con #6).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — M1→M2→M3 son secuenciales y comparten
  el mismo archivo `heartbeat.py`; sin paralelismo útil.
- **Cross-feature dependencies**: ninguna obligatoria. Independiente de FEAT-208.
  Las features #4 (ledger), #6 (operador) y #2 (voz proactiva) **consumirán** el
  estado/acciones del heartbeat más tarde, pero no son prerequisitos.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-31 | jesuslarag (via Claude) | Initial draft — heartbeat manager (own asyncio loop, wake→assess→maybe act) sobre AutonomousOrchestrator existente. |
