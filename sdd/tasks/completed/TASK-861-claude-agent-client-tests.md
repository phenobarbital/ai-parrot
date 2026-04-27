# TASK-861: Unit Tests for ClaudeAgentClient

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-857, TASK-858, TASK-859
**Assigned-to**: unassigned

---

## Context

> Spec Module 7. Comprehensive unit tests for `ClaudeAgentClient`, the
> `AIMessageFactory.from_claude_agent` factory method, and the `LLMFactory`
> registration. All tests mock `claude_agent_sdk` — no live CLI needed.

---

## Scope

- Create `tests/clients/test_claude_agent.py` with the following tests:
  1. `test_claude_agent_init_lazy_import` — construction does not import `claude_agent_sdk`
  2. `test_claude_agent_ask_assembles_text` — mocked `query()` yields messages → `AIMessage`
  3. `test_claude_agent_ask_stream_yields_text` — `ask_stream` yields text blocks in order
  4. `test_claude_agent_tool_use_recorded` — `ToolUseBlock` produces `ToolCall`
  5. `test_claude_agent_batch_ask_not_implemented` — raises `NotImplementedError`
  6. `test_factory_registers_claude_agent` — `LLMFactory.create("claude-agent")` works
  7. `test_factory_claude_agent_missing_extra_message` — clear `ImportError` hint
- Add a `fake_claude_agent_messages` fixture in `tests/clients/conftest.py`.
- Add a live integration test `test_claude_agent_live_smoke` marked `@pytest.mark.live`.

**NOT in scope**: implementation code (already done by TASK-857/858/859).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/clients/test_claude_agent.py` | CREATE | Full unit test suite |
| `tests/clients/conftest.py` | CREATE or MODIFY | Add `fake_claude_agent_messages` fixture |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from parrot.clients.claude_agent import ClaudeAgentClient, ClaudeAgentRunOptions  # TASK-858
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS                  # factory.py:19,38
from parrot.models.responses import AIMessage, AIMessageFactory                   # responses.py:72,383
from parrot.models.basic import ToolCall                                          # basic.py:17

# claude-agent-sdk types — for building mocks
from claude_agent_sdk.types import (
    AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude_agent.py (TASK-858 creates)
class ClaudeAgentClient(AbstractClient):
    client_type: str = "claude_agent"
    client_name: str = "claude-agent"
    _default_model: str = "claude-sonnet-4-6"
    async def ask(self, prompt, *, run_options=None, **kwargs) -> AIMessage: ...
    async def ask_stream(self, prompt, *, run_options=None, **kwargs) -> AsyncIterator[str]: ...
    async def batch_ask(self, requests, **kwargs): ...  # raises NotImplementedError
    async def invoke(self, prompt, *, output_type=None, **kwargs) -> InvokeResult: ...
    async def resume(self, session_id, user_input, state) -> AIMessage: ...

# packages/ai-parrot/src/parrot/clients/factory.py (TASK-859 modifies)
SUPPORTED_CLIENTS["claude-agent"]  # → _lazy_claude_agent
SUPPORTED_CLIENTS["claude-code"]   # → _lazy_claude_agent
LLMFactory.create("claude-agent:claude-sonnet-4-6")  # → ClaudeAgentClient instance
```

### Does NOT Exist
- ~~`ClaudeAgentClient.complete_async`~~ — method is `ask`
- ~~`claude_agent_sdk.ClaudeClient`~~ — class is `ClaudeSDKClient`

---

## Implementation Notes

### Pattern to Follow
```python
# tests/clients/test_anthropic_fallback.py — existing test pattern
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def fake_claude_agent_messages():
    """Mimics the message stream that claude_agent_sdk.query() yields."""
    # Build mock AssistantMessage, TextBlock, ToolUseBlock, ResultMessage
    ...
```

### Key Constraints
- All tests mock `claude_agent_sdk` — do NOT require the CLI to be installed
- Use `monkeypatch` to simulate missing `claude_agent_sdk` for the import error test
- Use `pytest-asyncio` for async tests
- The `fake_claude_agent_messages` fixture should go in `tests/clients/conftest.py`
- Live test must be `@pytest.mark.live` and skip if `claude` binary unavailable

### References in Codebase
- `tests/clients/test_anthropic_fallback.py` — test pattern reference
- `tests/unit/test_anthropic_invoke.py` — async test patterns

---

## Acceptance Criteria

- [ ] `tests/clients/test_claude_agent.py` exists with all 7+ tests
- [ ] `tests/clients/conftest.py` has `fake_claude_agent_messages` fixture
- [ ] `test_claude_agent_init_lazy_import` passes
- [ ] `test_claude_agent_ask_assembles_text` passes — verifies `output == "hello world"`
- [ ] `test_claude_agent_ask_stream_yields_text` passes — yields `"hello"`, `" world"`
- [ ] `test_claude_agent_tool_use_recorded` passes — `ToolCall` has correct fields
- [ ] `test_claude_agent_batch_ask_not_implemented` passes — `NotImplementedError` with `AnthropicClient` mention
- [ ] `test_factory_registers_claude_agent` passes — creates `ClaudeAgentClient` instance
- [ ] `test_factory_claude_agent_missing_extra_message` passes — `ImportError` with hint
- [ ] `pytest tests/clients/test_claude_agent.py -v` — all pass

