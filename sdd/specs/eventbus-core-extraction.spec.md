---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: EventBus Core Extraction → `navigator-eventbus`

**Feature ID**: FEAT-312
**Date**: 2026-07-17
**Author**: Jesus (phenobarbital) + Claude
**Status**: approved
**Target version**: `navigator-eventbus` 0.1.0

> **Fase 1 de 5** del plan de extracción definido en
> `sdd/proposals/navigator-eventbus-extraction.brainstorm.md` (Opción B —
> extracción por fases). Fases siguientes: `eventbus-lifecycle-extraction` (2),
> `eventbus-brokers-port` (3), `parrot-eventbus-migration` (4),
> `navigator-brokers-removal` (5).
>
> **Repo de implementación**: `/home/jesuslara/proyectos/navigator-eventbus`
> (hoy vacío: solo README + LICENSE). Este spec y sus tasks viven en ai-parrot
> (base `dev`) como artefactos SDD; el código se escribe en el repo destino,
> en rama creada desde su `main`.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-310 entregó el EventBus v2 completo (envelope unificado, dispatcher con
worker pool O(1)-publish, backends memory/pubsub/streams, DLQ, subscribers de
notificación/audit/metrics, ingress WS+gRPC, `route_to_bus` en HookManager) —
pero **vive dentro de ai-parrot** (`packages/ai-parrot/src/parrot/core/events/`
+ `parrot/core/hooks/`). Flowtask, QuerySource y navigator-auth necesitan el
mismo fabric de eventos, y hoy sus opciones son inaceptables: depender de
ai-parrot entero (arrastra LLM clients, bots, loaders) o duplicar el código.
El repo destino `navigator-eventbus` existe pero está vacío.

Esta fase extrae el **bus core + hooks genéricos** (~5.5k LOC + tests) al
paquete standalone, con los desacoples necesarios para que el paquete sea
neutral (cero imports de `parrot.*`).

### Goals

- Scaffold del paquete `navigator-eventbus`: src-layout
  `src/navigator_eventbus/`, `pyproject.toml` gestionado con `uv`,
  import plano `navigator_eventbus`, versión inicial **0.1.0**, destino
  **PyPI público** (publicación al final de la fase 4, cuando la suite de
  ai-parrot pase completa).
- CI con GitHub Actions replicando la infra de navigator y ai-parrot
  (pytest + ruff + mypy) desde esta fase.
- Mudanza (copia fresca, sin historia git; el commit inicial referencia el
  SHA de origen en ai-parrot) del bus core: envelope, BusCore, backends,
  converters, DLQ, ingress models, subscribers, ingress WS/gRPC, facade
  `evb.py`, y los hooks genéricos (base, manager, models, mixins,
  scheduler, file_watchdog, hooks de brokers).
- Desacoples de neutralidad: `HookType` pasa a **tipo abierto** (str
  validado + registry); prefijos Redis con **default neutro** y override
  per-app; DSN vía parámetro/navconfig (sin `parrot.conf`); `lazy_import`
  local; serialización **JSON vía `JSONContent` (orjson)** con cloudpickle
  opcional.
- `TOPICS.md` (governanza de namespaces de topics) nace en el repo nuevo
  con esta fase.
- API pública preservada: `EventBus.emit/subscribe/on/publish` y
  `HookManager.set_event_bus/route_to_bus` mantienen firma — solo cambia el
  módulo de origen.
- La rama `copilot/complete-event-bus-implementation` del repo destino se
  **borra** (FEAT-310 es la fuente canónica).

### Non-Goals (explicitly out of scope)

- Maquinaria lifecycle (`LifecycleEvent`, `TraceContext`, `EventRegistry`,
  mixin, yaml_loader wiring engine) — **fase 2**. La decisión de mover el
  motor de wiring de `yaml_loader` al paquete (con tabla de eventos
  inyectable) está tomada, pero se ejecuta en la fase 2 porque el módulo
  vive en `events/lifecycle/`.
- Port de `navigator.brokers` + fixes PR navigator#393 — **fase 3**.
- Migración de imports en ai-parrot (borrado del código origen) — **fase 4**.
  Durante esta fase ai-parrot NO cambia: sigue usando su copia.
- Eliminación de `navigator/brokers/` en navigator — **fase 5**.
- Capa de shims/compat (`parrot-events-compat`): rechazada en brainstorm
  (Opción C) — migración dura decidida.
- Consolidación de los dos consumers de Redis Streams (brokers vs bus):
  spec propio post-migración (`eventbus-streams-consolidation`).
- Publicación efectiva a PyPI: se hace al cierre de la fase 4; durante el
  desarrollo la distribución es editable local (`uv pip install -e`).

---

## 2. Architectural Design

### Overview

