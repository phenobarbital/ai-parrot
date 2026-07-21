---
type: Wiki Overview
title: 'TASK-1178: Gemma4Client `ask_stream` — Yield Final AIMessage'
id: doc:sdd-tasks-completed-task-1178-gemma4-client-askstream-aimessage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Gemma4Client uses pseudo-streaming: `ask_stream` calls `self.ask()` (which'
relates_to:
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1178: Gemma4Client `ask_stream` — Yield Final AIMessage

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1173
**Assigned-to**: unassigned

---

## Context

Gemma4Client uses pseudo-streaming: `ask_stream` calls `self.ask()` (which
returns an `AIMessage`), then yields the text in chunks. The `AIMessage` from
`ask()` already has full metadata — we just need to yield it at the end.

Implements: Spec §3 Module 6.

---

## Scope

- Update `ask_stream` return type from `AsyncIterator[str]` to
  `AsyncIterator[Union[str, AIMessage]]`.
- After yielding all text chunks, yield the `response` (AIMessage) from `self.ask()`.

**NOT in scope**: Implementing true streaming for Gemma4.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gemma4.py` | MODIFY | Yield the AIMessage from ask() at end |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage  # verified: parrot/models/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/gemma4.py:639-668
async def ask_stream(self, prompt, ...) -> AsyncIterator[str]:  # line 651 — CHANGE
    """Pseudo-streaming: generates fully then yields chunks."""
    response = await self.ask(...)  # line 653 — returns AIMessage
    text = response.content         # line 664
    chunk_size = 10
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]
        await asyncio.sleep(0.01)
```

### Does NOT Exist
- ~~`AIMessageFactory.from_gemma()`~~ — no such factory; `response` IS already an AIMessage

---

## Implementation Notes

This is the simplest task — `self.ask()` already returns an `AIMessage`. Just
yield it after the chunk loop:

```python
async def ask_stream(self, ...) -> AsyncIterator[Union[str, AIMessage]]:
    response = await self.ask(...)
    text = response.content
    chunk_size = 10
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]
        await asyncio.sleep(0.01)
    yield response  # response is already an AIMessage from self.ask()
```

---

## Acceptance Criteria

- [ ] `Gemma4Client.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] Final yield is the `AIMessage` from `self.ask()`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/gemma4.py`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_gemma4_ask_stream_yields_aimessage():
    chunks, ai_msg = [], None
    async for chunk in client.ask_stream("test"):
        if isinstance(chunk, AIMessage):
            ai_msg = chunk
        else:
            chunks.append(chunk)
    assert ai_msg is not None
    assert isinstance(ai_msg, AIMessage)
```

---

## Completion Note

Implemented 2026-05-15. Changed return type to `AsyncIterator[Union[str, AIMessage]]`.
After the chunk loop, added `yield response` — where `response` is the AIMessage
already returned by `self.ask()`. Also removed pre-existing unused import
`InvokeError`. Lint passes clean.
