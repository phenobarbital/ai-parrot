---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Dev-Loop Multiple Dev Agents (Parallel Development Node)

**Date**: 2026-07-21
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: C

---

## Problem Statement

El nodo `development` del flujo dev-loop (`parrot.flows.dev_loop`) despacha
**un único** agente (`sdd-worker` u otro code-agent CLI/LLM) que implementa
todas las tasks del spec **secuencialmente** dentro del worktree creado por
`sdd-research`. Para features con varias tasks independientes, esto
desaprovecha:

1. La capa de dispatchers, que ya soporta dispatches concurrentes
   (semáforos `asyncio.Semaphore` por dispatcher) y 7 backends heterogéneos
   (Claude Code, Codex, Gemini, Nvidia/LLM, Grok, Z.ai, Moonshot).
2. El índice per-spec (`sdd/tasks/index/<feature>.json`) que ya declara
   `depends_on` por task — los datos para planificar paralelismo ya existen
   en disco dentro del worktree.

Afectados: operadores del dev-loop (tiempo de ciclo por feature) y equipos
que quieren mezclar LLMs (p. ej. tasks mecánicas a un modelo barato, tasks
core a Claude).

**Objetivo**: que el nodo dev pueda, vía config, despachar N sub-agentes
(cantidad y LLM por agente configurables), dividir el spec en tasks y
distribuirlas entre los sub-agentes respetando dependencias.

## Constraints & Requirements

- **Back-compat estricta**: sin config de pool, el comportamiento actual
  (un solo `sdd-worker`) debe permanecer byte-idéntico. Fallback en cascada:
  `WorkBrief.dev_agents` → env `DEV_LOOP_DEV_AGENTS` → single-agent.
- **Config por-run**: el pool se define en el `WorkBrief` (contrato de
  entrada del flujo), con el env como fallback de despliegue.
- **Reusar el índice per-spec**: la partición de tasks NO usa un LLM
  planner; se lee `sdd/tasks/index/<feature>.json` (`depends_on`) desde el
  worktree. Cero costo extra de planificación.
- **Aislamiento híbrido configurable**: modo `shared` (olas sobre un
  worktree único) y modo `isolated` (sub-worktrees por agente + merge).
- **Conflictos de merge (modo isolated)**: merge secuencial; ante conflicto
  se lanza un dispatch resolutor con el contexto del conflicto; solo si ese
  dispatch falla el nodo cae al `failure_handler`.
- **Fallos de sub-agente**: la task del agente caído se reasigna UNA vez a
  otro agente del pool; si vuelve a fallar, el nodo completa con lo demás y
  reporta tasks incompletas en `DevelopmentOutput` — QA decide.
- **Streaming**: un stream Redis por sub-agente
  (`flow:{run_id}:dispatch:development.w1`, `.w2`, …). El multiplexor ya
  descubre streams por `SCAN flow:{run_id}:dispatch:*`, así que los
  consumidores no requieren cambios.
- Defensa en profundidad existente intacta: todo `cwd` (incluidos
  sub-worktrees) bajo `conf.WORKTREE_BASE_PATH` (check R4 del dispatcher).
- Async-first, Pydantic v2, sin dependencias nuevas de terceros.

---

## Options Explored

### Option A: Olas por dependencias sobre worktree único (modo `shared` puro)

El nodo dev lee el índice per-spec, agrupa las tasks en "olas" (tasks cuyos
`depends_on` ya están completos), y despacha en paralelo solo las tasks de
la ola actual — todas sobre el MISMO worktree. Cada sub-agente recibe un
brief acotado ("implementa SOLO TASK-NNN"). Entre olas, el nodo espera a que
todos los dispatches terminen (barrera).

✅ **Pros:**
- Sin plumbing de git adicional: un solo worktree, una sola rama, commits
  intercalados.
- Merge trivial (no hay merge): los agentes commitean sobre la misma rama.
- Implementación más corta; el check R4 del dispatcher sirve tal cual.

❌ **Cons:**
- Carreras reales en el working tree: dos agentes con archivos sin commitear
  o `git add` simultáneo corrompen el índice git; exige serializar commits o
  confiar en que las tasks tocan archivos disjuntos (no está garantizado).
- El paralelismo efectivo queda limitado por la estructura de dependencias
  y por la disciplina de archivos de cada task.
