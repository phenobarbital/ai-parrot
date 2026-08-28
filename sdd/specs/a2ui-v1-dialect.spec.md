---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI v1.0 Dialect — wire estándar, catálogo básico completo, catálogo de presentación propio

**Feature ID**: FEAT-470
**Date**: 2026-08-28
**Author**: Jesus Lara (con Claude)
**Status**: draft
**Target version**: 0.29.0
**Brainstorm**: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B)
**Followed by**: FEAT-469 `a2ui-agent-functions` (runtime RPC; depende de este spec)

---

## 1. Motivation & Business Requirements

### Problem Statement

La implementación A2UI de ai-parrot (FEAT-273 y derivados FEAT-301/324/326/420/430)
declara apuntar a A2UI v1.0 (`A2UI_VERSION = "1.0"`) pero el wire real es un
**dialecto propio** que ningún renderer A2UI externo puede consumir. Contrastado
contra los schemas oficiales (`google/A2UI` `specification/v1_0/json/*.json`,
`catalogs/basic/catalog.json`, extensión A2A; commit `90157ec1`), los
incumplimientos son:

1. **Sobre**: emitimos `{"messageType":"createSurface", …, "version":"1.0"}`; la
   spec exige `{"version":"v1.0","createSurface":{…}}` (exactamente una clave).
2. **Componente**: props anidadas en `properties:{}`; la spec las pone al nivel
   superior con `child` / `children` (lista o template `{componentId, path}`),
   `catalogId`, `weight`, `accessibility`, `checks`, `action`, `metadata.extensions`.
3. **Binding**: `{"$bind": "/ptr"}` (+ `optional`) vs `{"path": "/ptr"}` / `{"call","args"}`.
4. **Mensajes**: `updateDataModel` con `contents:{}` en vez de `{path?, value}`;
   faltan `deleteSurface`, `callRendererFunction`, `agentFunctionResponse`,
   `callAgentFunction`, `rendererFunctionResponse`, `error`; `callFunction`
   conserva el nombre 0.9.1; `actionResponse` no existe en la spec.
5. **Raíz**: no existe el componente `id:"root"` ni el contenedor reservado `Surface`.
6. **Catálogo básico**: `lower()` produce 5/18 primitivas (Column, Row, Card, Text,
   Image) con desvíos (`Text.role` vs `variant`, `Card.children` vs `child`);
   0/14 funciones renderer-side; sin `ValidationResult` ni `UNALLOWED_*`.
7. **A2A**: URI `…/extensions/a2a/display/v1` y mime `application/vnd.a2ui.envelope+json`
   vs `https://a2ui.org/a2a-extension/a2ui/v1.0` y `application/a2ui+json`.

A la vez, ai-parrot construyó sobre A2UI una capa de **rendering de presentación**
que la spec (pensada para UI viva) no cubre y que debe preservarse: catálogo de
presentación (Chart, DataTable, Map, KPICard, Timeline, Infographic, Report),
bake de bindings para renderers estáticos (SSR-HTML, PDF, Adaptive Cards, ECharts,
Folium, interactive-HTML), delivery multicanal, deep links de acción, productor LLM
con validate-retry-degrade, recetas (`LayoutSpec`) y el adaptador Infographic.

### Goals

- G1. **Wire 100% v1.0**: todo mensaje emitido valida contra `agent_to_renderer.json`;
  todo mensaje aceptado valida contra `renderer_to_agent.json`; `version` const `"v1.0"`.
- G2. **Dos catálogos mezclables**: `basic` oficial
  (`https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json`) y `parrot`
  (`https://parrot.dev/catalogs/v1`, se mantiene). La superficie usa `catalogId=parrot`
  por defecto; el catálogo parrot **incluye por `$ref`** los 18 componentes y 14
  funciones del básico para que la resolución estricta v1.0 encuentre `Text`,
  `Button`, etc. sin `catalogId` explícito.
- G3. **Catálogo básico completo en core** (`parrot/outputs/a2ui/catalog/basic/`):
  18 primitivas + 14 funciones modeladas y validadas; renderers propios declaran
  qué primitivas soportan y degradan las demás (render por niveles).
- G4. **Semántica de presentación fuera del schema**: `Text.role`, hints de
  renderer, bindings opcionales → `metadata.extensions.parrot_*`.
- G5. **Compatibilidad solo de lectura + migración**: `deserialize` acepta el
  dialecto actual y lo normaliza; emisión siempre v1.0; `migrate_layout()` para
  recetas persistidas (`SUPPORTED_SCHEMA_VERSION` 1→2). Sin flag de emisión dual.
- G6. **Acciones**: todos los mensajes modelados; `Form` pasa a composición de
  primitivas + `Button.action.event` + `checks`; deep links transportan un
  `action` v1.0; Adaptive Cards renderiza **inputs nativos** (`Input.Text`,
  `Input.Toggle`, `Input.ChoiceSet`, `Input.Number`, `Input.Date/Time`) con
  `Action.Submit` cuyo `data` es el `action` v1.0 + `surfaceId`, recibido por el
  wrapper de Teams ya existente. El runtime `callAgentFunction` es FEAT-469.
- G7. **Invariantes vigentes**: G8 (a2ui core no importa `parrot.bots`/`parrot.clients`),
  G3 (`version` solo en `serialization.py`), G4 (`lower()` obligatorio), G1/D10b
  (allowlist + gate de acciones por origen LLM/TOOL), `test_no_exec.py`.
- G8. **Validación de catálogo con `jsonschema`** como dependencia dura de core;
  schemas oficiales **vendorizados** con pin por SHA y test de drift.
- G9. Renombrar `Card` propio → **`InfoCard`** con alias de lectura en compat.
- G10. A2A: URI `https://a2ui.org/a2a-extension/a2ui/v1.0`, `DataPart.data.metadata["mimeType"]
  = "application/a2ui+json"`. (`agent_capabilities` en el Agent Card → FEAT-469.)

### Non-Goals (explicitly out of scope)

- Runtime RPC (`callAgentFunction` → tools, `agentFunctionResponse`, correlación de
  `callRendererFunction`, `sendDataModel` persistido, `agent_capabilities` en Agent
  Card, endpoint HTTP A2UI): **FEAT-469**.
- Runtime JS de funciones/`checks`/dos-vías en `interactive-html`; el JS vanilla
  existente solo se amplía para renderizar las primitivas nuevas. Adoptar el renderer
  web oficial (`@a2ui/lit`) queda como feature posterior (open question).
- Flag de emisión dual viejo/v1.0 (rechazado en brainstorm, Round 1).
- Capa de traducción sobre los modelos actuales (rechazado: brainstorm Option A).
- Modelos generados por codegen desde JSON Schema (rechazado: brainstorm Option C;
  se toma de ella solo el vendorizado + validación jsonschema).
- `inlineCatalogs` del renderer.
- Multi-idioma en el envelope (sigue single-language como hoy, `_text()` prefiere `"en"`).

---

## 2. Architectural Design

### Overview

Se reescribe `parrot/outputs/a2ui/models.py` para que las clases Pydantic **sean**
el wire v1.0 (una sola verdad), se añade el catálogo básico completo en core y se
reancla la capa de presentación a los mecanismos de extensión oficiales:

- **Sobre por clave**: `A2UIAgentMessage` = `{version:"v1.0"} ∪ exactamente-una-de
  {createSurface, updateComponents, updateDataModel, deleteSurface,
  callRendererFunction, agentFunctionResponse}`; `A2UIRendererMessage` =
  `{version:"v1.0"} ∪ una-de {action, callAgentFunction, rendererFunctionResponse,
  error}`. `serialize` produce `{"version":"v1.0","<msg>":{…}}`; `deserialize`
  detecta la clave (v1.0) o `messageType` (legado → `compat.normalize_legacy`).
- **`Component` v1.0**: `id`, `component`, `catalogId?`, `child?`, `children?`
  (lista | template), `weight?`, `accessibility?`, `checks?`, `action?`,
  `metadata.extensions?`; las props del catálogo van al nivel superior
  (`extra="allow"`) y se validan contra el JSON Schema del catálogo resuelto.
- **Tipos comunes**: `DataBinding{path}`, `FunctionCall{call,args,catalogId?}`,
  `DynamicString/Number/Boolean/StringList`, `Action{event|functionCall}`,
  `CheckRule`, `ValidationResult`, `AccessibilityAttributes`, `Extensions`.
- **`catalog/basic/`**: 18 modelos de primitivas (enums exactos, mixin `Checkable`),
  `functions.py` con evaluador puro de las 14 funciones (`formatString` con
  `${/path}`, `${fn(arg:'v')}`, escape `\${`; `@index`; validadores →
  `ValidationResult`; `and/or/not`; `openUrl` marcado `requiresUserActivation`),
  y `spec/` con los JSON oficiales vendorizados + `SPEC_COMMIT`.
