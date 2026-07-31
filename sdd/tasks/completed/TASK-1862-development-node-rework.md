# TASK-1862: DevelopmentNode rework — cascada de config, orquestación del pool, agregación

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1857, TASK-1858, TASK-1859, TASK-1860, TASK-1861
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 6** del spec: el `DevelopmentNode` pasa de "1 dispatch"
a "1..N dispatches" orquestando scheduler + pool + (shared|isolated), con la
**restricción más importante del feature**: sin config de pool, el camino
actual debe permanecer byte-idéntico (mismo profile default, mismo node_id,
mismo cwd).

---

## Scope

- Modificar `parrot/flows/dev_loop/nodes/development.py`:
  - `__init__` acepta además (keyword-only, opcionales):
    `pool_config: Optional[DevAgentPoolConfig] = None`,
    `dispatcher_builder: Optional[Callable[[DevAgentSpec], tuple] ] = None`,
    `pool_max: int = 4` — manteniendo `dispatcher` y `dispatch_profile`
    actuales intactos.
  - En `execute()`:
    1. **Resolución en cascada**: pool del `WorkBrief`
       (`shared["work_brief"]` si el flow lo expone — verificar la clave
       real en shared state; si el brief no está en shared, recibir el pool
       ya resuelto vía `__init__`) → `pool_config` inyectado (env, resuelto
       por el server/factories) → sin pool ⇒ **camino actual sin cambios**.
    2. Camino single (sin pool o count total == 1 sin isolation isolated):
       código EXACTAMENTE igual al actual (profile default `sdd-worker` +
       un dispatch con `node_id=self.name`).
    3. Camino pool: `TaskScheduler.from_worktree(research.worktree_path,
       feature_slug)` (slug derivado de `research.feat_id`/índice presente);
       scheduler `None` ⇒ log warning + camino single.
    4. Loop de olas: `next_wave()` → `pool.run_wave(...)`;
       `isolation_mode=="isolated"` ⇒ `SubWorktreeManager.create()` por
       worker antes de la primera ola, `cwd_for` devuelve el sub-worktree
       del worker; tras cada ola `merge_sequential(resolver=...)`;
       `"shared"` ⇒ `cwd_for` devuelve siempre `research.worktree_path`.
    5. **Política del resolutor**: callable que despacha al PRIMER worker
       del pool con un brief de resolución de conflicto; si ese dispatch
       falla y el primer worker no es claude-code, reintenta una vez con un
       dispatcher claude-code construido vía `dispatcher_builder`
       (`DevAgentSpec(agent="claude-code")`); fallo total ⇒ propagar
       `SubWorktreeMergeError`.
    6. `mark_done`/`mark_failed` según resultados de la ola; tasks fallidas
       tras retry ⇒ `incomplete_tasks`.
    7. Terminación: sin tasks despachables; TODAS incompletas ⇒ raise
       (→ `failure_handler`); si no, `aggregate_outputs(...)` ⇒
       `shared["development_output"]` y return.
    8. `cleanup()` de sub-worktrees en `finally` (conservar en conflicto).
- Unit tests del nodo con fakes: regresión single-agent byte-a-byte,
  cascada, degradación sin índice, all-incomplete falla, shared e isolated
  con manager falso.

**NOT in scope**: wiring de factories/flow/server (TASK-1863), subagent-def
(TASK-1863), tests de integración end-to-end (TASK-1864).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | Orquestación pool + camino single intacto |
| `tests/flows/dev_loop/test_development_node.py` | CREATE | Unit tests del nodo |

---

## Codebase Contract (Anti-Hallucination)

> Rutas relativas a `packages/ai-parrot/src/`.

### Verified Imports
```python
# Ya presentes en nodes/development.py:18-26 — conservar:
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_loop.dispatcher import DevLoopCodeDispatcher
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile, DevelopmentOutput, ResearchOutput,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
# Nuevos (tras TASK-1857..1861):
from parrot.flows.dev_loop.models import DevAgentPoolConfig, DevAgentSpec, TaskScopedBrief
from parrot.flows.dev_loop.task_scheduler import TaskScheduler
from parrot.flows.dev_loop.agent_pool import DevAgentPool, WaveResult, aggregate_outputs
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager
# SubWorktreeMergeError NOT imported here — the node never catches it,
# only lets it propagate (per "Does NOT Exist" note below); TaskScopedBrief
# added for the conflict-resolver's brief (see Completion Note deviation 2);
# conf.WORKTREE_BASE_PATH read via `from parrot import conf` (precedent:
# nodes/research.py already does this — confirmed via grep).
```

