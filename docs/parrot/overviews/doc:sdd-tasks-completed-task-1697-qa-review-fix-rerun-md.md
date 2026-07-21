---
type: Wiki Overview
title: 'TASK-1697: QANode Review-Fix-Rerun Loop'
id: doc:sdd-tasks-completed-task-1697-qa-review-fix-rerun-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: the deterministic QA pass (acceptance criteria + lint)
relates_to:
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.flows.dev_loop.code_review
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.qa
  rel: mentions
---

# TASK-1697: QANode Review-Fix-Rerun Loop

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1692, TASK-1693, TASK-1694
**Assigned-to**: unassigned

---

## Context

> This task implements Module 6 from the spec — the core QANode modification
> that replaces the hardcoded Claude-only code review with the pluggable
> `AbstractCodeReviewDispatcher` and adds the re-run loop after reviewer fixes.
> This is the most complex task in the feature.

---

## Scope

- Modify `QANode.__init__` to accept `codereview_dispatcher: AbstractCodeReviewDispatcher | None`:
  - If provided, use it for code review
  - If `None` (backward compatibility), wrap the existing `dispatcher` param in a
    `ClaudeCodeReviewDispatcher` automatically
  - Remove `codereview_model` param (superseded by the reviewer dispatcher's own model)
- Rewrite `_run_code_review()` to delegate to `self._codereview_dispatcher.review()`:
  - Pass `_CodeReviewBrief` as the brief
  - Receive `CodeReviewVerdict` (new extended model)
  - Convert findings to the format needed by QAReport
- Add the re-run loop after code review:
  - If code review made fixes (`verdict.files_modified` is non-empty), re-dispatch
    the deterministic QA pass (acceptance criteria + lint)
  - If re-run fails, QA reports failure
  - If code review found no issues or made no fixes, skip re-run
- Replace `_CodeReviewVerdict` usage with the public `CodeReviewVerdict`
- Preserve all existing degrade-on-infra-error behavior (FEAT-250 G4)
- Preserve `_CODE_REVIEW_SKIP_PREFIX` detection for skipped reviews
- Update existing tests in `test_qa_codereview.py` to work with new interface

**NOT in scope**: Factory wiring (Task 1698), server bootstrap (Task 1698), subagent prompt changes (Task 1699).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | New `__init__` param, rewrite `_run_code_review`, add re-run loop |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py` | MODIFY | Update for new interface, add re-run tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    ClaudeCodeReviewDispatcher,      # created by TASK-1694
)
from parrot.flows.dev_loop.models import (
    CodeReviewVerdict,               # created by TASK-1693
    CodeReviewFinding,               # created by TASK-1693
    ClaudeCodeDispatchProfile,       # models.py:374
    AcceptanceCriterion,             # models.py
    BugBrief,                        # models.py
    QAReport,                        # models.py
    ResearchOutput,                  # models.py
)
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher  # dispatcher.py:145
from parrot.bots.flows.core.context import FlowContext            # core/context.py
from parrot import conf                                            # conf.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:86
class QANode(DevLoopNode):
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 lint_command: Optional[str] = None,
                 codereview_model: Optional[str] = None,
                 name: str = "qa") -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)           # line 98
        object.__setattr__(self, "_lint_command", lint_command or ...) # line 99
        object.__setattr__(self, "_codereview_model", codereview_model or conf.DEV_LOOP_CODEREVIEW_MODEL)  # line 102

    async def execute(self, ctx, deps=None, **kwargs) -> QAReport:    # line 110
        # ... runs deterministic QA, then code review, combines results

    async def _run_code_review(self, shared, research, brief
                               ) -> tuple[bool, List[str]]:           # line 224
        # Currently hardcoded to ClaudeCodeDispatcher + ClaudeCodeDispatchProfile
        # with permission_mode="plan", allowed_tools=["Read","Bash","Grep","Glob"]

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:43
class _QABrief(BaseModel):
    acceptance_criteria: List[AcceptanceCriterion]
    lint_command: str
    worktree_path: str
    summary: str = ""

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:58
class _CodeReviewBrief(BaseModel):
    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str
    summary: str = ""
    jira_issue_key: str = ""

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:72
class _CodeReviewVerdict(BaseModel):
    passed: bool = True
    findings: List[str] = Field(default_factory=list)
    summary: str = ""
```

### Does NOT Exist
- ~~`QANode.codereview_dispatcher`~~ — does not exist yet; this task adds it
- ~~`QANode._rerun_deterministic_qa()`~~ — does not exist; this task adds the re-run logic

---

## Implementation Notes

### Pattern to Follow
```python
class QANode(DevLoopNode):
    def __init__(
        self,
        *,
        dispatcher: ClaudeCodeDispatcher,
        lint_command: Optional[str] = None,
        codereview_dispatcher: Optional[AbstractCodeReviewDispatcher] = None,
        name: str = "qa",
    ) -> None:
        super().__init__(node_id=name)
        object.__setattr__(self, "_dispatcher", dispatcher)
        object.__setattr__(self, "_lint_command", lint_command or _DEFAULT_LINT_COMMAND)
        # Backward compat: if no reviewer provided, wrap the Claude dispatcher
        if codereview_dispatcher is None:
            codereview_dispatcher = ClaudeCodeReviewDispatcher(dispatcher=dispatcher)
        object.__setattr__(self, "_codereview_dispatcher", codereview_dispatcher)

    async def execute(self, ctx, deps=None, **kwargs) -> QAReport:
        # 1. Run deterministic QA (unchanged)
        # 2. Run code review via self._codereview_dispatcher.review()
        # 3. If reviewer made fixes (files_modified non-empty), re-run deterministic QA
        # 4. Combine: passed = deterministic AND review AND (rerun if applicable)
```

### Key Constraints
- `codereview_model` param is REMOVED — the reviewer dispatcher owns its model config
- `_CodeReviewVerdict` can be REMOVED (replaced by `CodeReviewVerdict` from models.py)
- `_CodeReviewBrief` stays (it's the brief format passed to all reviewers)
- The re-run of deterministic QA uses the SAME dispatch path as the initial run
  (same `_QABrief`, same `sdd-qa` subagent) — the worktree may have changed
- `_CODE_REVIEW_SKIP_PREFIX` detection must use `finding.message` (now it's a
  `CodeReviewFinding` object, not a plain string)
- The `code_review_findings` field in the QA report update must be adapted:
  currently `List[str]`, now needs to serialize `List[CodeReviewFinding]`
  (or convert back to strings for backward compat)
- `object.__setattr__` is required because `DevLoopNode` is a frozen Pydantic model

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` — entire file, especially lines 86-265
- `packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py` — existing tests to update

---

## Acceptance Criteria

- [ ] `QANode.__init__` accepts `codereview_dispatcher: AbstractCodeReviewDispatcher | None`
- [ ] `QANode.__init__` without `codereview_dispatcher` auto-creates `ClaudeCodeReviewDispatcher` (backward compat)
- [ ] `_run_code_review` delegates to `self._codereview_dispatcher.review()`
- [ ] After code review with fixes, deterministic QA re-runs
- [ ] When no fixes made, re-run is skipped
- [ ] When re-run fails after fix, QA reports `passed=False`
- [ ] Infra error in code review degrades to pass (FEAT-250 G4 preserved)
- [ ] `_CODE_REVIEW_SKIP_PREFIX` detection works with new `CodeReviewFinding` objects
- [ ] All existing tests in `test_qa_codereview.py` pass (adapted for new interface)
- [ ] New re-run tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.models import CodeReviewVerdict, CodeReviewFinding, QAReport


class TestQANodeReviewFixRerun:
    @pytest.mark.asyncio
    async def test_rerun_after_fix(self):
        """When reviewer fixes files, deterministic QA re-runs."""
        mock_reviewer = MagicMock()
        mock_reviewer.review = AsyncMock(return_value=CodeReviewVerdict(
            passed=True,
            findings=[],
            files_modified=["sync.py"],  # indicates fixes were made
        ))
        # ... setup QANode with mock_reviewer, verify dispatch called twice

    @pytest.mark.asyncio
    async def test_skip_rerun_no_fixes(self):
        """When reviewer passes with no fixes, skip re-run."""
        mock_reviewer = MagicMock()
        mock_reviewer.review = AsyncMock(return_value=CodeReviewVerdict(
            passed=True, findings=[], files_modified=[],
        ))
        # ... verify dispatch called only once (initial deterministic QA)

    @pytest.mark.asyncio
    async def test_rerun_fails_after_fix(self):
        """When re-run fails after reviewer fix, QA fails."""
        # ... reviewer fixes, but re-run deterministic QA returns passed=False

    @pytest.mark.asyncio
    async def test_backward_compat_no_reviewer(self):
        """QANode without codereview_dispatcher auto-creates Claude reviewer."""
        node = QANode(dispatcher=MagicMock())
        assert hasattr(node, "_codereview_dispatcher")

    @pytest.mark.asyncio
    async def test_degrade_on_infra_error(self):
        """Infra error in review degrades to pass."""
        mock_reviewer = MagicMock()
        mock_reviewer.review = AsyncMock(side_effect=RuntimeError("boom"))
        # ... should not raise, should degrade
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1692, TASK-1693, TASK-1694 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `qa.py` fully to confirm current structure
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1697-qa-review-fix-rerun.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: `QANode.__init__` now accepts `codereview_dispatcher:
Optional[AbstractCodeReviewDispatcher]`; when omitted it auto-wraps the
existing `dispatcher` in a `ClaudeCodeReviewDispatcher` (backward compat).
`codereview_model` param and `_codereview_model` attribute removed (the
reviewer dispatcher now owns its own model). Extracted the original inline
deterministic-dispatch block into `_run_deterministic_qa()` so it can be
called twice: once for the initial pass, once for the re-run after the
reviewer reports `files_modified`. `_run_code_review()` now delegates to
`self._codereview_dispatcher.review()` and returns `(passed, findings,
files_modified)`, converting `CodeReviewFinding` objects to plain message
strings for `QAReport.code_review_findings` (kept as `List[str]` — not
touching `models.QAReport` since it isn't in this task's file list).
Removed the private `_CodeReviewVerdict` model from `qa.py` (replaced by the
public `CodeReviewVerdict` from `models.py`, per TASK-1693).
`_CODE_REVIEW_SKIP_PREFIX` detection preserved, now applied to
`finding.message` strings. Degrade-on-infra-error (FEAT-250 G4) preserved
via the reviewer dispatcher's own try/except.

Rewrote `test_qa_codereview.py` for the new interface (imports
`CodeReviewVerdict`/`CodeReviewFinding` from `models.py` instead of the
removed `_CodeReviewVerdict`), updated the write-enabled-profile assertion
(FEAT-270 review profiles are write-enabled, not read-only), and added the
re-run/skip-rerun/rerun-fails/backward-compat/custom-dispatcher test cases
from the task's Test Specification.

**Deviations from spec**: Also had to touch `test_qa.py` (not in this
task's file list) because four of its existing tests mocked
`dispatcher.dispatch` with a single `return_value` applied to *every* call;
since the default `codereview_dispatcher` re-uses the same `dispatcher` for
the code-review pass, those mocks now returned a `QAReport` where a
`CodeReviewVerdict` was expected (`AttributeError` on `.findings`). Fixed by
switching those mocks to `side_effect=[<qa-report>, CodeReviewVerdict(...)]`
and pointing `TestPermissionMode`/`TestCwd` assertions at
`await_args_list[0]` (the deterministic dispatch) instead of `await_args`
(which is now the write-enabled review dispatch) — otherwise `pytest
tests/flows/dev_loop/` would regress. Full `dev_loop/` suite (excluding
`-m live`) re-run after this change: 329 passed; the same 4 pre-existing
failures (`test_server_repo_wiring.py`, `test_webhook.py`
`TestSweepFinishedWorktrees`) reproduce identically on unmodified `qa.py`
(verified via `git stash`) — confirmed pre-existing test-order flakiness,
unrelated to this feature.
