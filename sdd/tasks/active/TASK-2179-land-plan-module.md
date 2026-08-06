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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
