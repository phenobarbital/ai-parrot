# TASK-885: `FailureHandlerNode` — Jira escalation on failure

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-874
**Assigned-to**: unassigned

---

## Context

Implements **Module 9**. Terminal failure node. Routed-to either by:

- An explicit pass/fail transition out of `QANode` when `passed=False`.
- A global error transition when any earlier node raises (typically
  `DispatchExecutionError`, `DispatchOutputValidationError`, or
  `RuntimeError` from `ResearchNode`).

Behavior: post a structured Jira comment, transition the ticket to
"Needs Human Review", reassign to `BugBrief.escalation_assignee`. Then
end the flow gracefully.

Spec acceptance criterion: "Any `DispatchExecutionError` /
`DispatchOutputValidationError` raised by a middle node also routes to
`FailureHandlerNode`."

---

## Scope

- Implement `parrot/flows/dev_loop/nodes/failure_handler.py`:
  - `class FailureHandlerNode(Node)`.
  - `__init__(*, jira_toolkit, name: str = "failure_handler")`.
  - `async def execute(self, prompt, ctx) -> Dict[str, str]`.
  - Reads from `ctx`:
    - `bug_brief: BugBrief` (escalation_assignee + reporter).
    - `research_output: Optional[ResearchOutput]` (for `jira_issue_key`
      if research succeeded).
    - `failure_kind: str` — one of `"qa_failed"`, `"node_error"`.
    - `failure_payload: Any` — `QAReport` if qa-failed, or
      `{"node_id", "exception_type", "message"}` for node errors.
  - Builds a structured comment body; posts via `jira_add_comment`;
    transitions via `jira_transition_issue` to "Needs Human Review";
    reassigns via `jira_assign_issue` (line 1347 of jiratoolkit).
  - Returns `{"status": "escalated", "issue_key": <key>}`.

**NOT in scope**:
- Telegram HITL (out of scope per spec §1).
- Auto-retry (out of scope).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` | CREATE | `FailureHandlerNode`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_failure_handler.py` | CREATE | Unit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import logging
from typing import Any, Dict, Optional

from parrot.bots.flow.node import Node                           # node.py:14
from parrot.flows.dev_loop.models import (
    BugBrief, QAReport, ResearchOutput,
)
from parrot_tools.jiratoolkit import JiraToolkit                 # jiratoolkit.py:609
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
async def jira_transition_issue(self, ...): ...                  # line 1209
async def jira_assign_issue(self, issue: str,
                            assignee: str) -> Dict[str, Any]:     # line 1347
async def jira_add_comment(self, ...): ...                       # line 1616
```

### Does NOT Exist

- ~~`Node.flow_terminate(...)`~~ — there is no built-in terminate
  method on `Node`. Returning normally signals end of node execution;
  the flow factory wires this node as terminal.

---

## Implementation Notes

```python
class FailureHandlerNode(Node):
    def __init__(self, *, jira_toolkit, name: str = "failure_handler"):
        super().__init__()
        self._init_node(name)
        self._jira = jira_toolkit
        self.logger = logging.getLogger(__name__)

    async def execute(self, prompt, ctx) -> Dict[str, str]:
        brief: BugBrief = ctx["bug_brief"]
        research: Optional[ResearchOutput] = ctx.get("research_output")
        failure_kind: str = ctx.get("failure_kind", "node_error")
        failure_payload: Any = ctx.get("failure_payload")

        issue_key = research.jira_issue_key if research else None
        if not issue_key:
            self.logger.error(
                "FailureHandler: no jira_issue_key in ctx; "
                "research never created the ticket. ctx=%s", ctx,
            )
            return {"status": "escalated_without_ticket"}

        body = self._build_comment(failure_kind, failure_payload)
        await self._jira.jira_add_comment(issue=issue_key, body=body)
        await self._jira.jira_transition_issue(
            issue=issue_key, transition="Needs Human Review",
        )
        await self._jira.jira_assign_issue(
            issue=issue_key, assignee=brief.escalation_assignee,
        )
        return {"status": "escalated", "issue_key": issue_key}

    def _build_comment(self, kind, payload) -> str:
        if kind == "qa_failed" and isinstance(payload, QAReport):
            return (
                "QA failed. Acceptance criterion results:\n" +
                "\n".join(
                    f"- {r.name}: exit={r.exit_code}, "
                    f"passed={r.passed}, stderr_tail={r.stderr_tail!r}"
                    for r in payload.criterion_results
                ) +
                f"\nLint passed: {payload.lint_passed}"
            )
        if kind == "node_error":
            d = payload or {}
            return (
                f"Flow halted on node `{d.get('node_id','?')}` with "
                f"`{d.get('exception_type','?')}`:\n\n"
                f"```\n{d.get('message','')}\n```"
            )
        return f"Flow failed: {kind}"
