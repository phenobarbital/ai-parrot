# TASK-1745: BedrockConverseClient Core

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4–8h)
**Depends-on**: TASK-1742, TASK-1743, TASK-1744
**Assigned-to**: unassigned

---

## Context

This is the central task: implement the `BedrockConverseClient` class with `aioboto3` session management and the Bedrock Converse API for text-based LLM interaction. Depends on the response models, tool schema adapter, and model ID translator from the previous tasks.

Implements Spec Module 4.

---

## Scope

- Create `packages/ai-parrot/src/parrot/clients/bedrock.py`
- Implement `BedrockConverseClient(AbstractClient)` with:
  - `client_type = "bedrock-converse"`, `client_name = "bedrock-converse"`
  - `_default_model = "claude-sonnet-4-5"` (via Bedrock model ID)
  - `get_client()` — create `aioboto3` session and `bedrock-runtime` client
  - `_sdk_create(messages, **kwargs)` — thin wrapper around `converse()`
  - `_sdk_stream(messages, **kwargs)` — thin wrapper around `converse_stream()`
  - `ask(prompt, ...)` — non-streaming completion with tool-use loop
  - `ask_stream(prompt, ...)` — streaming completion yielding `str` chunks then `AIMessage`
  - `resume(messages, ...)` — continue a conversation from existing messages
  - `invoke(prompt, ...)` — single-turn, no tool-use, returns `InvokeResult`
  - `_prepare_messages(messages)` — convert ai-parrot messages to Bedrock format
  - `_prepare_tools(tools)` — use `ToolSchemaAdapter` with `ToolFormat.BEDROCK`
- Handle tool-use loop: unbounded `while True` on `stopReason == "tool_use"` (same pattern as AnthropicClient)
- Map `reasoningContent` blocks with `signature` through tool-use loops (preserve signature for Bedrock validation)
- Use `CompletionUsage.from_bedrock()` and `AIMessageFactory.from_bedrock()` from TASK-1742
- Use `translate()` from `bedrock_models.py` for model ID resolution

**NOT in scope**: Extended thinking, prompt caching, structured output (TASK-1746), NovaSonicClient (TASK-1748), factory registration (TASK-1747).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | CREATE | `BedrockConverseClient` implementation |
| `tests/clients/test_bedrock_converse.py` | CREATE | Unit tests with mocked aioboto3 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # verified: parrot/clients/base.py:244
from parrot.models.basic import CompletionUsage, ToolCall  # verified: parrot/models/basic.py:48, 23
from parrot.models.responses import AIMessage, AIMessageFactory, InvokeResult  # verified: parrot/models/responses.py:72, 389, 1282
from parrot.models.bedrock_models import translate  # verified: parrot/models/bedrock_models.py:87
from parrot.tools.manager import ToolFormat, ToolSchemaAdapter  # verified: parrot/tools/manager.py:43, 53
```

### Existing Signatures to Use
```python
# parrot/clients/base.py:244
class AbstractClient:
    client_type: str  # line 273
    client_name: str  # line 274
    _default_model: str  # line 278
    _min_cache_tokens: int = 0  # line 280

    async def get_client(self) -> Any:  # line 846 (abstract)
    async def ask(self, prompt: str, ...) -> AIMessage:  # line 412 (abstract)
    async def ask_stream(self, prompt: str, ...) -> AsyncIterator:  # line 810 (abstract)
    async def resume(self, messages: List[Dict], ...) -> AIMessage:  # line 700 (abstract)
    async def invoke(self, prompt: str, ...) -> InvokeResult:  # line 1810 (abstract)

    def _prepare_tools(self, tools: list) -> list:  # line 1270 (available for override)
    async def _execute_tool(self, tool_call: ToolCall, tools: list) -> Any:  # line 1330
    def _build_invoke_result(self, ...) -> InvokeResult:  # line 1731

# parrot/clients/claude.py:67 (REFERENCE pattern — do NOT import)
class AnthropicClient(AbstractClient):
    async def _sdk_create(self, messages, **kwargs):  # line 310
    async def _sdk_stream(self, messages, **kwargs):  # line 316
    # Tool loop: while True on stop_reason == "tool_use" in ask() at line 412
