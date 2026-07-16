---
type: Wiki Overview
title: 'Brainstorm: ScrapingFlow, FlowExecutor & TemplatePlan — scraping componible
  de horizonte largo'
id: doc:sdd-proposals-scrapingflow-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'El `WebScrapingToolkit` resuelve hoy una unidad de trabajo: un `ScrapingPlan`
  (JSON declarativo) que se ejecuta sobre una sola página y se cachea por URL en el
  `PlanRegistry`. Esto cubre extracción estructurada repetible y barata, pero tres
  necesidades quedan fuera:'
relates_to:
- concept: mod:parrot_tools.scraping
  rel: mentions
- concept: mod:parrot_tools.scraping.crawler
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers
  rel: mentions
- concept: mod:parrot_tools.scraping.executor
  rel: mentions
- concept: mod:parrot_tools.scraping.plan
  rel: mentions
- concept: mod:parrot_tools.scraping.registry
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: ScrapingFlow, FlowExecutor & TemplatePlan — scraping componible de horizonte largo

**Date**: 2026-06-03
**Author**: <author>
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

El `WebScrapingToolkit` resuelve hoy una unidad de trabajo: un `ScrapingPlan` (JSON declarativo) que se ejecuta sobre una sola página y se cachea por URL en el `PlanRegistry`. Esto cubre extracción estructurada repetible y barata, pero tres necesidades quedan fuera:

1. **Reutilización parametrizada.** Un plan está atado a una URL concreta vía su `fingerprint`. "Mismo flujo, distintos argumentos" (fechas, origen/destino, filtros de búsqueda) hoy implica regenerar o duplicar planes. No existe la noción de plantilla.
2. **Composición de flujos largos.** Tareas de horizonte largo (login multi-paso → listado → detalle por cada item → checkout) no se modelan como una secuencia de planes conectados que se pasan datos entre sí. El `CrawlEngine` cubre el caso "seguir links homogéneos", pero no un grafo heterogéneo de etapas distintas.
3. **Operación multi-ventana con sesión.** No hay un modelo explícito de sesión/`BrowserContext` compartido entre etapas, que es justo lo que distingue un flujo autenticado largo de N scrapes independientes.

El estudio comparativo con `microsoft/Webwright` (agente "code-as-action" que trata el navegador como recurso desechable y el código como artefacto persistente) confirmó que nuestro modelo declarativo es superior para extracción repetible a escala, y que la pieza que nos falta para igualarlo en horizonte largo es **composición explícita + estado de sesión**, no reescribir el motor como generador de código.

## Constraints & Requirements

- No modificar `ScrapingPlan` como value object: sigue siendo inmutable y con `fingerprint` derivado de URL. La parametrización se construye **por encima**, no dentro.
- El `ScrapingFlow` se ejecuta **dentro** del motor (sobre `execute_plan_steps`); no se delega su orquestación a agentes externos en este alcance.
- El paso de datos entre etapas debe ser independiente del navegador (valores Python), de modo que un dato pueda cruzar de una sesión a otra.
- Reanudabilidad: un fallo en la etapa N de M no debe forzar reiniciar desde 0.
- Multi-ventana real: varias `Page` dentro de un mismo `BrowserContext` para sesiones compartidas; contexts distintos para sesiones aisladas.
- Reutilizar la maquinaria existente (`execute_plan_steps`, `ACTION_MAP`/`ScrapingStep`, cola y concurrencia de `CrawlEngine`, `PlanRegistry`) en lugar de duplicarla.
- Mantener `scrape()` de plan único driver-agnóstico (`AbstractDriver`); el `ScrapingFlow` puede ser Playwright-first por el modelo de contexto.

---

## Options Explored

### Option A: Modelo declarativo en capas (TemplatePlan → ScrapingFlow → FlowExecutor)

Tres capas ortogonales construidas sobre lo que ya existe:

- **`TemplatePlan`**: plantilla con `ParamSpec` tipados que produce `ScrapingPlan`s concretos vía `bind(**kwargs)`. Sigue el patrón ya presente en `ExtractionPlan.to_scraping_plan()` ("plan rico → plan ejecutable por traducción").
- **`ScrapingFlow`**: DAG de `FlowNode`s. Las aristas son **dependencias de datos** (`inputs`: `param <- "node_id.field"`). Cada nodo declara además una etiqueta `session` (afinidad de `BrowserContext`). Orden de ejecución y afinidad de sesión son dos grafos separados.
- **`FlowExecutor`**: capa fina sobre `execute_plan_steps`. Resuelve orden topológico, abre/cierra `BrowserContext` por sesión (lazy open, cierre por último-uso precomputado), hace `bind` de inputs, ejecuta cada nodo en una `Page` nueva, y persiste el `ExtractionResult` de cada nodo como checkpoint.

