# TASK-1860: DevAgentPool — asignación round-robin, dispatch paralelo, retry y agregación

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1857, TASK-1858, TASK-1859
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 4** del spec — el corazón del feature. El pool
materializa los `DevAgentSpec` en dispatchers, expande por `count` (con cap
`DEV_LOOP_DEV_POOL_MAX`), asigna las tasks de cada ola por round-robin,
despacha en paralelo con `node_id="development.wN"`, aplica la semántica de
reintento único en OTRO agente, y fusiona los resultados por worker en un
`DevelopmentOutput` agregado.

---

## Scope

- Crear `parrot/flows/dev_loop/agent_pool.py` con:
  - `PoolWorker`: dataclass/modelo interno — `worker_id: str`
    (`"development.w1"`...), `spec: DevAgentSpec`,
    `dispatcher: DevLoopCodeDispatcher`, `profile: BaseModel`.
  - `class DevAgentPool`:
    - `__init__(self, *, config: DevAgentPoolConfig, workers: list[PoolWorker], pool_max: int)`
      — o factory `DevAgentPool.build(config, dispatcher_builder, pool_max)`
      que expande specs por `count`, trunca al cap (con `log.warning` de lo
      recortado) y numera `worker_id` secuencialmente.
    - `async run_wave(self, tasks: list[TaskRef], *, research: ResearchOutput,
      run_id: str, cwd_for: Callable[[str], str]) -> WaveResult` —
      round-robin task→worker; por cada task construye un `TaskScopedBrief`
      y llama `worker.dispatcher.dispatch(brief=..., profile=worker.profile,
      output_model=DevelopmentOutput, run_id=run_id,
      node_id=worker.worker_id, cwd=cwd_for(worker.worker_id))`;
      `asyncio.gather(..., return_exceptions=True)`.
    - Semántica de fallo: excepción, `DispatchOutputValidationError` o
      timeout ⇒ reintento único de esa task en OTRO worker (si el pool tiene
      >1; si no, en el mismo); segundo fallo ⇒ task fallida en el
      `WaveResult`.
    - `WaveResult`: `completed: dict[task_id, DevelopmentOutput]`,
      `failed: list[task_id]`, `worker_summaries: list[WorkerSummary]`.
  - `aggregate_outputs(results: list[WaveResult], incomplete: list[str])
    -> DevelopmentOutput` — une `files_changed` (dedup, orden estable),
    `commit_shas` (orden de llegada), `summary` concatenado por worker, y
    puebla `incomplete_tasks` + `worker_summaries`.
- Unit tests con dispatchers falsos (Protocol): round-robin, cap, retry en
  otro worker, ids de stream, agregación.

**NOT in scope**: creación de sub-worktrees/merge (TASK-1861), decisión
shared/isolated y wiring en el nodo (TASK-1862).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` | CREATE | Pool + agregación |
| `tests/flows/dev_loop/test_agent_pool.py` | CREATE | Unit tests con fakes |

---

## Codebase Contract (Anti-Hallucination)

> Rutas relativas a `packages/ai-parrot/src/`.

### Verified Imports
```python
from parrot.flows.dev_loop.dispatcher import (
    DevLoopCodeDispatcher,               # Protocol — dispatcher.py:129
    DispatchExecutionError,              # dispatcher.py (clase de error)
    DispatchOutputValidationError,       # dispatcher.py (clase de error)
)
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,                   # models.py:329
    ResearchOutput,                      # models.py:273
    # tras TASK-1857:
    DevAgentPoolConfig, DevAgentSpec, TaskScopedBrief, WorkerSummary,
)
# tras TASK-1858:
from parrot.flows.dev_loop.task_scheduler import TaskRef
# tras TASK-1859:
from parrot.flows.dev_loop.agent_builder import build_dispatcher
```

### Existing Signatures to Use
```python
# parrot/flows/dev_loop/dispatcher.py
class DevLoopCodeDispatcher(Protocol):                    # line 129
    async def dispatch(self, *, brief: BaseModel, profile: BaseModel,
                       output_model: Type[T], run_id: str,
                       node_id: str, cwd: str) -> T: ...  # line 132
# El stream Redis se deriva DENTRO del dispatcher:
#   stream_key = f"flow:{run_id}:dispatch:{node_id}"        line 222
# ⇒ pasar node_id="development.wN" ya produce streams por sub-agente.
# Cada dispatcher concreto tiene su propio asyncio.Semaphore interno
# (lines 180/890/1306/1746) — el pool NO gestiona semáforos de dispatch.

