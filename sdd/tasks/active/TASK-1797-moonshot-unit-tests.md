# TASK-1797: Unit Tests for MoonshotClient

**Feature**: FEAT-311 — Moonshot Client (MoonshotClient)
**Spec**: `sdd/specs/moonshot-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1794, TASK-1795, TASK-1796
**Assigned-to**: unassigned

---

## Context

Comprehensive unit tests for the MoonshotClient covering parameter stripping,
thinking mode injection, factory creation, model defaults, and capacity error
detection.

Implements spec §4 (Test Specification) and §3 Module 4.

---

## Scope

- Create test file with all test cases from spec §4
- Test parameter stripping for K-series vs legacy models
- Test thinking mode injection for K3, K2.6, K2.7-code
- Test max_tokens → max_completion_tokens translation
- Test prompt_cache_key injection
- Test factory creation via "moonshot" and "kimi" keys
- Test model enum values
- Test client class attributes (client_type, client_name, defaults)

**NOT in scope**: Integration tests with live Moonshot API, streaming tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/clients/test_moonshot_client.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.clients.moonshot import MoonshotClient             # TASK-1795 creates this
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS  # verified: factory.py:103, 64
from parrot.models.moonshot import (                            # TASK-1794 creates this
    MoonshotModel, K_SERIES_MODELS, ALWAYS_THINKING_MODELS,
    REASONING_EFFORT_MODELS, THINKING_DICT_MODELS,
)
```

### Existing Signatures to Use

```python
# tests/clients/test_openai_fallback.py:6-11 (TEST PATTERN)
def _make_openai_client(**attrs):
    """Create a minimal OpenAIClient instance for testing."""
    client = OpenAIClient.__new__(OpenAIClient)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client

# packages/ai-parrot/src/parrot/clients/factory.py:134
class LLMFactory:
    @staticmethod
    def create(llm: str, model_args=None,
               tool_manager=None, **kwargs) -> AbstractClient:  # line 134

# packages/ai-parrot/src/parrot/clients/gpt.py:79
class OpenAIClient(AbstractClient):
    _fallback_model: str = "gpt-5-nano"                        # line 86
    def _is_capacity_error(self, error) -> bool:               # inherited from AbstractClient
```

### Does NOT Exist

- ~~`MoonshotClient._is_capacity_error()`~~ — inherited from AbstractClient, not overridden
- ~~`MoonshotClient.get_client()`~~ — inherited from OpenAIClient, not overridden
- ~~`tests/clients/test_moonshot_client.py`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow

```python
# tests/clients/test_openai_fallback.py
# Use __new__ pattern to create minimal client instances

def _make_moonshot_client(**attrs):
    """Create a minimal MoonshotClient instance for testing."""
    client = MoonshotClient.__new__(MoonshotClient)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client
```

### Test Cases (from spec §4)

```python
class TestMoonshotClientAttributes:
    def test_client_type_and_name(self): ...
    def test_default_model(self): ...
    def test_fallback_model(self): ...

class TestMoonshotParameterSanitization:
    def test_sanitize_strips_temperature_for_k_series(self): ...
    def test_sanitize_strips_top_p_for_k_series(self): ...
    def test_sanitize_strips_penalties_for_k_series(self): ...
    def test_sanitize_preserves_params_for_legacy_models(self): ...

class TestMoonshotMaxTokensTranslation:
    def test_max_tokens_translated_to_max_completion_tokens(self): ...

class TestMoonshotThinkingMode:
    def test_thinking_k3_reasoning_effort(self): ...
    def test_thinking_k26_thinking_dict(self): ...
    def test_thinking_k27_always_on(self): ...

class TestMoonshotPromptCacheKey:
    def test_prompt_cache_key_injected(self): ...

class TestMoonshotFactoryRegistration:
    def test_factory_create_moonshot(self): ...
    def test_factory_create_kimi(self): ...

class TestMoonshotModelEnum:
    def test_model_enum_values(self): ...
    def test_k_series_models_frozenset(self): ...
    def test_always_thinking_models_frozenset(self): ...
```

### Key Constraints

- Tests must NOT require a live API key — use `__new__` pattern
- For `_sanitize_params_for_model` tests, call the static method directly
- For thinking mode tests, verify the contextvars mechanism by checking
  that `_chat_completion` receives the correct `extra_body`
- For factory tests, verify the returned instance type (no API calls)
- Use `pytest` (not `unittest`)

### References in Codebase

- `tests/clients/test_openai_fallback.py` — `__new__` test pattern
- `tests/clients/test_client_fallback.py` — comprehensive client test patterns

---

## Acceptance Criteria

- [ ] All 15+ test cases from spec §4 implemented
- [ ] All tests pass: `pytest tests/clients/test_moonshot_client.py -v`
- [ ] Parameter stripping tested for all K-series models
- [ ] Parameter preservation tested for legacy models
- [ ] Thinking mode tested for all 3 variants
- [ ] Factory creation tested for both "moonshot" and "kimi" keys
- [ ] No linting errors: `ruff check tests/clients/test_moonshot_client.py`

---

## Test Specification

This task IS the test specification. See the test cases listed above.

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — verify TASK-1794, TASK-1795, TASK-1796 are completed
2. **Read the test pattern** in `tests/clients/test_openai_fallback.py`
3. **Read the MoonshotClient** to understand exact method signatures
4. **Implement** all test cases
5. **Run** `pytest tests/clients/test_moonshot_client.py -v` to verify
6. **Move this file** to `sdd/tasks/completed/TASK-1797-moonshot-unit-tests.md`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
