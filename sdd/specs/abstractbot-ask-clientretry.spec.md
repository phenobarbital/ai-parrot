# Feature Specification: LLM Client-Level Fallback Model on Error

**Feature ID**: FEAT-067
**Date**: 2026-03-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

There is a **double-retry problem** in the current architecture. LLM clients already have their own retry mechanisms (GoogleGenAIClient: explicit while-loop with `max_retries`, AnthropicClient: SDK `max_retries=2`, OpenAIClient: tenacity with `stop_after_attempt(5)`). On top of that, `AbstractBot.conversation()` and `ask()` have their own retry loops via the `retries` kwarg. When a model fails (e.g., timeout), instead of 2 retries we end up with **4 retries** (2 at client × 2 at bot level) — all hitting the same overloaded/unavailable model.

The correct approach is: when the primary model fails due to capacity issues (429, 503, busy, unavailable), retry **once** with a **lower/cheaper fallback model from the same provider** at the client level. This avoids provider-switching complexity and leverages each SDK's native error types.

GoogleGenAIClient already has `_high_demand_fallback_model` and `_is_high_demand_error()` — this pattern must be standardized across all clients.

### Goals
- Add a `_fallback_model` attribute to each LLM client with a provider-appropriate default
- In each client's `ask()` method: on capacity/availability errors (429, 503, busy, rate limit, unavailable), retry **once** with `_fallback_model`
- Rename Google's existing `_high_demand_fallback_model` → `_fallback_model` for consistency
- Only trigger fallback on capacity-related errors — NOT on auth errors, bad requests, or tool execution failures
- Remove the redundant retry loops from `AbstractBot.conversation()` and `ask()` in `base.py`

### Non-Goals (explicitly out of scope)
- Cross-provider fallback (switching from Google to Anthropic) — different feature
- Chaining multiple fallback levels
- Fallback for streaming endpoints
- Custom user-configurable fallback models per bot instance (can be added later)

---

## 2. Architectural Design

### Overview

Standardize the fallback model pattern at the `AbstractClient` level. Each concrete client defines its own `_fallback_model` (a cheaper/smaller model from the same provider). When `ask()` catches a capacity error, it retries **once** with `_fallback_model` substituted for the primary model. The response includes metadata indicating fallback was used.

### Component Diagram
```
AbstractClient (base)
    └── _fallback_model: Optional[str]  (defined per-subclass)
    └── _is_capacity_error(e) -> bool   (common interface)

GoogleGenAIClient.ask()          AnthropicClient.ask()          OpenAIClient.ask()
    ├── try: primary model           ├── try: primary model          ├── try: primary model
    └── except capacity_error:       └── except capacity_error:      └── except capacity_error:
        retry with _fallback_model       retry with _fallback_model      retry with _fallback_model

AbstractBot.conversation() / ask()
    └── REMOVE redundant retry loop (retries kwarg)
```

### Default Fallback Models

| Client | Primary (example) | `_fallback_model` default | Capacity Error Types |
|---|---|---|---|
| `GoogleGenAIClient` | `gemini-2.5-pro` | `gemini-3.1-flash-preview-lite` | 503, "unavailable", "high demand", "overloaded" |
| `AnthropicClient` | `claude-sonnet-4-5` | `claude-sonnet-4.5` | `RateLimitError`, `OverloadedError`, `APIStatusError` with 429/503 |
| `OpenAIClient` | `gpt-4.1` | `gpt-4.1-nano` | `RateLimitError` (429), `APIError` with 503/502 |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/clients/base.py` | modifies | Add `_fallback_model` attribute + `_is_capacity_error()` to base class |
| `parrot/clients/google/client.py` | modifies | Rename `_high_demand_fallback_model` → `_fallback_model`, update default, standardize retry |
| `parrot/clients/claude.py` | modifies | Add `_fallback_model`, add fallback retry in `ask()` |
| `parrot/clients/gpt.py` | modifies | Add `_fallback_model`, add fallback retry in `ask()` |
| `parrot/bots/base.py` | modifies | Remove redundant `retries` retry loops from `conversation()` and `ask()` |

### Data Models
```python
# New attribute on AbstractClient (base.py):
_fallback_model: Optional[str] = None  # Subclasses set their default