- Un agente que rompe el árbol (reset, checkout) afecta a todos.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib `asyncio` | `gather` + barreras por ola | ya en uso |
| stdlib `json` | leer índice per-spec | ya en uso |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` — los 7 dispatchers y sus semáforos
- `sdd/tasks/index/<feature>.json` — grafo de dependencias ya materializado

---

### Option B: Sub-worktrees por agente + merge secuencial (modo `isolated` puro)

Cada sub-agente recibe su propio `git worktree` ramificado de la feature
branch (bajo `WORKTREE_BASE_PATH`), implementa sus tasks asignadas y
commitea aislado. Al terminar cada ola, el nodo hace merge secuencial de las
ramas de los sub-agentes sobre la feature branch; ante conflicto, un
dispatch resolutor (agente del pool con el diff conflictivo como brief) lo
resuelve; si falla, `failure_handler`.

✅ **Pros:**
- Aislamiento git real: cero carreras de índice/working tree entre agentes.
- Máximo paralelismo: no depende de que las tasks toquen archivos disjuntos.
- Un agente descarrilado no contamina el trabajo de los demás.

❌ **Cons:**
- Plumbing de git considerable: crear/destruir sub-worktrees, merges,
  limpieza en errores/timeouts.
- Conflictos de merge son un modo de fallo nuevo que hoy no existe.
- Más disco y latencia de setup por sub-worktree.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `git` CLI vía `asyncio.create_subprocess_exec` | worktree add/remove, merge | patrón ya usado por sdd-research |
| stdlib `asyncio` | gather por ola | ya en uso |

🔗 **Existing Code to Reuse:**
- `dispatcher.py::_enforce_cwd_under_worktree_base` — validar sub-worktrees
- `streaming.py::FlowStreamMultiplexer._discover_dispatch_streams` — auto-descubre sub-streams

---

### Option C: Pool híbrido configurable (`shared` | `isolated`) — A y B tras una config

Un `DevAgentPoolConfig` (en `WorkBrief`, fallback env) declara la lista de
agentes (`agent`, `model`, `count`) y el `isolation_mode`. Un
`TaskScheduler` determinista (sin LLM) lee el índice per-spec y produce olas
de tasks; un `DevAgentPool` mapea cada task a un sub-agente y despacha vía
el dispatcher correspondiente. `isolation_mode="shared"` ejecuta la
estrategia A; `"isolated"` ejecuta la B (sub-worktrees + merge + resolutor).
Reintento de task fallida una vez en otro agente del pool; luego reporte
parcial en `DevelopmentOutput` extendido.

✅ **Pros:**
- Cubre ambos perfiles de uso: features chicas/disjuntas (shared, barato) y
  features grandes (isolated, robusto) sin re-deploy — se decide por-run.
- El scheduler, el pool, el modelo de config, el streaming por sub-agente y
  la semántica de reintento/parcial son comunes a ambos modos: el código
  exclusivo de cada modo se reduce al manejo de worktree/merge.
- Back-compat natural: pool ausente ⇒ camino actual intacto.

❌ **Cons:**
- Mayor superficie a testear (dos modos × fallos × conflictos).
- El modo `shared` conserva el riesgo de carreras de la Opción A (hay que
  documentarlo como "para tasks con archivos disjuntos").

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2` | `DevAgentSpec`, `DevAgentPoolConfig`, outputs por worker | ya en uso |
| `git` CLI vía asyncio subprocess | sub-worktrees + merge (solo modo isolated) | sin dependencia nueva |
| stdlib `asyncio` | gather, barreras, reintentos | ya en uso |

🔗 **Existing Code to Reuse:**
- `nodes/development.py::DevelopmentNode` — punto de extensión único
- `dispatcher.py` — Protocol + 7 dispatchers, semáforos, streams Redis
- `factories.py` / `flow.py` — inyección `development_dispatcher`/`development_profile` ya existente
- `examples/dev_loop/server.py:454-575` — parsing de agentes por env a generalizar

---

### Option D (no convencional): Fan-out delegado al propio Claude Code

No tocar el nodo: un único dispatch `sdd-worker` cuyo subagent-def instruye
usar la herramienta `Agent` de Claude Code para spawnear N subagentes
internos (uno por task) dentro de la misma sesión headless. La "config" de
paralelismo viaja en el prompt.

✅ **Pros:**
- Cero cambios en dispatcher/nodo/modelos; solo el markdown del subagente.
- Claude Code ya maneja la concurrencia interna y el working tree.

❌ **Cons:**
- Solo funciona con el backend Claude Code — Codex/Gemini/Grok/Zai/Moonshot
  quedan fuera (rompe el requisito de heterogeneidad de LLM).
