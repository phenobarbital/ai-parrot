# TASK-1803: Mudar hooks genéricos + HookTypeRegistry (tipo abierto)

**Feature**: FEAT-312 — EventBus Core Extraction → `navigator-eventbus`
**Spec**: `sdd/specs/eventbus-core-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1800
**Assigned-to**: unassigned

---

## Context

Module 6 del spec y el único cambio de contrato de la fase: `HookType` deja
de ser un enum cerrado y pasa a **tipo abierto** (str validado + registry
dinámico), para que cada app registre sus hook types sin tocar el core
(decisión de brainstorm). Se mudan los módulos genéricos de hooks; los hooks
de integración parrot (jira, github, sharepoint, whatsapp, matrix, imap,
messaging, postgres, file_upload) NO se mudan.

## Scope

- Copiar a `src/navigator_eventbus/hooks/`:
  `base.py` (HookRegistry, BaseHook), `manager.py` (HookManager),
  `models.py` (**entero** — HookEvent + TODOS los config models, incluidos
  los de integraciones parrot: decisión de brainstorm), `mixins.py`,
  `scheduler.py`, `file_watchdog.py`, y `brokers/{base,redis,rabbitmq,sqs,mqtt}.py`.
- **`HookTypeRegistry`** (nuevo, en `models.py` o módulo propio
  `hooks/registry.py`):
  - `register(name: str) -> str` — valida slug (`^[a-z][a-z0-9_]*$`),
    idempotente, retorna el nombre.
  - `is_registered(name) -> bool`, `all() -> frozenset[str]`.
  - Singleton de módulo `HOOK_TYPES` pre-poblado con los genéricos:
    `scheduler`, `file_watchdog`, `postgres_listen`, `imap_watchdog`,
    `file_upload`, `broker_redis`, `broker_rabbitmq`, `broker_mqtt`,
    `broker_sqs`, `filesystem`, `jira_webhook`, `github_webhook`,
    `sharepoint`, `telegram`, `whatsapp`, `msteams`, `whatsapp_redis`,
    `matrix` — **los 18 miembros actuales se pre-registran** para
    compatibilidad total (la fase 4 decide cuáles pasan a registro per-app);
    el mecanismo de registro dinámico es lo que habilita tipos nuevos.
  - Compat: mantener un alias `HookType` exportado cuyo acceso por atributo
    siga funcionando para los 18 nombres actuales
    (p.ej. `HookType.SCHEDULER == "scheduler"` — puede ser una clase de
    constantes str), para minimizar el diff de la fase 4.
- `HookEvent.hook_type` pasa de `HookType` a `str` con validator Pydantic
  contra `HOOK_TYPES`; los config models que tipan `hook_type` igual.
- `scheduler.py`: cambiar `from parrot._imports import lazy_import` →
  `from navigator_eventbus._imports import lazy_import` (TASK-1799).
- Hooks de brokers: los lazy-imports a `navigator.brokers.*` y `gmqtt` se
  conservan TAL CUAL (la fase 3 los recablea a la capa interna).
- Mudar tests de hooks genéricos; añadir tests del registry (pre-poblado,
  registro dinámico, rechazo de no-registrados, idempotencia).

**NOT in scope**: hooks de integración parrot; port de `navigator.brokers`
(fase 3); `route_to_bus` cambios de comportamiento (se copia tal cual).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/hooks/base.py` | CREATE | HookRegistry + BaseHook |
| `src/navigator_eventbus/hooks/manager.py` | CREATE | HookManager |
| `src/navigator_eventbus/hooks/models.py` | CREATE | modelos + hook_type abierto |
| `src/navigator_eventbus/hooks/registry.py` | CREATE | HookTypeRegistry + HOOK_TYPES |
| `src/navigator_eventbus/hooks/mixins.py` | CREATE | copia |
| `src/navigator_eventbus/hooks/scheduler.py` | CREATE | copia + _imports local |
| `src/navigator_eventbus/hooks/file_watchdog.py` | CREATE | copia |
| `src/navigator_eventbus/hooks/brokers/{base,redis,rabbitmq,sqs,mqtt}.py` | CREATE | copia (lazy navigator.brokers intacto) |
| `src/navigator_eventbus/hooks/__init__.py` | MODIFY | exports |
| `src/navigator_eventbus/converters.py` | MODIFY | activar import real de HookEvent (quitar el lazy/skip de TASK-1800) |
| `tests/test_hooks_*.py`, `tests/test_hook_type_registry.py` | CREATE | suite + registry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_eventbus._imports import lazy_import      # TASK-1799
from navigator_eventbus.envelope import EventEnvelope    # TASK-1799
from navigator_eventbus.evb import EventBus              # TASK-1800 (manager type hints)
```

### Existing Signatures to Use
```python
# ORIGEN: packages/ai-parrot/src/parrot/core/hooks/models.py
class HookType(str, Enum):                    # línea 9 — 18 miembros (líneas 11-28):
#   SCHEDULER, FILE_WATCHDOG, POSTGRES_LISTEN, IMAP_WATCHDOG, JIRA_WEBHOOK,
#   GITHUB_WEBHOOK, FILE_UPLOAD, BROKER_REDIS, BROKER_RABBITMQ, BROKER_MQTT,
#   BROKER_SQS, SHAREPOINT, TELEGRAM, WHATSAPP, MSTEAMS, WHATSAPP_REDIS,
#   MATRIX, FILESYSTEM
class HookEvent(BaseModel):                   # línea 31 — hook_type: HookType ← pasa a str validado
# models.py contiene además config models (SchedulerHookConfig, BrokerHookConfig,
#   configs de Jira/GitHub/SharePoint/WhatsApp/Matrix...) — leer entero; TODO se muda.

