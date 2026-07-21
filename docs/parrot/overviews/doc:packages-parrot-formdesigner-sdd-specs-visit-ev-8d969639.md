---
type: Wiki Overview
title: 'Feature Specification: Visit & Event Lifecycle (multi-shift)'
id: doc:packages-parrot-formdesigner-sdd-specs-visit-event-lifecycle-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Vision Legacy modela una Activity single-rep: un solo representante ejecuta'
---

---
type: feature
base_branch: dev
---

# Feature Specification: Visit & Event Lifecycle (multi-shift)

**Feature ID**: FEAT-303
**Date**: 2026-06-09
**Author**: Javier (T-ROC)
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

Vision Legacy modela una Activity single-rep: un solo representante ejecuta
un punto de venta en una visita sin estructura de turnos. Vision IQ extiende ese
modelo a un Event multi-shift donde varios miembros de staff cubren el mismo
punto de venta en turnos distintos, cada uno generando su propia recap
(FormResponse), reclamaciones de horas y media.

El objetivo de FEAT-303 es introducir en `parrot-formdesigner` las entidades de
ciclo de vida — **Event → Shift → Visit → FormResponse** — y el conjunto mínimo
de servicios y endpoints de API que permiten: crear un evento con uno o varios
turnos, registrar check-in/check-out con validación de geofence GPS, setear
Missed Reasons, y exportar las horas validadas hacia el motor de payroll
externo (Workday, FEAT-026/027 — reside en `ai-parrot`).

### Goals

- Modelo unificado `Event` (contenedor) → `Shift` (asignación por staff) →
  `Visit` (ejecución single-rep) → `FormSubmission` (respuesta de recap).
- Máquina de estados para `Event` y `Shift` (requested → scheduled →
  in_progress → completed | cancelled | missed).
- Check-in / check-out con validación de geofence y almacenamiento de GPS
  breadcrumb; bloqueo de submission si `gps_outside=True`.
- Missed Reasons: catálogo configurable por tenant; asignación a Visit cuando
  la fecha límite se supera sin recap.
- Ad hoc / guerilla stops: creación de Events no planificados desde la app.
- Horas GPS-validadas expuestas vía hook hacia Workday payroll y hacia el motor
  de claims (FEAT-304). El hook NO escribe directo en `troc.worked_hours`: el
  flujo de ejecución de referencia es Event (N shifts) → check-in en geofence →
  recap → check-out → `TimeCaptureRecord` → staging (`time_capture_staging`) →
  consolidación en `worked_hours` → attestation → aprobación de manager → sync
  Workday → conciliación por `time_block_wid`. El write-path vía staging es
  decisión [PROPUESTA — Review v2.1]; el detalle vive en FEAT-321.

### Non-Goals (explicitly out of scope)

- Motor de claims auto-generados (FEAT-304 — spec separado).
- Scheduling / calendar de turnos (FEAT-306 — spec separado).
- Evaluación server-side de fórmulas en recaps (FEAT-301 — spec separado).
- Integración directa con Workday API (FEAT-026/027 — vive en `ai-parrot`).
- UI de gestión de Events / calendar (fuera de este paquete).

---

## 2. Architectural Design

### Overview

La feature añade una nueva capa de servicios de ciclo de vida bajo
`services/visit/` dentro de `parrot-formdesigner`. Estos servicios orquestan la
relación Event → Shift → Visit y se integran con los servicios existentes
(`FormRegistry`, `FormSubmissionStorage`, `PartialSaveStore`) para vincular las
visitas con los recap forms.

Las API se exponen como nuevas rutas bajo `/api/v1/visits/` añadidas a
`api/handlers.py` y `api/routes.py`.

El geofence y el GPS breadcrumb son datos capturados en `Visit`; la lógica de
validación reside en `services/visit/geofence.py`. El hook de payroll escribe
en un bus de eventos (callback) hacia `ai-parrot`; en este paquete sólo se
define la interfaz del hook.

### Component Diagram

