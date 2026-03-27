# Feature Specification: AbstractBot Ask Client Retry with Fallback LLM

**Feature ID**: FEAT-067
**Date**: 2026-03-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Currently, `AbstractBot.conversation()`, `invoke()`, and `ask()` implement a retry mechanism that retries with the **same** LLM client when a request fails (lines 210-306, 418-439, 716-859 in `base.py`). If the LLM provider is experiencing an outage or returning persistent errors, retrying the same provider is futile.

Users need the ability to **automatically switch to a different LLM provider** on failure — e.g., if the primary client (Google Gemini) fails, fall back to Anthropic Claude without manual intervention.

### Goals
- Add a `fallback_llm` flag to `AbstractBot` that enables automatic LLM provider switching on failure
- Configure the fallback model from `DEFAULT_FALLBACK_LLM` in `parrot.conf` (format: `provider:model`, e.g. `anthropic:claude-sonnet-4-5`)
- On LLM failure in `conversation()`, `invoke()`, or `ask()`, immediately retry with the fallback LLM client instead of the same client
- Reuse existing `_resolve_llm_config()` and `_create_llm_client()` infrastructure to create the fallback client

### Non-Goals (explicitly out of scope)
- Chaining multiple fallback models (only one fallback level)
- Automatic selection of the best fallback provider
- Fallback for streaming (`ask_stream`) — can be added later
- Rate-limit-aware routing or load balancing across providers

---

## 2. Architectural Design

### Overview

Add a `fallback_llm` boolean flag and a `DEFAULT_FALLBACK_LLM` config variable. During `configure()`, if `fallback_llm=True`, create a second LLM client (`self._fbllm`) using the fallback model string. In the retry loops of `conversation()`, `invoke()`, and `ask()`, when the primary LLM fails, immediately retry the same request using `self._fbllm` instead of retrying the same client.

### Component Diagram
```
AbstractBot.__init__()
    ├── self._llm_raw (primary)
    └── self._fallback_llm = True/False

AbstractBot.configure()
    ├── self._llm = _create_llm_client(primary_config)
    └── self._fbllm = _create_llm_client(fallback_config)  [if fallback_llm=True]

ask() / invoke() / conversation()
    ├── try: primary LLM call (self._llm)
    └── except: fallback LLM call (self._fbllm)  [if fallback_llm=True]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.__init__()` | modifies | Add `fallback_llm` flag, `_fallback_llm_model` attribute |
| `AbstractBot.configure()` | modifies | Create `self._fbllm` client when fallback enabled |
| `AbstractBot.conversation()` | modifies | Catch primary failure → retry with `self._fbllm` |
| `AbstractBot.invoke()` | modifies | Catch primary failure → retry with `self._fbllm` |
| `AbstractBot.ask()` | modifies | Catch primary failure → retry with `self._fbllm` |
| `parrot/conf.py` | modifies | Add `DEFAULT_FALLBACK_LLM` config variable |
| `_resolve_llm_config()` | uses | Reuse to resolve fallback model string |
| `_create_llm_client()` | uses | Reuse to instantiate fallback client |

### Data Models
```python
# No new Pydantic models needed — uses existing LLMConfig
# New attributes on AbstractBot:
fallback_llm: bool = False          # Enable/disable fallback
_fallback_llm_model: Optional[str]  # e.g. "anthropic:claude-sonnet-4-5"
_fbllm: Optional[AbstractClient]    # Fallback LLM client instance
```

### New Public Interfaces
```python
# No new public methods — behavior is controlled via:
# 1. Constructor kwarg: fallback_llm=True
# 2. Config variable: DEFAULT_FALLBACK_LLM=anthropic:claude-sonnet-4-5
```

---

## 3. Module Breakdown