- **`catalog/parrot/`** (antes `catalog/components/`): `InfoCard`, `Chart`,
  `DataTable`, `Map`, `KPICard`, `Timeline`, `Infographic`, `Report`; `lower()`
  emite primitivas básicas v1.0 (`Text{variant}` + `metadata.extensions.parrot_role`,
  `Card{child}`, `Tabs`, `Divider`, `List`, `Image{fit}`); `DataTable` usa template
  `children` + `@index`. `Form` deja de ser componente registrado y pasa a
  `build_form()` (helper de composición).
- **`catalog/export.py`**: genera el `catalog_definition.json` de parrot
  (`protocolVersion:"1.0"`, `$ref` a los componentes/funciones del básico,
  `instructions` concatenadas, `allowedParents/allowedChildren`).
  `validate_envelope` resuelve `catalogId` (componente → superficie → error),
  valida con `jsonschema`, comprueba `root`, ids únicos, referencias a hijos,
  `allowedParents/Children` (`UNALLOWED_PARENT/CHILD`), y el gate de origen
  (LLM no puede emitir `action` ni `callAgentFunction`).
- **Bake**: resuelve `path`, evalúa `call`, expande template `children` con `@index`;
  opcionales en `metadata.extensions.parrot_optional: ["/ptr", …]`; post-condición:
  ningún `path`/`call` vivo.
- **Renderers**: `RendererCapabilities` gana `supported_catalog_ids` y
  `supported_components`; cada renderer del satélite mapea sus primitivas y
  degrada el resto con política explícita, registrada en
  `RenderedArtifact.metadata["degraded"]`.
- **Transporte**: handlers y A2A envían el sobre v1.0 tal cual; `deeplink.ResumePayload`
  envuelve un `action` v1.0; Adaptive Cards `Action.Submit.data = {"a2ui_action":
  <action v1.0>, "surfaceId": …}` y el wrapper de Teams lo enruta como turno
  estructurado (mismo camino que el resume de deep link).
- **Recetas**: `LayoutSpec` v2 = componente v1.0; `migrate_layout()`;
  `SUPPORTED_SCHEMA_VERSION = 2` con lectura de v1.

Comportamiento visible: un agente en `OutputMode.A2UI` devuelve en `a2ui_envelope`
un sobre v1.0 (o lista JSONL cuando hay varios); cualquier renderer A2UI v1.0 lo
consume; los propios entienden además el catálogo parrot. Los builders públicos
(`build_surface/build_chart/…`) y el toolkit Infographic mantienen su API.

### Component Diagram
```
LLM / tools / Infographic toolkit / recipes
        │ (builders, adapters, producer)
        ▼
models.py (wire v1.0) ──► catalog/validate_envelope ──► jsonschema ◄── catalog/basic/spec/*.json (vendorizado, SHA)
        │                        │  resolve catalogId → basic | parrot
        │                        │  allowedParents/Children · root · gate LLM/TOOL
        │                        ▼
        │              catalog/parrot/*.lower() ──► BasicNode (primitivas v1.0 + extensions.parrot_*)
        │                        │
        ▼                        ▼
serialization.py ─► {"version":"v1.0", msg:{…}}    baking.py (path · call · @index · template children)
        │   ▲                                            │
        │   └── compat.normalize_legacy (messageType/$bind/properties/Card)   ▼
        │                                     a2ui_renderers/* (satellite): ssr_html · pdf · adaptive_cards
        ▼                                                 echarts · folium_map · interactive-html
handlers/agent.py · a2a/models.py (a2ui+json) · deeplink · recipes(LayoutSpec v2, migrate_layout)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/models.py` | modifies (breaking interno) | sobre por clave, `Component` v1.0, `DataBinding{path}`, set completo de mensajes |
| `parrot/outputs/a2ui/serialization.py` | modifies | `A2UI_VERSION="v1.0"`, `deserialize` compat, JSONL de sobres |
| `parrot/outputs/a2ui/catalog/{base,__init__}.py` | extends | resolución `catalogId`, jsonschema, `allowed*`, códigos v1.0, `root` |
| `parrot/outputs/a2ui/catalog/basic/` (nuevo) | new | 18 primitivas, 14 funciones, spec vendorizada |
| `parrot/outputs/a2ui/catalog/components/*.py` → `catalog/parrot/` | modifies | `lower()` v1.0; `Card`→`InfoCard`; `Form` retirado → `build_form()` |
| `parrot/outputs/a2ui/{builders,baking,producer,deeplink,emission}.py` | modifies | forma v1.0; `call`/template en bake; `action` en resume |
| `parrot/outputs/a2ui/adapters/infographic.py` | modifies | remapeo a `Tabs/Divider/List/CheckBox/Image.fit` |
| `parrot/outputs/a2ui/recipes/{models,store,__init__}.py` | modifies | `LayoutSpec` v2, `SUPPORTED_SCHEMA_VERSION=2`, `migrate_layout` |
| `parrot/outputs/a2ui/renderers/__init__.py`, `artifacts.py` | extends | `RendererCapabilities.supported_catalog_ids/supported_components`; `RenderedArtifact.metadata` (nuevo campo) |
| `ai-parrot-visualizations/.../a2ui_renderers/*.py` | modifies | 18 primitivas + degradación; AC inputs nativos + `Action.Submit` |
| `parrot/a2a/models.py:335-433` | modifies | URI/mime v1.0; `from_a2ui_envelope` lee la clave de sobre |
| `ai-parrot-server/.../handlers/{agent,deeplink}.py` | modifies (menor) | sobre v1.0 en `a2ui_envelope`; resume con `action` |
| `ai-parrot-integrations/.../a2ui_resume.py`, `msteams/wrapper.py`, `telegram/wrapper.py` | modifies (menor) | payload `action` v1.0; Teams enruta `activity.value["a2ui_action"]` |
| `parrot/tools/{infographic,interactive}_toolkit.py`, `tools/infographic_recipes/*` | modifies (menor) | usan builders; sin cambio de API pública |
| `parrot/outputs/formats/__init__.py` | modifies (menor) | `_A2UI_REPLACEMENTS` sigue igual; texto de deprecación menciona `InfoCard` |
| `ai-parrot/pyproject.toml`, `ai-parrot-visualizations/pyproject.toml` | extends | `jsonschema>=4.20` en core; `jsonpointer` sigue en extra `a2ui` |
| Tests (~470 funciones A2UI) | modifies | fixtures al wire v1.0 + tests de conformidad contra schemas vendorizados |
| `docs/migration/feat-273-a2ui-deprecations.md`, `docs/outputs/*` | extends | guía dialecto → v1.0 |

Breaking: sí para consumidores del `a2ui_envelope` que leían `messageType`/`properties`
(mitigado por la guía y el deserializador compat de entrada). Sin cambio en la API
pública de tools/agents (`OutputMode.A2UI`, builders).