```
Event (services/visit/models.py)
  ├── status: EventStatus (requested|scheduled|in_progress|completed|cancelled|missed)
  ├── org_node_id: str                   ← FK store/program (FEAT-302 — Programs)
  ├── recap_ids: list[str]               ← FK FormSchema.form_id
  └── shifts: list[Shift]
        ├── status: ShiftStatus
        ├── staff_id: str                ← FK User (ai-parrot auth)
        └── visit: Visit | None
              ├── check_in / check_out: datetime + GpsCoord
              ├── missed_reason_id: str | None
              └── gps_breadcrumb: list[GpsCoord]

EventService (services/visit/event_service.py)     [NEW]
  ├── create_event(payload) → Event
  ├── get_event(event_id, tenant) → Event | None
  ├── list_events(tenant, **filters) → list[Event]
  └── transition(event_id, status, tenant) → Event

ShiftService (services/visit/shift_service.py)     [NEW]
  └── assign_staff(event_id, staff_id, tenant) → Shift

VisitService (services/visit/visit_service.py)     [NEW]
  ├── checkin(visit_id, gps_coord, tenant) → Visit
  ├── checkout(visit_id, gps_coord, recap_data, tenant) → Visit
  ├── set_missed_reason(visit_id, reason_id, tenant) → Visit
  └── create_adhoc(org_node_id, staff_id, tenant) → Event + Shift + Visit

GeofenceValidator (services/visit/geofence.py)     [NEW]
  └── validate(coord, event) → GeofenceResult (ok | outside | error)

MissedReasonService (services/visit/missed_reasons.py)  [NEW]
  ├── list_reasons(tenant) → list[MissedReason]
  ├── create_reason(payload, tenant) → MissedReason
  └── get_reason(reason_id, tenant) → MissedReason | None

PayrollHook (services/visit/payroll_hook.py)       [NEW — interface only]
  └── on_checkout(visit: Visit, tenant: str) → None  (fires async callback)

VisitAPIHandler (api/handlers.py)                  [EXTEND FormAPIHandler]
  ├── create_event(request)     POST /api/v1/visits/events
  ├── checkin(request)          POST /api/v1/visits/{id}/checkin
  ├── checkout(request)         POST /api/v1/visits/{id}/checkout
  └── set_missed(request)       POST /api/v1/visits/{id}/missed
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormSchema` (`core/schema.py`) | uses | `recap_ids` references `FormSchema.form_id`; recaps are loaded via `FormRegistry` |
| `FormSubmission` (`services/submissions.py`) | uses | `VisitService.checkout()` creates a `FormSubmission` linked to the Visit's shift |
| `FormSubmissionStorage` (`services/submissions.py`) | uses | Persists recap answers on checkout |
| `PartialSaveStore` (`services/partial_saves.py`) | uses | Auto-save recap answers during in-progress Visit |
| `FormRegistry` (`services/registry.py`) | uses | Load recap `FormSchema` definitions by `form_id` |
| `FormAPIHandler` (`api/handlers.py`) | extend | New visit-lifecycle handler methods added to the same class |
| `api/routes.py` | extend | Register four new `/api/v1/visits/...` routes |
| `AuthContext` (`services/auth_context.py`) | uses | Extract `staff_id` from JWT claims on check-in/out |

### Data Models

