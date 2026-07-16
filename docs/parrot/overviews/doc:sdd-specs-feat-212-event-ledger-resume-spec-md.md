---
type: Wiki Overview
title: 'Feature Specification: Typed Event Ledger & Crash Resume'
id: doc:sdd-specs-feat-212-event-ledger-resume-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Un *agent harness* autónomo de servicio (inspirado en **aphelion**) escribe
  cada
relates_to:
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Typed Event Ledger & Crash Resume

**Feature ID**: FEAT-212
**Date**: 2026-05-31
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Un *agent harness* autónomo de servicio (inspirado en **aphelion**) escribe cada
evento significativo (ingress, turn, tool-call, grant, delivery) como **fila
tipada** en un ledger; tras un crash, **reanuda** desde el último estado
registrado en lugar de reinterpretar logs. Es la base de continuidad del harness
y la fuente de verdad de `/health` y `/status`.

Tras auditar el codebase, las **fuentes y patrones existen**, pero el ledger
persistente y el resume **no**:

- **Eventos tipados ya emitidos**: `LifecycleEvent` (clase base,
  `core/events/lifecycle/base.py:21`) con `to_dict()` JSON-safe (:52),
  `event_id` (:45), `timestamp` UTC (:46), `trace_context` (:44), `source_type`
  (:49). Hay **16 tipos concretos** (agent/invoke/client/tool/message), p. ej.
  `BeforeToolCallEvent`, `AfterToolCallEvent`, `ToolCallFailedEvent`,
  `BeforeInvokeEvent`/`AfterInvokeEvent`/`InvokeFailedEvent`.
- **Registro GLOBAL**: `get_global_registry()`
  (`core/events/lifecycle/global_registry.py:37`) → un `EventRegistry` singleton
  al que **se reenvían todos los eventos**; `EventRegistry.subscribe(event_type,
  callback)` (`registry.py:121`) permite suscribirse a `LifecycleEvent` y recibir
  todos.
- **Acceso a Postgres**: patrón `app["database"]` (asyncdb) + `async with await
  db.acquire() as conn` (visto en handlers y `manager/manager.py`).
- **Patrón de store async**: `SuspendedExecutionStore`
  (`ai-parrot-server/.../human/suspended_store.py:64`) — `save/load/delete`
  async con backend, modelo Pydantic serializado.
- **Orchestrator**: `AutonomousOrchestrator.start()`
  (`autonomous/orchestrator.py:202`), `inject_job(...)` (:620),
  `_execute(request)` (:799), `_execution_history` (solo memoria, :193).

**La brecha** (confirmada repo-wide): NO existe ledger append-only persistente,
ni replay/resume tras crash. `EventBus._event_history` y
`_execution_history` son **solo memoria (1000 máx)**; `SuspendedExecutionStore`
es checkpoint HITL (Redis/TTL), no un ledger.

### Goals

- **G1**: Tabla y modelos del ledger: `LedgerEvent` (Pydantic) persistido como
  fila tipada en **Postgres** (asyncdb vía `app["database"]`), append-only, con
  `seq` monótono, `event_class`, `event_data` (JSONB), `trace_id`, `timestamp`,
  `source_type`/`source_name`, `agent_id`, `status`.
- **G2**: `EventLedger` (store async, patrón `SuspendedExecutionStore`):
  `append(event)`, `read(filter)`, `last_state(agent_id)`, con backend
  `PostgresLedgerBackend` (append-only).
- **G3**: **Captura automática** suscribiéndose al **registro global** de
  lifecycle events (`get_global_registry().subscribe(LifecycleEvent, ...)`) →
  persiste TODOS los eventos sin instrumentar cada bot.
- **G4**: **Proyecciones de lectura** para observabilidad: `last_state(agent_id)`
  (última actividad, ejecuciones abiertas/cerradas) que alimentan `/health` y
  `/status` (FEAT-210) y registran grants (FEAT-211).
- **G5**: **Resume completo**: `EventLedger.find_incomplete()` + un
  `resume()` invocable desde `AutonomousOrchestrator.start()` que lee
  ejecuciones **abiertas** (un `Before*`/`Invoke` sin su `After*`/cierre) y las
  **re-encola** vía `inject_job(...)`.
