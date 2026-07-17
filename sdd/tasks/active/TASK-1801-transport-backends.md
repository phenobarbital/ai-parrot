# TASK-1801: Mudar transport backends (memory, redis pub/sub, redis streams) con prefijos neutros

**Feature**: FEAT-312 — EventBus Core Extraction → `navigator-eventbus`
**Spec**: `sdd/specs/eventbus-core-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1800
**Assigned-to**: unassigned

---

## Context

Module 4 del spec. Los tres backends de transporte + el Protocol. Desacople:
prefijos Redis y consumer-group pasan a defaults neutros (`evb:*`, `evb-bus`)
configurables por constructor y navconfig — ai-parrot fijará los legacy
`parrot:*` en la fase 4.

## Scope

- Copiar `bus/backends/{base,memory,redis_pubsub,redis_streams}.py` →
  `src/navigator_eventbus/backends/` con imports intra-paquete.
- `redis_streams.py`: `STREAM_PREFIX` default `"evb:stream:"`,
  `DEDUP_PREFIX` default `"evb:events:dedup:"`, consumer-group default
  `"evb-bus"` — los tres configurables por constructor (ya lo son en parte;
  verificar) y por navconfig (`BUS_STREAM_PREFIX`, `BUS_DEDUP_PREFIX`,
  `BUS_GROUP`).
- `redis_pubsub.py`: prefijo de canal heredado de la facade
  (`channel_prefix` de TASK-1800) — verificar en el origen cómo se compone
  y mantener la composición.
- `backends/__init__.py`: exports `TransportBackend`, `MemoryBackend`,
  `RedisPubSubBackend`, `RedisStreamsBackend` (verificar nombres exactos en
  el `__init__.py` de origen).
- Mudar tests de backends; los que requieren Redis se marcan
  (`pytest.mark.redis` o skipif sin servidor). Añadir asserts de prefijos
  neutros/override.

**NOT in scope**: consolidación con el consumer de `navigator.brokers`
(spec post-migración); cambios a la lógica XADD/XREADGROUP/XAUTOCLAIM.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/backends/base.py` | CREATE | TransportBackend Protocol |
| `src/navigator_eventbus/backends/memory.py` | CREATE | copia |
| `src/navigator_eventbus/backends/redis_pubsub.py` | CREATE | copia + prefijo neutro |
| `src/navigator_eventbus/backends/redis_streams.py` | CREATE | copia + 3 knobs neutros |
| `src/navigator_eventbus/backends/__init__.py` | MODIFY | exports |
| `tests/test_backends*.py` | CREATE | suite mudada + prefijos |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_eventbus.envelope import EventEnvelope   # TASK-1799
import redis.asyncio as aioredis                         # extra [redis]; patrón del origen
```

### Existing Signatures to Use
```python
# ORIGEN: packages/ai-parrot/src/parrot/core/events/bus/backends/base.py
@runtime_checkable
class TransportBackend(Protocol):                  # línea 25
    async def publish(self, envelope) -> None: ...
    async def start_consumer(self, on_envelope) -> None: ...
    async def close(self) -> None: ...

# ORIGEN: packages/ai-parrot/src/parrot/core/events/bus/backends/redis_streams.py
class RedisStreamsBackend:                         # línea 55
    STREAM_PREFIX = "parrot:stream:"               # línea 81 ← "evb:stream:"
    DEDUP_PREFIX = "parrot:events:dedup:"          # línea 82 ← "evb:events:dedup:"
    # consumer group "parrot-bus" (docstring línea 13, param group línea ~62/89) ← "evb-bus"
    # XAUTOCLAIM sweeper para mensajes stuck: línea ~269 — NO tocar la lógica

# ORIGEN backends/__init__.py: verificar exports exactos con read antes de replicar
```

### Does NOT Exist
- ~~Backend RabbitMQ/NATS~~ — solo memory/pubsub/streams; los demás son
  future drop-ins (no crear stubs).
- ~~Dedup en pubsub/memory~~ — el dedup set TTL solo existe en streams.
- ~~`BUS_STREAM_PREFIX`/`BUS_DEDUP_PREFIX`/`BUS_GROUP` en el origen~~ —
  claves navconfig NUEVAS del paquete; documentar en README.

---

## Implementation Notes

### Key Constraints
- Copia fiel de la lógica: XADD/XREADGROUP/XACK/XAUTOCLAIM, dedup TTL,
  reconnect con backoff — cero cambios de comportamiento.
- Los defaults neutros NO deben romper los tests mudados: los tests que
  asuman `parrot:*` se actualizan a los nuevos defaults (y se añade el test
  de override con `parrot:*`).
- redis es extra: los módulos redis se importan lazy-guarded como en el
  origen (verificar el patrón al leer).

### References in Codebase
- Origen: `packages/ai-parrot/src/parrot/core/events/bus/backends/`
- Tests origen: `packages/ai-parrot/tests/core/events/` (grep "Backend")

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.backends import MemoryBackend, RedisStreamsBackend, TransportBackend` funciona
- [ ] Defaults: `evb:stream:` / `evb:events:dedup:` / grupo `evb-bus`
- [ ] Override por constructor Y navconfig probado (valores `parrot:*`)
- [ ] `test_end_to_end_memory_bus` (emit → workers → subscriber con MemoryBackend) verde
- [ ] Tests redis marcados y skipeados sin servidor; verdes con servidor local
- [ ] `ruff` + `mypy` limpios; cero `parrot.` en `src/`

---

## Test Specification

```python
# tests/test_backends_streams.py (extracto)
from navigator_eventbus.backends.redis_streams import RedisStreamsBackend


def test_streams_prefixes_default_neutral():
    b = RedisStreamsBackend(redis_url="redis://localhost:6379")
    assert b.STREAM_PREFIX == "evb:stream:" or b.stream_prefix == "evb:stream:"


def test_streams_prefixes_override():
    b = RedisStreamsBackend(redis_url="redis://localhost:6379",
                            stream_prefix="parrot:stream:", group="parrot-bus")
    assert b.stream_prefix == "parrot:stream:"
```

---

## Agent Instructions

1. Read the spec; verifica TASK-1800 en `completed/`.
2. Repo navigator-eventbus, rama `feat-FEAT-312-eventbus-core-extraction`.
3. Verify the Codebase Contract — lee cada backend de origen entero.
4. Update index en ai-parrot `dev`; commit
   `feat: transport backends (FEAT-312 TASK-1801)`; move a `completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
