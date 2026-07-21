---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Dev-Loop Multiple Dev Agents (Parallel Development Node)

**Feature ID**: FEAT-323
**Date**: 2026-07-21
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.26.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

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

### Goals

- El nodo dev puede, vía config, despachar N sub-agentes definiendo cantidad
  y backend/LLM por agente, dividir el spec en tasks (índice per-spec) y
  distribuirlas respetando `depends_on`.
- Config por-run en el `WorkBrief`, con fallback en cascada:
  `WorkBrief.dev_agents` → env `DEV_LOOP_DEV_AGENTS` → single-agent actual.
- **Back-compat estricta**: sin config de pool, el comportamiento actual
  (un solo `sdd-worker`, un dispatch, un stream) permanece idéntico.
- Aislamiento híbrido configurable: modo `shared` (olas sobre el worktree
  único) y modo `isolated` (sub-worktrees por agente + merge secuencial con
  dispatch resolutor de conflictos).
- Resiliencia: task de un sub-agente fallido se reintenta UNA vez en otro
  agente del pool; luego el nodo completa parcial y reporta
  `incomplete_tasks` — QA decide.
- Observabilidad: un stream Redis por sub-agente
  (`flow:{run_id}:dispatch:development.wN`), auto-descubierto por el
  multiplexor existente sin cambios en consumidores.
- Cap global de concurrencia del pool vía `DEV_LOOP_DEV_POOL_MAX`.
- La partición de tasks NO usa un LLM planner: scheduler determinista sobre
  el índice per-spec.

### Non-Goals (explicitly out of scope)

- Fan-out delegado al propio Claude Code (subagentes internos vía tool
  `Agent`) — rechazado en brainstorm (Option D): ata el diseño a un solo
  backend y pierde observabilidad tipada. Ver
  `sdd/proposals/dev-loop-multiple-dev-agents.brainstorm.md`.
- Un planner LLM para particionar/optimizar la asignación de tasks
  (rechazado: el índice per-spec ya trae `depends_on`).
- Cambios al contrato `DevLoopCodeDispatcher.dispatch()` o a los 7
  dispatchers existentes.
- Paralelizar los nodos Research/QA/CodeReview — solo Development.
- UI nueva: los consumidores actuales del WebSocket ya descubren los
  sub-streams.

---

## 2. Architectural Design

### Overview

Se introduce un **pool híbrido configurable** de sub-agentes de desarrollo
dentro del `DevelopmentNode` (Opción C del brainstorm):

- Un `DevAgentPoolConfig` declara la lista de agentes (`agent` = backend,
  `model`, `count`) y el `isolation_mode: "shared" | "isolated"`. Viaja en
  el `WorkBrief` (campos opcionales `dev_agents` / `dev_isolation`); si el
  brief no lo trae, se parsea del env `DEV_LOOP_DEV_AGENTS` /
  `DEV_LOOP_DEV_ISOLATION`; si tampoco existe, el nodo ejecuta el camino
  single-agent actual **sin cambios de conducta**.
- Un **TaskScheduler determinista** (sin LLM) lee
  `sdd/tasks/index/<feature>.json` desde `research.worktree_path` y produce
  "olas": conjuntos de tasks cuyas dependencias ya están completas. Detecta
  ciclos (error → `failure_handler`) e índice ausente/ilegible (degrada a
  single-agent con warning).