# No new Pydantic models needed
```

### New Public Interfaces
```python
# No new public methods — behavior is automatic and internal to ask()
# Response metadata includes:
response.metadata['used_fallback_model'] = True  # when fallback was triggered
response.metadata['original_model'] = 'gemini-2.5-pro'
response.metadata['fallback_model'] = 'gemini-3.1-flash-preview-lite'
```

---

## 3. Module Breakdown

### Module 1: Base Client Fallback Interface
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**:
  - Add `_fallback_model: Optional[str] = None` attribute to `AbstractClient`
  - Add `_is_capacity_error(self, error: Exception) -> bool` method (default implementation checks for common patterns: 429, 503, "rate limit", "unavailable", "overloaded", "high demand")
  - Add `_should_use_fallback(self, model: str, error: Exception) -> bool` helper: returns `True` if `_fallback_model` is set AND model != `_fallback_model` AND `_is_capacity_error(error)`
- **Depends on**: nothing

### Module 2: GoogleGenAIClient Fallback Standardization
- **Path**: `packages/ai-parrot/src/parrot/clients/google/client.py`
- **Responsibility**:
  - Rename `_high_demand_fallback_model` → `_fallback_model` (update default to `gemini-3.1-flash-preview-lite`)
  - Rename `_is_high_demand_error()` → override `_is_capacity_error()` (keep existing markers: 503, unavailable, high demand, overloaded)
  - Remove `_resolve_high_demand_fallback_model()` — replace with base class `_should_use_fallback()`
  - In `ask()` retry loop: use the standardized `_should_use_fallback()` pattern — on capacity error, set `current_model = self._fallback_model` and retry **once only**
- **Depends on**: Module 1

### Module 3: AnthropicClient Fallback
- **Path**: `packages/ai-parrot/src/parrot/clients/claude.py`
- **Responsibility**:
  - Set `_fallback_model = 'claude-sonnet-4.5'`
  - Override `_is_capacity_error()` to detect Anthropic-specific errors: `RateLimitError`, `OverloadedError`, `APIStatusError` with status 429 or 503
  - In `ask()`: wrap the primary API call. On capacity error, log warning and retry **once** with `_fallback_model` substituted in the `model` parameter
  - Note: The SDK's built-in `max_retries=2` handles transient network errors — the fallback is for persistent capacity issues where the same model won't recover
- **Depends on**: Module 1

### Module 4: OpenAIClient Fallback
- **Path**: `packages/ai-parrot/src/parrot/clients/gpt.py`
- **Responsibility**:
  - Set `_fallback_model = 'gpt-4.1-nano'`
  - Override `_is_capacity_error()` to detect: `RateLimitError` (429), `APIError` with status 502/503
  - In `ask()` or `_chat_completion()`: on capacity error after tenacity exhausts retries, catch and retry **once** with `_fallback_model`
  - Consider reducing tenacity `stop_after_attempt` from 5 to 2-3 to avoid excessive retries before fallback
- **Depends on**: Module 1

### Module 5: Remove Redundant Bot-Level Retry Loops
- **Path**: `packages/ai-parrot/src/parrot/bots/base.py`
- **Responsibility**:
  - In `conversation()` (lines 210-306): remove the `for attempt in range(retries + 1)` loop — the client handles retries internally now
  - In `ask()` (lines 714-859): remove the `for attempt in range(retries + 1)` loop — same reason
  - Keep the outer `try/except` for error logging and status updates
  - The `retries` kwarg can be kept but **ignored** (deprecated) or removed
- **Depends on**: Modules 2, 3, 4

### Module 6: Unit Tests
- **Path**: `tests/clients/test_client_fallback.py`
- **Responsibility**: Test fallback behavior for each client
- **Depends on**: Modules 2, 3, 4, 5

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_base_is_capacity_error_429` | Module 1 | Base `_is_capacity_error` detects 429 patterns |
| `test_base_is_capacity_error_503` | Module 1 | Base `_is_capacity_error` detects 503/unavailable |
| `test_should_use_fallback_true` | Module 1 | Returns True when fallback set + capacity error + different model |
| `test_should_use_fallback_same_model` | Module 1 | Returns False when current model == fallback model |
| `test_google_fallback_model_renamed` | Module 2 | `_fallback_model` exists, `_high_demand_fallback_model` removed |
| `test_google_ask_fallback_on_503` | Module 2 | Primary model 503 → retries once with `gemini-3.1-flash-preview-lite` |
| `test_google_no_fallback_on_auth_error` | Module 2 | Auth error → no fallback, raises immediately |
| `test_anthropic_fallback_on_overloaded` | Module 3 | `OverloadedError` → retries with `claude-sonnet-4.5` |
| `test_anthropic_fallback_on_rate_limit` | Module 3 | `RateLimitError` → retries with fallback |
| `test_anthropic_no_fallback_on_bad_request` | Module 3 | `BadRequestError` → no fallback |
| `test_openai_fallback_on_rate_limit` | Module 4 | `RateLimitError` → retries with `gpt-4.1-nano` |
| `test_openai_no_fallback_on_auth` | Module 4 | `AuthenticationError` → no fallback |
| `test_fallback_response_metadata` | Module 3/4 | Response includes `used_fallback_model`, `original_model`, `fallback_model` |
| `test_both_models_fail_raises` | Module 3/4 | Primary fails + fallback fails → exception propagated |
| `test_bot_no_double_retry` | Module 5 | Verify `conversation()`/`ask()` no longer have retry loops |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_anthropic_overloaded():
    """Simulate Anthropic OverloadedError."""
    from anthropic import OverloadedError
    return OverloadedError("The model is currently overloaded")