Se crea el paquete `navigator-eventbus` (repo standalone, peer de `navigator`
y `asyncdb`) y se muda el bus core de FEAT-310 tal cual, aplicando solo los
desacoples que eliminan las referencias a `parrot.*`. Diseño de módulos,
algoritmos y semántica (worker pool, backpressure, DLQ, meta-events,
severidad, at-least-once en Streams) **no cambian** — este spec es una
mudanza con desacoples, no un rediseño.

Decisiones de diseño ya resueltas (brainstorm, no re-abrir):

1. **Import name**: `navigator_eventbus` plano. `navigator.eventbus` vía
   PEP 420 es inviable (`navigator/__init__.py` es paquete regular).
2. **`HookType` abierto**: deja de ser `str, Enum` cerrado. Pasa a tipo
   abierto — un `str` validado contra un **registry de hook types** con
   registro dinámico. **[AMENDED 2026-07-17 post-implementation, ver
   Revision History]**: el paquete pre-registra en `HOOK_TYPES`, a import
   time, los **18 hook types del enum cerrado pre-FEAT-312** (los 10
   genéricos originales: scheduler, file_watchdog, postgres_listen,
   imap_watchdog, file_upload, broker_redis, broker_rabbitmq, broker_mqtt,
   broker_sqs, filesystem; más los 8 específicos de ai-parrot: jira_webhook,
   github_webhook, sharepoint, telegram, whatsapp, msteams, whatsapp_redis,
   matrix) **más** el nuevo genérico `webhook` que introduce el paquete —
   compatibilidad retro total con FEAT-310, cero wiring de registro
   necesario para reproducir su comportamiento. Cualquier app puede seguir
   registrando dinámicamente tipos NUEVOS (no incluidos en esos 18+1) via
   `HOOK_TYPES.register(...)` a su propio import time — el registry sigue
   siendo abierto, solo cambia qué viene pre-poblado de fábrica.
   `HookEvent.hook_type` y los config models pasan a `str` validado.
3. **`hooks/models.py` se muda entero**: modelos genéricos Y configs de
   integraciones (Jira/GitHub/SharePoint/WhatsApp/Matrix) viajan al paquete
   — son modelos de datos, no lógica de integración. Las apps los importan
   de `navigator_eventbus.hooks.models`.
4. **Prefijos Redis neutros**: defaults del paquete `evb:events:` /
   `evb:stream:` / `evb:events:dedup:` y consumer-group `evb-bus`,
   configurables por constructor y navconfig. (ai-parrot fijará los valores
   legacy `parrot:*` / `parrot-bus` en la fase 4 para no romper streams
   desplegados — fuera de alcance aquí, pero el knob debe existir.)
5. **Config**: navconfig es dependencia directa (estandarización del
   ecosistema). Las claves `BUS_*` existentes se conservan.
6. **DSN de DLQ/audit**: parámetro explícito con fallback a navconfig —
   se elimina el lazy-import de `parrot.conf.default_dsn`.
7. **Serialización**: JSON por defecto vía `JSONContent` de
   `datamodel.parsers.json` (orjson). cloudpickle/msgpack quedan como
   serialización opcional (extra) — relevante desde la fase 3 (brokers),
   pero el helper de serialización del core nace ya sobre `JSONContent`.
8. **NotificationSubscriber en el core** con sender por defecto sobre la
   librería `notify` (async-notify, extra `[notify]`); sigue aceptando
   senders inyectados duck-typed.
9. **Observability bootstrap**: el bus core NO importa
   `parrot.observability` (ese acople está en `lifecycle/mixin.py`, fase 2).
   En esta fase no hay nada que desacoplar al respecto.
10. **`lazy_import`**: `hooks/scheduler.py` importa `parrot._imports.lazy_import`
    — se replica como util local `navigator_eventbus._imports.lazy_import`.

### Component Diagram

```
navigator-eventbus (repo standalone, src-layout)
└── src/navigator_eventbus/
    ├── __init__.py            # re-exporta EventBus, Event, EventPriority,
    │                          #   EventSubscription, EventEnvelope, Severity, BusCore
    ├── _imports.py            # lazy_import local (replica parrot._imports)
    ├── envelope.py            # EventEnvelope (frozen dataclass) + Severity
    ├── core.py                # BusCore: colas por prioridad, workers, backpressure
    ├── evb.py                 # facade EventBus/Event/EventPriority/EventSubscription
    ├── converters.py          # Event↔EventEnvelope, HookEvent→EventEnvelope
    ├── dlq.py                 # DLQHandler (asyncdb, DSN param/navconfig)
    ├── ingress_models.py      # IngressEnvelope (Pydantic, boundary validation)
    ├── serialization.py       # JSONContent (orjson) default; cloudpickle opcional
    ├── backends/              # base (TransportBackend Protocol), memory,
    │   │                      #   redis_pubsub, redis_streams
    │   └── ...                # prefijos neutros evb:* configurables
    ├── subscribers/           # notification (sender notify default), audit, metrics
    ├── ingress/               # websocket, grpc, proto/ (+ __init__.py que hoy falta)
    └── hooks/                 # base (HookRegistry, BaseHook), manager (HookManager),
        │                      #   models (HookEvent + configs, hook_type abierto),
        │                      #   registry de hook types, mixins, scheduler,
        │                      #   file_watchdog
        └── brokers/           # base, redis, rabbitmq, sqs, mqtt (lazy imports;
                               #   en fase 1 siguen apuntando a navigator.brokers,
                               #   la fase 3 los recablea a la capa interna)
TOPICS.md                      # registro de namespaces (bus.*, hooks.*, lifecycle.*,
                               #   agent.*, task.*, auth.* — ownership por app)
.github/workflows/ci.yml       # pytest + ruff + mypy (matriz replicada de ai-parrot)
```

