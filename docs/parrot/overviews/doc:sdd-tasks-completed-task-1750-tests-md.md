---
type: Wiki Overview
title: 'TASK-1750: Comprehensive Test Suite for FEAT-302'
id: doc:sdd-tasks-completed-task-1750-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Each prior task includes its own unit tests. This task adds integration
  tests that span multiple components: end-to-end flow through factory → client →
  response models, error handling scenarios, and edge cases.'
relates_to:
- concept: mod:parrot.clients.bedrock
  rel: mentions
- concept: mod:parrot.clients.factory
  rel: mentions
- concept: mod:parrot.models.basic
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

# TASK-1750: Comprehensive Test Suite for FEAT-302

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-1745, TASK-1746, TASK-1747
**Assigned-to**: unassigned

---

## Context

Each prior task includes its own unit tests. This task adds integration tests that span multiple components: end-to-end flow through factory → client → response models, error handling scenarios, and edge cases.

Implements Spec Module 9.

---

## Scope

- **Integration tests**:
  - Factory instantiation → `BedrockConverseClient` → `ask()` → `AIMessage` (mocked SDK)
  - Full tool-use loop: multi-round with tool execution
  - Extended thinking + tool-use combined
  - Streaming with chunk validation
- **Error handling tests**:
  - `ThrottlingException` → retry behavior
  - `ValidationException` → proper error propagation
  - `ModelStreamErrorException` in streaming
  - Missing `aioboto3` → graceful `ImportError`
  - Invalid model ID → error message
- **Edge case tests**:
  - Empty response content blocks
  - Response with only `reasoningContent` (no text)
  - Multiple text blocks concatenated
  - Very large tool results
  - `stopReason` values: `end_turn`, `tool_use`, `max_tokens`, `stop_sequence`, `guardrail_intervened`

**NOT in scope**: Live AWS integration tests (those require real credentials).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/clients/test_bedrock_integration.py` | CREATE | Integration tests spanning factory → client → models |
| `tests/clients/test_bedrock_errors.py` | CREATE | Error handling and edge case tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.factory import SUPPORTED_CLIENTS  # verified: factory.py:48
from parrot.clients.bedrock import BedrockConverseClient  # created by TASK-1745
from parrot.models.basic import CompletionUsage, ToolCall  # verified: basic.py:48, 23
from parrot.models.responses import AIMessage, AIMessageFactory  # verified: responses.py:72, 389
from parrot.tools.manager import ToolFormat  # verified: manager.py:43
```

---

## Implementation Notes

### Key Constraints
- All tests use mocked `aioboto3` — no real AWS calls
- Use `pytest-asyncio` for all async tests
- Follow existing test patterns in the `tests/` directory
- Use `pytest.mark.parametrize` for `stopReason` variations

---

## Acceptance Criteria

- [ ] Integration test: factory → client → ask → AIMessage roundtrip works
- [ ] Integration test: full tool-use loop (3+ rounds) completes correctly
- [ ] Integration test: streaming yields str chunks then AIMessage
- [ ] Error test: ThrottlingException triggers retry or proper error
- [ ] Error test: missing aioboto3 raises ImportError
- [ ] Edge case: empty content blocks return empty string output
- [ ] Edge case: all 5 stopReason values handled correctly
- [ ] All tests pass: `pytest tests/clients/test_bedrock_integration.py tests/clients/test_bedrock_errors.py -v`

---

## Test Specification