- Sin observabilidad por sub-agente en Redis (todo en un stream).
- Sin control de reintento/aislamiento desde el framework; no configurable
  por-run vía WorkBrief de forma tipada.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | solo edición de `_subagent_data/sdd-worker.md` | |

🔗 **Existing Code to Reuse:**
- `_subagent_defs.py::load_subagent_definition` — carga dual repo/paquete

---

## Recommendation

**Option C** es la recomendada (y la elegida por el usuario en las rondas de
descubrimiento):

- La Opción A sola deja el riesgo de carreras git como única semántica
  disponible; la B sola impone el costo de sub-worktrees incluso para
  features triviales de 2 tasks disjuntas. El híbrido pone esa decisión
  donde pertenece: en la config por-run.
- El costo real del híbrido es acotado porque ~80% del código (config,
  scheduler de olas, pool, streams por worker, reintento, output agregado)
  es común a ambos modos; solo el manejo de worktree/merge es exclusivo del
  modo `isolated`.
- La Opción D se descarta como solución principal por atarse a un solo
  backend, pero queda anotada como atajo válido para despliegues
  Claude-only.
- Tradeoff aceptado: mayor superficie de test (dos modos), mitigado porque
  el modo `shared` documenta explícitamente su precondición (tasks con
  archivos disjuntos) y el default sigue siendo single-agent.

---

## Feature Description

### User-Facing Behavior

- El caller del flujo puede añadir al `WorkBrief` (campo nuevo, opcional)
  un pool de agentes de desarrollo, p. ej.:
  `dev_agents: [{agent: "claude-code", model: "claude-sonnet-4-6", count: 2}, {agent: "zai", model: "glm-5.2"}]`
  y un `dev_isolation: "shared" | "isolated"`.
- Alternativamente, el operador define `DEV_LOOP_DEV_AGENTS` (JSON) y
  `DEV_LOOP_DEV_ISOLATION` en el entorno del servidor como fallback.
- Sin ninguna de las dos configs: comportamiento actual (un `sdd-worker`).
- En la UI/WebSocket, cada sub-agente aparece como un dispatch propio
  (`development.w1`, `development.w2`, …) con sus eventos en vivo — el
  multiplexor los descubre automáticamente.
- El `DevelopmentOutput` final agrega archivos cambiados, commits y summary
  de todos los sub-agentes, más la lista de tasks incompletas (si las hay)
  para que QA y el operador decidan.

### Internal Behavior

1. `DevelopmentNode.execute()` resuelve la config del pool (brief → env →
   single). Con un solo agente efectivo, ejecuta el camino actual sin
   cambios.
2. Con pool: lee `sdd/tasks/index/<feature>.json` desde
   `research.worktree_path` y construye olas de tasks por `depends_on`
   (scheduler determinista, sin LLM).
3. Por cada ola, asigna tasks a sub-agentes (round-robin sobre el pool
   expandido por `count`) y despacha en paralelo (`asyncio.gather`), cada
   dispatch con `node_id="development.wN"` y un brief task-scoped
   ("implementa SOLO TASK-NNN").
4. Modo `shared`: todos los dispatches usan `cwd=worktree_path`.
   Modo `isolated`: antes de cada ola se crean sub-worktrees bajo
   `WORKTREE_BASE_PATH` ramificados de la feature branch; al cerrar la ola
   se mergean secuencialmente a la feature branch; conflicto ⇒ dispatch
   resolutor; fallo del resolutor ⇒ `failure_handler`.
5. Fallo de un dispatch (excepción u output inválido): la task se reintenta
   UNA vez en otro agente del pool; segundo fallo ⇒ task marcada incompleta,
   la ola continúa. Las tasks dependientes de una incompleta se marcan
   `skipped` (no se despachan).
6. Al final, el nodo fusiona los outputs por worker en un
   `DevelopmentOutput` agregado y lo deja en
   `shared["development_output"]` como hoy.

### Edge Cases & Error Handling

- **Índice per-spec ausente/ilegible** en el worktree ⇒ degradar a
  single-agent (log warning) en vez de fallar.
- **Ciclos en `depends_on`** ⇒ error de validación del scheduler ⇒
  `failure_handler` con detalle (nunca deadlock silencioso).
- **Pool con `count` total = 1** ⇒ equivale a single-agent con brief
  task-scoped por ola (sin sub-worktrees en modo isolated).
