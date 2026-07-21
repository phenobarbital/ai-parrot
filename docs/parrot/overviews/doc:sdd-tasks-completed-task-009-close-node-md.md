---
type: Wiki Overview
title: 'TASK-009: `DevLoopCloseNode` terminal node'
id: doc:sdd-tasks-completed-task-009-close-node-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 10 (G7). A terminal node that records the run's final state
relates_to:
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: mentions
---

# TASK-009: `DevLoopCloseNode` terminal node

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-003
**Assigned-to**: unassigned

---

## Context

Implements Module 10 (G7). A terminal node that records the run's final state
(Jira summary comment + transition) and ends the flow, used on both the initial
and revision paths.

---

## Scope

- Create `DevLoopCloseNode(DevLoopNode)` in `nodes/close.py`:
  - `__init__(self, jira_toolkit, name="dev_loop_close")`.
  - `async execute(ctx, deps, **kwargs) -> Dict[str, str]`: read final outputs
    from shared state (`research_output`, `qa_report`, deployment dict /
    revision result), post a Jira summary comment, transition the ticket
    (e.g. "Ready to Deploy" on initial; "In Review – revised" on revision —
    branch on a `shared["mode"]` flag set by the runner), and return a terminal
    status dict.
  - Pure AI-Parrot, no dispatch. Never raises on Jira hiccups — log and return a
    degraded status.
- Unit tests with `jira_toolkit` mocked.

**NOT in scope**: registering it as a declarative node type / factory (TASK-010);
revision-mode wiring (TASK-012).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/close.py` | CREATE | `DevLoopCloseNode` |
| `packages/ai-parrot/tests/flows/dev_loop/test_close_node.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import DevLoopNode          # nodes/base.py:29
from parrot.bots.flows.core.context import FlowContext            # core/context.py:52
from parrot.bots.flows.core.types import DependencyResults
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py
class DevLoopNode(Node):
    def shared_state(self, ctx) -> Dict[str, Any]    # :62
    # subclasses implement: async def execute(self, ctx, deps, **kwargs) -> T

# Mirror the construction/return style of an existing pure node:
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py
class FailureHandlerNode(DevLoopNode):
    def __init__(self, jira_toolkit, name="failure_handler")     # :34
    async def execute(self, ctx, deps, **kwargs) -> Dict[str, str]  # :47
    # uses jira_toolkit to comment + transition + reassign; returns {"status": ...}
```

### Does NOT Exist
- ~~`DevLoopCloseNode`~~ — this task creates it.
- ~~a `shared["mode"]` flag today~~ — TASK-012 sets it for revision runs; default to "initial" when absent.

---

## Implementation Notes

### Key Constraints
- Construct nodes the same way `FailureHandlerNode` does (frozen Pydantic `Node`;
  use `object.__setattr__` for private attrs as the existing nodes do, or follow
  the base class's pattern).
- Idempotent / non-raising: a Jira failure must not crash the flow's terminal node.
- Transition labels: reuse the existing transition helper used by
  `DeploymentHandoffNode`/`FailureHandlerNode` rather than hard-coding API calls.

### References in Codebase
- `nodes/failure_handler.py` — closest sibling (pure node, Jira comment + transition).
- `nodes/deployment_handoff.py` — Jira transition usage.

---

## Acceptance Criteria

- [ ] `DevLoopCloseNode` posts a Jira summary comment + transition and returns a terminal status dict.
- [ ] Branches transition label on `shared.get("mode", "initial")`.
- [ ] A Jira error yields a degraded status, not an exception.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_close_node.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/close.py` clean.

---

## Test Specification
```python
async def test_close_node_transitions_jira(mock_jira):
    node = DevLoopCloseNode(jira_toolkit=mock_jira)
    out = await node.execute(ctx_with_research_and_qa, deps)
    assert out["status"]  # terminal status set
    mock_jira.jira_add_comment.assert_called()  # or the toolkit's comment method
```

---

## Agent Instructions
Standard SDD lifecycle. Confirm the JiraToolkit method names used by
`failure_handler.py`/`deployment_handoff.py` and reuse them verbatim.

## Completion Note

**Status**: done — 2026-06-20

**What changed**
- Created `nodes/close.py` with `DevLoopCloseNode(DevLoopNode)`:
  `__init__(self, jira_toolkit, name="dev_loop_close")` mirroring
  `FailureHandlerNode`'s construction (`super().__init__(node_id=name)` +
  `object.__setattr__(self, "_jira", …)`). `execute` reads `research_output`,
  `qa_report`, and `deployment_result`/`revision_result` from shared state,
  posts a Jira summary comment, transitions by `shared.get("mode", "initial")`
  (`initial`→"Ready to Deploy", `revision`→"In Review – revised"), and returns
  a terminal status. Never raises — Jira errors yield `close_failed`.
- Reuses the exact JiraToolkit methods used by `failure_handler.py`:
  `jira_add_comment` / `jira_transition_issue`.

**Verification**
- `pytest test_close_node.py` → 5 passed (initial transition, revision
  transition, no-ticket path, Jira-error degradation, code-review findings in
  summary).
- `ruff check` clean on both files.