- Un **DevAgentPool** materializa cada `DevAgentSpec` en un dispatcher
  existente (reusando el builder generalizado del server), asigna tasks por
  round-robin sobre el pool expandido por `count`, y despacha cada task en
  paralelo (`asyncio.gather`) con `node_id="development.wN"` y un brief
  task-scoped (`task_id` → el `sdd-worker.md` instruye "implementa SOLO esa
  task"). El `count` total efectivo se limita por `DEV_LOOP_DEV_POOL_MAX`.
- **Modo `shared`**: todos los dispatches usan `cwd=worktree_path`
  (precondición documentada: tasks con archivos disjuntos).
  **Modo `isolated`**: sub-worktrees por agente bajo `WORKTREE_BASE_PATH`
  ramificados de la feature branch; al cerrar cada ola, merge secuencial a
  la feature branch; ante conflicto, dispatch resolutor (primer agente del
  pool, fallback claude-code); si el resolutor falla → `failure_handler`
  conservando las ramas para inspección.
- **Fallos**: excepción/output inválido/timeout de un dispatch ⇒ reintento
  único en otro agente del pool ⇒ segundo fallo marca la task incompleta y
  sus dependientes `skipped`. El nodo agrega los outputs por worker en un
  `DevelopmentOutput` extendido (`incomplete_tasks`, `worker_summaries`,
  defaults backward-compatible) y lo deja en
  `shared["development_output"]` como hoy.

### Component Diagram

```
WorkBrief.dev_agents ──(fallback)── env DEV_LOOP_DEV_AGENTS ──(fallback)── single-agent (camino actual)
        │
        ▼
DevelopmentNode.execute()
        │
        ├──► TaskScheduler ◄── sdd/tasks/index/<feature>.json (worktree)
        │        │  olas por depends_on (ciclos → failure_handler)
        │        ▼
        ├──► DevAgentPool ── DevAgentSpec[] → dispatchers existentes
        │        │  round-robin + retry(1) + cap DEV_LOOP_DEV_POOL_MAX
        │        ▼
        │   dispatch × N  (node_id=development.wN, brief task-scoped)
        │        │
        │        ├─ shared:   cwd = worktree_path (común)
        │        └─ isolated: WorktreeManager
        │                       ├─ sub-worktree por agente (WORKTREE_BASE_PATH)
        │                       ├─ merge secuencial → feature branch
        │                       └─ conflicto → dispatch resolutor → failure_handler
        │
        └──► agrega outputs → DevelopmentOutput(+incomplete_tasks, +worker_summaries)
                 │
                 ▼
        Redis: flow:{run_id}:dispatch:development.wN  ──► FlowStreamMultiplexer (SCAN, sin cambios)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DevelopmentNode` (`nodes/development.py`) | modifies | Orquestación del pool: scheduler, olas, reintentos, agregación. Camino single-agent intacto. |
| `parrot/flows/dev_loop/models.py` | extends | Nuevos `DevAgentSpec`, `DevAgentPoolConfig`; `WorkBrief.dev_agents`/`dev_isolation` opcionales; `DevelopmentOutput.incomplete_tasks`/`worker_summaries` con defaults. |
| `DevLoopCodeDispatcher` (Protocol) + 7 dispatchers | uses (sin cambios) | Se reusa `dispatch()` tal cual con `node_id` sintético `development.wN`. |
| `factories.py` / `flow.py` | extends | Aceptar/propagar el mapa de dispatchers disponibles (no solo uno) hacia el DevelopmentNode. |
| `examples/dev_loop/server.py` | modifies | Extraer builder `agente→dispatcher` reutilizable del bloque `DEV_LOOP_DEVELOPMENT_AGENT` (líneas 461-575) + parsing de `DEV_LOOP_DEV_AGENTS`/`DEV_LOOP_DEV_ISOLATION`/`DEV_LOOP_DEV_POOL_MAX`. |
| `FlowStreamMultiplexer` (`streaming.py`) | none | `SCAN flow:{run_id}:dispatch:*` ya descubre los sub-streams `development.wN`. |
| `sdd-worker.md` (`.claude/agents/` + `_subagent_data/`) | extends | Instrucción condicional task-scoped: "si el brief trae `task_id`, implementa SOLO esa task". |
| `conf.WORKTREE_BASE_PATH` / check R4 | depends on | Todo `cwd` (incl. sub-worktrees) debe vivir bajo la base; el check existente aplica sin cambios. |

### Data Models

```python
# Diseño (no implementación) — parrot/flows/dev_loop/models.py

DevAgentBackend = Literal[
    "claude-code", "codex", "gemini", "nvidia", "grok", "zai", "moonshot"
]

class DevAgentSpec(BaseModel):
    agent: DevAgentBackend            # backend → dispatcher existente
    model: str = ""                   # "" ⇒ default del backend (server)
    count: int = 1                    # réplicas de este spec (ge=1)

class DevAgentPoolConfig(BaseModel):
    agents: list[DevAgentSpec]        # min_length=1
    isolation_mode: Literal["shared", "isolated"] = "shared"

# WorkBrief — campos NUEVOS, opcionales (back-compat):
#   dev_agents: Optional[list[DevAgentSpec]] = None
#   dev_isolation: Optional[Literal["shared", "isolated"]] = None

# Brief task-scoped por dispatch (envuelve el ResearchOutput):
class TaskScopedBrief(BaseModel):
    research: ResearchOutput
    task_id: str                      # "TASK-NNN" — el subagent-def lo honra

# DevelopmentOutput — campos NUEVOS con defaults (back-compat):
#   incomplete_tasks: list[str] = []           # TASK-NNN no completadas
#   worker_summaries: list[WorkerSummary] = [] # resumen por sub-agente

class WorkerSummary(BaseModel):
    worker_id: str                    # "development.w1"
    agent: str                        # backend usado
    model: str
    tasks_completed: list[str]
    tasks_failed: list[str]
    summary: str
```

### New Public Interfaces

```python
# Diseño (no implementación)

# parrot/flows/dev_loop/task_scheduler.py
class TaskScheduler:
    """Olas deterministas desde el índice per-spec (sin LLM)."""
    @classmethod
    def from_index_file(cls, path: Path) -> "TaskScheduler": ...
    def next_wave(self) -> list[TaskRef]:      # tasks desbloqueadas
    def mark_done(self, task_id: str) -> None: ...
    def mark_failed(self, task_id: str) -> None:  # dependientes → skipped
    # ValueError en ciclos de depends_on

# parrot/flows/dev_loop/agent_pool.py
class DevAgentPool:
    """Materializa DevAgentSpec[] → dispatchers; asigna y despacha."""
    def __init__(self, *, config: DevAgentPoolConfig,
                 dispatcher_builder: Callable[[DevAgentSpec], DevLoopCodeDispatcher],
                 pool_max: int) -> None: ...
    async def run_wave(self, tasks, *, research, run_id, cwd_for) -> list[...]:
        # gather + retry(1) en otro agente + WorkerSummary por dispatch

# parrot/flows/dev_loop/worktree_manager.py  (solo modo isolated)
class SubWorktreeManager:
    """Crea/mergea/limpia sub-worktrees bajo WORKTREE_BASE_PATH."""
    async def create(self, worker_id: str) -> str          # ruta sub-worktree
    async def merge_sequential(self, resolver) -> MergeReport
    async def cleanup(self, *, keep_on_conflict: bool) -> None
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Pool config & output models
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models.py`
- **Responsibility**: `DevAgentSpec`, `DevAgentPoolConfig`, `WorkerSummary`,
  `TaskScopedBrief`; campos opcionales `WorkBrief.dev_agents`/`dev_isolation`;
  `DevelopmentOutput.incomplete_tasks`/`worker_summaries` con defaults
  backward-compatible. Validadores (count≥1, agents min_length=1).
- **Depends on**: — (existing models.py)

### Module 2: TaskScheduler determinista
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` (nuevo)
- **Responsibility**: cargar `sdd/tasks/index/<feature>.json` desde el
  worktree, computar olas por `depends_on`, detección de ciclos, `mark_done`/
  `mark_failed` con propagación `skipped` a dependientes. Índice
  ausente/ilegible ⇒ señal de degradación a single-agent (no excepción).
- **Depends on**: Module 1

### Module 3: Builder de dispatchers reutilizable + env parsing
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py`
  (nuevo) + `examples/dev_loop/server.py` (refactor)
- **Responsibility**: extraer del server el mapeo
  `DevAgentSpec → DevLoopCodeDispatcher + profile` (los 7 backends, con sus
  defaults de modelo actuales); parsing de `DEV_LOOP_DEV_AGENTS` (JSON),
  `DEV_LOOP_DEV_ISOLATION`, `DEV_LOOP_DEV_POOL_MAX`. El server pasa a
  consumir el builder (sin cambio de conducta para el camino single).
- **Depends on**: Module 1

### Module 4: DevAgentPool (asignación, retry, agregación)
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` (nuevo)
- **Responsibility**: expandir specs por `count` (cap `DEV_LOOP_DEV_POOL_MAX`),
  round-robin de tasks→workers, `asyncio.gather` por ola con
  `node_id="development.wN"`, reintento único en otro agente, construcción de
  `WorkerSummary` y fusión en `DevelopmentOutput` agregado.
- **Depends on**: Modules 1, 2, 3

### Module 5: SubWorktreeManager (modo isolated)
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` (nuevo)
- **Responsibility**: crear sub-worktrees por worker bajo
  `WORKTREE_BASE_PATH` (git CLI vía asyncio subprocess), merge secuencial a
  la feature branch al cerrar cada ola, dispatch resolutor ante conflicto
  (primer agente del pool, fallback claude-code), limpieza (conservar ramas
  en conflicto irresoluble), rutas siempre válidas para el check R4.
- **Depends on**: Modules 1, 4

### Module 6: DevelopmentNode rework
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py`
- **Responsibility**: resolución de config en cascada (brief → env → single);
  camino single-agent byte-idéntico al actual; camino pool: scheduler + pool
  + (shared|isolated) + agregación; escrituras a
  `shared["development_output"]`; degradación y errores → `failure_handler`.
- **Depends on**: Modules 1–5

### Module 7: Wiring factories/flow + subagent-def task-scoped
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py`,
  `flow.py`, `.claude/agents/sdd-worker.md`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`
- **Responsibility**: propagar builder/config del pool por
  `build_dev_loop_flow`/`build_dev_loop_node_factories` (parámetros nuevos
  opcionales); añadir al `sdd-worker.md` (ambas copias dual-sourced) la
  instrucción condicional: "si el brief trae `task_id`, implementa SOLO esa
  task y no marques otras".
- **Depends on**: Modules 4, 6

### Module 8: Tests (unit + integration)
- **Path**: `tests/flows/dev_loop/` (siguiendo el layout de tests existente)
- **Responsibility**: unit tests de scheduler/pool/models/builder; tests de
  back-compat del nodo (sin pool ⇒ un dispatch idéntico); integración con
  dispatchers falsos (protocolo `DevLoopCodeDispatcher`) para olas,
  reintento, parcial, merge y conflicto.
- **Depends on**: Modules 1–7

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_dev_agent_spec_defaults` | Module 1 | `count=1`, `model=""` por defecto; `count>=1` validado |
| `test_workbrief_backcompat_no_pool` | Module 1 | `WorkBrief` sin `dev_agents` valida igual que hoy (payloads existentes) |
| `test_development_output_defaults` | Module 1 | `incomplete_tasks=[]`/`worker_summaries=[]` — payloads antiguos validan |
| `test_scheduler_waves_by_depends_on` | Module 2 | Grafo A←B,C←B ⇒ olas [B],[A,C] |
| `test_scheduler_cycle_detection` | Module 2 | Ciclo en `depends_on` ⇒ ValueError |
| `test_scheduler_missing_index_degrades` | Module 2 | Índice ausente/corrupto ⇒ señal de degradación, no excepción |
| `test_scheduler_mark_failed_skips_dependents` | Module 2 | Task fallida ⇒ dependientes `skipped`, no despachadas |
| `test_env_pool_parsing` | Module 3 | `DEV_LOOP_DEV_AGENTS` JSON ⇒ `DevAgentPoolConfig`; inválido ⇒ warning + None |
| `test_builder_maps_all_backends` | Module 3 | Cada `DevAgentBackend` produce el dispatcher correcto con su default de modelo |
| `test_pool_round_robin_and_cap` | Module 4 | Expansión por `count` limitada por `DEV_LOOP_DEV_POOL_MAX` |
| `test_pool_retry_once_then_partial` | Module 4 | 1er fallo ⇒ reintento en OTRO agente; 2º fallo ⇒ `incomplete_tasks` |
| `test_pool_worker_stream_ids` | Module 4 | Dispatches usan `node_id="development.wN"` secuenciales |
| `test_worktree_manager_r4_paths` | Module 5 | Sub-worktrees siempre bajo `WORKTREE_BASE_PATH` |
| `test_merge_conflict_triggers_resolver` | Module 5 | Conflicto ⇒ dispatch resolutor (primer agente del pool) |
| `test_resolver_failure_keeps_branches` | Module 5 | Resolutor falla ⇒ excepción a failure_handler + ramas conservadas |
| `test_node_single_agent_unchanged` | Module 6 | Sin pool: exactamente 1 dispatch con los args actuales (regresión byte-a-byte del profile) |
| `test_node_cascade_brief_env_single` | Module 6 | Prioridad brief > env > single |
| `test_node_all_tasks_incomplete_fails` | Module 6 | Todas incompletas ⇒ el nodo falla (no pasa a QA) |

### Integration Tests
| Test | Description |
|---|---|
| `test_pool_shared_mode_end_to_end` | 2 workers falsos, 4 tasks (2 olas) en worktree compartido ⇒ output agregado correcto |
| `test_pool_isolated_mode_end_to_end` | Sub-worktrees reales (repo git temporal), merges limpios ⇒ feature branch con todos los commits |
| `test_isolated_merge_conflict_resolved` | Conflicto sintético ⇒ resolutor falso lo resuelve ⇒ flujo continúa |
| `test_partial_completion_reaches_qa` | Task incompleta ⇒ `DevelopmentOutput.incomplete_tasks` visible en shared state para QA |
| `test_multiplexer_discovers_worker_streams` | Streams `development.w1/w2` en Redis falso ⇒ `_discover_dispatch_streams` los devuelve |

### Test Data / Fixtures
```python
# Fixtures clave
@pytest.fixture
def per_spec_index(tmp_path):
    """sdd/tasks/index/<feature>.json sintético con depends_on en 2 olas."""

@pytest.fixture
def fake_dispatcher():
    """Implementación del Protocol DevLoopCodeDispatcher que registra
    (node_id, cwd, brief) y devuelve DevelopmentOutput programables,
    incluyendo modos de fallo (excepción / output inválido / timeout)."""

@pytest.fixture
def git_worktree_sandbox(tmp_path):
    """Repo git temporal con feature branch, bajo un WORKTREE_BASE_PATH
    parcheado, para los tests del SubWorktreeManager."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **Back-compat**: sin `dev_agents` (brief) ni `DEV_LOOP_DEV_AGENTS`
  (env), `DevelopmentNode` realiza exactamente 1 dispatch con el mismo
  profile/args que hoy (test de regresión dedicado).
- [ ] Cascada de config verificada: `WorkBrief.dev_agents` > env
  `DEV_LOOP_DEV_AGENTS` > single-agent.
- [ ] El scheduler produce olas correctas desde `sdd/tasks/index/<feature>.json`
  respetando `depends_on`; ciclos ⇒ fallo explícito; índice ausente ⇒
  degradación a single-agent con warning (nunca deadlock ni crash).
- [ ] Modo `shared` funcional: N dispatches paralelos sobre el worktree único.
- [ ] Modo `isolated` funcional: sub-worktrees bajo `WORKTREE_BASE_PATH`
  (check R4 pasa), merge secuencial a la feature branch, conflicto ⇒
  dispatch resolutor (primer agente del pool, fallback claude-code), fallo
  del resolutor ⇒ `failure_handler` con ramas conservadas.
- [ ] Task fallida se reintenta exactamente 1 vez en otro agente; segundo
  fallo ⇒ task en `incomplete_tasks`, dependientes `skipped`, la ola continúa.
- [ ] Todas las tasks incompletas ⇒ el nodo falla (no pasa a QA).
- [ ] `DevelopmentOutput` agrega `files_changed`/`commit_shas`/`summary` de
  todos los workers + `incomplete_tasks` + `worker_summaries`; payloads
  antiguos siguen validando (defaults).
- [ ] Cada sub-agente publica en `flow:{run_id}:dispatch:development.wN` y
  `FlowStreamMultiplexer` los descubre sin cambios en su código.
- [ ] `DEV_LOOP_DEV_POOL_MAX` limita el count total efectivo del pool; los
  semáforos por dispatcher siguen aplicando por debajo.
- [ ] `sdd-worker.md` (ambas copias dual-sourced) honra `task_id` en el brief
  (implementa SOLO esa task); sin `task_id` su conducta actual no cambia.
- [ ] Sin dependencias externas nuevas; sin breaking changes de API pública.
- [ ] All unit tests pass (`pytest tests/ -v` en los paths del feature).
- [ ] Documentación: docstring de módulos nuevos + nota en
  `examples/dev_loop/server.py` sobre las env vars nuevas.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
>
> Verificado 2026-07-21 sobre `dev` post-merge FEAT-321 (el merge no tocó
> `parrot/flows/dev_loop/`). Rutas relativas a
> `packages/ai-parrot/src/` salvo indicación contraria.

### Verified Imports
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

### Existing Class Signatures
```python
# parrot/flows/dev_loop/nodes/development.py
class DevelopmentNode(DevLoopNode):                       # line 30
    def __init__(self, *, dispatcher: DevLoopCodeDispatcher,
                 dispatch_profile: Optional[Any] = None,
                 name: str = "development") -> None: ...  # line 33
    async def execute(self, ctx, deps=None, **kwargs) -> DevelopmentOutput:  # line 48
        # shared["research_output"] -> ResearchOutput     # line 68
        # default profile: subagent="sdd-worker",
        #   permission_mode="acceptEdits"                 # lines 70-82
        # single dispatch: cwd=research.worktree_path,
        #   node_id=self.name                             # lines 84-91

# parrot/flows/dev_loop/dispatcher.py
class DevLoopCodeDispatcher(Protocol):                    # line 129
    async def dispatch(self, *, brief: BaseModel, profile: BaseModel,
                       output_model: Type[T], run_id: str,
                       node_id: str, cwd: str) -> T: ...  # line 132

class ClaudeCodeDispatcher:                               # line 150
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...    # line 157
    # self._semaphore = asyncio.Semaphore(max_concurrent)   line 180
    async def dispatch(...) -> T:                         # line 189
        # stream_key = f"flow:{run_id}:dispatch:{node_id}"  line 222
        # self._enforce_cwd_under_worktree_base(cwd, profile)  line 228
        # async with self._semaphore:                       line 238
# Homólogos en el mismo módulo: CodexCodeDispatcher (dispatch línea 896),
# GeminiCodeDispatcher, LLMCodeDispatcher, GrokCodeDispatcher,
# ZaiCodeDispatcher, MoonshotCodeDispatcher — cada uno con su propio
# Semaphore (líneas 890/1306/1746).

# parrot/flows/dev_loop/models.py
class WorkBrief(BaseModel):                               # line 118
    kind: WorkKind = Field(default="bug")                 # line 131
    summary: str                                          # line 141 (10..255)
    description: str = ""                                 # line 150
    affected_component: str                               # line 158
    log_sources: List[LogSource]                          # line 159
    acceptance_criteria: List[AcceptanceCriterion]        # line 160 (min_length=1)
    escalation_assignee: str                              # line 161

class ResearchOutput(BaseModel):                          # line 273
    jira_issue_key: str                                   # line 288
    spec_path: str                                        # line 293
    feat_id: str                                          # line 298
    branch_name: str                                      # line 303
    worktree_path: str                                    # line 308 (UN solo worktree)
    repo_path: str = ""                                   # line 313 (fallback: worktree_path)
    log_excerpts: List[str]                               # line 323

class DevelopmentOutput(BaseModel):                       # line 329
    files_changed: List[str]                              # line 332
    commit_shas: List[str]                                # line 333
    summary: str                                          # line 334

class ClaudeCodeDispatchProfile(BaseModel):               # line 381
    subagent: Optional[Literal["sdd-research", "sdd-worker",
        "sdd-qa", "sdd-codereview"]] = "sdd-worker"       # line 389
    permission_mode: Literal["default", "acceptEdits",
        "plan", "bypassPermissions"] = "default"          # line 392
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)  # line 407
    model: str = "claude-sonnet-4-6"                      # line 408

