# TASK-1857: Pool config & output models (`DevAgentSpec`, `DevAgentPoolConfig`, extensiones WorkBrief/DevelopmentOutput)

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 1** del spec. Todo el feature se apoya en estos
contratos Pydantic: el pool de sub-agentes se declara con `DevAgentSpec`/
`DevAgentPoolConfig`, viaja opcionalmente en `WorkBrief`, cada dispatch
task-scoped envuelve el `ResearchOutput` en un `TaskScopedBrief`, y el
resultado agregado extiende `DevelopmentOutput` con campos backward-compatible.

---

## Scope

- Implementar en `parrot/flows/dev_loop/models.py`:
  - `DevAgentBackend` (Literal: `"claude-code" | "codex" | "gemini" | "nvidia" | "grok" | "zai" | "moonshot"`).
  - `DevAgentSpec(BaseModel)`: `agent: DevAgentBackend`, `model: str = ""`,
    `count: int = 1` (con `ge=1`).
  - `DevAgentPoolConfig(BaseModel)`: `agents: list[DevAgentSpec]`
    (`min_length=1`), `isolation_mode: Literal["shared", "isolated"] = "shared"`.
  - `WorkerSummary(BaseModel)`: `worker_id: str`, `agent: str`, `model: str`,
    `tasks_completed: list[str]`, `tasks_failed: list[str]`, `summary: str`.
  - `TaskScopedBrief(BaseModel)`: `research: ResearchOutput`, `task_id: str`.
- Extender `WorkBrief` con campos NUEVOS opcionales (al final de la clase):
  `dev_agents: Optional[List[DevAgentSpec]] = None`,
  `dev_isolation: Optional[Literal["shared", "isolated"]] = None`.
- Extender `DevelopmentOutput` con defaults backward-compatible:
  `incomplete_tasks: List[str] = Field(default_factory=list)`,
  `worker_summaries: List[WorkerSummary] = Field(default_factory=list)`.
- Exportar los nombres nuevos donde `models.py` ya exporte los existentes
  (revisar `__all__` del módulo y `parrot/flows/dev_loop/__init__.py`).
- Escribir unit tests (defaults, validadores, back-compat de payloads viejos).

**NOT in scope**: scheduler (TASK-1858), builder/env parsing (TASK-1859),
pool (TASK-1860), cambios a nodos o dispatchers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | Modelos nuevos + extensiones WorkBrief/DevelopmentOutput |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Exportar los modelos nuevos junto a los existentes |
| `tests/flows/__init__.py` | CREATE | Paquete de tests (si no existe) |
| `tests/flows/dev_loop/__init__.py` | CREATE | Paquete de tests |
| `tests/flows/dev_loop/test_pool_models.py` | CREATE | Unit tests de los modelos |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: usar estos imports/firmas VERBATIM. No inventar nada fuera
> de esta lista sin verificar con `grep`/`read`. Rutas relativas a
> `packages/ai-parrot/src/`.

### Verified Imports
```python
# models.py ya usa (verificado en el propio archivo):
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Literal, Optional
```

### Existing Signatures to Use
```python
# parrot/flows/dev_loop/models.py
class WorkBrief(BaseModel):                               # line 118
    kind: WorkKind = Field(default="bug")                 # line 131
    summary: str                                          # line 141 (min 10, max 255)
    description: str = ""                                 # line 150
    affected_component: str                               # line 158
    log_sources: List[LogSource]                          # line 159
    acceptance_criteria: List[AcceptanceCriterion]        # line 160 (min_length=1)
    escalation_assignee: str                              # line 161
# NOTA: existe el alias módulo-level `BugBrief = WorkBrief` — no romperlo.

class ResearchOutput(BaseModel):                          # line 273
    model_config = ConfigDict(populate_by_name=True)      # line 286
    jira_issue_key: str                                   # line 288
    spec_path: str                                        # line 293
    feat_id: str                                          # line 298
    branch_name: str                                      # line 303
    worktree_path: str                                    # line 308
    repo_path: str = ""                                   # line 313
    log_excerpts: List[str]                               # line 323

class DevelopmentOutput(BaseModel):                       # line 329
    files_changed: List[str]                              # line 332
    commit_shas: List[str]                                # line 333
    summary: str                                          # line 334
```

