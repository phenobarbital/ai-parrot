---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI Agent Functions Runtime (v1.0 RPC leg)

**Feature ID**: FEAT-469
**Date**: 2026-08-28
**Author**: Jesus Lara (con Claude)
**Status**: approved
**Target version**: 0.29.0
**Depends on**: `a2ui-v1-dialect` (brainstorm `sdd/proposals/a2ui-v1-dialect.brainstorm.md`, Option B) — esta feature asume el wire v1.0 y los modelos de mensajes definidos allí. No puede iniciarse hasta que el spec de `a2ui-v1-dialect` esté `approved` y su bloque de wire (modelos + serialización) esté mergeado en `dev`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`a2ui-v1-dialect` deja el wire A2UI de ai-parrot 100% conforme a v1.0 y modela
**todos** los mensajes del protocolo, pero corta explícitamente el alcance de
acciones en "modelos + `Form` como composición + deep links" (constraint C6 de
ese brainstorm). Queda sin runtime la **pata RPC** de v1.0:

- El renderer no puede pedirle nada al agente sin pasar por un turno
  conversacional: no hay despacho de `callAgentFunction` → tool → `agentFunctionResponse`.
- El agente no puede invocar funciones del renderer (`callRendererFunction` /
  `rendererFunctionResponse`), ni recibir `error` estructurado.
- `sendDataModel` (el renderer adjunta el `dataModel` completo de la superficie
  en cada `action`) se acepta en el modelo pero no se procesa: el agente no
  conoce el estado vivo de la superficie.
- El catálogo parrot exportado no declara `functions` con `allowedCallers` /
  `requiresUserActivation`, y el Agent Card A2A no publica
  `agent_capabilities` (`supportedCatalogIds`), así que un renderer v1.0 no
  puede descubrir qué puede invocar.

Sin esto, las superficies interactivas (formularios, dashboards actualizables,
recetas con refresco) siguen siendo "display + deep link", y toda interacción
regresa al LLM aunque sea una operación determinista (`refreshChart`,
`runRecipe`, `exportPdf`).

### Goals

- G1. Despachar `callAgentFunction` (renderer→agent) a **cualquier tool
  registrada en el `ToolManager`** del agente (decisión del usuario, §8),
  devolviendo `agentFunctionResponse{functionCallId, value|error}`.
- G2. Permitir al agente emitir `callRendererFunction` y correlacionar
  `rendererFunctionResponse` / `error` por `functionCallId`, tanto en
  request-response (HTTP) como en streaming.
- G3. Procesar `action` v1.0 (`name`, `context`, `userMessage`) y
  `sendDataModel`: persistir el último `dataModel` por `surfaceId` en la
  memoria de conversación y exponerlo al agente/tools.
- G4. Exportar `functions` en el `catalog_definition.json` de parrot con
  `allowedCallers` y `requiresUserActivation`, derivadas de las tools.
- G5. Publicar `agent_capabilities` (`{"v1.0": {"supportedCatalogIds": [...]}}`)
  y la extensión `https://a2ui.org/a2a-extension/a2ui/v1.0` en el Agent Card
  A2A; aceptar sobres R→A en `DataPart` (`mimeType: application/a2ui+json`).
- G6. Endpoint HTTP dedicado (`/api/v1/agents/{agent_id}/a2ui`, POST + stream)
  para sobres R→A fuera de A2A, con la misma autenticación/sesión de AgentTalk.
- G7. Autorización: cada invocación se ejecuta con el `PermissionContext` del
  usuario de la sesión vía `ToolManager.execute_tool(permission_context=...)`.

### Non-Goals (explicitly out of scope)

- Cambios al wire o al catálogo básico (18 primitivas / 14 funciones
  renderer-side): son de `a2ui-v1-dialect`.
- Renderer web propio que ejecute `callRendererFunction` (el JS inline de
  `interactive-html` no gana un runtime RPC en esta feature; los renderers
  estáticos declaran `supports_actions=False` y siguen usando deep links).
- Un registro de funciones A2UI separado de tools (rechazado en §3 de
  clarificación: "todas las tools del ToolManager").
- Enrutar sobres A2UI por el POST de AgentTalk (rechazado: endpoint dedicado).
- Allowlist de funciones por superficie (rechazado: el control es el
  `PermissionContext` del usuario).
- Función inline `inlineCatalogs` del renderer (`acceptsInlineCatalogs=false`).
- Push de `updateDataModel`/`updateComponents` iniciado por el agente fuera de
  una respuesta a un sobre R→A (multi-superficie proactiva) — feature posterior.

---

## 2. Architectural Design

### Overview

Se añade un **runtime A2UI** en core (`parrot/outputs/a2ui/runtime/`) que es
puro protocolo: recibe sobres R→A ya deserializados (por `a2ui-v1-dialect`),
los despacha y devuelve sobres A→R. No conoce HTTP ni A2A (invariante G8: no
importa `parrot.bots`/`parrot.clients`); recibe por inyección un
`FunctionExecutor` (adaptador sobre `ToolManager.execute_tool`) y un
`SurfaceStateStore` (adaptador sobre `ConversationMemory`).

Flujo `callAgentFunction`:

1. Transporte (HTTP dedicado o A2A `DataPart`) autentica, resuelve `agent`,
   `user_id`, `session_id` y construye el `PermissionContext`.
2. `A2UIRuntime.dispatch(envelope, ctx)` valida el sobre (una sola clave,
   `version:"v1.0"`), resuelve `callFunction.catalogId` (componente →
   superficie → error `INVALID_FUNCTION_CALL`), comprueba que la función
   existe en el catálogo parrot exportado con `allowedCallers ∈
   {rendererOrAgent, rendererOnly→rechazo}`.
3. `FunctionExecutor.call(name, args, ctx)` → `ToolManager.execute_tool(name,
   args, permission_context=ctx.permission_context)` → `ToolResult`.
4. `ToolResult.success` → `agentFunctionResponse{functionCallId, value}`;
   `status='forbidden'` → `error{code:"FORBIDDEN"}`; `not_found` →
   `error{code:"INVALID_FUNCTION_CALL"}`; excepción → `error{code:"INTERNAL"}`.
   `value` es `ToolResult.result` serializado a JSON; si el tool devolvió un
   `a2ui_envelope`, se emite además como `updateComponents`/`updateDataModel`.

Flujo `action`: se persiste `dataModel` (si `sendDataModel`) por
`surfaceId` en `ConversationHistory.metadata["a2ui_surfaces"][surfaceId]`, y
el `action` se convierte en un turno de usuario estructurado (el mismo
formato que ya usa el resume de deep links) que entra al bot por el camino
normal (`AgentTalk`/A2A), con `a2ui_surface_state` disponible en el contexto
del turno. `userMessage`, si viene, es el texto visible del turno.

Flujo `callRendererFunction`: el agente (una tool o el post-loop) encola
`callRendererFunction{functionCallId, callFunction}` en la respuesta; el
runtime guarda la llamada pendiente por `functionCallId` en la memoria de
sesión (TTL) y, cuando llega `rendererFunctionResponse`/`error`, la resuelve
(future en streaming; en HTTP request-response se entrega al siguiente
`dispatch` como resultado pendiente).

Descubrimiento: `catalog/export.py` (de `a2ui-v1-dialect`) gana
`export_functions(tool_manager)`: cada tool → `FunctionDefinition{args: schema
de la tool, returnType: "any", allowedCallers: "rendererOrAgent",
requiresUserActivation: tool.a2ui_requires_user_activation (default False)}`.
`A2AServer` añade al Agent Card `AgentExtension(uri=A2UI_EXTENSION_URI,
params={"a2uiAgentCapabilities": {"v1.0": {"supportedCatalogIds": [parrot,
basic], "acceptsInlineCatalogs": false}}})`.

