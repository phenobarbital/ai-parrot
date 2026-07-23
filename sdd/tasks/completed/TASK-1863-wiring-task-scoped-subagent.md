# TASK-1863: Wiring factories/flow/server + instrucción task-scoped en sdd-worker.md

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1860, TASK-1862
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 7** del spec: propagar la config del pool desde el
server/env hasta el `DevelopmentNode` a través de `build_dev_loop_flow` /
`build_dev_loop_node_factories`, y enseñar al subagente `sdd-worker` a
respetar el `task_id` del brief (modo task-scoped) en sus DOS copias
dual-sourced.

---

## Scope

- Modificar `parrot/flows/dev_loop/factories.py`:
  `build_dev_loop_node_factories(...)` acepta además (keyword-only,
  opcionales, default `None`): `development_pool_config`,
  `development_dispatcher_builder`, `development_pool_max`; el
  `development_factory` los pasa al `DevelopmentNode`.
- Modificar `parrot/flows/dev_loop/flow.py`: `build_dev_loop_flow(...)`
  acepta y propaga los mismos parámetros hacia
  `build_dev_loop_node_factories`.
- Modificar `examples/dev_loop/server.py`: tras el bloque single-agent
  actual, resolver el pool del env (`parse_pool_env` + `resolve_pool_max`
  de TASK-1859) y pasarlo a `build_dev_loop_flow`; log INFO con el pool
  efectivo (backends+counts+isolation) o "single-agent mode".