- **G6**: Rendimiento: la captura no debe bloquear el hot-path del agente
  (escritura asíncrona / batched; el dual-emit a bus ya es fire-and-forget).
- **G7**: Tests verdes (con backend fake/SQLite-in-memory para CI) + cero
  regresiones.

### Non-Goals (explicitly out of scope)

- **Reescritura del sistema de eventos** (FEAT-176): se **consume** tal cual; no
  se modifican `LifecycleEvent` ni el `EventRegistry`.
- **Backend Redis del ledger**: el ledger es **Postgres append-only**. (Redis
  sigue siendo para EventBus pub/sub y SuspendedExecutionStore; no para el ledger.)
- **UI/dashboard del ledger**: las proyecciones se exponen vía API/comandos
  (FEAT-210), no una UI nueva.
- **Retención/rotación avanzada** (particionado, archivado a cold storage):
  fuera de alcance; solo un borrado/poda básico opcional.
- **Replay determinista de side-effects**: el resume **re-encola trabajo
  pendiente** (idempotencia es responsabilidad del agente/tool), no re-ejecuta
  efectos ya aplicados.
- **Persistir `ClientStreamChunkEvent`** (alta frecuencia): se **excluye** del
  ledger por defecto (filtro), para no inundarlo.

---

## 2. Architectural Design

### Overview

Un `LedgerRecorder` se suscribe al **registro global** de lifecycle events y, por
cada evento (salvo los filtrados, p. ej. stream chunks), construye un
`LedgerEvent` y lo persiste vía `EventLedger.append()` en Postgres (append-only,
`seq` monótono). Las proyecciones (`last_state`) se calculan por consulta sobre
la tabla. En el arranque, `AutonomousOrchestrator.start()` llama a un
`resume()` que detecta ejecuciones abiertas y las re-encola con `inject_job`.

```
[Agentes/Tools/Clients]
        │ emit LifecycleEvent
        ▼
EventRegistry (per-instance) ──forward──► GLOBAL EventRegistry
                                              │ subscribe(LifecycleEvent, recorder.on_event)
                                              ▼
                                    LedgerRecorder.on_event(evt)
                                              │ filter (skip stream chunks)
                                              ▼
                                    EventLedger.append(LedgerEvent)  ──► Postgres (append-only, seq)
                                              ▲
   /health,/status ── EventLedger.last_state(agent_id) ──────────────┘  (read projection)

App startup:
AutonomousOrchestrator.start() ──► resume(ledger):
        incomplete = ledger.find_incomplete()
        for exec in incomplete: orchestrator.inject_job(...)   # re-encola
```

### Component Diagram

```
LedgerRecorder ──subscribe──► get_global_registry()        (FEAT-176)
     │
     ├─ on_event(evt: LifecycleEvent) ─► LedgerEvent(**evt.to_dict())
     │                                       │
     ▼                                       ▼
EventLedger (ABC)  ◄──── PostgresLedgerBackend (asyncdb, app["database"])
     │  append() / read() / last_state() / find_incomplete()
     ▼
AutonomousOrchestrator.resume(ledger) ──► inject_job(...) per incomplete execution
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `get_global_registry()` (`lifecycle/global_registry.py:37`) | subscribes | El recorder se suscribe a `LifecycleEvent` una sola vez. |
| `EventRegistry.subscribe` (`lifecycle/registry.py:121`) | uses | `subscribe(LifecycleEvent, cb, where=...)`; `where` filtra stream chunks. |
| `LifecycleEvent.to_dict` (`lifecycle/base.py:52`) | uses | Serialización JSON-safe → `event_data` JSONB. |
| `app["database"]` (asyncdb) | uses | `async with await db.acquire() as conn` para append/read. |
| `SuspendedExecutionStore` (`suspended_store.py:64`) | mirrors | Patrón de store async (save/load) — referencia de estilo. |
| `AutonomousOrchestrator.start` (`orchestrator.py:202`) | modifies | Llama `resume(ledger)` al final del arranque (opcional/configurable). |
| `AutonomousOrchestrator.inject_job` (`orchestrator.py:620`) | uses | Re-encola ejecuciones incompletas durante el resume. |
| FEAT-211 grants | future-hook | `grant`/`revoke` se persisten como `GrantEvent` cuando ese código emita lifecycle events (o vía append directo). |
| FEAT-209 heartbeat / FEAT-210 operador | consumers | `last_state` alimenta `/health` y `/status`. |

### Data Models

```python
# packages/ai-parrot-server/src/parrot/autonomous/ledger.py
class LedgerEvent(BaseModel):
    seq: Optional[int] = None             # assigned by the store (monotonic)
    event_id: str                         # from LifecycleEvent.event_id
    event_class: str                      # type(evt).__name__
    trace_id: Optional[str] = None        # from trace_context
    source_type: str = ""                 # "agent" | "client" | "tool"
    source_name: str = ""
    agent_id: Optional[str] = None        # resolved from source_name/metadata
    timestamp: datetime
    event_data: dict                      # evt.to_dict() (JSONB)

    @classmethod
    def from_lifecycle(cls, evt) -> "LedgerEvent": ...