### Data Models
```python
# parrot/outputs/a2ui/models.py (v1.0 — Pydantic v2, alias camelCase, populate_by_name=True)

A2UI_VERSION_CONST = "v1.0"           # usado solo por serialization (G3)

class DataBinding(BaseModel):  path: str                      # JSON Pointer RFC 6901; extra="forbid"
class FunctionCall(BaseModel): call: str; args: dict[str, Any] = {}; catalog_id: Optional[str]  # alias catalogId
DynamicString  = Union[str, DataBinding, FunctionCall]
DynamicNumber  = Union[float, int, DataBinding, FunctionCall]
DynamicBoolean = Union[bool, DataBinding, FunctionCall]
DynamicStringList = Union[list[str], DataBinding, FunctionCall]

class ChildTemplate(BaseModel): component_id: str; path: str  # alias componentId; extra="forbid"
ChildList = Union[list[str], ChildTemplate]

class EventAction(BaseModel):  name: str; user_message: Optional[DynamicString]; context: dict[str, Any] = {}
class Action(BaseModel):       event: Optional[EventAction]; function_call: Optional[FunctionCall]   # exactamente uno
class CheckRule(BaseModel):    condition: Union[FunctionCall, DataBinding]; message: Optional[DynamicString]
class ValidationResult(BaseModel): valid: bool; code: Optional[str]; message: Optional[str]; severity: Literal["error","warning","info"] = "error"
class AccessibilityAttributes(BaseModel): label, description: Optional[DynamicString]; live: Literal["off","polite","assertive"] = "off"; hidden: bool = False
class Extensions(RootModel[dict[str, Any]]) # claves UAX #31; `a2ui_` reservado; parrot usa `parrot_*`
class ComponentMetadata(BaseModel): extensions: Optional[Extensions]

class Component(BaseModel):                       # extra="allow" (props del catálogo top-level)
    id: str; component: str
    catalog_id: Optional[str]                     # alias catalogId
    child: Optional[str]; children: Optional[ChildList]
    weight: Optional[float]
    accessibility: Optional[AccessibilityAttributes]
    checks: Optional[list[CheckRule]]
    action: Optional[Action]
    metadata: Optional[ComponentMetadata]

class CreateSurface(BaseModel):   surface_id: str; catalog_id: Optional[str]; send_data_model: bool = False; components: list[Component] = []; data_model: dict = {}; metadata: Optional[SurfaceMetadata]
class UpdateComponents(BaseModel): surface_id: str; components: list[Component]
class UpdateDataModel(BaseModel):  surface_id: str; path: Optional[str]; value: Any   # value REQUERIDO (puede ser null → borrar)
class DeleteSurface(BaseModel):    surface_id: str
class CallRendererFunction(BaseModel): function_call_id: str; call_function: FunctionCall
class AgentFunctionResponse(BaseModel): function_call_id: str; value: Optional[Any]; error: Optional[ErrorPayload]
class ActionMessage(BaseModel):    name: str; context: dict[str, Any] = {}; surface_id: Optional[str]; data_model: Optional[dict]  # forma exacta de renderer_to_agent.json (verificar campos al vendorizar)
class CallAgentFunction(BaseModel): function_call_id: str; call_function: FunctionCall
class RendererFunctionResponse(BaseModel): function_call_id: str; value: Any
class ErrorMessage(BaseModel):     code: str; message: str; function_call_id: Optional[str]

class A2UIAgentMessage(BaseModel):     # sobre A→R: version + exactamente una clave (validator)
    version: Literal["v1.0"]; create_surface | update_components | update_data_model | delete_surface | call_renderer_function | agent_function_response
class A2UIRendererMessage(BaseModel):  # sobre R→A
    version: Literal["v1.0"]; action | call_agent_function | renderer_function_response | error

# parrot/outputs/a2ui/catalog/base.py (ampliado)
class ComponentDefinition(BaseModel):
    name: str; catalog_id: str = DEFAULT_CATALOG_ID; schema_: dict; instructions: str = ""
    requires_actions: bool = False
    allowed_parents: Optional[list[str]] = None; allowed_children: Optional[list[str]] = None   # nuevo
class FunctionDefinition(BaseModel):
    name: str; catalog_id: str; args_schema: dict; return_type: str
    allowed_callers: Literal["rendererOnly","agentOnly","rendererOrAgent"] = "rendererOnly"
    requires_user_activation: bool = False
class BasicNode(BaseModel):    # lowered tree — props top-level como Component (ya no `properties`)
    id: Optional[str]; component: str; child: Optional["BasicNode"]; children: Optional[Union[list["BasicNode"], ChildTemplate]]
    metadata: Optional[ComponentMetadata]      # extensions.parrot_role, parrot_component_id
    model_config = ConfigDict(extra="allow")

# parrot/outputs/a2ui/renderers/__init__.py (ampliado)
class RendererCapabilities(BaseModel):
    interactive: bool; supports_actions: bool; supports_updates: bool; output: str
    supported_catalog_ids: list[str] = [BASIC_CATALOG_ID, DEFAULT_CATALOG_ID]   # nuevo
    supported_components: set[str]                                              # nuevo; degradación para el resto

# parrot/outputs/a2ui/recipes/models.py
class LayoutSpec(BaseModel):   # v2
    component: str
    # props top-level (extra="allow"), children/child, DataBinding {"path"}
SUPPORTED_SCHEMA_VERSION = 2   # lectura de 1 vía migrate_layout
```

### New Public Interfaces
```python
# parrot/outputs/a2ui/compat.py
def is_legacy_envelope(data: dict) -> bool
def normalize_legacy(data: dict) -> dict            # messageType/properties/$bind/Card/contents → v1.0; DeprecationWarning
def normalize_legacy_component(comp: dict) -> dict

# parrot/outputs/a2ui/catalog/basic/__init__.py
BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
SPEC_COMMIT = "90157ec10f36cf8e192daa71c95d2684af20c756"   # pin upstream
def basic_components() -> list[ComponentDefinition]; def basic_functions() -> list[FunctionDefinition]
def load_spec(name: Literal["catalog","common_types","agent_to_renderer","renderer_to_agent","catalog_definition","agent_capabilities"]) -> dict

# parrot/outputs/a2ui/catalog/basic/functions.py
class FunctionEvaluator:
    def evaluate(self, call: FunctionCall, *, data_model: dict, scope_path: str = "", index: Optional[int] = None) -> Any
    def format_string(self, template: str, *, data_model: dict, scope_path: str = "", index: Optional[int] = None) -> str
    def check(self, rule: CheckRule, **ctx) -> ValidationResult

# parrot/outputs/a2ui/catalog/__init__.py (ampliado)
def resolve_catalog(component_catalog_id: Optional[str], surface_catalog_id: Optional[str]) -> str   # raises CatalogValidationError(code="CATALOG_UNRESOLVED")
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL, surface_catalog_id: Optional[str] = None) -> None
def validate_message(message: A2UIAgentMessage | A2UIRendererMessage) -> None   # jsonschema contra agent_to_renderer/renderer_to_agent

# parrot/outputs/a2ui/catalog/export.py
def export_catalog_definition(*, catalog_id: str = DEFAULT_CATALOG_ID, include_basic: bool = True) -> dict
def write_catalog_definition(path: Path) -> None

# parrot/outputs/a2ui/catalog/parrot/form.py (reemplaza el componente Form)
def build_form(*, id_prefix: str, title: Optional[str], fields: list[FormField], submit: FormSubmit) -> list[Component]   # primitivas + Button.action.event + checks

# parrot/outputs/a2ui/builders.py (firmas conservadas; salida v1.0)
def build_surface(...) -> CreateSurface   # garantiza componente id="root"

# parrot/outputs/a2ui/baking.py
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]   # ahora también evalúa `call` y expande ChildTemplate

# parrot/outputs/a2ui/recipes/migrate.py
def migrate_layout(layout: dict, *, from_version: int) -> dict
async def migrate_store(store: AbstractRecipeStore, *, dry_run: bool = False) -> MigrationReport
```

---

## 3. Module Breakdown

### Module 1: Wire v1.0 — models + serialization + compat
- **Path**: `parrot/outputs/a2ui/models.py`, `serialization.py`, `compat.py` (nuevo)
- **Responsibility**: sobre por clave, `Component` v1.0, tipos comunes, set completo de mensajes A→R/R→A; `serialize/deserialize/to_jsonl/iter_jsonl`; `normalize_legacy` (incluye `Card`→`InfoCard`, `updateDataModel.contents` → N mensajes `{path,value}`); `A2UI_VERSION = "v1.0"`.
- **Depends on**: —. **Bloque secuencial #1** (todo lo demás depende de él).

### Module 2: Spec vendorizada + validación jsonschema
- **Path**: `parrot/outputs/a2ui/catalog/basic/spec/*.json`, `catalog/basic/__init__.py` (`load_spec`, `SPEC_COMMIT`), `catalog/__init__.py` (`validate_message`, `resolve_catalog`, `validate_envelope` ampliado), `catalog/base.py` (`FunctionDefinition`, `allowed_*`, códigos), `ai-parrot/pyproject.toml` (`jsonschema>=4.20`)
- **Responsibility**: copiar `catalog.json`, `common_types.json`, `agent_to_renderer.json`, `renderer_to_agent.json`, `catalog_definition.json`, `agent_capabilities.json` de `google/A2UI@90157ec1`; resolver `$ref` locales (registry de `jsonschema` con `referencing`); test de drift marcado `network`; resolución estricta de catálogo; `root`, ids únicos, hijos existentes, `UNALLOWED_PARENT/CHILD`, `INVALID_FUNCTION_CALL`, gate LLM/TOOL.
- **Depends on**: Module 1.

### Module 3: Catálogo básico — 18 primitivas
- **Path**: `parrot/outputs/a2ui/catalog/basic/components.py` (o un módulo por familia: `layout.py`, `media.py`, `inputs.py`)
- **Responsibility**: modelos `Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Divider, Modal, Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput` con enums exactos, `Checkable` mixin, `INSTRUCTIONS` por primitiva; registro en el catálogo `basic` (sin `lower()`: son el nivel base — el registro admite `is_primitive=True`).
- **Depends on**: Module 2. **Paralelizable** con 4 y 5.

### Module 4: Funciones renderer-side + bake v1.0
- **Path**: `parrot/outputs/a2ui/catalog/basic/functions.py`, `baking.py`
- **Responsibility**: `FunctionEvaluator` (14 funciones, `@index`, `formatString` con escape, `ValidationResult`); `bake_envelope` resuelve `path` (absoluto/relativo con scope), evalúa `call`, expande `ChildTemplate` con `@index`, respeta `metadata.extensions.parrot_optional`, y verifica post-condición.
- **Depends on**: Module 2. **Paralelizable** con 3 y 5.

