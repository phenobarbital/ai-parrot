---
type: Wiki Overview
title: 'Brainstorm: Form Lifecycle Events for parrot-formdesigner'
id: doc:sdd-proposals-formdesigner-lifecycle-events-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. `services/callback_registry.py` resuelve callables async para `FieldType.REST`
  con `mode=callback` — es un mecanismo **por-campo** para fetch dinámico de opciones,
  no un ciclo de vida del formulario.
relates_to:
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Form Lifecycle Events for parrot-formdesigner

**Date**: 2026-05-20
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`parrot-formdesigner` actualmente carece de un sistema de eventos de ciclo de vida para formularios. Hay dos primitivas adyacentes que **no** cubren este caso:

1. `services/callback_registry.py` resuelve callables async para `FieldType.REST` con `mode=callback` — es un mecanismo **por-campo** para fetch dinámico de opciones, no un ciclo de vida del formulario.
2. `SubmitAction.action_type = "event" | "callback"` (core/schema.py:146) sólo determina **a qué destino** se envía un submit; no expone hooks intermedios.

Como consecuencia, los integradores no pueden:

- Reaccionar/transformar el `FormSchema` antes de servirlo (gating por tenant/usuario, ocultación dinámica de campos).
- Normalizar/aumentar el payload de submission antes de validar o persistir.
- Capturar éxitos para disparar side-effects (notificación, webhook, audit) sin tocar el handler central.
- Transformar mensajes de error a versiones friendly/i18n sin reescribir `submit_data` ni `validator`.
- Disponer de hooks UX inmediatos en el HTML5 renderer (validación cliente, feedback visual antes del fetch).

**FEAT-176 `lifecycle-events-system`** define eventos para `AbstractBot/AbstractClient/AbstractTool` pero (a) su código aún no existe en `parrot/core/` y (b) son strictly **read-only** — incompatibles con el requisito de interceptación/mutación que pide esta feature.

---

## Constraints & Requirements

- **Semántica de interceptor**: los `before*` deben poder mutar (payload/schema/metadata) y abortar con un mensaje user-facing. `onError` puede transformar mensaje pero NO suprimir el error.
- **Doble capa server + client (HTML5)**: server-side ejecuta lógica Python async; client-side emite `CustomEvent` DOM-nativos; un evento puede marcarse `remote: true` para puentearse al server vía fetch.
- **Registro híbrido**: decorador a nivel código (`@register_form_event(...)`) + referencia por nombre lógico desde el `FormSchema`. Tenant-scoped con fallback global, igual que el `callback_registry` existente.
- **MVP: solo HTML5 renderer**. Telegram/AdaptiveCard/PDF/XForms quedan fuera del MVP (pero la API server-side debe ser renderer-agnóstica para extenderse después).
- **Async-only** (coherente con el resto del paquete y con la regla del proyecto).
- **No-breaking**: añadir el sistema no debe romper formularios existentes sin `events` declarados.
- **Trazabilidad**: errores en handlers no deben enmascarar el error original ni romper el handler raíz (`submit_data`, `get_form`, `get_schema`).

---

## Options Explored

### Option A: Registro paralelo `event_registry` espejando `callback_registry`

Crear un módulo nuevo `services/event_registry.py` que reusa **exactamente** el mismo patrón de `services/callback_registry.py`: dict module-level con clave compuesta `(tenant, event_name_canónico)` y decorador `@register_form_event(...)`. El `FormSchema` gana un campo opcional `events: FormEventsConfig | None` (modelo Pydantic) que mapea cada evento (`onBeforeOpen`, `onSchemaLoaded`, `onBeforeSubmit`, `onAfterSubmit`, `onError`) a una `FormEventBinding` con `handler_ref: str` y `remote: bool` (este último controla si el cliente puentea por fetch). Un nuevo servicio `services/event_dispatcher.py` orquesta: resuelve el handler vía registry, ejecuta async, captura `FormEventAbort`/excepciones, devuelve `EventResolution` (payload mutado, schema mutado, metadatos extra).

