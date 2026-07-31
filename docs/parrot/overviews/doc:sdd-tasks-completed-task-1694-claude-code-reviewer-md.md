---
type: Wiki Overview
title: 'TASK-1694: ClaudeCodeReviewDispatcher'
id: doc:sdd-tasks-completed-task-1694-claude-code-reviewer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: from parrot.flows.dev_loop.code_review import (
relates_to:
- concept: mod:parrot.flows.dev_loop.code_review
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
---

# TASK-1694: ClaudeCodeReviewDispatcher

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1692, TASK-1693
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 from the spec — the Claude Code concrete code
> review dispatcher. It wraps `ClaudeCodeDispatcher` with a write-enabled
> review profile and delegates to the `sdd-codereview` subagent.

---

## Scope

- Implement `ClaudeCodeReviewDispatcher` in `code_review.py`:
  - Inherits `AbstractCodeReviewDispatcher`
  - `agent_name = "claude-code"`
  - Constructor accepts a `ClaudeCodeDispatcher` instance + optional model override
  - `build_review_profile()` returns `ClaudeCodeReviewProfile` with write tools
  - `review()` delegates to `self._dispatcher.dispatch()` with:
    - `profile=self.build_review_profile()`
    - `output_model=CodeReviewVerdict`
    - The brief, run_id, node_id, cwd passed through
  - Degrade-on-infra-error: catch exceptions, return `CodeReviewVerdict(passed=True, findings=[...skip message...])`
- Register with `@CodeReviewDispatcherFactory.register("claude-code")`
- Write unit tests.

**NOT in scope**: Codex/Gemini reviewers (Tasks 1695–1696), QANode changes (Task 1697).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | Add ClaudeCodeReviewDispatcher |
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | MODIFY | Add tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher  # dispatcher.py:145
from parrot.flows.dev_loop.models import (
    ClaudeCodeReviewProfile,      # created by TASK-1693
    CodeReviewVerdict,            # created by TASK-1693
    CodeReviewFinding,            # created by TASK-1693
    ClaudeCodeDispatchProfile,    # models.py:374
)
from parrot import conf                                            # conf.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:145
class ClaudeCodeDispatcher:
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...
    async def dispatch(self, *, brief, profile: ClaudeCodeDispatchProfile,
                       output_model, run_id, node_id, cwd) -> T: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:224
# Current _run_code_review pattern to mirror:
async def _run_code_review(self, shared, research, brief) -> tuple[bool, List[str]]:
    profile = ClaudeCodeDispatchProfile(
        subagent="sdd-codereview",
        permission_mode="plan",
        allowed_tools=["Read", "Bash", "Grep", "Glob"],
        setting_sources=["project"],
        model=self._codereview_model,
    )
    # ...
    verdict = await self._dispatcher.dispatch(
        brief=review_brief, profile=profile,
        output_model=_CodeReviewVerdict,
        run_id=shared["run_id"], node_id=self.name, cwd=review_cwd,
    )
```

### Does NOT Exist
- ~~`ClaudeCodeReviewDispatcher`~~ — this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
@CodeReviewDispatcherFactory.register("claude-code")
class ClaudeCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    agent_name = "claude-code"

    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or conf.DEV_LOOP_CODEREVIEW_MODEL
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> ClaudeCodeReviewProfile:
        return ClaudeCodeReviewProfile(model=self._model)

    async def review(self, *, brief, run_id, node_id, cwd) -> CodeReviewVerdict:
        try:
            return await self._dispatcher.dispatch(
                brief=brief,
                profile=self.build_review_profile(),
                output_model=CodeReviewVerdict,
                run_id=run_id, node_id=node_id, cwd=cwd,
            )
        except Exception as exc:
            self.logger.warning("Code-review dispatch failed: %s", exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[CodeReviewFinding(
                    message=f"code-review could not run: {exc}",
                    severity="nit",
                )],
            )
```

### Key Constraints
- Must preserve FEAT-250 G4 degrade-on-infra-error behavior
- The `_CODE_REVIEW_SKIP_PREFIX` detection in `QANode` relies on findings starting
  with `"code-review could not run:"` — the error finding message must start with this
- Use `conf.DEV_LOOP_CODEREVIEW_MODEL` as default model

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:224-265` — current `_run_code_review` to replace
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:145` — `ClaudeCodeDispatcher` being wrapped

---

## Acceptance Criteria

- [ ] `ClaudeCodeReviewDispatcher` inherits `AbstractCodeReviewDispatcher`
- [ ] Registered as `"claude-code"` in factory
- [ ] `build_review_profile()` returns write-enabled `ClaudeCodeReviewProfile`
- [ ] `review()` delegates to `ClaudeCodeDispatcher.dispatch()`
- [ ] Infra errors degrade to pass with skip-prefix finding
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_code_review.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.flows.dev_loop.code_review import ClaudeCodeReviewDispatcher
from parrot.flows.dev_loop.models import CodeReviewVerdict, ClaudeCodeReviewProfile


class TestClaudeCodeReviewDispatcher:
    def test_agent_name(self):
        d = ClaudeCodeReviewDispatcher(dispatcher=MagicMock())
        assert d.agent_name == "claude-code"

    def test_build_review_profile(self):
        d = ClaudeCodeReviewDispatcher(dispatcher=MagicMock())
        p = d.build_review_profile()
        assert isinstance(p, ClaudeCodeReviewProfile)
        assert p.permission_mode == "default"
        assert "Edit" in p.allowed_tools

    @pytest.mark.asyncio
    async def test_review_delegates(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = ClaudeCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1",
                                node_id="qa", cwd="/tmp")
        assert result.passed is True
        mock_disp.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_degrades_on_error(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        d = ClaudeCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1",
                                node_id="qa", cwd="/tmp")
        assert result.passed is True
        assert any("code-review could not run" in f.message for f in result.findings)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1692, TASK-1693 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `ClaudeCodeDispatcher` still at dispatcher.py:145
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1694-claude-code-reviewer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `ClaudeCodeReviewDispatcher` to `code_review.py`, registered as
`"claude-code"`. Constructor accepts a `ClaudeCodeDispatcher` + optional model
override (defaulting to `conf.DEV_LOOP_CODEREVIEW_MODEL`). `review()`
delegates to `dispatcher.dispatch()` with `CodeReviewVerdict` as the output
model, and degrades to `passed=True` with a `"code-review could not run: ..."`
finding on any exception (FEAT-250 G4 preserved). Tests cover agent_name,
factory registration, profile write-tools, delegation, and error-degradation.
All 16 tests pass; `ruff check` clean.

**Deviations from spec**: none
