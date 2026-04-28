# TASK-882: `DevelopmentNode` — sdd-worker dispatch

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-874, TASK-878, TASK-881
**Assigned-to**: unassigned

---

## Context

Implements **Module 6**. Thin node that dispatches to the `sdd-worker`
subagent inside the worktree created by `ResearchNode`. The subagent
implements the spec produced in research, then commits per task.

Spec acceptance criterion: "DevelopmentNode dispatches with
`subagent="sdd-worker"`, `permission_mode="acceptEdits"`, and `cwd`
from the upstream `ResearchOutput`."

---

## Scope

- Implement `parrot/flows/dev_loop/nodes/development.py`:
  - `class DevelopmentNode(Node)`.
  - `__init__(*, dispatcher: ClaudeCodeDispatcher)`.
  - `async def execute(self, prompt, ctx) -> DevelopmentOutput`:
    1. Read `ResearchOutput` from `ctx["research_output"]`.
    2. Build a `ClaudeCodeDispatchProfile` with `subagent="sdd-worker"`,
       `permission_mode="acceptEdits"`,
       `allowed_tools=["Read","Edit","Write","Bash","Grep","Glob"]`,
       `setting_sources=["project"]`.
    3. Build the dispatch prompt:
       `"Implement the spec at <spec_path> by running /sdd-start on each
        unblocked task in dependency order. After each task, commit. When
        all tasks are completed, return the JSON object matching
        DevelopmentOutput."`
    4. `await dispatcher.dispatch(brief=research_output, profile=profile,
        output_model=DevelopmentOutput, cwd=research_output.worktree_path,
        run_id=ctx["run_id"], node_id=self.name)`.
    5. Return the `DevelopmentOutput`.

**NOT in scope**:
- Modifying the dispatcher's behavior.
- Inspecting commits / file changes (the worker reports them in its
  `DevelopmentOutput.files_changed` and `commit_shas`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | CREATE | `DevelopmentNode`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_development.py` | CREATE | Unit tests with mocked dispatcher. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import logging
from typing import Any, Dict

from parrot.bots.flow.node import Node                          # node.py:14
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile, DevelopmentOutput, ResearchOutput,
)
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
```

### Existing Signatures to Use

```python
# parrot/flows/dev_loop/dispatcher.py (from TASK-878)
class ClaudeCodeDispatcher:
    async def dispatch(
        self, *, brief: BaseModel, profile: ClaudeCodeDispatchProfile,
        output_model: Type[T], run_id: str, node_id: str, cwd: str,
    ) -> T: ...
```

### Does NOT Exist

- ~~`Node.dispatch_self(...)`~~ — call `self._dispatcher.dispatch(...)`
  directly.
- ~~`ResearchOutput.cwd`~~ — the field is `worktree_path`. Pass that to
  `dispatch(cwd=...)`.

---

## Implementation Notes

### execute() shape

```python
class DevelopmentNode(Node):
    def __init__(self, *, dispatcher, name: str = "development"):
        super().__init__()
        self._init_node(name)
        self._dispatcher = dispatcher
        self.logger = logging.getLogger(__name__)

    async def execute(self, prompt, ctx) -> DevelopmentOutput:
        research: ResearchOutput = ctx["research_output"]
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            permission_mode="acceptEdits",
            allowed_tools=["Read","Edit","Write","Bash","Grep","Glob"],
            setting_sources=["project"],
        )
        dispatch_prompt = self._build_prompt(research)
        dev_out = await self._dispatcher.dispatch(
            brief=research,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id=ctx["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
        )
        return dev_out
```

### Key Constraints

- `cwd=research.worktree_path` (NOT `WORKTREE_BASE_PATH`). The
  dispatcher's R4 check verifies the path is under the base.
- Allowed tools include `Edit`/`Write` (the worker MUST be able to
  modify files). This is a deliberate distinction from QA.

### References in Codebase

- `parrot/flows/dev_loop/nodes/research.py` (TASK-881) — companion
  pattern.

---

## Acceptance Criteria

- [ ] Profile passed to dispatcher has `subagent="sdd-worker"`,
  `permission_mode="acceptEdits"`, `Edit` in `allowed_tools`.
- [ ] `dispatch(cwd=...)` receives `research_output.worktree_path`.
- [ ] On `DispatchOutputValidationError`, the node propagates (flow
  factory handles routing).
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_development.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.flows.dev_loop import (
    DevelopmentOutput, ResearchOutput, ClaudeCodeDispatchProfile,
)
from parrot.flows.dev_loop.nodes.development import DevelopmentNode


@pytest.fixture
def research_out():
    return ResearchOutput(
        jira_issue_key="OPS-1", spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130", branch_name="feat-130-fix",
        worktree_path="/abs/.claude/worktrees/feat-130-fix",
        log_excerpts=[],
    )


@pytest.mark.asyncio
async def test_dispatch_arguments(research_out):
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=DevelopmentOutput(
        files_changed=["a.py"], commit_shas=["abc"], summary="done",
    ))
    node = DevelopmentNode(dispatcher=dispatcher)
    await node.execute(prompt="", ctx={"run_id": "r1",
                                       "research_output": research_out})
    kwargs = dispatcher.dispatch.call_args.kwargs
    assert kwargs["cwd"] == research_out.worktree_path
    assert kwargs["output_model"] is DevelopmentOutput
    profile: ClaudeCodeDispatchProfile = kwargs["profile"]
    assert profile.subagent == "sdd-worker"
    assert profile.permission_mode == "acceptEdits"
    assert "Edit" in profile.allowed_tools
```

---

## Agent Instructions

1. Confirm TASK-874, TASK-878, TASK-881 are completed.
2. Update index → `"in-progress"`.
3. Implement; tests; lint.
4. Move to completed.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-27
**Notes**: Thin node that builds the sdd-worker dispatch profile
(`subagent="sdd-worker"`, `permission_mode="acceptEdits"`,
allowed_tools includes Edit/Write/Bash/Read/Grep/Glob,
`setting_sources=["project"]`) and dispatches inside
`research_output.worktree_path`. Stores the validated DevelopmentOutput
on `ctx["development_output"]`. 3 unit tests cover dispatch kwargs,
error propagation, and context mutation.
**Deviations from spec**: None.