Flujo interno (sin cambios respecto a FEAT-310):

```
emit()/publish() ──O(1) enqueue──▶ per-priority asyncio.Queue
                                        │ worker pool (TaskGroup)
                                        ▼
                    match (glob + severity + filter_fn) ──▶ handlers (timeout,
                                        │                    retry, aislamiento B)
                                        ├─▶ bus.subscriber_error / bus.dlq (meta)
                                        └─▶ TransportBackend.publish (memory |
                                             redis_pubsub | redis_streams)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/core/events/bus/` (ai-parrot, FEAT-310) | source de la mudanza | copia fresca; origen queda intacto y **congelado** (freeze) hasta la fase 4 |
| `parrot/core/events/evb.py` | source de la mudanza | facade se muda tal cual; preservar orden de import lazy evb↔bus |
| `parrot/core/hooks/{base,manager,models,mixins,scheduler,file_watchdog}.py` + `brokers/*` | source de la mudanza | hooks genéricos; los hooks de integración parrot (jira, github, sharepoint, whatsapp, matrix, imap, messaging, postgres, file_upload) NO se mudan |
| `navconfig` | dependencia directa | config + logging del core; claves `BUS_*` conservadas |
| `asyncdb` | dependencia directa | persistencia DLQ (`navigator.evb_dlq`) y audit (`navigator.evb_audit`) |
| `datamodel.parsers.json.JSONContent` | dependencia (vía datamodel) | serializador JSON default (orjson) |
| `notify` (async-notify) | extra `[notify]` | sender por defecto de NotificationSubscriber |
| `redis.asyncio` | extra `[redis]` | backends pubsub/streams |
| `grpcio`/`grpcio-tools` | extra `[grpc]` | ingress gRPC |
| `aiohttp` | dependencia directa | ingress WS + webhook egress + consumers |
| `navigator.brokers` (framework navigator) | lazy-import temporal | los hooks de brokers siguen lazy-importándolo en fase 1; la fase 3 los recablea |
| Flowtask / QuerySource / navigator-auth | future consumers | pueden adoptar el paquete (editable) al cerrar esta fase |

### Data Models

Sin modelos nuevos — se mudan los existentes. Cambio de contrato único:

```python
# ANTES (parrot/core/hooks/models.py:9) — enum cerrado
class HookType(str, Enum):
    SCHEDULER = "scheduler"; ...  # 18 miembros, incl. parrot-específicos

# DESPUÉS (navigator_eventbus/hooks/models.py) — tipo abierto + registry
class HookTypeRegistry:
    """Registro dinámico de hook types. El paquete pre-registra los 18
    legacy (10 genéricos + 8 específicos de ai-parrot) + `webhook`
    (AMENDED, v0.2); cada app puede registrar tipos NUEVOS en import-time."""
    def register(self, name: str) -> str: ...      # valida slug, idempotente
    def is_registered(self, name: str) -> bool: ...
    def all(self) -> frozenset[str]: ...

HOOK_TYPES = HookTypeRegistry()  # singleton de módulo, pre-poblado con los 18 legacy + webhook

class HookEvent(BaseModel):
    hook_type: str  # validado contra HOOK_TYPES (validator Pydantic)
    ...             # resto de campos sin cambio
```

### New Public Interfaces

Ninguna interfaz nueva de comportamiento — el paquete re-expone la API de
FEAT-310 bajo el nuevo import root:

```python
from navigator_eventbus import EventBus, Event, EventPriority, EventSubscription
from navigator_eventbus import EventEnvelope, Severity, BusCore
from navigator_eventbus.backends import MemoryBackend, RedisStreamsBackend
from navigator_eventbus.subscribers import NotificationSubscriber, AuditSubscriber
from navigator_eventbus.hooks import HookManager, BaseHook, HookRegistry
from navigator_eventbus.hooks.models import HookEvent, HOOK_TYPES
```

Nuevos knobs de configuración (constructor + navconfig):

