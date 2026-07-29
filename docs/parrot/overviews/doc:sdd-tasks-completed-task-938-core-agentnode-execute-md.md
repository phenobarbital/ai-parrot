---
type: Wiki Overview
title: 'TASK-938: Core AgentNode Enhancement — Add execute()'
id: doc:sdd-tasks-completed-task-938-core-agentnode-execute-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The core `AgentNode` in `flows.core.node` currently wraps an agent with FSM
  and dependency metadata but has no execution logic. Both `_CrewAgentNode` (crew.py)
  and `FlowNode` (flow/fsm.py) have their own `execute()` implementations with varying
  levels of functionality.
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-938: Core AgentNode Enhancement — Add execute()

**Feature**: FEAT-137 — AgentCrew Primitives Migration
**Spec**: `sdd/specs/agentcrew-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-937
**Assigned-to**: unassigned

---

## Context

The core `AgentNode` in `flows.core.node` currently wraps an agent with FSM and dependency metadata but has no execution logic. Both `_CrewAgentNode` (crew.py) and `FlowNode` (flow/fsm.py) have their own `execute()` implementations with varying levels of functionality.

This task adds a canonical `execute()` method to core `AgentNode` with timeout handling, execution time tracking, and pre/post action hooks — making it the shared execution primitive for all orchestration engines. Then `_CrewAgentNode` becomes a subclass of `AgentNode`, inheriting `execute()` and overriding `_format_prompt()` as a private method.

This is Module 1 of the spec — the foundation that all per-mode migration tasks build on.

---

## Scope

- Add `execute()` method to `AgentNode` in `packages/ai-parrot/src/parrot/bots/flows/core/node.py`:
  - Signature: `async def execute(self, prompt: str, *, timeout: Optional[float] = None, **ctx: Any) -> Dict[str, Any]`
  - Calls `run_pre_actions(prompt, **ctx)` before execution.
  - Executes agent via `self.agent.ask(prompt=prompt, **ctx)` (NOT `invoke()` — see D11).
  - Wraps with `asyncio.wait_for(... , timeout=timeout)` when timeout is provided.
  - Tracks execution time (`asyncio.get_event_loop().time()`).
  - Extracts output: `response.content` if available, else `str(response.output)` if available, else `str(response)`.
  - Calls `run_post_actions(result, **ctx)` after execution.
  - Returns dict: `{'response': response, 'output': output, 'execution_time': float, 'prompt': prompt}`.
  - On `asyncio.TimeoutError`: calls `self.fsm.fail()` if FSM exists, then raises `TimeoutError` with descriptive message.
  - On generic `Exception`: calls `self.fsm.fail()` if FSM exists, then re-raises.
- Refactor `_CrewAgentNode` in `crew.py` to be a dataclass subclass of core `AgentNode`:
  - Remove duplicated `__init__`, `execute()` logic (inherited from parent).
  - Keep `_format_prompt()` as a private method (crew-specific prompt format).
  - Preserve the `AgentNode = _CrewAgentNode` backward-compat alias.
- Add unit tests for core `AgentNode.execute()`.
- Verify `_CrewAgentNode` subclass produces identical results to the old standalone class.

**NOT in scope**: Migrating any `run_*` methods. Changing `FlowContext`. Changing type aliases.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/node.py` | MODIFY | Add `execute()` to `AgentNode` |
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Refactor `_CrewAgentNode` as subclass of core `AgentNode` |
| `packages/ai-parrot/tests/test_agentnode_execute.py` | CREATE | Unit tests for core `AgentNode.execute()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# flows/core/node.py — current imports (line 16-26):
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, Set
from navconfig.logging import logging
from .fsm import AgentTaskMachine
from .types import ActionCallback, AgentLike

# crew.py — current imports relevant to _CrewAgentNode (lines 1-50):
from typing import List, Dict, Any, Union, Optional, Set
from parrot.bots import BasicAgent, AbstractBot
from parrot.models.crew import (
    CrewResult, AgentExecutionInfo, build_agent_metadata,  # lines 43-46
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py:34
class Node(ABC):
    node_id: str                                          # line 61
    logger: logging.Logger                                # line 62
    _pre_actions: list                                    # line 63
    _post_actions: list                                   # line 64
    def _init_node(self, node_id: str, name: str):        # line 66
    async def run_pre_actions(self, prompt="", **ctx):     # line 105
    async def run_post_actions(self, result=None, **ctx):  # line 121

# packages/ai-parrot/src/parrot/bots/flows/core/node.py:144
@dataclass
class AgentNode(Node):
    agent: AgentLike                                      # line 161
    node_id: str                                          # line 162
    dependencies: Set[str] = field(default_factory=set)   # line 163
    successors: Set[str] = field(default_factory=set)     # line 164
    fsm: Optional[AgentTaskMachine] = field(default=None) # line 165
    def __post_init__(self):                               # line 167
    @property
    def name(self) -> str:                                # line 173

# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:130
class _CrewAgentNode:
    def __init__(self, agent: Union[BasicAgent, AbstractBot],
                 dependencies: Optional[Set[str]] = None):  # line 141
        self.agent = agent                                  # line 142
        self.dependencies = dependencies or set()           # line 143
        self.successors: Set[str] = set()                   # line 144
    def _format_prompt(self, input_data: Dict[str, Any]) -> str:  # line 146
    async def execute(self, context: FlowContext,
                      timeout: Optional[float] = None) -> Any:  # line 172

# packages/ai-parrot/src/parrot/bots/flows/core/fsm.py:40
class AgentTaskMachine(StateMachine):
    # Transitions: schedule, start, succeed, fail, block, unblock, retry
    # fail: running/ready/idle → failed

# packages/ai-parrot/src/parrot/bots/flows/core/types.py:55
class AgentLike(Protocol):
    @property
    def name(self) -> str: ...                             # line 63
    async def invoke(self, prompt: str, **kwargs) -> Any:  # line 73
    # NOTE: Protocol says invoke(), concrete agents use ask().
    # execute() must call ask(), not invoke(). See D11.
```

