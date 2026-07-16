---
type: Wiki Entity
title: FileUploadHook
id: class:parrot.core.hooks.file_upload.FileUploadHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Exposes an HTTP POST/PUT endpoint that accepts file uploads.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# FileUploadHook

Defined in [`parrot.core.hooks.file_upload`](../summaries/mod:parrot.core.hooks.file_upload.md).

```python
class FileUploadHook(BaseHook)
```

Exposes an HTTP POST/PUT endpoint that accepts file uploads.

Validates MIME types and file names, saves files to a temporary
directory, fires a HookEvent, then cleans up.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
- `def setup_routes(self, app: Any) -> None`