```python
# src/parrot_formdesigner/services/visit/models.py  (NEW)
from __future__ import annotations
from enum import Enum
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
import uuid


class EventStatus(str, Enum):
    REQUESTED   = "requested"
    SCHEDULED   = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"
    MISSED      = "missed"


class ShiftStatus(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    MISSED      = "missed"


class GpsCoord(BaseModel):
    """A single GPS coordinate sample."""
    lat: float
    lon: float
    accuracy_m: float | None = None
    recorded_at: datetime | None = None


class MissedReason(BaseModel):
    """Tenant-scoped catalogue entry for a Missed Reason."""
    reason_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    tenant: str
    active: bool = True


class Visit(BaseModel):
    """Single-rep execution record within a Shift."""
    visit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    shift_id: str
    check_in: datetime | None = None
    check_out: datetime | None = None
    check_in_coord: GpsCoord | None = None
    check_out_coord: GpsCoord | None = None
    gps_breadcrumb: list[GpsCoord] = Field(default_factory=list)
    missed_reason_id: str | None = None
    gps_outside: bool = False          # True → checkout is blocked
    submission_id: str | None = None   # FK FormSubmission.submission_id
    meta: dict[str, Any] | None = None
    tenant: str | None = None


class Shift(BaseModel):
    """Staff assignment within an Event."""
    shift_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    staff_id: str                       # FK User (ai-parrot auth)
    status: ShiftStatus = ShiftStatus.PENDING
    visit: Visit | None = None


class Event(BaseModel):
    """Top-level container representing a multi-shift execution at a location."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: EventStatus = EventStatus.REQUESTED
    org_node_id: str                    # FK store/program (FEAT-302)
    recap_ids: list[str] = Field(default_factory=list)  # FK FormSchema.form_id
    shifts: list[Shift] = Field(default_factory=list)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    is_adhoc: bool = False
    tenant: str | None = None
    meta: dict[str, Any] | None = None
```

```python
# src/parrot_formdesigner/services/visit/geofence.py  (NEW)
from enum import Enum
from pydantic import BaseModel

class GeofenceStatus(str, Enum):
    OK      = "ok"
    OUTSIDE = "outside"
    ERROR   = "error"

class GeofenceResult(BaseModel):
    status: GeofenceStatus
    distance_m: float | None = None
    message: str | None = None
```

### New Public Interfaces