```python
# Prefijos neutros con override:
EventBus(channel_prefix="evb:events:")                       # default nuevo
RedisStreamsBackend(stream_prefix="evb:stream:",
                    dedup_prefix="evb:events:dedup:",
                    group="evb-bus")                          # defaults nuevos
# navconfig: BUS_CHANNEL_PREFIX, BUS_STREAM_PREFIX, BUS_DEDUP_PREFIX, BUS_GROUP
```

---

## 3. Module Breakdown

### Module 1: Package scaffold + CI
- **Path**: repo `navigator-eventbus` — `pyproject.toml`, `src/navigator_eventbus/__init__.py`, `.github/workflows/ci.yml`, `README.md`, `TOPICS.md`
- **Responsibility**: src-layout uv-managed, versión 0.1.0, extras
  `[redis][grpc][notify][scheduler][watchdog][mqtt]`, CI pytest+ruff+mypy
  replicando la matriz de ai-parrot/navigator; `TOPICS.md` con el vocabulario
  base (`bus.*` meta-topics, `hooks.*`, reserva de `lifecycle.*`, `agent.*`,
  `task.*`, `auth.*`); borrado de la rama copilot del repo destino.
- **Depends on**: —

### Module 2: Envelope + serialization
- **Path**: `src/navigator_eventbus/{envelope,serialization,_imports}.py`
- **Responsibility**: mudar `EventEnvelope`/`Severity` sin cambios;
  helper de serialización sobre `JSONContent` (orjson) con hook opcional
  cloudpickle; util `lazy_import` local.
- **Depends on**: Module 1

### Module 3: BusCore + facade + converters + DLQ
- **Path**: `src/navigator_eventbus/{core,evb,converters,dlq,ingress_models}.py`
- **Responsibility**: mudar dispatcher, facade `EventBus` (misma firma,
  `channel_prefix` configurable con default `evb:events:`), converters
  (import de `HookEvent` pasa a intra-paquete), DLQ con DSN
  parámetro/navconfig (fuera `parrot.conf`). Preservar el orden de import
  lazy evb↔bus documentado en el contrato.
- **Depends on**: Module 2

### Module 4: Transport backends
- **Path**: `src/navigator_eventbus/backends/{base,memory,redis_pubsub,redis_streams}.py`
- **Responsibility**: mudar los tres backends + protocol; prefijos y
  consumer-group neutros configurables (constructor + navconfig).
- **Depends on**: Module 2

### Module 5: Subscribers
- **Path**: `src/navigator_eventbus/subscribers/{notification,audit,metrics}.py`
- **Responsibility**: mudar los tres; `NotificationSubscriber` gana sender
  por defecto sobre `notify` (extra `[notify]`, lazy) manteniendo el sender
  inyectado duck-typed; `AuditSubscriber` con DSN parámetro/navconfig.
- **Depends on**: Module 3

### Module 6: Hooks genéricos + HookType registry
- **Path**: `src/navigator_eventbus/hooks/{base,manager,models,mixins,scheduler,file_watchdog}.py` + `hooks/brokers/{base,redis,rabbitmq,sqs,mqtt}.py`
- **Responsibility**: mudar HookRegistry/BaseHook/HookManager/mixins/
  scheduler/file_watchdog y los hooks de brokers (lazy-imports a
  `navigator.brokers` intactos en esta fase); `models.py` entero con
  `hook_type` abierto + `HookTypeRegistry` (18 legacy + `webhook`
  pre-registrados — AMENDED v0.2; documentar el registro per-app para
  tipos NUEVOS); `scheduler.py` usa `_imports.lazy_import` local.
- **Depends on**: Module 3

### Module 7: Ingress WS/gRPC
- **Path**: `src/navigator_eventbus/ingress/{websocket,grpc}.py` + `ingress/proto/`
- **Responsibility**: mudar ambos ingress (imports pasan a intra-paquete);
  añadir el `__init__.py` que falta en `proto/`; regenerar/ajustar los
  stubs `events_pb2*` al nuevo package path.
- **Depends on**: Modules 3, 6 (BaseHook)

### Module 8: Test suite migration
- **Path**: `tests/` del repo navigator-eventbus
- **Responsibility**: mudar la suite del bus de ai-parrot
  (`packages/ai-parrot/tests/core/events/` — porción bus/hooks genéricos),
  adaptar imports, añadir tests nuevos: HookTypeRegistry (registro dinámico,
  validación, rechazo de no-registrados), prefijos configurables, helper de
  serialización JSONContent, `grep`-guard de neutralidad (cero `parrot.`
  en `src/`).
