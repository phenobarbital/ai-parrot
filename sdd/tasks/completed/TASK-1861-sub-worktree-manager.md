# TASK-1861: SubWorktreeManager — sub-worktrees por worker, merge secuencial y resolutor de conflictos

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1857, TASK-1860
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 5** del spec — el modo `isolated`. Cada worker del
pool recibe su propio `git worktree` ramificado de la feature branch para
eliminar carreras de git entre agentes paralelos. Al cerrar cada ola, las
ramas de worker se mergean secuencialmente a la feature branch; un conflicto
dispara un dispatch resolutor (primer agente del pool, fallback claude-code);
si el resolutor falla, se lanza excepción (→ `failure_handler` del flow)
conservando las ramas para inspección forense.

---

## Scope

- Crear `parrot/flows/dev_loop/worktree_manager.py` con:
  - `MergeReport(BaseModel)`: `merged: list[str]` (worker branches),
    `conflicts_resolved: list[str]`, `kept_for_inspection: list[str]`.
  - `class SubWorktreeManager`:
    - `__init__(self, *, base_worktree: str, feature_branch: str,
      worktree_base_path: str)` — valida que `base_worktree` vive bajo
      `worktree_base_path`.
    - `async create(self, worker_id: str) -> str` — `git worktree add -b
      <feature_branch>--<worker_id> <worktree_base_path>/<...>/<worker_id>
      <feature_branch>` vía `asyncio.create_subprocess_exec`; devuelve la
      ruta absoluta (SIEMPRE bajo `worktree_base_path` — check R4).
    - `async merge_sequential(self, *, resolver: Optional[Callable]) ->
      MergeReport` — por cada rama de worker con commits nuevos, merge a la
      feature branch (en el worktree base); conflicto ⇒ invocar `resolver`
      (callable async que recibe ruta + descripción del conflicto y devuelve
      bool éxito); resolutor falla o ausente ⇒ `SubWorktreeMergeError` con
      las rutas conservadas.
    - `async cleanup(self, *, keep_on_conflict: bool = True) -> None` —
      `git worktree remove` + `git worktree prune` de los sub-worktrees
      mergeados; los conflictivos se conservan si `keep_on_conflict`.
  - `SubWorktreeMergeError(Exception)` — transporta rama/worktree/stderr.
- El "resolver" aquí es un callable inyectado — la política (primer agente
  del pool, fallback claude-code) la implementa el nodo en TASK-1862; esta
  task solo define el hook y lo invoca en el punto correcto.
- Unit tests sobre un repo git temporal (fixture sandbox): create/merge
  limpio, conflicto→resolver llamado, resolver falla→error con ramas
  conservadas, cleanup.

**NOT in scope**: política de selección del resolutor (TASK-1862), dispatch
real de agentes, modo shared.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py` | CREATE | Manager de sub-worktrees |
| `tests/flows/dev_loop/test_worktree_manager.py` | CREATE | Tests sobre repo git temporal |

---

## Codebase Contract (Anti-Hallucination)

> Rutas relativas a `packages/ai-parrot/src/`.

### Verified Imports
```python
import asyncio                      # create_subprocess_exec — patrón CLI existente
import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional
from pydantic import BaseModel, Field
from parrot.flows.dev_loop.models import ResearchOutput   # models.py:273
```

### Existing Signatures to Use
```python
# parrot/flows/dev_loop/models.py
class ResearchOutput(BaseModel):        # line 273
    branch_name: str                    # line 303  ⇒ feature_branch
    worktree_path: str                  # line 308  ⇒ base_worktree

