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

*(Agent fills this in when done)*
