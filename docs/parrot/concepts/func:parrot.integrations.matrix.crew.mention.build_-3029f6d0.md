---
type: Concept
title: build_reply_content()
id: func:parrot.integrations.matrix.crew.mention.build_reply_content
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build the ``m.relates_to`` content dict for a reply-to message.
---

# build_reply_content

```python
def build_reply_content(text: str, reply_to_event_id: str) -> dict
```

Build the ``m.relates_to`` content dict for a reply-to message.

Constructs the event content fragment needed to mark a Matrix message
as a threaded reply to an existing event.

Args:
    text: Message body text.
    reply_to_event_id: Event ID of the message being replied to.

Returns:
    Dict with ``body`` and ``m.relates_to`` keys suitable for inclusion
    in a Matrix event content.