✅ **Pros:**
- Reutiliza el motor de ejecución autoritativo: una sola fuente de verdad.
- Composición y estado de sesión **explícitos** y validables (DAG de datos + etiquetas de sesión).
- Mantiene el coste bajo del modelo cacheado; el LLM no entra en el loop de ejecución.
- Encaja con la jerarquía nativa de Playwright (`BrowserContext`/`Page`).
- Reanudable por checkpoint de nodo (lección "run-artifact first" de Webwright).

❌ **Cons:**
- El `FlowExecutor` concentra complejidad real: ciclo de vida de contexts, fan-out, threading de datos.
- Fan-out concurrente sobre sesión autenticada compartida puede dar carreras (deuda diferida).

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `playwright` | `BrowserContext`/`Page` para multi-ventana y sesión | ya en uso (`PlaywrightDriver`) |
| `pydantic` v2 | modelos `TemplatePlan`, `ScrapingFlow`, `FlowNode`, `ParamSpec` | coherente con `ScrapingPlan`/`ExtractionPlan` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py::execute_plan_steps` — motor de ejecución por nodo.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py::ExtractionPlan.to_scraping_plan` — patrón de traducción a imitar en `TemplatePlan.bind`.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py` — `ACTION_MAP`, `ScrapingStep.from_dict`, convención `{{index}}`/`do_replace` del `Loop`.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py::CrawlEngine` — cola + concurrencia reutilizable para fan-out.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/registry.py::PlanRegistry` — base para almacenar plantillas/flows y checkpoints.

---

### Option B: Enfoque "code-as-action" estilo Webwright

Abandonar el plan declarativo para flujos largos y dejar que un LLM escriba/ejecute código Playwright en un loop, con el workspace (código + logs + screenshots) como estado persistente.

✅ **Pros:**
- Máxima robustez ante páginas dinámicas (lazy-load, re-render) sin selectores frágiles.
- SOTA demostrado en tareas de horizonte largo.

❌ **Cons:**
- LLM en cada paso → coste alto por ejecución; pierde la ventaja del plan cacheado.
- Dos runtimes a mantener; resultados no deterministas entre corridas.
- Tira por la borda la disciplina de selectores anclados al DOM verificado, que es nuestra mayor fortaleza.
- No aporta composición explícita: la deja implícita en código generado.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `playwright` | ejecución del código generado | — |
| (LLM backend) | generación/depuración en loop | coste recurrente por corrida |

🔗 **Existing Code to Reuse:**
- Poco; sería un subsistema paralelo. Reservar la idea como "agentic fallback" futuro cuando un `ScrapingPlan` falla N veces.

---

### Option C: Extensión mínima (parámetros + secuencia plana)

Añadir parametrización simple a `ScrapingPlan` y un runner secuencial sin DAG ni modelo de sesión.

✅ **Pros:**
- Esfuerzo bajo; entrega rápida de la parte de parametrización.

❌ **Cons:**
- No cumple el requisito de multi-ventana/sesión compartida.
- Secuencia plana no modela fan-out (1 listado → N detalles) ni dependencias de datos.
- Probablemente habría que rehacerlo para llegar a la Opción A.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | parámetros en el plan | — |

🔗 **Existing Code to Reuse:**
- `executor.py::execute_plan_steps` en bucle simple.

---

## Recommendation

**Option A** se recomienda porque es la única que satisface a la vez los tres requisitos (parametrización, composición, multi-ventana con sesión) reutilizando el motor de ejecución existente como fuente única de verdad. Conserva la ventaja de coste y determinismo del modelo declarativo cacheado —nuestra diferencia real frente a Webwright— y añade exactamente lo que faltaba: composición y estado de sesión explícitos.

Tradeoffs aceptados conscientemente: el `FlowExecutor` concentra complejidad (ciclo de vida de contexts, fan-out, threading de datos), y el fan-out concurrente sobre sesión autenticada queda como deuda conocida. La Opción B se reserva como posible "agentic fallback" en un spec futuro, no como base. La Opción C se descarta porque no llega a multi-ventana y casi con seguridad habría que rehacerla.

---

## Feature Description

### User-Facing Behavior

El usuario (o un agente que entienda el toolkit) puede:

1. **Definir un `TemplatePlan`**: un plan con huecos parametrizables (`{{origin}}`, `{{date}}`, …) y una lista de `ParamSpec` tipados (nombre, tipo, required, default, choices). `template.bind(origin="SEA", date="2026-05-15")` devuelve un `ScrapingPlan` concreto y ejecutable.
2. **Componer un `ScrapingFlow`**: declarar nodos que referencian plantillas/planes del registry, conectados por dependencias de datos (`inputs: {url: "listing.product_url"}`) y agrupados por etiqueta `session`.
3. **Ejecutar el flow dentro del motor**: `FlowExecutor.run(flow, params)` orquesta todo y devuelve un `FlowResult` agregado, reanudando desde el último checkpoint si una corrida previa falló.

### Internal Behavior

- `TemplatePlan.bind` valida los kwargs contra los `ParamSpec`, rellena `url_template`/`objective_template` y renderiza los huecos `{{param}}` recorriendo solo los valores string de los steps (reutilizando la convención de doble llave del `Loop`, no `str.format`, para no romper con selectores CSS o JSON embebido).
- `FlowExecutor` calcula el **orden topológico** a partir del grafo de `inputs` (no del de sesiones). Para cada nodo: obtiene/crea el `BrowserContext` de su `session` (lazy), abre una `Page` nueva, envuelve la `Page` en un `AbstractDriver`, hace `bind` resolviendo `inputs` desde los outputs ya disponibles, ejecuta vía `execute_plan_steps`, y persiste el `ExtractionResult` como checkpoint.
- Cierre de contexts **determinista por último-uso**: como todas las etiquetas de sesión se conocen por adelantado (declaradas, no inferidas), se precomputa `last_use[session]` en el mismo paso topológico y se cierra cada context justo tras su último nodo.
- **Fan-out**: un nodo cuyo output es una lista mapea a N ejecuciones del nodo dependiente; se reutiliza la cola/concurrencia de `CrawlEngine` en vez de reimplementarla.

### Edge Cases & Error Handling

- **Refs colgantes / ciclos** en `inputs`: se validan al cargar el flow, antes de ejecutar.
- **Fingerprint de plantillas**: `bind()` debe incorporar los valores de parámetros al fingerprint (p.ej. `template_name + param_hash`) para que dos binds de la misma URL base no colisionen en el registry.
- **`on_error` por nodo**: `abort` | `skip` | `retry`.
- **Cruce de sesión legítimo**: un dato (p.ej. URL) extraído en `session="auth"` puede consumirse en un nodo `session="clean"` sin compartir cookies, porque data-flow y context son ejes independientes.
- **Context huérfano**: el cierre por último-uso evita dejar `BrowserContext` colgando o cerrarlos antes de tiempo.
- **Fan-out concurrente sobre sesión autenticada compartida**: riesgo de carrera si varias `Page` escriben estado de sesión a la vez. Diferido; seguro en modo secuencial.

---

## Capabilities

### New Capabilities
- `template-plan`: plantilla parametrizada (`ParamSpec` + `bind()`) que produce `ScrapingPlan`s concretos. Maps to `docs/sdd/specs/template-plan.spec.md`.
- `scraping-flow`: modelo de datos del DAG de etapas (DAG de datos por `inputs` + afinidad de `session`), con validación de refs/ciclos. Maps to `docs/sdd/specs/scraping-flow.spec.md`.
- `flow-executor`: ejecución in-engine del flow sobre `execute_plan_steps`, con ciclo de vida de `BrowserContext` por sesión, fan-out y checkpoint por nodo. Maps to `docs/sdd/specs/flow-executor.spec.md`.

### Modified Capabilities
- `plan-registry` (`PlanRegistry`): extender para almacenar `TemplatePlan`/`ScrapingFlow` y los checkpoints de ejecución, con clave que distinga `template_name + param_hash`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_tools.scraping.executor.execute_plan_steps` | depends on | el `FlowExecutor` lo invoca por nodo; sin cambios de firma esperados |
| `parrot_tools.scraping.registry.PlanRegistry` | modifies | almacenar plantillas, flows y checkpoints; nueva estrategia de clave |
| `parrot_tools.scraping.crawler.CrawlEngine` | depends on | reutilizar cola/concurrencia para fan-out |
| `parrot_tools.scraping.drivers.PlaywrightDriver` | depends on | `ScrapingFlow` es Playwright-first (contexts/multi-page) |
| `parrot_tools.scraping.plan.ScrapingPlan` | depends on | NO se modifica; `TemplatePlan.bind` lo produce |
| `parrot_tools.scraping.__init__` | extends | exportar nuevos símbolos públicos |

