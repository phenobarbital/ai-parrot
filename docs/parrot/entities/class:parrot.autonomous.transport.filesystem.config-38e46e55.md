---
type: Wiki Entity
title: FilesystemTransportConfig
id: class:parrot.autonomous.transport.filesystem.config.FilesystemTransportConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 configuration for the FilesystemTransport.
---

# FilesystemTransportConfig

Defined in [`parrot.autonomous.transport.filesystem.config`](../summaries/mod:parrot.autonomous.transport.filesystem.config.md).

```python
class FilesystemTransportConfig(BaseModel)
```

Pydantic v2 configuration for the FilesystemTransport.

All transport settings with sensible defaults. The ``root_dir`` is
automatically resolved to an absolute path via a field validator.

## Methods

- `def resolve_root_dir(self) -> 'FilesystemTransportConfig'` — Resolve root_dir to an absolute path.
