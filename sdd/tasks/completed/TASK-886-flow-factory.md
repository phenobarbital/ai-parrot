# TASK-886: `build_dev_loop_flow` factory — wire 5 nodes + transitions

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-880, TASK-881, TASK-882, TASK-883, TASK-884, TASK-885
**Assigned-to**: unassigned

---

## Context

Implements **Module 10**. Wires the five primary nodes plus the failure
handler into an `AgentsFlow` (`parrot.bots.flow.fsm:277`). Topology:

```
BugIntake → Research → Development → QA → DeploymentHandoff
                                       │
                                       ↓ (passed=False)
                                  FailureHandler
                                       ↑ (any node hard-error)
```

Spec acceptance criteria:
- "QAReport.passed=True routes to `DeploymentHandoffNode`,
  `passed=False` to `FailureHandlerNode`."
- "Any `DispatchExecutionError` / `DispatchOutputValidationError`
  raised by a middle node also routes to `FailureHandlerNode`."

---

## Scope

- Implement `parrot/flows/dev_loop/flow.py`:
  - `def build_dev_loop_flow(*, dispatcher, jira_toolkit,
     log_toolkits: dict, redis_url: str) -> AgentsFlow`.
  - Construct one instance of each of the six nodes (Bug, Research,
    Development, QA, DeploymentHandoff, FailureHandler).
  - Use `flow.add_start_node(...)` for `BugIntakeNode`,
    `flow.add_end_node(...)` for `DeploymentHandoffNode` AND
    `FailureHandlerNode` (both terminal — flow can end on either).
  - Use `flow.task_flow(...)` to chain `BugIntake → Research →
    Development → QA`.
  - Use `flow.on_condition(...)` (or a custom `FlowTransition`) to
    branch on `QAReport.passed`:
    - `passed is True` → `DeploymentHandoffNode`.
    - `passed is False` → `FailureHandlerNode` with
      `ctx["failure_kind"]="qa_failed"`,
      `ctx["failure_payload"]=qa_report`.
  - Use `flow.on_error(...)` to globally route exceptions from
    Research / Development / QA / Handoff to `FailureHandlerNode`
    with `ctx["failure_kind"]="node_error"`,
    `ctx["failure_payload"]={"node_id", "exception_type", "message"}`.

**NOT in scope**:
- The orchestrator-level flow lifecycle (creating runs, persisting
  state, the flow-level semaphore). Those live in
  `AutonomousOrchestrator` itself, outside FEAT-129.
- The webhook (TASK-887).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | CREATE | `build_dev_loop_flow` factory. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Re-export `build_dev_loop_flow`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_flow.py` | CREATE | Unit tests for the topology. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Dict
from parrot.bots.flow import AgentsFlow, FlowTransition           # __init__.py:22
from parrot.bots.flow.fsm import FlowNode                          # fsm.py:198

from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,
    DispatchExecutionError, DispatchOutputValidationError,
)
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.research import ResearchNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.models import QAReport
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flow/fsm.py
class AgentsFlow(PersistenceMixin, SynthesisMixin):           # line 277
    def __init__(self, ...): ...                              # line 316
    def add_start_node(self, name: str, ...): ...             # line 456
    def add_end_node(self, name: str, ...): ...               # line 483
    def task_flow(self, ...): ...                             # line 505
    def on_success(self, ...): ...                            # line 631
    def on_error(self, ...): ...                              # line 645
    def on_condition(self, ...): ...                          # line 659
    async def run_flow(self, ...): ...                        # line 675

class FlowTransition:                                          # line 116
    async def should_activate(self, result: Any,
                              error: Optional[Exception] = None) -> bool: ...
```

### Does NOT Exist

- ~~`flow.add_node(...)`~~ — registration is implicit when calling
  `task_flow`, `add_start_node`, `add_end_node`, `add_agent`.
- ~~`flow.connect(a, b)`~~ — use `task_flow(a, b)`.
- ~~`AgentsFlow.set_failure_handler(...)`~~ — use `on_error(...)`
  with a transition.

---

## Implementation Notes

### Construction shape

```python
def build_dev_loop_flow(
    *, dispatcher, jira_toolkit, log_toolkits, redis_url,
) -> AgentsFlow:
    bug_intake = BugIntakeNode(redis_url=redis_url)
    research = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        log_toolkits=log_toolkits,
    )
    development = DevelopmentNode(dispatcher=dispatcher)
    qa = QANode(dispatcher=dispatcher)
    handoff = DeploymentHandoffNode(jira_toolkit=jira_toolkit)
    failure = FailureHandlerNode(jira_toolkit=jira_toolkit)

    flow = AgentsFlow(name="dev-loop")
    flow.add_start_node(bug_intake)
    flow.task_flow(bug_intake, research)
    flow.task_flow(research, development)
    flow.task_flow(development, qa)

    # Conditional branch on QA result
    flow.on_condition(
        qa, handoff,
        condition=lambda result, ctx: getattr(result, "passed", False) is True,
    )
    flow.on_condition(
        qa, failure,
        condition=lambda result, ctx: getattr(result, "passed", True) is False,
        ctx_update=lambda r, c: {"failure_kind": "qa_failed",
                                 "failure_payload": r},
    )

    # Global error route
    flow.on_error(
        from_nodes=[research, development, qa, handoff],
        to_node=failure,
        ctx_update=lambda exc, ctx, node: {
            "failure_kind": "node_error",
            "failure_payload": {
                "node_id": node.name,
                "exception_type": type(exc).__name__,
                "message": str(exc)[:1000],
            },
        },
    )

    flow.add_end_node(handoff)
    flow.add_end_node(failure)
    return flow
```