```

### Key Constraints

- This node MUST NOT raise. If Jira itself errors, log and return
  `{"status": "escalation_failed", ...}`. (The orchestrator marks the
  run as abandoned per spec §7 R8 if even escalation fails.)
- `jira_assign_issue` arg name verified at line 1347.

### References in Codebase

- `parrot_tools/jiratoolkit.py:1209,1347,1616` — exact methods used.

---

## Acceptance Criteria

- [ ] On `qa_failed`, the comment body includes per-criterion
  `exit_code` + `passed` + lint status.
- [ ] On `node_error`, the comment body includes the node id and
  exception class.
- [ ] `jira_assign_issue` is called with
  `assignee=brief.escalation_assignee`
  (`test_failure_handler_reassigns_to_escalation`).
- [ ] Node never raises — Jira errors are caught and logged.
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_failure_handler.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.flows.dev_loop import (
    BugBrief, FlowtaskCriterion, QAReport, ResearchOutput,
)
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode


@pytest.mark.asyncio
async def test_reassigns_to_escalation():
    jira = MagicMock()
    jira.jira_add_comment = AsyncMock()
    jira.jira_transition_issue = AsyncMock()
    jira.jira_assign_issue = AsyncMock()

    node = FailureHandlerNode(jira_toolkit=jira)
    brief = BugBrief(
        summary="x" * 20, affected_component="y", log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="x", task_path="a.yaml")],
        escalation_assignee="557058:human", reporter="557058:other",
    )
    research = ResearchOutput(
        jira_issue_key="OPS-1", spec_path="x", feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path="/abs/.claude/worktrees/feat-130-fix",
        log_excerpts=[],
    )
    qa = QAReport(passed=False, criterion_results=[], lint_passed=True)
    ctx = {"bug_brief": brief, "research_output": research,
           "failure_kind": "qa_failed", "failure_payload": qa}
    result = await node.execute(prompt="", ctx=ctx)
    assert result == {"status": "escalated", "issue_key": "OPS-1"}
    jira.jira_assign_issue.assert_awaited_with(
        issue="OPS-1", assignee="557058:human",
    )
```

---

## Agent Instructions

1. Confirm TASK-874 is completed.
2. Verify `jira_assign_issue` signature at jiratoolkit.py:1347.
3. Update index → `"in-progress"`.
4. Implement; tests; lint.
5. Move to completed.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-27
**Notes**: Implemented `FailureHandlerNode` with structured comment
construction for both `qa_failed` (renders per-criterion exit codes,
stderr tails, lint status) and `node_error` (renders node id + exception
class + traceback message). Calls `jira_add_comment`,
`jira_transition_issue("Needs Human Review")`, and
`jira_assign_issue(escalation_assignee)` in sequence. Never raises:
returns `{"status": "escalation_failed", ...}` on Jira-side error and
`{"status": "escalated_without_ticket"}` when research never created the
ticket. 5 unit tests cover the QA path, node-error path, no-ticket path,
and the Jira-failure-doesn't-propagate guarantee.
**Deviations from spec**: None.