### Module 5: Catálogo parrot — lowering v1.0, InfoCard, build_form, export
- **Path**: `parrot/outputs/a2ui/catalog/parrot/` (mover desde `catalog/components/`), `catalog/export.py`, `builders.py`
- **Responsibility**: `InfoCard, Chart, DataTable, Map, KPICard, Timeline, Infographic, Report` con `lower()` a primitivas v1.0 (`Text.variant` + `extensions.parrot_role`, `Card{child}`, `Tabs`, `Divider`, `List`, `Image.fit`; `DataTable` → `ChildTemplate` + `@index`); `allowed_parents/children`; `build_form()`; `export_catalog_definition()` con `$ref` al básico e `instructions`; builders emiten `root`.
- **Depends on**: Modules 3, 4.

### Module 6: Adaptador Infographic + recetas
- **Path**: `parrot/outputs/a2ui/adapters/infographic.py`, `recipes/{models,store,__init__}.py`, `recipes/migrate.py` (nuevo), `tools/infographic_recipes/{runner,freeze}.py`
- **Responsibility**: remapeo de los 19 `BlockType` (`tab_view/accordion→Tabs`, `divider→Divider`, `bullet_list/steps→List`, `checklist→CheckBox`, `image→Image.fit`, resto como hoy); `LayoutSpec` v2; `SUPPORTED_SCHEMA_VERSION=2`; `migrate_layout`/`migrate_store`; freeze produce v2.
- **Depends on**: Module 5.

### Module 7: Renderers del satélite — primitivas + degradación
- **Path**: `ai-parrot-visualizations/.../a2ui_renderers/{ssr_html,interactive_html,pdf,adaptive_cards,echarts,folium_map}.py`, `parrot/outputs/a2ui/renderers/__init__.py`
- **Responsibility**: `RendererCapabilities.supported_catalog_ids/supported_components`; cada renderer cubre las 18 primitivas o declara degradación (Video→link+poster, AudioPlayer→link, Modal→inline, Tabs→secciones apiladas en PDF/SSR, Icon→nombre/`svgPath` inline); `RenderedArtifact.metadata["degraded"]`; **Adaptive Cards**: `TextField→Input.Text` (`variant` → `style`/`isMultiline`), `CheckBox→Input.Toggle`, `ChoicePicker→Input.ChoiceSet` (`isMultiSelect`, `style`), `Slider→Input.Number`, `DateTimeInput→Input.Date`/`Input.Time`, `Button{action.event}→Action.Submit{data:{a2ui_action, surfaceId}}`, `Button{action.functionCall openUrl}→Action.OpenUrl`; los `Input.id` son los `path` del binding para que el `value` de Teams devuelva el `dataModel` parcial. **Paralelizable por renderer** tras Module 5.
- **Depends on**: Modules 3, 4, 5.

### Module 8: Transporte — A2A, handlers, deep links, Teams submit
- **Path**: `parrot/a2a/models.py`, `parrot/outputs/a2ui/deeplink.py`, `ai-parrot-server/.../handlers/{agent,deeplink}.py`, `ai-parrot-integrations/.../{a2ui_resume.py,msteams/wrapper.py,telegram/wrapper.py}`, `parrot/outputs/a2ui/emission.py`
- **Responsibility**: `A2UI_EXTENSION_URI`/`A2UI_MEDIA_TYPE` v1.0; `Artifact.from_a2ui_envelope` lee `createSurface` como clave de sobre; `a2ui_envelope` en handlers = sobre v1.0 o lista; `ResumePayload.action_payload` = sobre `action`; `build_structured_message` emite `{"type":"a2ui_action","action":<sobre>}`; wrapper Teams enruta `activity.value["a2ui_action"]` (y `a2ui_token` como hoy) al mismo camino.
- **Depends on**: Modules 1, 5, 7.

### Module 9: Productor LLM + emisión
- **Path**: `parrot/outputs/a2ui/producer.py`, `emission.py`, `tools/{infographic,interactive}_toolkit.py`
- **Responsibility**: `structured_output=CreateSurface` v1.0; `catalog_instructions()` con básico + parrot; re-prompt con códigos v1.0; medición de tasa first-shot (spike SPK: ≥ 85 % en 20 prompts con `claude-sonnet-4-5` o el modelo por defecto del repo) registrada en `artifacts/logs/`.
- **Depends on**: Modules 2, 5.