- **Depends on**: Modules 2–7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| suite FEAT-310 mudada (envelope, core, backends, dlq, converters, subscribers, ingress, hooks) | 2–7 | misma cobertura que en ai-parrot, imports `navigator_eventbus.*` |
| `test_hook_type_registry_generic_prepopulated` | 6 | los genéricos están registrados al importar |
| `test_hook_type_registry_register_custom` | 6 | una app registra `jira_webhook` y HookEvent lo acepta |
| `test_hook_event_rejects_unregistered_type` | 6 | `hook_type` no registrado → ValidationError |
| `test_bus_prefixes_default_neutral` | 3, 4 | defaults `evb:events:`/`evb:stream:`/`evb-bus` |
| `test_bus_prefixes_override` | 3, 4 | constructor y navconfig permiten `parrot:*` |
| `test_serialization_jsoncontent_roundtrip` | 2 | envelope → JSON (orjson) → envelope |
| `test_dlq_dsn_explicit_param` | 3 | DSN por parámetro sin tocar navconfig |
| `test_no_parrot_imports` | 8 | `grep -r "from parrot\|import parrot" src/` → vacío |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_memory_bus` | emit → workers → subscriber, MemoryBackend (mudado) |
| `test_redis_streams_roundtrip` | XADD/XREADGROUP/ACK con prefijos custom (marcado `redis`, skip sin servidor) |
| `test_hookmanager_route_to_bus` | HookManager publica `hooks.<type>.<event>` (mudado) |

### Test Data / Fixtures

```python
# Se mudan las fixtures existentes de la suite del bus; nuevas:
@pytest.fixture
def custom_hook_type():
    """Registra un hook type de prueba y lo desregistra al terminar."""
    name = HOOK_TYPES.register("test_custom_hook")
    yield name
    # registry expone limpieza para tests (o registry por-test)
```

---

## 5. Acceptance Criteria

- [ ] Repo `navigator-eventbus` con src-layout `src/navigator_eventbus/`,
      `pyproject.toml` uv, versión `0.1.0`, extras
      `[redis][grpc][notify][scheduler][watchdog][mqtt]`.
- [ ] `uv pip install -e .` funciona en un venv limpio y
      `from navigator_eventbus import EventBus, EventEnvelope, Severity` resuelve.
- [ ] **Cero imports de `parrot.*`** en `src/navigator_eventbus/`
      (verificado por test `test_no_parrot_imports` + grep en CI).
- [ ] API pública preservada: `EventBus.emit/subscribe/on/publish`,
      `HookManager.set_event_bus/route_to_bus` con las mismas firmas que en
      FEAT-310 (diff de firmas documentado = vacío).
- [ ] `__init__.py` re-exporta al menos `EventBus, Event, EventPriority,
      EventSubscription` (paridad con `parrot.core.events.__all__`).
- [ ] `HookType` reemplazado por tipo abierto: `HookTypeRegistry` con los
      18 hook types legacy (10 genéricos + 8 específicos de ai-parrot) más
      el nuevo genérico `webhook` pre-registrados a import time (AMENDED,
      ver Revision History); `HookEvent.hook_type: str` validado; registro
      dinámico de tipos nuevos probado.
- [ ] Prefijos Redis y consumer-group con defaults neutros (`evb:*`,
      `evb-bus`) y override por constructor + navconfig
      (`BUS_CHANNEL_PREFIX`, `BUS_STREAM_PREFIX`, `BUS_DEDUP_PREFIX`, `BUS_GROUP`).
- [ ] DLQ y AuditSubscriber aceptan DSN por parámetro con fallback navconfig;
      sin referencia a `parrot.conf`.
- [ ] Serialización default vía `JSONContent` (orjson); cloudpickle opcional
      documentado (extra), no requerido.
- [ ] `ingress/proto/` contiene `__init__.py`; import del módulo gRPC
      funciona con el extra `[grpc]`.
- [ ] Suite de tests mudada y verde en el repo nuevo: `pytest tests/ -v`.
- [ ] CI GitHub Actions verde (pytest + ruff + mypy) en el primer PR.
- [ ] `TOPICS.md` presente con namespaces base y convención de registro.
- [ ] Rama `copilot/complete-event-bus-implementation` eliminada del repo.
- [ ] Commit inicial del código mudado referencia el SHA de origen de
      ai-parrot (dev) del que se copió.
- [ ] ai-parrot intacto: esta fase no modifica ningún archivo de
      `packages/ai-parrot/` (freeze declarado de `parrot/core/events|hooks`).
- [ ] Performance: benchmark de emit-overhead (script
      `scripts/bench/feat310_emit_overhead.py` adaptado al paquete) sin
      regresión vs FEAT-310 (misma máquina, ±ruido).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Fuente de la mudanza: `packages/ai-parrot/src/parrot/core/` en ai-parrot,
> rama `dev` post-FEAT-310. Referencias re-verificadas 2026-07-17.

### Verified Imports

```python
# Origen (ai-parrot) — el código que se copia:
from parrot.core.events import EventBus, Event, EventPriority, EventSubscription
#   __all__ = ["EventBus", "Event", "EventPriority", "EventSubscription"]  (events/__init__.py)
from parrot.core.events.bus.envelope import EventEnvelope, Severity
from parrot.core.events.bus.core import BusCore
from parrot.core.hooks.models import HookEvent, HookType   # models.py:31, :9
from parrot.core.hooks.base import BaseHook, HookRegistry  # base.py:96, :39
from parrot.core.hooks.manager import HookManager          # manager.py