### Component Diagram
```
Renderer (web / A2A client)
   │  POST /api/v1/agents/{id}/a2ui  ──┐        A2A message/send (DataPart a2ui+json)
   │                                   ▼                     │
   │                          A2UIHandler (server)     A2AServer._handle_send_message
   │                                   │                     │
   │                                   └──── build A2UICallContext ────┘
   │                                              │  (agent, user_id, session_id,
   │                                              │   PermissionContext)
   │                                              ▼
   │                              A2UIRuntime.dispatch(envelope, ctx)   [core, G8-safe]
   │                                 │            │              │
   │              callAgentFunction  │   action   │   renderer   │ FunctionResponse/error
   │                                 ▼            ▼              ▼
   │                       FunctionExecutor   SurfaceStateStore   PendingCallRegistry
   │                       (ToolManager)      (ConversationMemory) (memory, TTL)
   │                                 │            │
   ◄──── agentFunctionResponse / error / updateDataModel / updateComponents ────
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.manager.ToolManager.execute_tool()` | uses | despacho de funciones; `permission_context=` obligatorio |
| `parrot.tools.abstract.ToolResult` | uses | mapeo success/status → `agentFunctionResponse`/`error` |
| `parrot.auth.permission.PermissionContext` | uses | construido por el transporte a partir del usuario autenticado |
| `parrot.memory.abstract.ConversationMemory` / `ConversationHistory.metadata` | extends (uso de `metadata`) | estado de superficies y llamadas pendientes |
| `parrot.outputs.a2ui.models` (v1.0, de `a2ui-v1-dialect`) | uses | sobres R→A / A→R |
| `parrot.outputs.a2ui.serialization` | uses | `serialize`/`deserialize`/`to_jsonl` |
| `parrot.outputs.a2ui.catalog` + `catalog/export.py` (de `a2ui-v1-dialect`) | extends | `export_functions()` |
| `parrot.outputs.a2ui.deeplink.DeepLinkService` / `ResumePayload` | uses | el payload de deep link es un `action` v1.0; el resume pasa por el mismo `dispatch` |
| `parrot.a2a.models.AgentCard/AgentCapabilities/AgentExtension` | extends | extensión A2UI + `a2uiAgentCapabilities` |
| `parrot.a2a.models.Artifact.from_a2ui_envelope` | modifies | ya no rechaza componentes con `action` cuando el agente declara la extensión |
| `parrot.a2a.server.A2AServer` (ai-parrot-server) | extends | detecta `DataPart` con `mimeType: application/a2ui+json` en `_handle_send_message`/`_handle_stream_message` |
| `parrot.handlers.agent.AgentTalk` (ai-parrot-server) | reuses | `_get_user_session()` y patrón de auth para el nuevo handler |
| `parrot.manager.manager` route registration (ai-parrot-server) | extends | `router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)` |
| `parrot.handlers.deeplink.DeepLinkResumeHandler` | modifies | `build_structured_message` emite el `action` v1.0 |
| `parrot.bots.base.AbstractBot` | extends (mínimo) | hook `a2ui_surface_state` en el contexto del turno; sin nueva API pública obligatoria |

### Data Models
```python
# parrot/outputs/a2ui/runtime/models.py  (todos Pydantic v2; wire models vienen de a2ui-v1-dialect)

class A2UICallContext(BaseModel):
    """Contexto de una invocación R→A construido por el transporte."""
    agent_id: str
    user_id: Optional[str]
    session_id: str
    surface_id: Optional[str]
    permission_context: Any            # parrot.auth.permission.PermissionContext (no se re-modela)
    transport: Literal["http", "a2a", "deeplink"]
    streaming: bool = False

class FunctionCallRecord(BaseModel):
    """Llamada agent→renderer pendiente (correlación por functionCallId)."""
    function_call_id: str
    surface_id: Optional[str]
    call: str
    catalog_id: Optional[str]
    args: dict[str, Any]
    created_at: datetime
    ttl_seconds: int = 900

class SurfaceState(BaseModel):
    surface_id: str
    catalog_id: str
    data_model: dict[str, Any]
    updated_at: datetime

class DispatchResult(BaseModel):
    """Salida de A2UIRuntime.dispatch: sobres A→R a devolver + efectos."""
    messages: list[dict[str, Any]]      # ya serializados (version:"v1.0")
    user_turn: Optional[str] = None     # turno estructurado a inyectar al bot (para `action`)
    surface_state: Optional[SurfaceState] = None

class A2UIErrorCode(str, Enum):
    INVALID_FUNCTION_CALL = "INVALID_FUNCTION_CALL"
    UNALLOWED_PARENT = "UNALLOWED_PARENT"
    UNALLOWED_CHILD = "UNALLOWED_CHILD"
    FORBIDDEN = "FORBIDDEN"             # parrot-specific (extensión)
    NOT_FOUND = "NOT_FOUND"
    INTERNAL = "INTERNAL"
    TIMEOUT = "TIMEOUT"
```

### New Public Interfaces
```python
# parrot/outputs/a2ui/runtime/__init__.py
class FunctionExecutor(Protocol):
    async def call(self, name: str, args: dict[str, Any], ctx: A2UICallContext) -> "ToolResult": ...
    def list_functions(self) -> list["FunctionDefinition"]: ...

class SurfaceStateStore(Protocol):
    async def get(self, session_id: str, surface_id: str) -> Optional[SurfaceState]: ...
    async def put(self, session_id: str, state: SurfaceState) -> None: ...
    async def delete(self, session_id: str, surface_id: str) -> None: ...

class PendingCallRegistry(Protocol):
    async def add(self, session_id: str, record: FunctionCallRecord) -> None: ...
    async def resolve(self, session_id: str, function_call_id: str, value: Any, error: Optional[dict]) -> Optional[FunctionCallRecord]: ...

class A2UIRuntime:
    def __init__(self, *, executor: FunctionExecutor, surfaces: SurfaceStateStore,
                 pending: PendingCallRegistry, catalog_id: str = DEFAULT_CATALOG_ID) -> None: ...
    async def dispatch(self, envelope: dict[str, Any] | A2UIRendererMessage, ctx: A2UICallContext) -> DispatchResult: ...
    async def call_renderer(self, session_id: str, surface_id: str, call: str, args: dict[str, Any],
                            *, catalog_id: Optional[str] = None) -> tuple[str, dict[str, Any]]:
        """Registra la llamada pendiente y devuelve (functionCallId, sobre callRendererFunction serializado)."""

# parrot/outputs/a2ui/runtime/adapters.py  (viven en core pero importan tools/memory bajo TYPE_CHECKING + inyección)
class ToolManagerExecutor(FunctionExecutor): ...       # envuelve ToolManager.execute_tool
class ConversationMemorySurfaceStore(SurfaceStateStore, PendingCallRegistry): ...  # usa ConversationHistory.metadata

# parrot/outputs/a2ui/catalog/export.py (extiende el de a2ui-v1-dialect)
def export_functions(executor: FunctionExecutor) -> dict[str, dict[str, Any]]: ...
def agent_capabilities(catalog_ids: list[str]) -> dict[str, Any]:
    """→ {"v1.0": {"supportedCatalogIds": [...], "acceptsInlineCatalogs": False}}"""

# ai-parrot-server: parrot/handlers/a2ui.py
class A2UIHandler(BaseView):
    async def post(self) -> web.Response: ...        # sobre R→A → JSON {"messages": [...A→R...]}
    async def get(self) -> web.StreamResponse: ...   # SSE de sobres A→R pendientes (callRendererFunction)

# ai-parrot: parrot/tools/abstract.py (atributo opcional, sin cambio de firma)
class AbstractTool:
    a2ui_requires_user_activation: bool = False   # → FunctionDefinition.requiresUserActivation
```

