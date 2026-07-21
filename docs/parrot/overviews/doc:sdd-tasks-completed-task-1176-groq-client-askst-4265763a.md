---
type: Wiki Overview
title: 'TASK-1176: GroqClient `ask_stream` — Yield Final AIMessage'
id: doc:sdd-tasks-completed-task-1176-groq-client-askstream-aimessage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: GroqClient uses the Groq SDK (OpenAI-compatible) for streaming. The streaming
relates_to:
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1176: GroqClient `ask_stream` — Yield Final AIMessage

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1173
**Assigned-to**: unassigned

---

## Context

GroqClient uses the Groq SDK (OpenAI-compatible) for streaming. The streaming
loop accumulates `assistant_content` but currently yields only `str` chunks.
The Groq SDK mirrors OpenAI's API — it should support
`stream_options={"include_usage": True}` for usage in the final chunk.

Implements: Spec §3 Module 4.

---

## Scope

- Update `ask_stream` return type from `AsyncIterator[str]` to
  `AsyncIterator[Union[str, AIMessage]]`.
- After the streaming loop (line 650), build and yield `AIMessage` using
  `AIMessageFactory.from_groq()`.
- Attempt to add `stream_options={"include_usage": True}` to `request_args`.
  If the SDK rejects it, fall back to zeroed usage.
- Yield AIMessage before conversation memory update (line 652).

**NOT in scope**: Streaming tool-call support. Modifying `ask()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/groq.py` | MODIFY | Add AIMessage yield at end of ask_stream |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage, AIMessageFactory, CompletionUsage  # verified: parrot/models/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/groq.py:596-608
async def ask_stream(
    self, prompt: str,
    model: str = GroqModel.LLAMA_3_3_70B_VERSATILE,
    ...
) -> AsyncIterator[str]:  # line 608 — CHANGE

# packages/ai-parrot/src/parrot/clients/groq.py:643
response_stream = await self.client.chat.completions.create(**request_args)

# packages/ai-parrot/src/parrot/clients/groq.py:645-650
assistant_content = ""
async for chunk in response_stream:
    if chunk.choices and chunk.choices[0].delta.content:
        text_chunk = chunk.choices[0].delta.content
        assistant_content += text_chunk
        yield text_chunk

# packages/ai-parrot/src/parrot/models/responses.py:468
@staticmethod
def from_groq(response, input_text, model, ...) -> AIMessage:
# Note: from_groq expects response.choices[0].message — not applicable for streaming.
# Use AIMessageFactory.create_message() or direct AIMessage construction instead.

# packages/ai-parrot/src/parrot/models/basic.py:72
@classmethod
def from_groq(cls, usage: Any) -> "CompletionUsage":
```

### Does NOT Exist
- ~~`response_stream.get_final_message()`~~ — Groq streaming has no final message accessor
- ~~`response_stream.get_final_response()`~~ — not available in Groq streaming

---

## Implementation Notes

### Pattern
Since `from_groq()` expects a full response object with `choices[0].message`,
and streaming doesn't provide one, build the AIMessage directly:

```python
# After the streaming loop, before memory update
usage_data = None
async for chunk in response_stream:
    if chunk.choices and chunk.choices[0].delta.content:
        text_chunk = chunk.choices[0].delta.content
        assistant_content += text_chunk
        yield text_chunk
    if hasattr(chunk, 'usage') and chunk.usage is not None:
        usage_data = chunk.usage

# Build AIMessage
if usage_data is not None:
    usage = CompletionUsage.from_groq(usage_data)
else:
    usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

ai_message = AIMessage(
    input=prompt,
    output=assistant_content,
    response=assistant_content,
    model=model,
    provider="groq",
    usage=usage,
    user_id=user_id,
    session_id=session_id,
    turn_id=turn_id,
)
yield ai_message
```

### Key Constraints
- Add `stream_options={"include_usage": True}` to `request_args` (line 622-630).
  Wrap in try-except in case older Groq SDK versions don't support it.
- Variable `model` at line 613 is already resolved. `turn_id` at line 612.
- `prompt` is the original parameter name.

---

## Acceptance Criteria

- [ ] `GroqClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] Final `AIMessage` is yielded after all text chunks
- [ ] `AIMessage.provider == "groq"`
- [ ] Usage stats populated when `stream_options` works, zeroed otherwise
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/groq.py`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_groq_ask_stream_yields_aimessage():
    """GroqClient.ask_stream yields str chunks then final AIMessage."""
    chunks, ai_msg = [], None
    async for chunk in client.ask_stream("test"):
        if isinstance(chunk, AIMessage):
            ai_msg = chunk
        else:
            chunks.append(chunk)
    assert ai_msg is not None
    assert ai_msg.provider == "groq"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/homologate-llm-clients-askstream.spec.md`
2. **Check dependencies** — verify TASK-1173 is completed
3. **Read the full ask_stream** (lines 596-670)
4. **Test `stream_options`** support in Groq SDK if possible
5. **Implement** and verify

---

## Completion Note

Implemented 2026-05-15. Added `stream_options={"include_usage": True}` to
`request_args`. Changed return type to `AsyncIterator[Union[str, AIMessage]]`.
Captures `usage_data` from final chunk in streaming loop. Yields AIMessage with
`CompletionUsage.from_groq(usage_data)` when available, zeroed usage otherwise.
Also added `deep_research`, `agent_config`, `lazy_loading` params to match the
abstract interface. Lint passes clean.