### Existing Signatures to Use
```python
# parrot/flows/dev_loop/nodes/development.py — ESTADO ACTUAL a preservar
# como camino single:
@register_dev_loop_node("dev_loop.development")           # line 29
class DevelopmentNode(DevLoopNode):                       # line 30
    def __init__(self, *, dispatcher: DevLoopCodeDispatcher,
                 dispatch_profile: Optional[Any] = None,
                 name: str = "development") -> None:      # line 33
        super().__init__(node_id=name)                    # line 40
        object.__setattr__(self, "_dispatcher", dispatcher)        # line 41
        object.__setattr__(self, "_dispatch_profile", dispatch_profile)  # line 42
    # NOTA: los atributos se setean con object.__setattr__ — el nodo base
    # es frozen/pydantic-like. Mantener el patrón para atributos nuevos.

    async def execute(self, ctx, deps=None, **kwargs) -> DevelopmentOutput:  # line 48
        shared = self.shared_state(ctx)                   # line 67 — helper del base
        research: ResearchOutput = shared["research_output"]   # line 68
        profile = self._dispatch_profile or ClaudeCodeDispatchProfile(
            subagent="sdd-worker", permission_mode="acceptEdits",
            allowed_tools=["Read", "Edit", "Write", "Bash", "Grep", "Glob"],
            setting_sources=["project"])                  # lines 70-82
        dev_out = await self._dispatcher.dispatch(
            brief=research, profile=profile,
            output_model=DevelopmentOutput,
            run_id=shared["run_id"], node_id=self.name,
            cwd=research.worktree_path)                   # lines 84-91
        shared["development_output"] = dev_out            # line 92
        return dev_out                                    # line 93
```

### Does NOT Exist
- ~~`shared["work_brief"]`~~ — (unverified — check before use): verificar
  con grep qué claves publica el flow en shared state (`bug_intake`/
  `intent_classifier` nodes) ANTES de leer el brief ahí; si el brief no
  viaja en shared, la cascada brief→env se resuelve FUERA del nodo (server/
  factories pasan el pool ya resuelto) y el nodo solo distingue
  pool_config presente/ausente
- ~~soporte actual multi-dispatch en el nodo~~ — hoy es 1 dispatch estricto
- ~~`DevelopmentNode.pool_config` / `dispatcher_builder` / `pool_max`~~ — los añade ESTA task
- ~~`failure_handler` invocado directamente por el nodo~~ — el nodo solo
  LANZA excepciones; el routing a failure_handler lo hace el flow (flow.py)

---

## Implementation Notes

### Pattern to Follow
```python
# Bifurcación temprana y explícita — el camino single es EL CÓDIGO ACTUAL:
async def execute(self, ctx, deps=None, **kwargs):
    shared = self.shared_state(ctx)
    research = shared["research_output"]
    pool_cfg = self._resolve_pool_config(shared)
    if pool_cfg is None:
        return await self._execute_single(shared, research)   # código actual, intacto
    return await self._execute_pool(shared, research, pool_cfg)
```

### Key Constraints
- **Regresión byte-a-byte**: `_execute_single` debe emitir el MISMO
  dispatch que hoy (mismo profile default con esos 6 allowed_tools, mismo
  `node_id=self.name`, mismo cwd). Test con fake dispatcher que capture y
  compare los kwargs exactos.
- Atributos nuevos vía `object.__setattr__` (patrón del nodo).
- `try/finally` alrededor del loop de olas para `cleanup()` del manager.
- Slug del índice: derivarlo listando `<worktree>/sdd/tasks/index/*.json`
  y matcheando `feature_id == research.feat_id` (no asumir nombre).
- Errores del scheduler (ciclos) y `SubWorktreeMergeError` se propagan
  (el flow los enruta a failure_handler); degradaciones (índice ausente)
  NO son errores.

### References in Codebase
- `parrot/flows/dev_loop/nodes/base.py` — `DevLoopNode.shared_state()` y patrón de nodo
- `parrot/flows/dev_loop/flow.py:285-301` — routing development→qa/failure
- Spec §2 Overview (cascada, resolutor, terminación) y §7 Known Risks

---

## Acceptance Criteria

- [ ] Sin pool: dispatch único con kwargs idénticos a los actuales (test de regresión con captura)
- [ ] Cascada: `pool_config` inyectado usado cuando presente; ausente ⇒ single
- [ ] Índice ausente ⇒ warning + camino single (nunca crash)
- [ ] Olas ejecutadas respetando scheduler; fallo→retry→incomplete integrados
- [ ] Modo isolated: sub-worktrees creados antes de la ola 1, merge tras cada ola, resolutor = primer worker con fallback claude-code, cleanup en finally
- [ ] Todas las tasks incompletas ⇒ excepción (→ failure_handler)
- [ ] `shared["development_output"]` recibe el output agregado
- [ ] All tests pass: `pytest tests/flows/dev_loop/test_development_node.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py`

---

## Test Specification

