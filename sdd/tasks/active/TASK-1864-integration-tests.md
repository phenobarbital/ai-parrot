# TASK-1864: Tests de integración end-to-end del pool (shared, isolated, parcial, streams)

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1857, TASK-1858, TASK-1859, TASK-1860, TASK-1861, TASK-1862, TASK-1863
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 8** del spec. Los módulos 1-7 traen unit tests
propios; esta task cubre los caminos COMPUESTOS del spec §4 Integration
Tests: pool completo en modo shared e isolated, conflicto+resolutor,
parcial→QA y descubrimiento de streams por el multiplexor.

---

## Scope

- Crear `tests/flows/dev_loop/integration/` (con `__init__.py`) con:
  - `test_pool_shared_mode_end_to_end` — 2 workers falsos, índice per-spec
    sintético con 4 tasks en 2 olas, worktree compartido ⇒ output agregado
    con files/shas/summaries de ambos workers y 0 `incomplete_tasks`.
  - `test_pool_isolated_mode_end_to_end` — repo git temporal real
    (sandbox de TASK-1861), 2 workers falsos que commitean archivos
    distintos en sus sub-worktrees ⇒ merges limpios ⇒ feature branch
    contiene todos los commits; sub-worktrees limpiados.
  - `test_isolated_merge_conflict_resolved` — workers falsos que editan el
    MISMO archivo ⇒ conflicto ⇒ resolutor falso lo resuelve (edita y
    commitea) ⇒ el run completa y `MergeReport.conflicts_resolved` lo
    registra.
  - `test_partial_completion_reaches_qa` — un worker programado para fallar
    2 veces una task ⇒ `DevelopmentOutput.incomplete_tasks` contiene esa
    task y el objeto queda en `shared["development_output"]` (lo que QA
    leerá); dependientes skipped no despachadas.
  - `test_multiplexer_discovers_worker_streams` — con un Redis falso/mock
    que responde a `scan`, sembrar claves
    `flow:R1:dispatch:development.w1` / `.w2` ⇒
    `FlowStreamMultiplexer._discover_dispatch_streams()` devuelve ambas.
  - `test_single_agent_regression_e2e` — flujo con nodo SIN pool sobre los
    fakes ⇒ exactamente 1 dispatch, `node_id="development"`.
- Fixtures compartidas en `tests/flows/dev_loop/integration/conftest.py`:
  índice per-spec sintético, `FakeDispatcher` programable (reutilizar/
  extraer el de TASK-1860 si quedó local), sandbox git, Redis falso con
  `scan`/`xadd`/`xrange` mínimos.

**NOT in scope**: tocar código de producción (solo tests); si un test
revela un bug, documentarlo en el Completion Note y coordinar el fix como
follow-up del task correspondiente.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/flows/dev_loop/integration/__init__.py` | CREATE | Paquete |
| `tests/flows/dev_loop/integration/conftest.py` | CREATE | Fixtures compartidas |
| `tests/flows/dev_loop/integration/test_pool_e2e.py` | CREATE | shared/isolated/conflicto/parcial/regresión |
| `tests/flows/dev_loop/integration/test_stream_discovery.py` | CREATE | Multiplexor descubre sub-streams |

---

## Codebase Contract (Anti-Hallucination)

> Rutas relativas a `packages/ai-parrot/src/`.

### Verified Imports
```python
# Producción (existente + creado por TASK-1857..1862):
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig, DevAgentSpec, DevelopmentOutput, ResearchOutput,
)
from parrot.flows.dev_loop.task_scheduler import TaskScheduler
from parrot.flows.dev_loop.agent_pool import DevAgentPool
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer
```

### Existing Signatures to Use
```python
# parrot/flows/dev_loop/streaming.py
class FlowStreamMultiplexer:
    # __init__ recibe redis + run_id (verificar firma exacta en el archivo)
    # self._dispatch_prefix = f"flow:{run_id}:dispatch:"    line 81
    async def _discover_dispatch_streams(self) -> List[str]:  # line 90
        # usa self._redis.scan(cursor, match=..., count=...) — lines 99-110
        # un fake de Redis necesita: async def scan(cursor, match=None, count=None)
        #   -> (next_cursor, [keys])  con next_cursor 0 para terminar

