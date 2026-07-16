---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: `navigator-eventbus-extraction` — mudar el fabric de eventos de ai-parrot al paquete standalone `navigator-eventbus`

**Date**: 2026-07-17
**Author**: Jesus (phenobarbital) + Claude
**Status**: exploration
**Recommended Option**: B (extracción por fases con migración dura de imports)

> **Relación con brainstorms anteriores**: sucede a `sdd/proposals/brainstorm-eventbus-v2.md`
> (Opción B "layered bus" + decomposición multi-repo). Sus specs 1–4 fueron implementados
> **dentro de ai-parrot** por FEAT-310 (`eventbus-v2`, 11 tareas done, completado
> 2026-07-16). Este brainstorm ejecuta la parte pendiente: la **extracción física** del
> código al repo `/home/jesuslara/proyectos/navigator-eventbus` y el refit de ai-parrot.

---

## Problem Statement

FEAT-310 entregó el EventBus v2 completo (envelope unificado, dispatcher con worker
pool, backends memory/pubsub/streams, DLQ, subscribers de notificación/audit/metrics,
ingress WS+gRPC, `route_to_bus` en HookManager) — pero **vive dentro de ai-parrot**
(`packages/ai-parrot/src/parrot/core/events/` + `parrot/core/hooks/`, ~10.135 LOC).

Flowtask, QuerySource y navigator-auth necesitan el mismo fabric de eventos. Hoy sus
opciones son: depender de ai-parrot entero (inaceptable — arrastra LLM clients, bots,
loaders) o duplicar el código (el problema que brainstorm-eventbus-v2 identificó).
El repo destino `navigator-eventbus` existe pero está vacío (solo README/LICENSE).

Afectados: los cuatro consumidores del ecosistema; en ai-parrot, los ~30 archivos de
producción y ~70 de tests/examples que importan `parrot.core.events` / `parrot.core.hooks`.

## Constraints & Requirements

- **Decisiones tomadas en discovery (Rondas 0–3):**
  - Flow `feature` / base `dev` en ai-parrot; el trabajo en `navigator-eventbus` se hace
    en su propio repo (rama desde `main` de ese repo).
  - **Alcance**: bus core + maquinaria lifecycle + hooks genéricos (manager, base,
    models, mixins, brokers, scheduler, watchdog). Los **eventos tipados de agente**
    (`agent/invoke/client/tool/message/flow`) y los hooks específicos de parrot
    (jira, github, sharepoint, whatsapp, matrix, imap, messaging) **quedan en ai-parrot**.
  - **Dependencias**: ecosistema navigator completo — `navconfig` y `asyncdb` como deps
    directas; `notify` (async-notify), `redis`, `aiohttp`, `grpcio` como extras.
  - **Imports**: migración dura — todos los call-sites de parrot cambian a
    `from navigator_eventbus import ...`; sin capa de shims (la facade `EventBus`
    existente ya es la capa de compatibilidad de API).
  - **Nombre de import**: `navigator_eventbus` (plano). `navigator.eventbus` vía PEP 420
    fue descartado: el paquete `navigator` instalado es regular (`navigator/__init__.py`
    verificado en el venv) y el namespace no fusionaría.
  - **NotificationSubscriber** se muda al core usando la librería `notify`
    (async-notify 1.5.7) como sender por defecto (hoy el sender es duck-typed, inyectado).
  - **Distribución**: install editable local (`uv pip install -e`) durante la migración;
    publicar a PyPI solo cuando la suite de ai-parrot pase completa con el paquete.
  - **Rama `copilot/complete-event-bus-implementation`** del repo navigator-eventbus:
    se ignora/descarta; FEAT-310 es la fuente canónica.
- API pública preservada: `EventBus.emit/subscribe/on/publish`, `EventRegistry.subscribe/emit`,
  `HookManager.set_event_bus/route_to_bus` mantienen firma — solo cambia el módulo de origen.
- Presupuesto de rendimiento FEAT-177 intacto (< 0.1% overhead en dual-emit lifecycle).
- Modelo de aislamiento de errores B (nunca interrumpir el flujo emisor) preservado.
- Python 3.11+, async-first, `uv`-managed, ambos repos.

---

## Options Explored

### Option A: Big-bang — extracción y migración en un solo flow

Un único spec mueve de una vez todo el alcance acordado a `navigator-eventbus`
(scaffold + código + tests), y un segundo spec simultáneo en ai-parrot borra el código,
añade la dependencia y reescribe los ~100 archivos importadores en un solo PR por repo.