```python
# tests/flows/dev_loop/test_development_node.py
import pytest
from parrot.flows.dev_loop.nodes.development import DevelopmentNode


class RecordingDispatcher:
    """Captura los kwargs exactos de dispatch para el test de regresión."""


class TestSinglePathRegression:
    async def test_no_pool_exact_current_behavior(self):
        """Sin pool: 1 dispatch, node_id='development', cwd=worktree_path,
        profile default sdd-worker/acceptEdits con los 6 allowed_tools."""


class TestCascade:
    async def test_injected_pool_used(self): ...
    async def test_missing_index_degrades_to_single(self): ...


class TestPoolPath:
    async def test_waves_and_partial(self): ...
    async def test_all_incomplete_raises(self): ...
    async def test_isolated_uses_manager_and_cleanup(self):
        """Manager falso: create por worker, merge por ola, cleanup en finally
        incluso si una ola lanza."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1857..1861 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — en especial la clave del brief en shared state (grep en nodes/ y flow.py) antes de implementar la cascada
4. **Update status** in `sdd/tasks/index/dev-loop-multiple-dev-agents.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: Reworked `DevelopmentNode` per scope: `__init__` gained
`pool_config`/`dispatcher_builder`/`pool_max=4` (keyword-only, optional,
via `object.__setattr__` matching the existing frozen-node pattern);
`execute()` bifurcates via `_resolve_pool_config` (cascade:
`shared["work_brief"] or shared["bug_brief"]`.`dev_agents` — verified via
grep that BOTH keys exist, forward-compat/legacy, set by
`intent_classifier.py`/`runner.py` — > injected `pool_config` > `None`);
`_execute_single` is the untouched pre-FEAT-323 code (verified byte-a-byte
via `TestSinglePathRegression` + the pre-existing `test_development.py`
suite, both green); `_execute_pool` resolves the feature slug by scanning
`sdd/tasks/index/*.json` for a `feature_id` match (never assumes the
filename), builds the pool via `DevAgentPool.build`, loops
`scheduler.next_wave()` → `pool.run_wave()` → `mark_done`/`mark_failed`,
creates sub-worktrees via `SubWorktreeManager` before the first wave and
merges after each wave in 'isolated' mode (`cleanup()` always runs in
`finally`), raises `RuntimeError` only when zero tasks completed AND some
are incomplete (true "all-incomplete" case — partial completion does not
raise, matching "QA decide"), and returns `aggregate_outputs(...)`. The
conflict-resolver policy (`_resolve_conflict`) dispatches the pool's first
worker into the conflicted sub-worktree, falling back to a claude-code
dispatcher (via `dispatcher_builder`) on failure, propagating
`SubWorktreeMergeError` if both fail. Added
`packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` (9
tests: single-path regression, injected-pool-used, brief-overrides-
injected, missing-index-degrades, no-builder-degrades, waves+partial
aggregation, all-incomplete raises, isolated mode manager/dispatch-cwd
wiring, cleanup-runs-in-finally-even-on-merge-failure — via a `FakeManager`/
`FailingMergeManager` test double, no real git needed for this file since
TASK-1861 already covers real-git behavior). Full
`packages/ai-parrot/tests/flows/dev_loop/` suite (449 tests) passes except
the same 4 pre-existing full-suite-ordering failures already verified
unrelated to this feature. `ruff check` clean. Verified
`parrot.flows.dev_loop.factories`/`.flow`/the bare package still import
cleanly after the fix below.

**Deviations from spec**:
1. Discovered and fixed a **circular-import bug** in `agent_pool.py`
   (TASK-1860), outside this task's nominal file list but blocking this
   task entirely: `agent_pool.py` imported its dependencies via the
   `parrot.flows.dev_loop` package (a TASK-1859/1860 deviation to keep
   class identity stable against `test_lazy_import.py`'s `sys.modules`
   surgery). `nodes/development.py` now imports `agent_pool.py`, and
   `nodes/development.py` is reached **transitively** through the
   package's own init chain (`__init__.py -> flow.py -> factories.py ->
   nodes/development.py`), so importing the package from `agent_pool.py`
   raised `ImportError: cannot import name ... from partially initialized
   module`. Fixed by reverting `agent_pool.py` to import directly from
   `.dispatcher`/`.models`/`.task_scheduler` (submodule-direct) — safe
   here because nothing else currently imports `agent_pool`'s classes via
   the package path, so there is no class-identity divergence risk (unlike
   `agent_builder.py`, which stays package-style since it is NOT reached
   by the package's own init chain and IS imported by `server.py` via the
   package). Documented the rationale in `agent_pool.py`'s module docstring.
2. `_resolve_conflict`'s brief for the conflict-resolver dispatch has no
   dedicated Pydantic model in the spec's Data Models section (only
   `TaskScopedBrief` exists). I reused `TaskScopedBrief(research=research,
   task_id="RESOLVE_MERGE_CONFLICT")` — a sentinel task_id, not a real
   TASK-NNN — dispatched with `cwd` set to the conflicted sub-worktree, so
   the resolver agent discovers the conflict via `git status` itself
   (mirroring how the single-agent path already drops `sdd-worker` into a
   worktree with no further hand-holding). TASK-1863 (subagent-def wiring)
   should confirm whether `sdd-worker.md`'s new task-scoped instruction
   needs an explicit carve-out for this sentinel, or whether the existing
   "no task_id match in index -> use judgment" behavior already covers it.
