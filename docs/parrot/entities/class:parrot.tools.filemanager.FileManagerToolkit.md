---
type: Wiki Entity
title: FileManagerToolkit
id: class:parrot.tools.filemanager.FileManagerToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for AI agents to interact with file systems — preferred API.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# FileManagerToolkit

Defined in [`parrot.tools.filemanager`](../summaries/mod:parrot.tools.filemanager.md).

```python
class FileManagerToolkit(AbstractToolkit)
```

Toolkit for AI agents to interact with file systems — preferred API.

Exposes each file operation as a separate, focused tool with a minimal
schema.  LLMs no longer need to know about an ``operation`` dispatch field;
they simply call the right tool directly.

Tool names (with ``tool_prefix="fs"``):
  - ``fs_list_files``      — list files in a directory
  - ``fs_upload_file``     — upload a local file to storage
  - ``fs_download_file``   — download a file from storage
  - ``fs_copy_file``       — copy a file within storage
  - ``fs_delete_file``     — delete a file from storage
  - ``fs_file_exists``     — check whether a file exists
  - ``fs_get_file_url``    — get a URL to access a file
  - ``fs_get_file_metadata`` — fetch detailed file metadata
  - ``fs_create_file``     — create a new file with text content

Supported backends:
  - ``"fs"``   — local filesystem (sandboxed by default)
  - ``"temp"`` — temporary storage (auto-cleaned on exit)
  - ``"s3"``   — AWS S3 (requires aioboto3)
  - ``"gcs"``  — Google Cloud Storage (requires google-cloud-storage)

Example::

    toolkit = FileManagerToolkit(manager_type="fs")
    tools = toolkit.get_tools()   # returns 9 AbstractTool instances
    result = await toolkit.list_files(path="docs", pattern="*.md")

## Methods

- `async def list_files(self, path: str='', pattern: str='*') -> Dict[str, Any]` — List files in a directory on the configured storage backend.
- `async def upload_file(self, source_path: str, destination: Optional[str]=None, destination_name: Optional[str]=None) -> Dict[str, Any]` — Upload a local file to the configured storage backend.
- `async def download_file(self, path: str, destination: Optional[str]=None) -> Dict[str, Any]` — Download a file from the storage backend to the local filesystem.
- `async def copy_file(self, source: str, destination: str) -> Dict[str, Any]` — Copy a file within the configured storage backend.
- `async def delete_file(self, path: str) -> Dict[str, Any]` — Delete a file from the configured storage backend.
- `async def file_exists(self, path: str) -> Dict[str, Any]` — Check whether a file exists on the configured storage backend.
- `async def get_file_url(self, path: str, expiry_seconds: int=3600) -> Dict[str, Any]` — Get a URL to access a file on the configured storage backend.
- `async def get_file_metadata(self, path: str) -> Dict[str, Any]` — Retrieve detailed metadata for a file on the storage backend.
- `async def create_file(self, path: str, content: str, encoding: str='utf-8') -> Dict[str, Any]` — Create a new text file on the configured storage backend.
