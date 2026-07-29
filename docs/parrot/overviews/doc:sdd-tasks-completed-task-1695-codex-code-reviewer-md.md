---
type: Wiki Overview
title: 'TASK-1695: CodexCodeReviewDispatcher'
id: doc:sdd-tasks-completed-task-1695-codex-code-reviewer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: and `CodeReviewVerdict` as output_model
relates_to:
- concept: mod:parrot.flows.dev_loop.code_review
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
---

# TASK-1695: CodexCodeReviewDispatcher

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1692, TASK-1693
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec — the Codex CLI concrete code
> review dispatcher. It wraps `CodexCodeDispatcher` with a write-enabled
> sandbox profile for review + fix.

---

## Scope

- Implement `CodexCodeReviewDispatcher` in `code_review.py`:
  - Inherits `AbstractCodeReviewDispatcher`
  - `agent_name = "codex"`
  - Constructor accepts a `CodexCodeDispatcher` instance + optional model override
  - `build_review_profile()` returns `CodexCodeReviewProfile` with
    `sandbox="workspace-write"` and `approval_policy="auto-edit"`
  - `review()` delegates to `self._dispatcher.dispatch()` with the review profile
    and `CodeReviewVerdict` as output_model
  - Degrade-on-infra-error behavior matching Claude reviewer
- Register with `@CodeReviewDispatcherFactory.register("codex")`
- Write unit tests.

**NOT in scope**: Gemini reviewer (Task 1696), QANode changes (Task 1697).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | Add CodexCodeReviewDispatcher |
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | MODIFY | Add tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher   # dispatcher.py:859
from parrot.flows.dev_loop.models import (
    CodexCodeReviewProfile,       # created by TASK-1693
    CodeReviewVerdict,            # created by TASK-1693
    CodeReviewFinding,            # created by TASK-1693
    CodexCodeDispatchProfile,     # models.py:404
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:859
class CodexCodeDispatcher:
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds,
                 codex_bin="codex") -> None: ...
    async def dispatch(self, *, brief, profile: CodexCodeDispatchProfile,
                       output_model, run_id, node_id, cwd) -> T: ...
```

### Does NOT Exist
- ~~`CodexCodeReviewDispatcher`~~ — this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
@CodeReviewDispatcherFactory.register("codex")
class CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    agent_name = "codex"

    def __init__(self, *, dispatcher: CodexCodeDispatcher,
                 model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or "gpt-5.5"
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> CodexCodeReviewProfile:
        return CodexCodeReviewProfile(model=self._model)

    async def review(self, *, brief, run_id, node_id, cwd) -> CodeReviewVerdict:
        try:
            return await self._dispatcher.dispatch(
                brief=brief,
                profile=self.build_review_profile(),
                output_model=CodeReviewVerdict,
                run_id=run_id, node_id=node_id, cwd=cwd,
            )
        except Exception as exc:
            self.logger.warning("Codex code-review dispatch failed: %s", exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[CodeReviewFinding(
                    message=f"code-review could not run: {exc}",
                    severity="nit",
                )],
            )
```

### Key Constraints
- `CodexCodeDispatcher` uses CLI spawning (`codex exec --json`) — the review
  profile just changes sandbox/approval settings, the dispatch mechanism is the same
- The `sdd-codereview` subagent prompt is loaded by the Codex dispatcher as the
  system instruction — no separate prompt file needed initially
- Error finding message must start with `"code-review could not run:"`

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:859` — `CodexCodeDispatcher`
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` — `ClaudeCodeReviewDispatcher` as pattern

---

## Acceptance Criteria

- [ ] `CodexCodeReviewDispatcher` inherits `AbstractCodeReviewDispatcher`
- [ ] Registered as `"codex"` in factory
- [ ] `build_review_profile()` returns `CodexCodeReviewProfile` with `approval_policy="auto-edit"`
- [ ] `review()` delegates to `CodexCodeDispatcher.dispatch()`
- [ ] Infra errors degrade to pass with skip-prefix finding
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_code_review.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.flows.dev_loop.code_review import CodexCodeReviewDispatcher
from parrot.flows.dev_loop.models import CodeReviewVerdict, CodexCodeReviewProfile


class TestCodexCodeReviewDispatcher:
    def test_agent_name(self):
        d = CodexCodeReviewDispatcher(dispatcher=MagicMock())
        assert d.agent_name == "codex"

    def test_build_review_profile(self):
        d = CodexCodeReviewDispatcher(dispatcher=MagicMock())
        p = d.build_review_profile()
        assert isinstance(p, CodexCodeReviewProfile)
        assert p.sandbox == "workspace-write"
        assert p.approval_policy == "auto-edit"

    @pytest.mark.asyncio
    async def test_review_delegates(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = CodexCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1",
                                node_id="qa", cwd="/tmp")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_review_degrades_on_error(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        d = CodexCodeReviewDispatcher(dispatcher=mock_disp)
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
3. **Verify the Codebase Contract** — confirm `CodexCodeDispatcher` still at dispatcher.py:859
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1695-codex-code-reviewer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `CodexCodeReviewDispatcher` to `code_review.py`, registered as
`"codex"`. Mirrors `ClaudeCodeReviewDispatcher`'s structure exactly, wrapping
`CodexCodeDispatcher` with `CodexCodeReviewProfile` (`sandbox="workspace-write"`,
`approval_policy="auto-edit"`) and the same degrade-on-infra-error behavior.
Tests cover agent_name, factory registration, profile fields, delegation,
and error-degradation. All 21 tests pass; `ruff check` clean.

**Deviations from spec**: none
