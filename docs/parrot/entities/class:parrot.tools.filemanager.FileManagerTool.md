---
type: Wiki Entity
title: FileManagerTool
id: class:parrot.tools.filemanager.FileManagerTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for AI agents to interact with file systems.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# FileManagerTool

Defined in [`parrot.tools.filemanager`](../summaries/mod:parrot.tools.filemanager.md).

```python
class FileManagerTool(AbstractTool)
```

Tool for AI agents to interact with file systems.

.. deprecated::
    ``FileManagerTool`` uses a multi-operation dispatch pattern (an ``operation``
    field that routes to one of nine sub-operations).  This flat schema confuses
    LLMs because every call must include the ``operation`` key and the parameters
    vary by operation.  Prefer :class:`FileManagerToolkit` instead — it exposes
    each operation as a separate, focused tool with a minimal, unambiguous schema.

Provides secure file operations across different storage backends:
- 'fs': Local filesystem
- 'temp': Temporary storage (auto-cleanup)
- 's3': AWS S3 buckets
- 'gcs': Google Cloud Storage

Usage Pattern:
The LLM must specify an 'operation' field to route to the correct action.
Each operation has specific required and optional fields.

Examples:
    List files: {"operation": "list", "path": "documents", "pattern": "*.pdf"}
    Upload: {"operation": "upload", "source_path": "/tmp/file.txt", "destination": "uploads"}
    Download: {"operation": "download", "path": "reports/summary.pdf", "destination": "/tmp/summary.pdf"}
    Get URL: {"operation": "get_url", "path": "shared/file.zip", "expiry_seconds": 7200}
    Create: {"operation": "create", "path": "output.txt", "content": "Hello, World!"}