---

## Test Specification

```python
# tests/clients/test_claude_agent.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_claude_agent_init_lazy_import():
    """ClaudeAgentClient() does not import claude_agent_sdk at construction time."""
    import sys
    # Temporarily remove claude_agent_sdk from sys.modules if present
    # Instantiate ClaudeAgentClient
    # Verify claude_agent_sdk not in sys.modules


@pytest.mark.asyncio
async def test_claude_agent_ask_assembles_text(fake_claude_agent_messages):
    """Mocked query() yielding messages produces AIMessage with correct output."""
    # Mock query() to return fake_claude_agent_messages
    # Call client.ask("test prompt")
    # Assert result.output == "hello world"


@pytest.mark.asyncio
async def test_claude_agent_ask_stream_yields_text():
    """ask_stream yields text blocks in order."""
    # Mock streaming to yield TextBlock text
    # Collect yielded strings
    # Assert ["hello ", "world"]


@pytest.mark.asyncio
async def test_claude_agent_tool_use_recorded():
    """ToolUseBlock(name='Bash', input={'cmd':'ls'}, id='t1') → ToolCall."""
    # Verify ToolCall in result.tool_calls


@pytest.mark.asyncio
async def test_claude_agent_batch_ask_not_implemented():
    """batch_ask raises NotImplementedError mentioning AnthropicClient."""
    from parrot.clients.claude_agent import ClaudeAgentClient
    client = ClaudeAgentClient()
    with pytest.raises(NotImplementedError, match="AnthropicClient"):
        await client.batch_ask([])


def test_factory_registers_claude_agent():
    """LLMFactory.create('claude-agent') returns ClaudeAgentClient."""
    from parrot.clients.factory import LLMFactory
    client = LLMFactory.create("claude-agent:claude-sonnet-4-6")
    assert type(client).__name__ == "ClaudeAgentClient"


def test_factory_claude_agent_missing_extra_message(monkeypatch):
    """When claude_agent_sdk unavailable, ImportError with pip hint."""
    # monkeypatch to make import fail
    # Assert ImportError message contains "pip install ai-parrot[claude-agent]"


@pytest.mark.live
@pytest.mark.asyncio
async def test_claude_agent_live_smoke():
    """Live test — runs actual claude CLI. Skipped if unavailable."""
    import shutil
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found")
    from parrot.clients.claude_agent import ClaudeAgentClient
    client = ClaudeAgentClient()
    result = await client.ask("List the files in cwd")
    assert result.output
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-857, TASK-858, TASK-859 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `ClaudeAgentClient` class exists as specified
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** the test file and fixture
6. **Run** `pytest tests/clients/test_claude_agent.py -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-861-claude-agent-client-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-124 autonomous run)
**Date**: 2026-04-27
**Notes**:
- Created `tests/clients/conftest.py` with the `fake_claude_agent_messages`
  pytest fixture (real `claude_agent_sdk` dataclasses when available;
  duck-typed `SimpleNamespace` fallback otherwise) plus a
  `_install_navigator_file_stubs()` helper that injects placeholder
  attributes onto `navigator.utils.file` (`FileManagerInterface`,
  `FileMetadata`, `LocalFileManager`, `TempFileManager`,
  `FileManagerFactory`) so `parrot.clients.factory` imports cleanly in
  environments where `navigator` predates FEAT-123. The stubs are no-ops
  once a current `navigator` is installed.
- Created `tests/clients/test_claude_agent.py` with 20 tests covering all 7
  spec acceptance items plus parametrised verification of every
  unsupported method (`ask_to_image`, `summarize_text`, `translate_text`,
  `analyze_sentiment`, `analyze_product_review`, `extract_key_points`),
  `ClaudeAgentRunOptions` field defaults, and `resume()`.
- All 20 tests pass against `claude_agent_sdk==0.1.63` plus
  `anthropic==0.97.0`. Combined with the earlier 24 FEAT-124 tests
  (`test_anthropic_sdk_097.py` + `test_aimessage_factory_claude_agent.py`),
  the FEAT-124 suite total is **44 passing** with zero failures.
- The factory-import errors observed when first running these tests are
  **pre-existing** in this venv (the installed `navigator` version is
  older than FEAT-123 expects) and are mitigated for the FEAT-124 test
  suite by the conftest stubs. They are not caused by this feature.

**Deviations from spec**: minor — added a parametrised test that covers
each of the six "unsupported methods" mentioned in the spec
(NotImplementedError + AnthropicClient redirect message), beyond just
`batch_ask`.
