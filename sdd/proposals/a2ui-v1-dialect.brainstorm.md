---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: A2UI v1.0 Dialect — wire estándar, catálogo básico completo, catálogo de presentación propio

**Date**: 2026-08-28
**Author**: Jesus Lara (con Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

La implementación A2UI de ai-parrot (FEAT-273 y derivados: FEAT-301/324/326/420/430)
declara apuntar a A2UI v1.0 (`A2UI_VERSION = "1.0"`), pero el wire real es un
**dialecto propio** que ningún renderer A2UI externo puede consumir. El diagnóstico
completo está en `artifacts/a2ui_v1_gap_diagnosis.md`; en síntesis, contrastado
contra los schemas oficiales (`google/A2UI` `specification/v1_0/json/*.json`,
`catalogs/basic/catalog.json`, `extensions/a2a/docs/a2ui_extension_specification.md`):

1. **Sobre**: emitimos `{"messageType":"createSurface", …, "version":"1.0"}`; la spec
   exige `{"version":"v1.0","createSurface":{…}}` (exactamente una clave de mensaje).
2. **Componente**: props anidadas en `properties:{}`; la spec las pone al nivel superior,
   con `child` / `children` (lista o template `{componentId, path}`), `catalogId`,
   `weight`, `accessibility`, `checks`, `action`, `metadata.extensions`.
3. **Binding**: `{"$bind": "/ptr"}` (+ `optional`) vs `{"path": "/ptr"}` / `{"call","args"}`.
4. **Mensajes**: `updateDataModel` con `contents:{}` en vez de `{path?, value}`; falta
   `deleteSurface`, `callRendererFunction`, `agentFunctionResponse`, `callAgentFunction`,
   `rendererFunctionResponse`, `error`; `callFunction` conserva el nombre 0.9.1;
   `actionResponse` no existe en la spec; `action` tiene otra forma.
5. **Raíz**: no existe el componente `id:"root"` ni el contenedor reservado `Surface`.
6. **Catálogo básico**: `lower()` solo produce 5/18 primitivas (Column, Row, Card, Text,
   Image), y con desvíos (`Text.role` vs `variant`, `Card.children` vs `child`);
   0/14 funciones renderer-side; sin `ValidationResult` ni códigos `UNALLOWED_*`.
7. **A2A**: URI `…/extensions/a2a/display/v1` y mime `application/vnd.a2ui.envelope+json`
   vs `https://a2ui.org/a2a-extension/a2ui/v1.0` y `application/a2ui+json`; sin
   `agent_capabilities` / `renderer_capabilities`.

Al mismo tiempo, ai-parrot construyó sobre A2UI una capa de **rendering de
presentación** que la spec (pensada para UI viva) no cubre y que hay que preservar:
catálogo de presentación (Chart, DataTable, Map, KPICard, Timeline, Infographic,
Report), bake de bindings para renderers estáticos (SSR-HTML, PDF, Adaptive Cards,
ECharts, Folium, interactive-HTML), delivery multicanal, deep links de acción sobre
canales sin renderer, productor LLM con validate-retry-degrade, recetas
(`LayoutSpec`) y el adaptador Infographic (19 `BlockType`).

**Afectados**: desarrolladores de agentes (catálogo y OutputMode A2UI), consumidores
del `a2ui_envelope` (handlers HTTP/stream, A2A, integraciones Telegram/Teams/Slack),
operadores con recetas persistidas, y cualquier renderer A2UI de terceros que
queramos habilitar (Lit/Angular/Flutter oficiales).

**Por qué ahora**: v1.0 es la spec candidata estable; cada feature nueva sobre el
dialecto actual (recipes, theme catalog, narrative) aumenta el costo de migrar.

## Constraints & Requirements

- **C1 — Wire 100% v1.0**: todo mensaje emitido valida contra
  `agent_to_renderer.json` v1.0; todo mensaje recibido valida contra
  `renderer_to_agent.json`. `version` const `"v1.0"`.
- **C2 — Dos catálogos mezclables**: `basic` oficial
  (`https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json`) y `parrot`
  (`https://parrot.dev/catalogs/v1`). La superficie usa `catalogId=parrot` por defecto;
  el catálogo parrot **incluye** (por `$ref`) los 18 componentes y 14 funciones del
  básico, de modo que la resolución estricta v1.0 (component `catalogId` → surface
  default → error) encuentre `Text`, `Button`, etc. sin `catalogId` explícito.
- **C3 — Catálogo básico completo en core**: 18 primitivas + 14 funciones modeladas y
  validadas en `parrot/outputs/a2ui/catalog/basic/`; los renderers propios declaran
  qué primitivas soportan y degradan las demás (render por niveles).
- **C4 — Semántica de presentación fuera del schema**: `Text.role`, hints de renderer,
  bindings opcionales → `metadata.extensions.parrot_*` (claves UAX #31; `a2ui_` reservado).
- **C5 — Compatibilidad solo de lectura + migración**: `deserialize` acepta el dialecto
  actual (`messageType`, `properties{}`, `$bind`) y lo normaliza a v1.0; emisión
  siempre v1.0; `migrate_layout()` para recetas persistidas (bump de
  `SUPPORTED_SCHEMA_VERSION`). Sin flag de emisión dual.
- **C6 — Acciones**: se modelan todos los mensajes; `Form` pasa a composición de
  primitivas (`TextField`/`CheckBox`/`ChoicePicker`/`DateTimeInput`/`Slider` +
  `Button.action.event` + `checks`); los deep links transportan un `action` v1.0.
  El runtime de `callAgentFunction`/`agentFunctionResponse`/`sendDataModel` es un
  **follow-up con spec propio** (`a2ui-agent-functions`), no parte de esta feature.
- **C7 — Invariantes vigentes se mantienen**: G8 (a2ui core no importa `parrot.bots`/
  `parrot.clients`), G3 (`version` solo en `serialization.py`), G4 (`lower()` obligatorio),
  G1/D10b (allowlist + gate de acciones por origen LLM/TOOL), `test_no_exec.py`.
- **C8 — Sin deps pesadas en core**: `jsonpointer`/`jsonschema` siguen siendo opcionales
  (extras del satélite) o import lazy; el evaluador de funciones básicas es puro Python.
- **C9 — Renombrar `Card` propio** (colisiona con `Card` básico) → `InfoCard`, con alias
  de lectura en el deserializador compat.

---

## Options Explored

### Option A: Capa de traducción (wire adapter) sobre los modelos actuales

Mantener `models.py` tal cual (dialecto interno) y añadir un par
`to_v1()` / `from_v1()` en `serialization.py` que reescriba el sobre, suba `properties`
al nivel superior, convierta `$bind`→`path` y reempaquete `updateDataModel`. El catálogo
básico se añade como componentes propios más (`Button`, `Tabs`, …) registrados con
`register_component`, cada uno con su `lower()`.

✅ **Pros:**
- Cambio mínimo en el código existente (builders, adapters, recipes, renderers no cambian).
- Riesgo bajo de regresión; los ~470 tests actuales siguen válidos.

❌ **Cons:**
- Dos verdades: el modelo interno diverge del wire; cada campo nuevo de v1.0
  (`weight`, `accessibility`, `checks`, `action`, `child`, template `children`)
  necesita mapeo bidireccional ad-hoc y se acaba parcheando `Component.extra`.
- `LayoutSpec`/recipes siguen en dialecto viejo → migración pendiente para siempre.
- Las 18 primitivas registradas como "componentes parrot" con `lower()` es un
  contrasentido: son ya el nivel básico, no se bajan a nada.
- El LLM sigue produciendo el dialecto interno → el `structured_output` no aprovecha
  el schema oficial ni el `instructions` del catálogo.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonpointer>=2.4` (3.1.1 instalado) | resolver `path` en bake | ya extra `a2ui` del satélite |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/serialization.py` — único punto de inyección de `version`.
- `parrot/outputs/a2ui/catalog/__init__.py::register_component` — registro de los nuevos.

---

### Option B: Modelos nativos v1.0 + catálogo básico en core + deserializador compat (recomendada)

Reescribir `models.py` para que las clases Pydantic **sean** el wire v1.0:

- Sobre por clave: `A2UIMessage = {version:"v1.0"} ∪ exactamente-una-de
  {createSurface, updateComponents, updateDataModel, deleteSurface,
  callRendererFunction, agentFunctionResponse}` (A→R) y
  `{action, callAgentFunction, rendererFunctionResponse, error}` (R→A). `serialize`
  produce `{"version":"v1.0","<msg>":{…}}`; `deserialize` detecta la clave.
- `Component` v1.0: `id`, `component`, `catalogId?`, `child?`, `children?`
  (lista | template), `weight?`, `accessibility?`, `checks?`, `action?`,
  `metadata.extensions?`, y el resto como props top-level (`extra="allow"` pero
  validadas contra el schema del catálogo resuelto).
- `DataBinding = {"path": str}`, `FunctionCall = {"call": str, "args": {...},
  "catalogId"?}`; tipos `DynamicString/Number/Boolean/StringList`.
- Nuevo paquete `catalog/basic/`: 18 modelos de primitivas (uno por componente, con
  `variant`/enums exactos y `Checkable` mixin), `functions.py` con evaluador puro
  de las 14 funciones (`formatString` con `${/path}`, `${fn(arg:'v')}`, escape
  `\${`; `@index`; validadores → `ValidationResult`; `and/or/not`; `openUrl` marcado
  `requiresUserActivation`), y `catalog.json` exportado (`protocolVersion:"1.0"`).
- Catálogo parrot: `InfoCard` (renombrado), `Chart`, `DataTable`, `Map`, `KPICard`,
  `Timeline`, `Infographic`, `Report`; `lower()` ahora emite primitivas básicas v1.0
  completas (`Text{variant}` + `metadata.extensions.parrot_role`, `Card{child}`,
  `Tabs`, `Divider`, `List`, `Image{fit}`) y `DataTable` usa template `children`
  + `@index`. `Form` deja de ser componente y pasa a **helper de composición**
  (`build_form()` produce primitivas + `Button.action.event`).
- `catalog/export.py`: genera `catalog_definition.json` de parrot que `$ref`-ea el
  básico e incluye `instructions` concatenadas; `validate_envelope` valida
  componentes contra el schema del catálogo resuelto (jsonschema lazy) además del
  allowlist y el gate de acciones.
- `serialization.deserialize` + `compat.py`: reconocen el dialecto legado
  (`messageType`, `properties`, `$bind`, `Card` propio, `updateDataModel.contents`) y
  lo normalizan a v1.0 con `DeprecationWarning`; `recipes.migrate_layout()` sube
  `LayoutSpec` a la forma nueva y `SUPPORTED_SCHEMA_VERSION` a 2.
- Bake: resuelve `path` y evalúa `call` (formatString/@index/validación) en agent-side
  antes de un renderer estático; los bindings opcionales se marcan en
  `metadata.extensions.parrot_optional: ["/ptr"]`.
- `RendererCapabilities` gana `supported_catalog_ids: list[str]` y
  `supported_components: set[str]`; cada renderer del satélite declara sus primitivas
  y `render()` degrada las no soportadas (Video→link+poster, AudioPlayer→link,
  Modal→inline, Tabs→secciones apiladas en PDF/SSR, inputs→texto de solo lectura
  en Adaptive Cards con deep link, Icon→nombre/svgPath inline).
- A2A: `A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v1.0"`,
  `mimeType = "application/a2ui+json"` en `DataPart.data.metadata`, y
  `agent_capabilities` (`supportedCatalogIds: [parrot, basic]`) publicable en el
  Agent Card. Handlers HTTP/stream siguen exponiendo `a2ui_envelope` (ahora un
  sobre v1.0 o lista JSONL de sobres).
- Deep links: el payload almacenado es un `action` v1.0 (`name`, `context`,
  `surfaceId`); el resume inyecta ese `action` (en vez de `a2ui_action_resume`).

✅ **Pros:**
- Una sola verdad: el modelo Pydantic es el wire; el `structured_output` del productor
  recibe el schema oficial + `instructions`, sube la tasa first-shot y elimina mapeos.
- Catálogo básico completo habilita renderers A2UI de terceros (Lit/Angular/Flutter)
  sobre superficies parrot; el catálogo parrot queda como extensión legítima.
- `Form` como composición elimina la degradación "This form is not available" y
  desbloquea validación declarativa (`checks`).
- Template `children` + `@index` reemplaza la materialización manual de filas.
- La capa de presentación (bake, renderers, delivery, deep links, recipes, adapter)
  se conserva íntegra y queda re-anclada a `capabilities`.

❌ **Cons:**
- Cambio amplio: `models.py`, `builders.py`, `adapters/infographic.py`, los 9
  componentes, `LayoutSpec`, 6 renderers, `a2a/models.py`, `deeplink.py` y sus tests.
- Migración de recetas persistidas (FileRecipeStore/DBRecipeStore) y de consumidores
  externos que leen `messageType`/`properties` — mitigado por C5 (lectura compat).
- Doble nomenclatura transitoria (`Card` básico vs `InfoCard`).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonpointer>=2.4` (3.1.1) | resolver `path` en bake | extra `a2ui` del satélite; import lazy en core |
| `jsonschema>=4.20` (4.26.0 presente transitivamente) | validar componentes contra `catalog.json` | añadir como extra opcional de core (`ai-parrot[a2ui-schema]`) o import lazy con fallback a allowlist |
| `google/A2UI` `specification/v1_0/**` | schemas y catálogo oficial vendorizados en `catalog/basic/spec/` | pin por commit SHA; test de drift |
| `pydantic>=2` | modelos discriminados por clave de sobre | ya en core |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/serialization.py` — sigue siendo el único dueño de `version`; se
  reescribe `serialize/deserialize/to_jsonl/iter_jsonl`.
- `parrot/outputs/a2ui/catalog/__init__.py` — `register_component`, `validate_envelope`,
  `catalog_instructions` se extienden (no se reemplazan).
- `parrot/outputs/a2ui/catalog/base.py` — `ComponentDefinition` (añadir
  `allowed_parents`, `allowed_children`), `BasicNode` (pasa a usar props top-level).
- `parrot/outputs/a2ui/baking.py` — `_resolve_value` cambia `$bind`→`path` y añade `call`.
- `parrot/outputs/a2ui/renderers/__init__.py` — `RendererCapabilities` ampliado.
- `parrot/outputs/a2ui/deeplink.py` — `ResumePayload` pasa a envolver un `action` v1.0.
- `parrot/a2a/models.py:335-433` — constantes y `Artifact.from_a2ui_envelope`.
- `parrot/outputs/a2ui/adapters/infographic.py` — mapeo de 19 `BlockType`; se mejora
  (`tab_view/accordion→Tabs`, `divider→Divider`, `bullet_list/steps→List`,
  `checklist→CheckBox`, `image→Image{fit}`).
- `parrot/outputs/a2ui/recipes/models.py::LayoutSpec` + `store.py` — migración.
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/*.py` — los 6
  renderers amplían `_render_basic`/`_map_node`.

---

### Option C: Catálogo dirigido por JSON Schema (modelos generados) + renderer web oficial

Vendorizar `catalog.json`/`common_types.json` y **generar** los modelos Pydantic de
las primitivas en build time (`datamodel-code-generator`), validando siempre con
`jsonschema` contra el catálogo resuelto; el catálogo parrot se escribe también como
`catalog.json` y sus modelos se generan igual. Para `interactive-html`, en vez del
runtime JS propio, embeber el **renderer web oficial** de A2UI (`@a2ui/lit` o
`@a2ui/web-core`, npm) como bundle vendorizado, delegándole las 18 primitivas y las
14 funciones, y manteniendo solo los renderers estáticos propios (SSR/PDF/Adaptive
Cards/ECharts/Folium) en Python.

✅ **Pros:**
- Cero drift con la spec: los modelos son derivados del schema oficial; actualizar a
  v1.1 es re-generar.
- El renderer web oficial ya implementa funciones, `checks`, template `children`,
  dos-vías y `action` — evita reimplementar el runtime interactivo en JS propio.
- Catálogo parrot definido como JSON = publicable tal cual para terceros.

❌ **Cons:**
- Modelos generados son menos ergonómicos (nombres, docstrings, validadores custom
  como el gate de acciones deben vivir fuera).
- Dependencia de un bundle npm (tamaño, licencia Apache-2.0 OK, CSP en Slack/Teams no
  aplica, pero sí peso del HTML autocontenido; Chart.js vendorizado ya pesa ~200 KB).
- El renderer oficial no conoce `Chart`/`DataTable`/`Map` parrot: habría que
  registrar componentes custom en su API JS → trabajo JS/TS que hoy el repo no tiene.
- Paso de build (codegen + bundle) nuevo en CI/release.

📊 **Effort:** High (y añade superficie JS/TS)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `datamodel-code-generator` | generar Pydantic desde `catalog.json` | dev-dep; salida commiteada |
| `jsonschema>=4.20` | validación runtime | igual que B |
| `@a2ui/lit` / `@a2ui/web-core` (npm) | renderer web oficial para `interactive-html` | verificar nombre/versión exacta del paquete en el repo oficial antes de spec |

🔗 **Existing Code to Reuse:**
- `interactive_html.py` — patrón de bundle vendorizado (`_CHART_JS_SOURCE`) y `_safe_json`.
- Todo lo listado en B para la parte Python.

---

## Recommendation

**Option B** es la recomendada porque:

- Resuelve la raíz del problema (dos verdades wire/modelo) en lugar de esconderla (A).
  Con A, cada rasgo de v1.0 que queramos usar — `checks`, `action`, template
  `children`, `weight` — requiere un mapeo más; el costo se paga igual, pero diferido
  y disperso.
- Preserva íntegra la capa de presentación que es el diferencial de ai-parrot (bake,
  renderers estáticos, delivery, deep links, recipes) y la re-ancla a mecanismos
  oficiales (`catalogId` mezclable, `metadata.extensions`, `capabilities`), que es
  exactamente lo acordado: dialecto propio **encima** de un wire estándar.
- Toma de C lo valioso sin su costo: vendorizar los schemas oficiales con test de
  drift y validar con `jsonschema` (lazy) contra el catálogo resuelto; pero los
  modelos se escriben a mano (ergonomía, validadores propios) y el runtime
  interactivo sigue en el JS vanilla existente. Adoptar el renderer web oficial queda
  como **opción futura** para `interactive-html` una vez el wire sea v1.0 — B lo
  hace posible, C lo exigía ya.
- Lo que se sacrifica: un cambio amplio y una migración de recetas. Es aceptable
  porque C5 (deserializador compat + `migrate_layout`) acota el riesgo, y porque el
  alcance de acciones se corta en "modelos + Form como composición + deep links",
  dejando el runtime RPC al follow-up `a2ui-agent-functions`.

---

## Feature Description

### User-Facing Behavior

- Un agente en `OutputMode.A2UI` devuelve en `a2ui_envelope` un sobre v1.0
  (`{"version":"v1.0","createSurface":{…}}`) o, cuando hay varios mensajes, una lista
  de sobres (JSONL en stream). Cualquier renderer A2UI v1.0 lo consume; los renderers
  propios además entienden el catálogo parrot.
- Los desarrolladores de tools/agents siguen usando `build_surface/build_chart/…` y
  el `Infographic` toolkit; ahora pueden componer con las 18 primitivas básicas
  (`Tabs`, `List`, `Button`, `TextField`, …) y con `checks`/`action`.
- Formularios: el LLM o una tool emiten `TextField`/`CheckBox`/`ChoicePicker`/
  `DateTimeInput`/`Slider` + `Button{action.event}`; en canales vivos se despacha un
  `action` v1.0; en Slack/Teams/email el botón es un deep link que reanuda la
  conversación con ese mismo `action`.
- Recetas guardadas en dialecto viejo siguen cargando (con `DeprecationWarning`) y
  se pueden migrar con un comando (`parrot a2ui migrate-recipes` o vía
  `AbstractRecipeStore.migrate()`).
- Agent Card A2A anuncia `supportedCatalogIds` y la extensión
  `https://a2ui.org/a2a-extension/a2ui/v1.0`; el `DataPart` lleva
  `mimeType: application/a2ui+json`.

### Internal Behavior

1. **Modelado**: `models.py` define el sobre por clave y `Component` v1.0; `catalog/basic/`
   define las 18 primitivas (modelos + `catalog.json` vendorizado) y `functions.py`
   (evaluador puro). `catalog/parrot/` contiene los 8 componentes propios
   (renombrado `Card`→`InfoCard`) con `lower()` que devuelve `BasicNode`s v1.0.
2. **Catálogo**: `catalog/export.py` produce el `catalog_definition.json` de parrot
   (`$ref` al básico + componentes propios + `instructions`); `validate_envelope`
   resuelve `catalogId` (componente → superficie → error `CatalogValidationError`),
   valida schema (jsonschema lazy, fallback a allowlist), `allowedParents/Children`
   (`UNALLOWED_PARENT/CHILD`), `root` presente, ids únicos, y aplica el gate de
   origen (LLM no puede emitir `action`/`callAgentFunction`).
3. **Producción**: `producer.generate_envelope` pasa `CreateSurface` v1.0 como
   `structured_output` e inyecta `catalog_instructions()`; el retry re-prompt usa los
   códigos de error v1.0.
4. **Serialización**: `serialize` → `{"version":"v1.0", key:{…}}`; `deserialize`
   detecta la clave (v1.0) o `messageType` (legado → `compat.normalize_legacy`).
5. **Bake**: resuelve `path`, evalúa `call` (funciones básicas) y expande template
   `children` con `@index`; marca opcionales via `metadata.extensions.parrot_optional`;
   post-condición: ningún `path`/`call` vivo.
6. **Render**: `RendererCapabilities{supported_catalog_ids, supported_components,…}`;
   cada renderer del satélite mapea las primitivas soportadas y degrada el resto con
   una política explícita y testeada.
7. **Transporte**: handlers (`agent.py`) y A2A (`Artifact.from_a2ui_envelope`) envían
   el sobre tal cual; `deeplink.ResumePayload` envuelve un `action` v1.0.
8. **Recetas**: `LayoutSpec` v2 = componente v1.0 (props top-level + `path`);
   `migrate_layout()`; `SUPPORTED_SCHEMA_VERSION = 2` con lectura de v1.

### Edge Cases & Error Handling

- Sobre con más de una clave de mensaje o sin `version` → `ValidationError` en
  `deserialize`; sobre legado sin `messageType` → error claro, no adivinar.
- Componente sin `catalogId` en superficie sin default → `CatalogValidationError`
  (`code="CATALOG_UNRESOLVED"`).
- `id:"root"` ausente o duplicado; referencia a hijo inexistente → error de
  validación con lista completa (para el retry del productor).
- `Card` legado con `title/subtitle/...` → normalizado a `InfoCard` con warning.
- `updateDataModel` legado `contents:{a:1,b:2}` → N mensajes v1.0 `{path,value}`.
- Binding no resoluble en bake: error salvo que esté en `parrot_optional`.
- `formatString` con función desconocida o `@`-namespace no reservado →
  `INVALID_FUNCTION_CALL`.
- Renderer estático recibe primitiva no soportada → degradación registrada en
  `RenderedArtifact.metadata["degraded"]` (nunca excepción silenciosa).
- Deep link consumido dos veces → `DeepLinkExpiredError` (sin cambios).
- Recetas con `schema_version` desconocida → `RecipeSchemaVersionError` (sin cambios).

---

## Capabilities

### New Capabilities
- `a2ui-v1-wire`: sobre por clave, `version:"v1.0"`, `Component` v1.0, `DataBinding{path}`,
  `FunctionCall`, set completo de mensajes A→R y R→A, serializador + compat legado.
- `a2ui-basic-catalog`: 18 primitivas + 14 funciones en core, `catalog.json` vendorizado,
  evaluador de funciones, `ValidationResult`, códigos de error v1.0.
- `a2ui-catalog-export`: `catalog_definition.json` de parrot, resolución estricta de
  `catalogId`, `allowedParents/Children`, `agent_capabilities`.
- `a2ui-form-composition`: helper `build_form()` sobre primitivas + `Button.action`;
  deep links transportan `action` v1.0.
- `a2ui-recipe-migration`: `LayoutSpec` v2 + `migrate_layout()` + comando de migración.

### Modified Capabilities
- `a2ui-implementation` (FEAT-273): catálogo parrot (`Card`→`InfoCard`, `lower()` v1.0,
  `Form` retirado como componente), bake, `RendererCapabilities`, producer, A2A emit,
  handlers, deep links, 6 renderers del satélite.
- `infographic-theme-catalog-a2ui`: adaptador Infographic remapeado a primitivas nuevas.
- `infographic-recipes` (FEAT-324/326/420): `LayoutSpec` y stores.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/models.py` | modifies (breaking interno) | sobre por clave, `Component` v1.0, bindings `path` |
| `parrot/outputs/a2ui/serialization.py` | modifies | `version="v1.0"`, compat legado |
| `parrot/outputs/a2ui/catalog/{base,__init__}.py` | extends | resolución `catalogId`, jsonschema lazy, `allowed*`, códigos v1.0 |
| `parrot/outputs/a2ui/catalog/basic/` (nuevo) | new | 18 primitivas, 14 funciones, schema vendorizado |
| `parrot/outputs/a2ui/catalog/components/*.py` → `catalog/parrot/` | modifies | `lower()` a primitivas v1.0; `Card`→`InfoCard`; `Form` retirado |
| `parrot/outputs/a2ui/{builders,baking,producer,deeplink}.py` | modifies | forma v1.0; evaluación de `call`; `action` en resume |
| `parrot/outputs/a2ui/adapters/infographic.py` | modifies | remapeo a `Tabs/Divider/List/CheckBox/Image.fit` |
| `parrot/outputs/a2ui/recipes/{models,store}.py` | modifies | `LayoutSpec` v2, `SUPPORTED_SCHEMA_VERSION=2`, migración |
| `parrot/outputs/a2ui/renderers/__init__.py` | extends | `RendererCapabilities` con catálogos/primitivas soportadas |
| `ai-parrot-visualizations/.../a2ui_renderers/*.py` | modifies | 18 primitivas con degradación por renderer |
| `parrot/a2a/models.py:335-433` | modifies | URI/mime v1.0; `agent_capabilities` |
| `ai-parrot-server/.../handlers/{agent,deeplink}.py` | modifies (menor) | sobre v1.0 en `a2ui_envelope`; resume con `action` |
| `ai-parrot-integrations/.../a2ui_resume.py`, telegram/msteams wrappers | modifies (menor) | payload `action` v1.0 |
| `parrot/tools/{infographic,interactive}_toolkit.py`, `infographic_recipes/*` | modifies (menor) | usan builders; sin cambio de API pública |
| `ai-parrot-visualizations/pyproject.toml`, `ai-parrot/pyproject.toml` | extends | extra `jsonschema` opcional; pin de spec vendorizada |
| Tests (~470 funciones A2UI) | modifies | reescritura de fixtures al wire v1.0 + nuevos tests de conformidad contra schemas oficiales |
| `docs/migration/feat-273-a2ui-deprecations.md`, `docs/outputs/*` | extends | guía de migración dialecto→v1.0 |

Breaking: sí para consumidores del `a2ui_envelope` que leían `messageType`/`properties`
(mitigado por la guía y el deserializador compat, que sólo aplica a entrada). Sin
cambio en la API pública de tools/agents (`OutputMode.A2UI`, builders).

---

## Code Context

### User-Provided Code

_Ninguno; el input del usuario fue el diagnóstico `artifacts/a2ui_v1_gap_diagnosis.md`._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py
BINDING_KEY = "$bind"                                                 # line 50
_JSON_POINTER_RE = re.compile(r"^(?:/(?:[^/~\s]|~[01])*)*$")          # line 56
def is_valid_pointer(pointer: str) -> bool: ...                       # line 59
def is_binding_expression(value: Any) -> bool: ...                    # line 79
class Component(BaseModel):                                           # line 123
    model_config = ConfigDict(populate_by_name=True, extra="allow")   # line 138
    id: str; component: str
    properties: dict[str, Any]; children: list[str]
class A2UIMessageBase(BaseModel):                                     # line 157 (extra="forbid")
class CreateSurface(A2UIMessageBase):                                 # line 167
    message_type: Literal["createSurface"] (alias "messageType")
    surface_id: str (alias "surfaceId"); catalog_id: str (alias "catalogId")
    components: list[Component]; data_model: dict (alias "dataModel")
class UpdateComponents(A2UIMessageBase): ...                          # line 183
class UpdateDataModel(A2UIMessageBase): contents: dict[str, Any]      # line 196
class Action(A2UIMessageBase): ...                                    # line 220
class ActionResponse(A2UIMessageBase): ...                            # line 230  (NO existe en spec)
class CallFunction(A2UIMessageBase): ...                              # line 241  (nombre 0.9.1)

# From packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
A2UI_VERSION = "1.0"                                                  # line 38
VERSION_FIELD = "version"                                             # line 41
def serialize(message: A2UIMessageBase) -> dict[str, Any]             # line 48
def deserialize(data: dict[str, Any] | str | bytes) -> A2UIMessageBase # line 64
def to_jsonl(messages) -> str                                          # line 98
def iter_jsonl(text: str) -> Iterator[A2UIMessageBase]                 # line 112

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"                 # line 38
class ProducerOrigin(str, Enum)  # LLM / TOOL                          # line 41
class BasicNode(BaseModel): component: str; properties: dict; children: list["BasicNode"]  # line 53
BasicTree = BasicNode                                                  # line 75
class ComponentDefinition(BaseModel):                                  # line 79
    name: str; catalog_id: str = DEFAULT_CATALOG_ID
    schema_: dict (alias "schema"); instructions: str = ""; requires_actions: bool = False
class RegisteredComponent: definition: ComponentDefinition; component_cls: type  # line 100
class CatalogError / ComponentContractError / CatalogValidationError   # lines 112/116/124

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(...) -> decorator (enforces lower())            # line 57
def unregister_component(name: str) -> None                            # line 105
def get_component(name: str) -> RegisteredComponent                    # line 110
def list_components() -> list[ComponentDefinition]                     # line 119
def catalog_instructions() -> str                                      # line 124
def validate_envelope(envelope: CreateSurface, *, origin: ProducerOrigin = ProducerOrigin.TOOL) -> None  # line 165

# From packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
_RENDERER_NAMESPACE = "parrot.outputs.a2ui_renderers"                  # line 35
class RendererCapabilities(BaseModel):                                 # line 48
    interactive: bool; supports_actions: bool; supports_updates: bool; output: str
class AbstractA2UIRenderer(ABC):                                       # line 65
    capabilities: RendererCapabilities
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str"
def register_a2ui_renderer(name: str, capabilities: RendererCapabilities)  # line 97
def get_a2ui_renderer(name: str) -> type[AbstractA2UIRenderer]         # line 130

# From packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError(Exception)                                             # line 31
_ABSENT = object()                                                     # line 38
def _resolve_value(value: Any, data_model: dict[str, Any]) -> Any      # line 66
def _has_live_binding(value: Any) -> bool                              # line 111
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]     # line 122

# From packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
_DEFAULT_COMPONENT_ID = "blk-000"                                      # line 37
def build_surface(...)  # line 44 ; build_chart 71 ; build_kpicard 91 ; build_card 111
def build_datatable(...) # line 128 ; build_infographic 151

# From packages/ai-parrot/src/parrot/outputs/a2ui/producer.py
DEFAULT_MAX_ATTEMPTS = 3                                               # line 45
class ProducerResult(BaseModel)                                        # line 48
def _extract_envelope(output) -> tuple[Optional[CreateSurface], Optional[str]]  # line 71
def _repair_prompt(base_prompt: str, error_text: str, offending: Any) -> str    # line 91

# From packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py
_KEY_TEMPLATE = "a2ui:deeplink:{token_id}"; _DEFAULT_TTL_SECONDS = 900  # lines 41-42
class ResumePayload(BaseModel)                                         # line 53
class DeepLinkService: __init__(...) line 77; _resume_url(channel, token_id) line 94

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/card.py
@register_component("Card") class CardComponent: SCHEMA = CARD_SCHEMA  # line 34-38
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree  # line 41
    # emits BasicNode(component="Text", properties={"role": ..., "text": ...})
    # and BasicNode(component="Card", properties={"variant": "card", "componentId": ...})

# From packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
CHART_TYPE_MAP (line ~80); _CHART_FALLBACK = "bar" 91; _MAX_NESTING_DEPTH = 4 95; _X_COLUMN = "label" 97
class _Converter: _bind_rows 235; _chart 241; _table 273; _hero_card 301; _timeline 312;
    _progress 329; _card_like 343; _chain 401; _steps 419; _code 437; _card_grid 448;
    walk 468; _flatten_container 538
def infographic_response_to_envelope(...)                              # line 573

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class LayoutSpec(BaseModel): component: str; properties: dict[str, Any]  # line 99 (extra="forbid")
class InfographicRecipe(BaseModel): schema_version: int = 1              # line 175/211
SUPPORTED_SCHEMA_VERSION  (re-exported recipes/__init__.py:36)

# From packages/ai-parrot/src/parrot/a2a/models.py
A2UI_EXTENSION_URI = "https://a2ui.org/extensions/a2a/display/v1"       # line 338
A2UI_MEDIA_TYPE = "application/vnd.a2ui.envelope+json"                  # line 339
def _reject_action_components(envelope: Dict[str, Any]) -> None         # line 342
class Artifact: from_a2ui_envelope(cls, envelope, *, name="a2ui-surface", artifact_id=None)  # line ~375
    # checks envelope.get("messageType") in (None, "createSurface")
    # Part(data=envelope, metadata={"extensionUri": ..., "mediaType": ...})

# From packages/ai-parrot-server/src/parrot/handlers/agent.py
# stream: envelope['a2ui_envelope'] = ai_message.a2ui_envelope        # lines 2701-2705
# non-stream: {"input","output","output_mode":"a2ui","a2ui_envelope"}  # lines 2819-2827

# Satellite renderers (packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/)
class SSRHTMLRenderer(AbstractA2UIRenderer)         # ssr_html.py:59  (_render_basic :129)
class InteractiveHTMLRenderer(AbstractA2UIRenderer) # interactive_html.py:217 (_render_basic :310, _render_chart :333, _render_datatable :387)
class EChartsRenderer(AbstractA2UIRenderer)         # echarts.py:56
class FoliumMapRenderer(AbstractA2UIRenderer)       # folium_map.py:61
class AdaptiveCardsRenderer(AbstractA2UIRenderer)   # adaptive_cards.py:64 (_map_node :120)
class PDFRenderer(AbstractA2UIRenderer)             # pdf.py:99
```

#### Verified Imports
```python
from parrot.outputs.a2ui.models import Component, CreateSurface, A2UIMessageBase   # models.py
from parrot.outputs.a2ui.serialization import serialize, deserialize, A2UI_VERSION   # serialization.py:38-48
from parrot.outputs.a2ui.catalog import register_component, get_component, validate_envelope, catalog_instructions  # catalog/__init__.py
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, ComponentDefinition, ProducerOrigin, DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.renderers import AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer, get_a2ui_renderer
from parrot.outputs.a2ui.baking import bake_envelope, BakeError
from parrot.outputs.a2ui.recipes import SUPPORTED_SCHEMA_VERSION   # recipes/__init__.py:36
from parrot.a2a.models import A2UI_EXTENSION_URI, A2UI_MEDIA_TYPE, Artifact
```

#### Key Attributes & Constants
- `A2UI_VERSION` → `"1.0"` (serialization.py:38) — debe pasar a `"v1.0"`.
- `DEFAULT_CATALOG_ID` → `"https://parrot.dev/catalogs/v1"` (catalog/base.py:38) — se mantiene.
- `Component.model_config.extra` → `"allow"` (models.py:138); `A2UIMessageBase` → `"forbid"`.
- `RendererCapabilities` campos: `interactive, supports_actions, supports_updates, output`.
- Extras satélite: `a2ui = ["jsonpointer>=2.4", …]`, `a2ui-pdf` (+`weasyprint>=68`)
  (ai-parrot-visualizations/pyproject.toml:52-63). Instalados: `jsonpointer 3.1.1`,
  `jsonschema 4.26.0` (transitivo, **no** declarado en `ai-parrot/pyproject.toml`).
- Spec oficial v1.0 (verificada 2026-08-28): `catalogId` básico
  `https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json`; `protocolVersion: "1.0"`;
  `version` const `"v1.0"`; A→R: createSurface, updateComponents, updateDataModel,
  deleteSurface, callRendererFunction, agentFunctionResponse; R→A: action,
  callAgentFunction, rendererFunctionResponse, error; extensión A2A URI
  `https://a2ui.org/a2a-extension/a2ui/v1.0`, mime `application/a2ui+json`;
  `agent_capabilities.json` → `{"v1.0": {"supportedCatalogIds": [...], "acceptsInlineCatalogs": bool}}`.
- Enums básicos: `Text.variant {caption, body}`; `Image.fit {contain, cover, fill, none,
  scaleDown}` (default `fill`), `Image.variant {icon, avatar, smallFeature, mediumFeature,
  largeFeature, header}`; `Row/Column.justify {start, center, end, spaceBetween,
  spaceAround, spaceEvenly, stretch}`, `align {start, center, end, stretch}`;
  `List.direction {vertical, horizontal}`; `Divider.axis`; `Button.variant {default,
  primary, borderless}`; `TextField.variant {shortText, longText, number, obscured}`;
  `ChoicePicker.variant {multipleSelection, mutuallyExclusive}`, `displayStyle {checkbox,
  chips}`; `Tabs.tabs[{title, child}]`; `Modal{trigger, content}`; `Icon.name` (60
  nombres enum | `{svgPath}` | DataBinding); `Slider{value*, max*, min=0, steps}`;
  `DateTimeInput{value, enableDate, enableTime, min, max, label}`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.models.DeleteSurface`~~, ~~`CallRendererFunction`~~,
  ~~`AgentFunctionResponse`~~, ~~`CallAgentFunction`~~, ~~`RendererFunctionResponse`~~,
  ~~`ErrorMessage`~~ — no modelados hoy.
- ~~`parrot.outputs.a2ui.catalog.basic`~~ — paquete inexistente; las primitivas básicas
  sólo existen como strings en `BasicNode.component` dentro de `lower()`.
- ~~`parrot.outputs.a2ui.catalog.export`~~ / ~~`catalog_definition.json`~~ — no hay
  exportación de catálogo.
- ~~`parrot.outputs.a2ui.compat`~~ / ~~`migrate_layout()`~~ — no existen.
- ~~`RendererCapabilities.supported_components`~~ / ~~`supported_catalog_ids`~~ — no existen.
- ~~`InfoCard`~~ — el componente hoy se llama `Card` (`catalog/components/card.py`).
- ~~`build_form()`~~ — no existe; `Form` es un componente registrado (`form.py:60`).
- ~~Componente `id:"root"`~~ — ningún envelope actual lo usa (`grep '"root"'` vacío).
- ~~`parrot/outputs/a2ui/catalog/parrot/`~~ — los componentes propios viven en
  `catalog/components/`.
- ~~`beginRendering`, `surfaceUpdate`, `dataModelUpdate`, `userAction`~~ — nombres
  0.8/0.9 que sólo aparecen en `sdd/proposals/infographic-theme-catalog-a2ui.spec.md`.
- ~~`ai-parrot` core dependiendo de `jsonschema`~~ — no está declarado en su pyproject.
- ~~Paquete JS/TS propio de A2UI~~ — el único runtime cliente es `_BEHAVIOR_JS` inline
  en `interactive_html.py`.
- El evaluador de funciones (`formatString`, `@index`, `required`, …) y `ValidationResult`
  no existen en ningún módulo Python.

---

## Parallelism Assessment

- **Internal parallelism**: media. Tras un primer bloque secuencial (modelos wire v1.0 +
  serialización + compat + `catalog/base` ampliado), se abren tres carriles
  independientes: (1) `catalog/basic/` (primitivas + funciones + schema vendorizado +
  export), (2) catálogo parrot (`lower()` v1.0, `InfoCard`, `build_form`, builders,
  adaptador Infographic, recipes/migración), (3) satélite (6 renderers con degradación,
  `RendererCapabilities`). Un bloque final integra transporte (A2A, handlers, deep links,
  integraciones) y docs.
- **Cross-feature independence**: no hay índices por-spec con tareas pendientes
  (`sdd/tasks/index/*.json` sin `pending`). Archivos compartidos con features recientes
  ya cerradas: `adapters/infographic.py` (infographic-theme-catalog-a2ui),
  `recipes/*` y `tools/infographic_recipes/*` (FEAT-324/326/420),
  `tools/infographic_sections.py` (finance-reporter-tier2-narrative). Cualquier feature
  nueva que toque `outputs/a2ui/` debe esperar a esta.
- **Recommended isolation**: `mixed` — bloque 1 y bloque final en el worktree de la
  feature; carriles (1)/(2)/(3) en worktrees hijos ramificados desde la feature tras el
  bloque 1, con merge de vuelta en orden (1) → (2) → (3).
- **Rationale**: los carriles tocan directorios disjuntos (`catalog/basic/`,
  `catalog/parrot/`+`recipes/`, satélite) y sólo dependen del wire nuevo; forzarlos en
  serie alargaría una feature ya grande. El bloque final debe ser secuencial porque
  cruza tres paquetes del workspace.

---

## Open Questions

- [x] ¿Tipo de flujo y rama base? — *Owner: Jesus Lara*: feature sobre `dev`.
- [x] ¿Compatibilidad hacia atrás? — *Owner: Jesus Lara*: solo lectura + migración; emisión siempre v1.0; sin flag dual.
- [x] ¿Alcance del catálogo básico en renderers? — *Owner: Jesus Lara*: modelos completos en core; render por niveles con degradación declarada por renderer.
- [x] ¿Acciones/RPC en esta feature? — *Owner: Jesus Lara*: modelos + `Form` como composición + deep links con `action` v1.0; runtime `callAgentFunction` en follow-up con spec propio (`a2ui-agent-functions`, generar con `/sdd-spec` inmediatamente después de este brainstorm).
- [x] ¿Identidad de catálogos? — *Owner: Jesus Lara*: `basic` oficial + `parrot` propio; superficie default `parrot`; el catálogo parrot incluye el básico por `$ref`.
- [x] ¿Dónde va la semántica de presentación? — *Owner: Jesus Lara*: `metadata.extensions.parrot_*`.
- [x] ¿Dónde viven modelos/funciones básicas? — *Owner: Jesus Lara*: core `parrot/outputs/a2ui/catalog/basic/`; renderers en `ai-parrot-visualizations`.
- [ ] ¿`jsonschema` como extra opcional de core (`ai-parrot[a2ui-schema]`) o dependencia dura? Hoy está sólo transitivo. — *Owner: Jesus Lara*
- [ ] ¿Se vendoriza la spec oficial (`catalog.json`, `common_types.json`, `agent_to_renderer.json`, `renderer_to_agent.json`) dentro del paquete con pin por SHA y test de drift, o se descarga en CI? — *Owner: Jesus Lara*
- [ ] Nombre definitivo del `Card` propio: `InfoCard` vs `ContentCard` vs `ParrotCard`. — *Owner: Jesus Lara*
- [ ] `catalogId` del catálogo parrot: mantener `https://parrot.dev/catalogs/v1` o adoptar la forma recomendada por la spec `parrot.dev:presentation` (no resoluble). — *Owner: Jesus Lara*
- [ ] Política de degradación por renderer para inputs (`TextField`, `ChoicePicker`, …) en Adaptive Cards: ¿usar `Input.Text`/`Input.ChoiceSet` nativos con `Action.Submit` (requiere runtime de acciones) o sólo texto + deep link en esta feature? — *Owner: Jesus Lara*
- [ ] ¿Se emite `agent_capabilities` en el Agent Card A2A en esta feature o en `a2ui-agent-functions`? — *Owner: Jesus Lara*
- [ ] ¿Comando de migración de recetas como subcomando CLI (`parrot a2ui migrate-recipes`) o sólo método del store? — *Owner: Jesus Lara*
- [ ] Adoptar el renderer web oficial (`@a2ui/lit`) para `interactive-html` en una feature posterior — registrar como idea, verificar nombre/versión del paquete npm. — *Owner: Jesus Lara*