### Does NOT Exist
- ~~`WorkBrief.dev_agents` / `WorkBrief.dev_isolation`~~ — los crea ESTA task
- ~~`DevAgentSpec` / `DevAgentPoolConfig` / `WorkerSummary` / `TaskScopedBrief`~~ — los crea ESTA task
- ~~`DevelopmentOutput.incomplete_tasks` / `.worker_summaries`~~ — los crea ESTA task
- ~~`ResearchOutput.tasks`~~ — NO existe y NO se añade
- ~~import de `claude_agent_sdk` en models.py~~ — PROHIBIDO a nivel de módulo (regla del spec)

---

## Implementation Notes

### Pattern to Follow
```python
# Mismo estilo que los modelos existentes de models.py: BaseModel + Field
# con description, defaults explícitos, Literal para enums pequeños.
class DevAgentSpec(BaseModel):
    agent: DevAgentBackend = Field(..., description="Backend → dispatcher existente.")
    model: str = Field("", description="'' ⇒ default del backend.")
    count: int = Field(1, ge=1, description="Réplicas de este spec.")
```

### Key Constraints
- Pydantic v2; NO imports de `claude_agent_sdk` a nivel de módulo.
- Campos nuevos de `WorkBrief`/`DevelopmentOutput` SIEMPRE con default —
  payloads existentes deben validar sin cambios (tests de regresión).
- Google-style docstrings en cada modelo nuevo.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` — estilo y ubicación
- Spec §2 Data Models — diseño autoritativo

---

## Acceptance Criteria

- [ ] Modelos nuevos implementados y exportados
- [ ] `WorkBrief` sin `dev_agents` valida payloads pre-existentes (test)
- [ ] `DevelopmentOutput` sin campos nuevos valida payloads viejos (test)
- [ ] `DevAgentSpec(count=0)` lanza ValidationError; `DevAgentPoolConfig(agents=[])` también
- [ ] All tests pass: `pytest tests/flows/dev_loop/test_pool_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/models.py`
- [ ] `from parrot.flows.dev_loop.models import DevAgentSpec, DevAgentPoolConfig` funciona

---

## Test Specification

```python
# tests/flows/dev_loop/test_pool_models.py
import pytest
from pydantic import ValidationError
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig, DevAgentSpec, DevelopmentOutput, WorkBrief, WorkerSummary,
)


class TestDevAgentSpec:
    def test_defaults(self):
        s = DevAgentSpec(agent="claude-code")
        assert s.model == "" and s.count == 1

    def test_count_ge_1(self):
        with pytest.raises(ValidationError):
            DevAgentSpec(agent="codex", count=0)


class TestPoolConfig:
    def test_isolation_default_shared(self):
        c = DevAgentPoolConfig(agents=[DevAgentSpec(agent="zai")])
        assert c.isolation_mode == "shared"

    def test_agents_min_length(self):
        with pytest.raises(ValidationError):
            DevAgentPoolConfig(agents=[])


class TestBackCompat:
    def test_workbrief_without_pool_fields(self):
        """Payloads existentes (sin dev_agents) validan igual que hoy."""
        # construir WorkBrief válido mínimo y assert dev_agents is None

    def test_development_output_old_payload(self):
        out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="x")
        assert out.incomplete_tasks == [] and out.worker_summaries == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
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
**Notes**: Implemented `DevAgentBackend`, `DevAgentSpec`, `DevAgentPoolConfig`,
`WorkerSummary`, `TaskScopedBrief` in `models.py`, plus back-compat-safe
`WorkBrief.dev_agents`/`dev_isolation` and `DevelopmentOutput.incomplete_tasks`/
`worker_summaries` (all with defaults). Exported the new names from
`parrot/flows/dev_loop/__init__.py`. Added
`packages/ai-parrot/tests/flows/dev_loop/test_pool_models.py` (13 new tests);
`tests/flows/__init__.py` and `tests/flows/dev_loop/__init__.py` already existed
so no new package files were needed there. Full existing
`packages/ai-parrot/tests/flows/dev_loop/test_models.py` +
`test_models_feat250.py` + new suite (45 tests) pass; `ruff check` clean.
Note: had to `uv pip install navigator-eventbus` (missing after a recent
`dev` sync) and copy two pre-built Cython `.so` artifacts
(`parrot/utils/types.*.so`, `parrot/utils/parsers/toml.*.so`, both
gitignored build outputs with identical `.pyx` sources to the main repo)
into the worktree to get the dev_loop test suite importable — pre-existing
environment issue, unrelated to this task's scope, not committed (gitignored).
Also confirmed 4 pre-existing failures in `test_server_repo_wiring.py` /
`test_webhook.py` (full-suite ordering pollution) are present identically
with and without this task's changes (verified via `git stash`).

**Deviations from spec**: None.