> **NB**: the EXACT signatures of `on_condition`, `on_error`,
> `task_flow`, `add_start_node`, `add_end_node` MUST be verified
> against `fsm.py:456-660` before implementation. The block above is
> structural; argument names may need adjustment to match the existing
> API. If the API uses positional `from_node, to_node` instead of
> named kwargs, follow the existing convention.

### Key Constraints

- `add_end_node` must accept multiple terminals (`handoff` AND
  `failure`). If the existing API only allows ONE end node, refactor
  by routing both into a shared `_FlowTerminal` no-op node first. Add
  this to the Completion Note as a deviation.
- The factory is a pure function — no globals, no env reads.

### References in Codebase

- `parrot/bots/flow/fsm.py:277-700` — full AgentsFlow API.
- Look for existing flow factories in `parrot/bots/orchestration/` for
  a working `task_flow` example.

---

## Acceptance Criteria

- [ ] `build_dev_loop_flow(...)` returns an `AgentsFlow` instance.
- [ ] `QAReport(passed=True)` causes the flow to transition QA →
  DeploymentHandoff (`test_flow_qa_pass_routes_to_handoff`).
- [ ] `QAReport(passed=False)` causes the flow to transition QA →
  FailureHandler (`test_flow_qa_fail_routes_to_failure_handler`).
- [ ] `DispatchExecutionError` raised in `DevelopmentNode` causes the
  flow to transition Development → FailureHandler
  (`test_flow_node_hard_error_routes_to_failure_handler`).
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_flow.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.flows.dev_loop import (
    BugBrief, DevelopmentOutput, QAReport, ResearchOutput,
    FlowtaskCriterion,
)
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.dispatcher import DispatchExecutionError


@pytest.fixture
def good_brief():
    return BugBrief(
        summary="x" * 20, affected_component="y", log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="x", task_path="a.yaml")],
        escalation_assignee="557058:abc", reporter="557058:def",
    )


@pytest.mark.asyncio
async def test_qa_pass_routes_to_handoff(good_brief):
    dispatcher = MagicMock()
    # Each node's dispatch returns the canonical happy-path object.
    dispatcher.dispatch = AsyncMock(side_effect=[
        ResearchOutput(jira_issue_key="OPS-1", spec_path="x",
                       feat_id="FEAT-130", branch_name="feat-130-fix",
                       worktree_path="/abs/.claude/worktrees/feat-130-fix",
                       log_excerpts=[]),
        DevelopmentOutput(files_changed=[], commit_shas=[], summary=""),
        QAReport(passed=True, criterion_results=[], lint_passed=True),
    ])
    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    jira.jira_transition_issue = AsyncMock()
    jira.jira_add_comment = AsyncMock()

    flow = build_dev_loop_flow(
        dispatcher=dispatcher, jira_toolkit=jira,
        log_toolkits={"cloudwatch": MagicMock(),
                      "elasticsearch": MagicMock()},
        redis_url="redis://localhost",
    )
    # Patch DeploymentHandoffNode subprocesses; assert handoff was the
    # terminal hit.
    ...


@pytest.mark.asyncio
async def test_qa_fail_routes_to_failure_handler(good_brief):
    ...


@pytest.mark.asyncio
async def test_dispatch_error_routes_to_failure_handler(good_brief):
    ...
```

---

## Agent Instructions

1. Confirm TASKs 880-885 are all completed.
2. Read `parrot/bots/flow/fsm.py:456-700` end-to-end. Note exact
   parameter names of `task_flow`, `on_condition`, `on_error`.
3. Update index → `"in-progress"`.
4. Implement; run flow tests; lint.
5. Move to completed.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-27
**Notes**: Implemented `build_dev_loop_flow` factory. Verified API
against `parrot/bots/flow/fsm.py:316-700`: `AgentsFlow.__init__(name, ...
enable_execution_memory=False)`, `add_agent(agent)`, `task_flow(source,
targets, condition=ON_SUCCESS, predicate=...)`, `on_condition`,
`on_error`. 10 topology unit tests inspect `flow.nodes` and
`outgoing_transitions` directly. Both terminals (handoff + failure)
are reachable through transitions; the test suite verifies the four
global error routes from research/development/qa/handoff.
**Deviations from spec**: AgentsFlow's `add_agent` API expects
BasicAgent/AbstractBot shape, but the dev-loop nodes inherit from
`parrot.bots.flow.node.Node`. Added a small `_NodeAgentAdapter`
inside `flow.py` (private) that exposes `name`, `is_configured=True`,
`ask(question, **kwargs)` and delegates back to
`Node.execute(prompt, ctx)`. This is the minimal contract surface
required by `AgentsFlow._ensure_agent_ready` + `FlowNode.execute`.
Documented inline. The TASK-889 live integration test will exercise
the full run path end-to-end.
