---
type: Wiki Overview
title: 'TASK-1177: GrokClient `ask_stream` — Yield Final AIMessage'
id: doc:sdd-tasks-completed-task-1177-grok-client-askstream-aimessage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: GrokClient (xAI) uses a custom chat SDK. The streaming loop iterates
relates_to:
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1177: GrokClient `ask_stream` — Yield Final AIMessage

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1173
**Assigned-to**: unassigned

---

## Context

GrokClient (xAI) uses a custom chat SDK. The streaming loop iterates
`chat.stream()` and accumulates tokens. There's no final message object
accessible after streaming — AIMessage will be built with best-effort metadata
and zeroed usage if usage isn't available.

Implements: Spec §3 Module 5.

---

## Scope

- Update `ask_stream` return type from `AsyncIterator[str]` to
  `AsyncIterator[Union[str, AIMessage]]`.
- After the streaming loop (line 477), build and yield `AIMessage`.
- Use best-effort metadata; zeroed usage is acceptable.
- Yield AIMessage before conversation memory update (line 479).

**NOT in scope**: Modifying `ask()`. Adding usage extraction from xAI SDK.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/grok.py` | MODIFY | Add AIMessage yield at end of ask_stream |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage, AIMessageFactory, CompletionUsage  # verified: parrot/models/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/grok.py:408-420
async def ask_stream(
    self, prompt: str, model: str = None, ...
) -> AsyncIterator[str]:  # line 420 — CHANGE

# packages/ai-parrot/src/parrot/clients/grok.py:424
turn_id = str(uuid.uuid4())

# packages/ai-parrot/src/parrot/clients/grok.py:464-477
full_response = []
async for token in chat.stream():
    content = token
    ...
    if content:
        full_response.append(content)
        yield content

# packages/ai-parrot/src/parrot/models/basic.py:172
@classmethod
def from_grok(cls, usage: Any) -> "CompletionUsage":
```

### Does NOT Exist
- ~~`chat.get_final_response()`~~ — xAI chat SDK has no such method
- ~~`chat.usage`~~ — not available after streaming
- ~~`AIMessageFactory.from_xai()`~~ — use `from_grok()`

---

## Implementation Notes

```python
# After streaming loop, before memory update
final_text = "".join(full_response)
ai_message = AIMessage(
    input=prompt,
    output=final_text,
    response=final_text,
    model=model or self.model or self.default_model,
    provider="grok",
    usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    user_id=user_id,
    session_id=session_id,
    turn_id=turn_id,
)
yield ai_message
```

---

## Acceptance Criteria

- [ ] `GrokClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] Final `AIMessage` is yielded with `provider="grok"`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/grok.py`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_grok_ask_stream_yields_aimessage():
    chunks, ai_msg = [], None
    async for chunk in client.ask_stream("test"):
        if isinstance(chunk, AIMessage):
            ai_msg = chunk
        else:
            chunks.append(chunk)
    assert ai_msg is not None
    assert ai_msg.provider == "grok"
```

---

## Completion Note

Implemented 2026-05-15. Changed return type to `AsyncIterator[Union[str, AIMessage]]`.
Added `deep_research`, `agent_config`, `lazy_loading` params to match abstract interface.
After the streaming loop, assembles `final_text = "".join(full_response)` and yields
AIMessage with `provider="grok"` and zeroed usage (xAI SDK has no final response object).
Pre-existing E402, F821 (undefined `output_config`), F841 lint issues in grok.py exist
prior to this task and cannot be fixed without restructuring the file (out of scope).
Unused imports cleaned up. Task-specific lint: done-with-issues (pre-existing E402/F821).
