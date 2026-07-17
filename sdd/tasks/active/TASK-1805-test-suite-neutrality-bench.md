# TASK-1805: Completar migración de test suite, guard de neutralidad y benchmark

**Feature**: FEAT-312 — EventBus Core Extraction → `navigator-eventbus`
**Spec**: `sdd/specs/eventbus-core-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1801, TASK-1802, TASK-1803, TASK-1804
**Assigned-to**: unassigned

---

## Context

Module 8 — cierre de la fase 1. Los tasks anteriores mudaron tests por área;
este task barre lo que falte de la suite del bus de ai-parrot, añade el
guard de neutralidad (cero `parrot.` en `src/`), porta el benchmark de
overhead de FEAT-310 y deja el CI verde de punta a punta.

## Scope

- Auditar `packages/ai-parrot/tests/core/events/` (y grep por
  `EventBus|BusCore|HookManager` en todo `tests/` de ai-parrot) contra la
  suite ya mudada; portar los tests del alcance que falten (bus, backends,
  subscribers, ingress, hooks genéricos). Los tests de lifecycle/typed
  events NO se portan (fase 2).
- Implementar `test_no_parrot_imports`: escanea `src/navigator_eventbus/`
  y falla si encuentra `from parrot` / `import parrot` (los lazy
  `navigator.brokers` están permitidos en fase 1).
- Añadir el mismo guard como step de CI (grep) en `ci.yml`.
- Portar `scripts/bench/feat310_emit_overhead.py` de ai-parrot →
  `scripts/bench_emit_overhead.py` del paquete (imports nuevos); ejecutarlo
  y registrar el resultado en la Completion Note comparado con el baseline
  FEAT-310 (misma máquina).
- Revisar el `conftest.py` del paquete: eliminar cualquier stub heredado de
  parrot (`sys.modules["parrot.notifications"]` etc. — origen
  `tests/conftest.py:342-345` de ai-parrot).
- `README.md`: sección de configuración (todas las claves `BUS_*` +
  `EVB_DSN` + prefijos) y nota prominente sobre defaults neutros vs
  despliegues legacy `parrot:*`.
- Verificación final de TODOS los Acceptance Criteria del spec §5
  (checklist en la Completion Note).

**NOT in scope**: publicación PyPI; migración de ai-parrot (fase 4);
benchmark FEAT-177 completo de lifecycle (fase 2/4 — aquí solo emit-overhead).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/**` (repo navigator-eventbus) | CREATE/MODIFY | tests faltantes + guard |
| `tests/test_neutrality.py` | CREATE | test_no_parrot_imports |
| `.github/workflows/ci.yml` | MODIFY | step grep de neutralidad |
| `scripts/bench_emit_overhead.py` | CREATE | port del benchmark |
| `README.md` | MODIFY | config reference + nota prefijos |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Todo el paquete ya disponible (TASK-1799..1804):
from navigator_eventbus import EventBus, EventEnvelope, Severity, BusCore
from navigator_eventbus.backends import MemoryBackend
from navigator_eventbus.hooks import HookManager
```

### Existing Signatures to Use
```python
# Benchmark origen: /home/jesuslara/proyectos/ai-parrot/scripts/bench/feat310_emit_overhead.py
#   (instancia EventBus con queue_size — línea ~43; leerlo entero antes de portar)
# Suite origen: /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/tests/core/events/
# Stub a eliminar: /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/tests/conftest.py:342-345
#   (inyecta parrot.notifications fake en sys.modules)
# Claves de config a documentar (origen evb.py:121-129, notification.py:127-133,
#   websocket.py:60): BUS_WORKERS, BUS_QUEUE_SIZE, BUS_HANDLER_TIMEOUT,
#   BUS_RETRY_ATTEMPTS, BUS_RETRY_BASE_DELAY, BUS_DEFAULT_BACKPRESSURE,
#   BUS_DRAIN_TIMEOUT, BUS_ALERTS_*, BUS_INGRESS_TOKEN
#   + nuevas del paquete: BUS_CHANNEL_PREFIX, BUS_STREAM_PREFIX, BUS_DEDUP_PREFIX,
#   BUS_GROUP, EVB_DSN
```

### Does NOT Exist
- ~~Baseline de benchmark publicado~~ — el número de referencia se obtiene
  ejecutando el script origen en ai-parrot en la misma máquina; no hay CI
  de performance.
- ~~Tests de lifecycle en el alcance~~ — `tests/unit/events/lifecycle/` de
  ai-parrot se parte en la fase 2; NO portarlos aquí.
- ~~`pytest-benchmark` como dependencia~~ — el script de bench es standalone
  (asyncio + time), no un plugin de pytest.

---

## Implementation Notes

### Pattern to Follow
```python
# tests/test_neutrality.py
import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "navigator_eventbus"
FORBIDDEN = re.compile(r"^\s*(from|import)\s+parrot(\.|\s|$)", re.MULTILINE)


def test_no_parrot_imports():
    offenders = [p for p in SRC.rglob("*.py")
                 if FORBIDDEN.search(p.read_text())]
    assert not offenders, f"parrot imports found: {offenders}"
```

### Key Constraints
- El CI debe pasar completo en el repo nuevo sin servicios externos
  (redis tests skipeados por marca).
- El benchmark NO es un test de CI — es evidencia manual para la
  Completion Note (criterio del spec: sin regresión vs FEAT-310).

### References in Codebase
- Spec §5 Acceptance Criteria — checklist completo a verificar.

---

## Acceptance Criteria

- [ ] Cobertura de la suite del bus portada (auditoría documentada: qué se
      portó, qué quedó en ai-parrot y por qué)
- [ ] `test_no_parrot_imports` verde + step CI equivalente
- [ ] `pytest tests/ -v` completo verde; CI verde
- [ ] Benchmark emit-overhead ejecutado; resultado y comparación en la Completion Note
- [ ] README con referencia de configuración completa
- [ ] TODOS los criterios del spec §5 verificados y marcados

---

## Test Specification

(ver Pattern to Follow — el guard de neutralidad es el test nuevo principal;
el resto es porte de la suite existente)

---

## Agent Instructions

1. Read the spec §5 — este task cierra la fase; todos los criterios cuentan.
2. Verifica TASK-1801..1804 en `completed/`.
3. Repo navigator-eventbus, rama `feat-FEAT-312-eventbus-core-extraction`.
4. Update index en ai-parrot `dev`; commit
   `test: suite completion + neutrality guard + bench (FEAT-312 TASK-1805)`;
   move a `completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
