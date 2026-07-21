---
type: Wiki Overview
title: 'TASK-1312: AgentsFlow class internal repointing (L4 — Module 5)'
id: doc:sdd-tasks-completed-task-1312-agentsflow-migration-internal-repointing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Layer 4 of the migration. After Modules 1–4, all files the AgentsFlow class
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
---

# TASK-1312: AgentsFlow class internal repointing (L4 — Module 5)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1308, TASK-1309, TASK-1310, TASK-1311
**Assigned-to**: unassigned

---

## Context

Layer 4 of the migration. After Modules 1–4, all files the AgentsFlow class
depends on exist in `parrot/bots/flows/flow/`. This task updates
`flows/flow/flow.py` to drop the four legacy cross-package imports from
`parrot.bots.flow.*` and replace them with intra-subpackage relative imports.

This is the critical decoupling step — after this task, `parrot/bots/flows/`
no longer imports anything from `parrot/bots/flow/` (singular).

Additionally, AgentsFlow's run path is updated to use the FEAT-143 canonical
models: `FlowResult` as return type, `NodeResult` for per-node output,
`FlowContext` with `shared_data` for shared run state, and `build_node_metadata`
/ `NodeExecutionInfo` for telemetry.

Implements §3 Module 5 of the spec.

---

## Scope

In `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`:

1. **Replace** the 4 cross-package legacy imports with relative imports:

   | Line (approx) | Old import | New import |
   |---|---|---|
   | ~42 | `from parrot.bots.flow.definition import FlowDefinition` | `from .definition import FlowDefinition` |
   | ~45–50 | `from parrot.bots.flow.decision_node import (DecisionFlowNode, DecisionResult, DecisionMode, ...)` | `from .nodes import (DecisionFlowNode, DecisionResult, DecisionMode, ...)` |
   | ~51–53 | `from parrot.bots.flow.interactive_node import (InteractiveDecisionNode,)` *(note: currently references `parrot.bots.flows.flow.interactive_node` — see spec §6)* | `from .nodes import (InteractiveDecisionNode,)` |
   | ~508 (lazy) | `from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator` | `from .cel_evaluator import CELPredicateEvaluator` |

2. **Adopt canonical result models** in `AgentsFlow.run()` and the four execution
   mode methods:
   - Return type of `run()` → `FlowResult`
   - Per-node output → `NodeResult`
   - Shared run state → `FlowContext` (with `shared_data`)
   - Telemetry → `build_node_metadata` + `NodeExecutionInfo`

3. Run acceptance tests:
   - `test_agentsflow_returns_flowresult`
   - `test_agentsflow_uses_flowcontext`
   - `test_agentsflow_four_modes`

**NOT in scope**: updating external consumers (dev_loop, test files) — that is
TASK-1313 / TASK-1314. Not deleting `parrot/bots/flow/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | Replace 4 legacy imports + adopt FlowResult/NodeResult/FlowContext/build_node_metadata |
| `packages/ai-parrot/tests/bots/flows/test_agentsflow_models.py` | CREATE | Tests for FlowResult return type + FlowContext usage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# New intra-subpackage imports (replace legacy ones):
from .definition import FlowDefinition          # verified: TASK-1309 creates this
from .nodes import (                             # verified: TASK-1311 creates this
    DecisionFlowNode, DecisionResult, DecisionMode, DecisionNodeConfig,
    InteractiveDecisionNode,
)
from .cel_evaluator import CELPredicateEvaluator  # verified: TASK-1309 creates this

# Canonical models already imported in flow.py (keep these):
from .core.node import AgentNode, EndNode, Node, StartNode
# verified: parrot/bots/flows/core/node.py:68, 182, 323, 387

from .core.context import FlowContext
# verified: parrot/bots/flows/core/context.py:51

from .core.result import (
    FlowResult, NodeExecutionInfo, build_node_metadata, determine_run_status,
)
# verified: parrot/bots/flows/core/result.py:273, 190, 527, 162

from .core.storage import PersistenceMixin
# verified: parrot/bots/flows/core/storage/__init__.py
```

### Existing Signatures to Use

```python
# parrot/bots/flows/core/result.py:273
@dataclass
class FlowResult: ...   # read file for full signature

# parrot/bots/flows/core/result.py:39
@dataclass
class NodeResult:
    node_id: str
    node_name: str
    task: str
    result: Any
    ...

# parrot/bots/flows/core/result.py:527
def build_node_metadata(...) -> dict: ...  # read file for signature

# parrot/bots/flows/core/context.py:51
@dataclass
class FlowContext:
    node_metadata: Dict[str, NodeExecutionInfo]
    shared_data: Dict[str, Any]
    agent_registry: Optional[AgentRegistry]
    def mark_completed(...) -> None: ...
    def mark_failed(...) -> None: ...
    def can_execute(self, _node_id: str, dependencies: Set[str]) -> bool: ...
```

