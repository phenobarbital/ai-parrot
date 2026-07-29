---
type: Concept
title: build_structured_message()
id: func:parrot.integrations.a2ui_resume.build_structured_message
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Serialize a resumed action into a structured user-message query string.
---

# build_structured_message

```python
def build_structured_message(action_payload: dict[str, Any]) -> str
```

Serialize a resumed action into a structured user-message query string.

Mirrors the web route (TASK-1735): tagged so downstream recognizes it as an A2UI
action resume rather than free-form user text.
