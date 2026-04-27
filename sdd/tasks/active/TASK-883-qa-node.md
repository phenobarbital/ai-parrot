# TASK-883: `QANode` — sdd-qa dispatch in plan mode

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-874, TASK-878, TASK-882
**Assigned-to**: unassigned

---

## Context

Implements **Module 7**. Dispatches the `sdd-qa` subagent in
`permission_mode="plan"` (NO edits) inside the worktree. The subagent
runs each `AcceptanceCriterion` deterministically (subprocess + exit
code), runs lint, and returns a `QAReport`.

Spec acceptance criteria:
- "QANode dispatches with `permission_mode="plan"` and no `Edit`/`Write`
  in `allowed_tools`. The node returns successfully even when
  `QAReport.passed is False`."
- "test_qa_node_returns_failure_without_raising": the *flow* takes the
  failure path based on `QAReport.passed`; the node itself never raises.

---

## Scope

- Implement `parrot/flows/dev_loop/nodes/qa.py`:
  - `class QANode(Node)`.
  - `__init__(*, dispatcher: ClaudeCodeDispatcher,
     lint_command: str = "ruff check . && mypy --no-incremental")`.
  - `async def execute(self, prompt, ctx) -> QAReport`:
    1. Read `ResearchOutput` (for `worktree_path`) and `BugBrief` (for
       `acceptance_criteria`) from `ctx`.
    2. Build a `ClaudeCodeDispatchProfile` with `subagent="sdd-qa"`,
       `permission_mode="plan"`, `allowed_tools=["Read","Bash"]`.
       NEVER include `Edit` or `Write`.
    3. Build the dispatch prompt: list of `AcceptanceCriterion` (as
       JSON) and the lint command. Tell the subagent to return a
       `QAReport`.
    4. Dispatch; return the typed `QAReport` whether `passed=True` or
       `passed=False`. NO raising on `passed=False`.
    5. If the dispatcher raises `DispatchOutputValidationError`, do NOT
       catch — let the flow factory route to FailureHandler.

**NOT in scope**:
- The flow's pass/fail routing (TASK-886 handles that).
- The QA subagent definition itself (TASK-877).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | CREATE | `QANode`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa.py` | CREATE | Unit tests with mocked dispatcher. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import json
import logging
from typing import Any, Dict, List

from parrot.bots.flow.node import Node                           # node.py:14
from parrot.flows.dev_loop.models import (
    AcceptanceCriterion, BugBrief, ClaudeCodeDispatchProfile,
    QAReport, ResearchOutput,
)
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
```

### Existing Signatures to Use

```python
# parrot/flows/dev_loop/dispatcher.py (TASK-878)
async def dispatch(
    self, *, brief, profile, output_model, run_id, node_id, cwd,
) -> T: ...
```

### Does NOT Exist

- ~~`permission_mode="readonly"`~~ — not a real value. Valid values:
  `default`, `acceptEdits`, `plan`, `bypassPermissions`. QA uses `plan`.
- ~~`AcceptanceCriterion.to_command()`~~ — the subagent reads the
  Pydantic JSON dump and constructs the subprocess invocation itself.

---

## Implementation Notes

### execute() shape

```python
class QANode(Node):
    def __init__(self, *, dispatcher, lint_command=None,
                 name: str = "qa"):
        super().__init__()
        self._init_node(name)
        self._dispatcher = dispatcher
        self._lint_command = (
            lint_command or "ruff check . && mypy --no-incremental"
        )
        self.logger = logging.getLogger(__name__)

    async def execute(self, prompt, ctx) -> QAReport:
        research: ResearchOutput = ctx["research_output"]
        brief: BugBrief = ctx["bug_brief"]

        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-qa",
            permission_mode="plan",
            allowed_tools=["Read", "Bash"],
            setting_sources=["project"],
        )

        criteria_json = json.dumps([
            c.model_dump() for c in brief.acceptance_criteria
        ])
        dispatch_prompt = (
            f"Run each acceptance criterion deterministically as a "
            f"subprocess and collect exit code + stdout/stderr tail. "
            f"Then run lint: `{self._lint_command}`. Return a single "
            f"JSON object matching QAReport.\n"
            f"Criteria: {criteria_json}"
        )

        report: QAReport = await self._dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=QAReport,
            run_id=ctx["run_id"],
            node_id=self.name,
            cwd=research.worktree_path,
        )
        # Return regardless of passed/failed — flow does the routing.
        self.logger.info("QA report: passed=%s, lint_passed=%s",
                         report.passed, report.lint_passed)
        return report
```

### Key Constraints

- Profile MUST NOT contain `Edit` or `Write` in `allowed_tools`.
- Profile MUST NOT use `permission_mode="acceptEdits"` or
  `bypassPermissions`. Use `plan`.
- Must NOT raise on `report.passed is False`.
- The subagent prompt MUST be deterministic (no LLM judgment) — only
  the subagent's subprocess execution is in scope per spec G6.

### References in Codebase

- TASK-877 — QA subagent definition.

---

## Acceptance Criteria

- [ ] Profile passed to dispatcher has
  `permission_mode="plan"` and `allowed_tools` excludes `Edit`/`Write`
  (`test_qa_node_dispatch_uses_plan_permission`).
- [ ] On `QAReport(passed=False, ...)` from dispatcher, `execute`
  returns the report and does NOT raise
  (`test_qa_node_returns_failure_without_raising`).
- [ ] On `QAReport(passed=True, ...)`, `execute` returns the report.
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.flows.dev_loop import (
    BugBrief, FlowtaskCriterion, LogSource, QAReport, ResearchOutput,
    ClaudeCodeDispatchProfile,
)
from parrot.flows.dev_loop.nodes.qa import QANode


@pytest.fixture
def ctx():
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1", spec_path="x", feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/abs/.claude/worktrees/feat-130-fix",
            log_excerpts=[],
        ),
        "bug_brief": BugBrief(
            summary="x" * 20, affected_component="y",
            log_sources=[],
            acceptance_criteria=[
                FlowtaskCriterion(name="run", task_path="a.yaml"),
            ],
            escalation_assignee="a", reporter="b",
        ),
    }


@pytest.mark.asyncio
async def test_uses_plan_permission(ctx):
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=QAReport(
        passed=True, criterion_results=[], lint_passed=True,
    ))
    node = QANode(dispatcher=dispatcher)
    await node.execute(prompt="", ctx=ctx)
    profile: ClaudeCodeDispatchProfile = (
        dispatcher.dispatch.call_args.kwargs["profile"]
    )
    assert profile.permission_mode == "plan"
    assert "Edit" not in (profile.allowed_tools or [])
    assert "Write" not in (profile.allowed_tools or [])


@pytest.mark.asyncio
async def test_returns_failure_without_raising(ctx):
    failing = QAReport(passed=False, criterion_results=[],
                       lint_passed=False, notes="boom")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=failing)
    node = QANode(dispatcher=dispatcher)
    result = await node.execute(prompt="", ctx=ctx)
    assert result.passed is False
```

---

## Agent Instructions

1. Confirm TASK-874, TASK-878, TASK-882 are completed.
2. Update index → `"in-progress"`.
3. Implement; tests; lint.
4. Move to completed.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
