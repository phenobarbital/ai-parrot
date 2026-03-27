# TASK-473: Remove Redundant Bot-Level Retry Loops

**Feature**: abstractbot-ask-clientretry
**Spec**: `sdd/specs/abstractbot-ask-clientretry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-470, TASK-471, TASK-472
**Assigned-to**: unassigned

---

## Context

> This task implements Module 5 from the spec. Now that all LLM clients handle
> retries and fallback internally, the redundant `retries` retry loops in
> `AbstractBot.conversation()` and `ask()` must be removed to eliminate
> the double-retry problem.

---

## Scope

- In `conversation()` (lines ~210-306 of `base.py`): remove the `for attempt in range(retries + 1)` loop
  - Keep the actual LLM call and all response processing
  - Keep the outer `try/except` for error logging and status updates
  - Remove `retries = kwargs.get('retries', 0)` and the loop structure
  - Remove the `await asyncio.sleep(1)` retry delay
- In `ask()` (lines ~714-859 of `base.py`): same removal
  - Remove `retries = kwargs.get('retries', 0)` and the `for attempt in range(retries + 1)` loop
  - Flatten the code — the `async with llm as client:` block moves to where the loop was
  - Remove the inner `except` that logged retry attempts
- Remove the `retries` kwarg handling entirely (it's no longer used)
- Verify `invoke()` — it does NOT have a retry loop, so no changes needed there
- Write a test confirming no double-retry behavior

**NOT in scope**: Changes to any LLM client code — those are done in TASK-470/471/472.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Remove retry loops from `conversation()` and `ask()` |
| `tests/bots/test_no_double_retry.py` | CREATE | Verify retry loops are removed |

---

## Implementation Notes

### conversation() — Before and After
```python
# BEFORE (lines ~210-308):
retries = kwargs.get('retries', 0)
try:
    for attempt in range(retries + 1):
        try:
            async with llm as client:
                # ... LLM call and response processing ...
                return self.get_response(response, ...)
        except Exception as e:
            if attempt < retries:
                self.logger.warning(f"Error in conversation (attempt ...): {e}. Retrying...")
                await asyncio.sleep(1)
                continue
            raise e
finally:
    await self._llm.close()

# AFTER:
try:
    async with llm as client:
        # ... LLM call and response processing (unchanged) ...
        return self.get_response(response, ...)
finally:
    await self._llm.close()
```

### ask() — Before and After
```python
# BEFORE (lines ~714-861):
retries = kwargs.get('retries', 0)
try:
    for attempt in range(retries + 1):
        try:
            async with llm as client:
                # ... LLM call and response processing ...
                return response
        except Exception as e:
            if attempt < retries:
                self.logger.warning(f"Error in ask (attempt ...): {e}. Retrying...")
                await asyncio.sleep(1)
                continue
            raise e
finally:
    pass

# AFTER:
async with llm as client:
    # ... LLM call and response processing (unchanged) ...
    return response
```

### Key Constraints
- Do NOT modify any response processing logic — only remove the retry loop wrapper
- Do NOT modify `invoke()` — it has no retry loop
- Preserve the `finally: await self._llm.close()` in `conversation()` — it's still needed
- Preserve the outer `try/except` blocks for `asyncio.CancelledError` and general exception handling
- Be careful with indentation when removing the loop — code moves left by one indent level

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/base.py` lines 210-308 — `conversation()` retry loop
- `packages/ai-parrot/src/parrot/bots/base.py` lines 714-861 — `ask()` retry loop

---

## Acceptance Criteria

- [ ] `conversation()` no longer has a `for attempt in range(retries + 1)` loop
- [ ] `ask()` no longer has a `for attempt in range(retries + 1)` loop
- [ ] No references to `retries = kwargs.get('retries', ...)` in `conversation()` or `ask()`
- [ ] `invoke()` unchanged (it had no retry loop)
- [ ] `conversation()` still closes `self._llm` in finally block
- [ ] All existing response processing logic preserved
- [ ] Outer exception handling (CancelledError, status updates) preserved
- [ ] Tests pass: `pytest tests/bots/test_no_double_retry.py -v`
- [ ] Existing bot tests still pass: `pytest tests/bots/ -v`

---

## Test Specification

```python
# tests/bots/test_no_double_retry.py
import pytest
import inspect
from parrot.bots.base import AbstractBot


class TestNoDoubleRetry:
    def test_conversation_no_retry_loop(self):
        """conversation() should not contain a retry loop."""
        source = inspect.getsource(AbstractBot.conversation)
        assert "for attempt in range" not in source
        assert "retries + 1" not in source

    def test_ask_no_retry_loop(self):
        """ask() should not contain a retry loop."""
        source = inspect.getsource(AbstractBot.ask)
        assert "for attempt in range" not in source
        assert "retries + 1" not in source

    def test_conversation_still_closes_llm(self):
        """conversation() still has finally block to close LLM."""
        source = inspect.getsource(AbstractBot.conversation)
        assert "self._llm.close()" in source
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/abstractbot-ask-clientretry.spec.md`
2. **Check dependencies** — verify TASK-470, TASK-471, TASK-472 are completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/bots/base.py` — understand the full `conversation()` and `ask()` methods
5. **Carefully remove** the retry loops while preserving all other logic
6. **Run tests**: `pytest tests/bots/ -v` to ensure no regressions
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 4.6
**Date**: 2026-03-28
**Notes**: Removed `for attempt in range(retries + 1)` loops from both `BaseBot.conversation()` and `BaseBot.ask()`. Removed `retries = kwargs.get('retries', 0)` extraction. Preserved finally/close block in conversation(), CancelledError handling in both methods, and all response processing logic. Tests use `BaseBot` (concrete subclass) since `AbstractBot` methods are abstract stubs. 192 total tests pass.

**Deviations from spec**: Tests reference `BaseBot` instead of `AbstractBot` since the implementations live in `BaseBot` (the concrete subclass in base.py), not in the abstract class.