**Fuera de alcance (spec futuro):** emisión de código Playwright portable (contexto AgentCrew: un agente genera el ejecutable que consume otro) y exposición del DSL vía tool/MCP server. Ambos consumen el mismo runtime autoritativo, pero introducen un segundo camino de ejecución que requiere su propio conformance harness y semántica de job asíncrono.

---

## Code Context

> ⚠️ Las firmas y rutas siguientes se confirmaron por búsqueda en el codebase. **Los números de línea NO están verificados** y deben confirmarse en tiempo de implementación (la búsqueda no los expone). No asumir líneas concretas.

### User-Provided Code

```python
# Source: user-provided (boceto de diseño en el brainstorm)
class ParamSpec(BaseModel):
    name: str
    type: Literal["string", "int", "date", "enum", "url"] = "string"
    required: bool = True
    default: Optional[Any] = None
    choices: Optional[List[Any]] = None
    description: str = ""

class PlanTemplate(BaseModel):  # nombre tentativo: TemplatePlan
    name: str
    objective_template: str
    url_template: str
    params: List[ParamSpec]
    steps_template: List[Dict[str, Any]]
    selectors: Optional[List[Dict[str, Any]]] = None
    def bind(self, **kwargs) -> "ScrapingPlan": ...

class FlowNode(BaseModel):
    id: str
    plan_ref: str
    inputs: Dict[str, str] = {}          # param <- "node_id.path.field"
    session: str = "default"             # misma 'session' => mismo BrowserContext
    on_error: Literal["abort", "skip", "retry"] = "abort"

class ScrapingFlow(BaseModel):
    name: str
    nodes: List[FlowNode]

# Boceto del cierre determinista por último-uso (FlowExecutor)
last_use = {}
for node in topo_order:
    last_use[node.session] = node.id
# tras procesar cada nodo:
#   if last_use[node.session] == node.id:
#       await contexts[node.session].close(); del contexts[node.session]
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py  (line: TBD)
class ScrapingPlan(BaseModel):
    name: Optional[str] = None
    version: str = "1.0"
    tags: List[str]
    url: str
    domain: str = ""
    objective: str
    steps: List[Dict[str, Any]]
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None
    follow_selector: Optional[str] = None
    follow_pattern: Optional[str] = None
    max_depth: Optional[int] = None
    source: str = "llm"
    fingerprint: str = ""
    @computed_field
    @property
    def normalized_url(self) -> str: ...
    def model_post_init(self, __context: Any) -> None: ...
# helpers en el mismo módulo: _normalize_url, _compute_fingerprint, _sanitize_domain

# From packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py  (line: TBD)
class ExtractionPlan(BaseModel):
    def to_scraping_plan(self) -> ScrapingPlan: ...   # patrón a imitar en bind()
class ExtractedEntity(BaseModel):
    entity_type: str
    fields: Dict[str, Any]
    source_url: str
    confidence: float
    raw_text: Optional[str] = None
    rag_text: str = ""

# From packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py  (line: TBD)
async def execute_plan_steps(
    driver: AbstractDriver,
    plan: Optional[ScrapingPlan] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    selectors: Optional[List[Dict[str, Any]]] = None,
    config: Optional[DriverConfig] = None,
    base_url: Optional[str] = None,
) -> ScrapingResult: ...

# From packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py  (line: TBD)
class CrawlEngine:
    def __init__(self, scrape_fn, strategy=None, follow_selector="a[href]",
                 follow_pattern=None, allow_external=False, concurrency=1, logger=None): ...
    async def run(self, start_url: str, plan: Any, depth: int = 1,
                  max_pages: Optional[int] = None) -> CrawlResult: ...

# From packages/ai-parrot-tools/src/parrot_tools/scraping/models.py  (line: TBD)
ACTION_MAP: dict[str, type]          # "navigate", "click", "loop", ...
class ScrapingStep:                  # dataclass
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScrapingStep": ...
    def to_dict(self) -> Dict[str, Any]: ...
# Loop usa convención {{index}}/{{index_1}} con flag do_replace
```

