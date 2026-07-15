---
type: Wiki Entity
title: ScrubPolicy
id: class:parrot.security.redaction.ScrubPolicy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Policy controlling OutputScrubber behaviour.
---

# ScrubPolicy

Defined in [`parrot.security.redaction`](../summaries/mod:parrot.security.redaction.md).

```python
class ScrubPolicy
```

Policy controlling OutputScrubber behaviour.

Attributes:
    reason_tags: Emit reason-tagged markers (``***REDACTED:<reason>***``)
        instead of the plain ``[REDACTED]`` sentinel.
    audit_log: Record matched tag + tool name (never the secret value)
        via ``logging.getLogger(__name__)``.
    allowlist: Context allowlist — strings matching any of these exact
        substrings are left un-scrubbed (e.g. a ticket body containing
        the literal text ``token=`` as documentation).
    max_output_bytes: Inputs larger than this are scrubbed wholesale rather
        than per-pattern (defence-in-depth for giant blobs).