class DevelopmentOutput(BaseModel):                       # models.py:329
    files_changed: List[str]                              # line 332
    commit_shas: List[str]                                # line 333
    summary: str                                          # line 334
```

### Does NOT Exist
- ~~`parrot/flows/dev_loop/agent_pool.py` / `DevAgentPool` / `PoolWorker` / `WaveResult`~~ — los crea ESTA task
- ~~`DispatchEvent.worker_id`~~ — NO existe y NO se añade (el worker_id ES el node_id del stream)
- ~~timeout propio del pool~~ — el timeout vive en el profile de cada dispatcher (`timeout_seconds`, models.py:407); el pool solo trata la excepción resultante como fallo
- ~~semáforo global nuevo en el pool~~ — el cap del pool es `pool_max` (recorte de workers), NO otro semáforo de dispatch

---

## Implementation Notes

### Pattern to Follow
```python
# Round-robin estable por índice de task:
assignments = {t.id: workers[i % len(workers)] for i, t in enumerate(tasks)}
results = await asyncio.gather(
    *(self._dispatch_one(w, t, ...) for t, w in assignments.items()),
    return_exceptions=False,  # _dispatch_one captura internamente y devuelve un resultado tipado
)
```

### Key Constraints
- `_dispatch_one` captura TODA excepción del dispatch y la convierte en un
  resultado tipado (task_id, worker_id, error) — nunca dejar que un fallo
  individual mate el gather de la ola.
- El reintento elige el SIGUIENTE worker distinto (round-robin desde el que
  falló); con 1 solo worker, reintenta en el mismo.
- `worker_id` estable durante todo el run: `development.w1..wN` numerados en
  orden de expansión (specs en orden, réplicas consecutivas).
- Agregación determinista: `files_changed` dedup preservando primer orden de
  aparición; `summary` = líneas `"[wN/backend] <summary>"`.
- Async puro; logging con `logging.getLogger(__name__)`.

### References in Codebase
- `parrot/flows/dev_loop/dispatcher.py:189-238` — semántica de dispatch/errores del backend Claude
- Spec §2 New Public Interfaces + §3 Module 4

---

## Acceptance Criteria

- [ ] Expansión por `count` con cap `pool_max` (warning con lo recortado)
- [ ] Round-robin determinista task→worker; `node_id="development.wN"` correctos y únicos
- [ ] Fallo (excepción/output inválido) ⇒ 1 reintento en OTRO worker; 2º fallo ⇒ task en `failed`
- [ ] `aggregate_outputs` produce `DevelopmentOutput` con dedup de archivos, shas en orden, `incomplete_tasks` y `worker_summaries` poblados
- [ ] Con pool de 1 worker y 1 task el dispatch es único y el output agregado ≡ output del worker (más metadata)
- [ ] All tests pass: `pytest tests/flows/dev_loop/test_agent_pool.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py`
- [ ] `from parrot.flows.dev_loop.agent_pool import DevAgentPool` funciona

---

## Test Specification

```python
# tests/flows/dev_loop/test_agent_pool.py
import pytest
from parrot.flows.dev_loop.agent_pool import DevAgentPool, aggregate_outputs
from parrot.flows.dev_loop.models import DevelopmentOutput


class FakeDispatcher:
    """Cumple el Protocol DevLoopCodeDispatcher; registra llamadas y
    permite programar fallos por task_id (excepción o output inválido)."""
    def __init__(self, fail_ids=()):
        self.calls = []
        self.fail_ids = set(fail_ids)

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd):
        self.calls.append((brief.task_id, node_id, cwd))
        if brief.task_id in self.fail_ids:
            self.fail_ids.discard(brief.task_id)  # falla solo la 1ª vez
            raise RuntimeError("boom")
        return DevelopmentOutput(files_changed=[f"{brief.task_id}.py"],
                                 commit_shas=["abc"], summary=brief.task_id)


class TestPool:
    async def test_round_robin_and_stream_ids(self):
        """2 workers, 4 tasks ⇒ w1,w2,w1,w2 con node_id development.wN."""

    async def test_retry_on_other_worker_then_partial(self):
        """Task programada para fallar 2 veces ⇒ aparece en failed;
        1 fallo ⇒ reintento aterriza en worker distinto."""

    async def test_pool_max_truncates(self):
        """count total 5 con pool_max=2 ⇒ 2 workers."""


class TestAggregate:
    def test_dedup_and_metadata(self):
        """files_changed dedup, incomplete_tasks y worker_summaries poblados."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1857, TASK-1858, TASK-1859 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code
4. **Update status** in `sdd/tasks/index/dev-loop-multiple-dev-agents.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
