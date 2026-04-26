# TASK-856: AnthropicClient Regression Validation Against SDK 0.97.0

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-855
**Assigned-to**: unassigned

---

## Context

> Spec Module 2. After bumping the `anthropic` pin (TASK-855), we must validate
> that `AnthropicClient` suffers no regressions. The 36-version gap carries risk
> of hidden API drift. This task creates a dedicated regression test file and
> re-runs existing tests to confirm zero breakage.

---

## Scope

- Create `tests/clients/test_anthropic_sdk_097.py` with tests that verify:
  1. `from anthropic import RateLimitError, APIStatusError, AsyncAnthropic` imports
  2. `from anthropic.types import Message, MessageStreamEvent` imports
  3. `betas` parameter for 1M context is still accepted (mocked `messages.create`)
  4. `_is_capacity_error` returns `True` for `RateLimitError` and `APIStatusError(status_code=529)`
- Run existing `tests/clients/test_anthropic_fallback.py` and `tests/unit/test_anthropic_invoke.py` — they must pass unchanged.
- Add an optional live smoke test `test_anthropic_live_smoke` marked `@pytest.mark.live`.

**NOT in scope**: changes to `parrot/clients/claude.py`, new client code, pyproject changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/clients/test_anthropic_sdk_097.py` | CREATE | Regression test suite for SDK 0.97.0 compatibility |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from parrot.clients.claude import AnthropicClient         # claude.py:40
from anthropic import AsyncAnthropic, RateLimitError, APIStatusError  # claude.py:17,75
from anthropic.types import Message, MessageStreamEvent   # claude.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient):                     # line 40
    version: str = "2023-06-01"                            # line 42
    client_type: str = "anthropic"                         # line 43
    client_name: str = "claude"                            # line 44
    _default_model: str = 'claude-sonnet-4-5'              # line 46
    _fallback_model: str = 'claude-sonnet-4.5'             # line 47
    _lightweight_model: str = "claude-haiku-4-5-20251001"  # line 48

    def __init__(self, api_key=None, base_url="https://api.anthropic.com",
                 **kwargs): ...                            # line 50
    async def get_client(self) -> AsyncAnthropic: ...      # line 66
    def _is_capacity_error(self, error) -> bool: ...       # line 73
    async def ask(self, prompt, …, context_1m=False) -> AIMessage: ...
                                                           # line 82
```

### Does NOT Exist
- ~~`anthropic.AsyncAnthropic.responses`~~ — no `responses` namespace
- ~~`from anthropic.types import StreamEvent`~~ — actual type is `MessageStreamEvent`
- ~~`AnthropicClient.complete_async`~~ — does not exist; base method is at `base.py:627`

---

## Implementation Notes

### Pattern to Follow
```python
# tests/clients/test_anthropic_fallback.py — existing test pattern
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.clients.claude import AnthropicClient
```

### Key Constraints
- Use `pytest` and `pytest-asyncio` for async tests
- Mock `messages.create` to test betas passthrough — do NOT call real API in unit tests
- The live smoke test must be `@pytest.mark.live` and skip without `ANTHROPIC_API_KEY`
- Do NOT modify `claude.py` — if tests fail, report it as a finding

### References in Codebase
- `tests/clients/test_anthropic_fallback.py` — existing test patterns
- `tests/unit/test_anthropic_invoke.py` — existing invoke tests
- `packages/ai-parrot/src/parrot/clients/claude.py:73-80` — `_is_capacity_error` implementation

---

## Acceptance Criteria

- [ ] `tests/clients/test_anthropic_sdk_097.py` exists with all specified tests
- [ ] `test_anthropic_imports_097` passes — verifies SDK imports
- [ ] `test_anthropic_betas_param_passthrough` passes — mocked `messages.create` receives `betas`
- [ ] `test_anthropic_capacity_error_detection` passes — `_is_capacity_error` returns correct results
- [ ] Existing `tests/clients/test_anthropic_fallback.py` passes unchanged
- [ ] Existing `tests/unit/test_anthropic_invoke.py` passes unchanged
- [ ] `pytest tests/clients/test_anthropic_sdk_097.py -v` passes

---

## Test Specification

```python
# tests/clients/test_anthropic_sdk_097.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_anthropic_imports_097():
    """Verify critical SDK imports survive the 0.61→0.97 upgrade."""
    from anthropic import RateLimitError, APIStatusError, AsyncAnthropic
    from anthropic.types import Message, MessageStreamEvent
    assert all([RateLimitError, APIStatusError, AsyncAnthropic,
                Message, MessageStreamEvent])


@pytest.mark.asyncio
async def test_anthropic_betas_param_passthrough():
    """Mocked messages.create receives betas when context_1m=True."""
    from parrot.clients.claude import AnthropicClient
    # Mock the client and verify betas parameter is forwarded


def test_anthropic_capacity_error_detection():
    """_is_capacity_error returns True for RateLimitError and 529."""
    from anthropic import RateLimitError, APIStatusError
    from parrot.clients.claude import AnthropicClient
    client = AnthropicClient(api_key="test-key")
    assert client._is_capacity_error(RateLimitError.__new__(RateLimitError)) is True


@pytest.mark.live
@pytest.mark.asyncio
async def test_anthropic_live_smoke():
    """Live smoke test. Skipped without ANTHROPIC_API_KEY."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("No ANTHROPIC_API_KEY")
    from parrot.clients.claude import AnthropicClient
    client = AnthropicClient()
    result = await client.ask("ping")
    assert result.output
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and signatures are current
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** the test file
6. **Run** `pytest tests/clients/test_anthropic_sdk_097.py tests/clients/test_anthropic_fallback.py tests/unit/test_anthropic_invoke.py -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-856-anthropic-regression-validation.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
