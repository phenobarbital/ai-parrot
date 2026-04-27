# TASK-880: `BugIntakeNode` — input validation, no dispatch

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-874, TASK-876
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** from spec §3. First node of the dev-loop flow.
Pure AI-Parrot — does NOT call the dispatcher. Validates the incoming
`BugBrief` against the `ACCEPTANCE_CRITERION_ALLOWLIST` and shape rules
before any expensive Claude Code work begins.

Spec acceptance criterion: "BugIntakeNode rejects a brief whose
`ShellCriterion.command` head is not in `ACCEPTANCE_CRITERION_ALLOWLIST`."

---

## Scope

- Implement `parrot/flows/dev_loop/nodes/bug_intake.py`:
  - `class BugIntakeNode(Node)` (inherits from `parrot.bots.flow.node.Node`).
  - `async def execute(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief`:
    1. Locate the incoming `BugBrief` either in `ctx["bug_brief"]` or
       parse it from `prompt` if a JSON string is passed.
    2. Validate every `ShellCriterion`: `command.split()[0]` must be in
       `ACCEPTANCE_CRITERION_ALLOWLIST` (compare on the **head** only).
    3. Validate every `FlowtaskCriterion.task_path`: must be a relative
       path, no `..` segments, no leading `/`.
    4. Emit a flow event `flow.bug_brief_validated` to the run's
       `flow:{run_id}:flow` Redis stream (use the `redis_url` and
       `run_id` from `ctx`).
    5. Return the validated `BugBrief` (downstream nodes consume it).
- Create `parrot/flows/dev_loop/nodes/__init__.py`.

**NOT in scope**:
- Any Claude Code dispatch.
- Jira / log fetching (TASK-881 owns that).
- Persisting flow state to durable storage (orchestrator concern).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/__init__.py` | CREATE | Namespace marker. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py` | CREATE | `BugIntakeNode`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_bug_intake.py` | CREATE | Unit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import logging
import os
import time
from typing import Any, Dict

import redis.asyncio as aioredis

from parrot.bots.flow.node import Node                   # node.py:14
from parrot.flows.dev_loop.models import (
    BugBrief, FlowtaskCriterion, ShellCriterion,
)
from parrot.conf import ACCEPTANCE_CRITERION_ALLOWLIST   # added in TASK-876
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flow/node.py
class Node(ABC):                                         # line 14
    def _init_node(self, name: str) -> None: ...         # line 48
    @property
    def name(self) -> str: ...                           # line 61
    def add_pre_action(self, action) -> None: ...        # line 66
    def add_post_action(self, action) -> None: ...       # line 70
    async def run_pre_actions(self, ...) -> None: ...    # line 76
    async def run_post_actions(self, ...) -> None: ...   # line 92
    # NB: no abstract `execute` on Node directly. FlowNode (fsm.py:266)
    # adds:
    #   async def execute(self, prompt: str, ctx: Dict[str, Any]) -> Any
    # Decide between Node and FlowNode based on whether transitions are
    # needed; the dev-loop flow factory (TASK-886) wires transitions on
    # FlowNode wrappers, so subclassing Node here is fine — the flow
    # factory promotes nodes to FlowNode via `task_flow(...)`.
```

### Does NOT Exist

- ~~`Node.emit_event(...)`~~ — there is no built-in event emit on the
  base `Node`. Use the Redis client directly with `XADD
  flow:{run_id}:flow ...`.
- ~~`shlex.quote`-based allowlist matching~~ — match on the **first
  whitespace-split token** only:
  `head = command.split(maxsplit=1)[0]`. Do NOT shell-parse.

---

## Implementation Notes

### execute() shape

