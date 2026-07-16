---
type: Wiki Overview
title: 'TASK-1696: GeminiCodeReviewDispatcher'
id: doc:sdd-tasks-completed-task-1696-gemini-code-reviewer-md
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

# TASK-1696: GeminiCodeReviewDispatcher

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1692, TASK-1693
**Assigned-to**: unassigned

---

## Context

> This task implements Module 5 from the spec — the Gemini CLI concrete code
> review dispatcher. It wraps `GeminiCodeDispatcher` with sandbox disabled
> and auto-edit approval mode for review + fix.

---

## Scope

- Implement `GeminiCodeReviewDispatcher` in `code_review.py`:
  - Inherits `AbstractCodeReviewDispatcher`
  - `agent_name = "gemini"`
  - Constructor accepts a `GeminiCodeDispatcher` instance + optional model override
  - `build_review_profile()` returns `GeminiCodeReviewProfile` with
    `sandbox=False` and `approval_mode="auto_edit"`
  - `review()` delegates to `self._dispatcher.dispatch()` with the review profile
    and `CodeReviewVerdict` as output_model
  - Degrade-on-infra-error behavior matching Claude reviewer
- Register with `@CodeReviewDispatcherFactory.register("gemini")`
- Write unit tests.

**NOT in scope**: QANode changes (Task 1697), factory wiring (Task 1698).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | Add GeminiCodeReviewDispatcher |
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | MODIFY | Add tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)
from parrot.flows.dev_loop.dispatcher import GeminiCodeDispatcher  # dispatcher.py:1281
from parrot.flows.dev_loop.models import (
    GeminiCodeReviewProfile,      # created by TASK-1693
    CodeReviewVerdict,            # created by TASK-1693
    CodeReviewFinding,            # created by TASK-1693
    GeminiCodeDispatchProfile,    # models.py:433
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:1281
class GeminiCodeDispatcher:
    def __init__(self, *, max_concurrent, redis_url, stream_ttl_seconds,
                 gemini_bin="gemini") -> None: ...
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd) -> T: ...
```

### Does NOT Exist
- ~~`GeminiCodeReviewDispatcher`~~ — this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
@CodeReviewDispatcherFactory.register("gemini")
class GeminiCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    agent_name = "gemini"

    def __init__(self, *, dispatcher: GeminiCodeDispatcher,
                 model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or "auto"
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> GeminiCodeReviewProfile:
        return GeminiCodeReviewProfile(model=self._model)

    async def review(self, *, brief, run_id, node_id, cwd) -> CodeReviewVerdict:
        try:
            return await self._dispatcher.dispatch(
                brief=brief,
                profile=self.build_review_profile(),
                output_model=CodeReviewVerdict,
                run_id=run_id, node_id=node_id, cwd=cwd,
            )
        except Exception as exc:
            self.logger.warning("Gemini code-review dispatch failed: %s", exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[CodeReviewFinding(
                    message=f"code-review could not run: {exc}",
                    severity="nit",
                )],
            )
```

### Key Constraints
- `GeminiCodeDispatcher` uses CLI spawning (`gemini --output-format stream-json`)
- The dispatcher transparently converts `ClaudeCodeDispatchProfile` via inline mapping
  (dispatcher.py lines 1335-1350) — the `GeminiCodeReviewProfile` is a native Gemini
  profile, so no conversion is needed
- Error finding message must start with `"code-review could not run:"`

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:1281` — `GeminiCodeDispatcher`
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` — `ClaudeCodeReviewDispatcher` as pattern

---

## Acceptance Criteria

- [ ] `GeminiCodeReviewDispatcher` inherits `AbstractCodeReviewDispatcher`
- [ ] Registered as `"gemini"` in factory
- [ ] `build_review_profile()` returns `GeminiCodeReviewProfile` with `sandbox=False`
- [ ] `review()` delegates to `GeminiCodeDispatcher.dispatch()`
- [ ] Infra errors degrade to pass with skip-prefix finding
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_code_review.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.flows.dev_loop.code_review import GeminiCodeReviewDispatcher
from parrot.flows.dev_loop.models import CodeReviewVerdict, GeminiCodeReviewProfile


class TestGeminiCodeReviewDispatcher:
    def test_agent_name(self):
        d = GeminiCodeReviewDispatcher(dispatcher=MagicMock())
        assert d.agent_name == "gemini"

    def test_build_review_profile(self):
        d = GeminiCodeReviewDispatcher(dispatcher=MagicMock())
        p = d.build_review_profile()
        assert isinstance(p, GeminiCodeReviewProfile)
        assert p.sandbox is False
        assert p.approval_mode == "auto_edit"

    @pytest.mark.asyncio
    async def test_review_delegates(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(return_value=CodeReviewVerdict(passed=True))
        d = GeminiCodeReviewDispatcher(dispatcher=mock_disp)
        result = await d.review(brief=MagicMock(), run_id="r1",
                                node_id="qa", cwd="/tmp")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_review_degrades_on_error(self):
        mock_disp = MagicMock()
        mock_disp.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        d = GeminiCodeReviewDispatcher(dispatcher=mock_disp)
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
3. **Verify the Codebase Contract** — confirm `GeminiCodeDispatcher` still at dispatcher.py:1281
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1696-gemini-code-reviewer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added `GeminiCodeReviewDispatcher` to `code_review.py`, registered as
`"gemini"`. Mirrors the Claude/Codex reviewers, wrapping `GeminiCodeDispatcher`
with `GeminiCodeReviewProfile` (`sandbox=False`, `approval_mode="auto_edit"`)
and the same degrade-on-infra-error behavior. Tests cover agent_name, factory
registration, profile fields, delegation, and error-degradation. All 26 tests
pass; `ruff check` clean. `code_review.py` now contains all three concrete
reviewers (Modules 1–5 of the spec complete).

**Deviations from spec**: none
