---
type: Wiki Entity
title: OutputScrubber
id: class:parrot.security.redaction.OutputScrubber
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Policy-driven output scrubber for tool results and egress text.
---

# OutputScrubber

Defined in [`parrot.security.redaction`](../summaries/mod:parrot.security.redaction.md).

```python
class OutputScrubber
```

Policy-driven output scrubber for tool results and egress text.

Wraps the existing ``redact_text``/``redact_secrets`` logic and adds:
- Reason-tagged redaction markers (``***REDACTED:env_dump***``, …).
- Idempotency: re-scrubbing an already-scrubbed value is a no-op.
- Audit logging: tag + tool name only — the secret value is never logged.
- Allowlist awareness: callers can exempt known-safe substrings.
- Recursive structure traversal (dict / list / tuple / str).

Example:
    >>> scrubber = OutputScrubber(ScrubPolicy())
    >>> scrubber.scrub("PASSWORD=hunter2", tool_name="my_tool")
    '***REDACTED:secret_kv:tool=my_tool***'
    >>> scrubber.scrub({"token": "abc", "ok": "plain"}, tool_name="my_tool")
    {'token': '***REDACTED:secret_kv:tool=my_tool***', 'ok': 'plain'}

## Methods

- `def scrub(self, value: Any, tool_name: Optional[str]=None) -> Any` — Recursively scrub *value*, returning a sanitised copy.
