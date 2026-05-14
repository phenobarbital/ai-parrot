# TASK-1181: Integration Tests — Verify Streaming Contract Across All Clients

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1174, TASK-1175, TASK-1176, TASK-1177, TASK-1178, TASK-1179, TASK-1180
**Assigned-to**: unassigned

---

## Context

After all client implementations are complete, this task verifies the uniform
streaming contract: every client's `ask_stream` yields ≥1 `str` chunks followed
by exactly 1 `AIMessage` as the last item. Also verifies that `BaseBot.ask_stream`
prefers the client-provided AIMessage over its fallback construction.

Implements: Spec §4 Integration Tests.

---

## Scope

- Write parametrized integration tests covering all client classes.
- Verify the streaming contract: str chunks + final AIMessage.
- Verify `BaseBot.ask_stream` receives and passes through the client AIMessage.
- Verify the `AbstractClient.ask_stream` type annotation is correct.

**NOT in scope**: Testing individual client features beyond the streaming contract.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/test_stream_contract.py` | CREATE | Parametrized tests for all clients |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage, CompletionUsage  # verified: parrot/models/__init__.py
from parrot.clients.base import AbstractClient  # verified: parrot/clients/base.py
from parrot.clients.claude import AnthropicClient  # verify actual class name in claude.py
from parrot.clients.gpt import OpenAIClient  # verified: gpt.py
from parrot.clients.groq import GroqClient  # verified: groq.py
from parrot.clients.grok import GrokClient  # verified: grok.py
from parrot.clients.gemma4 import Gemma4Client  # verified: gemma4.py
from parrot.clients.hf import TransformersClient  # verified: hf.py
from parrot.clients.claude_agent import ClaudeAgentClient  # verified: claude_agent.py
from parrot.bots.base import BaseBot  # verified: bots/base.py
```

### Does NOT Exist
- ~~`parrot.clients.claude.ClaudeClient`~~ — verify actual class name (may be `AnthropicClient`)
- ~~`parrot.testing.mock_stream`~~ — no test helpers for streaming; build mocks locally

---

## Implementation Notes

### Test Strategy
Use mocking to avoid real API calls. Each client mock should:
1. Return an async generator that yields 2-3 str chunks
2. Return a properly constructed AIMessage as the final item

### Parametrized Test Pattern
```python
import pytest
from typing import Union, AsyncIterator, get_type_hints
from parrot.models import AIMessage


CLIENTS_TO_TEST = [
    "AnthropicClient",  # or whatever the actual class name is
    "OpenAIClient",
    "GroqClient",
    "GrokClient",
    "Gemma4Client",
    "TransformersClient",
    "ClaudeAgentClient",
]


def test_abstract_client_return_type():
    """AbstractClient.ask_stream has Union[str, AIMessage] return type."""
    hints = get_type_hints(AbstractClient.ask_stream)
    assert hints["return"] == AsyncIterator[Union[str, AIMessage]]


class TestStreamContract:
    """Verify all clients follow the str-chunks + final-AIMessage contract."""

    async def _consume_stream(self, stream):
        chunks = []
        ai_msg = None
        async for item in stream:
            if isinstance(item, AIMessage):
                ai_msg = item
            else:
                assert isinstance(item, str), f"Expected str, got {type(item)}"
                chunks.append(item)
        return chunks, ai_msg

    @pytest.mark.asyncio
    async def test_stream_yields_aimessage_last(self, mock_client):
        chunks, ai_msg = await self._consume_stream(
            mock_client.ask_stream("test prompt")
        )
        assert len(chunks) > 0, "Should yield at least one str chunk"
        assert ai_msg is not None, "Should yield final AIMessage"
        assert isinstance(ai_msg.model, str)
        assert isinstance(ai_msg.provider, str)
        assert ai_msg.turn_id is not None
```

### Key Constraints
- Tests must not make real API calls.
- Verify actual class names by grepping the client files before writing imports.
- Each test should verify: ≥1 str chunk, exactly 1 AIMessage, AIMessage is last.

---

## Acceptance Criteria

- [ ] Parametrized test covers all 7 client classes
- [ ] Tests verify: ≥1 str yield, exactly 1 AIMessage yield, AIMessage is last
- [ ] Tests verify AIMessage has: model, provider, turn_id populated
- [ ] BaseBot test verifies client AIMessage is used (not fallback)
- [ ] All tests pass: `pytest tests/unit/test_stream_contract.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/homologate-llm-clients-askstream.spec.md`
2. **Check dependencies** — ALL TASK-1174 through TASK-1180 must be completed
3. **Verify class names** — `grep "^class" packages/ai-parrot/src/parrot/clients/*.py`
4. **Write tests** with proper mocking
5. **Run tests** and verify all pass

---

## Completion Note

*(Agent fills this in when done)*