# ResearchOutput mínimo para fixtures (models.py:273):
#   jira_issue_key, spec_path, feat_id, branch_name, worktree_path (requeridos)

# tests/bots/flows/ — layout/estilo de tests async existente del repo
# (pytest-asyncio; ver tests/conftest.py para configuración global)
```

### Does NOT Exist
- ~~Redis real en CI para estos tests~~ — usar fake/mock con `scan` async;
  NO requerir servidor
- ~~dispatch real a Claude/Codex CLIs en tests~~ — SIEMPRE `FakeDispatcher`
  (Protocol `DevLoopCodeDispatcher`)
- ~~`tests/flows/dev_loop/integration/`~~ — lo crea ESTA task
- ~~helpers de fixtures previos para dev_loop~~ — no existen tests previos
  de `parrot.flows.dev_loop` en el repo; todo se crea aquí o vino de
  TASK-1857..1862

---

## Implementation Notes

### Pattern to Follow
```python
# Fake Redis mínimo para _discover_dispatch_streams:
class FakeRedis:
    def __init__(self, keys): self._keys = keys
    async def scan(self, cursor, match=None, count=None):
        import fnmatch
        return 0, [k for k in self._keys if fnmatch.fnmatch(k, match)]
```

### Key Constraints
- Marcar tests async con el patrón del repo (pytest-asyncio — revisar
  `tests/conftest.py` para el modo configurado).
- Los tests de git usan `tmp_path` y configuran `user.email`/`user.name`
  locales al repo temporal (CI no tiene global config garantizada).
- Determinismo: nada de sleeps arbitrarios; sincronizar por awaits.
- Si el sandbox de TASK-1861 quedó como fixture local de su archivo,
  extraerlo a `conftest.py` compartido SIN cambiar su comportamiento.

### References in Codebase
- Spec §4 Integration Tests — lista autoritativa de escenarios
- `tests/bots/flows/` — convenciones de tests de flows existentes
- `parrot/flows/dev_loop/streaming.py:60-130` — contrato exacto del descubrimiento

---

## Acceptance Criteria

- [ ] Los 6 escenarios de integración implementados y pasando
- [ ] Ningún test requiere red, Redis real ni CLIs de agentes
- [ ] Fixtures compartidas en conftest.py (sin duplicación con unit tests)
- [ ] All tests pass: `pytest tests/flows/dev_loop/ -v` (unit + integración completos)
- [ ] No linting errors: `ruff check tests/flows/dev_loop/`
- [ ] Suite completa del feature verde: criterio global del spec §5

---

## Test Specification

```python
# tests/flows/dev_loop/integration/test_pool_e2e.py — esqueleto
import pytest


class TestSharedMode:
    async def test_pool_shared_mode_end_to_end(self, pool_fixture): ...

class TestIsolatedMode:
    async def test_pool_isolated_mode_end_to_end(self, git_sandbox): ...
    async def test_isolated_merge_conflict_resolved(self, git_sandbox): ...

class TestPartial:
    async def test_partial_completion_reaches_qa(self, pool_fixture): ...

class TestRegression:
    async def test_single_agent_regression_e2e(self): ...


# tests/flows/dev_loop/integration/test_stream_discovery.py
class TestStreamDiscovery:
    async def test_multiplexer_discovers_worker_streams(self):
        """Claves development.w1/.w2 en FakeRedis ⇒ ambas descubiertas."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1857..1863 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirmar la firma real de `FlowStreamMultiplexer.__init__` y el modo pytest-asyncio del repo antes de escribir fixtures
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