# Ecosistema (verificado instalado en .venv de ai-parrot):
from datamodel.parsers.json import JSONContent  # verificado 2026-07-17 — serializador orjson
import navconfig    # 2.2.3
import asyncdb      # 2.15.9
import notify       # async-notify 1.5.7
import redis.asyncio as aioredis
```

### Existing Class Signatures

```python
# events/bus/envelope.py
class Severity(IntEnum): ...                       # línea 21 — DEBUG=10..CRITICAL=50
@dataclass(frozen=True, slots=True)
class EventEnvelope:                                # línea 38
    def to_dict(self) -> dict[str, Any]: ...        # línea 92
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope": ...  # línea 115

# events/bus/core.py
class BusCore:                                      # línea 90
    async def publish(self, envelope: EventEnvelope) -> None: ...  # línea 285
    def subscribe(self, pattern, handler, *, priority=0,
                  filter_fn=None, min_severity=None) -> str: ...   # línea 395

# events/evb.py — facade (se muda tal cual + channel_prefix configurable)
def _bus_config() -> Dict[str, Any]: ...            # línea 108 — lee BUS_* de navconfig
class EventBus:                                     # línea 132
    CHANNEL_PREFIX = "parrot:events:"               # línea 153 → pasa a default "evb:events:" + knob
    def __init__(self, redis_url=None, use_redis=False, **bus_options)  # línea 155
    async def publish(self, event: Event, *, severity=None) -> int      # línea 295
    async def emit(self, event_type: str, payload: dict, **kwargs) -> int  # línea 335

# events/bus/backends/base.py
class TransportBackend(Protocol): ...               # línea 25

# events/bus/backends/redis_streams.py
class RedisStreamsBackend:                          # línea 55
    STREAM_PREFIX = "parrot:stream:"                # línea 81 → default "evb:stream:" + knob
    DEDUP_PREFIX = "parrot:events:dedup:"           # línea 82 → default "evb:events:dedup:" + knob
    # consumer group "parrot-bus" configurable      # docstring línea 13 → default "evb-bus"

# events/bus/subscribers/notification.py
class AlertsConfig(BaseModel): ...                  # línea 81 — from_navconfig lee BUS_ALERTS_*
class NotificationSubscriber:                       # línea 169
    def __init__(self, sender, *, rules=None, config=None, send_timeout=10.0)  # línea 186
    # sender duck-typed: await sender.send_notification(...)

# events/bus/dlq.py
class DLQHandler:                                   # DLQ_TABLE = "navigator.evb_dlq"
    # fallback DSN: from parrot.conf import default_dsn  # líneas 109-110 ← DESACOPLAR

# events/bus/subscribers/audit.py
#   fallback DSN: from parrot.conf import default_dsn    # líneas 89-90 ← DESACOPLAR

# hooks/models.py
class HookType(str, Enum): ...                      # línea 9 — 18 miembros ← reemplazar por registry
class HookEvent(BaseModel): ...                     # línea 31

# hooks/base.py
class HookRegistry: ...                             # línea 39 — registro classmethod import-time
class BaseHook(ABC): ...                            # línea 96 — start/stop abstractos, setup_routes

# hooks/scheduler.py
from parrot._imports import lazy_import             # línea 8 ← DESACOPLAR (util local)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `navigator_eventbus.converters` | `hooks.models.HookEvent` | import intra-paquete | origen: `bus/converters.py:22` |
| `navigator_eventbus.converters` | `evb.Event/EventPriority` | import intra-paquete | origen: `bus/converters.py:21` |
| `navigator_eventbus.ingress.websocket` | `hooks.base.BaseHook`, facade `EventBus`, `ingress_models` | imports intra-paquete | origen: `ingress/websocket.py:23-25` |
| `navigator_eventbus.ingress.grpc` | ídem + `ingress/proto` (lazy) | imports intra-paquete | origen: `ingress/grpc.py:26-28,42` |
| `navigator_eventbus.hooks.brokers.redis` | `navigator.brokers.redis.RedisConnection` | lazy import (temporal, fase 3 recablea) | origen: `hooks/brokers/redis.py:21` |
| `navigator_eventbus.hooks.brokers.mqtt` | `gmqtt.Client` | lazy import | origen: `hooks/brokers/mqtt.py:22` |
| `navigator_eventbus.serialization` | `datamodel.parsers.json.JSONContent` | import directo | verificado en venv 2026-07-17 |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator.eventbus` como namespace importable~~ — `navigator` es paquete
  regular; el import es `navigator_eventbus` plano.
- ~~`__init__.py` en `bus/ingress/proto/`~~ — falta en el origen (verificado
  2026-07-17: solo `events_pb2*.py`, `events.proto`, `README.md`); la mudanza
  DEBE añadirlo.
- ~~`yaml_loader.py` / `legacy_bridge.py` en el alcance de esta fase~~ —
  viven en `events/lifecycle/` (verificado) y van en la fase 2.
- ~~Import de `parrot.observability` en el bus core~~ — ese acople está solo
  en `lifecycle/mixin.py:68` (fase 2); el core no lo tiene.
- ~~Import de `parrot.notifications` en NotificationSubscriber~~ — el sender
  es inyectado duck-typed; no hay import.
- ~~Extra `redis` o `events` en `ai-parrot/pyproject.toml`~~ — no existen;
  el paquete nuevo debe declarar `redis` como extra explícito.
- ~~Contenido útil en la rama `copilot/complete-event-bus-implementation`~~ —
  decidido borrarla; el repo destino solo tiene README + LICENSE (verificado
  2026-07-17).
- ~~`XCLAIM`/`XAUTOCLAIM` en `navigator.brokers`~~ — no existe (bug #2 del
  PR navigator#393, fase 3); el único XAUTOCLAIM es el sweeper de
  `RedisStreamsBackend` que se muda con esta fase.
- ~~`aiomqtt`/`paho` en el hook MQTT~~ — usa `gmqtt`.
- ~~Código del bus en el top-level `parrot/` del repo ai-parrot~~ — la fuente
  canónica es `packages/ai-parrot/src/parrot/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Copia fresca, no rewrite**: cada archivo se copia y se le aplican SOLO
  los desacoples enumerados. Cualquier mejora extra queda fuera (spec propio).
