---
type: Wiki Entity
title: ImageNotFoundError
id: class:parrot_tools.security.trivy.executor.ImageNotFoundError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when a `trivy image` target is not present on the local Docker daemon.
---

# ImageNotFoundError

Defined in [`parrot_tools.security.trivy.executor`](../summaries/mod:parrot_tools.security.trivy.executor.md).

```python
class ImageNotFoundError(RuntimeError)
```

Raised when a `trivy image` target is not present on the local Docker daemon.

Surfaced by the pre-flight check in `TrivyExecutor.scan_image` so the
caller gets a clear, actionable error before Trivy spends ~10 seconds
downloading the vulnerability DB only to fail on image resolution.
