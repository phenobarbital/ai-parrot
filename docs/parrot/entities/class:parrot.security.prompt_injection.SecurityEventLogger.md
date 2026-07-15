---
type: Wiki Entity
title: SecurityEventLogger
id: class:parrot.security.prompt_injection.SecurityEventLogger
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Logs security events with session tracking.
---

# SecurityEventLogger

Defined in [`parrot.security.prompt_injection`](../summaries/mod:parrot.security.prompt_injection.md).

```python
class SecurityEventLogger
```

Logs security events with session tracking.

## Methods

- `async def log_injection_attempt(self, user_id: str, session_id: str, chatbot_id: str, threats: List[Dict[str, Any]], original_input: str, sanitized_input: str, metadata: Optional[Dict[str, Any]]=None)` — Log a detected prompt injection attempt.