### Module 1: Configuration Variable
- **Path**: `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: Add `DEFAULT_FALLBACK_LLM` config variable with default `anthropic:claude-sonnet-4-5`
- **Depends on**: nothing

### Module 2: AbstractBot Initialization & Configuration
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**:
  - Add `fallback_llm` parameter to `__init__()` (default `False`)
  - Store `_fallback_llm_model` from `DEFAULT_FALLBACK_LLM` config when `fallback_llm=True`
  - In `configure()`: if `fallback_llm=True`, resolve and create `self._fbllm` using `_resolve_llm_config()` + `_create_llm_client()` with the fallback model string
  - Sync tools with `self._fbllm` same as with `self._llm`
- **Depends on**: Module 1

### Module 3: Fallback Retry in conversation(), invoke(), ask()
- **Path**: `packages/ai-parrot/src/parrot/bots/base.py`
- **Responsibility**:
  - In `conversation()` (line ~299-306): when the primary LLM raises an exception and `self._fbllm` is set, instead of retrying the same client, retry once with `self._fbllm`
  - In `invoke()` (line ~496-505): wrap the LLM call in a try/except, on failure retry with `self._fbllm` if available
  - In `ask()` (line ~852-859): same pattern — on primary failure, retry with `self._fbllm`
  - Log clearly which model is being used on fallback: `"Primary LLM failed, switching to fallback: {model}"`
  - Set `response.metadata['used_fallback'] = True` when fallback is used
- **Depends on**: Module 2

### Module 4: Unit Tests
- **Path**: `tests/bots/test_fallback_llm.py`
- **Responsibility**: Test fallback behavior across all three methods
- **Depends on**: Module 3

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_fallback_llm_flag_default` | Module 2 | `fallback_llm` defaults to `False`, `_fbllm` is `None` |
| `test_fallback_llm_configure` | Module 2 | When `fallback_llm=True`, `configure()` creates `self._fbllm` |
| `test_fallback_llm_different_provider` | Module 2 | `self._fbllm` uses a different provider/model than `self._llm` |
| `test_conversation_fallback_on_failure` | Module 3 | Primary fails → fallback succeeds → returns response |
| `test_invoke_fallback_on_failure` | Module 3 | Primary fails → fallback succeeds → returns response |
| `test_ask_fallback_on_failure` | Module 3 | Primary fails → fallback succeeds → returns response |
| `test_no_fallback_when_disabled` | Module 3 | `fallback_llm=False` → normal retry, no fallback |
| `test_both_fail_raises` | Module 3 | Primary fails → fallback fails → exception propagated |
| `test_fallback_metadata_flag` | Module 3 | Response includes `used_fallback=True` when fallback was used |
| `test_default_fallback_llm_config` | Module 1 | `DEFAULT_FALLBACK_LLM` reads from config with correct default |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_primary_client():
    """Primary LLM client that raises on ask()."""
    client = AsyncMock(spec=AbstractClient)
    client.ask.side_effect = Exception("Provider unavailable")
    return client

@pytest.fixture
def mock_fallback_client():
    """Fallback LLM client that succeeds."""
    client = AsyncMock(spec=AbstractClient)
    client.ask.return_value = AIMessage(content="Fallback response")
    return client
```

---

## 5. Acceptance Criteria

- [x] `DEFAULT_FALLBACK_LLM` config variable exists in `conf.py`
- [ ] `AbstractBot(fallback_llm=True)` creates a second LLM client during `configure()`
- [ ] `conversation()` switches to fallback client on primary failure
- [ ] `invoke()` switches to fallback client on primary failure
- [ ] `ask()` switches to fallback client on primary failure
- [ ] Fallback is logged with model name for observability
- [ ] When both primary and fallback fail, exception is raised normally
- [ ] `fallback_llm=False` (default) preserves existing retry behavior unchanged
- [ ] All unit tests pass
- [ ] No breaking changes to existing public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Reuse `_resolve_llm_config()` and `_create_llm_client()` — do NOT duplicate client creation logic
- Follow the existing `configure_llm()` pattern in `tools.py` for runtime LLM switching
- Use `self.logger` for all fallback logging
- The fallback retry replaces (not adds to) the same-client retry when `fallback_llm=True`

### Fallback Retry Semantics
```python
# In conversation()/ask():
# Existing behavior (fallback_llm=False):
for attempt in range(retries + 1):
    try: primary_call()
    except: if attempt < retries: continue; raise

# New behavior (fallback_llm=True, self._fbllm exists):
try:
    primary_call()
except Exception as e:
    self.logger.warning(f"Primary LLM failed: {e}. Switching to fallback.")
    fallback_call()  # single attempt with fallback
```

### Known Risks / Gotchas
- The fallback client must have tools synced the same way as primary (handled in `configure()`)
- Different providers may have different tool calling formats — `AbstractClient` already handles this via its interface
- The fallback model string format must match what `_resolve_llm_config()` expects (i.e. `provider:model`)

### External Dependencies
None — uses existing provider SDKs already installed.

---

## 7. Open Questions

- [x] Should fallback apply to `ask_stream()` too? — *Deferred to future iteration*
- [ ] Should the `retries` kwarg still apply when fallback is enabled? — *Proposed: fallback replaces retry with same client; if both should be supported, the retry loop tries primary N times, then falls back*

---

## Worktree Strategy
- **Isolation unit**: `per-spec` (sequential tasks)
- All 4 modules are tightly coupled and modify connected files
- No cross-feature dependencies

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-27 | Jesus Lara | Initial draft |
