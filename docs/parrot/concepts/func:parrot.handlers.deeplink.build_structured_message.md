---
type: Concept
title: build_structured_message()
id: func:parrot.handlers.deeplink.build_structured_message
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Serialize a resumed action into a structured user-message query string.
---

# build_structured_message

```python
def build_structured_message(payload: ResumePayload) -> str
```

Serialize a resumed action into a structured user-message query string.

The message is tagged so downstream can recognize it as an A2UI action resume
rather than free-form user text.
