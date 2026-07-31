---
type: Wiki Overview
title: 'TASK-921: Contract Tests — FSM Invariants, Serialization, Protocol Conformance'
id: doc:sdd-tasks-completed-task-921-flow-primitives-contract-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Final task: consolidates and extends the per-module tests from previous
  tasks'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-921: Contract Tests — FSM Invariants, Serialization, Protocol Conformance

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-920
**Assigned-to**: unassigned

---

## Context

Final task: consolidates and extends the per-module tests from previous tasks
into a comprehensive contract test suite. These are pure unit tests (no LLM,
no network) that validate the invariants documented in the spec.

Previous tasks wrote focused tests for their own modules. This task adds
cross-module integration tests and ensures the full spec §4 test matrix is
covered.

Implements Spec §3 Module 9.

---

## Scope

- Create/extend `packages/ai-parrot/tests/test_flow_primitives/conftest.py`
  with shared fixtures (`mock_agent`, `agent_node`, `flow_context`).
- Ensure all tests from Spec §4 are present and passing:
  - FSM: initial state, happy path, retry, blocked, invalid transitions,
    completed-is-final, failed-is-not-final.
  - Node: `node_id` vs `name` separation, action hooks (sync + async).
  - Result: `to_dict()` round-trip, backward-compat aliases.
  - Context: `can_execute()`, `mark_completed()`, `get_input_for_node()`,
    backward-compat aliases.
  - Transition: `should_activate()` for all conditions, predicate handling.
  - Protocol: `AgentLike` conformance/rejection.
  - Import compat: all old import paths still work.
- Run the full existing test suite to ensure zero regressions.

**NOT in scope**: Performance tests, LLM integration tests, end-to-end
workflow tests (those belong to Spec 2/3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_flow_primitives/conftest.py` | CREATE | Shared fixtures |
| `packages/ai-parrot/tests/test_flow_primitives/test_contract.py` | CREATE | Cross-module contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All from the new core package (verified by TASK-920):
from parrot.bots.flows.core import (
    AgentLike, AgentRef, FlowStatus,
    AgentTaskMachine, TransitionCondition,
    Node, AgentNode, StartNode, EndNode,
    FlowResult, NodeExecutionInfo,
    FlowContext, FlowTransition,
    ExecutionMemory, PersistenceMixin, SynthesisMixin,
    build_node_metadata, determine_run_status,
)

# Old import paths that must still work:
from parrot.models.crew import CrewResult, AgentExecutionInfo
from parrot.bots.flow import Node as OldNode, StartNode as OldStart, EndNode as OldEnd
from parrot.bots.flow.storage import ExecutionMemory as OldEM
```

### Does NOT Exist
- ~~`NodeResult`~~ — not created (D11)
- ~~`parrot.bots.flows.core.node.FlowNode`~~ — `FlowNode` stays in `parrot.bots.flow.fsm`

---

## Implementation Notes

### conftest.py Pattern
```python
import pytest
from parrot.bots.flows.core import (
    AgentLike, AgentNode, FlowContext, NodeExecutionInfo,
    AgentTaskMachine,
)


class MockAgent:
    @property
    def name(self) -> str:
        return "test-agent"
    async def invoke(self, prompt: str, **kwargs):
        return f"response to: {prompt}"


@pytest.fixture
def mock_agent():
    return MockAgent()

@pytest.fixture
def agent_node(mock_agent):
    return AgentNode(agent=mock_agent, node_id="node-1")

@pytest.fixture
def flow_context():
    return FlowContext(initial_task="test task")
```

### Key Constraints
- All tests MUST be pure unit tests — no LLM calls, no network, no database.
- Tests should import from `parrot.bots.flows.core` (the canonical path),
  except import-compat tests which explicitly test old paths.
- Use `pytest.mark.asyncio` for async test methods.

---

## Acceptance Criteria

- [ ] `conftest.py` with shared fixtures exists
- [ ] All spec §4 unit tests are present and passing
- [ ] All spec §4 integration (import compat) tests are present and passing
- [ ] Full test suite passes: `pytest packages/ai-parrot/tests/test_flow_primitives/ -v`
- [ ] No regressions in existing tests: `pytest packages/ai-parrot/tests/ -x --timeout=60`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_contract.py
import pytest
from parrot.bots.flows.core import (
    AgentLike, FlowStatus, AgentTaskMachine, TransitionCondition,
    AgentNode, StartNode, EndNode,
    FlowResult, NodeExecutionInfo,
    FlowContext, FlowTransition,
    build_node_metadata, determine_run_status,
)


class TestCrossModuleIntegration:
    """Tests that span multiple core modules."""

    def test_agent_node_has_fsm(self, agent_node):
        assert isinstance(agent_node.fsm, AgentTaskMachine)
        assert agent_node.fsm.current_state == agent_node.fsm.idle

    def test_agent_node_protocol_conformance(self, mock_agent):
        assert isinstance(mock_agent, AgentLike)

    def test_flow_context_with_node_execution_info(self, flow_context):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1", status="completed")
        flow_context.mark_completed("n1", result="done", metadata=info)
        assert flow_context.node_metadata["n1"] == info
        assert flow_context.agent_metadata["n1"] == info  # alias

    def test_flow_result_with_flow_status(self):
        r = FlowResult(output="ok", status=FlowStatus.COMPLETED)
        assert r.success is True
        assert r.status == FlowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_transition_activates_and_builds_prompt(self):
        t = FlowTransition(
            source="a", targets={"b"},
            condition=TransitionCondition.ALWAYS,
            instruction="Do the thing",
        )
        assert await t.should_activate(result="ok") is True

    def test_node_id_uniqueness_concept(self, mock_agent):
        n1 = AgentNode(agent=mock_agent, node_id="instance-1")
        n2 = AgentNode(agent=mock_agent, node_id="instance-2")
        assert n1.node_id != n2.node_id
        assert n1.name == n2.name  # same agent

    def test_determine_run_status_integration(self):
        assert determine_run_status(5, 0) == "completed"
        assert determine_run_status(3, 2) == "partial"
        assert determine_run_status(0, 4) == "failed"

    def test_build_node_metadata_returns_correct_type(self):
        info = build_node_metadata(
            node_id="n1", agent=None, response=None,
            output="result", execution_time=1.5, status="completed"
        )
        assert isinstance(info, NodeExecutionInfo)
        assert info.node_id == "n1"
        assert info.agent_id == "n1"  # backward compat
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §4 Test Specification for the full test matrix
2. **Check dependencies** — TASK-920 must be completed (all modules ready)
3. **Review** tests already written in TASK-913 through TASK-920 — don't
   duplicate; focus on cross-module and contract tests
4. **Create** `conftest.py` and `test_contract.py`
5. **Run**: `pytest packages/ai-parrot/tests/test_flow_primitives/ -v`
6. **Run**: `pytest packages/ai-parrot/tests/ -x --timeout=60` for regression check

---

## Completion Note

Completed 2026-04-29. Created:
- `conftest.py`: shared fixtures `mock_agent`, `agent_node`, `flow_context`, `node_execution_info`.
- `test_contract.py`: 216 tests total across all modules (cross-module integration, FSM invariants, Node contract, Result contract, Context contract, Transition contract, Protocol conformance, Import compatibility).

All 216 tests pass. 0 regressions.