# parrot/flows/dev_loop/dispatcher.py — referencia del check R4 que las
# rutas creadas deben satisfacer (lo aplica el dispatcher en cada dispatch):
#   _enforce_cwd_under_worktree_base(cwd, profile)   line 228
# conf.WORKTREE_BASE_PATH — raíz permitida (se recibe como parámetro
# worktree_base_path; NO leer conf directamente en este módulo para
# mantenerlo puro/testeable).
```

### Does NOT Exist
- ~~`parrot/flows/dev_loop/worktree_manager.py` / `SubWorktreeManager` / `MergeReport` / `SubWorktreeMergeError`~~ — los crea ESTA task
- ~~helper git async previo en dev_loop~~ — no hay wrapper git en `parrot/flows/dev_loop/`; usar `asyncio.create_subprocess_exec("git", ...)` directamente
- ~~GitPython / dulwich~~ — PROHIBIDO añadir dependencias; solo git CLI
- ~~auto-resolución de conflictos vía `git merge -X`~~ — NO usar estrategias ours/theirs silenciosas; conflicto ⇒ resolver hook o error

---

## Implementation Notes

### Pattern to Follow
```python
async def _git(self, *args: str, cwd: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(), err.decode()
```

### Key Constraints
- Nombres de rama de worker: `"{feature_branch}--{worker_id}"` (p. ej.
  `feat-130-fix--development.w1` → sanear puntos si git los rechaza:
  reemplazar `.` por `-` en el sufijo).
- Merge SECUENCIAL y determinista (orden de worker_id) — nunca merges
  concurrentes sobre la misma rama.
- Detección de conflicto: exit code del `git merge` + `git status
  --porcelain` con entradas `UU/AA/...`; abortar con `git merge --abort`
  ANTES de invocar al resolver si el resolver trabaja re-ejecutando, o
  dejar el estado conflictivo si el resolver edita in-place — documentar la
  elección en docstring (el resolver del spec edita in-place el worktree
  base y commitea).
- `cleanup` NUNCA borra el worktree base ni el repo principal; solo los
  sub-worktrees que este manager creó.
- Todo async; sin `subprocess.run` bloqueante.

### References in Codebase
- Spec §2 (modo isolated) y §7 Known Risks (conservación forense, prune defensivo)
- `.claude/rules/using-git-worktrees.md` — convenciones de worktree del repo

---

## Acceptance Criteria

- [ ] `create()` produce sub-worktrees bajo `worktree_base_path` con rama por worker
- [ ] Rutas devueltas satisfacen el layout que exige el check R4 del dispatcher
- [ ] Merge limpio de N ramas ⇒ feature branch contiene todos los commits; `MergeReport.merged` correcto
- [ ] Conflicto ⇒ `resolver` invocado con contexto; éxito ⇒ merge continúa y `conflicts_resolved` lo registra
- [ ] Resolver falla/ausente ⇒ `SubWorktreeMergeError` y ramas/worktrees conservados (`kept_for_inspection`)
- [ ] `cleanup()` elimina solo lo mergeado + `git worktree prune`; conserva conflictivos con `keep_on_conflict=True`
- [ ] All tests pass: `pytest tests/flows/dev_loop/test_worktree_manager.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py`

---

## Test Specification

```python
# tests/flows/dev_loop/test_worktree_manager.py
import pytest
from parrot.flows.dev_loop.worktree_manager import (
    SubWorktreeManager, SubWorktreeMergeError,
)


@pytest.fixture
async def git_sandbox(tmp_path):
    """Repo git real en tmp_path: init, commit inicial, feature branch,
    y un 'worktree base' clonado como worktree de esa rama. Devuelve
    (base_worktree, feature_branch, worktree_base_path=tmp_path)."""


class TestCreate:
    async def test_paths_under_base(self, git_sandbox): ...

class TestMerge:
    async def test_clean_merge_two_workers(self, git_sandbox): ...
    async def test_conflict_calls_resolver(self, git_sandbox): ...
    async def test_resolver_failure_raises_and_keeps(self, git_sandbox):
        with pytest.raises(SubWorktreeMergeError):
            ...

class TestCleanup:
    async def test_removes_merged_keeps_conflicted(self, git_sandbox): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1857, TASK-1860 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code
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
**Notes**: Implemented `MergeReport`, `SubWorktreeMergeError`, and
`SubWorktreeManager` in `parrot/flows/dev_loop/worktree_manager.py`:
`__init__` validates `base_worktree` lives under `worktree_base_path`
(`ValueError` otherwise); `create(worker_id)` runs `git worktree add -b
<feature_branch>--<sanitized-worker-id> <path> <feature_branch>` via
`asyncio.create_subprocess_exec`, sanitizing `.` → `-` in the branch
suffix, path always under `worktree_base_path`; `merge_sequential(resolver=)`
merges worker branches strictly in `worker_id` order against the same
`base_worktree` (never concurrent), skips workers with no new commits,
detects conflicts via `git merge` exit code + `git status --porcelain`
(`UU`/`AA`/... entries) for diagnostics, invokes the injected `resolver`
WITHOUT aborting first (resolver edits in-place + commits per the spec's
resolver contract — documented in the module docstring), aborts the merge
only when the resolver is absent/fails, and raises `SubWorktreeMergeError`
while preserving the sub-worktree; `cleanup(keep_on_conflict=)` removes
merged sub-worktrees + `git worktree prune`, preserving conflicted ones by
default. Added `packages/ai-parrot/tests/flows/dev_loop/test_worktree_manager.py`
(7 tests, on a REAL temporary git repo/worktree sandbox fixture — no
mocking of git itself): paths-under-base, base-worktree-outside-base
rejection, clean two-worker merge, conflict→resolver-invoked-and-succeeds,
resolver-failure→raises+keeps, no-resolver→raises+keeps,
cleanup-removes-merged-keeps-conflicted. All 7 pass; `ruff check` clean.
Full `packages/ai-parrot/tests/flows/dev_loop/` suite (438 tests) passes
except the same 4 pre-existing full-suite-ordering failures already
verified unrelated to this feature in TASK-1857/1859/1860's notes.

**Deviations from spec**: None — implemented exactly as scoped. Conflict-
resolution ordering (resolver invoked before any abort, only aborting on
resolver absence/failure) was an implementation decision required to
satisfy the spec's own note that "el resolutor edita in-place el worktree
base y commitea" (§ Implementation Notes); documented explicitly in the
module docstring per that note's instruction to "documentar la elección."