#### Verified Imports
```python
# Confirmados desde packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py
from parrot_tools.scraping import (
    WebScrapingToolkit, ScrapingPlan, PlanRegistry,
    CrawlEngine, BFSStrategy, DFSStrategy, CrawlStrategy,
    ExtractionPlan, ExtractedEntity, ExtractionResult,
    DriverFactory, AbstractDriver, PlaywrightDriver, SeleniumDriver,
)
# execute_plan_steps vive en .executor (no re-exportado en __init__ según lo visto)
from parrot_tools.scraping.executor import execute_plan_steps
```

#### Key Attributes & Constants
- `ScrapingPlan.fingerprint` → `str` (derivado de URL normalizada; relevante para la clave de plantillas).
- `ScrapingPlan.follow_selector` / `follow_pattern` → hints reenviados a `CrawlEngine`.
- `ExtractedEntity.fields` → `Dict[str, Any]` (origen del resolver tipo JSONPath-lite para `inputs`).
- `CrawlEngine.__init__(concurrency=...)` → reutilizable para fan-out.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.scraping.TemplatePlan` / `PlanTemplate`~~ — a crear.
- ~~`parrot_tools.scraping.ScrapingFlow` / `FlowNode` / `ParamSpec`~~ — a crear.
- ~~`parrot_tools.scraping.FlowExecutor`~~ — a crear.
- ~~`ScrapingPlan.bind()` / `ScrapingPlan.params`~~ — no existe; la parametrización va en `TemplatePlan`, no en `ScrapingPlan`.
- ~~emisor de código Playwright / MCP server~~ — no existe; fuera de alcance (spec futuro).
- ~~`PlanRegistry` con clave por `param_hash`~~ — la clave actual es por URL/fingerprint; la extensión es parte de este trabajo.

---

## Parallelism Assessment

- **Internal parallelism**: parcial. `template-plan` y el **modelo de datos** de `scraping-flow` pueden especificarse/desarrollarse en paralelo (no comparten archivos). `flow-executor` depende de ambos (necesita `TemplatePlan.bind()` para resolver `inputs` y el modelo de `ScrapingFlow`), así que va después. Orden duro: parametrización → modelo de flow → executor.
- **Cross-feature independence**: bajo riesgo de conflicto. `ScrapingPlan` NO se toca (se construye por encima), lo que evita choques en el value object más compartido. El punto de contacto compartido es `PlanRegistry` (lo modifican `template-plan` y `flow-executor`) y el `__init__` de exports.
- **Recommended isolation**: mixed — worktree propio para `flow-executor` (concentra la complejidad y depende de los otros dos); `template-plan` y el modelo de `scraping-flow` pueden compartir o ir separados, coordinando solo los cambios en `PlanRegistry`/`__init__`.
- **Rationale**: la dependencia es lineal en la capa de ejecución pero los modelos de datos son independientes; aislar el executor evita que su complejidad bloquee el avance de las capas inferiores.

---

## Open Questions

- [x] ¿La parametrización la **infiere un LLM** a partir de un `ScrapingPlan` concreto ya validado ("generaliza este plan a plantilla"), o el plan **nace parametrizado** desde el `PlanGenerator`? Cambia el diseño del generador. — *Owner: <author>*: Ambos.
- [x] Estrategia exacta de **fingerprint/clave de registry** para plantillas (`template_name + param_hash`): ¿qué entra en el hash y cómo se versiona? — *Owner: <author>*: suggestion.
- [x] **Sintaxis de placeholders**: confirmar reutilización de `{{param}}` (convención del `Loop`) y el alcance del renderizado (solo valores string de steps + `url_template`/`objective_template`). — *Owner: <author>*: confirmado.
- [x] **Almacenamiento de checkpoints**: ¿reutilizar `PlanRegistry` o un store de ejecuciones separado? Define la API de reanudación. — *Owner: <author>*: reutilizar PlanRegistry.
- [ ] **Resolver de `inputs`** (`"node_id.path.field"`): definir la mini-gramática de acceso sobre `ExtractedEntity.fields` (índices de lista, anidamiento). — *Owner: <author>*
- [x] **Afinidad de sesión**: explícita vía campo `session` por nodo, no inferida de dependencias de datos. — *Owner: <author>*: resuelve el caso "B usa URL de A pero en sesión limpia" como `session="clean"`; data-flow y `BrowserContext` quedan como ejes ortogonales.
- [x] **Quién ejecuta el flow**: dentro del motor (`FlowExecutor` sobre `execute_plan_steps`), no orquestado por agentes externos en este alcance. — *Owner: <author>*: la exportación a artefacto Playwright / MCP se difiere a spec futuro.
- [x] **Driver del flow**: Playwright-first por el modelo `BrowserContext`/`Page`; `scrape()` de plan único sigue driver-agnóstico. — *Owner: <author>*: no forzar Selenium en el `ScrapingFlow`.
- [ ] **Deuda diferida (no resolver ahora)**: fan-out concurrente sobre una misma sesión autenticada — varias `Page` concurrentes compartiendo cookies pueden producir carreras al escribir estado de sesión. Seguro en secuencial; revisar al subir `concurrency`. — *Owner: <author>*