@pytest.fixture
def mock_rate_limit_429():
    """Simulate a 429 rate limit error."""
    return Exception("Error code: 429 - Rate limit exceeded")
```

---

## 5. Acceptance Criteria

- [ ] `AbstractClient` has `_fallback_model` attribute and `_is_capacity_error()` method
- [ ] `GoogleGenAIClient._fallback_model` = `gemini-3.1-flash-preview-lite` (renamed from `_high_demand_fallback_model`)
- [ ] `AnthropicClient._fallback_model` = `claude-sonnet-4.5`
- [ ] `OpenAIClient._fallback_model` = `gpt-4.1-nano`
- [ ] Each client's `ask()` retries **once** with fallback model on capacity errors only
- [ ] Fallback does NOT trigger on auth errors, bad requests, or tool failures
- [ ] Response metadata includes fallback usage info when fallback was used
- [ ] `AbstractBot.conversation()` and `ask()` no longer have redundant retry loops
- [ ] No double-retry behavior (client retry × bot retry)
- [ ] All unit tests pass
- [ ] No breaking changes to existing public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Follow Google's existing `_is_high_demand_error()` pattern — it's battle-tested
- Use `self.logger` for all fallback logging
- Keep fallback logic minimal: swap model name, retry once, done
- Set response metadata so callers can detect fallback usage

### Fallback Retry Semantics (per client)
```python
# Inside each client's ask() method:
try:
    response = await self._make_api_call(model=model, ...)
except Exception as e:
    if self._should_use_fallback(model, e):
        self.logger.warning(
            f"Model {model} capacity error: {e}. "
            f"Retrying once with fallback model: {self._fallback_model}"
        )
        response = await self._make_api_call(model=self._fallback_model, ...)
        response.metadata['used_fallback_model'] = True
        response.metadata['original_model'] = model
        response.metadata['fallback_model'] = self._fallback_model
    else:
        raise
```

### Capacity Error Detection per Provider
```python
# Google (existing patterns, proven in production):
# 503, "unavailable", "high demand", "model is overloaded", "please try again later"

# Anthropic (SDK exception types):
# anthropic.RateLimitError (429)
# anthropic.OverloadedError (529)
# anthropic.APIStatusError with status_code in (429, 503, 529)

# OpenAI (SDK exception types):
# openai.RateLimitError (429)
# openai.APIError with status_code in (502, 503)
```

### Known Risks / Gotchas
- The fallback model must be from the **same provider** — cross-provider fallback is a separate feature
- If the fallback model itself is overloaded, the error propagates normally (no cascade)
- Google's existing retry loop already has fallback logic — refactor carefully to avoid regression
- AnthropicClient relies on SDK-level retries (`max_retries=2`) for transient errors; the fallback is for **persistent** capacity issues where the model itself is unavailable
- OpenAI's tenacity retries should be reduced (5 → 2-3) before adding fallback to avoid slow failure cascades

### External Dependencies
None — uses existing provider SDKs already installed.

---

## 7. Open Questions

- [ ] Should fallback apply to streaming endpoints (`ask_stream`)? — *Deferred*: No on this version.
- [ ] Should `_fallback_model` be configurable per-bot-instance via kwargs? — *Can be added later*: yes, via kwargs or default per client.
- [ ] Should the `retries` kwarg in `AbstractBot` be formally deprecated or silently ignored? — *Proposed: remove it*: remove it.

---

## Worktree Strategy
- **Isolation unit**: `per-spec` (sequential tasks)
- Modules 2, 3, 4 can be parallelized (independent clients) but share Module 1 as dependency
- Module 5 depends on all client modules being done
- No cross-feature dependencies

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-27 | Jesus Lara | Initial draft — AbstractBot-level fallback |
| 0.2 | 2026-03-27 | Jesus Lara | Rewrite: moved fallback to client level, per-provider fallback models, removed double-retry |
