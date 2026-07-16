---
type: Wiki Overview
title: 'TASK-1179: TransformersClient `ask_stream` — Yield Final AIMessage'
id: doc:sdd-tasks-completed-task-1179-hf-client-askstream-aimessage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'TransformersClient uses pseudo-streaming identical to Gemma4Client: `ask_stream`'
relates_to:
- concept: mod:parrot.models
  rel: mentions
---

# TASK-1179: TransformersClient `ask_stream` — Yield Final AIMessage

**Feature**: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
**Spec**: `sdd/specs/homologate-llm-clients-askstream.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1173
**Assigned-to**: unassigned

---

## Context

TransformersClient uses pseudo-streaming identical to Gemma4Client: `ask_stream`
calls `self.ask()` (which returns an `AIMessage`), then yields text in chunks.
The `AIMessage` from `ask()` already has full metadata.

Implements: Spec §3 Module 7.

---

## Scope

- Update `ask_stream` return type from `AsyncIterator[str]` to
  `AsyncIterator[Union[str, AIMessage]]`.
- After yielding all text chunks, yield the `response` (AIMessage) from `self.ask()`.

**NOT in scope**: Implementing true streaming for Transformers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/hf.py` | MODIFY | Yield the AIMessage from ask() at end |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage  # verified: parrot/models/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/hf.py:495-534
async def ask_stream(self, prompt, ...) -> AsyncIterator[str]:  # line 507 — CHANGE
    response = await self.ask(...)  # line 514 — returns AIMessage
    text = response.content         # line 528
    chunk_size = 10
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        yield chunk
        await asyncio.sleep(0.01)
```

### Does NOT Exist
- ~~`AIMessageFactory.from_hf()`~~ — no such factory
- ~~`AIMessageFactory.from_transformers()`~~ — no such factory

---

## Implementation Notes

Identical pattern to TASK-1178 (Gemma4):

```python
async def ask_stream(self, ...) -> AsyncIterator[Union[str, AIMessage]]:
    response = await self.ask(...)
    text = response.content
    chunk_size = 10
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]
        await asyncio.sleep(0.01)
    yield response  # response is already an AIMessage from self.ask()
```

---

## Acceptance Criteria

- [ ] `TransformersClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] Final yield is the `AIMessage` from `self.ask()`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/hf.py`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_hf_ask_stream_yields_aimessage():
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

Implemented 2026-05-15. Identical pattern to Gemma4: changed return type to
`AsyncIterator[Union[str, AIMessage]]`, added `yield response` after the chunk loop.
Also removed 5 pre-existing unused imports (ruff auto-fix). Pre-existing F821
(`"torch.dtype"` forward reference — false positive) and F841 (`turn_id` in
`resume()`) remain; these are not caused by this task. Task-specific
implementation lint: done-with-issues (pre-existing F821/F841).