Los hooks se enchufan en:

- `HandlerView.get_form` (api/handlers.py:503) → `onBeforeOpen` (puede abortar con 403 + mensaje).
- `HandlerView.get_schema` (api/handlers.py:512) → `onSchemaLoaded` (puede mutar el schema antes de renderizar).
- `HandlerView.submit_data` (api/handlers.py:840) → `onBeforeSubmit` (antes de validate), `onAfterSubmit` (tras persistir y forward), `onError` (cualquier `ValidationError`/`MetadataResolutionError`/`Exception` en el ciclo).

HTML5 renderer emite `CustomEvent('parrot:before-submit', ...)` etc. Si la binding tiene `remote: true`, un script ligero embebido hace fetch a un endpoint nuevo `POST /api/v1/forms/{id}/events/{event}` antes/después según el caso.

✅ **Pros:**
- Coherencia visual con `callback_registry`: cualquiera que conozca uno entiende el otro de inmediato.
- Aislamiento: cero modificaciones a `callback_registry` existente → no se introduce regresión.
- Permite ACL/auth distintas para callbacks REST vs eventos de ciclo de vida.
- Migración incremental: formularios sin `events: ...` siguen funcionando idénticamente.

❌ **Cons:**
- Cierta duplicación de código entre los dos registries (decorador + dict + fallback global).
- Dos sistemas casi gemelos pueden divergir en sutilezas si no se gobiernan con un test compartido.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (≥2.x, ya en uso) | Modelos `FormEventsConfig`, `FormEventBinding`, `EventResolution` | `extra="forbid"` para errores tempranos |
| `aiohttp` (ya en uso) | Endpoint remote para hooks `remote: true` | reusa `_wrap_auth` existente |
| `pytest-asyncio` (ya en uso) | Tests de dispatcher + registry tenant fallback | — |
| Sin librerías externas nuevas | — | — |

🔗 **Existing Code to Reuse:**
- `services/callback_registry.py` — patrón decorador + dict global + fallback `(tenant, name) → (None, name)` (líneas 53–158).
- `api/operations.py:150` `class OperationError(Exception)` — patrón para `class FormEventAbort(Exception)` con `reason`, `user_message`, `status_code`.
- `core/schema.py:241` `FormSchema` — añadir el campo `events`.
- `api/handlers.py:503/512/840` — puntos de inserción de los dispatcher calls.
- `services/metadata_enricher.py` — patrón de pipeline con `MetadataResolutionError` capturada y traducida a HTTP 422.

---

### Option B: Hook Registry unificado (refactor de `callback_registry`)

Generalizar `services/callback_registry.py` para que el `_CALLBACK_REGISTRY` admita un discriminador `category: Literal["rest_callback", "form_event"]`. La clave pasa de `(tenant, name)` a `(tenant, category, name)`. Los decoradores existentes (`register_form_callback`) se mantienen como wrappers thin que fijan `category="rest_callback"`. Se añade `register_form_event(event, *, tenant=None)` que fija `category="form_event"`. Mismo registry, mismo motor de fallback, semántica unificada.

✅ **Pros:**
- Una sola fuente de verdad para "callables asociados a forms".
- Reduce duplicación; si un día se añade un tercer tipo (validador customizado, listener), encaja sin nuevo registry.
- Test coverage existente del callback_registry cubre el motor base.

❌ **Cons:**
- Modifica un módulo en producción cubierto por tests (services/__init__.py exporta `register_form_callback`, `_clear_registry_for_tests`); requiere migration cuidadosa y dejar shim de compatibilidad.
- Mezcla conceptos (resolución de campo dinámico vs hook de ciclo de vida) en el mismo lookup table — peor segregación de ACL.
- La firma de los callables es diferente (`(payload: RestCallbackInput, auth_context)` vs `(event_ctx)`), forzar un tipo común vuelve el contrato ambiguo o requiere overloads.