---

## 3. Module Breakdown

### Module 1: Runtime models y códigos de error
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/models.py`
- **Responsibility**: `A2UICallContext`, `FunctionCallRecord`, `SurfaceState`, `DispatchResult`, `A2UIErrorCode`; helper `error_envelope(code, message, function_call_id)` que produce `{"version":"v1.0","error":{...}}`.
- **Depends on**: `a2ui-v1-dialect` models/serialization.

### Module 2: Protocolos y `A2UIRuntime.dispatch`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/__init__.py`, `runtime/dispatch.py`
- **Responsibility**: validar sobre R→A; resolver `catalogId` de la función; comprobar `allowedCallers`; despachar `callAgentFunction` → `FunctionExecutor`; `action` → persistir estado + turno estructurado; `rendererFunctionResponse`/`error` → `PendingCallRegistry.resolve`; `call_renderer()`; mapeo `ToolResult`→sobres. Sin imports de `parrot.bots`/`parrot.clients`/`parrot.tools`/`parrot.memory` (solo Protocols).
- **Depends on**: Module 1.

### Module 3: Adaptadores ToolManager y ConversationMemory
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py`
- **Responsibility**: `ToolManagerExecutor` (`execute_tool(name, args, permission_context=ctx.permission_context)`; `list_functions()` desde `get_tool_schemas()`); `ConversationMemorySurfaceStore` (lee/escribe `ConversationHistory.metadata["a2ui_surfaces"]` y `["a2ui_pending_calls"]` con expiración por `created_at + ttl`). Import lazy de `parrot.tools`/`parrot.memory` dentro de las clases para preservar G8 (test `adapters/test_import_rule.py` extendido).
- **Depends on**: Module 2.

### Module 4: Export de funciones y `agent_capabilities`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py` (extiende), `packages/ai-parrot/src/parrot/tools/abstract.py` (atributos `a2ui_requires_user_activation` y `a2ui_hidden`)
- **Responsibility**: `export_functions()` → mapa `functions` del `catalog_definition.json` (nombre UAX #31 — las tools con nombres no conformes se exponen con nombre saneado y se registra un warning); omite las tools con `a2ui_hidden=True` (OQ resuelta §8); `agent_capabilities()`.
- **Nota de integración (verificado 2026-08-29)**: `export_catalog_definition()` YA existe (`catalog/export.py`, FEAT-470 TASK-2540) y ya emite un bloque `functions` construido desde `list_functions()` del registro de catálogo. `export_functions(executor)` es una fuente **adicional** (las tools del `ToolManager`), y debe **fusionarse** con ese bloque sin pisar las funciones del Basic Catalog copiadas verbatim del schema oficial. Colisión de nombres tool↔catálogo ⇒ error explícito al exportar.
- **Depends on**: Module 3; `catalog/export.py` de `a2ui-v1-dialect`.

### Module 5: A2A — Agent Card y `DataPart` inbound
- **Path**: `packages/ai-parrot/src/parrot/a2a/models.py`, `packages/ai-parrot-server/src/parrot/a2a/server.py`
- **Responsibility**: `AgentExtension` A2UI con `params.a2uiAgentCapabilities` en `AgentCapabilities.extensions`; en `_handle_send_message`/`_handle_stream_message`, si algún `Part.data` tiene `metadata.mimeType == "application/a2ui+json"` se construye `A2UICallContext(transport="a2a")` y se llama `A2UIRuntime.dispatch`; las respuestas A→R salen como `Part(data=..., metadata={"mimeType": "application/a2ui+json"})` dentro de un `Artifact`. `Artifact.from_a2ui_envelope` deja de rechazar componentes con `action` cuando `allow_actions=True`. `callRendererFunction` se entrega por DOS vías (OQ resuelta §8): en el SSE de `message/stream` y encolado en `PendingCallRegistry` para adjuntarse a la respuesta del siguiente `message/send`.
- **Depends on**: Modules 2–4.

### Module 6: Endpoint HTTP dedicado
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/a2ui.py`, `packages/ai-parrot-server/src/parrot/manager/manager.py` (registro de ruta)
- **Responsibility**: `A2UIHandler` en `/api/v1/agents/{agent_id}/a2ui`: POST recibe un sobre R→A (o lista JSONL), reutiliza la resolución de agente/usuario/sesión de `AgentTalk._get_user_session`, construye `PermissionContext`, llama `dispatch`, y responde `{"messages": [...]}` (`Content-Type: application/a2ui+json` cuando es un único sobre; JSON con lista en caso contrario). GET abre un stream (SSE, `text/event-stream`, un evento por sobre A→R) para entregar `callRendererFunction` pendientes de la sesión. `GET /api/v1/agents/{agent_id}/a2ui/capabilities` devuelve `agent_capabilities()` en JSON para descubrimiento no-A2A (OQ resuelta §8). Si el `DispatchResult` trae `user_turn`, el handler lo inyecta como turno del bot por el mismo camino que AgentTalk POST y añade la respuesta del bot (incluido su `a2ui_envelope`) a `messages`.
- **Depends on**: Modules 2–4.

### Module 7: Deep links → `action` v1.0
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/deeplink.py`, `packages/ai-parrot-integrations/src/parrot/integrations/a2ui_resume.py`, `packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py`
- **Responsibility**: enrutar el resume por `dispatch(..., ctx.transport="deeplink")` y montar `setup_deeplink_routes` en `manager.py`.
- **CORRECCIÓN (verificado 2026-08-29 — el spec original estaba desfasado)**: `ResumePayload.action_payload` **ya** es un sobre `action` v1.0 y lo valida en construcción (`outputs/a2ui/deeplink.py:53-90`, `field_validator` que hace `A2UIRendererMessage.model_validate` y exige `envelope.action is not None`). `build_structured_message` **ya no** emite `a2ui_action_resume`: emite `{"type": "a2ui_action", "action": payload.action_payload}` (`handlers/deeplink.py:51-63`), el mismo tag que ya consumen Teams (`integrations/msteams/wrapper.py:414-428`), Telegram (`integrations/telegram/wrapper.py:1564`) y `integrations/a2ui_resume.py:34`. Todo eso lo hizo FEAT-470 (G6/TASK-2545). **Por tanto el alcance real del Módulo 7 se reduce a dos cosas**: (a) hacer que `DeepLinkResumeHandler.handle` pase por `A2UIRuntime.dispatch` con `transport="deeplink"` en lugar de entregar el string JSON crudo al `invoker`; (b) montar `setup_deeplink_routes` en `manager.py` — **sigue sin montarse**, verificado: `grep -rn "setup_deeplink_routes" packages/*/src` sólo devuelve su definición (`handlers/deeplink.py:116`) y su propio docstring. NO reescribir el formato del payload ni el tag `a2ui_action`: romperías Teams y Telegram.
- **Depends on**: Module 6.

### Module 8: Contexto de turno `a2ui_surface_state`
- **Path**: `packages/ai-parrot/src/parrot/bots/base.py` (hook mínimo)
- **Responsibility**: cuando un turno proviene de `dispatch` con `surface_state`, el bot recibe `a2ui_surface_state: SurfaceState` en el contexto del turno (mismo mecanismo que hoy inyecta `interactive_envelope`/`infographic_envelope`, líneas 1421–1464) y lo expone a las tools vía kwargs reservados (`_a2ui_surface_state`), siguiendo la convención de `_permission_context`.
- **Depends on**: Modules 2–3.

### Module 9: Docs y migración
- **Path**: `docs/outputs/a2ui-agent-functions.md`, `docs/migration/feat-273-a2ui-deprecations.md` (añadir sección)
- **Responsibility**: documentar el endpoint, el flujo A2A, cómo marcar `a2ui_requires_user_activation`, y el formato del turno estructurado.
- **Depends on**: todos.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_error_envelope_shape` | 1 | `{"version":"v1.0","error":{code,message,functionCallId?}}` valida contra `renderer_to_agent.json`/`agent_to_renderer.json` según dirección |
| `test_dispatch_rejects_multi_key_envelope` | 2 | sobre con dos claves → `error INVALID_FUNCTION_CALL` sin ejecutar nada |
| `test_dispatch_call_agent_function_success` | 2 | executor fake devuelve `ToolResult(success=True)` → `agentFunctionResponse{value}` con el mismo `functionCallId` |
| `test_dispatch_call_agent_function_forbidden` | 2 | `ToolResult(status="forbidden")` → `error{code:"FORBIDDEN"}` |
| `test_dispatch_call_agent_function_not_found` | 2 | tool ausente → `error{code:"INVALID_FUNCTION_CALL"}` |
| `test_dispatch_call_agent_function_exception` | 2 | excepción del executor → `error{code:"INTERNAL"}`, sin traceback en `message` |
| `test_dispatch_catalog_resolution_precedence` | 2 | `callFunction.catalogId` explícito gana sobre el default; sin ninguno → error |
| `test_dispatch_renderer_only_function_rejected` | 2 | función `allowedCallers=rendererOnly` invocada por renderer→agent → error |
| `test_dispatch_action_persists_data_model` | 2 | `action` con `sendDataModel` → `SurfaceStateStore.put` y `DispatchResult.user_turn` |
| `test_dispatch_action_without_data_model` | 2 | no toca el store; `user_turn` contiene `name`/`context`/`userMessage` |
| `test_call_renderer_registers_pending` | 2 | `call_renderer()` → `functionCallId` único + sobre `callRendererFunction` válido |
| `test_renderer_function_response_resolves_pending` | 2 | `rendererFunctionResponse` con id registrado → `resolve()`; id desconocido → `error NOT_FOUND` |
| `test_tool_manager_executor_passes_permission_context` | 3 | `execute_tool` recibe `permission_context=ctx.permission_context` |
| `test_tool_manager_executor_list_functions_uax31` | 3 | nombres no UAX #31 saneados + warning |
| `test_memory_store_roundtrip_and_ttl` | 3 | put/get por surfaceId; pending expirado no se resuelve |
| `test_runtime_import_rule` | 3 | `runtime/` no importa `parrot.bots`/`parrot.clients` a nivel de módulo (extiende `adapters/test_import_rule.py`) |
| `test_export_functions_schema` | 4 | `functions` válido contra `catalog_definition.json` v1.0 (`allowedCallers`, `requiresUserActivation`) |
| `test_agent_capabilities_shape` | 4 | valida contra `agent_capabilities.json` |
| `test_agent_card_declares_a2ui_extension` | 5 | Agent Card v1.0 incluye `extensions[].uri == A2UI_EXTENSION_URI` con `params.a2uiAgentCapabilities` |
| `test_artifact_from_a2ui_envelope_allows_actions` | 5 | con `allow_actions=True` no lanza; sin él, comportamiento actual |
| `test_a2a_send_message_dispatches_a2ui_part` | 5 | `DataPart` con `mimeType application/a2ui+json` → `dispatch`; respuesta en `Artifact` con mismo mimeType |
| `test_a2ui_handler_post_call_agent_function` | 6 | POST sobre válido → 200 `{"messages":[agentFunctionResponse]}` |
| `test_a2ui_handler_post_invalid_envelope` | 6 | → 400 con sobre `error` |
| `test_a2ui_handler_post_action_injects_turn` | 6 | `action` → turno del bot invocado; `messages` incluye `a2ui_envelope` del bot si existe |
| `test_a2ui_handler_requires_auth` | 6 | sin usuario autenticado → 401 (mismo comportamiento que AgentTalk) |
| `test_a2ui_handler_stream_delivers_pending_calls` | 6 | GET SSE emite `callRendererFunction` registrado |
| `test_deeplink_resume_dispatches_action_v1` | 7 | payload = sobre `action`; `build_structured_message` ya no emite `a2ui_action_resume` |
| `test_deeplink_routes_mounted` | 7 | `manager` registra `/api/v1/a2ui/resume/web` |
| `test_bot_receives_surface_state` | 8 | turno con `surface_state` → tools reciben `_a2ui_surface_state` |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_http_call_agent_function` | Agente con una tool `@tool` real; POST `callAgentFunction` → `agentFunctionResponse` con el resultado de la tool |
| `test_e2e_http_action_with_send_data_model` | `action` con `sendDataModel` → estado persistido en Redis (fixture) → siguiente turno lo ve |
| `test_e2e_a2a_round_trip` | `A2AServer` + cliente A2A: card descubre la extensión; `message/send` con `DataPart` a2ui → `Artifact` a2ui |
| `test_e2e_call_renderer_function_correlation` | tool llama `runtime.call_renderer()`; stream entrega el sobre; `rendererFunctionResponse` resuelve el pending |
| `test_e2e_deeplink_to_action` | click en deep link → `action` v1.0 → turno del bot |

### Test Data / Fixtures
```python
@pytest.fixture
def a2ui_call_ctx() -> A2UICallContext: ...          # user/session/permission_context fake
@pytest.fixture
def fake_executor() -> FunctionExecutor: ...          # programable: success/forbidden/not_found/raise
@pytest.fixture
def memory_store() -> ConversationMemorySurfaceStore: ...  # sobre FileConversationMemory
@pytest.fixture
def v1_schemas() -> dict: ...                         # agent_to_renderer/renderer_to_agent/agent_capabilities vendorizados por a2ui-v1-dialect
@pytest.fixture
def call_agent_function_envelope() -> dict:
    return {"version": "v1.0", "callAgentFunction": {"functionCallId": "fc-1",
            "callFunction": {"call": "get_weather", "args": {"location": "Caracas"}}}}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Todos los tests unitarios pasan (`pytest packages/ai-parrot/tests/outputs/a2ui/runtime packages/ai-parrot/tests/a2a packages/ai-parrot-server/tests -v`).
- [ ] Todos los tests de integración pasan (Redis y aiohttp test client como fixtures).
- [ ] AC-G1: cualquier tool registrada en el `ToolManager` del agente es invocable vía `callAgentFunction` y devuelve `agentFunctionResponse` con el mismo `functionCallId`.
- [ ] AC-G2: `callRendererFunction` emitido por el agente se correlaciona con `rendererFunctionResponse`/`error` por `functionCallId`, en HTTP (SSE) y en A2A streaming; pendientes expiran a los 900 s.
- [ ] AC-G3: con `sendDataModel`, el último `dataModel` por `surfaceId` se persiste en `ConversationHistory.metadata["a2ui_surfaces"]` y las tools lo reciben como `_a2ui_surface_state`.
- [ ] AC-G4: el `catalog_definition.json` de parrot incluye `functions` con `allowedCallers` y `requiresUserActivation` y valida contra el schema v1.0.
- [ ] AC-G5: el Agent Card expone la extensión `https://a2ui.org/a2a-extension/a2ui/v1.0` con `a2uiAgentCapabilities`; `DataPart` inbound con `mimeType: application/a2ui+json` se despacha; outbound usa el mismo mimeType.
- [ ] AC-G6: existe `/api/v1/agents/{agent_id}/a2ui` (POST + GET stream), con la misma autenticación que AgentTalk; sobres inválidos → 400 con sobre `error`.
- [ ] AC-G7: toda invocación pasa `permission_context` a `execute_tool`; una tool denegada produce `error{code:"FORBIDDEN"}` y no se ejecuta.
- [ ] Todo sobre A→R emitido por el runtime valida contra `agent_to_renderer.json`; todo sobre R→A aceptado valida contra `renderer_to_agent.json`.
- [ ] `runtime/` no importa `parrot.bots`/`parrot.clients` a nivel de módulo (test de import rule).
- [ ] `setup_deeplink_routes` queda montado en el manager y el resume de deep link emite un `action` v1.0.
- [ ] Sin cambios rompientes en la API pública de tools/agents; `a2ui_requires_user_activation` es opcional con default `False`.
- [ ] AC-OQ1: `AbstractTool.a2ui_hidden=True` excluye la tool de `export_functions()` y de la invocación por `callAgentFunction`.
- [ ] AC-OQ2: `GET /api/v1/agents/{agent_id}/a2ui/capabilities` devuelve el mismo documento `agent_capabilities()` que publica el Agent Card, y valida contra `agent_capabilities.json`.
- [ ] AC-OQ3: `callRendererFunction` se entrega tanto por el SSE de `message/stream` como encolado en la respuesta del siguiente `message/send`.
- [ ] AC-OQ4: un `action` con `userMessage` produce un turno de usuario visible; sin `userMessage`, un turno de sistema; en ninguno de los dos casos el `dataModel` aparece en el texto del turno.
- [ ] AC-OQ5: un `dataModel` mayor que `A2UI_MAX_DATA_MODEL_BYTES` (1 MiB) produce `error{code:"INTERNAL"}` y conserva el estado previo de la superficie.
- [ ] AC-F1: `ActionMessage` acepta `dataModel` (campo explícito, no `extra="allow"`) y sigue validando contra `renderer_to_agent.json`; `callAgentFunction` con `dataModel` se RECHAZA (el schema lo prohíbe con `additionalProperties: false`).
- [ ] Documentación en `docs/outputs/a2ui-agent-functions.md`.
- [ ] Rendimiento: `dispatch` de un `callAgentFunction` añade < 5 ms de overhead sobre `execute_tool` (medido en test con executor no-op).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verificado el 2026-08-28 sobre `dev` (`a518fee03`). Todo lo relativo al wire v1.0
> (modelos de mensajes, `catalog/export.py`, `compat`) **todavía no existe**: lo
> crea `a2ui-v1-dialect` y esta feature depende de su merge.

### Verified Imports
```python
from parrot.tools.manager import ToolManager                       # tools/manager.py:233
from parrot.tools.abstract import AbstractTool, ToolResult          # tools/abstract.py:235, :200
from parrot.auth.permission import PermissionContext                # auth/permission.py:81
from parrot.memory.abstract import ConversationMemory, ConversationHistory, ConversationTurn  # memory/abstract.py:135, :51, :11
from parrot.memory.redis import RedisConversation                   # memory/redis.py:10
from parrot.memory.file import FileConversationMemory               # memory/file.py:9
from parrot.a2a.models import AgentCard, AgentCapabilities, AgentExtension, Artifact, Part, A2UI_EXTENSION_URI, A2UI_MEDIA_TYPE  # a2a/models.py:959, :930, :518, ~:375, :129, :338, :339
from parrot.outputs.a2ui.deeplink import DeepLinkService, DeepLinkExpiredError, ResumePayload  # outputs/a2ui/deeplink.py:66, :49, :53
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID     # catalog/base.py:38
from parrot.outputs.a2ui.serialization import serialize, deserialize, to_jsonl  # serialization.py:48, :64, :98
# ai-parrot-server
from parrot.a2a.server import A2AServer                             # ai-parrot-server/src/parrot/a2a/server.py:77
from parrot.handlers.agent import AgentTalk                         # handlers/agent.py:104
from parrot.handlers.deeplink import DeepLinkResumeHandler, build_structured_message, setup_deeplink_routes  # handlers/deeplink.py:~66, :55, :113
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):                                     # line 233
    _tools: Dict[str, Union[ToolDefinition, AbstractTool]]                 # line 273
    def get_tool_schemas(...)                                               # line 1121
    def get_tool(self, tool_name: str) -> Optional[Any]                     # line 1215
    def list_tools(self) -> List[str]                                       # line 1235
    def get_tools(self) -> Dict[str, Any]                                   # line 1239
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                           permission_context: Optional["PermissionContext"] = None) -> Any  # line 1519
        # tool ausente → ToolResult(success=False, status='not_found', error=..., result=None)  # line ~1540
    async def execute_tool_call(...)                                        # line 1869

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                                # line 200
    success: bool = True; status: str = "success"; result: Any
    error: Optional[str] = None; metadata: Dict[str, Any]; timestamp: str; files: Optional[list]
class AbstractTool(EventEmitterMixin, ABC):                                 # line 235
    async def _execute(self, **kwargs) -> Any                               # line 490
    def get_schema(self) -> Dict[str, Any]                                  # line 502
    def get_tool_schema(self) -> Dict[str, Any]                             # line 582
    async def execute(self, *args, **kwargs) -> ToolResult                  # line 797
        # kwargs reservados: _permission_context, _resolver; status='forbidden' si denegado

# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationTurn                                                      # line 11
class ConversationHistory:                                                  # line 51
    session_id: str; user_id: str; chatbot_id: Optional[str]
    turns: List[ConversationTurn]; created_at; updated_at; metadata: Dict[str, Any]
class ConversationMemory(ABC):                                              # line 135
    async def create_history(...)                                           # line ~146
    async def get_history(...)                                              # line 157
    async def update_history(self, history: ConversationHistory) -> None    # line ~167
    async def add_turn(...)                                                 # line ~172
    async def clear_history(...)                                            # line ~183
    async def list_sessions(...)                                            # line ~193

# packages/ai-parrot/src/parrot/a2a/models.py
class Part:  text, file_uri, file_bytes, file_media_type, filename, data: Optional[Dict], metadata: Optional[Dict]  # line 129
A2UI_EXTENSION_URI = "https://a2ui.org/extensions/a2a/display/v1"   # line 338  ← a2ui-v1-dialect lo cambia a https://a2ui.org/a2a-extension/a2ui/v1.0
A2UI_MEDIA_TYPE = "application/vnd.a2ui.envelope+json"              # line 339  ← a2ui-v1-dialect lo cambia a application/a2ui+json
def _reject_action_components(envelope: Dict[str, Any]) -> None     # line 342
class Artifact: from_a2ui_envelope(cls, envelope, *, name="a2ui-surface", artifact_id=None)  # line ~375
class AgentExtension: uri: str; description; required: bool = False; params: Optional[Dict]  # line 518
class AgentCapabilities: ... extensions: List[AgentExtension]       # line 930, :935
class AgentCard: capabilities: AgentCapabilities                    # line 959, :972 ; to_dict("1.0") line ~1046

# packages/ai-parrot-server/src/parrot/a2a/server.py
class A2AServer:                                                    # line 77
    def __init__(...)  self.capabilities = capabilities or AgentCapabilities(streaming=True)  # line 111, :169
    def setup(self, app, ...)                                       # line 219  (rutas: message/send :279, message/stream :280, message:send :288)
    async def _handle_send_message(self, request) -> web.Response   # line 1092
    async def _handle_stream_message(self, request) -> web.StreamResponse  # line 1132

# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView):                                          # line 104
    async def post(self)                                            # line 1504
    async def put(self)                                             # line 2170
    async def get(self)                                             # line 2268
    async def _get_user_session(self, data: dict) -> tuple[str|None, str|None]  # line 912
    # stream final dict: envelope['a2ui_envelope'] = ai_message.a2ui_envelope   # lines 2701-2705
    # non-stream A2UI: {"input","output","output_mode":"a2ui","a2ui_envelope"}  # lines 2819-2827
# packages/ai-parrot-server/src/parrot/manager/manager.py
router.add_view("/api/v1/agents/chat/{agent_id}", AgentTalk)                      # line 1933
router.add_view("/api/v1/agents/chat/{agent_id}/{method_name}", AgentTalk)        # line 1934

# packages/ai-parrot-server/src/parrot/handlers/deeplink.py
ResumeInvoker = Callable[..., Awaitable[Any]]  # (agent_name, query, session_id, user_id)   # line ~31
def build_structured_message(payload: ResumePayload) -> str   # emite {"type":"a2ui_action_resume","action":...}  # line ~55
class DeepLinkResumeHandler: __init__(service, invoker); async def handle(token) -> (body, status)  # line ~66
def setup_deeplink_routes(...)                                                    # line 113

# packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py
_KEY_TEMPLATE = "a2ui:deeplink:{token_id}"; _DEFAULT_TTL_SECONDS = 900             # lines 41-42
class ResumePayload(BaseModel)  (campo action_payload)                             # line 53
class DeepLinkService: __init__(...) line 77; _resume_url(channel, token_id) line 94

# packages/ai-parrot/src/parrot/bots/base.py
# hooks donde se inyectan envelopes al response: lines 498-500, 1421-1423, 1455-1457, 1492-1494
# comentario sobre permission_context kwarg de execute_tool: line 1805
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ToolManagerExecutor.call` | `ToolManager.execute_tool(name, params, permission_context=)` | llamada async | `tools/manager.py:1519` |
| `ToolManagerExecutor.list_functions` | `ToolManager.get_tool_schemas()` | llamada | `tools/manager.py:1121` |
| `ConversationMemorySurfaceStore` | `ConversationMemory.get_history/update_history`, `ConversationHistory.metadata` | dict `metadata["a2ui_surfaces"]`, `["a2ui_pending_calls"]` | `memory/abstract.py:51-59,135-170` |
| `A2UIHandler` | `AgentTalk._get_user_session(data)` (extraer y reutilizar) | herencia/composición | `handlers/agent.py:912` |
| `A2UIHandler` | `manager.py` `router.add_view` | registro | `manager/manager.py:1933` |
| `A2AServer._handle_send_message` | `Part.data` + `Part.metadata["mimeType"]` | inspección de parts | `a2a/server.py:1092`, `a2a/models.py:129` |
| Agent Card | `AgentCapabilities.extensions.append(AgentExtension(...))` | dataclass | `a2a/models.py:518,930` |
| Deep link resume | `DeepLinkResumeHandler.handle` → `A2UIRuntime.dispatch` | reemplaza `build_structured_message` | `handlers/deeplink.py:55-80` |
| `_a2ui_surface_state` kwarg | convención `_permission_context`/`_resolver` en `AbstractTool.execute` | kwargs reservados | `tools/abstract.py:797-812` |

### Contract Refresh — 2026-08-29 (re-verified on `dev` @ `dd06d939c`)

> The §6 block above was written on `dev` @ `a518fee03`, **before** FEAT-470
> merged. FEAT-470 (`a2ui-v1-dialect`) is now merged (PR #1263). Everything it
> was supposed to create **exists**; several line numbers drifted, and two
> assumptions in the original contract are now WRONG. Use the values below —
> they override §6 wherever they disagree.

**Dependency satisfied.** Verified present on `dev`: the ten v1.0 message
models in `outputs/a2ui/models.py`, `catalog/export.py`, and all four vendored
schemas under `outputs/a2ui/catalog/basic/spec/` (`agent_to_renderer.json`,
`renderer_to_agent.json`, `agent_capabilities.json`, `catalog_definition.json`).
`A2UI_EXTENSION_URI` and `A2UI_MEDIA_TYPE` already carry their v1.0 values.

**Corrected line numbers** (the §6 values are stale — do not trust them):

| Symbol | File | §6 said | Actually |
|---|---|---|---|
| `A2UI_EXTENSION_URI` = `https://a2ui.org/a2a-extension/a2ui/v1.0` | `parrot/a2a/models.py` | 338 (old value) | **335** (already v1.0) |
| `A2UI_MEDIA_TYPE` = `application/a2ui+json` | `parrot/a2a/models.py` | 339 (old value) | **336** (already v1.0) |
| `_reject_action_components(components)` | `parrot/a2a/models.py` | 342 | **339** — signature takes `components`, NOT an `envelope` |
| `Artifact.from_a2ui_envelope` | `parrot/a2a/models.py` | ~375 | **372** |
| `class AgentExtension` | `parrot/a2a/models.py` | 518 | **511** (`to_dict` at 519) |
| `class AgentCapabilities` | `parrot/a2a/models.py` | 930 | **928** (`extensions` field at **934**) |
| `class AgentTalk` | `ai-parrot-server/.../handlers/agent.py` | 104 | **110** |
| `AgentTalk._get_user_session` | `ai-parrot-server/.../handlers/agent.py` | 912 | **867** |
| `AgentTalk.post` / `.put` / `.get` | `ai-parrot-server/.../handlers/agent.py` | 1504 / 2170 / 2268 | **1441** / **2075** / **2157** |
| `build_structured_message` | `ai-parrot-server/.../handlers/deeplink.py` | ~55 | **51** |
| `class DeepLinkResumeHandler` | `ai-parrot-server/.../handlers/deeplink.py` | ~66 | **66** ✓ |
| `setup_deeplink_routes` | `ai-parrot-server/.../handlers/deeplink.py` | 113 | **116** |
| `_DEFAULT_TTL_SECONDS` | `outputs/a2ui/deeplink.py` | 41-42 (`= 900`) | **42**, written `15 * 60` |
| `class ResumePayload` | `outputs/a2ui/deeplink.py` | 53 | **53** ✓ (now has a `field_validator`) |

**Still accurate** (spot-checked, unchanged): `ToolManager` class 233 /
`execute_tool` **1519** / `get_tool_schemas` **1121** / `get_tool` 1215 /
`list_tools` 1235 / `get_tools` 1239; `ToolResult` **200**; `AbstractTool`
**235** with `execute` **797** popping `_permission_context` at **813** and
`_resolver` at **814**; `ConversationTurn` 11 / `ConversationHistory` 51 /
`ConversationMemory` 135 with `update_history` **167**; `A2AServer` 77 with
`_handle_send_message` **1092** and `_handle_stream_message` **1132**;
`DEFAULT_CATALOG_ID` = `"https://parrot.dev/catalogs/v1"` at
`catalog/base.py:52`; manager routes at `manager.py:1933-1934`.

**FINDING 1 — G3 needs a wire-model change (this was NOT anticipated).**
The official v1.0 `action` message carries **no `dataModel` field**.
`sendDataModel` is a boolean flag on `createSurface`
(`outputs/a2ui/models.py:467`, `alias="sendDataModel"`), documented as "if true,
the renderer sends the full data model back with every message". Checked
against the vendored `renderer_to_agent.json`:

- `properties.action` has **no** `additionalProperties` key ⇒ defaults to
  `true` ⇒ attaching a `dataModel` key to `action` **is schema-legal**.
- `properties.callAgentFunction` has **`additionalProperties: false`** ⇒
  attaching `dataModel` to `callAgentFunction` is **schema-ILLEGAL**.
- The envelope itself is `minProperties: 2, maxProperties: 2` with a `oneOf`
  over `action` / `callAgentFunction` / `rendererFunctionResponse` / `error` —
  so `dataModel` can never be a sibling key of the message at envelope level.

But the merged `ActionMessage` Pydantic model is
`model_config = ConfigDict(populate_by_name=True, extra="forbid")`
(`outputs/a2ui/models.py:585-608`) with no `data_model` field — so **a
`sendDataModel` payload is rejected today with a `ValidationError`**.
G3 therefore requires adding an explicit optional
`data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")`
to `ActionMessage` (preferred over relaxing to `extra="allow"`, which would
silently swallow renderer typos). This touches
`packages/ai-parrot/src/parrot/outputs/a2ui/models.py` — a file §6 assumed this
feature would only *consume*. It is TASK-2567, deliberately sequenced first and
kept surgical to minimise overlap with in-flight FEAT-473.

**FINDING 2 — docstring defect in merged FEAT-470 code.** In
`outputs/a2ui/models.py`, `AgentFunctionResponse` (**575**) and
`RendererFunctionResponse` (**627**) have their pairings **swapped** in prose:
`AgentFunctionResponse` says it answers a `callRendererFunction` and
`RendererFunctionResponse` says it answers a `callAgentFunction` — both
backwards. The class *placement* and wire directions are correct
(`AgentFunctionResponse` is in the A→R block and answers `callAgentFunction`;
`RendererFunctionResponse` is in the R→A block and answers
`callRendererFunction`). Docs-only, but it is precisely the pairing this
feature implements, so fix it in TASK-2567 before anyone reads it as truth.

**FINDING 3 — `PermissionContext` is never built by AgentTalk.** See the
resolved OQ in §8. Use `build_principal_context` (`parrot/auth/permission.py:166`,
returning at :199); model the call on `knowledge/ontology/tool_dispatcher.py:195-214`.
`UserSession` is at `auth/permission.py:21` (frozen/hashable: `user_id`,
`tenant_id`, `roles: frozenset`, `metadata`); `PermissionContext` at **81**
(`session`, `request_id`, `channel`, `trace_context`, `extra`).

**FINDING 4 — `_reject_action_components` already anticipates this feature.**
Its rejection message reads "interactive A2UI over A2A is FEAT-B"
(`a2a/models.py:356-359`). FEAT-469 *is* that follow-up; the `allow_actions`
flag added in Module 5 is what retires that error path.

**FINDING 5 — `export_catalog_definition` already emits `functions`.**
`catalog/export.py` builds `functions` from `list_functions()` plus the Basic
Catalog's official definitions copied verbatim (a bare `$ref` does not satisfy
`FunctionDefinition`'s inline `returnType` under `unevaluatedProperties: false`).
`export_functions()` must MERGE into that, not replace it. Catalog-side
`FunctionDefinition` lives at `catalog/base.py:246` with fields
`name`, `catalog_id`, `args_schema`, `return_type`, `allowed_callers`
(`Literal["rendererOnly","agentOnly","rendererOrAgent"]`, default
`"rendererOnly"`), `requires_user_activation`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.runtime`~~ (ni `A2UIRuntime`, `FunctionExecutor`, `SurfaceStateStore`, `PendingCallRegistry`, `A2UICallContext`) — todo nuevo en esta feature.
- ~~`parrot.outputs.a2ui.models.CallAgentFunction` / `AgentFunctionResponse` / `CallRendererFunction` / `RendererFunctionResponse` / `ErrorMessage` / `DeleteSurface`~~ — no existen aún; los crea `a2ui-v1-dialect`. Hoy existen `Action`, `ActionResponse` (no spec) y `CallFunction` (nombre 0.9.1) en `models.py:220-267`.
- ~~`parrot.outputs.a2ui.catalog.export`~~ — lo crea `a2ui-v1-dialect`; `export_functions`/`agent_capabilities` se añaden aquí.
- ~~`AbstractTool.a2ui_requires_user_activation`~~ / ~~`a2ui_exposed`~~ — no existen (se añade solo el primero).
- ~~`parrot.handlers.a2ui` / `A2UIHandler`~~ — no existe.
- ~~Ruta `/api/v1/agents/{agent_id}/a2ui`~~ — no existe; AgentTalk vive en `/api/v1/agents/chat/{agent_id}`.
- ~~`setup_deeplink_routes` montado en `manager.py`~~ — está **definido** (`handlers/deeplink.py:113`) pero **ningún módulo no-test lo llama** (`grep` en `packages/*/src`); la ruta web de deep link hoy no está expuesta por el manager.
- ~~`AgentCapabilities.a2ui` / `agent_capabilities` en el Agent Card~~ — no hay nada A2UI en `AgentCard`; la única declaración A2UI en a2a es el par de constantes en `a2a/models.py:338-339` y `Artifact.from_a2ui_envelope`.
- ~~`ConversationMemory.get_metadata()` / `set_metadata()`~~ — no hay API de metadata; se usa `ConversationHistory.metadata` + `update_history`.
- ~~`PermissionContext` construido dentro de `AgentTalk`~~ — `grep "PermissionContext("` en `handlers/agent.py` no da resultados; la construcción del contexto para el nuevo handler debe seguir el patrón de `bots/base.py:1805` (comentario) y `tools/abstract.py:797` (kwargs), **verificar en implementación** dónde se instancia hoy (`(unverified — check before use)`).
- ~~Runtime JS de `callRendererFunction` en `interactive_html.py`~~ — no existe; fuera de alcance.
- ~~`A2UI_EXTENSION_URI == "https://a2ui.org/a2a-extension/a2ui/v1.0"`~~ — hoy vale `…/extensions/a2a/display/v1`; el cambio es de `a2ui-v1-dialect`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **G8 one-way import rule**: `parrot/outputs/a2ui/runtime/` usa `Protocol`s e inyección; los adaptadores importan `parrot.tools`/`parrot.memory` de forma lazy. Extender `tests/outputs/a2ui/adapters/test_import_rule.py`.
- **Kwargs reservados** para pasar contexto a tools (`_permission_context`, `_resolver` → añadir `_a2ui_surface_state`), `tools/abstract.py:797`.
- **Sobre por clave y `version:"v1.0"`** siempre vía `serialization.serialize` (G3); el runtime nunca escribe `version` a mano.
- **Errores sin fuga**: `error.message` es un texto seguro; el traceback va al logger (`self.logger.exception`).
- **Ids de correlación**: `functionCallId` generado con `secrets.token_urlsafe(16)` (mismo criterio que deep links, `deeplink.py`).
- **Transporte fino** (como `DeepLinkResumeHandler`): auth → contexto → `dispatch` → respuesta; ninguna lógica de protocolo en handlers.
- **Streaming**: SSE con un evento por sobre A→R; el separador `b'\n\x00'` de AgentTalk **no** se reutiliza (es un formato propio de chunked-aimessage).
- Pydantic v2 + docstrings Google + `self.logger` en todo.

### Known Risks / Gotchas
- **Superficie de ataque**: exponer todas las tools del `ToolManager` (decisión §8) hace del `PermissionContext` la única barrera. Mitigación: el handler rechaza peticiones sin usuario autenticado (401), `execute_tool` recibe siempre el contexto, y se registra un log de auditoría por invocación (`agent_id`, `user_id`, `call`, `status`). Tools marcadas `return_direct`/destructivas deben documentarse; se recomienda (open question) un atributo `a2ui_hidden=True` para excluir tools puntuales sin volver al modelo opt-in.
- **Nombres de tools no UAX #31** (p. ej. con `-` o `.`): se sanean para el catálogo y se mantiene un mapa inverso; colisiones tras sanear → error al exportar.
- **`functionCallId` pendientes en HTTP request-response**: el renderer puede no volver nunca; TTL 900 s y limpieza perezosa en cada `dispatch`.
- **`sendDataModel` grande**: `dataModel` de tablas puede pesar MBs; límite configurable (`A2UI_MAX_DATA_MODEL_BYTES`, default 1 MiB) → `error{code:"INTERNAL", message:"data model too large"}`, se conserva el estado anterior.
- **Concurrencia en memoria**: `ConversationHistory.metadata` se actualiza con read-modify-write; con Redis usar la operación atómica que ofrezca `RedisConversation` o un lock por `session_id` (verificar en implementación).
- **Deep link no montado hoy**: al montarlo, cualquier despliegue que ya expusiera la ruta por otro medio podría duplicarla — comprobar en `manager.py` antes de registrar.
- **A2A `Artifact.from_a2ui_envelope`** hoy rechaza componentes con acciones; relajarlo solo cuando el Agent Card declare la extensión A2UI (si no, el cliente no sabrá manejarlas).
- **Dependencia dura de `a2ui-v1-dialect`**: si su spec cambia la forma de `catalog/export.py` o de los modelos R→A, este spec debe revisarse antes de `/sdd-task`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | ya en core | handler HTTP + SSE |
| `redis` (via `RedisConversation`) | ya en core | persistencia de estado de superficie y pendientes |
| `jsonschema` | `>=4.20` (opcional, extra de `a2ui-v1-dialect`) | validación de sobres en tests |
| Schemas v1.0 vendorizados (`agent_to_renderer.json`, `renderer_to_agent.json`, `agent_capabilities.json`, `catalog_definition.json`) | pin por SHA (de `a2ui-v1-dialect`) | tests de conformidad |

---

## 8. Open Questions

- [x] ¿Qué tools son invocables como funciones A2UI? — *Resolved in clarification*: **todas las tools del `ToolManager`** (sin opt-in).
- [x] ¿Transporte HTTP de los sobres R→A? — *Resolved in clarification*: **endpoint dedicado** `/api/v1/agents/{agent_id}/a2ui` (POST + stream), no el POST de AgentTalk.
- [x] ¿Autorización de funciones? — *Resolved in clarification*: **`PermissionContext` del usuario de la sesión** vía `execute_tool(permission_context=...)`; `requiresUserActivation` se verifica solo en el renderer.
- [x] ¿Qué hacer con `sendDataModel`? — *Resolved in clarification*: **persistir el último `dataModel` por `surfaceId` en memoria de conversación** y exponerlo al agente/tools (`a2ui_surface_state`).
- [x] Alcance de acciones en `a2ui-v1-dialect` — *Resolved in brainstorm a2ui-v1-dialect*: modelos + `Form` como composición + deep links; el runtime RPC es esta feature.
- [x] ¿Añadir `AbstractTool.a2ui_hidden: bool = False` para excluir tools puntuales del catálogo sin volver al modelo opt-in? — *Resolved 2026-08-29 (Jesus Lara)*: **sí**. Se añaden DOS atributos de clase opcionales en `AbstractTool`: `a2ui_requires_user_activation: bool = False` y `a2ui_hidden: bool = False`. `export_functions()` omite toda tool con `a2ui_hidden=True`. Sigue siendo un modelo opt-OUT (todas las tools se exportan salvo las marcadas), no opt-in.
- [x] ¿Dónde se instancia hoy el `PermissionContext` para las llamadas de AgentTalk (no aparece en `handlers/agent.py`)? — *Resolved 2026-08-29 (verificado en `dev`)*: **AgentTalk NO construye ninguno**. `grep -rn "PermissionContext(" packages/*/src` sólo da: `auth/permission.py:199` (dentro del factory `build_principal_context`, `permission.py:166`), `cli/identity.py:105`, `knowledge/ontology/tool_dispatcher.py:214`, y los tres wrappers de integrations (msagentsdk `agent.py:375`, `resume.py:298`, telegram `wrapper.py:1271`). El camino HTTP de AgentTalk pasa `permission_context=None` de facto. **Decisión**: `A2UIHandler` construye el suyo con `build_principal_context(principal=user_id, channel="a2ui", tenant_id=None, roles=None)` (`parrot/auth/permission.py:166`), siguiendo el patrón de `tool_dispatcher.py:195-214`. Nota de seguridad registrada en §7: `build_principal_context` deja `roles=frozenset()` por defecto, así que las políticas PBAC role-gated **deniegan por defecto** — es el comportamiento seguro para esta feature.
- [x] ¿Se emite `agent_capabilities` también en el endpoint HTTP o solo en el Agent Card A2A? — *Resolved 2026-08-29 (Jesus Lara)*: **ambos**. Además del Agent Card, `GET /api/v1/agents/{agent_id}/a2ui/capabilities` devuelve `agent_capabilities()` para que un renderer no-A2A descubra `supportedCatalogIds` sin pedir el Agent Card. Va en el Módulo 6.
- [x] Límite `A2UI_MAX_DATA_MODEL_BYTES` y TTL del estado de superficie. — *Resolved 2026-08-29 (default aceptado)*: límite **1 MiB** (`A2UI_MAX_DATA_MODEL_BYTES`, configurable por env). El estado de superficie **NO tiene TTL propio**: vive en `ConversationHistory.metadata["a2ui_surfaces"]` y por tanto hereda el ciclo de vida de la sesión. Sólo las llamadas pendientes (`a2ui_pending_calls`) tienen TTL (900 s), porque son correlaciones efímeras.
- [x] `callRendererFunction` en A2A: ¿sólo `message/stream` o también encolado? — *Resolved 2026-08-29 (Jesus Lara)*: **ambos**. Se emite en el SSE de `message/stream` y además se encola en `PendingCallRegistry` para adjuntarse a la respuesta del siguiente `message/send`, igual que el comportamiento request-response de HTTP descrito en §2.
- [x] ¿El turno estructurado de `action` es turno de usuario visible o de sistema? — *Resolved 2026-08-29 (default aceptado)*: **turno de usuario visible cuando `action.userMessage` está presente** (ese texto es exactamente lo que el protocolo define como "human-readable string describing the action performed by the user"); **turno de sistema** cuando no lo está (un `action` sin `userMessage` es telemetría de UI, no habla del usuario). El `dataModel`/`context` nunca va en el texto visible — viaja por `a2ui_surface_state`.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (un worktree `feat-469-a2ui-agent-functions`, tareas secuenciales).
- **Rationale**: los módulos 1–4 (core runtime) son estrictamente secuenciales; 5 (A2A), 6 (HTTP) y 7 (deep links) tocan paquetes distintos pero todos dependen de 2–4 y comparten el `A2UICallContext`; el volumen no justifica worktrees hijos.
- **Parallelizable tasks** (si se quisiera `mixed`): Módulo 5 (A2A) y Módulo 6 (HTTP) pueden desarrollarse en paralelo una vez mergeados 1–4, en worktrees hijos ramificados desde la feature.
- **Cross-feature dependencies**: **`a2ui-v1-dialect` debe estar mergeado en `dev` primero** (al menos su bloque de wire: modelos R→A/A→R, `serialization`, `catalog/export.py`). Comparte archivos con esa feature: `parrot/a2a/models.py`, `outputs/a2ui/deeplink.py`, `handlers/deeplink.py`, `integrations/a2ui_resume.py` — no arrancar esta feature mientras la otra tenga esos archivos abiertos.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-28 | Jesus Lara / Claude | Initial draft (follow-up de a2ui-v1-dialect, FEAT-469) |
| 1.0 | 2026-08-29 | Jesus Lara / Claude | Resueltas las 6 Open Questions pendientes (§8); status → `approved`. Refresco del Codebase Contract sobre `dev` @ `dd06d939c` tras el merge de FEAT-470 (PR #1263): tabla de line numbers corregidos + 5 findings. Hallazgos que cambian el alcance: G3 requiere añadir `dataModel` a `ActionMessage` (hoy `extra="forbid"` ⇒ rechaza `sendDataModel`); el Módulo 7 se reduce porque FEAT-470 ya migró `ResumePayload`/`build_structured_message` a v1.0 `a2ui_action`. ACs nuevas: AC-OQ1..5, AC-F1. |
