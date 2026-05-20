---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Form Lifecycle Events for parrot-formdesigner

**Feature ID**: FEAT-188
**Date**: 2026-05-20
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor of `parrot-formdesigner`)

> **Source brainstorm**: `sdd/proposals/formdesigner-lifecycle-events.brainstorm.md`
> (Recommended Option A — Registro paralelo `event_registry` espejando `callback_registry`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot-formdesigner` carece de un sistema de eventos de ciclo de vida para formularios. Las dos primitivas existentes adyacentes **no** cubren el caso:

1. `services/callback_registry.py` resuelve callables async para `FieldType.REST` con `mode=callback` — es un mecanismo **por-campo** para fetch dinámico de opciones, no un ciclo de vida.
2. `SubmitAction.action_type = "event" | "callback"` (`core/schema.py:146`) sólo determina **a qué destino** se envía un submit; no expone hooks intermedios.

Esto impide:

- Reaccionar/transformar el `FormSchema` antes de servirlo (gating por tenant/usuario, ocultación dinámica de campos).
- Normalizar/aumentar el payload de submission antes de validar o persistir.
- Capturar éxitos para disparar side-effects (notificación, webhook, audit) sin tocar el handler central.
- Transformar mensajes de error a versiones friendly/i18n sin reescribir `submit_data` ni el validator.
- Disponer de hooks UX inmediatos en el HTML5 renderer (validación cliente, feedback visual antes del fetch).

FEAT-176 `lifecycle-events-system` define eventos para `AbstractBot/AbstractClient/AbstractTool` pero (a) no tiene código mergeado en `parrot/core/` y (b) sus eventos son **read-only** — incompatibles con la semántica interceptora requerida aquí.

### Goals

- Introducir cinco hooks declarativos por formulario: `onBeforeOpen`, `onSchemaLoaded`, `onBeforeSubmit`, `onAfterSubmit`, `onError`.
- Semántica de **interceptor**: los `before*` pueden mutar payload / schema / metadata y abortar con mensaje user-facing tipado.
- Doble capa **server + client (HTML5)**: server-side ejecuta Python async; client-side emite `CustomEvent` DOM-nativos; flag `remote: true` puentea cliente → server vía endpoint dedicado.
- **Registro híbrido tenant-scoped**: decorador `@register_form_event(...)` registra el callable; `FormSchema.events` referencia por `handler_ref` lógico.
- MVP: **solo HTML5 renderer**; API server-side renderer-agnóstica para extender después.
- **No-breaking**: formularios sin `events` declarados se comportan idénticamente.

### Non-Goals (explicitly out of scope)

- Múltiples handlers por evento por form: **un solo handler** por `(form, event)` en MVP — encadenamiento, si se requiere, lo orquesta el propio handler.
- Soporte multi-renderer en MVP (Telegram, AdaptiveCard, PDF, XForms quedan en follow-up).
- Reemplazo o modificación de `services/callback_registry.py` — sistema paralelo, no refactor.
- Acoplamiento a FEAT-176 lifecycle-events-system — sistemas independientes hasta nuevo aviso.
- **Rejected option (brainstorm)**: refactor unificado del `callback_registry` con discriminador `category=` (Option B) — descartado por mezcla de conceptos y riesgo de regresión.
- **Rejected option (brainstorm)**: subclasear `LifecycleEvent` de FEAT-176 + layer interceptor (Option C) — bloqueado por falta de código upstream.

---

## 2. Architectural Design

### Overview

Se añade un sistema de eventos **espejo** del existente `callback_registry`:

- Nuevos modelos en `parrot_formdesigner.core.events` (Pydantic + excepción tipada).
- Nuevo registry tenant-scoped en `parrot_formdesigner.services.event_registry` (decorador `@register_form_event` + lookup `(tenant, handler_ref) → (None, handler_ref)`).
- Nuevo dispatcher en `parrot_formdesigner.services.event_dispatcher` que orquesta resolución + ejecución + captura de `FormEventAbort`.
- `FormSchema` gana un campo opcional `events: FormEventsConfig | None`.
- `FormAPIHandler` (api/handlers.py) inserta calls al dispatcher en `get_form`, `get_schema`, `submit_data`, y en un wrapper de manejo de excepciones para `onError`.
- Nueva ruta `POST /api/v1/forms/{form_id}/events/{event_name}` para hooks declarados `remote: true` (auth distinta — ver §7).
- `HTML5Renderer` emite `CustomEvent('parrot:before-open' | 'parrot:schema-loaded' | 'parrot:before-submit' | 'parrot:after-submit' | 'parrot:error', { detail: ... })` y embebe un script ligero que hace `fetch` al endpoint remote cuando la binding tiene `remote: true`.

### Component Diagram

```
   ┌────────────────────────────────────────────────┐
   │              FormAPIHandler                    │
   │  api/handlers.py                               │
   │  ├─ get_form  ──→ dispatch(onBeforeOpen)       │
   │  ├─ get_schema ─→ dispatch(onSchemaLoaded)     │
   │  └─ submit_data                                │
   │       ├─ dispatch(onBeforeSubmit)              │
   │       ├─ validate → enrich → store → forward   │
   │       ├─ dispatch(onAfterSubmit)               │
   │       └─ except *  → dispatch(onError) → reraise
   └─────────────────────┬──────────────────────────┘
                         │
                         ▼
           ┌─────────────────────────────┐
           │     event_dispatcher        │   services/event_dispatcher.py
           │  dispatch(name, ctx) ──┐    │
           └────────────────────────┼────┘
                                    ▼
           ┌─────────────────────────────┐
           │     event_registry          │   services/event_registry.py
           │  lookup (tenant, ref)       │   (espejo de callback_registry)
           │   → callable o KeyError     │
           └─────────────────────────────┘
                                    │
                                    ▼
                          user-registered async handler
                          (decorated with @register_form_event)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormAPIHandler` (api/handlers.py:34) | extends (no subclass) | Inserciones in-place en `get_form`, `get_schema`, `submit_data`. Try/except envolvente para `onError`. |
| `FormSchema` (core/schema.py:241) | extends | Nuevo campo opcional `events: FormEventsConfig \| None`. |
| `services/callback_registry.py` | unchanged | NO se toca. Sirve de patrón para el espejo. |
| `_wrap_auth` (api/routes.py:60) | reuses | El nuevo endpoint remote pasa por `_wrap_auth`. |
| `_get_tenant` (api/handlers.py:154) | reuses | Tenant scope para resolución. |
| `_build_auth_context` (api/handlers.py:176) | reuses | Inyectado en `FormEventContext`. |
| `setup_form_api` (api/routes.py:85) | extends | Añade la ruta `POST /forms/{form_id}/events/{event_name}`. |
| `HTML5Renderer` (renderers/html5.py:77) | extends | Emisión de `CustomEvent` + script puente para `remote: true`. |
| FEAT-176 lifecycle-events-system | independent | Sin acoplamiento. Si FEAT-176 aterriza, este dispatcher puede emitir `LifecycleEvent`s adicionales como observabilidad. |

### Data Models

```python
# parrot_formdesigner/core/events.py  (new)

from collections.abc import Mapping
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

FormEventName = Literal[
    "onBeforeOpen",
    "onSchemaLoaded",
    "onBeforeSubmit",
    "onAfterSubmit",
    "onError",
]


class FormEventBinding(BaseModel):
    """Declaración por-formulario de un binding evento → handler."""

    model_config = ConfigDict(extra="forbid")

    handler_ref: str = Field(
        ...,
        description="Logical handler name, namespaced as '<form_id>.<event>'.",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )
    remote: bool = False  # if True, HTML5 client bridges via fetch
    required: bool = False  # if True and handler missing → 500


class FormEventsConfig(BaseModel):
    """Mapa declarado por-formulario de event → binding."""

    model_config = ConfigDict(extra="forbid")

    onBeforeOpen: FormEventBinding | None = None
    onSchemaLoaded: FormEventBinding | None = None
    onBeforeSubmit: FormEventBinding | None = None
    onAfterSubmit: FormEventBinding | None = None
    onError: FormEventBinding | None = None


class FormEventContext(BaseModel):
    """Payload pasado a un handler."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    event: FormEventName
    form_id: str
    tenant: str
    auth_context: Any  # services.auth_context.AuthContext (avoid circular import)
    payload: Mapping[str, Any] | None = None       # submit only
    schema_dump: Mapping[str, Any] | None = None   # open / schema_loaded only
    error: BaseException | None = None             # onError only
    user_message: str | None = None                # onError mutable
    extra: dict[str, Any] = Field(default_factory=dict)  # correlation_id, etc.


class EventResolution(BaseModel):
    """Retorno de un handler — qué (si algo) mutar."""

    model_config = ConfigDict(extra="forbid")

    payload: Mapping[str, Any] | None = None             # replace payload
    schema_overrides: Mapping[str, Any] | None = None    # shallow merge on form dump
    metadata: Mapping[str, Any] | None = None            # added to ctx.extra
    user_message: str | None = None                      # only meaningful in onError


class FormEventAbort(Exception):
    """Cancela el flujo de un evento before* con respuesta tipada.
    Patrón inspirado en api/operations.py:150 OperationError."""

    def __init__(
        self,
        reason: str,
        *,
        user_message: str,
        status_code: int = 403,
    ) -> None:
        self.reason = reason
        self.user_message = user_message
        self.status_code = status_code
        super().__init__(reason)
```

### New Public Interfaces

```python
# parrot_formdesigner/services/event_registry.py  (new — mirror of callback_registry.py)

from collections.abc import Awaitable, Callable
from typing import Any

FormEventHandler = Callable[..., Awaitable["EventResolution | None"]]

def register_form_event(
    handler_ref: str,
    *,
    tenant: str | None = None,
) -> Callable[[FormEventHandler], FormEventHandler]: ...

def get_form_event(
    handler_ref: str,
    *,
    tenant: str | None = None,
) -> FormEventHandler: ...

def list_form_events(
    tenant: str | None = None,
) -> list[tuple[str | None, str]]: ...

def _clear_event_registry_for_tests() -> None: ...  # test helper
```

```python
# parrot_formdesigner/services/event_dispatcher.py  (new)

async def dispatch(
    event: FormEventName,
    *,
    form: FormSchema,
    request: web.Request,
    payload: Mapping[str, Any] | None = None,
    schema_dump: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> EventResolution:
    """Resuelve binding, ejecuta handler, captura FormEventAbort.

    Returns:
        EventResolution. Si no hay binding, retorna EventResolution() vacía
        (no-op). Si la binding es required y no resuelve, levanta RuntimeError.

    Raises:
        FormEventAbort: si el handler aborta (para before*).
        Exception: cualquier excepción del handler para before*/after* se
            propaga al caller; el caller decide si la convierte en HTTP 500
            o si la pasa a onError.
    """
```

---

## 3. Module Breakdown

### Module 1: `core/events` — modelos Pydantic + excepción

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` (new)
- **Responsibility**: Definir `FormEventName`, `FormEventBinding`, `FormEventsConfig`, `FormEventContext`, `EventResolution`, `FormEventAbort`. Validar regex de `handler_ref` namespaced.
- **Depends on**: pydantic (existing).

### Module 2: `services/event_registry` — registro tenant-scoped

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py` (new)
- **Responsibility**: Espejo de `callback_registry.py`. Dict `(tenant, handler_ref) → handler`. Decorador `@register_form_event`. Fallback global. Helper de limpieza para tests.
- **Depends on**: Module 1.

### Module 3: `services/event_dispatcher` — orquestación

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py` (new)
- **Responsibility**: `dispatch(...)` async. Resuelve binding desde `form.events`, busca handler en registry, ejecuta, captura `FormEventAbort`, retorna `EventResolution` agregada. Aplica shallow-merge a `schema_overrides`.
- **Depends on**: Module 1, Module 2.

### Module 4: `core/schema` extension — `FormSchema.events`

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (modify, l.241)
- **Responsibility**: Añadir campo `events: FormEventsConfig | None = None` a `FormSchema`. Validar que cada `handler_ref` referenciado cumple el regex namespaced. NO validar resolución del handler aquí (deferred a dispatch).
- **Depends on**: Module 1.

### Module 5: `api/handlers` integration — inserciones en `FormAPIHandler`

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (modify)
- **Responsibility**:
  - `get_form` (l.503): tras cargar el form, `await dispatch("onBeforeOpen", ...)`. Si `FormEventAbort`, responder con `status_code` + mensaje.
  - `get_schema` (l.512): tras renderizar el schema estructural, `await dispatch("onSchemaLoaded", schema_dump=rendered.content)`. Aplicar `schema_overrides` shallow.
  - `submit_data` (l.840): antes de `validate`, `dispatch("onBeforeSubmit", payload=data)`. Si retorna `payload` no-nulo, reemplazar `data`. Tras forward, `dispatch("onAfterSubmit", payload=result.sanitized_data)`. Try/except envolvente: en cualquier excepción, `dispatch("onError", error=exc)`, tomar `user_message` si existe, reraise.
- **Depends on**: Module 3.

### Module 6: `api/routes` — endpoint remote

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (modify, en `setup_form_api`)
- **Responsibility**: Añadir `app.router.add_post(f"{bp}/forms/{{form_id}}/events/{{event_name}}", _wrap_auth(handler.remote_event))` y un handler `remote_event` en `FormAPIHandler` que valida el `event_name` ∈ `FormEventName`, valida CSRF (ver §7), invoca `dispatch(...)`, devuelve `EventResolution` serializada.
- **Depends on**: Module 3, Module 5.

### Module 7: `renderers/html5` — CustomEvent + script puente

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` (modify, l.77)
- **Responsibility**: Embeber un `<script>` ligero (sin dependencias externas) que:
  - Emite `CustomEvent('parrot:<event>', { detail: { form_id, payload? } })` en el contenedor del formulario en los puntos correspondientes (open, before-submit con `event.preventDefault()` para cancelar, after-submit, error).
  - Si la binding tiene `remote: true`, hace `fetch('/api/v1/forms/{id}/events/{event}', {method:'POST', body, credentials:'same-origin', headers:{'X-CSRF-Token': ...}})` antes/después según el evento, con timeout configurable (default 5000ms). Si timeout, log warning y continúa.
- **Depends on**: Module 1, Module 6.

### Module 8: Tests

- **Path**: `packages/parrot-formdesigner/tests/unit/services/test_event_registry.py`, `tests/unit/services/test_event_dispatcher.py`, `tests/unit/core/test_form_events_models.py`, `tests/integration/test_lifecycle_events_e2e.py` (all new)
- **Responsibility**: Cobertura por módulo + e2e por endpoint.
- **Depends on**: All previous modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_form_event_binding_handler_ref_regex` | `core/events` | `handler_ref` sin punto → ValidationError; con punto → ok. |
| `test_form_event_abort_carries_status_code` | `core/events` | Default 403; custom respetado. |
| `test_register_form_event_global` | `services/event_registry` | Registro global resuelve sin tenant. |
| `test_register_form_event_tenant_overrides_global` | `services/event_registry` | Tenant-specific shadows global. |
| `test_register_form_event_duplicate_raises` | `services/event_registry` | Segundo registro de mismo `(tenant, ref)` → ValueError. |
| `test_dispatch_no_binding_is_noop` | `services/event_dispatcher` | Form sin `events.<name>` → `EventResolution()` vacía. |
| `test_dispatch_missing_required_handler_raises` | `services/event_dispatcher` | Binding required + no registrado → RuntimeError configuración. |
| `test_dispatch_form_event_abort_propagates` | `services/event_dispatcher` | `FormEventAbort` se re-eleva intacta. |
| `test_dispatch_payload_replacement` | `services/event_dispatcher` | Handler devuelve `payload=...` → reemplaza. |
| `test_dispatch_schema_overrides_shallow_merge` | `services/event_dispatcher` | Sólo top-level keys reemplazadas; nested no se profundiza. |
| `test_form_schema_accepts_events_config` | `core/schema` | `FormSchema(events=FormEventsConfig(...))` válido. |
| `test_form_schema_without_events_is_unchanged` | `core/schema` | Schema serializado sin `events` no incluye el campo. |

### Integration Tests

| Test | Description |
|---|---|
| `test_get_form_with_onbeforeopen_abort_returns_403` | Handler levanta `FormEventAbort` → respuesta HTTP 403 con `user_message`. |
| `test_get_schema_with_onschemaloaded_mutates_response` | `schema_overrides` aplicado al body de respuesta. |
| `test_submit_with_onbeforesubmit_normalizes_payload` | Email normalizado antes de validación; submission persistida con valor normalizado. |
| `test_submit_with_onaftersubmit_fires_side_effect` | Handler registra side-effect (mock); ejecutado después de store + forward. |
| `test_submit_error_path_dispatches_onerror_and_reraises` | Exception en validate → `onError` ejecutado → mensaje transformado → respuesta original NO suprimida. |
| `test_remote_event_endpoint_requires_auth` | `POST /forms/.../events/...` sin CSRF/auth → 401/403. |
| `test_remote_event_endpoint_invalid_event_name` | `event_name` fuera de `FormEventName` → 400. |
| `test_form_without_events_is_unchanged_e2e` | Forms preexistentes (sin `events`) no cambian de comportamiento — regresión cero. |

### Test Data / Fixtures

```python
# tests/conftest.py extensions

@pytest.fixture
def _clear_event_registry():
    """Aísla registry entre tests."""
    from parrot_formdesigner.services.event_registry import _clear_event_registry_for_tests
    yield
    _clear_event_registry_for_tests()

@pytest.fixture
def form_with_lifecycle_events(_clear_event_registry):
    from parrot_formdesigner.core.schema import FormSchema
    from parrot_formdesigner.core.events import FormEventsConfig, FormEventBinding
    return FormSchema(
        form_id="survey_v1",
        title={"en": "Survey"},
        sections=[...],
        events=FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="survey_v1.onBeforeSubmit"),
            onError=FormEventBinding(handler_ref="survey_v1.onError"),
        ),
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All new unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_event_registry.py packages/parrot-formdesigner/tests/unit/services/test_event_dispatcher.py packages/parrot-formdesigner/tests/unit/core/test_form_events_models.py -v`.
- [ ] All new integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/test_lifecycle_events_e2e.py -v`.
- [ ] **Full existing test suite passes unchanged**: `pytest packages/parrot-formdesigner -v` con cero regresiones.
- [ ] Formularios sin `events` declarados generan respuestas byte-idénticas a las del estado previo en `get_form`, `get_schema`, `submit_data` (no-breaking acid test).
- [ ] `mypy --strict packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py` limpio.
- [ ] `ruff check packages/parrot-formdesigner/` limpio.
- [ ] `register_form_event` y `get_form_event` exportados desde `parrot_formdesigner.services.__init__`.
- [ ] `FormEventName`, `FormEventBinding`, `FormEventsConfig`, `FormEventContext`, `EventResolution`, `FormEventAbort` exportados desde `parrot_formdesigner.core.__init__`.
- [ ] HTML5 renderer emite los 5 `CustomEvent`s en navegador real (verificado con un fixture de página estática + Playwright o test manual documentado en PR).
- [ ] Endpoint `POST /api/v1/forms/{form_id}/events/{event_name}` rechaza requests sin CSRF token con 401/403.
- [ ] Endpoint rechaza `event_name` fuera del `Literal FormEventName` con 400.
- [ ] `FormEventAbort` con `status_code=403` levantado en `onBeforeOpen` produce respuesta HTTP 403 con `{"error": user_message, "reason": reason}`.
- [ ] Excepción no-controlada en `submit_data` dispara `onError` antes de retornar 500; el `user_message` transformado aparece en el body; el error original se loggea con stack trace.
- [ ] Documentación añadida o actualizada en `packages/parrot-formdesigner/docs/` (o README) con un ejemplo end-to-end de registro + uso.
- [ ] CHANGELOG del paquete actualizado.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods not listed here without first verifying via `grep` or `read`.

### Verified Imports

```python
# Re-verified at this spec's creation date:
from parrot_formdesigner.services.callback_registry import (
    register_form_callback,         # services/callback_registry.py:60
    get_form_callback,              # services/callback_registry.py:130
    list_form_callbacks,            # services/callback_registry.py:161
    _clear_registry_for_tests,      # services/callback_registry.py:187
)
from parrot_formdesigner.services.metadata_enricher import (
    MetadataResolutionError,        # services/metadata_enricher.py:39
    enrich_submission,              # re-exported by services/__init__.py:9
)
from parrot_formdesigner.api.operations import OperationError  # api/operations.py:150
from parrot_formdesigner.services.auth_context import AuthContext  # services/auth_context.py:20
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:34
class FormAPIHandler:
    def __init__(self, ...): ...                             # line 54
    def _get_tenant(self, request: web.Request) -> str: ...  # line 154
    def _build_auth_context(self, request: web.Request) -> AuthContext: ...  # line 176
    async def get_form(self, request: web.Request) -> web.Response: ...      # line 503
    async def get_schema(self, request: web.Request) -> web.Response: ...    # line 512
    async def get_style(self, request: web.Request) -> web.Response: ...     # line 522
    async def validate(self, request: web.Request) -> web.Response: ...      # line 532
    async def submit_data(self, request: web.Request) -> web.Response: ...   # line 840

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def _wrap_auth(handler: _Handler) -> _Handler: ...    # line 60
def setup_form_api(app, ...): ...                     # line 85

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:136
class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 146
    action_ref: str
    method: str = "POST"
    confirm_message: LocalizedString | None = None
    auth: AuthConfig | None = None

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:241
class FormSchema(BaseModel):
    form_id: str                         # line 266
    version: str = "1.0"                 # line 267
    title: LocalizedString               # line 268
    description: LocalizedString | None = None  # line 269
    sections: list[FormSection]          # line 270
    submit: SubmitAction | None = None   # line 271
    cancel_allowed: bool = True          # line 272
    meta: dict[str, Any] | None = None   # line 273
    created_at: datetime | None = None   # line 274
    tenant: str | None = None            # line 275
    metadata: list[FormMetadataField] | None = None  # line 276
    # NEW: events: FormEventsConfig | None = None    (to be added by this feature)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py:150
class OperationError(Exception):
    """Raised by per-op apply functions on validation failure."""

# packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py:20
class AuthContext(BaseModel):
    """Resolved credentials passed explicitly to field resolvers."""

# packages/parrot-formdesigner/src/parrot_formdesigner/services/callback_registry.py
_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback]  # line 53
RestCallback = Callable[..., Awaitable[Any]]                    # line 48

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:77
class HTML5Renderer(AbstractFormRenderer):
    async def render(self, ...) -> RenderedForm: ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `event_dispatcher.dispatch` | `FormAPIHandler.get_form` | `await dispatch("onBeforeOpen", form=form, request=request)` | `api/handlers.py:503` |
| `event_dispatcher.dispatch` | `FormAPIHandler.get_schema` | `await dispatch("onSchemaLoaded", form=form, schema_dump=rendered.content)` | `api/handlers.py:512` |
| `event_dispatcher.dispatch` | `FormAPIHandler.submit_data` | 3 calls + try/except → `dispatch("onError", error=exc)` | `api/handlers.py:840` |
| `event_registry.get_form_event` | `event_dispatcher.dispatch` | direct function call with `(tenant, handler_ref)` fallback | NEW (mirror of `callback_registry.get_form_callback` at `services/callback_registry.py:130`) |
| `FormSchema.events.<name>.handler_ref` | `event_registry.get_form_event` | string lookup | NEW field on `FormSchema` |
| New route `POST /forms/{id}/events/{event}` | `event_dispatcher.dispatch` | bridged from HTML5 fetch when `remote: true` | NEW (added in `setup_form_api`, `api/routes.py:85`) |
| `HTML5Renderer` script | DOM | `CustomEvent('parrot:<event>', {detail: ...})` | NEW (embedded in `renderers/html5.py:77`) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_formdesigner.services.event_registry`~~ — created by this feature.
- ~~`parrot_formdesigner.services.event_dispatcher`~~ — created by this feature.
- ~~`parrot_formdesigner.core.events`~~ — created by this feature.
- ~~`FormSchema.events`~~ — to be added by this feature.
- ~~`FormEventAbort`, `FormEventContext`, `EventResolution`, `FormEventBinding`, `FormEventsConfig`, `FormEventName`~~ — created by this feature.
- ~~`@register_form_event`, `get_form_event`, `list_form_events`~~ — created by this feature.
- ~~`HandlerView`~~ — does NOT exist; the correct class name is `FormAPIHandler` (api/handlers.py:34).
- ~~`parrot.core.events.lifecycle.*`, `LifecycleEvent`, `EventRegistry`, `EventEmitterMixin`~~ — FEAT-176 spec exists at `sdd/specs/FEAT-176-lifecycle-events-system.md` but **no code is merged** in `parrot/core/`. Do not import from there.
- ~~`parrot:before-submit` / `parrot:after-submit` CustomEvents~~ — `HTML5Renderer` does not emit any CustomEvent today.
- ~~`onError` / `onSubmit` / `onLoad` keys on `FormSchema` or `FormSchema.meta`~~ — exhaustive grep confirms no form or test references these keys today.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Mirror, don't refactor**: `services/event_registry.py` debe ser una copia estructural de `services/callback_registry.py` (mismas funciones públicas, mismo patrón fallback global, mismo helper `_clear_*_for_tests`). NO refactorizar el original ni extraer base común en este feature (deferred a follow-up).
- **Async-only**: handlers obligatoriamente `async def`. El dispatcher comprueba `asyncio.iscoroutinefunction(...)` y rechaza con `TypeError` en registro si no lo es.
- **Pydantic con `extra="forbid"`** en todos los modelos nuevos para detectar typos en JSON.
- **Logging con `self.logger`** (o `logger = logging.getLogger(__name__)` en módulos sin clase). Nunca `print`.
- **Naming `handler_ref`**: obligatoriamente namespaced `<form_id>.<event>` (o más profundo). Validado por regex en `FormEventBinding`. **Decisión carry-forward del brainstorm**: namespaced obligatorio para evitar colisiones cross-form.
- **Shallow merge para `schema_overrides`**: sólo se reemplazan keys de top-level del `FormSchema.model_dump()`. Para mutar campos anidados, el handler debe componer el dict completo. **Decisión carry-forward del brainstorm**: shallow para MVP; deep cuando aparezca un caso real.
- **`onError` no se dispara para `FormEventAbort`**: abort es flujo válido, no error. **Decisión carry-forward del brainstorm**.
- **Un handler por `(form, event)`**: el registry rechaza duplicado con `ValueError`. **Decisión carry-forward del brainstorm**.

### Authentication for the remote endpoint

**Decisión carry-forward del brainstorm**: el endpoint `POST /forms/{form_id}/events/{event_name}` requiere auth **distinta** a los handlers principales del formulario:

- Sigue pasando por `_wrap_auth` (sesión válida).
- **Adicionalmente** valida un `X-CSRF-Token` header contra un token emitido en el HTML5 render del formulario (token rotado por sesión, scoped a `form_id`).
- Si el token falta o no coincide → 403 sin invocar el handler.
- Implementación concreta del CSRF (storage del token, expiración, rotación) se decide en la task correspondiente; el spec sólo fija el contrato (header + comportamiento).

### Known Risks / Gotchas

- **Duplicación con `callback_registry`**: dos sistemas casi gemelos. Mitigación: tests compartidos sobre el patrón fallback global (helper de test reusable). Refactor para extraer base común se difiere a un follow-up para no inflar este feature.
- **Mutación de payload + revalidación**: si `onBeforeSubmit` reemplaza `payload`, el dispatcher debe pasar el nuevo payload a `validator.validate()`. Cuidado de NO volver a invocar `dispatch("onBeforeSubmit")` recursivamente.
- **`onError` dentro de `onError`**: el handler de `onError` puede levantar excepción. Se loggea como `meta_error`; la excepción original sigue propagándose. NO hay loop ni doble dispatch.
- **`remote: true` timeout (default 5000ms)**: el client-side embebido continúa el flujo si el server no responde a tiempo, loggeando warning. El server-side de su lado SIEMPRE ejecuta — el `remote` es notificación adicional, no reemplazo.
- **CSRF token storage**: si no hay infraestructura de sesión persistente, este token debe vivir en una cookie HttpOnly + Secure + SameSite=Strict. Decisión final de storage va en la task correspondiente.
- **Backward compatibility**: `FormSchema.events` es `None` por defecto. `model_dump()` sin el campo declarado **no** debe incluir `"events": null` (usar `exclude_none=True` donde aplique en serialización).
- **Migración de bindings**: forms persistidos en BD sin `events` siguen cargando OK (campo opcional). Forms persistidos CON `events` requieren que la BD haya migrado el JSON schema; se documenta en CHANGELOG.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.x` (ya en uso) | Modelos `FormEventsConfig`, `FormEventBinding`, `FormEventContext`, `EventResolution`. |
| `aiohttp` | (ya en uso) | Endpoint remote `POST /forms/{id}/events/{event}`. |
| `pytest-asyncio` | (ya en uso) | Tests async del dispatcher + registry. |

Sin librerías externas nuevas.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- **All tasks run sequentially in one worktree**:
  ```bash
  git worktree add -b feat-188-formdesigner-lifecycle-events \
    .claude/worktrees/feat-188-formdesigner-lifecycle-events HEAD
  ```
- **Rationale**: el contrato compartido (`FormEventContext`, `EventResolution`, `FormEventBinding`) muta de forma natural durante la implementación. Separar por worktrees forzaría rebases caros sobre `core/events.py`. Mantener `core → registry → dispatcher → handlers → routes → renderer → tests` en un solo worktree con commits atómicos por task es más eficiente.
- **Cross-feature dependencies**: ninguna. NO acoplado a FEAT-176; NO toca `services/callback_registry.py`; las modificaciones a `core/schema.py` y `api/handlers.py` son aditivas (campo opcional + inserciones in-place) y no colisionan con specs activas del paquete.

---

## 8. Open Questions

> Todas las preguntas se resolvieron durante el brainstorm. Se conservan aquí como rastro de decisión auditable.

- [x] ¿Soportar múltiples handlers por evento por form en MVP, o postergar a un follow-up? — *Resolved in brainstorm*: un handler por evento; encadenamiento, si se requiere, lo orquesta el propio handler. Refleja en §1 Non-Goals y §3 Module 2 (duplicado en registry → ValueError).
- [x] ¿`onError` debe dispararse también para `FormEventAbort` o solo para excepciones no-controladas? — *Resolved in brainstorm*: no — abort es flujo válido, no error. Refleja en §7 Patterns y §3 Module 5 (try/except sólo para excepciones que NO sean `FormEventAbort`).
- [x] ¿La ruta `POST /forms/{form_id}/events/{event_name}` para `remote: true` requiere auth distinta a los handlers principales? — *Resolved in brainstorm*: sí. Refleja en §7 Authentication for the remote endpoint (CSRF token adicional sobre `_wrap_auth`).
- [x] ¿`EventResolution.schema_overrides` se aplica como deep-merge o shallow-merge? — *Resolved in brainstorm*: shallow para MVP. Refleja en §3 Module 3 y §7 Patterns.
- [x] ¿Telegram renderer debería emitir un equivalente al `CustomEvent` en un follow-up, o queda post-MVP indefinido? — *Resolved in brainstorm*: en un follow-up. Refleja en §1 Non-Goals.
- [x] ¿Convención de naming del `handler_ref`: free-form o namespaced obligatorio? — *Resolved in brainstorm*: namespaced obligatorio (`<form_id>.<event>` o más profundo) para evitar colisiones cross-form. Refleja en §2 Data Models (regex de `FormEventBinding.handler_ref`) y §7 Patterns.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-20 | Jesus Lara | Initial draft scaffolded from brainstorm (`sdd/proposals/formdesigner-lifecycle-events.brainstorm.md`). All 6 brainstorm Open Questions resolved and carried forward. |