📊 **Effort:** Medium-High (refactor + migración + compat shim)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (ya en uso) | Discriminated union para tipos de callable | — |
| Sin librerías externas nuevas | — | — |

🔗 **Existing Code to Reuse:**
- `services/callback_registry.py` completo (se refactoriza, no se duplica).
- `tests/unit/services/test_callback_registry.py` — necesita migración a la nueva firma.

---

### Option C: Adoptar FEAT-176 lifecycle-events como sustrato + capa interceptora encima

Esperar (o implementar antes) `parrot/core/events/lifecycle/` definido por FEAT-176 y declarar `FormBeforeOpenEvent`, `FormSchemaLoadedEvent`, `FormBeforeSubmitEvent`, `FormAfterSubmitEvent`, `FormErrorEvent` como subclases de `LifecycleEvent` (frozen dataclasses). Como FEAT-176 es estrictamente read-only, se añade un layer adicional `FormInterceptor` que envuelve cada emisión y permite mutación; el dispatch dual emite ambos (interceptor mutable + lifecycle read-only para observabilidad).

✅ **Pros:**
- Free observabilidad: `OpenTelemetrySubscriber`, `WebhookSubscriber`, `LoggingSubscriber` y trace context W3C funcionan sin trabajo extra.
- Alineación arquitectónica con el resto del codebase a futuro.
- Un solo modelo mental para "eventos" en todo `parrot`.

❌ **Cons:**
- FEAT-176 **no está implementado** todavía (`grep` en `parrot/core/` no devuelve nada de `LifecycleEvent`/`EventRegistry`). Acoplarse a un blanco móvil retrasa este feature indefinidamente.
- FEAT-176 declara explícitamente que **no** soporta interceptores en Fase 1 — los interceptores son "Phase 2". Construir el layer interceptor implicaría adelantar Fase 2 fuera de su feature owner.
- Mezcla responsabilidades (observabilidad agente-nivel + ciclo de vida formulario-nivel) que pueden divergir.

📊 **Effort:** High (bloqueado por FEAT-176; layer interceptor adicional sobre frozen dataclasses)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opentelemetry-api` | Trace context (heredado de FEAT-176) | Coupling con feature no implementada |
| `redis` (ya en uso) | EventBus transport (heredado de FEAT-176) | — |

🔗 **Existing Code to Reuse:**
- Ninguno aún: FEAT-176 vive como spec en `sdd/specs/FEAT-176-lifecycle-events-system.md` pero no hay código.

---

## Recommendation

**Option A** es la recomendada por tres razones concretas:

1. **Reusa el patrón ya probado** del `callback_registry` (tenant-scoped, fallback global, decorador) sin tocar código existente — propaga cero riesgo de regresión a un módulo ya en producción.
2. **Desbloquea ahora**. La opción C depende de FEAT-176, que no tiene código mergeado y cuya Fase 1 explícitamente excluye interceptores. La B implica refactor con migración + compat shim.
3. **Encaja con la semántica diferenciada** que pidió el usuario (interceptores con mutación de payload/schema/metadata + `FormEventAbort` tipado): un registry dedicado puede contratar firma propia (`(event_ctx) -> EventResolution`) sin contaminar la firma de los REST callbacks.

Tradeoff aceptado: cierta duplicación entre dos registries gemelos. Mitigación: un helper compartido `services/_registry_base.py` que ambos puedan importar (refactor menor, opcional, deferred a un follow-up).

A futuro, si FEAT-176 aterriza, este `event_registry` puede emitir adicionalmente `LifecycleEvent`s para observabilidad **sin** dejar de ser el bus interceptor primario.

---

## Feature Description

### User-Facing Behavior

**Para integradores Python:**

```python
from parrot_formdesigner.services.event_registry import register_form_event
from parrot_formdesigner.services.events import FormEventContext, EventResolution, FormEventAbort

