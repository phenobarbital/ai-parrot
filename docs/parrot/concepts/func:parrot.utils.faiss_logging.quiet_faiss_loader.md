---
type: Concept
title: quiet_faiss_loader()
id: func:parrot.utils.faiss_logging.quiet_faiss_loader
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raise the ``faiss`` logger to WARNING (or ``FAISS_LOG_LEVEL``). Idempotent.
---

# quiet_faiss_loader

```python
def quiet_faiss_loader() -> None
```

Raise the ``faiss`` logger to WARNING (or ``FAISS_LOG_LEVEL``). Idempotent.

Safe to call repeatedly and from multiple import sites — the first call
before ``import faiss`` wins; later calls just re-assert the same level.