class LedgerConfig(BaseModel):
    enabled: bool = True
    exclude_event_classes: set[str] = {"ClientStreamChunkEvent"}
    batch_size: int = Field(50, ge=1)     # async batched writes
    table_name: str = "harness_ledger"
```

Postgres DDL (append-only):
```sql
CREATE TABLE IF NOT EXISTS harness_ledger (
    seq          BIGSERIAL PRIMARY KEY,
    event_id     UUID NOT NULL,
    event_class  TEXT NOT NULL,
    trace_id     TEXT,
    source_type  TEXT,
    source_name  TEXT,
    agent_id     TEXT,
    ts           TIMESTAMPTZ NOT NULL,
    event_data   JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_agent_ts  ON harness_ledger (agent_id, ts);
CREATE INDEX IF NOT EXISTS ix_ledger_trace     ON harness_ledger (trace_id);
CREATE INDEX IF NOT EXISTS ix_ledger_class     ON harness_ledger (event_class);
```

### New Public Interfaces

```python
# packages/ai-parrot-server/src/parrot/autonomous/ledger.py
class EventLedger(ABC):
    @abstractmethod
    async def append(self, event: LedgerEvent) -> int: ...        # returns seq
    @abstractmethod
    async def read(self, *, agent_id=None, since_seq=None,
                   event_class=None, limit=100) -> list[LedgerEvent]: ...
    @abstractmethod
    async def last_state(self, agent_id: str) -> "AgentLedgerState": ...
    @abstractmethod
    async def find_incomplete(self) -> list["IncompleteExecution"]: ...

class PostgresLedgerBackend(EventLedger):
    def __init__(self, db, *, config: LedgerConfig | None = None) -> None: ...
    async def ensure_schema(self) -> None: ...   # idempotent DDL

class LedgerRecorder:
    """Subscribes to the global lifecycle registry and persists events."""
    def __init__(self, ledger: EventLedger, *, config: LedgerConfig | None = None) -> None: ...
    def start(self) -> None: ...   # global_registry.subscribe(LifecycleEvent, self.on_event, where=...)
    def stop(self) -> None: ...    # unsubscribe
    async def on_event(self, evt) -> None: ...

# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py  (MODIFIED — additive)
class AutonomousOrchestrator:
    async def resume(self, ledger: EventLedger) -> int: ...   # re-enqueue incomplete; returns count
```

---

## 3. Module Breakdown

### Module 1: Ledger models + DDL
- **Path**: `packages/ai-parrot-server/src/parrot/autonomous/ledger.py`
- **Responsibility**: `LedgerEvent` (+ `from_lifecycle`), `LedgerConfig`,
  `AgentLedgerState`, `IncompleteExecution`. DDL idempotente.
- **Depends on**: `LifecycleEvent` (lectura).

### Module 2: EventLedger + Postgres backend
- **Path**: `ledger.py` (continuación)
- **Responsibility**: `EventLedger` (ABC) + `PostgresLedgerBackend`
  (`append`/`read`/`last_state`/`find_incomplete`/`ensure_schema`) usando
  `app["database"]` (asyncdb, `db.acquire()`).
- **Depends on**: Module 1.

### Module 3: LedgerRecorder (global capture)
- **Path**: `ledger.py` (continuación)
- **Responsibility**: suscripción al registro global con `where` que excluye
  `ClientStreamChunkEvent`; `on_event` mapea y persiste (batched, no bloqueante).
- **Depends on**: Modules 1-2; `get_global_registry`.

### Module 4: resume() en el orchestrator
- **Path**: `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py`
- **Responsibility**: `resume(ledger)` que lee `find_incomplete()` y re-encola
  vía `inject_job(...)`; llamada **opcional/configurable** al final de `start()`.
- **Depends on**: Module 2.

### Module 5: Wiring + exports
- **Path**: `autonomous/__init__.py` + doc de wiring en `app.py`
- **Responsibility**: exportar `EventLedger`/`PostgresLedgerBackend`/
  `LedgerRecorder`/`LedgerEvent`/`LedgerConfig`; wiring en `on_startup`
  (crear backend, `ensure_schema`, `recorder.start()`, `orchestrator.resume`).
- **Depends on**: Modules 1-4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ledgerevent_from_lifecycle` | M1 | Mapea un `BeforeToolCallEvent` a `LedgerEvent` (event_class, trace_id, event_data). |
| `test_backend_append_returns_seq` | M2 | `append` asigna `seq` monótono creciente (backend fake/sqlite). |
| `test_backend_read_filters` | M2 | `read(agent_id=, event_class=, since_seq=)` filtra correctamente. |
| `test_last_state_projection` | M2 | `last_state` reporta última actividad y ejecuciones abiertas/cerradas. |
| `test_find_incomplete` | M2 | `Before*`/`Invoke` sin su `After*` → aparece como incompleto; con cierre → no. |
| `test_recorder_skips_stream_chunks` | M3 | `ClientStreamChunkEvent` NO se persiste (filtro `where`). |
| `test_recorder_persists_on_emit` | M3 | Emitir un evento en el registro global → `append` llamado una vez. |
| `test_resume_reenqueues_incomplete` | M4 | `resume()` llama `inject_job` por cada ejecución incompleta. |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_capture` | Un agente fake emite Before/After tool events → quedan 2 filas en el ledger con el mismo trace_id. |
| `test_crash_resume_flow` | Sembrar ledger con una ejecución abierta (Before sin After), reiniciar (nuevo orchestrator), `resume()` re-encola exactamente esa. |
| `test_no_recorder_no_regression` | Sin `LedgerRecorder` activo, el flujo de agente/tools funciona idéntico (cero overhead funcional). |

### Test Data / Fixtures
```python
@pytest.fixture
def memory_ledger():
    # In-memory/sqlite EventLedger impl for fast CI (no real Postgres).
    ...

@pytest.fixture
def fake_orchestrator():
    m = MagicMock()
    m.inject_job = AsyncMock(return_value="job-1")
    return m
```

---

## 5. Acceptance Criteria

> Esta feature está completa cuando TODO lo siguiente es cierto:

- [ ] `LedgerEvent.from_lifecycle` mapea cualquier `LifecycleEvent` (vía
  `to_dict()`), preservando `event_id`, `trace_id`, `timestamp`, `source_*`.
- [ ] `PostgresLedgerBackend` es **append-only** con `seq` monótono y
  `ensure_schema()` idempotente sobre `app["database"]`.
- [ ] `LedgerRecorder` se suscribe al **registro global** y persiste todos los
  eventos **excepto** `ClientStreamChunkEvent` (filtro).
- [ ] `last_state(agent_id)` provee proyección consumible por `/health`/`/status`.
- [ ] `find_incomplete()` detecta ejecuciones abiertas (sin evento de cierre).
- [ ] `AutonomousOrchestrator.resume(ledger)` re-encola las incompletas vía
  `inject_job` y devuelve el conteo.
- [ ] La captura **no bloquea** el hot-path del agente (escritura async/batched).
- [ ] **Aditivo**: sin recorder/ledger configurado, el sistema funciona idéntico
  (sin tocar `LifecycleEvent`/`EventRegistry`).
- [ ] Tests: `pytest packages/ai-parrot-server/tests/ -k ledger -v` verde (backend
  fake/sqlite; sin requerir Postgres real en CI).
- [ ] Sin breaking changes en la API pública existente.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.core.events.lifecycle.base import LifecycleEvent          # verified: lifecycle/base.py:21
from parrot.core.events.lifecycle.global_registry import get_global_registry  # verified: global_registry.py:37
from parrot.core.events.lifecycle.registry import EventRegistry       # verified: registry.py:90
from parrot.core.events.lifecycle.events import (                     # verified: events/__init__.py
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,     # :33,34,35
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,           # :19,20,21
    ClientStreamChunkEvent,                                           # :27 (EXCLUDE from ledger)
)
# Orchestrator (resume):
from parrot.autonomous.orchestrator import AutonomousOrchestrator, ExecutionRequest  # orchestrator.py:112,47
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py
@dataclass(frozen=True)
class LifecycleEvent(ABC):                       # line 21
    trace_context: TraceContext                  # line 44
    event_id: str = <uuid4>                       # line 45
    timestamp: datetime = <utcnow>                # line 46
    source_type: str = ""                         # line 49
    source_name: str = ""
    def to_dict(self) -> dict[str, Any]: ...      # line 52 (JSON-safe, adds "event_class")

# packages/ai-parrot/src/parrot/core/events/lifecycle/global_registry.py
def get_global_registry() -> EventRegistry: ...   # line 37 (singleton, forward_to_global=False)

# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py
class EventRegistry:                              # line 90
    def subscribe(self, event_type: Type[E], callback: AsyncSubscriber, *,
                  where: Optional[Callable[[E], bool]] = None,
                  forward_to_bus: bool = False) -> str: ...    # line 121 (returns subscription_id)
    # callback signature: Callable[[LifecycleEvent], Awaitable[None]]
    # emit() NEVER raises; subscriber exceptions are isolated (no veto)

# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:                     # line 112
    async def start(self): ...                    # line 202 (resume() hook goes here)
    async def inject_job(self, ...) -> ...        # line 620 (re-enqueue mechanism)
    async def _execute(self, request: ExecutionRequest) -> ExecutionResult:  # line 799
    self._execution_history: List[ExecutionResult]  # line 193 (in-memory only — NOT the ledger)
    def get_execution_history(self, limit=...) -> ...  # line 1196

# packages/ai-parrot-server/src/parrot/human/suspended_store.py
class SuspendedExecutionStore:                    # line 64 (async store pattern to mirror)
    async def save(self, record, ttl: int) -> None
    async def load(self, interaction_id: str) -> Optional[...]
    async def delete(self, interaction_id: str) -> None

# DB access pattern (verified in handlers + manager/manager.py):
#   db = app["database"]                          # asyncdb instance
#   async with await db.acquire() as conn: ...    # connection from pool
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LedgerRecorder.start` | `get_global_registry().subscribe(LifecycleEvent, ...)` | subscription | `global_registry.py:37` + `registry.py:121` |
| `LedgerEvent.from_lifecycle` | `LifecycleEvent.to_dict()` | serialization | `base.py:52` |
| `PostgresLedgerBackend` | `app["database"]` + `db.acquire()` | asyncdb conn | handlers / `manager.py` |
| `resume()` | `AutonomousOrchestrator.inject_job` | method call | `orchestrator.py:620` |
| `resume()` call site | `AutonomousOrchestrator.start` | inline (additive) | `orchestrator.py:202` |

### Does NOT Exist (Anti-Hallucination)
- ~~ledger / journal / audit log / event_store persistente, replay, resume()~~ — **NO existen** (confirmado repo-wide). Los crea esta feature.
- ~~`AutonomousOrchestrator.resume()` / `recover()`~~ — NO existe; lo añade M4.
- ~~`EventBus._event_history` / `_execution_history` como ledger~~ — son **solo memoria** (1000 máx), NO persistentes; no usarlos como fuente de resume.
- ~~Pydantic `LifecycleEvent`~~ — es un `@dataclass(frozen=True)`, NO Pydantic; usar `to_dict()` (no `.model_dump()`).
- ~~`AbstractStore` (parrot/stores) para el ledger~~ — es para vector stores; NO es el patrón del ledger. Usar asyncdb directo + patrón `SuspendedExecutionStore`.
- ~~persistir `ClientStreamChunkEvent`~~ — explícitamente EXCLUIDO (alta frecuencia).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Store async estilo `SuspendedExecutionStore` (save/load async, logger).
- Acceso DB: `db = app["database"]; async with await db.acquire() as conn`.
- Suscripción única al registro global con `where=lambda e: type(e).__name__ not
  in config.exclude_event_classes` (evita stream chunks).
- `LifecycleEvent` es dataclass frozen → usar `to_dict()` (NO `.model_dump()`).
- Escritura no bloqueante: cola interna + tarea de flush batched, para respetar
  el budget de overhead del hot-path (FEAT-176/177).
- Cambio **aditivo** en el orchestrator: `resume()` separado; `start()` lo llama
  solo si se le pasó un ledger (o `resume_on_start=True`).

### Known Risks / Gotchas
- **`LifecycleEvent` NO es Pydantic** (es frozen dataclass): serializar con
  `to_dict()`. `LedgerEvent` (Pydantic) envuelve `event_data=evt.to_dict()`.
- **Volumen**: sin excluir `ClientStreamChunkEvent` el ledger se inunda. Filtro
  obligatorio; `batch_size` configurable.
- **Definición de "ejecución incompleta"**: correlación por `trace_id` —
  un `BeforeInvokeEvent`/`Before*` sin su `After*`/`*Failed`. Documentar el
  criterio exacto y cubrir el caso de eventos perdidos por crash a mitad.
- **Idempotencia del resume**: re-encolar puede re-ejecutar efectos; el resume
  re-encola **trabajo**, no replica side-effects. La idempotencia es del agente.
- **CI sin Postgres**: proveer un backend in-memory/sqlite para tests; no exigir
  Postgres real.
- **Orden y `seq`**: append-only con `BIGSERIAL`; las lecturas ordenan por `seq`.
- **Suscripción al registro global**: una sola instancia de `LedgerRecorder` por
  proceso (evitar duplicar filas con múltiples suscripciones).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncdb` | (ya presente) | Acceso async a Postgres vía `app["database"]`. |
| (sqlite/aiosqlite para tests) | opcional | Backend fake en CI; o un in-memory puro. |

---

## 8. Open Questions

> Resueltas por el usuario antes de redactar este spec:

- [x] ¿Backend del ledger? — *Resuelto*: **Postgres desde el inicio** (resume
  real). Reflejado en G1/G2/M2 y Non-Goals (no Redis para el ledger).
- [x] ¿Qué eventos persiste? — *Resuelto*: **suscripción global a
  `LifecycleEvent`** (todos), excluyendo `ClientStreamChunkEvent`. Reflejado en
  G3/M3 y §6.
- [x] ¿Alcance del resume? — *Resuelto*: **resume() completo ahora** en
  `AutonomousOrchestrator.start()` re-encolando vía `inject_job`. Reflejado en
  G5/M4 y §5.

> Pendientes (decidibles en implementación):

- [ ] Resolución de `agent_id` desde el evento: `source_name` directo vs
  metadata/trace correlation — *Owner: implementador M1*.
- [ ] Criterio exacto de "ejecución incompleta" y manejo de eventos a medias por
  crash (¿ventana de gracia por `seq`/timestamp?) — *Owner: implementador M2/M4*.
- [ ] ¿`resume()` automático en `start()` por defecto o solo bajo
  `resume_on_start=True`? — *Owner: usuario* (preferencia del spec: opt-in
  configurable).: deberia ser opt-in configurable

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — M1→M5 secuenciales; M1-M3 comparten
  `ledger.py`, M4 toca `orchestrator.py`. Sin paralelismo útil.
- **Cross-feature dependencies**: **sinergia** con FEAT-209 (heartbeat: emite/
  consume estado), FEAT-210 (`/health`,`/status` consumen `last_state`), FEAT-211
  (grants: `grant`/`revoke` como eventos del ledger; habilita resume de grants).
  No hay merge-blockers duros — el ledger es aditivo y degradable.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-31 | jesuslarag (via Claude) | Initial draft — Postgres append-only ledger via global lifecycle subscription + resume() re-enqueue en AutonomousOrchestrator. |
