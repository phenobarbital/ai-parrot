# TASK-1799: Mudar EventEnvelope/Severity + helper de serialización JSONContent

**Feature**: FEAT-312 — EventBus Core Extraction → `navigator-eventbus`
**Spec**: `sdd/specs/eventbus-core-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1798
**Assigned-to**: unassigned

---

## Context

Module 2 del spec. El envelope es el contrato de wire de todo el fabric —
se muda primero porque core, backends, converters y subscribers lo importan.
Añade el helper de serialización (decisión de brainstorm: JSON vía
`JSONContent`/orjson por defecto, cloudpickle opcional) y el util
`lazy_import` local que desacopla `hooks/scheduler.py` de `parrot._imports`.

## Scope

- Copiar `parrot/core/events/bus/envelope.py` → `src/navigator_eventbus/envelope.py`
  **sin cambios de comportamiento** (frozen dataclass, rechazo de naive datetimes).
- Crear `src/navigator_eventbus/serialization.py`: funciones
  `dumps(obj) -> bytes` / `loads(data) -> Any` sobre
  `datamodel.parsers.json.JSONContent` (orjson); hook opcional cloudpickle
  (lazy import, error claro si no está instalado). Documentar que JSON es el
  baseline y cloudpickle es opt-in.
- Crear `src/navigator_eventbus/_imports.py` con `lazy_import` replicando la
  semántica de `parrot._imports.lazy_import` (leer el original y copiar la
  función; es un util pequeño).
- Añadir re-exports a `src/navigator_eventbus/__init__.py`:
  `EventEnvelope`, `Severity`.
- Mudar los tests del envelope de la suite de ai-parrot y añadir
  `test_serialization_jsoncontent_roundtrip`.

**NOT in scope**: BusCore/facade (TASK-1800); backends (TASK-1801);
uso de cloudpickle en brokers (fase 3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/envelope.py` | CREATE | copia de bus/envelope.py |
| `src/navigator_eventbus/serialization.py` | CREATE | JSONContent default + cloudpickle opt-in |
| `src/navigator_eventbus/_imports.py` | CREATE | lazy_import local |
| `src/navigator_eventbus/__init__.py` | MODIFY | re-exports |
| `tests/test_envelope.py`, `tests/test_serialization.py` | CREATE | suite mudada + roundtrip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from datamodel.parsers.json import JSONContent  # verificado 2026-07-17 en .venv
```

### Existing Signatures to Use
```python
# ORIGEN (copiar de): /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/src/parrot/core/events/bus/envelope.py
class Severity(IntEnum): ...                    # línea 21 — DEBUG=10, INFO=20, WARNING=30, ERROR=40, CRITICAL=50
@dataclass(frozen=True, slots=True)
class EventEnvelope:                            # línea 38
    # topic, payload, event_id, timestamp (tz-aware, rechaza naive ~:72),
    # source, severity, priority, correlation_id, trace_context, metadata
    def to_dict(self) -> dict[str, Any]: ...    # línea 92
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope": ...  # línea 115

# ORIGEN del util: /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/src/parrot/_imports.py
#   función lazy_import — leerla y replicarla (usada por hooks/scheduler.py:8)

# Tests origen: /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/tests/core/events/
#   (localizar los del envelope con grep "EventEnvelope" en ese árbol)
```

### Does NOT Exist
- ~~`EventEnvelope` como Pydantic model~~ — es frozen dataclass (decisión
  brainstorm-eventbus-v2: hot path; NO convertir a Pydantic).
- ~~`schema_version` field implementado~~ — decidido en brainstorm v2 pero NO
  existe aún en el envelope de FEAT-310; NO añadirlo en esta mudanza (copia
  fiel; el campo llega como cambio separado si se prioriza).
- ~~`orjson` como dependencia directa~~ — llega vía `datamodel` (`JSONContent`);
  no declarar orjson en pyproject.
- ~~`msgpack` en esta fase~~ — opcional, llega con brokers (fase 3).

---

## Implementation Notes

### Key Constraints
- Copia fiel del envelope: mismos campos, mismos defaults, misma validación.
  El único cambio permitido es el header del módulo (docstring de procedencia).
- `serialization.dumps` debe serializar `EventEnvelope.to_dict()` sin
  transformación extra; roundtrip exacto (timestamps ISO-8601 tz-aware).
- cloudpickle: `try: import cloudpickle except ImportError: raise RuntimeError("install navigator-eventbus[pickle]")` — patrón lazy-guarded.

### References in Codebase
- Origen envelope: `packages/ai-parrot/src/parrot/core/events/bus/envelope.py`
- Patrón lazy-guarded: `packages/ai-parrot/src/parrot/core/events/bus/dlq.py:107-110`

---

## Acceptance Criteria

- [ ] `from navigator_eventbus import EventEnvelope, Severity` funciona
- [ ] Suite del envelope mudada y verde
- [ ] `test_serialization_jsoncontent_roundtrip` verde (envelope → bytes → envelope)
- [ ] Naive datetime sigue rechazado (test presente)
- [ ] `ruff check src/` y `mypy src/` limpios
- [ ] Cero referencias a `parrot.` en los archivos nuevos

---

## Test Specification

```python
# tests/test_serialization.py
from datetime import datetime, timezone
from navigator_eventbus import EventEnvelope, Severity
from navigator_eventbus.serialization import dumps, loads


def test_serialization_jsoncontent_roundtrip():
    env = EventEnvelope(topic="test.topic", payload={"a": 1},
                        severity=Severity.INFO)
    data = dumps(env.to_dict())
    assert isinstance(data, (bytes, str))
    restored = EventEnvelope.from_dict(loads(data))
    assert restored.topic == env.topic
    assert restored.payload == {"a": 1}
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/eventbus-core-extraction.spec.md`, repo ai-parrot).
2. Verifica que TASK-1798 está en `sdd/tasks/completed/`.
3. Trabaja en el repo navigator-eventbus, rama `feat-FEAT-312-eventbus-core-extraction`.
4. Verify the Codebase Contract (lee el envelope de origen ANTES de copiar).
5. Update index status → in-progress / done en ai-parrot `dev`.
6. Commit: `feat: envelope + serialization (FEAT-312 TASK-1799)`.
7. Move este archivo a `sdd/tasks/completed/` + Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-17
**Notes**: envelope.py/serialization.py/_imports.py were already committed
to navigator-eventbus (commit 2dfd57b "wip: FEAT-312 new navigator Event
Bus") from an earlier partial pass; this close-out verified them against
the origin `packages/ai-parrot/src/parrot/core/events/bus/envelope.py`
line-for-line (frozen dataclass, tz-aware validation, `to_dict`/`from_dict`
unchanged) and confirmed `serialization.py` (JSONContent/orjson default +
lazy-guarded cloudpickle opt-in) and `_imports.py` (local `lazy_import`
replica) match the task's Codebase Contract. Added the migrated test
suite (`tests/test_envelope.py`, `tests/test_serialization.py`) and
confirmed `ruff check src/`/`mypy src/` clean and
`from navigator_eventbus import EventEnvelope, Severity` resolves —
committed in navigator-eventbus as
505d5ff "feat: reconcile envelope/serialization + bus core/facade/
converters/dlq/ingress-models (FEAT-312 TASK-1799, TASK-1800)".

**Deviations from spec**: none