### Does NOT Exist

- ~~`AgentNode.execute()`~~ — does NOT exist yet; this task adds it
- ~~`AgentLike.ask()`~~ — protocol defines `invoke()`, not `ask()`. But concrete agents (BasicAgent, AbstractBot) use `ask()`. Call `ask()` in execute().
- ~~`AgentNode.execution_time`~~ — does NOT exist on core `AgentNode`
- ~~`AgentNode.started_at` / `completed_at`~~ — do NOT exist on core `AgentNode`
- ~~`Node.execute()`~~ — `Node` ABC has no `execute()` method

---

## Implementation Notes

### Pattern to Follow

The new `AgentNode.execute()` should closely mirror `_CrewAgentNode.execute()` (crew.py:172-236) but be more generic:

```python
# Core pattern — in node.py:
async def execute(
    self,
    prompt: str,
    *,
    timeout: Optional[float] = None,
    **ctx: Any,
) -> Dict[str, Any]:
    await self.run_pre_actions(prompt=prompt, **ctx)
    start_time = asyncio.get_event_loop().time()
    try:
        if timeout:
            response = await asyncio.wait_for(
                self.agent.ask(prompt=prompt, **ctx),
                timeout=timeout,
            )
        else:
            response = await self.agent.ask(prompt=prompt, **ctx)
        end_time = asyncio.get_event_loop().time()
        output = (
            response.content if hasattr(response, 'content')
            else str(response.output if hasattr(response, 'output') else response)
        )
        await self.run_post_actions(result=response, **ctx)
        return {
            'response': response,
            'output': output,
            'execution_time': end_time - start_time,
            'prompt': prompt,
        }
    except asyncio.TimeoutError:
        end_time = asyncio.get_event_loop().time()
        if self.fsm:
            self.fsm.fail()
        raise TimeoutError(
            f"Agent {self.name} timed out after {timeout}s"
        )
    except Exception:
        if self.fsm:
            self.fsm.fail()
        raise
```

