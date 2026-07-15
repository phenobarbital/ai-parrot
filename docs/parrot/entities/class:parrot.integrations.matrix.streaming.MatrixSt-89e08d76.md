---
type: Wiki Entity
title: MatrixStreamHandler
id: class:parrot.integrations.matrix.streaming.MatrixStreamHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handles streaming LLM output to a Matrix room via message edits.
---

# MatrixStreamHandler

Defined in [`parrot.integrations.matrix.streaming`](../summaries/mod:parrot.integrations.matrix.streaming.md).

```python
class MatrixStreamHandler
```

Handles streaming LLM output to a Matrix room via message edits.

Usage::

    handler = MatrixStreamHandler(wrapper, room_id)
    event_id = await handler.begin_stream("Thinking...")

    async for token in llm_stream:
        await handler.send_token(event_id, token)

    await handler.end_stream(event_id, final_text)

## Methods

- `async def begin_stream(self, initial_text: str='▌') -> str` — Send the initial message and return its event_id.
- `async def send_token(self, event_id: str, token: str) -> None` — Accumulate a token and edit the message if thresholds are met.
- `async def end_stream(self, event_id: str, final_text: Optional[str]=None) -> None` — Finalize the stream with the complete response.