```python
class BugIntakeNode(Node):
    def __init__(self, *, redis_url: str, name: str = "bug_intake"):
        super().__init__()
        self._init_node(name)
        self._redis_url = redis_url
        self.logger = logging.getLogger(__name__)

    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
        brief = self._load_brief(prompt, ctx)
        self._validate(brief)
        await self._emit_validated_event(ctx["run_id"], brief)
        return brief

    def _load_brief(self, prompt: str, ctx: Dict[str, Any]) -> BugBrief:
        if "bug_brief" in ctx and isinstance(ctx["bug_brief"], BugBrief):
            return ctx["bug_brief"]
        if "bug_brief" in ctx:
            return BugBrief.model_validate(ctx["bug_brief"])
        return BugBrief.model_validate_json(prompt)

    def _validate(self, brief: BugBrief) -> None:
        for c in brief.acceptance_criteria:
            if isinstance(c, ShellCriterion):
                head = c.command.split(maxsplit=1)[0]
                if head not in ACCEPTANCE_CRITERION_ALLOWLIST:
                    raise ValueError(
                        f"Shell command head {head!r} not in allowlist"
                    )
            elif isinstance(c, FlowtaskCriterion):
                p = c.task_path
                if p.startswith("/") or ".." in p.split("/"):
                    raise ValueError(f"Invalid relative task_path: {p!r}")
```

### Event payload

```python
import json, time
event = {
    "kind": "flow.bug_brief_validated",
    "ts": str(time.time()),
    "run_id": ctx["run_id"],
    "node_id": self.name,
    "payload": json.dumps({"summary": brief.summary,
                           "n_criteria": len(brief.acceptance_criteria)}),
}
await redis.xadd(f"flow:{ctx['run_id']}:flow", event,
                 maxlen=10_000, approximate=True)
```

### Key Constraints

- `ValueError` is the validation-failure type — the flow factory
  (TASK-886) maps this to `FailureHandlerNode` via an error transition.
- The node MUST be safe to construct without a live Redis (Redis client
  is lazily built on first `execute`).

### References in Codebase

- `parrot/bots/flow/node.py` — base class.
- `parrot/bots/flow/fsm.py:266` — `FlowNode.execute` signature
  (informs the contract for any node).

---

## Acceptance Criteria

- [ ] `BugIntakeNode` constructible with `redis_url` only.
- [ ] `execute(...)` returns the validated `BugBrief` on the happy
  path.
- [ ] `ShellCriterion(command="rm -rf /")` raises `ValueError`
  (`test_shell_criterion_command_must_be_in_allowlist`).
- [ ] `FlowtaskCriterion(task_path="../etc/passwd")` raises
  `ValueError`.
- [ ] On success, an `XADD` to `flow:{run_id}:flow` is observed
  (verified via mocked Redis).
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_bug_intake.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch

from parrot.flows.dev_loop import (
    BugBrief, FlowtaskCriterion, ShellCriterion, LogSource,
)
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode


@pytest.fixture
def good_brief():
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(name="run", task_path="etl/customers/sync.yaml"),
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def node():
    return BugIntakeNode(redis_url="redis://localhost:6379/0")


@pytest.mark.asyncio
async def test_happy_path(node, good_brief):
    with patch("parrot.flows.dev_loop.nodes.bug_intake.aioredis"
               ) as mock_redis:
        mock_redis.from_url.return_value.xadd = AsyncMock()
        result = await node.execute(prompt="",
                                    ctx={"run_id": "r1",
                                         "bug_brief": good_brief})
        assert result.summary == good_brief.summary


@pytest.mark.asyncio
async def test_shell_command_must_be_in_allowlist(node, good_brief):
    bad = good_brief.model_copy(update={
        "acceptance_criteria": [
            ShellCriterion(name="x", command="rm -rf /"),
        ]
    })
    with pytest.raises(ValueError):
        await node.execute(prompt="",
                           ctx={"run_id": "r1", "bug_brief": bad})


@pytest.mark.asyncio
async def test_flowtask_path_rejects_traversal(node, good_brief):
    bad = good_brief.model_copy(update={
        "acceptance_criteria": [
            FlowtaskCriterion(name="x", task_path="../etc/passwd"),
        ]
    })
    with pytest.raises(ValueError):
        await node.execute(prompt="",
                           ctx={"run_id": "r1", "bug_brief": bad})
```

---

## Agent Instructions

1. Verify TASK-874, TASK-876 are in `sdd/tasks/completed/`.
2. Update index → `"in-progress"`.
3. Implement; run tests; lint.
4. Move to completed; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
