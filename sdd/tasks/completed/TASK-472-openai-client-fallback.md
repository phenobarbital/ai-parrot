# TASK-472: OpenAIClient Fallback Model

**Feature**: abstractbot-ask-clientretry
**Spec**: `sdd/specs/abstractbot-ask-clientretry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-469
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec. OpenAIClient currently uses tenacity
> with `stop_after_attempt(5)` for retries — all hitting the same model. This task
> adds fallback to `gpt-4.1-nano` on capacity errors and reduces tenacity attempts
> to avoid slow failure cascades.

---

## Scope

- Set `_fallback_model = 'gpt-4.1-nano'` as class attribute on `OpenAIClient`
- Override `_is_capacity_error()` to detect OpenAI-specific exception types:
  - `openai.RateLimitError` (HTTP 429)
  - `openai.APIError` with `status_code in (502, 503)`
- Reduce tenacity `stop_after_attempt` from 5 to 3 in `_chat_completion()` to limit retries before fallback
- Add fallback logic: when tenacity exhausts retries on a capacity error, catch and retry **once** with `self._fallback_model`
- Set response metadata (`used_fallback_model`, `original_model`, `fallback_model`) when fallback triggers
- Write tests for OpenAI fallback behavior

**NOT in scope**: Changes to `GoogleGenAIClient`, `AnthropicClient`, or `AbstractBot`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Add `_fallback_model`, override `_is_capacity_error()`, add fallback in `ask()`/`_chat_completion()` |
| `tests/clients/test_openai_fallback.py` | CREATE | Tests for OpenAI fallback behavior |

---

## Implementation Notes

### Fallback Strategy
Two options for where to place the fallback:

**Option A (recommended):** Wrap in `ask()` at the outer level:
```python
# In ask(), around the _chat_completion call:
try:
    response = await self._chat_completion(model=model, messages=messages, ...)
except Exception as e:
    if self._should_use_fallback(model, e):
        self.logger.warning(
            f"Model {model} capacity error: {e}. Retrying with: {self._fallback_model}"
        )
        response = await self._chat_completion(model=self._fallback_model, messages=messages, ...)
        # Mark fallback metadata
    else:
        raise
```

**Option B:** Inside `_chat_completion()` after tenacity exhausts. Less preferred because
`_chat_completion` is a lower-level utility.

### Tenacity Reduction
```python
# BEFORE:
stop=stop_after_attempt(5)

# AFTER:
stop=stop_after_attempt(3)
```

### Capacity Error Detection
```python
def _is_capacity_error(self, error: Exception) -> bool:
    """Detect OpenAI capacity errors."""
    from openai import RateLimitError, APIError
    if isinstance(error, RateLimitError):
        return True
    if isinstance(error, APIError) and hasattr(error, 'status_code'):
        if error.status_code in (502, 503):
            return True
    return super()._is_capacity_error(error)
```

### Key Constraints
- Keep tenacity for transient errors — just reduce max attempts
- The fallback wraps the tenacity-protected call, so tenacity retries happen first, then fallback
- Preserve all tool-calling loop logic unchanged
- Import OpenAI error types inside the method to avoid import-time failures

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/gpt.py` lines 202-225 — `_chat_completion()` with tenacity
- `packages/ai-parrot/src/parrot/clients/gpt.py` lines 573-925 — `ask()` method
- `packages/ai-parrot/src/parrot/clients/base.py` — `_is_capacity_error()`, `_should_use_fallback()`

---

## Acceptance Criteria

- [ ] `OpenAIClient._fallback_model` = `'gpt-4.1-nano'`
- [ ] `_is_capacity_error()` detects `RateLimitError`, `APIError` with 502/503
- [ ] Tenacity `stop_after_attempt` reduced from 5 to 3
- [ ] `ask()` retries once with `gpt-4.1-nano` on capacity errors after tenacity exhausts
- [ ] No fallback on `AuthenticationError` or `BadRequestError`
- [ ] Response metadata includes `used_fallback_model` when triggered
- [ ] Tests pass: `pytest tests/clients/test_openai_fallback.py -v`

---

## Test Specification

```python
# tests/clients/test_openai_fallback.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestOpenAIFallback:
    def test_fallback_model_default(self):
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        assert client._fallback_model == 'gpt-4.1-nano'

    def test_is_capacity_error_rate_limit(self):
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = Exception("429 Rate limit exceeded")
        assert client._is_capacity_error(error) is True

    def test_is_capacity_error_503(self):
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = Exception("503 Service Unavailable")
        assert client._is_capacity_error(error) is True

    def test_not_capacity_error_auth(self):
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = Exception("401 Unauthorized")
        assert client._is_capacity_error(error) is False

    def test_not_capacity_error_bad_request(self):
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = Exception("400 Bad Request")
        assert client._is_capacity_error(error) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/abstractbot-ask-clientretry.spec.md`
2. **Check dependencies** — verify TASK-469 is completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/clients/gpt.py` — focus on `_chat_completion()`, `ask()`, and tenacity config
5. **Implement** `_fallback_model`, `_is_capacity_error()`, reduce tenacity attempts, add fallback in `ask()`
6. **Run tests**: `pytest tests/clients/test_openai_fallback.py -v`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 4.6
**Date**: 2026-03-28
**Notes**: Added _fallback_model='gpt-4.1-nano', overrode _is_capacity_error() for RateLimitError and APIError 502/503, reduced tenacity from 5→3 attempts, added fallback retry wrapping both responses and chat completion paths in ask(), with metadata tracking. 13 tests pass.

**Deviations from spec**: none