```python
# services/visit/event_service.py
class EventService:
    def __init__(self, storage: EventStorage, registry: FormRegistry, *,
                 tenant: str) -> None: ...

    async def create_event(self, payload: dict) -> Event: ...
    async def get_event(self, event_id: str) -> Event | None: ...
    async def list_events(self, **filters) -> list[Event]: ...
    async def transition(self, event_id: str, status: EventStatus) -> Event: ...

# services/visit/visit_service.py
class VisitService:
    def __init__(self, event_service: EventService,
                 submission_storage: FormSubmissionStorage,
                 partial_save_store: PartialSaveStore,
                 geofence_validator: GeofenceValidator, *,
                 tenant: str) -> None: ...

    async def checkin(self, visit_id: str, coord: GpsCoord) -> Visit: ...
    async def checkout(self, visit_id: str, coord: GpsCoord,
                       recap_data: dict) -> Visit: ...
    async def set_missed_reason(self, visit_id: str, reason_id: str) -> Visit: ...
    async def create_adhoc(self, org_node_id: str, staff_id: str) -> Event: ...

# services/visit/payroll_hook.py
class PayrollHook:
    """Fire-and-forget async callback toward ai-parrot payroll bus."""
    async def on_checkout(self, visit: Visit, tenant: str) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: Event / Shift / Visit Data Models + State Machine (TASK-303-1)
- **Path**: `src/parrot_formdesigner/services/visit/models.py`,
  `src/parrot_formdesigner/services/visit/__init__.py`
- **Responsibility**: Define `Event`, `Shift`, `Visit`, `MissedReason`,
  `GpsCoord`, `EventStatus`, `ShiftStatus` Pydantic v2 models. Implement
  `EventService` with CRUD + state-machine transitions; `ShiftService` for
  staff assignment. Provide `EventStorage` ABC (mirrors `FormStorage` ABC
  pattern from `services/registry.py:50`).
  **Storage [RESUELTO §8]**: Event/Shift/Visit persist as a JSONB document in
  a `navigator.events` table, mirroring the `form_schemas` JSONB pattern of
  `PostgresFormStorage` (`services/storage.py`) — same DDL/identifier-safety
  approach.
  **No-overlap rule [RESUELTO §8]**: `ShiftService.assign_staff()` REJECTS a
  shift whose time window overlaps an existing active shift of the same rep
  (across any event) — raises a typed error; prevents double-counting hours.
- **Depends on**: `core/schema.py` (FormSchema, FormField),
  `services/registry.py` (FormRegistry)

### Module 2: Check-in / Check-out + Geofence Validation (TASK-303-2)
- **Path**: `src/parrot_formdesigner/services/visit/geofence.py`,
  `src/parrot_formdesigner/services/visit/visit_service.py`
- **Responsibility**: `GeofenceValidator` — haversine distance check against
  `Event.geofence_radius_m` (stored in `Event.meta`). `VisitService.checkin()`
  sets `check_in`, records `check_in_coord`, and starts `gps_breadcrumb`.
  `VisitService.checkout()` validates geofence (`gps_outside` flag), persists
  `FormSubmission` via `FormSubmissionStorage`, auto-saves recap with
  `PartialSaveStore`, and blocks submission if `gps_outside=True`.
- **Depends on**: Module 1, `services/submissions.py` (FormSubmissionStorage),
  `services/partial_saves.py` (PartialSaveStore)

### Module 3: Missed Reasons + Ad Hoc Stops (TASK-303-3)
- **Path**: `src/parrot_formdesigner/services/visit/missed_reasons.py`
- **Responsibility**: `MissedReasonService` with CRUD for tenant-scoped
  `MissedReason` catalogue. `VisitService.set_missed_reason()` assigns a reason
  to a Visit and transitions the Shift to `ShiftStatus.MISSED` and the Event
  to `EventStatus.MISSED` when all shifts are missed. `create_adhoc()` in
  `VisitService` creates an Event flagged `is_adhoc=True` with a single Shift
  and immediately starts the Visit.
- **Depends on**: Module 1

### Module 4: Payroll / Claims Hook Interface (TASK-303-4)
- **Path**: `src/parrot_formdesigner/services/visit/payroll_hook.py`
- **Responsibility**: `PayrollHook` abstract interface called by
  `VisitService.checkout()` after GPS-validated hours are computed. The
  concrete implementation (calling Workday via `ai-parrot`) is OUT OF SCOPE
  for this package; only the `PayrollHook` ABC and a no-op `NullPayrollHook`
  are implemented here. Dispatching to `FEAT-304` claims engine is done via the
  same hook pattern — implementers register their concrete hook at app startup.
  La implementación concreta downstream NO debe escribir directo en
  `troc.worked_hours`: pasa por staging (`time_capture_staging` →
  consolidación → `worked_hours` → attestation → aprobación → sync Workday →
  conciliación por `time_block_wid`) [PROPUESTA — Review v2.1], detalle en
  FEAT-321.
- **Depends on**: Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_event_create_with_shifts` | Module 1 | `EventService.create_event()` with N shifts produces `Event` with `len(shifts)==N` |
| `test_event_state_machine_valid` | Module 1 | Valid transitions (requested→scheduled→in_progress→completed) succeed |
| `test_event_state_machine_invalid` | Module 1 | Invalid transition raises `ValueError` |
| `test_shift_assign_staff` | Module 1 | `ShiftService.assign_staff()` returns `Shift` with correct `staff_id` |
| `test_visit_models_defaults` | Module 1 | `Visit` defaults: `gps_outside=False`, `breadcrumb=[]`, `submission_id=None` |
| `test_geofence_inside` | Module 2 | Coord within radius returns `GeofenceStatus.OK` |
| `test_geofence_outside` | Module 2 | Coord outside radius returns `GeofenceStatus.OUTSIDE` |
| `test_checkin_sets_timestamp` | Module 2 | `VisitService.checkin()` sets `Visit.check_in` and records coord |
| `test_checkout_blocked_outside_geofence` | Module 2 | `VisitService.checkout()` raises when `gps_outside=True` |
| `test_checkout_creates_submission` | Module 2 | `VisitService.checkout()` calls `FormSubmissionStorage.save()` and sets `Visit.submission_id` |
| `test_missed_reason_catalogue_crud` | Module 3 | Create, list, and get `MissedReason` entries per tenant |
| `test_set_missed_reason_transitions_shift` | Module 3 | Assigning missed reason transitions Shift → MISSED |
| `test_all_shifts_missed_transitions_event` | Module 3 | When all Shifts are MISSED, Event transitions to EventStatus.MISSED |
| `test_adhoc_event_flagged` | Module 3 | `create_adhoc()` returns Event with `is_adhoc=True` and one Shift |
| `test_payroll_hook_called_on_checkout` | Module 4 | `PayrollHook.on_checkout()` is invoked after valid checkout |
| `test_null_payroll_hook_noop` | Module 4 | `NullPayrollHook.on_checkout()` completes without error or side effects |