- **Timeout de un dispatch** ⇒ misma semántica que fallo (reintento → parcial).
- **Conflicto de merge irresoluble** (resolutor falla) ⇒ `failure_handler`
  conservando las ramas de sub-agente para inspección forense.
- **Todas las tasks incompletas** ⇒ el nodo falla (no tiene sentido pasar a QA).
- **Limpieza**: sub-worktrees se eliminan al cerrar el nodo (éxito o fallo
  ya mergeado); en fallo con conflicto se conservan y se reporta la ruta.
- **Cap de concurrencia**: cada dispatcher conserva su semáforo propio; el
  tamaño total del pool se valida contra un cap global configurable.

---

## Capabilities

### New Capabilities
- `dev-loop-multiple-dev-agents`: pool configurable de N sub-agentes de
  desarrollo (backend + modelo por agente) dentro del DevelopmentNode, con
  scheduler de tasks por dependencias, aislamiento híbrido
  (`shared`/`isolated` con sub-worktrees + merge resolutor), reintento en
  pool y output agregado con reporte de tasks incompletas.

### Modified Capabilities
- `dev-loop-orchestration` (`sdd/specs/dev-loop-orchestration.spec.md`):
  el contrato del nodo Development pasa de "un dispatch" a "1..N
  dispatches"; `WorkBrief` y `DevelopmentOutput` se extienden
  (backward-compatible).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/dev_loop/nodes/development.py` | modifies | Orquestación del pool: scheduler, olas, reintentos, agregación. Camino single-agent intacto. |
| `parrot/flows/dev_loop/models.py` | extends | Nuevos `DevAgentSpec`, `DevAgentPoolConfig`; `WorkBrief.dev_agents`/`dev_isolation` (opcionales); `DevelopmentOutput` + campos agregados (`incomplete_tasks`, `worker_summaries`) con defaults back-compat. |
| `parrot/flows/dev_loop/dispatcher.py` | depends on | Sin cambios de contrato: se reusa `DevLoopCodeDispatcher.dispatch()` con `node_id` sintético `development.wN`. |
| `parrot/flows/dev_loop/factories.py` / `flow.py` | extends | Pasar el mapa de dispatchers disponibles (no solo uno) al DevelopmentNode. |
| `examples/dev_loop/server.py` | modifies | Generalizar el bloque `DEV_LOOP_DEVELOPMENT_AGENT` (líneas 454–575) a un builder `agente→dispatcher` reutilizable + parsing de `DEV_LOOP_DEV_AGENTS`. |
| `parrot/flows/dev_loop/streaming.py` | none | `SCAN flow:{run_id}:dispatch:*` ya descubre los sub-streams `development.wN`. |
| `_subagent_data/sdd-worker.md` (+ `.claude/agents/`) | extends | Instrucción task-scoped: "si el brief trae `task_id`, implementa SOLO esa task". |
| Redis / infra | none | Mismas primitivas de stream; más claves por run. |

Sin dependencias externas nuevas. Sin breaking changes de API.

---

## Code Context

### User-Provided Code

(El usuario no aportó snippets; aportó la hipótesis de diseño: despachar
vía config varios agentes definiendo cantidad y LLM, dividir el spec en
tasks y distribuirlas entre sub-agentes dentro del nodo dev. Verificada
como factible contra el código abajo.)

### Verified Codebase References

Nota: rutas relativas a `packages/ai-parrot/src/` salvo indicación.

#### Classes & Signatures
```python
# From parrot/flows/dev_loop/nodes/development.py:30
class DevelopmentNode(DevLoopNode):
    def __init__(self, *, dispatcher: DevLoopCodeDispatcher,
                 dispatch_profile: Optional[Any] = None,
                 name: str = "development") -> None: ...  # line 33
    async def execute(self, ctx, deps=None, **kwargs) -> DevelopmentOutput:  # line 48
        # shared["research_output"] -> ResearchOutput (line 68)
        # default profile: subagent="sdd-worker", permission_mode="acceptEdits" (lines 70-82)
        # single dispatch: cwd=research.worktree_path, node_id=self.name (lines 84-91)

# From parrot/flows/dev_loop/dispatcher.py:129
class DevLoopCodeDispatcher(Protocol):
    async def dispatch(self, *, brief: BaseModel, profile: BaseModel,
                       output_model: Type[T], run_id: str,
                       node_id: str, cwd: str) -> T: ...  # line 132

