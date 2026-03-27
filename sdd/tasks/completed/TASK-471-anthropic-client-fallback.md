# TASK-471: AnthropicClient Fallback Model

**Feature**: abstractbot-ask-clientretry
**Spec**: `sdd/specs/abstractbot-ask-clientretry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-469
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 from the spec. AnthropicClient currently has NO fallback
> logic — it relies entirely on the SDK's built-in `max_retries=2` for transient errors.
> This task adds fallback to a cheaper model (`claude-sonnet-4.5`) when persistent
> capacity errors occur (429 rate limit, 529 overloaded).

---

## Scope

- Set `_fallback_model = 'claude-sonnet-4.5'` as class attribute on `AnthropicClient`
- Override `_is_capacity_error()` to detect Anthropic-specific exception types:
  - `anthropic.RateLimitError` (HTTP 429)
  - `anthropic.OverloadedError` (HTTP 529)
  - `anthropic.APIStatusError` with `status_code in (429, 503, 529)`
- In `ask()`: wrap the main API call (`self.client.messages.create(...)`) with fallback logic:
  - On capacity error → log warning → retry **once** with `self._fallback_model` substituted
  - Set `response.metadata['used_fallback_model'] = True`, `original_model`, `fallback_model`
- Do NOT change the SDK's `max_retries=2` — that handles transient network errors
- Write tests for Anthropic fallback behavior

**NOT in scope**: Changes to `GoogleGenAIClient`, `OpenAIClient`, or `AbstractBot`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | Add `_fallback_model`, override `_is_capacity_error()`, add fallback in `ask()` |
| `tests/clients/test_anthropic_fallback.py` | CREATE | Tests for Anthropic fallback behavior |

---

## Implementation Notes

### Capacity Error Detection
```python
def _is_capacity_error(self, error: Exception) -> bool:
    """Detect Anthropic capacity errors using SDK exception types."""
    from anthropic import RateLimitError, OverloadedError, APIStatusError
    if isinstance(error, (RateLimitError, OverloadedError)):
        return True
    if isinstance(error, APIStatusError) and error.status_code in (429, 503, 529):
        return True
    # Fall back to base string matching for unknown error formats
    return super()._is_capacity_error(error)
```

### Fallback in ask()
The `ask()` method has a tool-calling loop. The fallback should wrap the **outer** API call,
not the individual tool execution retries. The pattern:

```python
# In ask(), around the messages.create() call:
try:
    result = await self.client.messages.create(
        model=model,
        messages=messages,
        system=system_prompt,
        max_tokens=max_tokens,
        ...
    )
except Exception as e:
    if self._should_use_fallback(model, e):
        self.logger.warning(
            f"Model {model} capacity error: {e}. "
            f"Retrying with fallback: {self._fallback_model}"
        )
        model = self._fallback_model  # swap model for this and subsequent tool loops
        result = await self.client.messages.create(
            model=model, messages=messages, system=system_prompt,
            max_tokens=max_tokens, ...
        )
        # Mark response metadata after building AIMessage
    else:
        raise
```

### Key Constraints
- The Anthropic SDK already retries transient errors (`max_retries=2`). If after 2 SDK retries the error persists, THEN our fallback kicks in
- Preserve all existing tool-calling loop logic unchanged
- The fallback model swap should persist for the entire multi-turn tool loop (if the first call falls back, subsequent tool-loop calls also use the fallback model)
- Import Anthropic error types inside the method to avoid import-time failures when anthropic is not installed

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/claude.py` — entire file, especially `ask()` method and `get_client()`
- `packages/ai-parrot/src/parrot/clients/base.py` — `_is_capacity_error()`, `_should_use_fallback()`

---

## Acceptance Criteria

- [ ] `AnthropicClient._fallback_model` = `'claude-sonnet-4.5'`
- [ ] `_is_capacity_error()` detects `RateLimitError`, `OverloadedError`, status 429/503/529
- [ ] `ask()` retries once with `claude-sonnet-4.5` on capacity errors
- [ ] No fallback on `BadRequestError`, `AuthenticationError`, or tool execution errors
- [ ] Response metadata includes `used_fallback_model` when fallback triggered
- [ ] SDK `max_retries=2` unchanged — transient errors still handled by SDK
- [ ] Tests pass: `pytest tests/clients/test_anthropic_fallback.py -v`

---

## Test Specification

```python
# tests/clients/test_anthropic_fallback.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestAnthropicFallback:
    def test_fallback_model_default(self):
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        assert client._fallback_model == 'claude-sonnet-4.5'

    def test_is_capacity_error_rate_limit(self):
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        # Mock a RateLimitError-like exception
        error = Exception("429 Too Many Requests")
        assert client._is_capacity_error(error) is True

    def test_is_capacity_error_overloaded(self):
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        error = Exception("529 overloaded")
        assert client._is_capacity_error(error) is True

    def test_not_capacity_error_bad_request(self):
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        error = Exception("400 Bad Request - invalid_request_error")
        assert client._is_capacity_error(error) is False

    def test_not_capacity_error_auth(self):
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        error = Exception("401 Unauthorized")
        assert client._is_capacity_error(error) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/abstractbot-ask-clientretry.spec.md`
2. **Check dependencies** — verify TASK-469 is completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** `packages/ai-parrot/src/parrot/clients/claude.py` fully — understand the `ask()` flow and tool loop
5. **Implement** `_fallback_model`, `_is_capacity_error()`, and fallback logic in `ask()`
6. **Run tests**: `pytest tests/clients/test_anthropic_fallback.py -v`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude Opus 4.6
**Date**: 2026-03-27
**Notes**: Added `_fallback_model = 'claude-sonnet-4.5'` class attribute, overrode `_is_capacity_error()` for Anthropic SDK error types (RateLimitError, APIStatusError with 429/503/529), and wrapped `messages.create()` in `ask()` with fallback logic. Response metadata includes `used_fallback_model`, `original_model`, and `fallback_model` when fallback triggers. 16 tests pass.

**Deviations from spec**: Removed `OverloadedError` — not available in anthropic SDK v0.61.0. The 529 overloaded case is handled via `APIStatusError` with `status_code == 529` instead.