- Async-first en todo; logging con `self.logger` (navconfig logging);
  Pydantic para modelos de configuración/ingress; frozen dataclass para el
  envelope (hot path — decisión de brainstorm-eventbus-v2, no cambiar).
- Modelo de aislamiento de errores B (nunca interrumpir al emisor) —
  preservado tal cual en `BusCore`.
- Import lazy evb↔bus: `evb.py` define `Event`/`EventPriority` que
  `envelope.py`/`converters.py` importan; `evb` importa el bus lazy dentro de
  métodos. **Preservar ese orden** al mudar o el paquete no importa.
- Claves navconfig existentes (`BUS_WORKERS`, `BUS_QUEUE_SIZE`,
  `BUS_HANDLER_TIMEOUT`, `BUS_RETRY_ATTEMPTS`, `BUS_RETRY_BASE_DELAY`,
  `BUS_DEFAULT_BACKPRESSURE`, `BUS_DRAIN_TIMEOUT`, `BUS_ALERTS_*`,
  `BUS_INGRESS_TOKEN`) se conservan; se añaden las de prefijos.

### Known Risks / Gotchas

- **Ventana de divergencia**: hasta la fase 4 coexisten dos copias del bus.
  Mitigación: freeze declarado de `parrot/core/events/` y
  `parrot/core/hooks/` en ai-parrot — cualquier fix va primero al paquete
  nuevo y se replica a mano si es urgente en parrot.
- **Streams desplegados**: los defaults neutros `evb:*` NO deben usarse en
  despliegues parrot existentes; la fase 4 configura los valores legacy.
  Documentar el knob de forma prominente en el README.
- **Stubs gRPC**: `events_pb2_grpc.py` referencia el módulo generado por
  path — al cambiar el package root hay que regenerar con
  `grpcio-tools` o ajustar el import relativo; añadir `__init__.py` a
  `proto/`.
- **HookRegistry en import-time**: los hooks se registran vía classmethod al
  importar (base.py:39-72); los hooks parrot-específicos que NO se mudan
  deben seguir pudiendo registrarse contra el registry del paquete en la
  fase 4 — no introducir estado global que lo impida.
- **Tests con stubs**: `tests/conftest.py:342-345` de ai-parrot inyecta un
  `parrot.notifications` falso en `sys.modules` — al mudar la suite,
  eliminar/replantear esos stubs (el paquete no conoce parrot).