class DispatchEvent(BaseModel):                           # line 698
    kind: Literal["dispatch.queued", "dispatch.started",
        "dispatch.message", "dispatch.tool_use", "dispatch.tool_result",
        "dispatch.output_invalid", "dispatch.failed",
        "dispatch.completed"]                             # line 707
    ts: float; run_id: str                                # lines 717-718

# parrot/flows/dev_loop/streaming.py
class FlowStreamMultiplexer:
    # self._dispatch_prefix = f"flow:{run_id}:dispatch:"    line 81
    async def _discover_dispatch_streams(self) -> List[str]:  # line 90
        # SCAN cursor-based sobre flow:{run_id}:dispatch:*   lines 93-110
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DevAgentPool` | `DevLoopCodeDispatcher.dispatch()` | llamada con `node_id="development.wN"` | `parrot/flows/dev_loop/dispatcher.py:132` |
| `TaskScheduler` | índice per-spec | lectura JSON desde `<worktree>/sdd/tasks/index/<feature>.json` | esquema FEAT-145 (CLAUDE.md) |
| `DevelopmentNode` (rework) | `shared["research_output"]` / `shared["development_output"]` | shared state del flow | `nodes/development.py:68,92` |
| `SubWorktreeManager` | check R4 | rutas bajo `conf.WORKTREE_BASE_PATH` | `dispatcher.py:228` (`_enforce_cwd_under_worktree_base`) |
| builder de dispatchers | bloque de selección actual del server | refactor/extracción | `examples/dev_loop/server.py:461-575` (ruta desde raíz del repo) |
| pool wiring | `build_dev_loop_node_factories(development_dispatcher=, development_profile=)` | parámetros nuevos opcionales junto a los existentes | `parrot/flows/dev_loop/factories.py:45-46,77,99-103,141` |
| pool wiring | `build_dev_loop_flow(...)` | ídem; edges `research→development→qa` | `parrot/flows/dev_loop/flow.py:168-169,285-286` |
| task-scoped prompt | `load_subagent_definition("sdd-worker")` | mismo body para todos los backends | `parrot/flows/dev_loop/_subagent_defs.py:33` (`_VALID_NAMES`) |

### Configuration References
- `conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES` — cap del semáforo del
  dispatcher Claude (existente).
- `conf.WORKTREE_BASE_PATH` — raíz obligatoria de todo `cwd` de dispatch
  (existente; aplica también a los sub-worktrees nuevos).
- `DEV_LOOP_DEVELOPMENT_AGENT` — selección single-agent actual (existente,
  `examples/dev_loop/server.py:461`).
- `DEV_LOOP_DEV_AGENTS` / `DEV_LOOP_DEV_ISOLATION` / `DEV_LOOP_DEV_POOL_MAX`
  — **nuevas** env vars a introducir en Module 3.

### Does NOT Exist (Anti-Hallucination)
- ~~`WorkBrief.dev_agents` / `WorkBrief.dev_isolation`~~ — a crear en Module 1
- ~~`ResearchOutput.tasks`~~ — research NO transporta la lista de tasks; se
  lee el índice per-spec desde el worktree
- ~~`DevAgentSpec` / `DevAgentPoolConfig` / `TaskScheduler` / `DevAgentPool` /
  `SubWorktreeManager` / `WorkerSummary` / `TaskScopedBrief`~~ — a crear
  (Modules 1, 2, 4, 5)
- ~~`parrot/flows/dev_loop/task_scheduler.py` / `agent_pool.py` /
  `agent_builder.py` / `worktree_manager.py`~~ — archivos nuevos a crear
- ~~env `DEV_LOOP_DEV_AGENTS` / `DEV_LOOP_DEV_ISOLATION` /
  `DEV_LOOP_DEV_POOL_MAX`~~ — a crear en Module 3
- ~~`DispatchEvent.worker_id`~~ — no existe y NO se añade (streams por
  sub-agente lo hacen innecesario)
- ~~clase `DevLoopConfig`~~ — `config.py` solo contiene `parse_repo_specs()`
- ~~soporte multi-dispatch o multi-worktree en `DevelopmentNode`~~ — hoy es
  estrictamente 1 dispatch / 1 worktree
- ~~nodo o dispatcher de resolución de merges~~ — el resolutor es un
  dispatch más del pool (Module 5), no un nodo del flow

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first en todo: `asyncio.gather` para olas, git vía
  `asyncio.create_subprocess_exec` (patrón ya usado por sdd-research) —
  nunca subprocess bloqueante.
- Pydantic v2 para toda estructura nueva; `models.py` mantiene cero
  dependencias de `claude_agent_sdk` a nivel de import.
- Los dispatchers se consumen SOLO vía el Protocol
  `DevLoopCodeDispatcher.dispatch()` — no tocar sus internals.
- Logging con `self.logger` / `logging.getLogger(__name__)`; nada de print.
- Registro de nodo: mantener `@register_dev_loop_node("dev_loop.development")`.
- Subagent-defs dual-sourced: TODA edición de `sdd-worker.md` se aplica a
  `.claude/agents/sdd-worker.md` Y a `_subagent_data/sdd-worker.md`.

### Known Risks / Gotchas
- **Modo `shared` con tasks que comparten archivos**: carreras reales de git
  index/working tree. Mitigación: documentar la precondición (tasks
  disjuntas), y el default del pool es `shared` solo por elección explícita
  del operador; en duda, usar `isolated`.
- **Índice per-spec ausente/ilegible** en el worktree ⇒ degradar a
  single-agent (warning), nunca fallar el run por esto.
- **Ciclos en `depends_on`** ⇒ error de validación explícito ⇒
  `failure_handler` (nunca deadlock silencioso).
- **Timeout de un dispatch** ⇒ misma semántica que fallo (reintento →
  parcial); cuidado con dejar procesos CLI huérfanos (matar el proceso al
  timeout como ya hacen los dispatchers CLI).
- **Conflicto de merge irresoluble** ⇒ conservar sub-worktrees/ramas para
  inspección forense y reportar rutas en el error.
- **Pool con count total = 1** ⇒ equivale a single-agent con brief
  task-scoped por ola (sin sub-worktrees en modo isolated).
- **Todas las tasks incompletas** ⇒ el nodo falla; no tiene sentido pasar a QA.
- **Streams**: más claves Redis por run (`development.wN`); el TTL/MAXLEN
  existente por stream aplica igual — sin cambio de infra.
- **Limpieza de sub-worktrees**: siempre en éxito o fallo ya mergeado;
  `git worktree prune` defensivo al cerrar el nodo.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | Sin dependencias nuevas: stdlib `asyncio`/`json`, `pydantic>=2` (ya presente), git CLI vía subprocess (ya usado) |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] ¿Tipo de flujo/base? — *Resolved in brainstorm*: feature → dev.
- [x] ¿Estrategia de aislamiento? — *Resolved in brainstorm*: híbrido
  configurable (`shared` olas / `isolated` sub-worktrees), decidido por
  config por-run.
- [x] ¿Dónde se define el pool? — *Resolved in brainstorm*: en el `WorkBrief`
  por-run, con fallback a env `DEV_LOOP_DEV_AGENTS` y luego single-agent
  (back-compat exacta).
- [x] ¿Quién divide el spec en tasks? — *Resolved in brainstorm*: se reusa el
  índice per-spec de sdd-research (`depends_on`); sin planner LLM.
- [x] ¿Conflictos de merge en modo isolated? — *Resolved in brainstorm*:
  merge secuencial + dispatch resolutor; si el resolutor falla →
  failure_handler.
- [x] ¿Semántica ante fallo de un sub-agente? — *Resolved in brainstorm*: un
  reintento en otro agente del pool; luego completar parcial y reportar
  tasks incompletas (QA decide).
- [x] ¿Streaming? — *Resolved in brainstorm*: stream Redis por sub-agente
  (`development.wN`); el multiplexor los descubre vía SCAN sin cambios.
- [x] Task-scoped prompting del `sdd-worker` — *Resolved in brainstorm*:
  brief extendido con `task_id` + instrucción condicional en el
  `sdd-worker.md` existente; sin nombres nuevos en `_VALID_NAMES` ni cambios
  al `Literal` de `ClaudeCodeDispatchProfile.subagent`.
- [x] Cap agregado de concurrencia del pool — *Resolved in brainstorm*:
  `DEV_LOOP_DEV_POOL_MAX` limita el count total efectivo; semáforos por
  dispatcher como segunda capa.
- [x] Backend del dispatch resolutor de conflictos — *Resolved in
  brainstorm*: el primer agente del pool, con fallback a claude-code.
- [x] Forma del reporte parcial — *Resolved in brainstorm*:
  `DevelopmentOutput.incomplete_tasks: list[str]` + `worker_summaries`,
  defaults backward-compatible; QA los lee del shared state.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — todas las tasks secuenciales en
  un único worktree.
- **Rationale**: casi todas las tasks editan `models.py`,
  `nodes/development.py` y `flow.py`/`factories.py`; particionar en
  worktrees generaría los mismos conflictos de merge que esta feature
  intenta gestionar.
- **Cross-feature dependencies**: ninguna pendiente de merge. Tocaría
  coordinarse con cualquier spec futuro que reabra
  `parrot/flows/dev_loop/models.py` o `flow.py` (p. ej. iteraciones de
  FEAT-270 code-review multi-dispatcher).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-21 | Jesus Lara | Initial draft desde brainstorm (11 preguntas resueltas, 0 abiertas) |