For `_CrewAgentNode` as subclass:
```python
@dataclass
class _CrewAgentNode(AgentNode):
    # Inherits: agent, node_id, dependencies, successors, fsm, execute()
    # Override __post_init__ to set node_id=agent.name if not provided
    # Keep _format_prompt() as crew-specific private method
```

### Key Constraints

- `execute()` calls `self.agent.ask()`, NOT `self.agent.invoke()`.
- The result dict MUST have exactly these keys: `'response'`, `'output'`, `'execution_time'`, `'prompt'`.
- `_CrewAgentNode` must be a valid dataclass subclass of `AgentNode` (dataclass inheritance).
- The backward-compat alias `AgentNode = _CrewAgentNode` at crew.py:241 must be preserved.
- `_CrewAgentNode._format_prompt()` must produce byte-identical output to the current implementation (crew.py:146-170). Do NOT modify the format string logic.

---

## Acceptance Criteria

- [ ] Core `AgentNode` has `execute()` method with timeout + time tracking
- [ ] `execute()` calls `run_pre_actions` before and `run_post_actions` after
- [ ] Timeout triggers `TimeoutError` + FSM `fail()` transition
- [ ] `_CrewAgentNode` is a subclass of core `AgentNode` (`isinstance` check passes)
- [ ] `_format_prompt` on `_CrewAgentNode` produces byte-identical output
- [ ] `AgentNode = _CrewAgentNode` alias preserved in crew.py
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/test_agent_crew_examples.py -v`
- [ ] New unit tests pass: `pytest packages/ai-parrot/tests/test_agentnode_execute.py -v`
- [ ] No linting errors on modified files

---

## Test Specification

```python
# packages/ai-parrot/tests/test_agentnode_execute.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from parrot.bots.flows.core.node import AgentNode
from parrot.bots.orchestration.crew import _CrewAgentNode


class MockAgent:
    """Stub agent for testing."""
    def __init__(self, name="test-agent", response="test output"):
        self._name = name
        self._response = response

    @property
    def name(self) -> str:
        return self._name

    async def ask(self, prompt="", **kwargs):
        return MagicMock(content=self._response)


class TestAgentNodeExecute:
    async def test_execute_returns_result_dict(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="test")
        result = await node.execute("hello")
        assert set(result.keys()) == {"response", "output", "execution_time", "prompt"}
        assert result["output"] == "test output"
        assert result["prompt"] == "hello"
        assert result["execution_time"] > 0

    async def test_execute_timeout_raises(self):
        async def slow_ask(**kwargs):
            await asyncio.sleep(10)
        agent = MockAgent()
        agent.ask = slow_ask
        node = AgentNode(agent=agent, node_id="test")
        with pytest.raises(TimeoutError):
            await node.execute("hello", timeout=0.01)
        assert node.fsm.current_state == node.fsm.failed

    async def test_execute_calls_pre_post_hooks(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="test")
        calls = []
        node.add_pre_action(lambda name, prompt, **ctx: calls.append(("pre", name)))
        node.add_post_action(lambda name, result, **ctx: calls.append(("post", name)))
        await node.execute("hello")
        assert calls == [("pre", "test-agent"), ("post", "test-agent")]


class TestCrewAgentNodeSubclass:
    def test_isinstance_agentnode(self):
        agent = MockAgent()
        node = _CrewAgentNode(agent=agent, node_id="test")
        assert isinstance(node, AgentNode)

    def test_format_prompt_byte_equality(self):
        agent = MockAgent()
        node = _CrewAgentNode(agent=agent, node_id="test")
        input_data = {
            "task": "Analyze data",
            "dependencies": {"agent-a": "Result A", "agent-b": "Result B"},
        }
        expected = (
            "Task: Analyze data\n\n"
            "\nContext from previous agents:\n\n"
            "\n--- From agent-a ---\nResult A\n\n"
            "\n--- From agent-b ---\nResult B\n"
        )
        assert node._format_prompt(input_data) == expected
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-937 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-938-core-agentnode-execute.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
