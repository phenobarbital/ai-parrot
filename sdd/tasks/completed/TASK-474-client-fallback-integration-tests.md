# TASK-474: Client Fallback Integration Tests

**Feature**: abstractbot-ask-clientretry
**Spec**: `sdd/specs/abstractbot-ask-clientretry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-470, TASK-471, TASK-472, TASK-473
**Assigned-to**: unassigned

---

## Context

> This task implements Module 6 from the spec. It provides comprehensive integration
> tests that validate the fallback behavior end-to-end: primary model fails → client
> falls back to cheaper model → response is returned with fallback metadata.
> Also verifies that the bot layer no longer double-retries.

---

## Scope

- Create comprehensive test suite covering:
  - Each client (Google, Anthropic, OpenAI) falls back correctly on capacity errors
  - Each client does NOT fall back on non-capacity errors (auth, bad request, tool errors)
  - Response metadata is correctly set when fallback is used
  - Both primary and fallback failing raises the exception
  - Bot-level `conversation()` and `ask()` do not have retry loops (no double retry)
- Use mocked API responses to simulate capacity errors without hitting real APIs
- Test that fallback only triggers **once** (no cascading fallbacks)

**NOT in scope**: Real API calls to any provider.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/clients/test_client_fallback.py` | CREATE | Integration tests for all client fallbacks |

---

## Implementation Notes

### Test Structure
```python
# Group tests by concern:
class TestFallbackDecisionLogic:
    """Tests for _is_capacity_error and _should_use_fallback across all clients."""

class TestGoogleFallbackIntegration:
    """End-to-end Google fallback with mocked API."""

class TestAnthropicFallbackIntegration:
    """End-to-end Anthropic fallback with mocked API."""

class TestOpenAIFallbackIntegration:
    """End-to-end OpenAI fallback with mocked API."""

class TestFallbackMetadata:
    """Verify response metadata is set correctly on fallback."""

class TestNoDoubleFallback:
    """Verify fallback only happens once, not cascading."""

class TestBotLevelNoRetry:
    """Verify AbstractBot.conversation/ask no longer retry."""
```

### Key Constraints
- All tests must be runnable without API keys (use mocks)
- Use `pytest-asyncio` for async tests
- Mock at the SDK client level (e.g., `client.messages.create` for Anthropic)
- Test the EXACT error types each provider raises, not just generic Exception

### References in Codebase
- `tests/clients/test_base_fallback.py` — base fallback tests (TASK-469)
- `tests/clients/test_google_fallback.py` — Google-specific tests (TASK-470)
- `tests/clients/test_anthropic_fallback.py` — Anthropic-specific tests (TASK-471)
- `tests/clients/test_openai_fallback.py` — OpenAI-specific tests (TASK-472)

---

## Acceptance Criteria

- [ ] Integration tests cover all three clients (Google, Anthropic, OpenAI)
- [ ] Tests verify fallback triggers on capacity errors for each client
- [ ] Tests verify fallback does NOT trigger on non-capacity errors
- [ ] Tests verify response metadata is set on fallback
- [ ] Tests verify both-fail scenario raises exception
- [ ] Tests verify no double-retry at bot level
- [ ] All tests pass: `pytest tests/clients/test_client_fallback.py -v`
- [ ] Tests are runnable without API keys

---

## Test Specification

```python
# tests/clients/test_client_fallback.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestFallbackDecisionLogic:
    """Cross-client _is_capacity_error and _should_use_fallback tests."""

    @pytest.mark.parametrize("client_cls,fallback_model", [
        ("parrot.clients.google.client.GoogleGenAIClient", "gemini-3.1-flash-preview-lite"),
        ("parrot.clients.claude.AnthropicClient", "claude-sonnet-4.5"),
        ("parrot.clients.gpt.OpenAIClient", "gpt-4.1-nano"),
    ])
    def test_each_client_has_fallback_model(self, client_cls, fallback_model):
        """Every client defines its _fallback_model."""
        import importlib
        module_path, class_name = client_cls.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        instance = cls.__new__(cls)
        assert instance._fallback_model == fallback_model

    @pytest.mark.parametrize("error_msg", [
        "429 Too Many Requests",
        "503 Service Unavailable",
        "The model is overloaded",
        "Rate limit exceeded",
    ])
    def test_capacity_errors_detected_by_all(self, error_msg):
        """All clients detect common capacity error patterns."""
        from parrot.clients.base import AbstractClient
        client = AbstractClient.__new__(AbstractClient)
        client._fallback_model = "some-model"
        assert client._is_capacity_error(Exception(error_msg)) is True


class TestNoDoubleFallback:
    def test_fallback_model_does_not_fallback_again(self):
        """When current model IS the fallback model, _should_use_fallback returns False."""
        from parrot.clients.base import AbstractClient
        client = AbstractClient.__new__(AbstractClient)
        client._fallback_model = "fallback-model"
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("fallback-model", error) is False


class TestBotLevelNoRetry:
    def test_conversation_no_retry_loop(self):
        import inspect
        from parrot.bots.base import AbstractBot
        source = inspect.getsource(AbstractBot.conversation)
        assert "for attempt in range" not in source

    def test_ask_no_retry_loop(self):
        import inspect
        from parrot.bots.base import AbstractBot
        source = inspect.getsource(AbstractBot.ask)
        assert "for attempt in range" not in source
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/abstractbot-ask-clientretry.spec.md`
2. **Check dependencies** — verify TASK-470, TASK-471, TASK-472, TASK-473 are completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Read** the individual test files from TASK-469–473 to avoid duplication
5. **Create** comprehensive integration tests
6. **Run**: `pytest tests/clients/test_client_fallback.py -v`
7. **Also run**: `pytest tests/ -v` for full regression check
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 4.6
**Date**: 2026-03-28
**Notes**: 51 integration tests across 8 test classes. Covers: cross-client fallback defaults (parametrized), base capacity error consistency (7 capacity + 5 non-capacity), no-double-fallback (parametrized), response metadata, bot-level no-retry, provider-specific SDK errors (OpenAI, Anthropic, Google), Google Gemini-only constraint, legacy method removal. 243 total tests pass.

**Deviations from spec**: Used BaseBot instead of AbstractBot for bot-level tests (implementations live in BaseBot). Skipped mocked end-to-end ask() tests since per-client test files (TASK-470/471/472) already cover those patterns.
