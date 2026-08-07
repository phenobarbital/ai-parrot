# TASK-2179: Land the `plan/` module in the package

**Feature**: FEAT-419 — ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent
**Spec**: `sdd/specs/execution-plan-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The plan-execution machinery (models, validator, compiler, `PlanToolNode`)
is already written and tested standalone at `sdd/artifacts/plan/` (60 tests).
This task drops it into the real package at
`packages/ai-parrot/src/parrot/bots/flows/plan/` so every other task of
FEAT-419 can import it. Implements spec §3 Module 1.

---

## Scope

- Copy `models.py`, `paths.py`, `guards.py`, `facets.py`, `validator.py`,
  `compile.py`, `node.py`, `__init__.py` from `sdd/artifacts/plan/` to
  `packages/ai-parrot/src/parrot/bots/flows/plan/` VERBATIM except for the
  import-fallback collapse below.
- Do NOT copy `_shim.py` (standalone test scaffold). Collapse the
  `try: from parrot... except ImportError: from ._shim import ...` /
  `from flow_definition import ...` fallbacks in `node.py` and `compile.py`
  to the real `parrot.bots.flows.*` imports only.
- Move `test_plan.py` and `test_node.py` to
  `packages/ai-parrot/tests/bots/flows/plan/` (create the directory +
  `__init__.py` if the sibling test packages have one), adjusting imports
  to `from parrot.bots.flows.plan import ...`. Drop/replace any shim-based
  fixtures with the real `Node`/`AgentTaskMachine`.
- All 60 tests pass against real imports.

**NOT in scope**: the toolkit (TASK-2180+), any change to model/validator/
node semantics, registering `"tool"` at import time (registration stays
lazy via `ensure_tool_node_registered`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/{__init__,models,paths,guards,facets,validator,compile,node}.py` | CREATE | Verbatim drop-in minus shim fallbacks |
| `packages/ai-parrot/tests/bots/flows/plan/{test_plan,test_node}.py` | CREATE | Relocated test suite (60 tests) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# These are the REAL targets the shim fallbacks collapse to:
from parrot.bots.flows.flow.definition import (      # used by compile.py
    EdgeDefinition, FlowDefinition, FlowMetadata, NodeDefinition,
)
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node
from parrot.bots.flows.core.node import Node          # PlanToolNode base
from parrot.bots.flows.core.fsm import AgentTaskMachine
```

### Existing Signatures to Use
```python
# sdd/artifacts/plan/node.py:50-53 — the fallback to collapse:
#   try: from parrot.bots.flows.core.node import Node as _BaseNode
#   except ImportError: from ._shim import Node as _BaseNode
# sdd/artifacts/plan/compile.py:55-68 — same pattern for definition imports.
# sdd/artifacts/plan/compile.py:141 — ensure_tool_node_registered(node_cls):
#   idempotent, raises ValueError on a conflicting "tool" registration.
# sdd/artifacts/plan/__init__.py — the public API (__all__) to preserve.
```

### Does NOT Exist
- ~~`NODE_REGISTRY["tool"]`~~ — must remain unregistered after this task
  (registration is lazy, done by the toolkit at first compile).
- ~~`parrot.bots.flows.plan`~~ — does not exist until this task creates it.
- ~~`_shim.py` in the package~~ — never shipped.

---

## Implementation Notes

### Key Constraints
- Verbatim drop-in: no renames, no "improvements", no docstring edits. The
  60 tests are the contract.
- `plan/__init__.py` module docstring already states the intended location —
  keep it.
- Check sibling test dirs (`packages/ai-parrot/tests/bots/flows/`) for
  conftest/`__init__.py` conventions and mirror them.

### References in Codebase
- `sdd/artifacts/plan/` — source of truth.
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:2027-2029` —
  existing `register_node` usage (do not add a `"tool"` line there).

---

## Acceptance Criteria