# From parrot/flows/dev_loop/dispatcher.py:150
class ClaudeCodeDispatcher:
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...  # line 157
    # self._semaphore = asyncio.Semaphore(max_concurrent)  # line 180
    async def dispatch(...) -> T:  # line 189
        # stream_key = f"flow:{run_id}:dispatch:{node_id}"  # line 222
        # self._enforce_cwd_under_worktree_base(cwd, profile)  # line 228
        # async with self._semaphore:  # line 238
# Dispatchers homólogos en el mismo módulo: CodexCodeDispatcher (dispatch línea 896),
# GeminiCodeDispatcher, LLMCodeDispatcher, GrokCodeDispatcher, ZaiCodeDispatcher,
# MoonshotCodeDispatcher — cada uno con su propio Semaphore (líneas 890/1306/1746).

# From parrot/flows/dev_loop/models.py:381
class ClaudeCodeDispatchProfile(BaseModel):
    subagent: Optional[Literal["sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"]] = "sdd-worker"  # line 389
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"  # line 392
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)  # line 407
    model: str = "claude-sonnet-4-6"  # line 408

# From parrot/flows/dev_loop/models.py:118
class WorkBrief(BaseModel):
    kind: WorkKind = Field(default="bug")            # line 131
    summary: str                                     # line 141 (10..255)
    description: str = ""                            # line 150
    affected_component: str                          # line 158
    log_sources: List[LogSource]                     # line 159
    acceptance_criteria: List[AcceptanceCriterion]   # line 160 (min_length=1)
    escalation_assignee: str                         # line 161

# From parrot/flows/dev_loop/models.py:273
class ResearchOutput(BaseModel):
    jira_issue_key: str       # line 288
    spec_path: str            # line 293
    feat_id: str              # line 298
    branch_name: str          # line 303
    worktree_path: str        # line 308  (UN solo worktree)
    repo_path: str = ""       # line 313  (fallback: worktree_path)
    log_excerpts: List[str]   # line 323

# From parrot/flows/dev_loop/models.py:329
class DevelopmentOutput(BaseModel):
    files_changed: List[str]  # line 332
    commit_shas: List[str]    # line 333
    summary: str              # line 334

# From parrot/flows/dev_loop/models.py:698
class DispatchEvent(BaseModel):
    kind: Literal["dispatch.queued", "dispatch.started", "dispatch.message",
                  "dispatch.tool_use", "dispatch.tool_result",
                  "dispatch.output_invalid", "dispatch.failed",
                  "dispatch.completed"]  # line 707
    ts: float; run_id: str  # lines 717-718

# From parrot/flows/dev_loop/streaming.py:90
class FlowStreamMultiplexer:
    # self._dispatch_prefix = f"flow:{run_id}:dispatch:"  # line 81
    async def _discover_dispatch_streams(self) -> List[str]:  # line 90
        # SCAN cursor-based sobre flow:{run_id}:dispatch:*  (lines 93-110)