@register_form_event("survey_v1.onBeforeSubmit", tenant="acme")
async def normalize_email(ctx: FormEventContext) -> EventResolution:
    payload = dict(ctx.payload)
    if "email" in payload:
        payload["email"] = payload["email"].strip().lower()
    return EventResolution(payload=payload)

@register_form_event("survey_v1.onBeforeSubmit")
async def block_blacklisted(ctx: FormEventContext) -> EventResolution:
    if ctx.payload.get("email") in BLACKLIST:
        raise FormEventAbort(
            reason="email_blacklisted",
            user_message="Ese email no está permitido.",
            status_code=403,
        )
    return EventResolution()  # no-op
```

**En el `FormSchema`** (JSON declarado en BD o registry):

```json
{
  "form_id": "survey_v1",
  "events": {
    "onBeforeSubmit": { "handler_ref": "survey_v1.onBeforeSubmit", "remote": false },
    "onAfterSubmit":  { "handler_ref": "survey_v1.notify_slack",   "remote": false },
    "onError":        { "handler_ref": "survey_v1.friendly_error", "remote": false },
    "onBeforeOpen":   { "handler_ref": "survey_v1.gate_user",      "remote": true  }
  }
}
```

**Para front-end (HTML5 host):**

El HTML5 renderer emite `CustomEvent`s DOM-nativos en el contenedor del formulario:

```js
formEl.addEventListener('parrot:before-submit', (e) => {
  if (!confirm('¿Confirmar envío?')) e.preventDefault();  // cancela el submit
});
formEl.addEventListener('parrot:after-submit', (e) => {
  showToast('¡Gracias por tu respuesta!');
});
formEl.addEventListener('parrot:error', (e) => {
  console.error('Form error:', e.detail);
});
```

Si `remote: true`, el script embebido hace `fetch('/api/v1/forms/{id}/events/{event}', {method:'POST', body: JSON.stringify(ctx)})` antes de continuar y respeta el `EventResolution` devuelto.

### Internal Behavior

**Server-side pipeline** (orden de ejecución en `submit_data`):

```
GET  /forms/{id}             → load form → dispatch(onBeforeOpen)   → 200/403
GET  /forms/{id}/schema      → load form → render → dispatch(onSchemaLoaded) → 200
POST /forms/{id}/data        → load form
                             → dispatch(onBeforeSubmit)   ← puede mutar payload o abortar
                             → validate
                             → enrich_metadata
                             → store + forward
                             → dispatch(onAfterSubmit)    ← side-effects (notify, audit)
                             → return 200
                             ↳ cualquier Exception en el ciclo → dispatch(onError)
                                                              → respuesta original (con mensaje transformado opcional)