```python
# tests/clients/test_bedrock_integration.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestBedrockIntegration:
    @pytest.mark.asyncio
    async def test_factory_to_client_roundtrip(self):
        """Factory resolves bedrock-converse → client → ask → AIMessage."""
        from parrot.clients.factory import SUPPORTED_CLIENTS
        resolver = SUPPORTED_CLIENTS["bedrock-converse"]
        ClientCls = resolver() if callable(resolver) and not isinstance(resolver, type) else resolver
        client = ClientCls(model="claude-sonnet-4-5")
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "integrated!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        with patch.object(client, 'get_client', return_value=AsyncMock()), \
             patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("test")
            assert result.provider == "bedrock-converse"

    @pytest.mark.asyncio
    async def test_multi_round_tool_loop(self):
        """Tool-use loop completes after 3 rounds."""
        # Build 3 tool-use responses + 1 final response
        pass  # Implementation: sequence of mock responses

    @pytest.mark.parametrize("stop_reason", [
        "end_turn", "tool_use", "max_tokens", "stop_sequence", "guardrail_intervened"
    ])
    @pytest.mark.asyncio
    async def test_stop_reasons(self, stop_reason):
        """All stopReason values are handled correctly."""
        pass  # Implementation: mock response with each stopReason


# tests/clients/test_bedrock_errors.py
class TestBedrockErrors:
    def test_import_error_without_aioboto3(self):
        """Client raises ImportError when aioboto3 is not installed."""
        pass

    @pytest.mark.asyncio
    async def test_empty_content_blocks(self):
        """Empty content blocks return empty string output."""
        pass

    @pytest.mark.asyncio
    async def test_reasoning_only_response(self):
        """Response with only reasoningContent and no text."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context on Module 9
2. **Verify** TASK-1745, TASK-1746, TASK-1747 are completed
3. **Read** existing test patterns in `tests/clients/`
4. **Read** the task-level tests from TASK-1742, -1743, -1744, -1745, -1746 to avoid duplication
5. **Implement** integration and error tests that cover cross-component scenarios
6. **Run** the full test suite to verify no regressions

---

## Completion Note

Created `packages/ai-parrot/tests/clients/test_bedrock_integration.py` (7
tests) covering: factory→client→ask→AIMessage roundtrip, a 3-round
multi-tool-use loop, extended thinking combined with tool-use (signature
preserved into the follow-up payload), streaming chunk validation
(concatenation + usage on the sentinel), all 4 non-`tool_use` `stopReason`
values terminating the loop after one round (parametrized), and `tool_use`
continuing the loop.

Created `packages/ai-parrot/tests/clients/test_bedrock_errors.py` (9 tests)
covering: `ImportError` when `aioboto3` is unavailable (via
`sys.modules` patching), `ThrottlingException` → fallback-model retry,
`ValidationException` → unmodified propagation (no retry), a mid-stream
error propagating out of `ask_stream()`'s async generator (not swallowed),
an unrecognized model ID passing through with a logged warning (not a hard
failure — existing `bedrock_models.translate()` behavior from TASK-1744),
empty content blocks → empty string output, a reasoning-only response (no
text block) not crashing, multiple text blocks concatenating in order, and
a 200 KB tool result flowing through the loop intact.

Found and fixed a test-design issue while writing the fallback-retry test:
`AbstractClient.__init__` (base.py) always sets
`self._fallback_model = kwargs.get('fallback_model', None)`, which shadows
`BedrockConverseClient`'s class-level `_fallback_model = "claude-haiku-4-5"`
default unless a caller explicitly passes `fallback_model=` — this is
pre-existing base-class behavior (verified it identically affects
`AnthropicClient`, whose class-level `_fallback_model` is shadowed to
`None` the same way), not something introduced by this feature. The test
now passes `fallback_model="claude-haiku-4-5"` explicitly, matching how
real callers must configure it. Flagging here since it's a subtle
footgun — the class-level `_fallback_model` docstrings/defaults across all
providers read as if they're active by default, but they are not unless
explicitly passed as a constructor kwarg.

All 18 new tests pass. `ruff check` clean. Full re-run across all FEAT-302
test files (`test_bedrock_usage.py`, `test_bedrock_models.py` (both the
new one and the pre-existing TASK-1514 one), `test_bedrock_tool_format.py`,
`test_bedrock_converse.py`, `test_bedrock_advanced.py`,
`test_factory_bedrock.py`, plus these two new files) shows 109 tests
passing; the only failures in the broader `tests/clients/` directory are
the 2 pre-existing, unrelated `test_google_computer_use.py` failures
confirmed via `git stash` in TASK-1745.