```

#### Verified Imports
```python
# Confirmados en parrot/flows/dev_loop/nodes/development.py:18-26:
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatcher import DevLoopCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile, DevelopmentOutput, ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
```

#### Key Attributes & Constants
- `build_dev_loop_node_factories(..., development_dispatcher=None, development_profile=None)` — inyección ya existente (parrot/flows/dev_loop/factories.py:45-46; fallback al dispatcher global en línea 77; factory registrada como `"dev_loop.development"` en línea 141)
- `build_dev_loop_flow(..., development_dispatcher=None, development_profile=None)` (parrot/flows/dev_loop/flow.py:168-169); edges `research → development → qa` (flow.py:285-286)
- Selección de agente por env `DEV_LOOP_DEVELOPMENT_AGENT` ∈ {claude-code, codex, gemini, nvidia/llm, grok, zai, moonshot} — `examples/dev_loop/server.py:461-575` (ruta desde raíz del repo)
- `_VALID_NAMES = {"sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"}` (parrot/flows/dev_loop/_subagent_defs.py:33)
- Índice per-spec: `sdd/tasks/index/<feature>.json` con `tasks[].depends_on` (esquema FEAT-145, documentado en CLAUDE.md)
- `conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES` — cap del semáforo del dispatcher Claude
- `conf.WORKTREE_BASE_PATH` — raíz obligatoria de todo `cwd` de dispatch (check R4)

### Does NOT Exist (Anti-Hallucination)
- ~~`WorkBrief.dev_agents` / `WorkBrief.dev_isolation`~~ — no existen; son los campos a crear
- ~~`ResearchOutput.tasks`~~ — el output de research NO transporta la lista de tasks; hay que leer el índice per-spec desde el worktree
- ~~`DevAgentSpec` / `DevAgentPoolConfig` / `TaskScheduler` / `DevAgentPool`~~ — no existen en `parrot.flows.dev_loop`; nombres propuestos
- ~~env `DEV_LOOP_DEV_AGENTS` / `DEV_LOOP_DEV_ISOLATION`~~ — no existen todavía
- ~~`DispatchEvent.worker_id`~~ — no existe (y no hace falta con streams por sub-agente)
- ~~clase `DevLoopConfig`~~ — `config.py` solo contiene `parse_repo_specs()`
- ~~soporte multi-dispatch o multi-worktree en `DevelopmentNode`~~ — hoy es estrictamente 1 dispatch / 1 worktree
- ~~nodo o dispatcher de resolución de merges~~ — no existe; el resolutor es un dispatch más del pool a crear

---

## Parallelism Assessment

- **Internal parallelism**: Media. Los modelos Pydantic + scheduler
  determinista son separables del rework del `DevelopmentNode`, pero el nodo,
  el pool y el manejo de worktrees están fuertemente acoplados entre sí y al
  mismo archivo — conviene secuencial.
- **Cross-feature independence**: Toca `parrot/flows/dev_loop/*` (models,
  development node, factories, flow, server de ejemplo). Conflicto potencial
  con cualquier spec in-flight sobre dev-loop (p. ej. futuras iteraciones de
  FEAT-270 code-review multi-dispatcher si reabren `models.py`/`flow.py`).
- **Recommended isolation**: `per-spec` (un solo worktree, tasks secuenciales).
- **Rationale**: casi todas las tasks editan `models.py`,
  `nodes/development.py` y `flow.py`/`factories.py`; particionar en worktrees
  generaría los mismos conflictos de merge que esta feature intenta gestionar.

---

## Open Questions

- [x] ¿Tipo de flujo/base? — *Owner: Jesus Lara*: feature → dev.
- [x] ¿Estrategia de aislamiento? — *Owner: Jesus Lara*: híbrido configurable (`shared` olas / `isolated` sub-worktrees), decidido por config por-run.
- [x] ¿Dónde se define el pool? — *Owner: Jesus Lara*: en el `WorkBrief` por-run, con fallback a env `DEV_LOOP_DEV_AGENTS` y luego single-agent (back-compat exacta).
- [x] ¿Quién divide el spec en tasks? — *Owner: Jesus Lara*: se reusa el índice per-spec de sdd-research (`depends_on`); sin planner LLM.
- [x] ¿Conflictos de merge en modo isolated? — *Owner: Jesus Lara*: merge secuencial + dispatch resolutor; si el resolutor falla → failure_handler.
- [x] ¿Semántica ante fallo de un sub-agente? — *Owner: Jesus Lara*: un reintento en otro agente del pool; luego completar parcial y reportar tasks incompletas (QA decide).
- [x] ¿Streaming? — *Owner: Jesus Lara*: stream Redis por sub-agente (`development.wN`); el multiplexor los descubre vía SCAN sin cambios.
- [ ] Cap agregado de concurrencia del pool: cada dispatcher tiene semáforo propio — ¿se añade un cap global (p. ej. `DEV_LOOP_DEV_POOL_MAX`) que limite el `count` total efectivo? — *Owner: Jesus Lara*
- [ ] ¿El dispatch resolutor de conflictos usa un backend fijo (claude-code) o el primer agente del pool? — *Owner: Jesus Lara*
- [x] Task-scoped prompting del `sdd-worker`: ¿brief extendido o variante de subagente? — *Owner: Jesus Lara*: brief extendido con `task_id` + instrucción condicional en el `sdd-worker.md` existente ("si el brief trae `task_id`, implementa SOLO esa task"). Sin nombres nuevos en `_VALID_NAMES` ni cambios al `Literal` de `ClaudeCodeDispatchProfile.subagent`; funciona en todos los backends porque Codex/Gemini/LLM cargan el mismo prompt body vía `load_subagent_definition`. Cambio: 1 markdown dual-sourced (`.claude/agents/sdd-worker.md` + `_subagent_data/sdd-worker.md`) + 1 campo opcional en el modelo del brief.
- [ ] Forma exacta de reporte parcial en `DevelopmentOutput` (`incomplete_tasks: list[str]` + `worker_summaries`) y cómo la consume QA para decidir — *Owner: Jesus Lara*