```

### Does NOT Exist
- ~~`AbstractClient.converse()`~~ — not a method; use raw aioboto3 client
- ~~`AbstractClient._sdk_create()`~~ — not abstract; each client defines its own thin wrapper
- ~~`parrot.clients.bedrock`~~ — does not exist yet; this task creates it
- ~~`aioboto3` in pyproject.toml~~ — not yet a dependency (TASK-1747 adds it)
- ~~`AbstractClient.reasoning_content`~~ — not a field; handle in raw response

---

## Implementation Notes

### Session & Client Management
```python
import aioboto3

class BedrockConverseClient(AbstractClient):
    client_type = "bedrock-converse"
    client_name = "bedrock-converse"
    _default_model = "claude-sonnet-4-5"
    _tool_format = ToolFormat.BEDROCK

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._session = None
        self._bedrock_client = None
        self._region = kwargs.get("region", "us-east-1")

    async def get_client(self):
        if self._bedrock_client is None:
            self._session = aioboto3.Session()
            self._bedrock_client = await self._session.client(
                "bedrock-runtime", region_name=self._region
            ).__aenter__()
        return self._bedrock_client
```

### Tool-Use Loop Pattern
```python
# Follow AnthropicClient.ask() pattern at claude.py:412
# Key difference: Bedrock uses camelCase and different content block shapes
#
# Bedrock tool_use content block:
# {"toolUse": {"toolUseId": "...", "name": "...", "input": {...}}}
#
# Bedrock tool_result message:
# {"role": "user", "content": [{"toolResult": {"toolUseId": "...", "content": [{"text": "..."}]}}]}
```

### ReasoningContent Signature Preservation
```python
# When stopReason == "tool_use" AND response contains reasoningContent with signature:
# 1. Extract the signature from the reasoningContent block
# 2. Include it in the next request's messages to avoid Bedrock ValidationException
# 3. The signature is opaque — pass it through unmodified
```

### Key Constraints
- `aioboto3.Session()` is NOT async — only the client context manager is
- Model IDs must go through `translate()` before passing to `converse()`
- `converse()` takes `modelId`, `messages`, `system` (list of content blocks), `toolConfig`
- `converse_stream()` returns an async iterator of events, not a response dict
- Stream events: `contentBlockStart`, `contentBlockDelta`, `contentBlockStop`, `messageStop`, `metadata`

---

## Acceptance Criteria

- [ ] `BedrockConverseClient` inherits `AbstractClient` and implements all 5 abstract methods
- [ ] `get_client()` creates and caches an `aioboto3` bedrock-runtime client
- [ ] `ask()` sends `converse()` and returns `AIMessage` with correct provider
- [ ] `ask()` handles tool-use loop (multiple rounds until `stopReason != "tool_use"`)
- [ ] `ask_stream()` yields `str` chunks then `AIMessage` sentinel
- [ ] `resume()` continues from existing message history
- [ ] `invoke()` returns `InvokeResult` for single-turn use
- [ ] `reasoningContent.signature` is preserved through tool-use loops
- [ ] Model IDs are resolved via `translate()` from `bedrock_models.py`
- [ ] All tests pass: `pytest tests/clients/test_bedrock_converse.py -v`

---

## Test Specification

```python
# tests/clients/test_bedrock_converse.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.bedrock import BedrockConverseClient


@pytest.fixture
def mock_bedrock_response():
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": "Hello!"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5}
    }


class TestBedrockConverseClient:
    def test_client_type(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        assert client.client_type == "bedrock-converse"

    @pytest.mark.asyncio
    async def test_ask_basic(self, mock_bedrock_response):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=mock_bedrock_response):
            result = await client.ask("Hello")
            assert isinstance(result, AIMessage)
            assert result.output == "Hello!"
            assert result.provider == "bedrock-converse"

    @pytest.mark.asyncio
    async def test_tool_use_loop(self):
        tool_response = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_1", "name": "get_weather", "input": {"city": "NYC"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        final_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "NYC is sunny."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 30, "outputTokens": 15}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', side_effect=[tool_response, final_response]):
            with patch.object(client, '_execute_tool', return_value="Sunny, 25C"):
                result = await client.ask("What's the weather in NYC?")
                assert result.output == "NYC is sunny."
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/bedrock-client-llm.spec.md` for full context
2. **Verify dependencies**: confirm TASK-1742 (response models), TASK-1743 (tool schema), TASK-1744 (model IDs) are completed
3. **Study the AnthropicClient** at `parrot/clients/claude.py` — it is the reference implementation
4. **Study AbstractClient** at `parrot/clients/base.py` — all abstract methods must be implemented
5. **Implement** `BedrockConverseClient` following the patterns exactly
6. **Run tests** and verify all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
