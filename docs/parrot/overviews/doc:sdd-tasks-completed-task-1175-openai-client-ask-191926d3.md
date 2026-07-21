---
type: Wiki Overview
title: 'TASK-1175: OpenAIClient `ask_stream` — Yield Final AIMessage'
id: doc:sdd-tasks-completed-task-1175-openai-client-askstream-aimessage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'OpenAIClient has two streaming paths: Responses API (newer, for o3/o4 models)'
relates_to:
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1175: OpenAIClient `ask_stream` — Yield Final AIMessage

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1173
**Assigned-to**: unassigned

---

## Context

OpenAIClient has two streaming paths: Responses API (newer, for o3/o4 models)
and Chat Completions API (classic). Both need final AIMessage yields.
The Responses API path already captures `final_response` at line 1339 but
doesn't use it for AIMessage construction. The Chat Completions path has no
final response object — usage must come from `stream_options`.

This also fixes derived clients: `OpenRouterClient`, `LocalLLMClient`,
`NvidiaClient`, `vLLMClient` — all inherit from `OpenAIClient` and don't
override `ask_stream`, so they get the fix for free.

Implements: Spec §3 Module 3.

---

## Scope

- Update `ask_stream` return type from `AsyncIterator[str]` to
  `AsyncIterator[Union[str, AIMessage]]`.
- **Responses API path**: After `final_response = await stream.get_final_response()`
  (line 1339), build and yield `AIMessage` using available metadata.
- **Chat Completions path**: Add `stream_options={"include_usage": True}` to the
  `create()` call. Capture usage from the final chunk. Build and yield `AIMessage`.
- Both paths: yield AIMessage just before the conversation memory update (line 1392).
- Handle gracefully when `final_response` is None or usage is unavailable.

**NOT in scope**: Modifying derived clients. Streaming tool-call support.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Add AIMessage yield at end of both streaming paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage, AIMessageFactory, CompletionUsage  # verified: parrot/models/__init__.py
from typing import AsyncIterator, Union  # already imported in gpt.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/gpt.py:1162-1180
async def ask_stream(
    self,
    prompt: str,
    model: Union[str, OpenAIModel] = OpenAIModel.GPT5_MINI,
    ...
) -> AsyncIterator[str]:  # line 1180 — CHANGE to Union[str, AIMessage]

# packages/ai-parrot/src/parrot/clients/gpt.py:1337-1341
final_response = None                              # line 1337
try:
    final_response = await stream.get_final_response()  # line 1339
except Exception:
    final_response = None                          # line 1341

# packages/ai-parrot/src/parrot/models/responses.py:419
@staticmethod
def from_openai(
    response: Any,
    input_text: str,
    model: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    structured_output: Any = None
) -> AIMessage:

# packages/ai-parrot/src/parrot/models/basic.py:63
@classmethod
def from_openai(cls, usage: Any) -> "CompletionUsage":
```

### Does NOT Exist
- ~~`AIMessageFactory.from_gpt()`~~ — use `from_openai()` instead
- ~~`CompletionUsage.from_gpt()`~~ — use `from_openai()`
- ~~`stream.get_final_message()`~~ in OpenAI — it's `get_final_response()` (Responses API only)
- ~~`chunk.usage`~~ on Chat Completions without `stream_options` — must opt in

---

## Implementation Notes

### Responses API Path (lines 1293-1358)
`final_response` is already captured. Build AIMessage from it:

```python
if final_response is not None:
    ai_message = AIMessageFactory.from_openai(
        response=final_response,
        input_text=prompt,
        model=model_str,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
    )
else:
    ai_message = AIMessage(
        input=prompt,
        output=assistant_content,
        response=assistant_content,
        model=model_str,
        provider="openai",
        usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
    )
```

Note: `from_openai()` expects `response.choices[0].message` — verify that
`final_response` from the Responses API has this structure. If not, you may
need to use `AIMessageFactory.create_message()` instead and manually extract
fields.

### Chat Completions Path (lines 1359-1390)
Add `stream_options={"include_usage": True}` to the `create()` call. The final
chunk will have a `usage` attribute. Capture it:

```python
usage_data = None
async for chunk in response_stream:
    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
        text_chunk = chunk.choices[0].delta.content
        assistant_content += text_chunk
        yield text_chunk
    # Capture usage from final chunk
    if hasattr(chunk, 'usage') and chunk.usage is not None:
        usage_data = chunk.usage
```

Then build AIMessage after the loop.

### Key Constraints
- `stream_options` may not be supported in older OpenAI SDK versions. Wrap in
  try-except — if the SDK rejects the parameter, fall back to zeroed usage.
- `turn_id` is generated at line 1193. `model_str` at line 1196. `prompt` is
  the original parameter. Verify variable names by reading the full method.
- The AIMessage yield must happen after BOTH paths converge (before line 1392).

---

## Acceptance Criteria

- [ ] `OpenAIClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] Responses API path yields final `AIMessage` with metadata from `final_response`
- [ ] Chat Completions path yields final `AIMessage` (usage from `stream_options` or zeroed)
- [ ] Derived clients (OpenRouter, LocalLLM, Nvidia, vLLM) inherit behavior
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/gpt.py`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_gpt_ask_stream_yields_aimessage():
    """OpenAIClient.ask_stream yields str chunks then final AIMessage."""
    chunks = []
    ai_msg = None
    async for chunk in client.ask_stream("test prompt"):
        if isinstance(chunk, AIMessage):
            ai_msg = chunk
        else:
            chunks.append(chunk)

    assert len(chunks) > 0
    assert ai_msg is not None
    assert ai_msg.provider == "openai"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/homologate-llm-clients-askstream.spec.md`
2. **Check dependencies** — verify TASK-1173 is completed
3. **Read the full ask_stream method** (lines 1162-1409) — it's long and has two paths
4. **Verify `final_response` structure** — read what `get_final_response()` returns
5. **Implement** both paths carefully
6. **Verify** acceptance criteria

---

## Completion Note

Implemented 2026-05-15. Two streaming paths handled:
- Responses API: yields AIMessage using `CompletionUsage.from_openai(final_response.usage)`
  after the existing `final_response = await stream.get_final_response()` block.
- Chat Completions: added `stream_options={"include_usage": True}` to `chat_args`,
  captures usage from final chunk, yields AIMessage. Also fixed a pre-existing bug
  where `TypeError` fallback from `parse()` left `response_stream` unset.
Also removed 3 pre-existing lint issues (2 unused imports, 1 unused variable).
Lint passes clean.