- **CI sin PyPI**: el paquete no se publica en esta fase; el CI del repo
  nuevo es autosuficiente (no depende de ai-parrot).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navconfig[default]` | `>=2.2.2` | config + logging del core (dep directa) |
| `asyncdb` | `>=2.11` | persistencia DLQ/audit (dep directa) |
| `datamodel` | (la que trae asyncdb/navconfig) | `JSONContent` (orjson) — serialización default |
| `aiohttp` | `>=3.9` | ingress WS, webhook egress, consumers (dep directa) |
| `async-notify` | `>=1.5.2` | sender default NotificationSubscriber — extra `[notify]` |
| `redis` | `>=5` | backends pubsub/streams — extra `[redis]` |
| `grpcio`/`grpcio-tools` | `>=1.74` | ingress gRPC — extra `[grpc]` |
| `apscheduler` | actual de parrot | hook scheduler — extra `[scheduler]` |
| `watchdog` | actual de parrot | hook file_watchdog — extra `[watchdog]` |
| `gmqtt` | actual de parrot | hook broker MQTT — extra `[mqtt]` |
| `cloudpickle` | opcional | serialización alternativa — extra (documentado, no requerido en fase 1) |

---

## 8. Open Questions

> Todas las preguntas de diseño de esta fase fueron resueltas en el brainstorm
> (`sdd/proposals/navigator-eventbus-extraction.brainstorm.md`, 2026-07-17).
> Se listan como trail de auditoría; NO re-abrir.

- [x] `HookType`: ¿enum cerrado o tipo abierto? — *Resolved in brainstorm*:
  tipo abierto (str validado + registry); el paquete provee los genéricos y
  cada app registra los suyos al importar. **AMENDED 2026-07-17
  (post-implementation, ver Revision History)**: el paquete pre-registra
  los 18 hook types legacy completos (10 genéricos + 8 específicos de
  ai-parrot) más `webhook`, por compatibilidad retro total con FEAT-310;
  apps siguen registrando dinámicamente cualquier tipo NUEVO no incluido
  en esos 19.
- [x] `hooks/models.py`: ¿mudar entero o partir? — *Resolved in brainstorm*:
  se muda entero; las apps importan los modelos desde el paquete.
- [x] Prefijos Redis: ¿default neutro o `parrot:*`? — *Resolved in brainstorm*:
  default neutro con override per-app; parrot fija `parrot:*` en la fase 4.
- [x] CI del repo nuevo y rama copilot — *Resolved in brainstorm*: GitHub
  Actions replicando la infra de navigator/ai-parrot desde la fase 1; la rama
  copilot se borra.
- [x] ¿Preservar historia git? — *Resolved in brainstorm*: no — copia fresca;
  el commit inicial referencia el SHA de origen.
- [x] Versionado y distribución — *Resolved in brainstorm*: arranca en 0.1.0;
  PyPI público (publicación efectiva al cierre de la fase 4); editable local
  durante la migración.
- [x] `TOPICS.md` — *Resolved in brainstorm*: nace con esta fase.
- [x] Serialización — *Resolved in brainstorm*: JSON vía `JSONContent`
  (orjson) por defecto; cloudpickle opcional.
- [x] Import name — *Resolved in brainstorm*: `navigator_eventbus` plano.
- [x] NotificationSubscriber — *Resolved in brainstorm*: al core con sender
  default sobre `notify`; senders inyectados siguen funcionando.
- [x] Typed events post-migración — *Resolved in brainstorm*: quedan en
  `parrot.core.events.lifecycle` (afecta fases 2/4, registrado aquí por
  contexto).
- [x] Motor de wiring `yaml_loader` — *Resolved in brainstorm*: se muda al
  paquete con tabla de eventos inyectable — **en la fase 2** (vive en
  `events/lifecycle/`).
- [x] Owner de las migraciones — *Resolved in brainstorm*: Jesus es owner de
  todos los paquetes y ejecuta cada migración (parrot, navigator, Flowtask,
  FieldSync).

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — pero el worktree vive en el **repo
  `navigator-eventbus`**, no en ai-parrot (rama `feat-FEAT-312-eventbus-core-extraction`
  desde `main` de ese repo). En ai-parrot esta fase solo toca artefactos SDD
  (spec/tasks/index en `dev` directo — sin worktree, per política "cuando NO
  usar worktrees").
- **Secuencia**: Módulos 1→2 secuenciales (scaffold, luego envelope). Tras el
  Module 2, los módulos 4 (backends), 5 (subscribers), 6 (hooks) y 7 (ingress)
  son paralelizables entre sí (dependen de 2/3); en la práctica, con un solo
  implementador, se recomienda secuencial 1→2→3→4→5→6→7→8 en el mismo worktree.
- **Cross-feature dependencies**: ninguna spec previa pendiente. Coordinar el
  **freeze** de `parrot/core/events/` y `parrot/core/hooks/` en ai-parrot al
  arrancar (verificar que no haya flows en vuelo tocando esos árboles).
  FEAT-311 (moonshot-client) toca `clients/` — sin colisión.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-17 | Jesus + Claude | Initial draft desde brainstorm navigator-eventbus-extraction (fase 1) |
| 0.2 | 2026-07-17 | Jesus + Claude | Post-implementation amendment to §2 decision #2 (re-opened by explicit user directive after TASK-1803 flagged the contradiction between its own scope text and the closed decision): `HOOK_TYPES` now pre-registers ALL 18 legacy hook types (10 generics + 8 ai-parrot-specific integration types) plus the new `webhook` generic, for full FEAT-310 backward compatibility — not just the 11 generics. Apps still register any genuinely NEW hook type dynamically. Code + tests updated accordingly in `navigator-eventbus` (`hooks/models.py`, `tests/test_hook_type_registry.py`, `tests/test_hooks_manager.py`, `tests/test_envelope.py`). |
