---
type: Wiki Overview
title: 'TASK-1174: ClaudeClient `ask_stream` — Yield Final AIMessage'
id: doc:sdd-tasks-completed-task-1174-claude-client-askstream-aimessage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ClaudeClient already captures `final_message = await stream.get_final_message()`
relates_to:
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1174: ClaudeClient `ask_stream` — Yield Final AIMessage

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1173
**Assigned-to**: unassigned

---

## Context

ClaudeClient already captures `final_message = await stream.get_final_message()`
(line 555) with full usage, stop_reason, and model metadata — but currently
discards it after checking `stop_reason`. This task adds a final `AIMessage`
yield using `AIMessageFactory.from_claude()`, identical to how the non-streaming
`ask()` method builds its return value.

Implements: Spec §3 Module 2.

---

## Scope

- Update `ask_stream` return type from `AsyncIterator[str]` to
  `AsyncIterator[Union[str, AIMessage]]`.
- After the streaming retry loop completes (after line 619, before conversation
  memory update), build and yield an `AIMessage` using `AIMessageFactory.from_claude()`.
- Use `final_message.model_dump()` to convert the Anthropic SDK `Message` into
  the `Dict[str, Any]` that `from_claude()` expects.
- Handle the case where `final_message` may not exist (exception path) —
  fall back to constructing a minimal AIMessage with zeroed usage.

**NOT in scope**: Modifying the non-streaming `ask()` method. Streaming tool-call support.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | Add AIMessage yield at end of ask_stream |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage, AIMessageFactory, CompletionUsage  # verified: parrot/models/__init__.py
from typing import AsyncIterator, Union  # already imported in claude.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude.py:467-484
async def ask_stream(
    self,
    prompt: str,
    model: Union[ClaudeModel, str] = None,
    ...
) -> AsyncIterator[str]:  # line 484 — CHANGE to Union[str, AIMessage]

# packages/ai-parrot/src/parrot/clients/claude.py:555
final_message = await stream.get_final_message()
# Returns Anthropic Message object with: id, type, role, content, model,
# stop_reason, usage (input_tokens, output_tokens)
# .model_dump() converts to dict

# packages/ai-parrot/src/parrot/models/responses.py:573
@staticmethod
def from_claude(
    response: Dict[str, Any],
    input_text: str,
    model: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    structured_output: Any = None,
    tool_calls: List[ToolCall] = None
) -> AIMessage:

# packages/ai-parrot/src/parrot/models/basic.py:85
@classmethod
def from_claude(cls, usage: Dict[str, Any]) -> "CompletionUsage":
    # Expects: {'input_tokens': N, 'output_tokens': N}
```

### Does NOT Exist
- ~~`AIMessageFactory.from_anthropic()`~~ — use `from_claude()` instead
- ~~`stream.get_usage()`~~ — usage is on `final_message.usage`, not a separate call
- ~~`CompletionUsage.from_anthropic()`~~ — use `from_claude()`

---

## Implementation Notes

### Pattern to Follow (GoogleGenAIClient reference)
```python
# packages/ai-parrot/src/parrot/clients/google/client.py:2891-2907
ai_message = AIMessageFactory.from_gemini(
    response=None,
    input_text=prompt,
    model=model,
    user_id=user_id,
    session_id=session_id,
    turn_id=turn_id,
    structured_output=final_output if final_output is not None else final_text,
    tool_calls=all_tool_calls_history,
    ...
)
ai_message.provider = "google_genai"
yield ai_message
```

### Where to Insert
After the retry `while` loop ends (around line 619-620), just before the
conversation memory update block (line 621-636):

```python
# Build final AIMessage
if final_message is not None:
    ai_message = AIMessageFactory.from_claude(
        response=final_message.model_dump(),
        input_text=original_prompt,
        model=model_str,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
    )
else:
    ai_message = AIMessage(
        input=original_prompt,
        output=assistant_content,
        response=assistant_content,
        model=model_str,
        provider="claude",
        usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
    )
yield ai_message
```

### Key Constraints
- `final_message` is only set inside the `try` block at line 555. If an exception
  breaks the stream, it may be `None`. Initialize it to `None` before the loop.
- `original_prompt` is the original prompt variable. `model_str` is the resolved model.
  Verify these variable names by reading the full method.
- The `turn_id` variable is generated at the top of `ask_stream`. Verify it exists.

---

## Acceptance Criteria

- [ ] `ClaudeClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] Final `AIMessage` is yielded after all text chunks
- [ ] `AIMessage.usage.prompt_tokens > 0` when stream completes successfully
- [ ] Fallback `AIMessage` with zeroed usage when `final_message` is unavailable
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/claude.py`

---

## Test Specification

```python
# tests/unit/test_claude_stream_aimessage.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.models import AIMessage


@pytest.mark.asyncio
async def test_claude_ask_stream_yields_aimessage():
    """ClaudeClient.ask_stream yields str chunks then final AIMessage."""
    # Mock setup for Anthropic streaming
    chunks = []
    ai_msg = None
    async for chunk in client.ask_stream("test prompt"):
        if isinstance(chunk, AIMessage):
            ai_msg = chunk
        else:
            chunks.append(chunk)

    assert len(chunks) > 0, "Should yield at least one str chunk"
    assert ai_msg is not None, "Should yield final AIMessage"
    assert ai_msg.provider == "claude"
    assert ai_msg.model is not None
    assert ai_msg.turn_id is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/homologate-llm-clients-askstream.spec.md`
2. **Check dependencies** — verify TASK-1173 is completed
3. **Verify the Codebase Contract** — `read` claude.py to confirm `final_message` at line 555
4. **Read the full ask_stream method** (lines 467-636) to understand variable scope
5. **Implement** the AIMessage yield
6. **Verify** acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

Implemented 2026-05-15. Initialized `final_message = None` before the retry
while loop. Changed return type to `AsyncIterator[Union[str, AIMessage]]`.
After the while loop, yields `AIMessageFactory.from_claude(final_message.model_dump(), ...)`
when final_message is available, or a fallback AIMessage with zeroed usage
otherwise. Also fixed 3 pre-existing f-string lint issues. Lint passes clean.