- Actualizar `sdd-worker.md` en AMBAS copias dual-sourced
  (`.claude/agents/sdd-worker.md` y
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`):
  añadir sección "Task-scoped mode": si el brief JSON contiene `task_id`,
  implementar SOLO esa task (no tomar otras aunque estén desbloqueadas),
  commitear solo su alcance, y reflejar solo esa task en el output; sin
  `task_id`, comportamiento actual sin cambios.
- Tests: firma/propagación de factories y flow (fakes), parseo del pool en
  el server importable (si el server expone helper), y verificación de que
  ambas copias del markdown quedaron idénticas en la sección nueva.

**NOT in scope**: lógica del pool/nodo (hecha en 1860/1862), tests
end-to-end (TASK-1864).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` | MODIFY | Parámetros pool en factories |
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | Propagación en build_dev_loop_flow |
| `examples/dev_loop/server.py` | MODIFY | Resolver pool del env + pasarlo al flow |
| `.claude/agents/sdd-worker.md` | MODIFY | Sección task-scoped |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Sección task-scoped (copia idéntica) |
| `tests/flows/dev_loop/test_pool_wiring.py` | CREATE | Tests de propagación |

---

## Codebase Contract (Anti-Hallucination)

> Rutas relativas a `packages/ai-parrot/src/` salvo `examples/` y `.claude/`.

### Verified Imports
```python
# parrot/flows/dev_loop/factories.py:24 (existente):
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
# tras TASK-1859:
from parrot.flows.dev_loop.agent_builder import parse_pool_env, resolve_pool_max
```

### Existing Signatures to Use
```python
# parrot/flows/dev_loop/factories.py
def build_dev_loop_node_factories(
    ...,
    development_dispatcher: Optional[Any] = None,   # line 45
    development_profile: Optional[Any] = None,      # line 46
) -> ...:
    development_dispatcher = development_dispatcher or dispatcher  # line 77
    def development_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:  # line 99
        return DevelopmentNode(
            dispatcher=development_dispatcher,      # line 102
            dispatch_profile=development_profile,   # line 103
        )
    # registrada como "dev_loop.development"          line 141

# parrot/flows/dev_loop/flow.py
def build_dev_loop_flow(
    ...,
    development_dispatcher: Optional[Any] = None,   # line 168
    development_profile: Optional[Any] = None,      # line 169
) -> ...:
    # pasa ambos a build_dev_loop_node_factories      lines 227-228
    # edges: research→development→qa                  lines 285-286

# parrot/flows/dev_loop/_subagent_defs.py
_VALID_NAMES = frozenset({"sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"})  # line 33
# Dual-sourcing (docstring lines 13-20): repo `.claude/agents/<name>.md` +
# paquete `_subagent_data/<name>.md`. TODA edición va a AMBAS copias.

# tras TASK-1862 — firma nueva del nodo:
class DevelopmentNode(DevLoopNode):
    def __init__(self, *, dispatcher, dispatch_profile=None, name="development",
                 pool_config=None, dispatcher_builder=None, pool_max=4) -> None: ...
```

### Does NOT Exist
- ~~parámetros `development_pool_*` en factories/flow~~ — los añade ESTA task
- ~~`sdd-worker-task` como subagente~~ — NO crear; la decisión resuelta es
  instrucción condicional en el `sdd-worker.md` existente, sin tocar
  `_VALID_NAMES` ni el `Literal` de `ClaudeCodeDispatchProfile.subagent`
  (models.py:389)
- ~~loader que sincronice las dos copias del markdown~~ — no existe; la
  sincronización es manual (por eso el test de igualdad de sección)

---

## Implementation Notes

### Pattern to Follow
```python
# factories.py — mismo estilo que development_dispatcher/profile:
development_pool_config: Optional[Any] = None,
development_dispatcher_builder: Optional[Any] = None,
development_pool_max: int = 4,
```
```markdown
<!-- sdd-worker.md — sección nueva, misma redacción en ambas copias -->
## Task-Scoped Mode (FEAT-323)
If the brief JSON contains a `task_id` field, implement ONLY that task...
```

### Key Constraints
- Todos los parámetros nuevos son opcionales con default `None`/`4` —
  llamadas existentes a `build_dev_loop_flow` siguen compilando sin cambios.
- El server: el pool del env NO reemplaza la selección single-agent actual
  (`DEV_LOOP_DEVELOPMENT_AGENT`) — conviven: sin `DEV_LOOP_DEV_AGENTS`,
  todo queda como hoy.
- La sección del markdown debe dejar claro que sin `task_id` la conducta
  actual NO cambia (criterio del spec).

### References in Codebase
- `parrot/flows/dev_loop/factories.py:45-141` y `flow.py:168-228` — puntos de extensión exactos
- `parrot/flows/dev_loop/_subagent_defs.py:13-33` — contrato dual-sourcing

---

## Acceptance Criteria

- [ ] `build_dev_loop_flow`/`build_dev_loop_node_factories` aceptan y propagan los parámetros del pool (llamadas existentes intactas)
- [ ] `development_factory` construye `DevelopmentNode` con el pool cuando se provee
- [ ] Server: `DEV_LOOP_DEV_AGENTS` presente ⇒ pool pasado al flow + log del pool efectivo; ausente ⇒ conducta actual
- [ ] Ambas copias de `sdd-worker.md` contienen la sección task-scoped idéntica
- [ ] La sección instruye: con `task_id` SOLO esa task; sin `task_id` conducta actual
- [ ] All tests pass: `pytest tests/flows/dev_loop/test_pool_wiring.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/factories.py packages/ai-parrot/src/parrot/flows/dev_loop/flow.py`

---

## Test Specification

```python
# tests/flows/dev_loop/test_pool_wiring.py
import pytest


class TestFactoryWiring:
    def test_factories_accept_pool_params(self):
        """build_dev_loop_node_factories(...pool params...) no lanza y el
        development_factory produce un nodo con pool_config seteado."""

    def test_existing_calls_unchanged(self):
        """Llamada con la firma antigua (sin params nuevos) sigue funcionando."""


class TestSubagentDefSync:
    def test_both_copies_have_identical_task_scoped_section(self):
        """Extraer la sección '## Task-Scoped Mode' de ambos .md y comparar."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1860, TASK-1862 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirmar la firma final que TASK-1862 dejó en `DevelopmentNode.__init__` antes de cablear
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
**Notes**: `build_dev_loop_node_factories` gained
`development_pool_config`/`development_dispatcher_builder`/
`development_pool_max=4` (keyword-only, optional), passed straight through
to `DevelopmentNode(...)` in `development_factory`. `build_dev_loop_flow`
gained the same three params and forwards them to
`build_dev_loop_node_factories`. `examples/dev_loop/server.py`: after the
existing single-agent selection block, resolves
`parse_pool_env(conf.config.get)` + `resolve_pool_max(conf.config.get)`
(TASK-1859), builds a `functools.partial(build_dispatcher, redis_url=...,
max_concurrent=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS)` dispatcher_builder only
when a pool resolves, logs the effective pool (backends×counts +
isolation + pool_max) or "single-agent mode", and passes all three new
params to `build_dev_loop_flow`. Added the "## Task-Scoped Mode (FEAT-323)"
section (byte-identical, verified via a regex-extraction unit test) to
BOTH dual-sourced copies of `sdd-worker.md`
(`.claude/agents/sdd-worker.md` and `_subagent_data/sdd-worker.md`),
inserted right after `## Input`: with a `task_id` field in the brief,
implement ONLY that task, skip feature-level bookkeeping, update SDD state
for only that task; without `task_id`, behavior is unchanged. Did NOT
touch `_VALID_NAMES` or `ClaudeCodeDispatchProfile.subagent`'s `Literal`
(per contract). Added
`packages/ai-parrot/tests/flows/dev_loop/test_pool_wiring.py` (4 tests:
factories accept+propagate pool params, existing no-pool-params call still
works with `None`/`4` defaults, both `sdd-worker.md` copies have an
identical "## Task-Scoped Mode" section, the section states the `task_id`-
conditional behavior). All 4 pass; full
`packages/ai-parrot/tests/flows/dev_loop/` suite (448 tests) passes except
the same 4 pre-existing full-suite-ordering failures already verified
unrelated to this feature. `ruff check` clean.

**Deviations from spec**: Noted (but did not fix) a **pre-existing**
divergence between the two `sdd-worker.md` copies discovered while adding
the new section: `.claude/agents/sdd-worker.md` is already on the FEAT-145
per-spec-index workflow (worktree-local index, no `cd` back to a main
repo), while `_subagent_data/sdd-worker.md` still describes the older
"code in worktree, state on `dev`" workflow with explicit `cd` round-trips.
This predates FEAT-323 and is out of this task's scope (the acceptance
criteria and test only require the NEW "Task-Scoped Mode" section itself
to be identical between the two copies, which it is) — flagging here so a
future task can reconcile the rest of the file.
