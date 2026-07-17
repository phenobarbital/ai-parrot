# TASK-1802: Mudar subscribers (notification con sender notify, audit, metrics)

**Feature**: FEAT-312 — EventBus Core Extraction → `navigator-eventbus`
**Spec**: `sdd/specs/eventbus-core-extraction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1800
**Assigned-to**: unassigned

---

## Context

Module 5 del spec. Los tres subscribers de egress del bus. Dos desacoples:
`NotificationSubscriber` gana un sender por defecto sobre la librería
`notify` (async-notify, extra `[notify]`) manteniendo la inyección
duck-typed actual; `AuditSubscriber` pierde el fallback a
`parrot.conf.default_dsn` (igual que el DLQ en TASK-1800).

## Scope

- Copiar `bus/subscribers/{notification,audit,metrics}.py` →
  `src/navigator_eventbus/subscribers/` con imports intra-paquete.
- `notification.py`: añadir factory de sender por defecto sobre `notify`
  (lazy-guarded, error claro si el extra no está instalado) cuando no se
  inyecta sender. La firma `__init__(self, sender, *, rules=None,
  config=None, send_timeout=10.0)` se relaja a `sender=None` → default
  notify. El sender inyectado duck-typed (`await sender.send_notification(...)`)
  sigue funcionando sin cambios.
- `audit.py`: eliminar lazy-import de `parrot.conf.default_dsn`
  (líneas 89-90 del origen); fallback → navconfig (`EVB_DSN`, misma clave
  que el DLQ de TASK-1800) o parámetro.
- `subscribers/__init__.py`: exports (verificar nombres en el origen).
- Mudar tests; el conftest de origen inyecta un stub `parrot.notifications`
  en sys.modules (`tests/conftest.py:342-345` de ai-parrot) — NO replicar
  ese stub; los tests del paquete usan senders fake inyectados directamente.

**NOT in scope**: reglas de rate-limiting/dedup de alertas (pregunta abierta
de brainstorm-v2, spec posterior); `AlertsConfig` cambia solo lo mínimo
(sigue leyendo `BUS_ALERTS_*`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/subscribers/notification.py` | CREATE | copia + default sender notify |
| `src/navigator_eventbus/subscribers/audit.py` | CREATE | copia + DSN navconfig/param |
| `src/navigator_eventbus/subscribers/metrics.py` | CREATE | copia |
| `src/navigator_eventbus/subscribers/__init__.py` | MODIFY | exports |
| `tests/test_subscribers_*.py` | CREATE | suite mudada sin stubs parrot |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_eventbus.envelope import EventEnvelope, Severity  # TASK-1799
from navigator_eventbus.core import BusCore                      # TASK-1800
import notify   # async-notify 1.5.7 — verificado en .venv; extra [notify], lazy import
```

### Existing Signatures to Use
```python
# ORIGEN: packages/ai-parrot/src/parrot/core/events/bus/subscribers/notification.py
class AlertsConfig(BaseModel): ...                 # línea 81
#   AlertsConfig.from_navconfig() lee BUS_ALERTS_* (líneas ~127-133)
class NotificationSubscriber:                      # línea 169
    def __init__(self, sender, *, rules=None, config=None,
                 send_timeout: float = 10.0) -> None   # línea 186
    # sender duck-typed: await self._sender.send_notification(...)  (~línea 444)

# ORIGEN: packages/ai-parrot/src/parrot/core/events/bus/subscribers/audit.py
class AuditSubscriber:                             # línea 59
    AUDIT_TABLE = "navigator.evb_audit"            # línea 30 — NO cambiar
    # líneas 89-90: from parrot.conf import default_dsn ← ELIMINAR (desacople)
    # cola bounded + drop-oldest + filtro por topic pattern — copiar tal cual

# ORIGEN: packages/ai-parrot/src/parrot/core/events/bus/subscribers/metrics.py
#   leer entero antes de copiar (sin acoples parrot conocidos)
```

### Does NOT Exist
- ~~Import de `parrot.notifications` en NotificationSubscriber~~ — el sender
  es inyectado; el stub de sys.modules vive solo en el conftest de ai-parrot.
- ~~API estable asumida de `notify`~~ — verificar la API real de async-notify
  1.5.7 (leer su código en el venv) antes de escribir el default sender; NO
  asumir `Notify().send(...)` sin comprobar.
- ~~Refactor a AbstractLedger~~ — decidido en brainstorm-v2 pero es trabajo
  de specs posteriores (1b/3); `AuditSubscriber` se copia con su cola
  hand-rolled actual.

---

## Implementation Notes

### Pattern to Follow
```python
# Default sender lazy-guarded (mismo patrón que dlq.py:107-110 del origen):
def _default_notify_sender():
    try:
        from notify import Notify  # verificar el símbolo real en el venv
    except ImportError as exc:
        raise RuntimeError(
            "NotificationSubscriber default sender requires "
            "'navigator-eventbus[notify]'"
        ) from exc
    ...
```

### Key Constraints
- Sender inyectado tiene precedencia; el default solo se construye si
  `sender is None`.
- `AUDIT_TABLE`/`DLQ_TABLE` conservan el schema `navigator.*`.
- Semántica de cola del audit (bounded, drop-oldest) intacta.

### References in Codebase
- Origen: `packages/ai-parrot/src/parrot/core/events/bus/subscribers/`
- Stub a NO replicar: `packages/ai-parrot/tests/conftest.py:342-345`
- API notify: `.venv/lib/python3.*/site-packages/notify/` (leer)

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.subscribers import NotificationSubscriber, AuditSubscriber` funciona
- [ ] Sender inyectado duck-typed sigue funcionando (tests mudados verdes)
- [ ] `NotificationSubscriber()` sin sender + extra notify instalado → default notify sender
- [ ] Sin extra notify → RuntimeError con mensaje de install claro
- [ ] AuditSubscriber acepta DSN por parámetro; cero `parrot.conf`
- [ ] `ruff` + `mypy` limpios; cero `parrot.` en `src/`

---

## Test Specification

```python
# tests/test_subscribers_notification.py (extracto)
import pytest
from navigator_eventbus.subscribers.notification import NotificationSubscriber


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send_notification(self, *args, **kwargs):
        self.sent.append((args, kwargs))


async def test_injected_sender_still_works(bus_with_worker):
    sender = FakeSender()
    sub = NotificationSubscriber(sender)
    # ... attach al bus, emitir ERROR, assert sender.sent
```

---

## Agent Instructions

1. Read the spec; verifica TASK-1800 en `completed/`.
2. Repo navigator-eventbus, rama `feat-FEAT-312-eventbus-core-extraction`.
3. Verify the Codebase Contract — en especial la API real de `notify`.
4. Update index en ai-parrot `dev`; commit
   `feat: subscribers (FEAT-312 TASK-1802)`; move a `completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