### Integration Tests

| Test | Description |
|---|---|
| `test_event_checkin_checkout_full_flow` | Create event → assign staff → checkin → checkout with recap data → assert `FormSubmission` persisted and `Visit.submission_id` set |
| `test_geofence_block_submission_end_to_end` | Create event with tight radius → checkin from coord just outside → assert `VisitService.checkout()` raises `GeofenceError` |
| `test_missed_event_full_flow` | Create multi-shift event → mark all shifts missed → assert Event.status == MISSED |
| `test_adhoc_event_submission` | `create_adhoc()` → checkin → checkout → assert submission stored with `is_adhoc=True` in `Event.meta` |

### Edge Cases [PROPUESTA — Review v2.1]

| Caso | Descripción |
|---|---|
| Shift que cruza medianoche / cambio de timezone del store | Check-in antes de medianoche y check-out después (o el store cambia de timezone, p.ej. DST): las horas calculadas y los timestamps de `Visit` deben mantenerse consistentes (almacenar en UTC + timezone del store). Añadir test `test_shift_crosses_midnight_timezone`. |
| Rep con dos shifts solapados en events distintos | [RESUELTO §8 — no se permite] `ShiftService.assign_staff()` rechaza un shift que solape en tiempo con otro shift activo del mismo rep (cualquier event) con error tipado; el test verifica el rechazo. |

### Test Data / Fixtures

```python
import pytest
from parrot_formdesigner.services.visit.models import (
    Event, Shift, Visit, GpsCoord, EventStatus, ShiftStatus
)

@pytest.fixture
def sample_gps_inside():
    """Coord inside the test geofence (centre: 40.7128, -74.0060, radius: 200m)."""
    return GpsCoord(lat=40.7129, lon=-74.0061)

@pytest.fixture
def sample_gps_outside():
    """Coord clearly outside the test geofence."""
    return GpsCoord(lat=40.7500, lon=-74.0500)

@pytest.fixture
def sample_event(tenant="epson"):
    return Event(
        org_node_id="store-001",
        recap_ids=["recap-form-001"],
        shifts=[
            Shift(event_id="evt-001", staff_id="staff-001"),
        ],
        meta={"geofence_lat": 40.7128, "geofence_lon": -74.0060,
              "geofence_radius_m": 200},
        tenant=tenant,
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All tests pass (`pytest tests/ -v`)
- [ ] Documentation updated: docstrings on all new public classes and methods
- [ ] No breaking changes to `FormSchema`, `FormRegistry`, `FormSubmissionStorage`,
  or any existing public API in `parrot_formdesigner`
- [ ] Un Event soporta N shifts con staff distinto; cada Shift genera un `Visit`
  vinculado a su `FormSubmission` de recap
- [ ] Submission bloqueado fuera del geofence (`gps_outside=True` → `VisitService.checkout()` raises)
- [ ] El catálogo de Missed Reasons es configurable por tenant; asignar uno a
  todos los Shifts de un Event transiciona el Event a `EventStatus.MISSED`
- [ ] `create_adhoc()` crea un Event + Shift + Visit en una sola operación con
  `is_adhoc=True`
- [ ] `PayrollHook.on_checkout()` se invoca tras cada checkout exitoso (hook
  concreto es `NullPayrollHook` en tests; la implementación real es externa)
- [ ] Las cuatro rutas `/api/v1/visits/...` responden correctamente con datos
  de fixture en tests

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Core schema — verified: src/parrot_formdesigner/core/schema.py
from parrot_formdesigner.core.schema import (
    FormSchema,       # src/parrot_formdesigner/core/schema.py:241
    FormField,        # src/parrot_formdesigner/core/schema.py:23
    FormSection,      # src/parrot_formdesigner/core/schema.py:101
    RenderedForm,     # src/parrot_formdesigner/core/schema.py:347
    RenderWarning,    # src/parrot_formdesigner/core/schema.py:330
)

# Field types — verified: src/parrot_formdesigner/core/types.py
from parrot_formdesigner.core.types import FieldType, LocalizedString
# FieldType.LOCATION already exists at src/parrot_formdesigner/core/types.py:45

# Registry — verified: src/parrot_formdesigner/services/registry.py
from parrot_formdesigner.services.registry import (
    FormRegistry,           # line 146
    FormStorage,            # line 50 (ABC)
    FormAlreadyExistsError, # line 39
)

# Submissions — verified: src/parrot_formdesigner/services/submissions.py
from parrot_formdesigner.services.submissions import (
    FormSubmission,          # line 50
    FormSubmissionStorage,   # line 102
)

# Partial saves — verified: src/parrot_formdesigner/services/partial_saves.py
from parrot_formdesigner.services.partial_saves import PartialSaveStore  # line 24

# Auth context — verified: src/parrot_formdesigner/services/auth_context.py
from parrot_formdesigner.services.auth_context import AuthContext  # line 20

# Renderers — verified: src/parrot_formdesigner/renderers/base.py
from parrot_formdesigner.renderers.base import (
    AbstractFormRenderer,  # line 57
    FallbackRenderer,      # line 34
)

# API handler — verified: src/parrot_formdesigner/api/handlers.py
from parrot_formdesigner.api.handlers import FormAPIHandler  # line 34
```