```

**Componentes nuevos:**

- `core/events.py` — modelos Pydantic: `FormEventName` (Literal), `FormEventBinding`, `FormEventsConfig`, `FormEventContext`, `EventResolution`, `FormEventAbort` (excepción).
- `services/event_registry.py` — espejo de `callback_registry.py` con clave `(tenant, handler_ref)`.
- `services/event_dispatcher.py` — `async def dispatch(event_name, *, form, request, payload=None, schema=None) -> EventResolution`. Resuelve binding desde `form.events`, busca handler en registry, ejecuta, captura `FormEventAbort` y excepciones, retorna resolución estructurada o re-eleva.
- `api/handlers.py` — inserción de `dispatch(...)` en `get_form`, `get_schema`, `submit_data`. Nueva ruta `POST /api/v1/forms/{form_id}/events/{event_name}` para puenteo client-side `remote: true`.
- `renderers/html5.py` — emisión de `CustomEvent` en el HTML generado; script ligero para `remote: true` bindings.

**Resolución de handler** (idéntica a callback_registry):
1. Lookup `(tenant, handler_ref)` → handler tenant-específico.
2. Fallback `(None, handler_ref)` → handler global.
3. Si no existe y la binding es **opcional** → no-op silencioso + warning log.
4. Si la binding es **mandatoria** y no resuelve → 500 con error de configuración.

### Edge Cases & Error Handling

- **Handler levanta `FormEventAbort`**: el dispatcher captura, transforma a respuesta HTTP con `status_code` del abort y body `{"error": user_message, "reason": reason}`. NO se dispara `onError`.
- **Handler levanta excepción arbitraria**: se loggea con stack trace, se dispara `onError` con la excepción original en `ctx.error`, luego se re-eleva la excepción para que el handler central produzca 500. `onError` puede transformar `ctx.user_message` que se incluye en el body, pero no puede suprimir.
- **Handler de `onError` levanta excepción**: se loggea como `meta_error`; la excepción original se propaga sin transformación (failsafe). No hay loop infinito.
- **`remote: true` y el cliente no responde**: server-side ejecuta igualmente su lado del hook (el `remote` es una notificación adicional, no reemplazo). Si el cliente espera la respuesta y hay timeout, el HTML5 script tras `timeoutMs` (default 5000) loggea warning y deja continuar el flujo.
- **`FormSchema.events` referencia un handler_ref que nadie registró**: error de configuración detectado en `get_form` (cuando se sirve por primera vez), respuesta 500 + log explícito. No se difiere a tiempo de submit.
- **Múltiples handlers para el mismo evento del mismo form**: **No soportado en MVP** — un solo handler_ref por evento por form (regla del registry: duplicado → `ValueError`). Si se necesita encadenamiento, lo orquesta el propio handler. Ver Open Questions.
- **Mutaciones conflictivas**: `EventResolution.payload` reemplaza completamente; `EventResolution.schema_overrides` se aplica como merge poco profundo sobre `FormSchema.model_dump()`. No se soporta multi-handler-merge en MVP.
- **Compatibilidad backward**: `FormSchema.events` es opcional (`None` por defecto). Formularios existentes sin `events` siguen funcionando exactamente como hoy.

---

## Capabilities

### New Capabilities

- `formdesigner-lifecycle-events`: sistema de eventos de ciclo de vida (interceptor + observabilidad) para formularios, con registry tenant-scoped server-side y CustomEvent client-side en HTML5.

### Modified Capabilities

- `formdesigner-package`: añade `FormSchema.events` opcional y handler integration en `api/handlers.py`.
- `formdesigner-new-fields` (indirecto): si en el futuro algún field type quiere participar en eventos, el contrato ya existirá.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | modifies | añade `FormSchema.events: FormEventsConfig \| None`; añade `FormEventBinding` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` | new | modelos Pydantic + `FormEventAbort` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py` | new | registry tenant-scoped (espejo de `callback_registry.py`) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py` | new | orquestación de dispatch + captura `FormEventAbort` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | modifies | exporta nuevos símbolos públicos |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | modifies | inserciones en `get_form` (l.503), `get_schema` (l.512), `submit_data` (l.840) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | modifies | nueva ruta `POST /forms/{form_id}/events/{event_name}` para `remote: true` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | modifies | emisión `CustomEvent` + script ligero para `remote: true` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/callback_registry.py` | unchanged | NO se toca |
| `packages/parrot-formdesigner/tests/` | new + modifies | tests de registry, dispatcher, integración por endpoint |
| Otros renderers (Telegram, AdaptiveCard, PDF, XForms) | unchanged | fuera del MVP; la API server-side es renderer-agnóstica para extender después |

Sin breaking changes: todos los formularios sin `events` declarados se comportan idénticamente al estado actual.

---

## Code Context

### User-Provided Code

_Ninguno — feature elicitada en conversación._

### Verified Codebase References

#### Classes & Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:136
class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 146
    action_ref: str
    method: str = "POST"
    confirm_message: LocalizedString | None = None
    auth: AuthConfig | None = None

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:241
class FormSchema(BaseModel):
    form_id: str                          # line 266
    version: str = "1.0"                  # line 267
    title: LocalizedString                # line 268
    description: LocalizedString | None = None  # line 269
    sections: list[FormSection]           # line 270
    submit: SubmitAction | None = None    # line 271
    cancel_allowed: bool = True           # line 272
    meta: dict[str, Any] | None = None    # line 273
    created_at: datetime | None = None    # line 274
    tenant: str | None = None             # line 275
    metadata: list[FormMetadataField] | None = None  # line 276

# packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py:150
class OperationError(Exception):
    """Raised by per-op apply functions on validation failure."""
    # carga: op_index, op_name, message

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:503
async def get_form(self, request: web.Request) -> web.Response:
    """GET /api/v1/forms/{form_id} — Get full FormSchema as JSON."""

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:512
async def get_schema(self, request: web.Request) -> web.Response:
    """GET /api/v1/forms/{form_id}/schema — Get JSON Schema (structural)."""

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:840
async def submit_data(self, request: web.Request) -> web.Response:
    """POST /api/v1/forms/{form_id}/data — Receive and process a form submission."""
```