- [ ] Module importable: `from parrot.bots.flows.plan import ExecutionPlan,
  PlanToolNode, validate_plan, to_flow_definition, ensure_tool_node_registered`
- [ ] `_shim.py` absent from the package; no `try/except ImportError`
  import fallbacks remain in `node.py`/`compile.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/flows/plan/ -v`
  (60 tests)
- [ ] `"tool" not in NODE_REGISTRY` after plain import of the module
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/plan/`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/plan/ — relocated suite, plus:
def test_public_api_exports():
    import parrot.bots.flows.plan as plan
    for name in plan.__all__:
        assert getattr(plan, name, None) is not None

def test_tool_not_registered_on_import():
    from parrot.bots.flows.flow.flow import NODE_REGISTRY
    import parrot.bots.flows.plan  # noqa: F401
    assert "tool" not in NODE_REGISTRY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/execution-plan-tool.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2179-land-plan-module.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-07
**Notes**: Verbatim drop-in of `sdd/artifacts/plan/{models,paths,guards,facets,
validator,compile,node,__init__}.py` into
`packages/ai-parrot/src/parrot/bots/flows/plan/`. `_shim.py` not shipped.
Collapsed the `try/except ImportError` fallbacks in `node.py`
(`Node`, `AgentTaskMachine`) and `compile.py` (`EdgeDefinition`,
`FlowDefinition`, `FlowMetadata`, `NodeDefinition`) to plain
`parrot.bots.flows.*` imports. Relocated `test_plan.py`/`test_node.py` to
`packages/ai-parrot/tests/bots/flows/plan/` (with `__init__.py`, mirroring
sibling `tests/bots/flows/` convention), rewriting `from plan.X import`
to `from parrot.bots.flows.plan.X import`; no shim-based fixtures existed
in the tests to begin with (they build their own fakes for
`ToolManager`/`WorkingMemoryToolkit`/`FlowContext`), so nothing else
changed there. Added the two extra tests from the task's Test
Specification (`test_public_api_exports`, `test_tool_not_registered_on_import`)
to `test_plan.py`. All 62 tests pass
(`pytest packages/ai-parrot/tests/bots/flows/plan/ -v`): 60 relocated +
2 new. `"tool" not in NODE_REGISTRY` verified after plain import.

Environment notes (not code changes): the shared dev venv's `ormsgpack`
install was missing its compiled `.so` (broke `import
parrot.bots.flows` repo-wide, unrelated to this feature) — fixed via
`uv pip install --reinstall --no-deps ormsgpack==1.12.2`. The compiled
`parrot/utils/types*.so` and `parrot/utils/parsers/toml*.so` build
artifacts (gitignored, not present in a fresh worktree checkout) were
copied from the main repo into this worktree purely to make the editable
install resolve against the worktree's `packages/ai-parrot/src` (via
`PYTHONPATH` prepended ahead of the main-repo editable-install path) for
local test execution — neither is committed.

`ruff check packages/ai-parrot/src/parrot/bots/flows/plan/` reports only
style-modernization findings (`UP006`/`UP035`/`UP045` `Optional`/`List`/
`Dict`/`Set` → PEP 604/585 spellings, `RUF022`/`RUF023` sort suggestions,
one inherited `F401` unused `Tuple` import in `node.py`) — all inherited
verbatim from the frozen `sdd/artifacts/plan/` source. The repo has no
`[tool.ruff]` config, so `ruff check` runs under ruff 0.16's full default
ruleset; the same ruleset reports comparable pre-existing findings against
untouched sibling files (e.g. `bots/flows/core/node.py`, `bots/flows/flow/
loader.py`), confirming this is not something introduced here. Per this
task's own "verbatim drop-in: no renames, no 'improvements'" constraint
and spec §7 ("the `plan/` module is frozen"), these were left unmodified
rather than "fixed" — fixing them would violate Cardinal Rule 1.

**Deviations from spec**: none