### Existing Class Signatures

```python
# src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):
    form_id: str                             # line 266
    version: str = "1.0"                     # line 267
    title: LocalizedString                   # line 268
    sections: list[FormSection]              # line 270
    submit: SubmitAction | None = None
    meta: dict[str, Any] | None = None       # line 273
    tenant: str | None = None                # line 275 (FEAT-183 — DONE)
    metadata: list[FormMetadataField] | None = None  # line 276
    def iter_all_fields(self) -> Iterator[FormField]: ...  # line 278

# src/parrot_formdesigner/services/submissions.py
class FormSubmission(BaseModel):
    submission_id: str            # line 78 (auto-uuid)
    form_id: str                  # line ~82
    form_version: str             # line 83
    data: dict[str, Any]          # validated submission payload
    is_valid: bool
    tenant: str | None = None

class FormSubmissionStorage:
    async def save(self, submission: FormSubmission,
                   *, tenant: str | None = None) -> str: ...  # returns submission_id

# src/parrot_formdesigner/services/partial_saves.py
class PartialSaveStore:
    async def save(self, form_id: str, data: dict, *,
                   user_id: str, tenant: str | None = None) -> None: ...  # line 67
    async def delete(self, form_id: str, *,
                     user_id: str, tenant: str | None = None) -> None: ...  # line 141

# src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def register(self, form: FormSchema, *, persist: bool = False,
                       overwrite: bool = True, tenant: str | None = None) -> None: ...  # line 262
    async def get(self, form_id: str, *, tenant: str | None = None) -> FormSchema | None: ...  # line 575

class FormStorage(ABC):
    async def save(self, form: FormSchema, style=None, *, tenant=None) -> str: ...  # line 60
    async def load(self, form_id: str, version: str | None = None,
                   *, tenant: str | None = None) -> FormSchema | None: ...  # line 82

# src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:
    # line 34 — existing handler; visit methods will be added here
    async def list_forms(self, request: web.Request) -> web.Response: ...    # line 442
    async def get_form(self, request: web.Request) -> web.Response: ...      # line 503
    async def create_form(self, request: web.Request) -> web.Response: ...   # line 551
    def _build_auth_context(self, request: web.Request) -> AuthContext: ...  # line 176

…(truncated)…