✅ **Pros:**
- Sin estados intermedios: nunca coexisten dos copias del código.
- Un solo ciclo de review/QA por repo.
- La migración dura de imports (ya decidida) se hace una sola vez.

❌ **Cons:**
- PR gigante en ai-parrot (~100 archivos entre prod/tests) — difícil de revisar y de
  bisecar si algo se rompe.
- Cualquier bloqueo en el desacople (p.ej. `HookType` extensible) frena TODO el flow.
- La ventana con ai-parrot "roto" (código borrado, paquete aún inestable) es larga.

📊 **Effort:** High (concentrado)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navconfig[default]` >=2.2.2 | config + logging del core | instalado 2.2.3 |
| `asyncdb` >=2.11 | persistencia DLQ/audit | instalado 2.15.9 |
| `async-notify` >=1.5.2 | sender por defecto de NotificationSubscriber | instalado 1.5.7; extra `[notify]` |
| `redis` | backends pubsub/streams | extra `[redis]` |
| `grpcio`/`grpcio-tools` >=1.74 | ingress gRPC | extra `[grpc]` |

🔗 **Existing Code to Reuse:**
- Todo el árbol `packages/ai-parrot/src/parrot/core/events/` y `core/hooks/` (ver Code Context).

---

### Option B: Extracción por fases — tres cortes verticales, cada uno shippable

Tres specs secuenciales, cada uno deja ambos repos verdes:

1. **`eventbus-core-extraction`** (repo navigator-eventbus): scaffold del paquete
   (pyproject uv, src-layout `src/navigator_eventbus/`, CI) + mudanza del **bus core**:
   `envelope`, `ingress_models`, `core` (BusCore), `backends/*`, `converters`, `dlq`,
   `subscribers/*` (notification con sender `notify` por defecto, audit, metrics),
   `ingress/*` (WS/gRPC + proto), la facade `evb.py` (Event/EventPriority/EventBus) y
   los módulos genéricos de hooks que el bus necesita (`hooks/base`, `manager`, `models`,
   `mixins`, `brokers/*`, `scheduler`, `file_watchdog`). Desacoples puntuales:
   `parrot.conf.default_dsn` → parámetro/navconfig, `parrot._imports.lazy_import` →
   util local, prefijos `parrot:*` → configurables. Tests del bus se mudan con el código.
2. **`eventbus-lifecycle-extraction`** (repo navigator-eventbus): mudanza de la
   maquinaria lifecycle: `base` (LifecycleEvent), `trace` (TraceContext), `meta`,
   `registry` (EventRegistry), `global_registry`, `provider`, `mixin` (sin el auto-boot
   de observability — se reemplaza por hook inyectable), subscribers `logging` y
   `webhook`. Publica `0.1.0rc` interno (editable) al cierre.
3. **`parrot-eventbus-migration`** (repo ai-parrot, base `dev`): añade la dependencia,
   borra el código mudado, reescribe imports en los ~30 archivos prod + tests, conserva
   y recablea lo parrot-específico: eventos tipados (subclasean
   `navigator_eventbus.LifecycleEvent`), `legacy_bridge`, `yaml_loader`,
   `OpenTelemetrySubscriber` (importa eventos tipados → se queda), hooks de integración
   (jira/github/sharepoint/whatsapp/matrix/imap/messaging/postgres/file_upload) y
   `parrot.notifications`. Regression: suite completa + benchmark FEAT-177.

✅ **Pros:**
- Cada fase es reviewable y bisecable; navigator-eventbus queda usable (core) desde la fase 1.
- Los dos únicos desacoples con riesgo (mixin/observability, HookType extensible) se
  resuelven en fases tempranas sin bloquear la migración masiva.
- La ventana de "dos copias" existe pero controlada: ai-parrot sigue usando su copia
  hasta la fase 3; nadie consume las dos a la vez.
- Flowtask/QuerySource pueden empezar a probar el paquete tras la fase 1, antes de que
  ai-parrot migre.

❌ **Cons:**
- Tres flows SDD en dos repos — más ceremonia que la Opción A.
- Durante las fases 1–2 cualquier fix al bus en ai-parrot debe replicarse a mano en la
  copia extraída (ventana de divergencia; mitigable congelando `parrot/core/events/`).

📊 **Effort:** High (distribuido; fase 3 es la más ancha)

📦 **Libraries / Tools:** (idéntico a la Opción A)
| Package | Purpose | Notes |
|---|---|---|
| `navconfig[default]` >=2.2.2 | config + logging | dep directa |
| `asyncdb` >=2.11 | DLQ/audit | dep directa (decisión Ronda 1) |
| `async-notify` >=1.5.2 | notificaciones | extra `[notify]` |
| `redis`, `grpcio`, `aiohttp` | transportes/ingress | extras `[redis]`, `[grpc]`; aiohttp dep directa (WS + webhook subscriber) |
| `watchdog`, `apscheduler`, `gmqtt`, `navigator` | hooks opcionales | extras `[watchdog]`, `[scheduler]`, `[mqtt]`, `[brokers]` — todos ya lazy-imported |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/core/events/bus/` — íntegro (~2.6k LOC, casi sin acople).
- `packages/ai-parrot/src/parrot/core/events/evb.py` — facade, se muda tal cual.
- `packages/ai-parrot/src/parrot/core/events/lifecycle/{base,trace,meta,registry,global_registry,provider,mixin}.py` + `subscribers/{logging,webhook}.py`.
- `packages/ai-parrot/src/parrot/core/hooks/{base,manager,models,mixins}.py`, `brokers/*`, `scheduler.py`, `file_watchdog.py`.
- `packages/ai-parrot/tests/core/events/` — la suite del bus se muda; `tests/unit/events/lifecycle/` se parte (maquinaria → paquete; typed events → parrot).

---

### Option C (no convencional): Doble distribución — el paquete nuevo publica también un shim `parrot-events-compat`

`navigator-eventbus` se extrae igual que en B, pero además publica una segunda
distribución `parrot-events-compat` que re-exporta los símbolos bajo module-aliases
(`sys.modules["parrot.core.events.bus"] = navigator_eventbus.bus`, estilo bridge) para
que NINGÚN call-site de ai-parrot (ni de terceros que importen `parrot.core.events`)
cambie de inmediato; la migración de imports se hace después, gradualmente, con deprecation warnings.

✅ **Pros:**
- Riesgo de regresión mínimo en ai-parrot: el PR de migración se reduce a cambiar la dependencia.
- Terceros no monorepo (plugins, notebooks de usuarios) no se rompen.

❌ **Cons:**
- Contradice la decisión de discovery (migración dura, sin shims).
- Un merge PEP 420 real es imposible: `parrot/core/__init__.py` es paquete regular —
  el shim tendría que manipular `sys.modules` en import-time (frágil, orden-dependiente).
- Mantener dos superficies de import prolonga la fragmentación que se quiere matar.

📊 **Effort:** Medium (extracción) + deuda permanente del shim

📦 **Libraries / Tools:** los de B + nada adicional.

🔗 **Existing Code to Reuse:** patrón satélite de `ai-parrot-embeddings`
(`packages/ai-parrot-embeddings/`) como referencia de doble distribución — aunque ahí
funciona porque `parrot.embeddings` sí es namespace-mergeable; `parrot.core` no lo es.

---

## Recommendation

**Option B** es la recomendada:

- La decisión de migración dura ya está tomada (Ronda 1) — C queda descartada por diseño;
  su único mérito (proteger a terceros) se cubre documentando el breaking change en el
  CHANGELOG y el bump de versión de ai-parrot.
- Frente a A, B convierte el riesgo de un PR de ~100 archivos en tres cortes bisecables,
  y entrega valor temprano: Flowtask/QuerySource pueden adoptar el core tras la fase 1
  sin esperar la migración de parrot.
- El censo de acoplamiento (ver Code Context) confirma que B es barata en desacoples:
  solo **dos imports duros** de parrot fuera del subsistema (`lifecycle/mixin.py:68` →
  `parrot.observability`, ya guarded; `hooks/scheduler.py:8` → `parrot._imports`) más
  dos lazy-guarded (`dlq.py:109`, `audit.py:89` → `parrot.conf.default_dsn`). Todo lo
  demás son imports intra-subsistema que viajan juntos.
- Trade-off aceptado: ventana de divergencia entre fases 1–3. Mitigación: freeze
  declarado de `parrot/core/events/` y `parrot/core/hooks/` en ai-parrot durante la
  extracción (cualquier fix va primero al paquete nuevo).

---

## Feature Description

### User-Facing Behavior

- **Consumidores nuevos** (Flowtask, QuerySource, navigator-auth):
  `pip install navigator-eventbus[redis]` y `from navigator_eventbus import EventBus,
  EventEnvelope, Severity` — el mismo bus O(1)-publish con workers, severidad, DLQ,
  Redis Streams y alertas vía `notify`, sin arrastrar ai-parrot.
- **Desarrolladores de ai-parrot**: la API no cambia (`bus.emit(...)`,
  `@bus.on("topic.*", min_severity=...)`, `registry.subscribe(BeforeInvokeEvent, ...)`,
  `HookManager(route_to_bus=True)`); solo cambia el import:
  `from navigator_eventbus import EventBus` / `from navigator_eventbus.lifecycle import
  EventRegistry, LifecycleEvent`. Los eventos tipados de agente siguen importándose de
  parrot (`from parrot.core.events.lifecycle.events import BeforeInvokeEvent`).
- Config TOML/env idéntica (`BUS_WORKERS`, `BUS_ALERTS_*`, `BUS_INGRESS_TOKEN`), ahora
  leída por navconfig desde el paquete; los prefijos Redis (`parrot:events:`,
  `parrot:stream:`) pasan a ser configurables con default neutro y override en parrot
  para no romper streams existentes.

### Internal Behavior

- **navigator-eventbus** (src-layout, import `navigator_eventbus`):
  - `navigator_eventbus/` → `envelope.py`, `core.py`, `evb.py` (facade Event/EventBus/
    EventPriority), `converters.py`, `dlq.py`, `ingress_models.py`
  - `backends/` (base, memory, redis_pubsub, redis_streams), `subscribers/`
    (notification+notify sender, audit, metrics), `ingress/` (ws, grpc, proto — se añade
    el `__init__.py` que hoy falta en `proto/`)
  - `lifecycle/` (base, trace, meta, registry, global_registry, provider, mixin,
    subscribers/logging, subscribers/webhook)
  - `hooks/` (base, manager, models, mixins, brokers/*, scheduler, file_watchdog)
  - Desacoples: DSN por parámetro/navconfig (sin `parrot.conf`); `lazy_import` local;
    hook de bootstrap inyectable en `EventEmitterMixin` en vez del import de
    `parrot.observability`; prefijos y consumer-group configurables.
- **ai-parrot post-migración**:
  - `parrot/core/events/` queda reducido a lo parrot-específico: `lifecycle/events/*`
    (taxonomía tipada, subclasea `navigator_eventbus.lifecycle.LifecycleEvent`),
    `legacy_bridge.py`, `yaml_loader.py` (motor genérico importado, tabla de nombres
    parrot local), `subscribers/opentelemetry.py` (depende de eventos tipados).
  - `parrot/core/hooks/` conserva jira/github/sharepoint/whatsapp_redis/matrix/imap/
    messaging/postgres/file_upload, registrándose contra `navigator_eventbus.hooks.
    HookRegistry` y subclaseando su `BaseHook`.
  - `EventEmitterMixin` se importa del paquete y parrot le inyecta su bootstrap de
    observability al inicializar bots/clients.
  - pyprojects: `ai-parrot` añade `navigator-eventbus` como dep; `ai-parrot-server` y
    `ai-parrot-integrations` la heredan transitivamente (hoy solo declaran `ai-parrot`).

### Edge Cases & Error Handling

- **Streams Redis existentes**: datos en `parrot:stream:*` / grupo `parrot-bus` deben
  seguir siendo consumibles → parrot configura los prefijos legacy explícitamente;
  el default del paquete puede ser neutro sin romper despliegues.
- **Tablas DLQ/audit**: `navigator.evb_dlq` / `navigator.evb_audit` ya usan schema
  `navigator` — sin cambio; el DSN deja de venir de `parrot.conf` (parámetro obligatorio
  o navconfig).
- **`HookType` extensible**: el enum vive en el paquete pero contiene miembros
  parrot-específicos (JIRA_WEBHOOK, SHAREPOINT, WHATSAPP_REDIS...). Un `str`-enum no es
  subclaseable con miembros nuevos → o el enum completo viaja al paquete (simple, algo
  impuro), o `hook_type` pasa a tipo abierto (str validado) con registro de tipos.
  Decisión en el spec de la fase 1 (open question).
- **Import circular evb ↔ bus**: `evb.py` define `Event`/`EventPriority` que
  `envelope.py`/`converters.py` importan; `evb` importa el bus lazy dentro de métodos.
  La mudanza debe preservar ese orden (documentado en Code Context).
- **Divergencia durante la ventana de extracción**: freeze de `parrot/core/events|hooks`
  en dev; los fixes van al paquete nuevo primero.
- **Tests con stubs**: `tests/conftest.py:342-345` inyecta un `parrot.notifications`
  falso en `sys.modules` — la fase 3 debe revisar esos stubs al recablear.
- **Fallo de instalación editable en CI**: mientras no haya release PyPI, el CI de
  ai-parrot necesita el paquete como git-dep o path-dep temporal; se retira al publicar
  `0.1.0`.

---

## Capabilities

### New Capabilities
- `eventbus-core-extraction` (**navigator-eventbus**): scaffold del paquete + mudanza
  del bus core, backends, subscribers, ingress, facade y hooks genéricos, con los
  desacoples de `parrot.conf`/`parrot._imports` y prefijos configurables.
- `eventbus-lifecycle-extraction` (**navigator-eventbus**): mudanza de la maquinaria
  lifecycle (LifecycleEvent, TraceContext, EventRegistry, global registry, provider,
  mixin con bootstrap inyectable, subscribers logging/webhook).
- `parrot-eventbus-migration` (**ai-parrot**): dependencia nueva, borrado del código
  mudado, reescritura de imports (~30 archivos prod + tests/examples), recableado de
  eventos tipados, otel subscriber, hooks de integración y observability bootstrap.

### Modified Capabilities
- `eventbus-v2` (FEAT-310): el código entregado se convierte en el contenido del paquete
  externo; el spec queda como referencia histórica del diseño.
- `lifecycle-events-system` (FEAT-176/177): sin cambio de comportamiento; los imports de
  la maquinaria cambian de módulo. El benchmark de overhead se re-ejecuta en la fase 3.
- `formdesigner-lifecycle-events`, `event-ledger-resume` (FEAT-212): consumidores de
  lifecycle/registry — solo cambio de import en la fase 3.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator-eventbus` (repo) | new | recibe ~6.5k LOC + tests; pyproject uv, CI propio, extras `[redis][grpc][notify][scheduler][watchdog][mqtt][brokers]` |
| `packages/ai-parrot/src/parrot/core/events/` | modifies (se vacía parcialmente) | quedan typed events, legacy_bridge, yaml_loader, otel subscriber |
| `packages/ai-parrot/src/parrot/core/hooks/` | modifies | quedan hooks de integración; base/manager/models/brokers se van |
| `packages/ai-parrot/pyproject.toml` | extends | + `navigator-eventbus`; extras `grpc` migran de dueño |
| `ai-parrot-server` (autonomous/*) | modifies | 5 archivos cambian imports (orchestrator, evb shim, ledger, webhooks, filesystem hook) |
| `ai-parrot-integrations` (matrix/hook.py) | modifies | HookRegistry/BaseHook/HookType desde el paquete |
| `parrot.observability` | modifies | deja de ser importado por el mixin; parrot inyecta el bootstrap |
| `parrot.notifications` | unchanged | sigue en parrot; NotificationSubscriber del core acepta cualquier sender (notify default) |
| Redis desplegado (Cloud Run) | depends on | prefijos/consumer-group deben configurarse a los valores legacy `parrot:*` |
| Flowtask / QuerySource / navigator-auth | future consumers | adoptan el paquete tras la fase 1; specs de adopción fuera de este alcance (viven en sus repos) |
| CI ai-parrot | extends | dependencia editable/git temporal hasta release PyPI |

---

## Code Context

### User-Provided Code

(no se aportaron snippets; decisiones capturadas en Constraints)

### Verified Codebase References

Base: `packages/ai-parrot/src/parrot/core/` (rama `dev`, post-FEAT-310).

#### Classes & Signatures
```python
# events/bus/envelope.py:21,38
class Severity(IntEnum): DEBUG=10; INFO=20; WARNING=30; ERROR=40; CRITICAL=50
@dataclass(frozen=True, slots=True)
class EventEnvelope:
    topic: str; payload: dict; event_id: str; timestamp: datetime  # rechaza naive (:72)
    def to_dict(self) -> dict[str, Any]: ...            # :92
    @classmethod
    def from_dict(cls, data: dict) -> "EventEnvelope": ...  # :114

# events/bus/core.py:90
class BusCore:
    def __init__(self, *, workers=4, queue_size=1024, handler_timeout=30.0,
                 retry_attempts=3, retry_base_delay=0.1, backpressure=None,
                 default_backpressure=POLICY_BLOCK, drain_timeout=5.0,
                 on_dlq=None, backend: Optional[TransportBackend]=None) -> None  # :126
    async def publish(self, envelope: EventEnvelope) -> None                     # :285
    def subscribe(self, pattern, handler, *, priority=0, filter_fn=None,
                  min_severity=None) -> str                                      # :395

# events/evb.py:132 — facade (mueve al paquete tal cual)
class EventBus:
    CHANNEL_PREFIX = "parrot:events:"                                            # :153
    def __init__(self, redis_url=None, use_redis=False, **bus_options)           # :155
    async def publish(self, event: Event, *, severity=None) -> int               # :295
    async def emit(self, event_type: str, payload: dict, **kwargs) -> int        # :335
# evb.py:108 _bus_config() lee BUS_WORKERS/QUEUE_SIZE/HANDLER_TIMEOUT/... de navconfig (:121-129)

# events/bus/backends/base.py:24
@runtime_checkable
class TransportBackend(Protocol):
    async def publish(self, envelope) -> None; ...
    async def start_consumer(self, on_envelope: OnEnvelope) -> None; ...
    async def close(self) -> None; ...
# redis_streams.py:55 RedisStreamsBackend — STREAM_PREFIX="parrot:stream:" (:81),
#   DEDUP_PREFIX="parrot:events:dedup:" (:82), group="parrot-bus" (:89)

# events/bus/dlq.py:80
class DLQHandler:
    DLQ_TABLE = "navigator.evb_dlq"                                              # :32
    def __init__(self, bus: BusCore, *, dsn=None, driver="pg") -> None           # :95
# events/bus/subscribers/audit.py:59 AuditSubscriber — AUDIT_TABLE="navigator.evb_audit" (:30)

# events/bus/subscribers/notification.py:169
class NotificationSubscriber:
    def __init__(self, sender: Any, *, rules=None, config=None,
                 send_timeout: float=10.0) -> None                               # :186
    # sender duck-typed: await self._sender.send_notification(...)  (:444)
# AlertsConfig.from_navconfig() (:109) lee BUS_ALERTS_* (:127-133)

# events/lifecycle/base.py:20  @dataclass(frozen=True) class LifecycleEvent(ABC)
# events/lifecycle/trace.py:14 TraceContext (W3C traceparent, cero deps)
# events/lifecycle/registry.py:90
class EventRegistry:
    def __init__(self, event_bus=None, bus_channel_prefix=..., forward_to_global=True)  # :104
    def subscribe(self, event_type, callback, *, where=None, forward_to_bus=False) -> str  # :121
    async def emit(self, event: LifecycleEvent) -> None                          # :235
# events/lifecycle/mixin.py:24 EventEmitterMixin — import guarded de
#   parrot.observability.bootstrap en :68 (lazy, try/except :67-74) ← ÚNICO acople duro #1

# hooks/base.py:39 HookRegistry (registro por classmethod en import-time, :55-72)
# hooks/base.py:96 BaseHook(ABC) — start/stop abstractos (:169/:173), setup_routes (:176)
# hooks/manager.py:15
class HookManager:
    def __init__(self, *, route_to_bus: bool = False)                            # :40
    def set_event_bus(self, bus: "EventBus") -> None                             # :70
    async def _publish_hook_event(self, bus, event)  # topic f"hooks.{type}.{event}" (:127,:138)
# hooks/scheduler.py:8 from parrot._imports import lazy_import ← ÚNICO acople duro #2
# hooks/models.py:9 HookType(str, Enum) — 18 miembros incl. parrot-específicos (:11-28)
# hooks/models.py:31 HookEvent(BaseModel)
```

#### Verified Imports
```python
# Acoples que bloquean la extracción (censo exhaustivo — SOLO estos):
from parrot.observability.bootstrap import ensure_observability_bootstrapped  # lifecycle/mixin.py:68 (lazy+guarded)
from parrot._imports import lazy_import                                       # hooks/scheduler.py:8 (duro, module-level)
from parrot.conf import default_dsn                                           # bus/dlq.py:109, bus/subscribers/audit.py:89 (lazy+guarded)
from parrot.core.hooks.models import HookEvent                                 # bus/converters.py:22 (intra-alcance: hooks.models se muda)
from parrot.core.hooks.base import BaseHook                                    # bus/ingress/websocket.py:25, grpc.py:28 (intra-alcance)

# Brokers: deps fuera del set permitido, todas lazy (extras del paquete):
from navigator.brokers.redis import RedisConnection        # hooks/brokers/redis.py:21
from navigator.brokers.rabbitmq import RabbitMQConnection  # hooks/brokers/rabbitmq.py:23
from navigator.brokers.sqs import SQSConnection            # hooks/brokers/sqs.py:22
from gmqtt import Client as MQTTClient                     # hooks/brokers/mqtt.py:22

# Ecosistema (verificado instalado en .venv):
import navigator      # REGULAR package (__init__.py) → PEP 420 navigator.eventbus INVIABLE
import navconfig      # 2.2.3
import asyncdb        # 2.15.9
import notify         # async-notify 1.5.7

# Censo de consumidores prod (fase 3) — solo 3 paquetes:
# ai-parrot: bots/{abstract,base}.py, clients/{base,claude,claude_agent,gpt,grok,groq,google/client}.py,
#   observability/{attributes,bootstrap,provider,setup,traceloop_integration}.py + subscribers/recorders,
#   eval/{events,runner}.py, registry/registry.py (wire_events :190), auth/permission.py,
#   bots/flows/{core/context,flow/telemetry}.py, bots/{github_reviewer,jira_specialist}.py
# ai-parrot-server: autonomous/{evb,ledger,orchestrator,webhooks}.py, autonomous/transport/filesystem/hook.py
# ai-parrot-integrations: integrations/matrix/hook.py
# + ~70 archivos en tests/ y examples/
```

#### Key Attributes & Constants
- Env/config leídos vía navconfig: `BUS_WORKERS, BUS_QUEUE_SIZE, BUS_HANDLER_TIMEOUT,
  BUS_RETRY_ATTEMPTS, BUS_RETRY_BASE_DELAY, BUS_DEFAULT_BACKPRESSURE, BUS_DRAIN_TIMEOUT`
  (evb.py:121-129); `BUS_ALERTS_*` (notification.py:127-133); `BUS_INGRESS_TOKEN`
  (websocket.py:60, grpc.py:202)
- Meta-topics: `bus.subscriber_error`, `bus.backpressure`, `bus.shutdown_incomplete`
  (core.py:44-46); `bus.dlq`/`bus.dlq_error` (dlq.py:173,227)
- Convenciones de topic: `hooks.<type>.<event>` (converters.py:152), `lifecycle.<Class>`
  (converters.py:111)
- `async-notify` NO es dep core de ai-parrot — solo extras `notify-all` (pyproject:119)
  e `integrations` (:407-408); no existe extra `redis` ni `events` en ai-parrot
- LOC a mudar: bus+evb ≈ 3.993; lifecycle machinery ≈ 1.400 (sin typed events ≈ 625 que quedan);
  hooks genéricos ≈ 1.500. Total paquete ≈ 6.5k LOC + tests

### Does NOT Exist (Anti-Hallucination)
- ~~`navigator.eventbus` como namespace importable~~ — descartado: `navigator` es paquete
  regular; el import será `navigator_eventbus`.
- ~~Import de `parrot.notifications` en `NotificationSubscriber`~~ — NO existe; el sender
  es inyectado duck-typed (docstring menciona NotificationMixin, sin import).
- ~~Extra `redis` o `events` en `ai-parrot/pyproject.toml`~~ — no existen; redis llega
  transitivo. El paquete nuevo debe declararlo explícito.
- ~~`__init__.py` en `bus/ingress/proto/`~~ — falta hoy (resuelve por namespace implícito);
  la mudanza debe añadirlo.
- ~~Código del bus en el top-level `parrot/` del repo~~ — ese árbol está vacío
  (`__pycache__`); la fuente canónica es `packages/ai-parrot/src/parrot/`.
- ~~Contenido útil en la rama `copilot/complete-event-bus-implementation`~~ — decidido
  ignorarla; el repo navigator-eventbus está efectivamente vacío (README+LICENSE).
- ~~`aiomqtt`/`paho` en brokers/mqtt~~ — usa `gmqtt`.
- ~~PEP 420 merge en `parrot.core.*`~~ — `parrot/core/__init__.py` es regular; un satélite
  no puede contribuir módulos bajo `parrot.core` (a diferencia de `parrot.embeddings`).

---

## Parallelism Assessment

- **Internal parallelism**: Moderada. Las fases 1→2→3 son secuenciales (lifecycle importa
  el envelope/bus; la migración de parrot requiere el paquete completo). Dentro de la
  fase 1, tras el scaffold + envelope, las tareas (backends / subscribers / ingress /
  hooks genéricos) son paralelizables en worktrees del repo navigator-eventbus. La fase 3
  es un cambio ancho y transversal en ai-parrot — un solo worktree, tareas secuenciales
  por área (clients → bots → observability → server/integrations → tests).
- **Cross-feature independence**: en ai-parrot, la fase 3 toca `bots/`, `clients/`,
  `observability/`, `eval/` — verificar flows en vuelo sobre esos módulos antes de
  arrancarla (hoy: FEAT-311 moonshot-client-llm toca `clients/` — coordinar). Declarar
  freeze de `parrot/core/events|hooks` desde el inicio de la fase 1.
- **Recommended isolation**: `per-spec` (un worktree por fase, cada una en su repo).
- **Rationale**: los contratos entre fases son explícitos (API del paquete, versión
  editable); el riesgo dominante es la ventana de divergencia, que se minimiza con el
  freeze y fases cortas, no con paralelismo agresivo.

---

## Open Questions

- [ ] `HookType` en el paquete neutral: ¿enum cerrado con los 18 miembros actuales
  (incluye JIRA/SHAREPOINT/WHATSAPP...) o tipo abierto (str validado + registro) para que
  cada app añada los suyos sin tocar el core? Afecta a `HookEvent.hook_type` y a los
  config models. — *Owner: Jesus*
- [ ] `hooks/models.py` mezcla modelos genéricos (HookEvent, SchedulerHookConfig,
  BrokerHookConfig...) con configs de integraciones parrot (Jira/GitHub/SharePoint/
  WhatsApp/Matrix): ¿se muda entero (simple) o se parte (configs de integración quedan
  en parrot)? — *Owner: Jesus*
- [ ] Prefijos Redis: ¿default del paquete neutro (`nav:events:`/`nav:stream:`) con
  override `parrot:*` en ai-parrot, o conservar `parrot:*` como default para cero-config
  en despliegues actuales? — *Owner: Jesus*
- [ ] `yaml_loader`: ¿mudar el motor de wiring al paquete (con tabla de eventos
  inyectable) o dejarlo entero en parrot en la primera iteración? — *Owner: Jesus*
- [ ] Módulo destino de los typed events en parrot post-migración: ¿mantener
  `parrot.core.events.lifecycle.events` (mínimo diff) o promover a `parrot.events`?
  — *Owner: Jesus*
- [ ] Repo navigator-eventbus: ¿CI con GitHub Actions replicando la matriz de ai-parrot
  (pytest + ruff + mypy) desde la fase 1? ¿Se borra la rama copilot? — *Owner: Jesus*
- [ ] ¿Preservar historia git de los archivos mudados (git filter-repo / subtree) o copia
  fresca con commit de referencia al SHA de origen en ai-parrot? Propuesta: copia fresca
  (simple, la historia queda en ai-parrot). — *Owner: Jesus*
- [ ] Versionado del paquete: ¿arrancar en `0.1.0` con la fase 1 y `1.0.0` cuando
  ai-parrot migre (fase 3 verde)? ¿Publicación PyPI pública o índice privado? — *Owner: Jesus*
- [ ] `TOPICS.md` (governanza de namespaces `agent.*`/`task.*`/`auth.*` propuesta en
  brainstorm-eventbus-v2): ¿nace con la fase 1 en el repo nuevo? — *Owner: Jesus*
- [x] ¿Import name? — *Owner: Jesus*: `navigator_eventbus` (plano); `navigator.eventbus`
  PEP 420 inviable por `navigator/__init__.py` regular.
- [x] ¿Dónde vive NotificationSubscriber? — *Owner: Jesus*: en el core, con sender por
  defecto sobre `notify` (async-notify); sigue aceptando senders inyectados.
- [x] ¿Distribución durante el desarrollo? — *Owner: Jesus*: editable local
  (`uv pip install -e`); PyPI al pasar la suite completa de ai-parrot.
- [x] ¿Qué se hace con la rama copilot del repo destino? — *Owner: Jesus*: ignorarla;
  FEAT-310 es la fuente canónica.