#### Verified Imports

```python
# Confirmadas tras inspección directa:
from parrot_formdesigner.services.callback_registry import (
    register_form_callback,         # services/callback_registry.py:60
    get_form_callback,              # services/callback_registry.py:130
    list_form_callbacks,            # services/callback_registry.py:161
    _clear_registry_for_tests,      # services/callback_registry.py:187
)
from parrot_formdesigner.services.metadata_enricher import (
    MetadataResolutionError,        # services/metadata_enricher.py:39
    enrich_submission,              # services/__init__.py:9 re-export
)
from parrot_formdesigner.api.operations import OperationError  # api/operations.py:150
```

#### Key Attributes & Constants

- `_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback]` (services/callback_registry.py:53) — patrón a replicar.
- `RestCallback = Callable[..., Awaitable[Any]]` (services/callback_registry.py:48).
- `FormSchema.meta: dict[str, Any] | None` (core/schema.py:273) — campo libre actualmente usado para `style`; NO usar para `events` (mejor un campo tipado dedicado).
- `SubmitAction.action_type` ya incluye `"event"` como literal pero su semántica es **destino** del submit, NO hook de ciclo de vida; el nuevo sistema es ortogonal.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_formdesigner.services.event_registry`~~ — no existe; se crea en este feature.
- ~~`parrot_formdesigner.services.event_dispatcher`~~ — no existe; se crea en este feature.
- ~~`parrot_formdesigner.core.events`~~ — no existe; se crea en este feature.
- ~~`FormSchema.events`~~ — atributo no existe; se añade en este feature.
- ~~`FormEventAbort`~~ — excepción no existe; se añade.
- ~~`FormEventContext`, `EventResolution`, `FormEventBinding`~~ — modelos no existen.
- ~~`@register_form_event`~~ — decorador no existe.
- ~~`parrot.core.events.lifecycle.*` / `LifecycleEvent` / `EventRegistry` / `EventEmitterMixin`~~ — FEAT-176 spec existe (`sdd/specs/FEAT-176-lifecycle-events-system.md`) pero **no hay código mergeado** en `parrot/core/`.
- ~~`parrot:before-submit` / `parrot:after-submit` CustomEvents~~ — el HTML5 renderer actual no emite ningún CustomEvent.
- ~~`onError`/`onSubmit`/`onLoad` keys en `FormSchema` o `meta`~~ — `grep` exhaustivo confirma que ningún form ni test referencia estas keys hoy.

---

## Parallelism Assessment

- **Internal parallelism**: media. La feature se decompone en cuatro tracks parcialmente independientes:
  1. `core/events.py` (modelos Pydantic + excepción) — bloqueante para los demás.
  2. `services/event_registry.py` + tests — depende solo de (1); paralelizable con (4).
  3. `services/event_dispatcher.py` + integración en `api/handlers.py` — depende de (1) y (2).
  4. `renderers/html5.py` (CustomEvent + script `remote:true`) — depende de (1); paralelizable con (2).

…(truncated)…