# ORIGEN: packages/ai-parrot/src/parrot/core/hooks/base.py
class HookRegistry:                           # línea 39 — registro por classmethod
#   en import-time (líneas 55-72) — los hooks parrot NO mudados deben poder
#   seguir registrándose contra este registry en la fase 4: no romper el mecanismo.
class BaseHook(ABC):                          # línea 96
    async def start(self) -> None: ...        # abstracto (~línea 169)
    async def stop(self) -> None: ...         # abstracto (~línea 173)
    def setup_routes(self, app) -> None: ...  # (~línea 176)

# ORIGEN: packages/ai-parrot/src/parrot/core/hooks/manager.py
class HookManager:                            # línea 15
    def __init__(self, *, route_to_bus: bool = False)   # línea 40
    def set_event_bus(self, bus) -> None                # línea 70
    # _publish_hook_event → topic f"hooks.{type}.{event}" (líneas 127, 138)

# ORIGEN: packages/ai-parrot/src/parrot/core/hooks/scheduler.py
from parrot._imports import lazy_import      # línea 8 ← ÚNICO acople duro a cambiar

# ORIGEN hooks/brokers/ — lazy imports a conservar:
from navigator.brokers.redis import RedisConnection       # brokers/redis.py:21
from navigator.brokers.rabbitmq import RabbitMQConnection  # brokers/rabbitmq.py:23
from navigator.brokers.sqs import SQSConnection            # brokers/sqs.py:22
from gmqtt import Client as MQTTClient                     # brokers/mqtt.py:22
```

### Does NOT Exist
- ~~`HookTypeRegistry` en el origen~~ — es NUEVO; el diseño está en el spec
  §2 Data Models.
- ~~Subclaseo de `str, Enum` con miembros nuevos~~ — Python no lo permite;
  esa es la razón del registry (no intentar heredar del enum).
- ~~Broker MQTT en `navigator.brokers`~~ — no existe; el hook mqtt usa
  `gmqtt` directo.
- ~~`route_to_bus=True` como default~~ — el default del origen es `False`;
  copiar tal cual.
- ~~Hooks de integración parrot en el paquete~~ — jira/github/sharepoint/
  whatsapp_redis/matrix/imap/messaging/postgres/file_upload NO se mudan
  (quedan en ai-parrot, fase 4 los recablea).

---

## Implementation Notes

### Pattern to Follow
```python
# hooks/registry.py — diseño del spec §2:
class HookTypeRegistry:
    def __init__(self) -> None:
        self._types: set[str] = set()

    def register(self, name: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError(f"invalid hook type slug: {name!r}")
        self._types.add(name)
        return name

HOOK_TYPES = HookTypeRegistry()
# pre-población de los 18 + validator Pydantic en HookEvent:
#   @field_validator("hook_type")  → HOOK_TYPES.is_registered(v) o ValueError
```

### Key Constraints
- `HookManager.set_event_bus/route_to_bus` firmas idénticas (criterio del spec).
- El alias de compat `HookType.X` debe producir el mismo valor str que el
  enum actual (los tests mudados que comparan `HookType.SCHEDULER` deben
  pasar con cambios mínimos).
- Exponer un mecanismo de limpieza/aislamiento del registry para tests
  (fixture que desregistra tipos de prueba).

### References in Codebase
- Origen: `packages/ai-parrot/src/parrot/core/hooks/`
- Tests origen: `packages/ai-parrot/tests/` (grep "HookManager\|HookEvent\|HookType")

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.hooks import HookManager, BaseHook, HookRegistry` funciona
- [ ] `from navigator_eventbus.hooks.models import HookEvent, HOOK_TYPES` funciona
- [ ] Los 18 hook types actuales pre-registrados; `HookType.SCHEDULER == "scheduler"` (compat)
- [ ] `HOOK_TYPES.register("custom_x")` habilita `HookEvent(hook_type="custom_x", ...)`
- [ ] `HookEvent(hook_type="not_registered", ...)` → ValidationError
- [ ] `converters.py` con import real de HookEvent; test del converter de hooks des-skipeado y verde
- [ ] `test_hookmanager_route_to_bus` (topic `hooks.<type>.<event>`) verde
- [ ] `ruff` + `mypy` limpios; cero `parrot.` en `src/` (los lazy `navigator.brokers` sí se permiten)

---

## Test Specification

```python
# tests/test_hook_type_registry.py
import pytest
from pydantic import ValidationError
from navigator_eventbus.hooks.models import HookEvent, HOOK_TYPES


def test_generics_prepopulated():
    assert HOOK_TYPES.is_registered("scheduler")
    assert HOOK_TYPES.is_registered("broker_redis")


def test_register_custom(custom_hook_type):
    ev = HookEvent(hook_id="h1", hook_type=custom_hook_type,
                   event_type="ping", payload={}, metadata={})
    assert ev.hook_type == custom_hook_type


def test_rejects_unregistered():
    with pytest.raises(ValidationError):
        HookEvent(hook_id="h1", hook_type="nope_never_registered",
                  event_type="ping", payload={}, metadata={})
```

---

## Agent Instructions

1. Read the spec; verifica TASK-1800 en `completed/`.
2. Repo navigator-eventbus, rama `feat-FEAT-312-eventbus-core-extraction`.
3. Verify the Codebase Contract — lee `models.py` de origen ENTERO (hay más
   config models de los listados aquí).
4. Update index en ai-parrot `dev`; commit
   `feat: generic hooks + HookTypeRegistry (FEAT-312 TASK-1803)`; move a `completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
