---
type: Concept
title: shutdown_traceloop()
id: func:parrot.observability.traceloop_integration.shutdown_traceloop
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Flush Traceloop and unregister native subscribers. Idempotent + defensive.
---

# shutdown_traceloop

```python
def shutdown_traceloop() -> None
```

Flush Traceloop and unregister native subscribers. Idempotent + defensive.

With ``disable_batch=True`` spans export eagerly and Traceloop also registers
its own atexit flush, so this is a best-effort belt-and-braces teardown.
