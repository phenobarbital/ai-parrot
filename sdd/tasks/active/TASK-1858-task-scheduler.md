# TASK-1858: TaskScheduler determinista (olas por depends_on desde el índice per-spec)

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1857
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 2** del spec. El scheduler es la pieza que divide el
trabajo SIN LLM: lee `sdd/tasks/index/<feature>.json` desde el worktree
creado por sdd-research y produce "olas" de tasks despachables (todas sus
`depends_on` completas). Es puro y determinista — la clave de que el pool
sea testeable.

---

## Scope

- Crear `parrot/flows/dev_loop/task_scheduler.py` con:
  - `TaskRef(BaseModel)`: `id: str`, `title: str = ""`, `status: str`,
    `depends_on: list[str]` (subset del task-entry del índice per-spec).
  - `class TaskScheduler`:
    - `@classmethod from_index_file(cls, path: Path) -> "TaskScheduler"` —
      parsea el JSON del índice per-spec; tasks con `status` ya `"done"` se
      consideran completas de entrada.
    - `@classmethod from_worktree(cls, worktree_path: str, feature_slug: str)` —
      conveniencia: resuelve `<worktree>/sdd/tasks/index/<feature_slug>.json`.
    - `next_wave(self) -> list[TaskRef]` — tasks pendientes con todas sus
      deps completas; lista vacía cuando no queda nada despachable.
    - `mark_done(self, task_id: str) -> None`
    - `mark_failed(self, task_id: str) -> None` — marca la task fallida y
      propaga `skipped` (transitivo) a todas sus dependientes.
    - `pending()`, `failed()`, `skipped()`, `done()` — vistas de estado.
    - Detección de ciclos en `depends_on` al construir ⇒ `ValueError` con
      los ids del ciclo.
  - Excepción/señal de degradación: índice ausente o JSON ilegible ⇒
    `from_index_file`/`from_worktree` devuelven `None` (NO lanzan) — el
    caller (DevelopmentNode) degrada a single-agent con warning.
- Unit tests: olas, ciclos, índice ausente, propagación skipped.

**NOT in scope**: despacho real (TASK-1860), lectura de config del pool,
cambios al nodo.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` | CREATE | Scheduler determinista |
| `tests/flows/dev_loop/test_task_scheduler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Rutas relativas a `packages/ai-parrot/src/`.

### Verified Imports
```python
from pydantic import BaseModel, Field   # patrón de models.py
import json                             # stdlib
from pathlib import Path                # stdlib
import logging                          # logging.getLogger(__name__)
```

### Existing Signatures to Use
```json
// Esquema del índice per-spec (FEAT-145, documentado en CLAUDE.md y
// verificable en sdd/tasks/index/*.json del propio repo):
{
  "feature": "<feature-slug>",
  "feature_id": "FEAT-<NNN>",
  "tasks": [
    {"id": "TASK-<NNN>", "feature_id": "FEAT-<NNN>", "feature": "<slug>",
     "status": "pending|in-progress|done", "depends_on": ["TASK-<X>"]}
  ]
}
```
```python
# parrot/flows/dev_loop/models.py — disponible tras TASK-1857:
class ResearchOutput(BaseModel):   # line 273
    worktree_path: str             # line 308  (raíz donde vive sdd/tasks/index/)
    feat_id: str                   # line 298
```

### Does NOT Exist
- ~~`TaskScheduler` / `TaskRef` / `parrot/flows/dev_loop/task_scheduler.py`~~ — los crea ESTA task
- ~~`ResearchOutput.tasks`~~ — research NO transporta tasks; SIEMPRE leer el índice del worktree
- ~~`sdd/tasks/.index.json` como fuente~~ — el monolito legacy está EXCLUIDO; solo índices per-spec `sdd/tasks/index/<feature>.json`
- ~~dependencia de red o Redis en el scheduler~~ — es puro: filesystem + memoria

---

## Implementation Notes

### Pattern to Follow
```python
# Kahn topological check para ciclos al construir; olas = filtrado simple:
def next_wave(self) -> list[TaskRef]:
    done = self._done | self._external_done
    return [t for t in self._tasks.values()
            if t.id in self._pending and all(d in done for d in t.depends_on)]
```

### Key Constraints
- Sin I/O async necesario (archivo local pequeño) — pero NUNCA llamarlo
  dentro del event loop con archivos remotos; es sync puro y barato.
- `mark_failed` propaga `skipped` TRANSITIVAMENTE (si B depende de A
  fallida y C depende de B ⇒ B y C skipped).
- Deps que apuntan a ids inexistentes en el índice ⇒ tratarlas como no
  satisfechas + warning (no crash).
- Logging con `logging.getLogger(__name__)`.

### References in Codebase
- `sdd/tasks/index/*.json` (repo raíz) — ejemplos reales del esquema
- Spec §2 New Public Interfaces + §3 Module 2

---

## Acceptance Criteria

- [ ] Grafo A←B, C←B produce olas `[B]`, luego `[A, C]` (tras mark_done(B))
- [ ] Ciclo en depends_on ⇒ `ValueError` al construir, con ids del ciclo
- [ ] Índice ausente/JSON corrupto ⇒ `None` (degradación), nunca excepción
- [ ] `mark_failed` propaga skipped transitivo; skipped nunca aparece en `next_wave()`
- [ ] Tasks con `status: "done"` en el índice cuentan como completas de entrada
- [ ] All tests pass: `pytest tests/flows/dev_loop/test_task_scheduler.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`
- [ ] `from parrot.flows.dev_loop.task_scheduler import TaskScheduler` funciona

---

## Test Specification

```python
# tests/flows/dev_loop/test_task_scheduler.py
import json
import pytest
from parrot.flows.dev_loop.task_scheduler import TaskScheduler


@pytest.fixture
def index_file(tmp_path):
    def _make(tasks):
        p = tmp_path / "feature.json"
        p.write_text(json.dumps({"feature": "f", "feature_id": "FEAT-999",
                                 "tasks": tasks}))
        return p
    return _make


class TestWaves:
    def test_two_waves(self, index_file):
        p = index_file([
            {"id": "TASK-1", "status": "pending", "depends_on": []},
            {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
            {"id": "TASK-3", "status": "pending", "depends_on": ["TASK-1"]},
        ])
        s = TaskScheduler.from_index_file(p)
        assert [t.id for t in s.next_wave()] == ["TASK-1"]
        s.mark_done("TASK-1")
        assert {t.id for t in s.next_wave()} == {"TASK-2", "TASK-3"}

    def test_cycle_raises(self, index_file):
        p = index_file([
            {"id": "TASK-1", "status": "pending", "depends_on": ["TASK-2"]},
            {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
        ])
        with pytest.raises(ValueError):
            TaskScheduler.from_index_file(p)

    def test_missing_index_returns_none(self, tmp_path):
        assert TaskScheduler.from_index_file(tmp_path / "nope.json") is None

    def test_mark_failed_skips_dependents_transitively(self, index_file):
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1857 in `sdd/tasks/completed/`
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