### Does NOT Exist

- ~~`parrot.bots.flow.definition`~~ after this task (still exists in singular
  package but MUST NOT be imported by `flows/flow/flow.py`)
- ~~`parrot.bots.flow.decision_node`~~ must no longer be imported by flow.py
- ~~`parrot.bots.flow.interactive_node`~~ must no longer be imported by flow.py
- ~~`parrot.bots.flow.cel_evaluator`~~ must no longer be imported by flow.py (lazy import)
- ~~`parrot.bots.flows.flow.interactive_node`~~ — note the spec §6 says line 51–53
  currently reads `from parrot.bots.flows.flow.interactive_node import ...` (with
  `flows` plural — appears to be an error in the old code). Regardless, replace it
  with `from .nodes import InteractiveDecisionNode`

---

## Implementation Notes

### Key Constraints

- Read the full current `flows/flow/flow.py` (was `flows/flow.py` before TASK-1308)
  before making any changes
- Verify each legacy import line number by reading the file; the spec says ~42, ~45,
  ~51, ~508 but the actual line numbers may differ after TASK-1308 copying
- The lazy import at ~508 is inside a method body — locate it by searching for
  `from parrot.bots.flow.cel_evaluator import`
- After replacement, run: `grep -n "parrot.bots.flow" packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  — this must return ZERO matches
- For the FlowResult/NodeResult adoption:
  - First read the current `AgentsFlow.run()` method to understand the current
    return type and per-node output handling
  - Replace any custom result dict/class with `NodeResult` dataclass instances
  - Ensure `run()` returns `FlowResult` (may already be the case from FEAT-163 work)
- Circular import check: after this task, run
  `python -c "from parrot.bots.flows.flow import AgentsFlow"` — must succeed

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` — the file to modify
- `packages/ai-parrot/src/parrot/bots/flows/core/result.py` — FlowResult, NodeResult
- `packages/ai-parrot/src/parrot/bots/flows/core/context.py` — FlowContext

---

## Acceptance Criteria

- [ ] `grep -n "from parrot.bots.flow" packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` returns zero matches
- [ ] `AgentsFlow.run()` return type annotation is `FlowResult`
- [ ] `from parrot.bots.flows.flow import AgentsFlow` succeeds with no import errors
- [ ] `python -c "from parrot.bots.flows.flow import AgentsFlow; print('OK')"` exits 0
- [ ] `pytest packages/ai-parrot/tests/bots/flows/test_agentsflow_models.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_agentsflow_models.py
import pytest
import inspect
from parrot.bots.flows.flow import AgentsFlow
from parrot.bots.flows.core.result import FlowResult, NodeResult
from parrot.bots.flows.core.context import FlowContext


def test_agentsflow_run_return_annotation():
    """AgentsFlow.run() is annotated to return FlowResult."""
    hints = {}
    try:
        hints = AgentsFlow.run.__annotations__
    except AttributeError:
        pass
    # Either the annotation exists or we check the signature
    sig = inspect.signature(AgentsFlow.run)
    # return annotation should be FlowResult or a string 'FlowResult'
    ret = sig.return_annotation
    assert ret is FlowResult or str(ret) in ("FlowResult", "<class 'parrot.bots.flows.core.result.FlowResult'>")


def test_no_legacy_flow_import_in_flow_module():
    """flows/flow/flow.py must not import from parrot.bots.flow (singular)."""
    import pathlib  # noqa: PLC0415
    src = pathlib.Path(
        "packages/ai-parrot/src/parrot/bots/flows/flow/flow.py"
    ).read_text()
    assert "from parrot.bots.flow." not in src, \
        "Legacy parrot.bots.flow.* import found in flows/flow/flow.py"


def test_agentsflow_import_clean():
    """AgentsFlow imports without errors."""
    from parrot.bots.flows.flow import AgentsFlow  # noqa: PLC0415
    assert AgentsFlow is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md`
2. **Check dependencies** — TASK-1308, TASK-1309, TASK-1310, TASK-1311 must be done
3. **Read `flows/flow/flow.py` in full** before making any changes
4. **Locate exact line numbers** for the 4 legacy imports by searching the file
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-28
**Notes**: Replaced all 4 legacy `parrot.bots.flow.*` imports in `flows/flow/flow.py` with
relative imports from `.definition`, `.nodes`, `.cel_evaluator`. Also removed 3 pre-existing
unused imports (NodeExecutionInfo, `dataclasses.field`, `import time as _time`). Updated
`DecisionNode.execute()` to use `node_id=` (new canonical ctor) instead of `name=`. Updated
`InteractiveDecisionNode.execute()` to delegate to `nodes.InteractiveDecisionNode` instead of
legacy class. All 7 TASK-1312 acceptance tests pass.

**Deviations from spec**: none