### Module 10: Tests de conformidad, docs y deprecaciones
- **Path**: `tests/outputs/a2ui/conformance/`, `docs/migration/feat-273-a2ui-deprecations.md`, `docs/outputs/a2ui-v1.md`, `parrot/outputs/formats/__init__.py`
- **Responsibility**: suite que valida todo envelope producido por builders/adapters/producer/renderers contra los schemas vendorizados; guía de migración dialecto → v1.0; actualización de textos de deprecación; changelog.
- **Depends on**: todos.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_serialize_envelope_by_key` | 1 | `serialize(CreateSurface)` → `{"version":"v1.0","createSurface":{…}}`; sin `messageType` |
| `test_envelope_exactly_one_key` | 1 | dos claves o ninguna → `ValidationError` |
| `test_component_props_top_level` | 1 | `Component(text="x")` se dumpea top-level; `properties` ausente |
| `test_children_list_or_template` | 1 | ambos aceptados; template exige `componentId`+`path` |
| `test_data_binding_path_only` | 1 | `{"path"}` OK; `{"$bind"}` rechazado en modelos nuevos |
| `test_update_data_model_value_required` | 1 | omitir `value` → error; `value: null` permitido |
| `test_legacy_normalize_create_surface` | 1 | dialecto viejo → v1.0 equivalente + `DeprecationWarning` |
| `test_legacy_normalize_card_to_infocard` | 1 | `Card{title,...}` legado → `InfoCard` |
| `test_legacy_update_data_model_contents_split` | 1 | `contents:{a,b}` → dos mensajes `{path,value}` |
| `test_spec_files_present_and_pinned` | 2 | seis JSON cargan; `SPEC_COMMIT` = SHA de 40 hex |
| `test_spec_drift_against_upstream` (`@network`) | 2 | hash de cada JSON coincide con `raw.githubusercontent.com/google/A2UI/<SHA>/…` |
| `test_validate_message_agent_to_renderer` | 2 | sobres válidos pasan; inválidos fallan con la ruta del error |
| `test_resolve_catalog_precedence` | 2 | componente → superficie → `CATALOG_UNRESOLVED` |
| `test_validate_root_required_and_unique_ids` | 2 | sin `root` / ids repetidos / hijo inexistente → errores listados todos |
| `test_unallowed_parent_child_codes` | 2 | `UNALLOWED_PARENT`/`UNALLOWED_CHILD` |
| `test_llm_origin_rejects_action` | 2 | `origin=LLM` + `Button.action` → `CatalogValidationError`; `TOOL` pasa |
| `test_basic_component_enums` (parametrizado ×18) | 3 | cada primitiva valida sus enums/defaults contra `catalog.json` |
| `test_basic_required_fields` | 3 | `Slider{value,max}`, `CheckBox{label,value}`, `Button{child,action}`… |
| `test_format_string_paths_and_escape` | 4 | `${/a}`, `${rel}`, `\${` literal |
| `test_format_string_function_named_args` | 4 | `${formatDate(value:${/d}, format:'MM-dd')}` |
| `test_index_only_in_template_scope` | 4 | `@index` fuera de template → `INVALID_FUNCTION_CALL` |
| `test_validators_return_validation_result` | 4 | `required/regex/length/numeric/email` |
| `test_boolean_functions` | 4 | `and/or/not` |
| `test_bake_resolves_path_call_template` | 4 | post-bake sin `path`/`call`; template expandido con índice |
| `test_bake_optional_binding_omitted` | 4 | `parrot_optional` → clave omitida, sin `BakeError` |
| `test_bake_unresolvable_raises` | 4 | pointer inexistente → `BakeError` |
| `test_lower_emits_v1_primitives` (parametrizado ×8) | 5 | cada componente parrot baja a primitivas del básico válidas |
| `test_text_role_in_extensions` | 5 | `Text.variant ∈ {caption,body}` + `metadata.extensions.parrot_role` |
| `test_datatable_lowers_to_child_template` | 5 | `children={componentId,path}` + celda con `${@index}` |
| `test_build_form_composition` | 5 | `TextField/CheckBox/ChoicePicker/DateTimeInput/Slider` + `Button.action.event` + `checks` |
| `test_export_catalog_definition_valid` | 5 | valida contra `catalog_definition.json`; `$ref` al básico; `instructions` presentes |
| `test_builders_emit_root` | 5 | `build_surface` → componente `id="root"` |
| `test_adapter_blocktype_remap` | 6 | `tab_view→Tabs`, `divider→Divider`, `checklist→CheckBox`, `bullet_list→List`, `image.fit` |
| `test_layout_spec_v2_and_migrate` | 6 | `migrate_layout(v1)` == v2 esperado; store lee v1 y escribe v2 |
| `test_recipe_schema_version_bump` | 6 | `SUPPORTED_SCHEMA_VERSION == 2`; v3 → `RecipeSchemaVersionError` |
| `test_renderer_capabilities_declared` (×6) | 7 | cada renderer declara `supported_components` no vacío |
| `test_renderer_degradation_recorded` (×6) | 7 | primitiva no soportada → salida + `metadata["degraded"]`, nunca excepción |
| `test_ssr_html_all_primitives` | 7 | 18 primitivas → HTML escapado válido |
| `test_adaptive_cards_native_inputs` | 7 | `TextField→Input.Text`, `CheckBox→Input.Toggle`, `ChoicePicker→Input.ChoiceSet`, `Slider→Input.Number`, `DateTimeInput→Input.Date` |
| `test_adaptive_cards_submit_carries_action` | 7 | `Button.action.event` → `Action.Submit.data == {"a2ui_action": <sobre action>, "surfaceId": …}` |
| `test_adaptive_cards_openurl` | 7 | `functionCall openUrl` → `Action.OpenUrl` |
| `test_interactive_html_renders_new_primitives` | 7 | Tabs/List/Divider/inputs presentes en el DOM |
| `test_a2a_constants_v1` | 8 | URI y mime nuevos; `from_a2ui_envelope` acepta sobre por clave y rechaza legado no normalizado |
| `test_handler_a2ui_envelope_is_v1` | 8 | stream y non-stream exponen sobre con `version:"v1.0"` |
| `test_deeplink_payload_is_action_envelope` | 8 | `ResumePayload` valida como `A2UIRendererMessage.action` |
| `test_teams_wrapper_routes_a2ui_action` | 8 | `activity.value["a2ui_action"]` → turno estructurado |
| `test_producer_uses_v1_structured_output` | 9 | `structured_output.output_type is CreateSurface` v1.0; re-prompt incluye código |
| `test_conformance_all_emitters` | 10 | builders/adapters/renderers → todo sobre valida contra schema |
| `test_no_exec`, `test_import_rule` | 10 | invariantes existentes siguen verdes |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_infographic_to_v1_envelope_to_ssr_html` | `InfographicResponse` → adapter → validate → bake → SSR-HTML |
| `test_e2e_recipe_v1_store_migrates_and_renders_pdf` | receta v1 en `FileRecipeStore` → `migrate_store` → run → PDF |
| `test_e2e_form_to_adaptive_card_to_teams_submit` | `build_form` → Adaptive Card → simulación de `activity.value` → turno `a2ui_action` |
| `test_e2e_llm_producer_first_shot_rate` (`@llm`, opcional) | 20 prompts → tasa catálogo-válida ≥ 85 % (registrar en `artifacts/logs/`) |
| `test_e2e_a2a_artifact_v1` | `Artifact.from_a2ui_envelope` → cliente A2A lee `mimeType application/a2ui+json` |

### Test Data / Fixtures
```python
@pytest.fixture(scope="session")
def v1_schemas(): ...            # load_spec(...) para los seis JSON + registry de $ref
@pytest.fixture
def legacy_envelope() -> dict:   # dialecto actual: messageType/properties/$bind/Card
    ...
@pytest.fixture
def v1_surface() -> CreateSurface:   # root Column → [InfoCard, Chart{data:{path}}, DataTable{children:template}]
    ...
@pytest.fixture
def sample_form_components() -> list[Component]: return build_form(...)
@pytest.fixture
def teams_submit_activity(v1_surface): ...   # activity.value = {"a2ui_action": {...}, "surfaceId": "main", "/form/name": "x"}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Todos los tests unitarios pasan (`pytest packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers packages/ai-parrot/tests/a2a packages/ai-parrot/tests/tools -v`).
- [ ] Todos los tests de integración pasan (los marcados `@network`/`@llm` son opcionales en CI).
- [ ] AC-G1: todo sobre emitido por builders, adapters, producer, recipes y renderers valida contra `agent_to_renderer.json` v1.0; `A2UI_VERSION == "v1.0"` y sólo `serialization.py` lo escribe.
- [ ] AC-G2: `createSurface` sin `catalogId` por componente resuelve `Text`/`Button`/… vía el catálogo parrot (que `$ref`-ea el básico); `catalogId` explícito de componente tiene precedencia; sin ninguno → `CATALOG_UNRESOLVED`.
- [ ] AC-G3: existen y validan los 18 modelos de primitivas y las 14 funciones; cada uno de los 6 renderers declara `supported_components` y degrada el resto registrándolo en `RenderedArtifact.metadata["degraded"]`.
- [ ] AC-G4: ningún envelope emitido contiene `role`, `optional` ni `$bind` como props; la semántica va en `metadata.extensions.parrot_*` y valida contra `common_types.json#/$defs/Extensions`.
- [ ] AC-G5: `deserialize` acepta el dialecto legado con `DeprecationWarning` y produce el mismo `CreateSurface` que la forma v1.0 equivalente; `migrate_store` convierte recetas v1→v2 y `SUPPORTED_SCHEMA_VERSION == 2`; no existe ningún flag de emisión legado.
- [ ] AC-G6: `Form` ya no está registrado; `build_form()` produce primitivas + `Button.action.event`; el `action` de un deep link valida como `A2UIRendererMessage`; Adaptive Cards emite inputs nativos y `Action.Submit` con `a2ui_action`, y el wrapper de Teams lo enruta como turno estructurado.
- [ ] AC-G7: `test_no_exec`, `test_import_rule` (adapters, recipes y el nuevo `catalog/basic/`) y el gate LLM/TOOL siguen en verde; `register_component` sigue exigiendo `lower()` para componentes no primitivos.
- [ ] AC-G8: `jsonschema>=4.20` declarado en `packages/ai-parrot/pyproject.toml`; los seis JSON de la spec están vendorizados con `SPEC_COMMIT` y el test de drift pasa contra ese SHA.
- [ ] AC-G9: el componente propio se llama `InfoCard`; `Card` resuelve al básico; `normalize_legacy` mapea `Card` legado → `InfoCard`.
- [ ] AC-G10: `A2UI_EXTENSION_URI == "https://a2ui.org/a2a-extension/a2ui/v1.0"`, `A2UI_MEDIA_TYPE == "application/a2ui+json"`, y `Part.metadata["mimeType"]` lo usa.
- [ ] Tasa first-shot catálogo-válida del productor ≥ 85 % en el spike de 20 prompts, evidencia en `artifacts/logs/feat-470-producer-rate.md`.
- [ ] Sin cambios en la API pública de `OutputMode.A2UI`, builders (`build_surface/build_chart/build_kpicard/build_card/build_datatable/build_infographic`) ni de los toolkits; `build_card` emite `InfoCard`.
- [ ] Documentación: `docs/outputs/a2ui-v1.md` y sección de migración en `docs/migration/feat-273-a2ui-deprecations.md`.
- [ ] Rendimiento: `validate_envelope` con jsonschema sobre un envelope de 200 componentes < 50 ms (p50) en el test de benchmark.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verificado el 2026-08-28 sobre `dev` (`8329f8a03`). Coincide con el Code Context del
> brainstorm (mismo día, sin commits intermedios en `outputs/a2ui/`).

### Verified Imports
```python
from parrot.outputs.a2ui.models import Component, CreateSurface, UpdateComponents, UpdateDataModel, A2UIMessageBase, BINDING_KEY, is_valid_pointer, is_binding_expression  # models.py:50-267
from parrot.outputs.a2ui.serialization import serialize, deserialize, to_jsonl, iter_jsonl, A2UI_VERSION, VERSION_FIELD  # serialization.py:38-112
from parrot.outputs.a2ui.catalog import register_component, unregister_component, get_component, list_components, catalog_instructions, validate_envelope  # catalog/__init__.py:57-165
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin, BasicNode, BasicTree, ComponentDefinition, RegisteredComponent, CatalogError, ComponentContractError, CatalogValidationError  # catalog/base.py:38-124
from parrot.outputs.a2ui.renderers import RendererCapabilities, AbstractA2UIRenderer, register_a2ui_renderer, get_a2ui_renderer  # renderers/__init__.py:48-130
from parrot.outputs.a2ui.baking import bake_envelope, BakeError               # baking.py:122, :31
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_kpicard, build_card, build_datatable, build_infographic  # builders.py:44-151
from parrot.outputs.a2ui.producer import ProducerResult, DEFAULT_MAX_ATTEMPTS  # producer.py:48, :45
from parrot.outputs.a2ui.emission import finalize_a2ui_response               # emission.py:18
from parrot.outputs.a2ui.deeplink import DeepLinkService, DeepLinkExpiredError, ResumePayload  # deeplink.py:66, :49, :53
from parrot.outputs.a2ui.adapters.infographic import infographic_response_to_envelope, CHART_TYPE_MAP  # adapters/infographic.py:573, ~:80
from parrot.outputs.a2ui.recipes.models import LayoutSpec, InfographicRecipe  # recipes/models.py:99, :175
from parrot.outputs.a2ui.recipes import SUPPORTED_SCHEMA_VERSION              # recipes/__init__.py:36
from parrot.a2a.models import A2UI_EXTENSION_URI, A2UI_MEDIA_TYPE, Artifact, Part  # a2a/models.py:338, :339, ~:375, :129
from parrot.models.outputs import OutputMode                                   # OutputMode.A2UI: models/outputs.py:64
# ai-parrot-visualizations
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer             # ssr_html.py:59
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer  # interactive_html.py:217
from parrot.outputs.a2ui_renderers.adaptive_cards import AdaptiveCardsRenderer  # adaptive_cards.py:64
from parrot.outputs.a2ui_renderers.pdf import PDFRenderer                       # pdf.py:99
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer               # echarts.py:56
from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer          # folium_map.py:61
# ai-parrot-server / integrations
from parrot.handlers.deeplink import DeepLinkResumeHandler, build_structured_message, setup_deeplink_routes  # handlers/deeplink.py:~66, ~55, 113
from parrot.integrations.a2ui_resume import ChannelDeepLinkResume, build_structured_message  # a2ui_resume.py:41, :30
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
BINDING_KEY = "$bind"                                                 # line 50
_JSON_POINTER_RE = re.compile(r"^(?:/(?:[^/~\s]|~[01])*)*$")          # line 56
def is_valid_pointer(pointer: str) -> bool                            # line 59
def is_binding_expression(value: Any) -> bool                         # line 79
def _validate_bindings(value: Any) -> None                            # line 93
class Component(BaseModel):                                           # line 123
    model_config = ConfigDict(populate_by_name=True, extra="allow")   # line 138
    id: str; component: str; properties: dict[str, Any]; children: list[str]
    @field_validator("properties") _check_binding_syntax              # line 146
class A2UIMessageBase(BaseModel): extra="forbid"                      # line 157
class CreateSurface(A2UIMessageBase):                                 # line 167
    message_type: Literal["createSurface"] alias "messageType"; surface_id alias "surfaceId"
    catalog_id alias "catalogId" (obligatorio); components: list[Component]; data_model alias "dataModel"
class UpdateComponents(A2UIMessageBase)                               # line 183
class UpdateDataModel(A2UIMessageBase): contents: dict[str, Any]; _check_pointer_keys  # line 196, :210
class Action(A2UIMessageBase): surface_id, component_id, action: str, payload: dict   # line 220
class ActionResponse(A2UIMessageBase)                                 # line 230  (NO existe en spec — eliminar)
class CallFunction(A2UIMessageBase): function_name, arguments         # line 241  (nombre 0.9.1 — reemplazar)
A2UIMessage = Annotated[Union[...], Field(discriminator="message_type")]  # line ~270

# packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
A2UI_VERSION = "1.0"; VERSION_FIELD = "version"                       # lines 38, 41
_ADAPTER: TypeAdapter = TypeAdapter(A2UIMessage)                      # line ~45
def serialize(message: A2UIMessageBase) -> dict[str, Any]             # line 48  (model_dump(by_alias=True, mode="json") + version)
def deserialize(data: dict | str | bytes) -> A2UIMessageBase          # line 64  (strip version; no asserta valor)
def to_jsonl(messages) -> str; def iter_jsonl(text) -> Iterator       # lines 98, 112

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"                 # line 38
class ProducerOrigin(str, Enum): LLM / TOOL                           # line 41
class BasicNode(BaseModel): extra="allow"; component: str; properties: dict; children: list["BasicNode"]  # line 53
BasicTree = BasicNode                                                 # line 75
class ComponentDefinition(BaseModel): name; catalog_id = DEFAULT_CATALOG_ID; schema_ (alias "schema"); instructions = ""; requires_actions = False  # line 79
@dataclass class RegisteredComponent: definition; component_cls      # line 100
class CatalogError(Exception) :112; ComponentContractError :116; CatalogValidationError.__init__(...) :124/:133

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(...) -> decorator (exige lower())              # line 57 / :81
def unregister_component(name) :105; get_component(name) -> RegisteredComponent :110
def list_components() -> list[ComponentDefinition] :119
def catalog_instructions() -> str :124   # f"{d.name}: {d.instructions}".rstrip(": ") — bug latente con instrucciones que terminan en ':'
def _iter_nested_component_names(value) -> list[str] :138
def validate_envelope(envelope: CreateSurface, *, origin: ProducerOrigin = ProducerOrigin.TOOL) -> None  # line 165

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/card.py
CARD_SCHEMA (title*, subtitle, body, image, badge, footer)            # line 16
@register_component("Card") class CardComponent: lower() → BasicNode("Card", {"variant":"card","componentId":…}, children=[Text{role}…])  # line 34-60
# resto de componentes: chart.py:57 ChartComponent · datatable.py:87 DataTableComponent (_lower_row :50-83; contrato dos fases :124-137)
#   map.py:60 · kpicard.py:34 · timeline.py:44 · form.py:60 FormComponent (requires_actions=True) · infographic.py:83 · report.py:82

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
_RENDERER_NAMESPACE = "parrot.outputs.a2ui_renderers"                 # line 35
class RendererCapabilities(BaseModel): interactive; supports_actions; supports_updates; output: str  # line 48
class AbstractA2UIRenderer(ABC): capabilities; async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str"  # line 65/:77
def register_a2ui_renderer(name, capabilities) :97 ; get_a2ui_renderer(name) :130

# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError :31 ; _ABSENT = object() :38 ; _load_jsonpointer() :48 (lazy)
def _resolve_value(value, data_model) -> Any :66   # maneja {"$bind", "optional"}
def _has_live_binding(value) -> bool :111
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]] :122

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
_DEFAULT_COMPONENT_ID = "blk-000" :37 ; _binding(pointer) :40
build_surface :44 · build_chart :71 · build_kpicard :91 · build_card :111 · build_datatable :128 · build_infographic :151

# packages/ai-parrot/src/parrot/outputs/a2ui/producer.py
DEFAULT_MAX_ATTEMPTS = 3 :45 ; class ProducerResult :48 ; _extract_envelope :71 ; _repair_prompt :91
# generate_envelope(...) ~:110-192 usa client.ask(structured_output=StructuredOutputConfig(output_type=CreateSurface)); param `catalog=` es no-op (:114)

# packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py
_KEY_TEMPLATE = "a2ui:deeplink:{token_id}" :41 ; _DEFAULT_TTL_SECONDS = 900 :42
class ResumePayload(BaseModel) (action_payload) :53 ; class DeepLinkService.__init__ :77 ; _resume_url(channel, token_id) :94

# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
CHART_TYPE_MAP ~:80 ; _CHART_FALLBACK="bar" :91 ; _MAX_NESTING_DEPTH=4 :95 ; _X_COLUMN="label" :97 ; _text() :154
class _Converter: _bind_rows :235 · _chart :241 · _table :273 · _hero_card :301 · _timeline :312 · _progress :329 · _card_like :343 · _chain :401 · _steps :419 · _code :437 · _card_grid :448 · walk :468 · _flatten_container :538
def infographic_response_to_envelope(...) :573

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class LayoutSpec(BaseModel): extra="forbid"; component: str; properties: dict  # line 99
class InfographicRecipe: schema_version: int = 1                       # line 175 / :211
SUPPORTED_SCHEMA_VERSION re-export                                     # recipes/__init__.py:36

# packages/ai-parrot/src/parrot/a2a/models.py
class Part: text, file_uri, file_bytes, file_media_type, filename, data, metadata   # line 129
A2UI_EXTENSION_URI = "https://a2ui.org/extensions/a2a/display/v1" :338 ; A2UI_MEDIA_TYPE = "application/vnd.a2ui.envelope+json" :339
def _reject_action_components(envelope) :342
class Artifact.from_a2ui_envelope(envelope, *, name="a2ui-surface", artifact_id=None) ~:375  # lee envelope.get("messageType")

# packages/ai-parrot-server/src/parrot/handlers/agent.py
# stream final: envelope['a2ui_envelope'] = ai_message.a2ui_envelope   lines 2701-2705
# non-stream A2UI: {"input","output","output_mode":"a2ui","a2ui_envelope"}  lines 2819-2827
# packages/ai-parrot-server/src/parrot/handlers/deeplink.py
def build_structured_message(payload: ResumePayload) -> str  # {"type":"a2ui_action_resume","action":…}  ~:55
class DeepLinkResumeHandler(service, invoker).handle(token) ~:66 ; def setup_deeplink_routes(...) :113  (no montado en manager — ver Does NOT Exist)
# packages/ai-parrot-integrations/src/parrot/integrations/a2ui_resume.py
def build_structured_message(action_payload: dict) -> str :30 ; class ChannelDeepLinkResume.__init__ :44 ; async resume(token, *, inject) :55
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
def _get_deeplink_resume(self) :316 ; submitted_data = turn_context.activity.value :346 ; a2ui_token = submitted_data.get("a2ui_token") :366-368  ← punto de enganche para "a2ui_action"

# Satélite: packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/
ssr_html.py: _CONTAINER_COMPONENTS = {"Column":"a2ui-col","Row":"a2ui-row","Card":"a2ui-card"} :47 ; SSRHTMLRenderer :59 ; _render_component :109 ; _render_basic :129 (solo Text/Image/contenedores)
interactive_html.py: InteractiveHTMLRenderer :217 ; _render_top :261 ; _render_descriptor :271 ; _render_via_lowering :292 ; _render_basic :310 ; _render_chart :333 ; _render_datatable :387 ; _render_infographic :423 ; _BEHAVIOR_JS (ES2017 inline) ; _CHART_JS_SOURCE vendorizado
adaptive_cards.py: AdaptiveCardsRenderer :64 ; render() emite deep links como TextBlock(text=f"{link.action_label}: {link.url}") :81-84 (nunca Action.OpenUrl hoy) ; _element_for_component :101 ; _map_node :120
pdf.py: PDFRenderer :99 ; _rasterize :137 · echarts.py: EChartsRenderer :56 ; _build_option :110 · folium_map.py: FoliumMapRenderer :61
# packages/ai-parrot-visualizations/pyproject.toml: extras a2ui = ["jsonpointer>=2.4", …] :52-58 ; a2ui-pdf :59-62
# packages/ai-parrot/pyproject.toml: dependencies :36 (pydantic==2.12.5 :51; sin jsonschema ni jsonpointer)
# Instalados en .venv: jsonpointer 3.1.1, jsonschema 4.26.0 (transitivo)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `compat.normalize_legacy` | `serialization.deserialize` | llamada previa a la validación cuando `"messageType" in data` | `serialization.py:64` |
| `catalog/basic/*` | `catalog.register_component` (con `is_primitive=True`, sin `lower()`) | registro en import | `catalog/__init__.py:57-104` |
| `validate_message` / `validate_envelope` | `jsonschema.Draft202012Validator` + `referencing.Registry` con los JSON vendorizados | validación | nuevo (`jsonschema 4.26.0` presente) |
| `FunctionEvaluator` | `baking._resolve_value` | sustituye el manejo de `$bind`/`optional` | `baking.py:66-108` |
| `catalog/parrot/*.lower()` | `BasicNode` v1.0 | mismo contrato `lower(component, data_model) -> BasicTree` | `catalog/components/card.py:41` |
| `build_form()` | `Button.action.event` + `checks` | composición | nuevo |
| `export_catalog_definition` | `list_components()`, `basic_components()`, `catalog_instructions()` | agregación | `catalog/__init__.py:119-136` |
| `RendererCapabilities.supported_components` | cada `@register_a2ui_renderer(...)` del satélite | declaración | `ssr_html.py:50-58` y equivalentes |
| Adaptive Cards inputs | `AdaptiveCardsRenderer._map_node` | nuevas ramas por primitiva | `adaptive_cards.py:120` |
| Teams `Action.Submit` | `msteams/wrapper.py` bloque `submitted_data` | nueva rama `a2ui_action` junto a `a2ui_token` | `msteams/wrapper.py:346-368` |
| `ResumePayload.action_payload` | `A2UIRendererMessage.action` | validación al crear el deep link | `deeplink.py:53` |
| `Artifact.from_a2ui_envelope` | clave `createSurface` del sobre | reemplaza `envelope.get("messageType")` | `a2a/models.py:~390` |
| `migrate_store` | `AbstractRecipeStore` (`FileRecipeStore`, `DBRecipeStore`) | lectura v1 + escritura v2 | `recipes/store.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.models.DeleteSurface / CallRendererFunction / AgentFunctionResponse / CallAgentFunction / RendererFunctionResponse / ErrorMessage / A2UIAgentMessage / A2UIRendererMessage / DataBinding / FunctionCall / ChildTemplate / CheckRule / ValidationResult / AccessibilityAttributes`~~ — se crean en Module 1.
- ~~`parrot.outputs.a2ui.compat`~~ — no existe.
- ~~`parrot.outputs.a2ui.catalog.basic`~~ (ni `BASIC_CATALOG_ID`, `SPEC_COMMIT`, `load_spec`, `FunctionEvaluator`) — no existe; las primitivas hoy son solo strings en `BasicNode.component`.
- ~~`parrot.outputs.a2ui.catalog.parrot`~~ — los componentes propios viven en `catalog/components/`.
- ~~`parrot.outputs.a2ui.catalog.export`~~ / ~~`catalog_definition.json`~~ — no existe exportación.
- ~~`InfoCard`~~ — hoy es `Card` (`catalog/components/card.py:34`).
- ~~`build_form()`~~ — `Form` es componente registrado (`form.py:60`, `requires_actions=True`).
- ~~`RendererCapabilities.supported_components` / `supported_catalog_ids`~~ — no existen.
- ~~`RenderedArtifact.metadata`~~ — **no existe** (`artifacts.py:41`, campos actuales: content XOR path + mime; verificado 2026-08-28). Module 7 añade `metadata: dict[str, Any] = {}` (con la clave `degraded`) al modelo.
- ~~`ComponentDefinition.allowed_parents/allowed_children`~~, ~~`FunctionDefinition`~~ — no existen.
- ~~`recipes.migrate` / `migrate_layout` / `migrate_store`~~ — no existen; `SUPPORTED_SCHEMA_VERSION` vale 1.
- ~~Componente `id:"root"`~~ — ningún envelope actual lo usa; builders generan `blk-NNN`.
- ~~`Action.OpenUrl` / `Action.Submit` / `Input.*` en `adaptive_cards.py`~~ — hoy solo `TextBlock`, contenedores y deep links como texto.
- ~~`activity.value["a2ui_action"]` en el wrapper de Teams~~ — solo existe `a2ui_token` (`wrapper.py:366`).
- ~~`setup_deeplink_routes` montado en `manager.py`~~ — definido pero no llamado desde ningún módulo no-test (montarlo es FEAT-469 Module 7; aquí solo cambia el formato del payload).
- ~~`ai-parrot` core con `jsonschema`/`jsonpointer` declarados~~ — no en `pyproject.toml` (Module 2 añade `jsonschema`; `jsonpointer` sigue como extra del satélite, con import lazy en `baking.py`).
- ~~`beginRendering`, `surfaceUpdate`, `dataModelUpdate`, `userAction`~~ — nombres 0.8/0.9 solo en `sdd/proposals/infographic-theme-catalog-a2ui.spec.md`.
- ~~Paquete JS/TS propio o `@a2ui/lit` vendorizado~~ — el único runtime cliente es `_BEHAVIOR_JS` inline.
- ~~`agent_capabilities` en el Agent Card~~ — no existe; es FEAT-469.
- ~~`ActionMessage` con campos exactos confirmados~~ — la forma exacta de `renderer_to_agent.json#action` (p. ej. si `surfaceId`/`dataModel` van dentro o en `metadata`) debe leerse del JSON vendorizado en Module 2 antes de fijar el modelo `(unverified — check before use)`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **G3**: `version` sólo lo escribe `serialization.serialize`; los modelos de sobre lo declaran como `Literal["v1.0"]` pero `serialize` es quien lo inyecta al dumpear mensajes internos.
- **G8**: `catalog/basic/` y `compat.py` no importan `parrot.bots`/`parrot.clients`/`DatasetManager`; ampliar `adapters/test_import_rule.py` para cubrir `catalog/basic/` y `compat.py`.
- **G4**: `register_component` sigue exigiendo `lower()` salvo `is_primitive=True` (solo el catálogo básico).
- **Lazy imports**: `jsonpointer` (bake) permanece lazy; `jsonschema` puede importarse a nivel de módulo en `catalog/` porque pasa a ser dependencia dura.
- **Presentación en extensions**: claves `parrot_role`, `parrot_component_id`, `parrot_optional`, `parrot_variant` (para `Card{variant:"chart"|...}` que hoy usan los renderers); todas UAX #31, nunca `a2ui_*`.
- **Renderers**: `_render_basic`/`_map_node` se convierten en dispatch por `node.component` con tabla explícita + `_degrade(node)` que registra en `metadata["degraded"]`.
- **Adaptive Cards**: `Input.id` = `path` del binding (`/form/name`), de modo que `activity.value` devuelva `{"/form/name": "..."}` y pueda aplicarse como `updateDataModel` parcial; `Action.Submit.data = {"a2ui_action": <sobre action>, "surfaceId": …}`.
- **Compat sólo de entrada**: `normalize_legacy` vive en `compat.py` y sólo lo invoca `deserialize`; ningún emisor lo usa.
- **Producer**: `catalog_instructions()` concatena básico + parrot; arreglar el `rstrip(": ")` de `catalog/__init__.py:131` al tocarlo.
- Pydantic v2, docstrings Google, `self.logger`; tests con `pytest-asyncio`.

### Known Risks / Gotchas
- **Sobre con más de una clave** o sin `version` → `ValidationError` en `deserialize`; sobre legado sin `messageType` → error claro, no adivinar.
- **`CATALOG_UNRESOLVED`**: componente sin `catalogId` en superficie sin default. Los builders siempre ponen `catalogId=parrot` en `createSurface`.
- **`root`** ausente/duplicado o hijo inexistente → error de validación con lista completa (para el retry del productor).
- **`Card` legado** → `InfoCard` con warning; un `Card` v1.0 legítimo (con `child`) no se toca: la heurística es "tiene `properties`" (dialecto viejo) vs props top-level.
- **`updateDataModel` legado** `contents:{a,b}` → N mensajes; el orden se preserva.
- **Bake**: binding no resoluble → `BakeError` salvo que esté en `parrot_optional`; `formatString` con función desconocida o `@`-namespace no reservado → `INVALID_FUNCTION_CALL`; `@index` fuera de template → error.
- **Renderer estático con primitiva no soportada** → degradación registrada, nunca excepción silenciosa.
- **Adaptive Cards con inputs nativos antes de FEAT-469**: el `Action.Submit` llega al wrapper de Teams y se convierte en turno estructurado del bot (mismo camino que el deep link); no hay `agentFunctionResponse` hasta FEAT-469 — documentarlo. Para Slack/email (sin receptor) el `Button` sigue siendo deep link.
- **Teams `Input.id`** no admite `/` en algunas versiones del cliente → si falla, codificar `path` (p. ej. `~1` → verificar en implementación) y decodificar en el wrapper.
- **Recetas persistidas**: `migrate_store` debe ser idempotente y ofrecer `dry_run`; `DBRecipeStore` requiere transacción por receta.
- **Tests existentes (~470)**: reescritura de fixtures; conviene un helper `tests/outputs/a2ui/_v1.py` con constructores de sobres para no duplicar JSON.
- **Drift de la spec**: `catalog.json` es "v1.0 (Candidate)"; el pin por SHA protege, y el test `@network` avisa; actualizar el pin es un cambio deliberado con changelog.
- **`catalog_instructions()` bug latente** (`rstrip(": ")`) — corregir en Module 5.
- **FEAT-469** depende de este spec: cambios en la forma de `A2UIRendererMessage` o `catalog/export.py` deben reflejarse allí antes de su `/sdd-task`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `jsonschema` | `>=4.20` (4.26.0 instalado) — **dependencia dura de `ai-parrot`** | validación de sobres y componentes contra los JSON oficiales |
| `referencing` | transitivo de jsonschema ≥4.18 | registry de `$ref` entre los JSON vendorizados |
| `jsonpointer` | `>=2.4` (3.1.1) — extra `a2ui` del satélite, lazy en core | resolver `path` en bake |
| `pydantic` | `==2.12.5` (core) | modelos v1.0 |
| `google/A2UI` `specification/v1_0/**` | pin `90157ec10f36cf8e192daa71c95d2684af20c756` | schemas vendorizados + test de drift |
| `weasyprint`, `folium`, `jinja2` | sin cambios | renderers existentes |

---

## 8. Open Questions

- [x] ¿Tipo de flujo y rama base? — *Resolved in brainstorm*: feature sobre `dev`.
- [x] ¿Compatibilidad hacia atrás? — *Resolved in brainstorm*: solo lectura + migración; emisión siempre v1.0; sin flag dual.
- [x] ¿Alcance del catálogo básico en renderers? — *Resolved in brainstorm*: modelos completos en core; render por niveles con degradación declarada por renderer.
- [x] ¿Acciones/RPC en esta feature? — *Resolved in brainstorm*: modelos + `Form` como composición + deep links con `action` v1.0; runtime `callAgentFunction` en FEAT-469 (`sdd/specs/a2ui-agent-functions.spec.md`, ya creado).
- [x] ¿Identidad de catálogos? — *Resolved in brainstorm*: `basic` oficial + `parrot` propio; superficie default `parrot`; el catálogo parrot incluye el básico por `$ref`.
- [x] ¿Dónde va la semántica de presentación? — *Resolved in brainstorm*: `metadata.extensions.parrot_*`.
- [x] ¿Dónde viven modelos/funciones básicas? — *Resolved in brainstorm*: core `parrot/outputs/a2ui/catalog/basic/`; renderers en `ai-parrot-visualizations`.
- [x] ¿`jsonschema` como extra o dependencia dura? — *Resolved in spec clarification*: dependencia dura de `ai-parrot` (`jsonschema>=4.20`).
- [x] ¿Vendorizar la spec o descargar en CI? — *Resolved in spec clarification*: vendorizar en el paquete con pin por SHA (`90157ec1`) + test de drift `@network`.
- [x] Nombre del `Card` propio — *Resolved in spec clarification*: `InfoCard`, con alias de lectura `Card`-legado en compat.
- [x] Degradación de inputs en Adaptive Cards — *Resolved in spec clarification*: **inputs nativos ya** (`Input.Text/Toggle/ChoiceSet/Number/Date/Time` + `Action.Submit` con `a2ui_action`), recibidos por el wrapper de Teams existente; `agentFunctionResponse` llega con FEAT-469.
- [x] ¿`agent_capabilities` aquí o en el follow-up? — *Resolved by FEAT-469 spec*: en FEAT-469 (aquí sólo URI/mime).
- [x] `catalogId` del catálogo parrot — *Resolved by brainstorm C2*: se mantiene `https://parrot.dev/catalogs/v1`.
- [ ] ¿Comando de migración de recetas como subcomando CLI (`parrot a2ui migrate-recipes`) además de `migrate_store()`? — *Owner: Jesus Lara* (decidible en Module 6)
- [ ] Forma exacta del mensaje `action` en `renderer_to_agent.json` (ubicación de `surfaceId`/`dataModel`) — leer del JSON vendorizado en Module 2. — *Owner: implementación*
- [ ] Codificación de `Input.id` con `/` en Teams (ver riesgo) — *Owner: implementación (Module 7)*
- [ ] Adoptar el renderer web oficial (`@a2ui/lit`) para `interactive-html` — feature posterior; verificar nombre/versión del paquete npm. — *Owner: Jesus Lara*
- [ ] Modelo y umbral definitivos del spike de tasa first-shot (propuesto ≥ 85 % / 20 prompts). — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Secuencial en el worktree de la feature** (`feat-470-a2ui-v1-dialect`): Module 1 (wire) → Module 2 (spec vendorizada + validación) — nada más puede empezar sin ellos. Al final, Modules 8, 9 y 10 (transporte, productor, conformidad/docs) también secuenciales porque cruzan tres paquetes del workspace.
- **Paralelizables tras Module 2** (worktrees hijos ramificados desde la rama de la feature, merge de vuelta en este orden):
  1. Modules 3 + 4 (`catalog/basic/`: primitivas y funciones + bake) — directorio nuevo, sin conflictos.
  2. Module 5 + 6 (catálogo parrot, `build_form`, export, adaptador, recetas) — depende de 3/4 para las primitivas; puede arrancar en paralelo usando los modelos de 3 desde su rama si se mergea 3 primero.
  3. Module 7 (6 renderers del satélite) — paralelizable **por renderer** una vez mergeado 5.
- **Cross-feature dependencies**: ninguna feature con tareas pendientes en `sdd/tasks/index/`. **FEAT-469 `a2ui-agent-functions` debe esperar** al merge de este spec (comparte `a2a/models.py`, `deeplink.py`, `handlers/deeplink.py`, `integrations/a2ui_resume.py`, `msteams/wrapper.py`). Cualquier feature nueva que toque `outputs/a2ui/` o `a2ui_renderers/` debe esperar.
- **Rationale**: los carriles tocan directorios disjuntos (`catalog/basic/`, `catalog/parrot/`+`recipes/`, satélite) y sólo dependen del wire nuevo; serializar todo alargaría innecesariamente una feature ya grande, pero el wire y el transporte cruzan paquetes y deben ser un único hilo.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-28 | Jesus Lara / Claude | Initial draft desde brainstorm Option B (FEAT-470) |
